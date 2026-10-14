"""Mob-Cash kassa API klienti: v2 login + v1 mobile JSON-RPC metodlari.

Token Redis'da saqlanadi — bot, worker va userbot jarayonlari bitta sessiyadan
foydalanadi (har biri alohida login qilib, bir-birining sessiyasini bekor qilmasin).

Xatolar natija aniqligiga qarab ajratiladi:
* ``REJECTED``/``AUTH``/``NETWORK``/``CONFIG`` — amal Mob-Cash'da **bajarilmagan**,
  qayta urinish xavfsiz;
* ``UNKNOWN`` — so‘rov yuborilgan, lekin javob kelmadi (timeout/5xx). Pul harakati bo‘lgan
  bo‘lishi mumkin — avtomatik qayta yuborilmaydi, admin Mob-Cash panelida tekshiradi.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import httpx
from redis.exceptions import WatchError

from app.core.utils import utcnow

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from app.config import Config

log = logging.getLogger(__name__)

ACCEPT = "application/json, text/plain, */*"
LOGIN_LOCK_TTL = 60  # login so‘rovi timeout'idan uzun bo‘lishi kerak
LOGIN_LOCK_WAIT = 70


class MobCashErrorKind(StrEnum):
    CONFIG = "config"
    AUTH = "auth"
    REJECTED = "rejected"
    NETWORK = "network"
    UNKNOWN = "unknown"


class MobCashError(Exception):
    def __init__(self, message: str, kind: MobCashErrorKind) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind

    @property
    def outcome_unknown(self) -> bool:
        """So‘rov serverga yetib borgan, ammo natija noma’lum — qayta yuborish xavfli."""
        return self.kind == MobCashErrorKind.UNKNOWN


class _AuthExpired(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MobCashAuth:
    access_token: str
    session_id: str
    user_id: str
    expires_at: datetime | None
    cashbox: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "accessToken": self.access_token,
                "sessionID": self.session_id,
                "userID": self.user_id,
                "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
                "cashbox": self.cashbox,
            }
        )

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> MobCashAuth:
        if not isinstance(data, dict):
            raise ValueError("Login javobi obyekt bo‘lishi kerak")
        for key in ("accessToken", "sessionID", "userID"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Login javobida {key} yetishmayapti")
        cashbox = data.get("cashbox") or {}
        if not isinstance(cashbox, dict):
            raise ValueError("Login javobida cashbox noto‘g‘ri")
        return cls(
            access_token=data["accessToken"],
            session_id=data["sessionID"],
            user_id=data["userID"],
            expires_at=_parse_dt(data.get("expiresAt")),
            cashbox=cashbox,
        )

    def fresh(self, margin: timedelta = timedelta(seconds=60)) -> bool:
        return self.expires_at is None or self.expires_at - margin > utcnow()


@dataclass(frozen=True, slots=True)
class CashboxInfo:
    code: str
    currency_id: str
    is_deposit: bool
    is_withdrawal: bool
    expires_at: datetime | None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _to_decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
        if not amount.is_finite():
            raise ValueError("Summa chekli bo‘lishi kerak")
        return amount
    except (InvalidOperation, ValueError) as exc:
        raise MobCashError(
            f"Mob-Cash noto‘g‘ri summa qaytardi: {value!r}", MobCashErrorKind.REJECTED
        ) from exc


def _json_number(amount: Decimal) -> int | float:
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _validate_amount(amount: Decimal) -> None:
    # API'ga NaN/Infinity, manfiy yoki aniqligi yo‘qoladigan qiymat yuborilmasin.
    if (
        not isinstance(amount, Decimal)
        or not amount.is_finite()
        or amount <= 0
        or amount > Decimal("1000000000000")
        or amount != amount.quantize(Decimal("0.01"))
    ):
        raise MobCashError(
            "Summa musbat va ko‘pi bilan 2 kasrli bo‘lsin", MobCashErrorKind.REJECTED
        )


def _error_message(data: Any) -> str:
    """Mob-Cash xato javobidan o‘qiladigan matn (JSON-RPC, ogen yoki oddiy matn)."""
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("data") or err.get("code") or err)[:300]
        if err:
            return str(err)[:300]
        if data.get("message"):
            return str(data["message"])[:300]
    if isinstance(data, str) and data.strip():
        return data.strip()[:300]
    return "noma’lum xato"


class MobCashClient:
    @property
    def _identity(self) -> str:
        # Token kassa+login ga bog‘lanadi: kassa almashtirilganda boshqa jarayon (hali eski
        # ma’lumot bilan ishlayotgan) yozgan eski kassa tokeni yangi kassa uchun ishlatilmasin.
        identity = json.dumps(
            [self.auth_url, self.api_url, self.cashbox_code, self.login_name, self._password]
        )
        return hashlib.sha256(identity.encode()).hexdigest()

    @property
    def AUTH_KEY(self) -> str:
        return f"mobcash:auth:v2:{self._identity}"

    @property
    def LOCK_KEY(self) -> str:
        return f"mobcash:auth:lock:{self._identity}"

    def __init__(
        self,
        *,
        redis: Redis,
        cashbox_code: int,
        login: str,
        password: str,
        auth_url: str,
        api_url: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.redis = redis
        self.cashbox_code = cashbox_code
        self.login_name = login
        self._password = password
        self.auth_url = auth_url.rstrip("/")
        self.api_url = api_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            transport=transport,
            headers={"Accept": ACCEPT, "Content-Type": "application/json"},
        )
        self._local_lock = asyncio.Lock()
        self._login_lock_ttl = max(LOGIN_LOCK_TTL, int(timeout * 4) + 10)
        self._rpc_id = 0

    @classmethod
    def from_config(cls, config: Config, redis: Redis) -> MobCashClient:
        return cls(
            redis=redis,
            cashbox_code=config.mobcash_cashbox_code,
            login=config.mobcash_login,
            password=config.mobcash_password.get_secret_value(),
            auth_url=config.mobcash_auth_url,
            api_url=config.mobcash_api_url,
            timeout=float(config.mobcash_timeout_seconds),
        )

    @property
    def configured(self) -> bool:
        return bool(self.cashbox_code and self.login_name and self._password)

    async def set_credentials(self, cashbox_code: int, login: str, password: str) -> None:
        """Admin paneldagi sozlamalardan kelgan ma’lumotlarni qo‘llaydi.

        Qiymat o‘zgargan bo‘lsa eski token bekor qilinadi — keyingi so‘rovda yangi login.
        """
        if (self.cashbox_code, self.login_name, self._password) == (cashbox_code, login, password):
            return
        self.cashbox_code = cashbox_code
        self.login_name = login
        self._password = password
        await self.invalidate()
        log.info("Mob-Cash kassa ma’lumotlari yangilandi (kassa=%s)", cashbox_code or "—")

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ HTTP
    async def _post(
        self, url: str, payload: dict[str, Any], token: str | None = None
    ) -> tuple[int, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            resp = await self._http.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise MobCashError(
                "Mob-Cash serveriga ulanib bo‘lmadi", MobCashErrorKind.NETWORK
            ) from exc
        except httpx.TimeoutException as exc:
            raise MobCashError(
                "Mob-Cash serveri belgilangan vaqtda javob bermadi", MobCashErrorKind.UNKNOWN
            ) from exc
        except httpx.HTTPError as exc:
            raise MobCashError(f"Tarmoq xatosi: {exc}", MobCashErrorKind.UNKNOWN) from exc
        try:
            data: Any = resp.json()
        except ValueError:
            data = resp.text
        return resp.status_code, data

    # ------------------------------------------------------------------ avtorizatsiya
    async def _cached_auth(self) -> MobCashAuth | None:
        try:
            raw = await self.redis.get(self.AUTH_KEY)
        except Exception:
            log.warning("Mob-Cash token keshini o‘qib bo‘lmadi", exc_info=True)
            return None
        if not raw:
            return None
        try:
            return MobCashAuth.from_response(json.loads(raw))
        except (ValueError, KeyError, TypeError):
            return None

    async def _store_auth(self, auth: MobCashAuth) -> None:
        ttl = 30 * 60
        if auth.expires_at is not None:
            ttl = int((auth.expires_at - utcnow()).total_seconds()) - 60
        if ttl <= 0:
            return
        try:
            await self.redis.set(self.AUTH_KEY, auth.to_json(), ex=ttl)
        except Exception:
            log.warning("Mob-Cash tokenini keshga yozib bo‘lmadi", exc_info=True)

    async def invalidate(self) -> None:
        try:
            await self.redis.delete(self.AUTH_KEY)
        except Exception:
            log.warning("Mob-Cash token keshini tozalab bo‘lmadi", exc_info=True)

    async def _do_login(self) -> MobCashAuth:
        if not self.configured:
            raise MobCashError(
                "Mob-Cash sozlanmagan — admin panelda «🏦 Mob-Cash → 🔌 Kassa ulash» orqali "
                "kassa kodi, login va parolni kiriting",
                MobCashErrorKind.CONFIG,
            )
        try:
            status, data = await self._post(
                f"{self.auth_url}/login",
                {
                    "cashboxCode": self.cashbox_code,
                    "login": self.login_name,
                    "password": self._password,
                },
            )
        except MobCashError as exc:
            # Login timeout'i pul harakati noaniqligini anglatmaydi: hali RPC yuborilmadi.
            if exc.outcome_unknown:
                raise MobCashError(exc.message, MobCashErrorKind.NETWORK) from exc
            raise
        if status == 200:
            try:
                auth = MobCashAuth.from_response(data)
                if auth.expires_at is not None and auth.expires_at <= utcnow():
                    raise ValueError("Yangi tokenning muddati allaqachon tugagan")
            except (ValueError, TypeError, KeyError) as exc:
                raise MobCashError(
                    "Mob-Cash login javobi to‘liq emas yoki muddati noto‘g‘ri",
                    MobCashErrorKind.AUTH,
                ) from exc
            log.info("Mob-Cash login: kassa=%s", self.cashbox_code)
            return auth
        if status in (401, 403):
            raise MobCashError(
                f"Mob-Cash login rad etildi: {_error_message(data)}", MobCashErrorKind.AUTH
            )
        raise MobCashError(
            f"Mob-Cash login xatosi (HTTP {status}): {_error_message(data)}",
            MobCashErrorKind.AUTH if 400 <= status < 500 else MobCashErrorKind.NETWORK,
        )

    async def login(self, *, stale_token: str | None = None) -> MobCashAuth:
        """Amaldagi tokenni qaytaradi; kerak bo‘lsa yangisini oladi.

        `stale_token` — server rad etgan token. Keshda boshqa (yangiroq) token bo‘lsa,
        qayta login qilinmaydi: boshqa jarayon allaqachon yangilagan.
        """
        cached = await self._cached_auth()
        if cached and cached.fresh() and cached.access_token != stale_token:
            return cached
        async with self._local_lock:
            # Jarayonlararo lock: SET NX (Lua'siz — `memory://` fakeredis'da ham ishlaydi).
            token = secrets.token_hex(8)
            deadline = time.monotonic() + LOGIN_LOCK_WAIT
            acquired = False
            while True:
                cached = await self._cached_auth()
                if cached and cached.fresh() and cached.access_token != stale_token:
                    return cached
                try:
                    acquired = bool(
                        await self.redis.set(self.LOCK_KEY, token, nx=True, ex=self._login_lock_ttl)
                    )
                except Exception as exc:
                    raise MobCashError(
                        "Mob-Cash sessiya qulfi ishlamadi — Redis ulanishini tekshiring",
                        MobCashErrorKind.NETWORK,
                    ) from exc
                if acquired:
                    break
                if time.monotonic() > deadline:
                    raise MobCashError(
                        "Mob-Cash sessiyasini boshqa jarayon yangilayapti",
                        MobCashErrorKind.NETWORK,
                    )
                await asyncio.sleep(0.25)
            try:
                auth = await self._do_login()
                await self._store_auth(auth)
                return auth
            finally:
                if acquired:
                    await self._release_lock(token)

    async def _release_lock(self, token: str) -> None:
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(self.LOCK_KEY)
                current = await pipe.get(self.LOCK_KEY)
                if isinstance(current, bytes):
                    current = current.decode()
                if current == token:
                    pipe.multi()
                    pipe.delete(self.LOCK_KEY)
                    await pipe.execute()
        except WatchError:
            pass  # Qulf egasi o‘zgargan: yangi egasining qulfini o‘chirmaymiz.
        except Exception:
            log.debug("Mob-Cash login lockini bo‘shatib bo‘lmadi", exc_info=True)

    # ------------------------------------------------------------------ bir martalik HASH
    @property
    def _origin(self) -> str:
        return self.auth_url.split("/api/", 1)[0]

    async def raw_login(self, cashbox_code: int, login: str, password: str) -> MobCashAuth:
        """Keshga tegmasdan berilgan kredensiallar bilan bir marta login qiladi.

        Faqat bir martalik HASH oqimida ishlatiladi: natija Redis'ga yozilmaydi, demak
        asosiy sessiya va token keshi buzilmaydi.
        """
        status, data = await self._post(
            f"{self.auth_url}/login",
            {"cashboxCode": cashbox_code, "login": login, "password": password},
        )
        if status == 200 and isinstance(data, dict) and data.get("accessToken"):
            return MobCashAuth.from_response(data)
        if status in (401, 403):
            raise MobCashError(
                f"Mob-Cash login rad etildi: {_error_message(data)}", MobCashErrorKind.AUTH
            )
        raise MobCashError(
            f"Mob-Cash login xatosi (HTTP {status}): {_error_message(data)}",
            MobCashErrorKind.AUTH if 400 <= status < 500 else MobCashErrorKind.NETWORK,
        )

    async def one_time_login(self, token: str) -> dict[str, str]:
        """Bir martalik HASH orqali vaqtinchalik kredensiallarni oladi (zkassa oqimi).

        Token faqat bir marta ishlaydi. Javobdagi parol doimiy emas — `raw_login` bilan
        kirib, `set_password` orqali yangi doimiy parol o‘rnatilishi shart.
        """
        status, data = await self._post(
            f"{self._origin}/api/v2/public/cashier/one-time-login", {"token": token}
        )
        entry = data[0] if isinstance(data, list) and data else data
        creds = entry if isinstance(entry, dict) else {}
        if status == 200 and creds.get("login") and creds.get("password"):
            code = creds.get("cashboxCode", creds.get("cashbox_code", creds.get("code")))
            return {
                "login": str(creds["login"]),
                "password": str(creds["password"]),
                "cashbox_code": str(code or ""),
            }
        if 400 <= status < 500:
            raise MobCashError(
                f"Bir martalik HASH rad etildi: {_error_message(data)}", MobCashErrorKind.AUTH
            )
        raise MobCashError(
            f"Mob-Cash server xatosi (HTTP {status}): {_error_message(data)}",
            MobCashErrorKind.UNKNOWN,
        )

    async def set_password(self, new_password: str, access_token: str) -> None:
        """Vaqtinchalik parol bilan kirgandan keyin doimiy parolni o‘rnatadi."""
        status, data = await self._post(
            f"{self._origin}/api/v1/public/hydra/password",
            {"newPassword": new_password},
            token=access_token,
        )
        if status in (200, 201, 204):
            return
        if 400 <= status < 500:
            raise MobCashError(
                f"Yangi parol qabul qilinmadi: {_error_message(data)}", MobCashErrorKind.REJECTED
            )
        raise MobCashError(
            f"Mob-Cash server xatosi (HTTP {status}): {_error_message(data)}",
            MobCashErrorKind.UNKNOWN,
        )

    async def set_persistent_password(
        self, cashbox_code: int, login: str, temp_password: str, new_password: str
    ) -> None:
        """Bir martalik HASH oqimining yakuniy qadami.

        Vaqtinchalik parol bilan kiradi, doimiy parolni o‘rnatadi va yangi parol bilan
        qayta kirib tekshiradi. Hech narsa keshga yozilmaydi — doimiy parol bilan keyingi
        login oqimning o‘zi (settings/kantora saqlashi) to‘g‘riligini ko‘rsatadi.
        """
        auth = await self.raw_login(cashbox_code, login, temp_password)
        await self.set_password(new_password, auth.access_token)
        await self.raw_login(cashbox_code, login, new_password)

    # ------------------------------------------------------------------ JSON-RPC
    async def _rpc_once(self, method: str, auth: MobCashAuth, params: dict[str, Any]) -> Any:
        capability = {"deposit": "isDeposit", "withdrawal": "isWithdrawal"}.get(method)
        if capability and auth.cashbox.get(capability) is False:
            raise MobCashError("Kassada bu amal o‘chirilgan", MobCashErrorKind.REJECTED)
        if method == "deposit":
            # Har bir haqiqiy urinish oldidan, aynan shu sessiyada tekshiramiz.
            # Token yangilanganda va refund'da ham bu qadam tashlab ketilmaydi.
            try:
                payer = await self._rpc_once(
                    "payerNickname",
                    auth,
                    {"payerID": params["deposit"]["payerID"], **self._session(auth)},
                )
            except MobCashError as exc:
                if exc.outcome_unknown:
                    raise MobCashError(
                        "Depozit yuborilmadi: akkauntni tekshirib bo‘lmadi",
                        MobCashErrorKind.NETWORK,
                    ) from exc
                raise
            if not payer.get("nickname"):
                raise MobCashError("Akkaunt topilmadi", MobCashErrorKind.REJECTED)
        self._rpc_id += 1
        request_id = self._rpc_id
        status, data = await self._post(
            f"{self.api_url}/{method}",
            {"id": request_id, "jsonrpc": "2.0", "params": params},
            token=auth.access_token,
        )
        if status in (401, 403):
            raise _AuthExpired
        if status >= 500 or status == 408:
            raise MobCashError(
                f"Mob-Cash server xatosi (HTTP {status}): {_error_message(data)}",
                MobCashErrorKind.UNKNOWN,
            )
        if status >= 400:
            raise MobCashError(_error_message(data), MobCashErrorKind.REJECTED)
        if not 200 <= status < 300:
            raise MobCashError("Mob-Cash kutilmagan HTTP javob qaytardi", MobCashErrorKind.UNKNOWN)
        entry = data
        if isinstance(data, list):
            # Berilgan hujjatda bitta javobning id'si so‘rov id'sidan farq qiladi.
            # Bitta elementni qabul qilamiz; batch javobda aynan kerakli id tanlanadi.
            candidates = (
                data
                if len(data) == 1
                else [
                    item for item in data if isinstance(item, dict) and item.get("id") == request_id
                ]
            )
            entry = candidates[0] if len(candidates) == 1 else None
        if not isinstance(entry, dict) or ("error" in entry and "result" in entry):
            raise MobCashError("Mob-Cash JSON-RPC javobi noto‘g‘ri", MobCashErrorKind.UNKNOWN)
        if entry.get("error") is not None:
            raise MobCashError(_error_message(entry), MobCashErrorKind.REJECTED)
        if not isinstance(entry.get("result"), dict):
            raise MobCashError("Mob-Cash javobida result yo‘q", MobCashErrorKind.UNKNOWN)
        return entry["result"]

    async def _rpc(self, method: str, build_params: Callable[[MobCashAuth], dict[str, Any]]) -> Any:
        auth = await self.login()
        try:
            return await self._rpc_once(method, auth, build_params(auth))
        except _AuthExpired:
            # 401/403 — so‘rov avtorizatsiyada rad etilgan, demak bajarilmagan: xavfsiz takror.
            auth = await self.login(stale_token=auth.access_token)
            try:
                return await self._rpc_once(method, auth, build_params(auth))
            except _AuthExpired as exc:
                await self.invalidate()
                raise MobCashError(
                    "Mob-Cash tokeni qabul qilinmadi. Kassa ma’lumotlarini tekshiring.",
                    MobCashErrorKind.AUTH,
                ) from exc

    @staticmethod
    def _session(auth: MobCashAuth) -> dict[str, str]:
        return {"sessionID": auth.session_id, "userID": auth.user_id}

    # ------------------------------------------------------------------ metodlar
    async def check_connection(self) -> CashboxInfo:
        auth = await self.login()
        cb = auth.cashbox or {}
        return CashboxInfo(
            code=str(cb.get("code") or self.cashbox_code),
            currency_id=str(cb.get("currencyID") or "—"),
            is_deposit=bool(cb.get("isDeposit", True)),
            is_withdrawal=bool(cb.get("isWithdrawal", True)),
            expires_at=auth.expires_at,
        )

    async def payer_nickname(self, payer_id: str) -> str:
        """2-metod: o‘yinchi akkauntini tekshirish. Topilmasa MobCashError(REJECTED)."""
        result = await self._rpc(
            "payerNickname", lambda a: {"payerID": payer_id, **self._session(a)}
        )
        nickname = result.get("nickname") if isinstance(result, dict) else None
        if not nickname:
            raise MobCashError("Akkaunt topilmadi", MobCashErrorKind.REJECTED)
        return str(nickname)

    async def deposit(self, payer_id: str, amount: Decimal) -> dict[str, Any]:
        """2 → 3-metod: akkauntni tekshirish, keyin pul kiritish (refund uchun ham)."""
        _validate_amount(amount)
        result = await self._rpc(
            "deposit",
            lambda a: {
                "deposit": {"amount": format(amount.normalize(), "f"), "payerID": payer_id},
                **self._session(a),
            },
        )
        return self._check_success(result, "Depozit")

    async def get_withdrawal_amount(self, payer_id: str, code: str) -> Decimal:
        """4-metod: yechish kodi bo‘yicha summani olish (pul hali harakatlanmaydi)."""
        result = await self._rpc(
            "getWithdrawalAmount",
            lambda a: {
                **self._session(a),
                "withdraw": {"payerID": payer_id, "withdrawalCode": code},
            },
        )
        raw = result.get("amount") if isinstance(result, dict) else None
        if raw in (None, ""):
            raise MobCashError("Yechish arizasi topilmadi", MobCashErrorKind.REJECTED)
        amount = _to_decimal(raw)
        if amount <= 0:
            raise MobCashError("Yechish summasi noto‘g‘ri", MobCashErrorKind.REJECTED)
        return amount

    async def withdrawal(self, payer_id: str, code: str, amount: Decimal) -> dict[str, Any]:
        """5-metod: yechishni bajarish — pul o‘yinchi hisobidan kassaga o‘tadi."""
        _validate_amount(amount)
        result = await self._rpc(
            "withdrawal",
            lambda a: {
                **self._session(a),
                "withdraw": {
                    "amount": _json_number(amount),
                    "payerID": payer_id,
                    "withdrawalCode": code,
                },
            },
        )
        return self._check_success(result, "Yechish")

    @staticmethod
    def _check_success(result: Any, label: str) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise MobCashError(f"{label}: kutilmagan javob", MobCashErrorKind.UNKNOWN)
        if result.get("success") is False:
            raise MobCashError(
                f"{label} rad etildi: {_error_message(result)}", MobCashErrorKind.REJECTED
            )
        if result.get("success") is not True:
            raise MobCashError(
                f"{label}: muvaffaqiyat tasdiqlanmagan — panelda tekshiring",
                MobCashErrorKind.UNKNOWN,
            )
        return result

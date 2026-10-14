"""1xBet Cashdesk Bot API (partners.servcul.com/CashdeskBotAPI) klienti.

G&S «Mobcash» kassalari shu tizim orqali ishlaydi (admin.mob-cash.com emas!). Rasmiy
hujjatga ko'ra 4 metod bor: balans, o'yinchini topish, depozit (Deposit/{id}/Add) va
yechish (Deposit/{id}/Payout). Imzo formulalari va endpointlar jonli tekshirilgan
(2026-10-14; depozit/yechish sign'lari qabul qilingan). Diqqat: summa JSON tanada va
MD5 imzoda BIR XIL matnda bo'lishi shart (server o'zi shunday qayta hisoblaydi).

Maxfiy qiymatlar (hash, kassir paroli) faqat imzo hisoblash uchun ishlatiladi — logga
yozilmaydi. Xatolar MobCashError sifatida qaytariladi (kind bilan) — admin UI shakli bir xil.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.mobcash.client import (
    MobCashError,
    MobCashErrorKind,
    _to_decimal,
    _validate_amount,
)

log = logging.getLogger(__name__)

_DT_FORMAT = "%Y.%m.%d %H:%M:%S"
_LANG = "uz"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _dt_now() -> str:
    return datetime.now(UTC).strftime(_DT_FORMAT)


def _sum_text(amount: Decimal) -> str:
    """Summaning JSON'dagi va imzodagi yagona matn ko'rinishi (ortiqcha nolsiz)."""
    return format(amount.normalize(), "f")


@dataclass(frozen=True, slots=True)
class CashdeskInfo:
    """check_connection() natijasi — CashboxInfo bilan bir xil maydonlar + balans."""

    code: str
    currency_id: str
    is_deposit: bool
    is_withdrawal: bool
    expires_at: datetime | None
    balance: Decimal | None = None
    limit: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CashdeskUser:
    user_id: str
    name: str
    currency_id: str


def _parse_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).replace(" ", "").replace(",", "."))
        if amount.is_finite():
            return amount
    except InvalidOperation:
        pass
    raise MobCashError(
        f"Cashdesk noto'g'ri summa qaytardi: {value!r}", MobCashErrorKind.UNKNOWN
    ) from None


class CashdeskClient:
    """`cashdeskId + cashierPass + hash` bilan imzolanadigan HTTP klient (sessiyasiz)."""

    # Bu API'da kod bo'yicha summani oldindan ko'rish metodi yo'q — summa Payout
    # javobida keladi. Servis qatlami shunga qarab boshqacha ishlaydi.
    supports_amount_preview = False

    def __init__(
        self,
        *,
        cashdesk_id: int,
        cashier_pass: str,
        hash_key: str,
        api_url: str,
        timeout: float = 20.0,
    ) -> None:
        self.cashdesk_id = cashdesk_id
        self._cashier_pass = cashier_pass
        self._hash_key = hash_key
        self._base = api_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0))
        )

    @property
    def configured(self) -> bool:
        return bool(self.cashdesk_id and self._cashier_pass and self._hash_key)

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ so'rov
    def _sign(self, inner: str, outer: str) -> str:
        return _sha256(_sha256(inner) + _md5(outer))

    async def _send(self, request: httpx.Request) -> Any:
        try:
            resp = await self._http.send(request)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise MobCashError(f"Serverga ulanib bo'lmadi: {exc}", MobCashErrorKind.NETWORK) from exc
        except httpx.TimeoutException as exc:
            raise MobCashError("Server javob bermadi (timeout).", MobCashErrorKind.NETWORK) from exc
        except httpx.HTTPError as exc:
            raise MobCashError(f"Tarmoq xatosi: {exc}", MobCashErrorKind.NETWORK) from exc
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code >= 500:
            raise MobCashError(f"Server xatosi (HTTP {resp.status_code}).", MobCashErrorKind.UNKNOWN)
        if resp.status_code in (401, 403):
            raise MobCashError(
                self._error_text(data) or "Ruxsat yo'q — kalit yoki kassir paroli noto'g'ri.",
                MobCashErrorKind.AUTH,
            )
        if resp.status_code != 200:
            raise MobCashError(
                self._error_text(data) or f"So'rov rad etildi (HTTP {resp.status_code}).",
                MobCashErrorKind.REJECTED,
            )
        return data

    async def _get(self, path: str, params: dict[str, str], sign_inner: str, sign_outer: str) -> Any:
        request = self._http.build_request(
            "GET",
            f"{self._base}{path}",
            params=params,
            headers={"Accept": "application/json", "sign": self._sign(sign_inner, sign_outer)},
        )
        return await self._send(request)

    async def _post(self, path: str, body: str, sign_inner: str, sign_outer: str) -> Any:
        request = self._http.build_request(
            "POST",
            f"{self._base}{path}",
            content=body.encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "sign": self._sign(sign_inner, sign_outer),
            },
        )
        return await self._send(request)

    @staticmethod
    def _error_text(data: Any) -> str:
        if isinstance(data, dict):
            fields = data.get("invalidFields")
            if isinstance(fields, list) and fields:
                parts = [
                    f"{f.get('key', '?')}: {f.get('error', '?')}"
                    for f in fields
                    if isinstance(f, dict)
                ]
                if parts:
                    return "; ".join(parts)
            for key in ("message", "title", "Message"):
                if data.get(key):
                    return str(data[key])
        return ""

    @staticmethod
    def _uid(user_id: str | int) -> str:
        uid = str(user_id).strip()
        if not uid.isdigit():
            raise MobCashError(
                "O'yinchi ID faqat raqamlardan iborat bo'lishi kerak.", MobCashErrorKind.REJECTED
            )
        return uid

    @staticmethod
    def _money_result(data: Any, what: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise MobCashError(
                f"{what}: kutilmagan javob — natija noma'lum.", MobCashErrorKind.UNKNOWN
            )
        success = data.get("Success", data.get("success"))
        if success is False:
            raise MobCashError(
                f"{what}: {data.get('Message') or data.get('message') or 'rad etildi'}",
                MobCashErrorKind.REJECTED,
            )
        if success is None:
            # success maydoni yo'q — pul harakati bo'lgan-bo'lmaganini bilib bo'lmaydi.
            raise MobCashError(
                f"{what}: javobda success yo'q — natija noma'lum.", MobCashErrorKind.UNKNOWN
            )
        result: dict[str, Any] = {"success": bool(success)}
        for key in ("Summa", "summa", "Sum", "Amount"):
            if data.get(key) is not None:
                result["amount"] = data[key]
                break
        return result

    # ------------------------------------------------------------------ metodlar
    async def balance(self) -> tuple[Decimal, Decimal]:
        """Kassa balansi: GET /Cashdesk/{id}/Balance (dt — UTC ishlaydi)."""
        dt = _dt_now()
        data = await self._get(
            f"/Cashdesk/{self.cashdesk_id}/Balance",
            params={"confirm": _md5(f"{self.cashdesk_id}:{self._hash_key}"), "dt": dt},
            sign_inner=f"hash={self._hash_key}&cashierpass={self._cashier_pass}&dt={dt}",
            sign_outer=f"dt={dt}&cashierpass={self._cashier_pass}&cashdeskid={self.cashdesk_id}",
        )
        if not isinstance(data, dict) or "Balance" not in data:
            raise MobCashError(
                "Cashdesk balans javobi kutilgan shaklda emas.", MobCashErrorKind.UNKNOWN
            )
        return _parse_amount(data["Balance"]), _parse_amount(data.get("Limit") or 0)

    async def find_user(self, user_id: str | int) -> CashdeskUser:
        """O'yinchini tekshirish: GET /Users/{userId}."""
        uid = self._uid(user_id)
        data = await self._get(
            f"/Users/{uid}",
            params={
                "confirm": _md5(f"{uid}:{self._hash_key}"),
                "cashdeskId": str(self.cashdesk_id),
            },
            sign_inner=f"hash={self._hash_key}&userid={uid}&cashdeskid={self.cashdesk_id}",
            sign_outer=f"userid={uid}&cashierpass={self._cashier_pass}&hash={self._hash_key}",
        )
        if not isinstance(data, dict) or not data.get("UserId"):
            raise MobCashError("O'yinchi topilmadi.", MobCashErrorKind.REJECTED)
        return CashdeskUser(
            user_id=str(data["UserId"]),
            name=str(data.get("Name") or ""),
            currency_id=str(data.get("CurrencyId") or "—"),
        )

    async def payer_nickname(self, payer_id: str) -> str:
        user = await self.find_user(payer_id)
        return user.name or str(payer_id)

    async def deposit(self, payer_id: str, amount: Decimal) -> dict[str, Any]:
        """Depozit: POST /Deposit/{userId}/Add. Pul harakatlanadi.

        Imzo (hujjat 3.1): SHA256(SHA256('hash&lng&userid') + MD5('summa&cashierpass&cashdeskid')).
        Summa matni tanada ham, imzoda ham bir xil bo'lishi shart — server aynan shu
        matndan qayta hisoblaydi (jonli tasdiqlangan)."""
        uid = self._uid(payer_id)
        _validate_amount(amount)
        sum_text = _sum_text(amount)
        body = '{"cashdeskId":%d,"lng":"%s","summa":%s,"confirm":"%s"}' % (
            self.cashdesk_id, _LANG, sum_text, _md5(f"{uid}:{self._hash_key}"),
        )
        data = await self._post(
            f"/Deposit/{uid}/Add",
            body,
            sign_inner=f"hash={self._hash_key}&lng={_LANG}&userid={uid}",
            sign_outer=f"summa={sum_text}&cashierpass={self._cashier_pass}&cashdeskid={self.cashdesk_id}",
        )
        return self._money_result(data, "Depozit")

    async def get_withdrawal_amount(self, payer_id: str, code: str) -> Decimal:
        """Bu API'da kod bo'yicha oldindan summa ko'rish yo'q — summa Payout'da keladi."""
        raise MobCashError(
            "Bu kassada (1xBet Cashdesk) kod summasini oldindan ko'rish yo'q — "
            "summa yechish bajarilganda aniqlanadi.",
            MobCashErrorKind.CONFIG,
        )

    async def withdrawal(self, payer_id: str, code: str, amount: Decimal | None = None) -> dict[str, Any]:
        """Yechish: POST /Deposit/{userId}/Payout. Pul harakatlanadi.

        Imzo (hujjat 4.1): SHA256(SHA256('hash&lng&userid') + MD5('code&cashierpass&cashdeskid')).
        `amount` so'rovga kirmaydi (summani server kod bo'yicha o'zi hisoblaydi) — faqat
        javobdagi summa bilan solishtirish uchun ishlatiladi."""
        uid = self._uid(payer_id)
        code = code.strip()
        if not code or len(code) > 32:
            raise MobCashError("To'lov kodi 1–32 belgidan iborat bo'lsin.", MobCashErrorKind.REJECTED)
        body = '{"cashdeskId":%d,"lng":"%s","code":%s,"confirm":"%s"}' % (
            self.cashdesk_id, _LANG, json.dumps(code), _md5(f"{uid}:{self._hash_key}"),
        )
        data = await self._post(
            f"/Deposit/{uid}/Payout",
            body,
            sign_inner=f"hash={self._hash_key}&lng={_LANG}&userid={uid}",
            sign_outer=f"code={code}&cashierpass={self._cashier_pass}&cashdeskid={self.cashdesk_id}",
        )
        result = self._money_result(data, "Yechish")
        if amount is not None and result.get("amount") is not None:
            actual = _to_decimal(result["amount"])
            if actual != amount:
                log.warning("Cashdesk payout summasi farq qildi: kutilgan=%s javob=%s", amount, actual)
        return result

    async def check_connection(self) -> CashdeskInfo:
        balance, limit = await self.balance()
        return CashdeskInfo(
            code=str(self.cashdesk_id),
            # Balans javobida valyuta maydoni yo'q — G&S kassalari so'mda ishlaydi (agent bilan bir xil).
            currency_id="UZS",
            is_deposit=True,
            is_withdrawal=True,
            expires_at=None,
            balance=balance,
            limit=limit,
        )

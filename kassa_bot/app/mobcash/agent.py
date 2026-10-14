"""TeamCash / MELLO CASH agent API klienti (yangi arxitektura, cashdbcore).

TeamCash ilovasining backend'i (APK reverse + jonli probe bilan isbotlangan,
2026-10-10). Eski servul CashdeskBotAPI'dan farqli — bu yerda depozit va yechish
endpointlari bor:

    POST /agentservice/authorization/auth            {Login, Password} → JWT
    POST /agentservice/authorization/switchcashdesk  X-Auth: Bearer <jwt>, {cashId}
    GET  /cashdbcore/GetBalance                      → {Balance, ImperiumBalance}
    POST /cashdbcore/User/Get                        {UserId} → o'yinchi (sessiya konteksti)
    POST /cashdbcore/Deposit/Add                     {Amount} → depozit (pul harakatlanadi)
    GET  /cashdbcore/Deposit/FindPayoutByCode?code=  → {UserId, Success, Message}
    POST /cashdbcore/PrepaidBalance/Token            {} → joriy user uchun UserToken JWT
    GET  /cashdbcore/Deposit/CheckCodePayout         ?code=&UserToken=
    POST /cashdbcore/Deposit/Payout                  {Code, UserToken} → yechish

Oqim ilovadagidey: depozit = User/Get → Deposit/Add; yechish = FindPayoutByCode →
User/Get (kontekst) → PrepaidBalance/Token → CheckCodePayout → Payout.

Maxfiy qiymatlar (parol) faqat login so'rovida ishlatiladi — logga yozilmaydi.
Xatolar MobCashError bilan bir xil kind'larda (MobCashErrorKind) — servis qat'lamida
xatolarni ko'rsatish shakli bir xil qoladi.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.mobcash.cashdesk import CashdeskInfo
from app.mobcash.client import (
    MobCashError,
    MobCashErrorKind,
    _to_decimal,
    _validate_amount,
)

log = logging.getLogger(__name__)

_TOKEN_TTL_MARGIN = 60  # sekund — shuncha vaqt qolsa token yangilanadi
_MIRROR_URL = "https://tinyurl.com/newTeamCash"  # mirror aylanib qolsa qayta ochiladi
_UNSHORTEN = "https://unshorten.me/s/"


def _jwt_exp(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        exp = data.get("exp")
        return float(exp) if exp else None
    except (ValueError, IndexError, TypeError):
        return None


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
        for key in ("Message", "message", "title"):
            if data.get(key):
                return str(data[key])
    return ""


class AgentClient:
    """Agent login + cashdesk tanlash orqali ishlaydigan cashdbcore klienti."""

    def __init__(
        self,
        *,
        login: str,
        password: str,
        cashdesk_id: int,
        api_base: str,
        timeout: float = 30.0,
        whence: str = "2",
        language: str = "uz",
    ) -> None:
        self.login_name = login
        self._password = password
        self.cashdesk_id = cashdesk_id
        self._base = api_base.rstrip("/")
        self._app_guid = str(uuid.uuid4())
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Whence": whence,
                "X-Language": language,
                "AppGuid": self._app_guid,
                "MobModel": "Android",
            },
        )
        self._agent_token: str | None = None
        self._agent_exp: float = 0.0
        self._desk_token: str | None = None
        self._desk_exp: float = 0.0
        self._mirror_tried = False
        self._old_base: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.login_name and self._password and self.cashdesk_id)

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ HTTP
    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            if await self._try_mirror():
                return await self._http.request(method, url.replace(self._old_base or "", self._base, 1), **kwargs)
            raise MobCashError(f"Serverga ulanib bo'lmadi: {exc}", MobCashErrorKind.NETWORK) from exc
        except httpx.TimeoutException as exc:
            raise MobCashError("Server javob bermadi (timeout).", MobCashErrorKind.UNKNOWN) from exc
        except httpx.HTTPError as exc:
            raise MobCashError(f"Tarmoq xatosi: {exc}", MobCashErrorKind.UNKNOWN) from exc

    async def _try_mirror(self) -> bool:
        """Asosiy host ishlamay qolsa (CDN mirror almashganda) tinyurl'dan yangisini oladi."""
        if self._mirror_tried:
            return False
        self._mirror_tried = True
        try:
            resp = await self._http.get(f"{_UNSHORTEN}{_MIRROR_URL}")
            match = re.search(r"https?://([a-z0-9.-]+\.[a-z]{2,})", resp.text, re.I)
            if not match:
                return False
            host = match.group(1).lower()
            current = self._base.split("//", 1)[-1].split("/", 1)[0].lower()
            if host and host != current:
                log.warning("Agent API mirror almashdi: %s", host)
                self._old_base = self._base
                self._base = f"https://{host}"
                return True
        except httpx.HTTPError:
            pass
        return False

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: Any = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        resp = await self._send(method, f"{self._base}{path}", json=json_body, params=params, headers=headers)
        if resp.status_code in (401, 403):
            if token is None:
                raise MobCashError("Agent ruxsati rad etildi.", MobCashErrorKind.AUTH)
            # Desk token eskirgan bo'lishi mumkin — bir marta yangilab qayta urinamiz.
            self._desk_token = None
            fresh = await self._desk_token_fresh()
            resp = await self._send(
                method, f"{self._base}{path}", json=json_body, params=params,
                headers={"Authorization": f"Bearer {fresh}"},
            )
            if resp.status_code in (401, 403):
                raise MobCashError("Agent tokeni qabul qilinmadi.", MobCashErrorKind.AUTH)
        if resp.status_code >= 500:
            raise MobCashError(f"Server xatosi (HTTP {resp.status_code}).", MobCashErrorKind.UNKNOWN)
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _check(data: Any, what: str) -> dict[str, Any]:
        """HTTP 200 + Success:false shaklidagi biznes xatoni MobCashError ga aylantiradi."""
        if not isinstance(data, dict):
            raise MobCashError(f"{what}: kutilmagan javob", MobCashErrorKind.UNKNOWN)
        if data.get("Success") is False:
            raise MobCashError(
                f"{what}: {data.get('Message') or 'rad etildi'}", MobCashErrorKind.REJECTED
            )
        return data

    # ------------------------------------------------------------------ avtorizatsiya
    async def _agent_token_fresh(self) -> str:
        if self._agent_token and self._agent_exp - _TOKEN_TTL_MARGIN > time.time():
            return self._agent_token
        data = await self._request(
            "POST", "/agentservice/authorization/auth",
            json_body={"Login": self.login_name, "Password": self._password},
        )
        if not isinstance(data, dict) or not data.get("Token"):
            raise MobCashError(
                f"Agent login rad etildi: {_error_text(data) or 'token yo\u2019q'}",
                MobCashErrorKind.AUTH,
            )
        self._agent_token = str(data["Token"])
        self._agent_exp = _jwt_exp(self._agent_token) or (time.time() + 1200)
        # Desk token yangi agent tokenda bekor bo'ladi — qayta tanlaymiz.
        self._desk_token = None
        self._desk_exp = 0.0
        return self._agent_token

    async def _desk_token_fresh(self) -> str:
        if self._desk_token and self._desk_exp - _TOKEN_TTL_MARGIN > time.time():
            return self._desk_token
        agent = await self._agent_token_fresh()
        resp = await self._send(
            "POST",
            f"{self._base}/agentservice/authorization/switchcashdesk",
            json={"cashId": self.cashdesk_id},
            headers={**self._http.headers, "X-Auth": f"Bearer {agent}"},
        )
        try:
            data: Any = resp.json()
        except ValueError:
            data = None
        if resp.status_code in (401, 403):
            raise MobCashError("Agent ruxsati rad etildi.", MobCashErrorKind.AUTH)
        if resp.status_code >= 500:
            raise MobCashError(f"Server xatosi (HTTP {resp.status_code}).", MobCashErrorKind.UNKNOWN)
        if resp.status_code != 200 or not isinstance(data, dict) or not data.get("Token"):
            raise MobCashError(
                f"Kassani tanlab bo'lmadi: {_error_text(data) or f'HTTP {resp.status_code}'}",
                MobCashErrorKind.REJECTED,
            )
        self._desk_token = str(data["Token"])
        self._desk_exp = _jwt_exp(self._desk_token) or (time.time() + 1200)
        return self._desk_token

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        token = await self._desk_token_fresh()
        return await self._request("GET", path, token=token, params=params)

    async def _post(self, path: str, body: Any) -> Any:
        token = await self._desk_token_fresh()
        return await self._request("POST", path, token=token, json_body=body)

    # ------------------------------------------------------------------ umumiy metodlar
    async def check_connection(self) -> CashdeskInfo:
        balance, limit = await self.balance()
        return CashdeskInfo(
            code=str(self.cashdesk_id),
            currency_id="UZS",
            is_deposit=True,
            is_withdrawal=True,
            expires_at=None,
            balance=balance,
            limit=limit,
        )

    async def balance(self) -> tuple[Decimal, Decimal]:
        data = self._check(await self._get("/cashdbcore/GetBalance"), "Balans")
        return _to_decimal(data.get("Balance")), _to_decimal(data.get("ImperiumBalance") or 0)

    async def find_user(self, user_id: str | int) -> dict[str, Any]:
        """O'yinchini topish — ilovada «WebUserni topish» qadami (User/Get).

        Muvaffaqiyatli javob serverdagi joriy user kontekstini o'zgartiradi —
        shu kontekst keyingi Deposit/Add uchun ishlatiladi."""
        uid = str(user_id).strip()
        if not uid.isdigit():
            raise MobCashError(
                "O'yinchi ID faqat raqamlardan iborat bo'lishi kerak.", MobCashErrorKind.REJECTED
            )
        data = self._check(
            await self._post("/cashdbcore/User/Get", {"UserId": int(uid)}), "O'yinchi"
        )
        found_id = data.get("UserId")
        if found_id is not None and str(found_id) != uid:
            log.warning("User/Get ID farq qildi: so'raldi=%s javob=%s", uid, found_id)
        return data

    async def _user_token(self) -> str:
        """Joriy user konteksti uchun UserToken JWT (PrepaidBalance/Token)."""
        data = self._check(await self._post("/cashdbcore/PrepaidBalance/Token", {}), "User token")
        token = data.get("Token")
        if not token:
            raise MobCashError("UserToken javobida yo'q.", MobCashErrorKind.UNKNOWN)
        return str(token)

    # ------------------------------------------------------------------ pul metodlari
    async def payer_nickname(self, payer_id: str) -> str:
        data = await self.find_user(payer_id)
        for key in ("Name", "Nickname", "Login", "Fio"):
            if data.get(key):
                return str(data[key])
        return str(payer_id)

    async def deposit(self, payer_id: str, amount: Decimal) -> dict[str, Any]:
        """Depozit: User/Get (kontekst) → Deposit/Add {Amount}. Pul harakatlanadi."""
        _validate_amount(amount)
        await self.find_user(payer_id)
        data = self._check(
            await self._post("/cashdbcore/Deposit/Add", {"Amount": float(amount)}), "Depozit"
        )
        result: dict[str, Any] = {"success": data.get("Success", True)}
        for key in ("Summa", "Sum", "Amount"):
            if data.get(key) is not None:
                result["amount"] = data[key]
                break
        return result

    async def _payout_context(self, code: str) -> str:
        """Yechish kodi → UserToken. Kod yaroqsiz bo'lsa REJECTED."""
        code = code.strip()
        if not code or len(code) > 10:
            raise MobCashError("To'lov kodi 1–10 belgidan iborat bo'lsin.", MobCashErrorKind.REJECTED)
        found = self._check(
            await self._get("/cashdbcore/Deposit/FindPayoutByCode", {"code": code}),
            "To'lov so'rovi",
        )
        if not found.get("Success"):
            raise MobCashError(
                found.get("Message") or "To'lov so'rovi topilmadi.", MobCashErrorKind.REJECTED
            )
        user_id = int(found.get("UserId") or 0)
        if user_id <= 0:
            raise MobCashError("To'lov so'rovida user ID yo'q.", MobCashErrorKind.UNKNOWN)
        # Kontekstni shu user'ga o'tkazamiz (ilovadagi oqim shunday).
        await self.find_user(user_id)
        return await self._user_token()

    async def get_withdrawal_amount(self, payer_id: str, code: str) -> Decimal:
        """Kod bo'yicha summa: kontekst + CheckCodePayout. Pul harakatlanmaydi."""
        user_token = await self._payout_context(code)
        data = await self._get(
            "/cashdbcore/Deposit/CheckCodePayout",
            {"code": code.strip(), "UserToken": user_token},
        )
        if isinstance(data, dict):
            if data.get("Success") is False:
                raise MobCashError(
                    data.get("Message") or "Kod tekshirilmadi.", MobCashErrorKind.REJECTED
                )
            for key in ("Sum", "Summa", "Amount"):
                if data.get(key) is not None:
                    amount = _to_decimal(data[key])
                    if amount > 0:
                        return amount
        raise MobCashError("Kod bo'yicha summa aniqlanmadi.", MobCashErrorKind.UNKNOWN)

    async def withdrawal(self, payer_id: str, code: str, amount: Decimal) -> dict[str, Any]:
        """Yechish: kontekst → Deposit/Payout {Code, UserToken}. Pul harakatlanadi."""
        user_token = await self._payout_context(code)
        data = self._check(
            await self._post(
                "/cashdbcore/Deposit/Payout", {"Code": code.strip(), "UserToken": user_token}
            ),
            "Yechish",
        )
        result: dict[str, Any] = {"success": data.get("Success", True)}
        for key in ("Summa", "Sum", "Amount"):
            if data.get(key) is not None:
                result["amount"] = data[key]
                break
        return result

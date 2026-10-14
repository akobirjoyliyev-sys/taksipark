"""Mob-Cash klienti: login/token keshi, JSON-RPC javoblari va xatolar tasnifi (tarmoqsiz)."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import fakeredis
import httpx
import pytest

from app.mobcash import MobCashClient, MobCashError, MobCashErrorKind

AUTH = "https://mc.test/api/v2/cashbox"
API = "https://mc.test/api/v1/mobile"

LOGIN_OK = {
    "sessionID": "S1",
    "userID": "U1",
    "accessToken": "T1",
    "expiresAt": "2099-01-01T00:00:00.000Z",
    "cashbox": {"code": 1000042, "currencyID": "UZS", "isDeposit": True, "isWithdrawal": True},
}

Handler = Callable[[httpx.Request], httpx.Response]


def rpc(result: Any) -> httpx.Response:
    return httpx.Response(200, json=[{"id": 1, "jsonrpc": "2.0", "result": result}])


def make_client(handler: Handler, redis: Any | None = None) -> tuple[MobCashClient, list]:
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = MobCashClient(
        redis=redis or fakeredis.FakeAsyncRedis(),
        cashbox_code=1000042,
        login="cashier",
        password="secret",
        auth_url=AUTH,
        api_url=API,
        timeout=5,
        transport=httpx.MockTransport(wrapped),
    )
    return client, calls


def body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


async def test_login_then_rpc_uses_token_and_session() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            assert body(request) == {
                "cashboxCode": 1000042,
                "login": "cashier",
                "password": "secret",
            }
            return httpx.Response(200, json=LOGIN_OK)
        assert request.headers["authorization"] == "Bearer T1"
        params = body(request)["params"]
        assert params["sessionID"] == "S1" and params["userID"] == "U1"
        assert params["payerID"] == "777001"
        return rpc({"nickname": "player_one"})

    client, calls = make_client(handler)
    assert await client.payer_nickname("777001") == "player_one"
    assert await client.payer_nickname("777001") == "player_one"
    # Token keshdan olinadi — login faqat bir marta.
    assert sum(r.url.path.endswith("/login") for r in calls) == 1


async def test_token_shared_between_clients_via_redis() -> None:
    redis = fakeredis.FakeAsyncRedis()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json=LOGIN_OK)
        return rpc({"nickname": "x"})

    first, _ = make_client(handler, redis)
    second, second_calls = make_client(handler, redis)
    await first.payer_nickname("777001")
    await second.payer_nickname("777001")
    assert not any(r.url.path.endswith("/login") for r in second_calls)


async def test_deposit_and_withdrawal_payload_format() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json=LOGIN_OK)
        seen[request.url.path.rsplit("/", 1)[-1]] = body(request)["params"]
        if request.url.path.endswith("/getWithdrawalAmount"):
            return rpc({"amount": "101.00"})
        if request.url.path.endswith("/payerNickname"):
            return rpc({"nickname": "player_one"})
        return rpc({"success": True, "amount": "x"})

    client, _ = make_client(handler)
    await client.deposit("777001", Decimal("50437.00"))
    assert seen["deposit"]["deposit"] == {"amount": "50437", "payerID": "777001"}

    amount = await client.get_withdrawal_amount("777001", "Secret_abc")
    assert amount == Decimal("101.00")
    await client.withdrawal("777001", "Secret_abc", amount)
    assert seen["withdrawal"]["withdraw"] == {
        "amount": 101,
        "payerID": "777001",
        "withdrawalCode": "Secret_abc",
    }


async def test_expired_token_relogins_once() -> None:
    tokens = iter(["T1", "T2"])
    state = {"rpc": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={**LOGIN_OK, "accessToken": next(tokens)})
        state["rpc"] += 1
        if request.headers["authorization"] == "Bearer T1":
            return httpx.Response(401, json={"error": "token expired"})
        return rpc({"nickname": "ok"})

    client, _ = make_client(handler)
    assert await client.payer_nickname("777001") == "ok"
    assert state["rpc"] == 2


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (
            httpx.Response(200, json=[{"id": 1, "error": {"code": 5, "message": "not found"}}]),
            MobCashErrorKind.REJECTED,
        ),
        (
            httpx.Response(200, json=[{"id": 1, "result": {"success": False}}]),
            MobCashErrorKind.REJECTED,
        ),
        (httpx.Response(502, text="bad gateway"), MobCashErrorKind.UNKNOWN),
    ],
)
async def test_deposit_error_kinds(response: httpx.Response, kind: MobCashErrorKind) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json=LOGIN_OK)
        if request.url.path.endswith("/payerNickname"):
            return rpc({"nickname": "player_one"})
        return response

    client, _ = make_client(handler)
    with pytest.raises(MobCashError) as info:
        await client.deposit("777001", Decimal("10"))
    assert info.value.kind == kind


async def test_timeout_is_ambiguous_and_connect_error_is_safe() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json=LOGIN_OK)
        if request.url.path.endswith("/payerNickname"):
            return rpc({"nickname": "player_one"})
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(timeout)
    with pytest.raises(MobCashError) as info:
        await client.deposit("777001", Decimal("10"))
    assert info.value.outcome_unknown

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(refused)
    with pytest.raises(MobCashError) as info:
        await client.payer_nickname("777001")
    assert info.value.kind == MobCashErrorKind.NETWORK
    assert not info.value.outcome_unknown


async def test_bad_credentials() -> None:
    client, _ = make_client(lambda r: httpx.Response(403, json={"error": "unauthorized error"}))
    with pytest.raises(MobCashError) as info:
        await client.check_connection()
    assert info.value.kind == MobCashErrorKind.AUTH
    assert "unauthorized" in info.value.message


async def test_not_configured() -> None:
    client = MobCashClient(
        redis=fakeredis.FakeAsyncRedis(),
        cashbox_code=0,
        login="",
        password="",
        auth_url=AUTH,
        api_url=API,
    )
    assert not client.configured
    with pytest.raises(MobCashError) as info:
        await client.payer_nickname("1")
    assert info.value.kind == MobCashErrorKind.CONFIG


async def test_old_cashbox_token_not_reused_after_credentials_change() -> None:
    """Kassa almashtirilgach, boshqa jarayon yozgan eski kassa tokeni ishlatilmasligi kerak."""
    redis = fakeredis.FakeAsyncRedis()
    logins: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            code = body(request)["cashboxCode"]
            logins.append(code)
            return httpx.Response(200, json={**LOGIN_OK, "accessToken": f"T{code}"})
        return rpc({"nickname": request.headers["authorization"]})

    old_proc, _ = make_client(handler, redis)  # hali eski kassa ma’lumotlari bilan
    new_proc, _ = make_client(handler, redis)
    await new_proc.set_credentials(2000001, "cashier2", "secret2")
    assert await old_proc.payer_nickname("1") == "Bearer T1000042"
    assert await new_proc.payer_nickname("1") == "Bearer T2000001"
    assert logins == [1000042, 2000001]

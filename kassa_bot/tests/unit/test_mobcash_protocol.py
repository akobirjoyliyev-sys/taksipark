"""Berilgan v2/v1 hujjat kontrakti va pul harakati noaniq bo‘lgan javoblar."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock

import fakeredis
import httpx
import pytest

from app.mobcash import MobCashError, MobCashErrorKind
from tests.unit.test_mobcash_client import API, AUTH, LOGIN_OK, body, make_client, rpc


@pytest.fixture
async def clients():
    opened = []

    def create(handler, redis=None):
        client, calls = make_client(handler, redis)
        opened.append(client)
        return client, calls

    yield create
    for client in opened:
        await client.close()
        await client.redis.aclose()


def normal(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/login"):
        return httpx.Response(200, json=LOGIN_OK)
    if request.url.path.endswith("/payerNickname"):
        return rpc({"nickname": "player"})
    return rpc({"success": True, "amount": "101.25"})


async def test_documented_contract_all_five_methods(clients):
    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        assert request.headers["accept"] == "application/json, text/plain, */*"
        assert request.headers["content-type"] == "application/json"
        payload = body(request)
        if method == "login":
            assert str(request.url) == AUTH + "/login"
            assert payload == {"cashboxCode": 1000042, "login": "cashier", "password": "secret"}
            assert "authorization" not in request.headers
            return normal(request)
        assert str(request.url) == API + "/" + method
        assert request.headers["authorization"] == "Bearer T1"
        assert set(payload) == {"id", "jsonrpc", "params"}
        assert payload["jsonrpc"] == "2.0"
        params = payload["params"]
        session = {"sessionID": "S1", "userID": "U1"}
        if method == "payerNickname":
            assert params == {**session, "payerID": "1000016167"}
            result = {"nickname": "player"}
        elif method == "deposit":
            assert params == {**session, "deposit": {"amount": "10", "payerID": "1000016167"}}
            result = {"success": True, "amount": "10"}
        elif method == "getWithdrawalAmount":
            assert params == {
                **session,
                "withdraw": {"payerID": "1000016167", "withdrawalCode": "Secret_test"},
            }
            result = {"amount": "101.25"}
        else:
            assert method == "withdrawal"
            assert params == {
                **session,
                "withdraw": {
                    "amount": 101.25,
                    "payerID": "1000016167",
                    "withdrawalCode": "Secret_test",
                },
            }
            result = {"success": True, "amount": "101.25"}
        # Hujjatdagi namunalarda javob id'si so‘rovnikiga mos emas.
        return httpx.Response(200, json=[{"id": 17, "jsonrpc": "2.0", "result": result}])

    client, calls = clients(handler)
    await client.payer_nickname("1000016167")
    await client.deposit("1000016167", Decimal("10"))
    amount = await client.get_withdrawal_amount("1000016167", "Secret_test")
    await client.withdrawal("1000016167", "Secret_test", amount)
    assert [r.url.path.rsplit("/", 1)[-1] for r in calls] == [
        "login",
        "payerNickname",
        "payerNickname",
        "deposit",
        "getWithdrawalAmount",
        "withdrawal",
    ]


@pytest.mark.parametrize("method", ["deposit", "withdrawal"])
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, json=[]),
        httpx.Response(200, json=[{"result": None}]),
        httpx.Response(200, json=[{"result": {}}]),
        httpx.Response(200, json=[{"result": {"success": "true"}}]),
        httpx.Response(200, json=[{"result": {"success": 1}}]),
        httpx.Response(200, json=[{"result": {"success": True}, "error": {"code": 1}}]),
        httpx.Response(200, text="<html>proxy error</html>"),
        httpx.Response(204),
        httpx.Response(302, headers={"Location": "/login"}),
        httpx.Response(408),
        httpx.Response(502),
    ],
)
async def test_ambiguous_mutation_never_succeeds_or_repeats(clients, method, response):
    client, calls = clients(lambda r: response if r.url.path.endswith("/" + method) else normal(r))
    with pytest.raises(MobCashError) as error:
        if method == "deposit":
            await client.deposit("777001", Decimal("10"))
        else:
            await client.withdrawal("777001", "Secret_test", Decimal("10"))
    assert error.value.outcome_unknown
    assert sum(r.url.path.endswith("/" + method) for r in calls) == 1


async def test_payer_must_exist_before_deposit(clients):
    client, calls = clients(
        lambda r: rpc({"nickname": ""}) if r.url.path.endswith("/payerNickname") else normal(r)
    )
    with pytest.raises(MobCashError) as error:
        await client.deposit("777001", Decimal("10"))
    assert error.value.kind == MobCashErrorKind.REJECTED
    assert not any(r.url.path.endswith("/deposit") for r in calls)


@pytest.mark.parametrize("stage", ["login", "payerNickname"])
async def test_preflight_timeout_does_not_imply_money_was_sent(clients, stage):
    def handler(request):
        if request.url.path.endswith("/" + stage):
            raise httpx.ReadTimeout("slow", request=request)
        return normal(request)

    client, calls = clients(handler)
    with pytest.raises(MobCashError) as error:
        await client.deposit("777001", Decimal("10"))
    assert error.value.kind == MobCashErrorKind.NETWORK
    assert not any(r.url.path.endswith("/deposit") for r in calls)


async def test_relogin_rechecks_payer_with_new_session(clients):
    logins = 0

    def handler(request):
        nonlocal logins
        if request.url.path.endswith("/login"):
            logins += 1
            return httpx.Response(
                200,
                json={
                    **LOGIN_OK,
                    "accessToken": f"T{logins}",
                    "sessionID": f"S{logins}",
                    "userID": f"U{logins}",
                },
            )
        params = body(request)["params"]
        token = request.headers["authorization"][-1]
        assert params["sessionID"] == f"S{token}" and params["userID"] == f"U{token}"
        if request.url.path.endswith("/deposit") and token == "1":
            return httpx.Response(401)
        return normal(request)

    client, calls = clients(handler)
    await client.deposit("777001", Decimal("10"))
    assert [r.url.path.rsplit("/", 1)[-1] for r in calls] == [
        "login",
        "payerNickname",
        "deposit",
        "login",
        "payerNickname",
        "deposit",
    ]


@pytest.mark.parametrize(
    "key,value",
    [
        ("sessionID", None),
        ("userID", ""),
        ("accessToken", True),
        ("expiresAt", "bad date"),
        ("expiresAt", "2000-01-01T00:00:00Z"),
        ("cashbox", ["wrong"]),
    ],
)
async def test_invalid_login_does_not_send_mobile_requests(clients, key, value):
    client, calls = clients(lambda r: httpx.Response(200, json={**LOGIN_OK, key: value}))
    with pytest.raises(MobCashError) as error:
        await client.deposit("777001", Decimal("10"))
    assert error.value.kind == MobCashErrorKind.AUTH
    assert len(calls) == 1


@pytest.mark.parametrize("cached", ["[]", "null", '{"accessToken":"x"}', "bad-json"])
async def test_corrupt_auth_cache_is_replaced(clients, cached):
    client, calls = clients(normal)
    await client.redis.set(client.AUTH_KEY, cached)
    assert await client.payer_nickname("777001") == "player"
    assert calls[0].url.path.endswith("/login")


async def test_naive_expiry_date_is_normalized_to_utc(clients):
    def handler(r):
        if r.url.path.endswith("/login"):
            return httpx.Response(200, json={**LOGIN_OK, "expiresAt": "2099-01-01T00:00:00"})
        return normal(r)

    client, calls = clients(handler)
    await client.payer_nickname("1")
    await client.payer_nickname("1")
    assert sum(r.url.path.endswith("/login") for r in calls) == 1


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "0", "-1", "oops"])
async def test_invalid_withdrawal_quote_is_rejected(clients, amount):
    client, _ = clients(
        lambda r: (
            rpc({"amount": amount}) if r.url.path.endswith("/getWithdrawalAmount") else normal(r)
        )
    )
    with pytest.raises(MobCashError) as error:
        await client.get_withdrawal_amount("777001", "Secret_test")
    assert error.value.kind == MobCashErrorKind.REJECTED


@pytest.mark.parametrize("method", ["deposit", "withdrawal"])
@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-1", "0", "0.001", "1e100"])
async def test_invalid_amount_never_reaches_api(clients, method, amount):
    client, calls = clients(normal)
    with pytest.raises(MobCashError):
        if method == "deposit":
            await client.deposit("777001", Decimal(amount))
        else:
            await client.withdrawal("777001", "Secret_test", Decimal(amount))
    assert calls == []


@pytest.mark.parametrize("method,flag", [("deposit", "isDeposit"), ("withdrawal", "isWithdrawal")])
async def test_disabled_cashbox_capability_blocks_mutation(clients, method, flag):
    def handler(r):
        if r.url.path.endswith("/login"):
            return httpx.Response(
                200, json={**LOGIN_OK, "cashbox": {**LOGIN_OK["cashbox"], flag: False}}
            )
        return normal(r)

    client, calls = clients(handler)
    with pytest.raises(MobCashError) as error:
        if method == "deposit":
            await client.deposit("777001", Decimal("10"))
        else:
            await client.withdrawal("777001", "Secret_test", Decimal("10"))
    assert error.value.kind == MobCashErrorKind.REJECTED
    assert len(calls) == 1


async def test_credentials_and_environment_isolate_token_cache(clients):
    shared = fakeredis.FakeAsyncRedis()
    first, _ = clients(normal, shared)
    changed, _ = clients(normal, shared)
    staging, _ = clients(normal, shared)
    await changed.set_credentials(first.cashbox_code, first.login_name, "new-password")
    staging.api_url = "https://staging.test/api/v1/mobile"
    assert len({first.AUTH_KEY, changed.AUTH_KEY, staging.AUTH_KEY}) == 3
    assert "new-password" not in changed.AUTH_KEY


async def test_unavailable_redis_fails_without_uncoordinated_login(clients):
    client, calls = clients(normal)
    client.redis.set = AsyncMock(side_effect=ConnectionError("offline"))
    with pytest.raises(MobCashError) as error:
        await client.payer_nickname("777001")
    assert error.value.kind == MobCashErrorKind.NETWORK
    assert calls == []


async def test_busy_login_lock_is_not_bypassed(clients, monkeypatch):
    monkeypatch.setattr("app.mobcash.client.LOGIN_LOCK_WAIT", -1)
    client, calls = clients(normal)
    await client.redis.set(client.LOCK_KEY, "another-owner", ex=60)
    with pytest.raises(MobCashError) as error:
        await client.payer_nickname("777001")
    assert error.value.kind == MobCashErrorKind.NETWORK
    assert calls == []
    await client._release_lock("old-owner")
    assert await client.redis.get(client.LOCK_KEY) == b"another-owner"


async def test_concurrent_clients_share_one_login(clients):
    shared = fakeredis.FakeAsyncRedis()
    first, calls1 = clients(normal, shared)
    second, calls2 = clients(normal, shared)
    assert await asyncio.gather(first.payer_nickname("1"), second.payer_nickname("2")) == [
        "player",
        "player",
    ]
    assert sum(r.url.path.endswith("/login") for r in calls1 + calls2) == 1


async def test_batch_response_is_correlated_by_request_id(clients):
    def handler(r):
        if r.url.path.endswith("/login"):
            return normal(r)
        request_id = json.loads(r.content)["id"]
        return httpx.Response(
            200,
            json=[
                {"id": request_id + 1, "result": {"nickname": "wrong account"}},
                {"id": request_id, "result": {"nickname": "correct account"}},
            ],
        )

    client, _ = clients(handler)
    assert await client.payer_nickname("777001") == "correct account"

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    code: str
    available: bool
    failures: int
    last_error: str
    last_ok_at: int
    open_until: int


class ProviderHealthService:
    """Oddiy circuit breaker: ketma-ket N xatodan keyin provayder vaqtincha o‘chiriladi."""

    FAIL_THRESHOLD = 3
    COOLDOWN_SECONDS = 300

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def _key(code: str) -> str:
        return f"provider_health:{code}"

    async def record_success(self, code: str) -> None:
        await self.redis.hset(
            self._key(code),
            mapping={"failures": 0, "last_ok_at": int(time.time()), "open_until": 0},
        )

    async def record_failure(self, code: str, error: str) -> None:
        key = self._key(code)
        failures = await self.redis.hincrby(key, "failures", 1)
        now = int(time.time())
        await self.redis.hset(key, mapping={"last_error": error[:200], "failed_at": now})
        if failures >= self.FAIL_THRESHOLD:
            await self.redis.hset(key, "open_until", now + self.COOLDOWN_SECONDS)

    async def status(self, code: str) -> ProviderHealth:
        raw = await self.redis.hgetall(self._key(code))
        data = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        open_until = int(data.get("open_until", 0) or 0)
        return ProviderHealth(
            code=code,
            available=open_until <= time.time(),
            failures=int(data.get("failures", 0) or 0),
            last_error=str(data.get("last_error", "")),
            last_ok_at=int(data.get("last_ok_at", 0) or 0),
            open_until=open_until,
        )

    async def is_available(self, code: str) -> bool:
        return (await self.status(code)).available

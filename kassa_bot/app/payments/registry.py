from __future__ import annotations

from collections.abc import Iterable

from redis.asyncio import Redis

from app.config import Config
from app.payments.base import PaymentProvider
from app.payments.manual import ManualProvider
from app.payments.sandbox import SandboxProvider


class ProviderNotConfiguredError(LookupError):
    pass


class ProviderRegistry:
    def __init__(self, providers: Iterable[PaymentProvider]) -> None:
        self._providers = {p.code: p for p in providers}

    @property
    def codes(self) -> list[str]:
        return list(self._providers)

    def get(self, code: str) -> PaymentProvider:
        try:
            return self._providers[code]
        except KeyError as exc:
            raise ProviderNotConfiguredError(code) from exc

    def find(self, code: str) -> PaymentProvider | None:
        return self._providers.get(code)

    def enabled(self, codes: Iterable[str]) -> list[PaymentProvider]:
        return [self._providers[c] for c in codes if c in self._providers]

    def has_real_provider(self, codes: Iterable[str]) -> bool:
        return any(not p.is_sandbox for p in self.enabled(codes))

    def has_sandbox(self, codes: Iterable[str]) -> bool:
        return any(p.is_sandbox for p in self.enabled(codes))

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()


def build_registry(config: Config, redis: Redis) -> ProviderRegistry:
    """ENV dagi PAYMENT_PROVIDERS ro‘yxatidan adapterlarni yaratadi.

    Yangi provayder qo‘shish: `PaymentProvider`dan meros olgan adapter yozing va shu
    yerda ro‘yxatdan o‘tkazing (README → “Yangi provayder qo‘shish”).
    """
    providers: list[PaymentProvider] = []
    for code in config.provider_codes:
        if code == SandboxProvider.code:
            providers.append(
                SandboxProvider(
                    redis=redis,
                    secret=config.sandbox_webhook_secret.get_secret_value(),
                    public_base_url=config.public_base_url,
                    payout_failure_rate=config.sandbox_payout_failure_rate,
                    payout_delay_seconds=config.sandbox_payout_delay_seconds,
                )
            )
        elif code == ManualProvider.code:
            providers.append(ManualProvider())
        else:
            raise ValueError(f"Noma’lum to‘lov provayderi: {code!r}. Adapter qo‘shing.")
    if not providers:
        raise ValueError("PAYMENT_PROVIDERS bo‘sh — kamida 'sandbox' ko‘rsating.")
    return ProviderRegistry(providers)

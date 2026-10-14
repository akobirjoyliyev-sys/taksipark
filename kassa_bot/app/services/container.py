from __future__ import annotations

from functools import cached_property

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.mobcash import MobCashClient
from app.payments.registry import ProviderRegistry
from app.services.admins import AdminService
from app.services.audit import AuditService
from app.services.bonus import PromoService, ReferralService, VipService
from app.services.bookmakers import BookmakerService
from app.services.channels import ChannelService, JoinRequestService, SubscriptionService
from app.services.deposits import DepositService
from app.services.mass_payout import MassPayoutService
from app.services.mobcash_withdrawals import MobcashWithdrawalService
from app.services.notifier import Notifier
from app.services.p2p import P2PService
from app.services.provider_health import ProviderHealthService
from app.services.settings import SettingsService
from app.services.stats import StatsService
from app.services.userbots import UserbotService
from app.services.users import UserService
from app.services.withdrawals import CardService, WithdrawalService


class Services:
    """Bitta DB sessiyasi doirasidagi servislar to‘plami (handler, API va worker uchun)."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        providers: ProviderRegistry,
        config: Config,
        bot: Bot | None = None,
        mobcash: MobCashClient | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.providers = providers
        self.config = config
        self.bot = bot
        self.mobcash = mobcash

    @cached_property
    def settings(self) -> SettingsService:
        return SettingsService(self.session, self.redis, self.config, self.providers)

    @cached_property
    def health(self) -> ProviderHealthService:
        return ProviderHealthService(self.redis)

    @cached_property
    def audit(self) -> AuditService:
        return AuditService(self.session)

    @cached_property
    def admins(self) -> AdminService:
        return AdminService(self.session)

    @cached_property
    def users(self) -> UserService:
        return UserService(self.session)

    @cached_property
    def deposits(self) -> DepositService:
        return DepositService(self.session, self.providers, self.settings, self.config.currency)

    @cached_property
    def withdrawals(self) -> WithdrawalService:
        return WithdrawalService(
            self.session, self.providers, self.settings, self.health, self.config.currency
        )

    @cached_property
    def cards(self) -> CardService:
        return CardService(self.session, self.redis, self.providers, self.settings)

    @cached_property
    def promo(self) -> PromoService:
        return PromoService(self.session)

    @cached_property
    def vip(self) -> VipService:
        return VipService(self.session)

    @cached_property
    def referral(self) -> ReferralService:
        return ReferralService(self.session, self.settings, self.config.bot_username)

    @cached_property
    def subscription(self) -> SubscriptionService:
        return SubscriptionService(self.session, self.redis, self.bot)

    @cached_property
    def channels(self) -> ChannelService:
        return ChannelService(self.session, self.bot)

    @cached_property
    def join_requests(self) -> JoinRequestService:
        return JoinRequestService(self.session, self.bot)

    @cached_property
    def stats(self) -> StatsService:
        return StatsService(self.session)

    @cached_property
    def mass(self) -> MassPayoutService:
        return MassPayoutService(self.session, self.providers, self.settings)

    @cached_property
    def notifier(self) -> Notifier:
        return Notifier(self.bot)

    @cached_property
    def p2p(self) -> P2PService:
        return P2PService(
            self.session, self.redis, self.settings, self.mobcash, self.config, self.bookmakers
        )

    @cached_property
    def mcwd(self) -> MobcashWithdrawalService:
        return MobcashWithdrawalService(
            self.session, self.redis, self.settings, self.mobcash, self.bookmakers
        )

    @cached_property
    def bookmakers(self) -> BookmakerService:
        return BookmakerService(self.session, self.redis, self.config, self.settings, self.mobcash)

    @cached_property
    def userbots(self) -> UserbotService:
        return UserbotService(self.session, self.settings)

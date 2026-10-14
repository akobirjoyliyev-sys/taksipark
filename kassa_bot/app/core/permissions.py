from __future__ import annotations

from enum import StrEnum

from app.core.enums import AdminRole


class Perm(StrEnum):
    DASHBOARD = "dashboard"
    STATS_VIEW = "stats.view"
    AUDIT_VIEW = "audit.view"
    USERS_VIEW = "users.view"
    USERS_BAN = "users.ban"
    USERS_BALANCE = "users.balance"
    USERS_MESSAGE = "users.message"
    USERS_PII = "users.pii"
    ADMINS_MANAGE = "admins.manage"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_EDIT = "settings.edit"
    SETTINGS_CRITICAL = "settings.critical"
    MASS_VIEW = "mass.view"
    MASS_CREATE = "mass.create"
    MASS_APPROVE = "mass.approve"
    AUTO_VIEW = "auto.view"
    AUTO_MANAGE = "auto.manage"
    WITHDRAW_VIEW = "withdraw.view"
    WITHDRAW_PROCESS = "withdraw.process"
    JOIN_VIEW = "join.view"
    JOIN_PROCESS = "join.process"
    BONUS_VIEW = "bonus.view"
    BONUS_MANAGE = "bonus.manage"
    CHANNELS_VIEW = "channels.view"
    CHANNELS_MANAGE = "channels.manage"
    MOBCASH_VIEW = "mobcash.view"
    MOBCASH_PROCESS = "mobcash.process"
    MOBCASH_MANAGE = "mobcash.manage"
    USERBOT_MANAGE = "userbot.manage"


_READ_ONLY = frozenset(
    {
        Perm.DASHBOARD,
        Perm.STATS_VIEW,
        Perm.USERS_VIEW,
        Perm.SETTINGS_VIEW,
        Perm.MASS_VIEW,
        Perm.AUTO_VIEW,
        Perm.WITHDRAW_VIEW,
        Perm.JOIN_VIEW,
        Perm.BONUS_VIEW,
        Perm.CHANNELS_VIEW,
        Perm.MOBCASH_VIEW,
    }
)

ROLE_PERMISSIONS: dict[AdminRole, frozenset[Perm]] = {
    AdminRole.SUPERADMIN: frozenset(Perm),
    # Userbot sessiyasi Telegram akkauntiga to‘liq kirish beradi — faqat superadmin.
    AdminRole.ADMIN: frozenset(Perm)
    - {Perm.ADMINS_MANAGE, Perm.SETTINGS_CRITICAL, Perm.MASS_APPROVE, Perm.USERBOT_MANAGE},
    AdminRole.OPERATOR: _READ_ONLY
    | {
        Perm.USERS_MESSAGE,
        Perm.WITHDRAW_PROCESS,
        Perm.JOIN_PROCESS,
        Perm.MASS_APPROVE,
        Perm.MOBCASH_PROCESS,
    },
    AdminRole.AUDITOR: _READ_ONLY | {Perm.AUDIT_VIEW},
}


def has_perm(role: str | AdminRole, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[AdminRole(role)]
    except ValueError:
        return False

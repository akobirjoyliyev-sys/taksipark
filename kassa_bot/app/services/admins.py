from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AdminRole
from app.core.errors import DomainError
from app.core.permissions import Perm, has_perm
from app.models import Admin
from app.repositories.admins import AdminRepository
from app.services.audit import Actor, AuditService


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AdminRepository(session)
        self.audit = AuditService(session)

    async def sync_from_env(self, roles: dict[int, AdminRole]) -> None:
        """ENV dagi ADMIN_IDS ni DB bilan moslaydi (ENV ustun)."""
        existing = {a.telegram_id: a for a in await self.repo.list_all()}
        for tg_id, role in roles.items():
            admin = existing.get(tg_id)
            if admin is None:
                self.session.add(Admin(telegram_id=tg_id, role=role, from_env=True, is_active=True))
                await self.audit.log(
                    Actor.system(), "admin.env_sync", "admin", tg_id, after={"role": role}
                )
            elif admin.role != role or not admin.is_active or not admin.from_env:
                before = {"role": admin.role, "active": admin.is_active}
                admin.role, admin.is_active, admin.from_env = role, True, True
                await self.audit.log(
                    Actor.system(),
                    "admin.env_sync",
                    "admin",
                    tg_id,
                    before=before,
                    after={"role": role, "active": True},
                )
        for tg_id, admin in existing.items():
            if admin.from_env and tg_id not in roles and admin.is_active:
                admin.is_active = False
                await self.audit.log(
                    Actor.system(), "admin.env_removed", "admin", tg_id, after={"active": False}
                )
        await self.session.commit()

    async def get_active(self, telegram_id: int) -> Admin | None:
        admin = await self.repo.get_by_telegram_id(telegram_id)
        return admin if admin and admin.is_active else None

    async def list_all(self) -> list[Admin]:
        return await self.repo.list_all()

    async def telegram_ids_with(self, perm: Perm) -> list[int]:
        return [a.telegram_id for a in await self.repo.list_active() if has_perm(a.role, perm)]

    async def upsert(self, telegram_id: int, role: AdminRole, actor: Actor) -> Admin:
        admin = await self.repo.get_by_telegram_id(telegram_id)
        if admin is not None and admin.from_env:
            raise DomainError("Bu admin ENV (ADMIN_IDS) orqali boshqariladi.")
        before = None if admin is None else {"role": admin.role, "active": admin.is_active}
        if admin is None:
            admin = Admin(
                telegram_id=telegram_id, role=role, is_active=True, added_by=actor.telegram_id
            )
            self.session.add(admin)
        else:
            admin.role, admin.is_active = role, True
        await self.audit.log(
            actor,
            "admin.upsert",
            "admin",
            telegram_id,
            before=before,
            after={"role": role, "active": True},
        )
        await self.session.commit()
        return admin

    async def set_active(self, admin_id: int, active: bool, actor: Actor) -> Admin:
        admin = await self.repo.get(admin_id)
        if admin is None:
            raise DomainError("Admin topilmadi.")
        if admin.from_env:
            raise DomainError("Bu admin ENV (ADMIN_IDS) orqali boshqariladi.")
        if admin.telegram_id == actor.telegram_id:
            raise DomainError("O‘zingizni o‘chira olmaysiz.")
        before = {"active": admin.is_active}
        admin.is_active = active
        await self.audit.log(
            actor,
            "admin.set_active",
            "admin",
            admin.telegram_id,
            before=before,
            after={"active": active},
        )
        await self.session.commit()
        return admin

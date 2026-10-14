from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AdminRole
from app.models import Admin, AuditLog, SystemSetting


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Admin | None:
        return await self.session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))

    async def get(self, admin_id: int) -> Admin | None:
        return await self.session.get(Admin, admin_id)

    async def list_all(self) -> list[Admin]:
        return list(await self.session.scalars(select(Admin).order_by(Admin.role, Admin.id)))

    async def list_active(self, roles: tuple[AdminRole, ...] | None = None) -> list[Admin]:
        stmt = select(Admin).where(Admin.is_active.is_(True))
        if roles:
            stmt = stmt.where(Admin.role.in_(roles))
        return list(await self.session.scalars(stmt))

    async def count_active(self, role: AdminRole) -> int:
        stmt = select(func.count(Admin.id)).where(Admin.is_active.is_(True), Admin.role == role)
        return int(await self.session.scalar(stmt) or 0)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest(self, limit: int, offset: int = 0) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def all(self) -> dict[str, str]:
        rows = await self.session.scalars(select(SystemSetting))
        return {r.key: r.value for r in rows}

    async def get(self, key: str) -> SystemSetting | None:
        return await self.session.get(SystemSetting, key)

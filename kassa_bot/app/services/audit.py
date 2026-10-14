from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Admin, AuditLog


@dataclass(frozen=True, slots=True)
class Actor:
    telegram_id: int | None
    role: str

    @classmethod
    def system(cls, role: str = "system") -> Actor:
        return cls(telegram_id=None, role=role)

    @classmethod
    def from_admin(cls, admin: Admin) -> Actor:
        return cls(telegram_id=admin.telegram_id, role=str(admin.role))

    @classmethod
    def user(cls, telegram_id: int) -> Actor:
        return cls(telegram_id=telegram_id, role="user")


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class AuditService:
    """Har bir admin/tizim amali uchun o‘zgarmas yozuv. Commit chaqiruvchi tomonda."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        actor: Actor,
        action: str,
        entity_type: str,
        entity_id: object | None = None,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        comment: str | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                actor_telegram_id=actor.telegram_id,
                actor_role=actor.role,
                action=action,
                entity_type=entity_type,
                entity_id=None if entity_id is None else str(entity_id),
                before=jsonable(before) if before is not None else None,
                after=jsonable(after) if after is not None else None,
                comment=comment[:2000] if comment else None,
            )
        )
        await self.session.flush()

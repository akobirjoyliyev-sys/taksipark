"""cashdesk gateway (1xBet Cashdesk Bot API kassalari)

Revision ID: 0005_cashdesk
Revises: 0004_bookmakers
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_cashdesk"
down_revision: str | None = "0004_bookmakers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bookmakers",
        sa.Column("gateway", sa.String(16), server_default="mobcash", nullable=False),
    )
    op.add_column("bookmakers", sa.Column("hash_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bookmakers", "hash_encrypted")
    op.drop_column("bookmakers", "gateway")

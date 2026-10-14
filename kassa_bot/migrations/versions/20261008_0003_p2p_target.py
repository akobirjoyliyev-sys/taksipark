"""p2p_deposits.target — game | wallet

Revision ID: 0003_p2p_target
Revises: 0002_mobcash_p2p
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_p2p_target"
down_revision: str | None = "0002_mobcash_p2p"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "p2p_deposits",
        sa.Column("target", sa.String(32), nullable=False, server_default="game"),
    )
    op.create_index("ix_p2p_deposits_target", "p2p_deposits", ["target"])


def downgrade() -> None:
    op.drop_index("ix_p2p_deposits_target", table_name="p2p_deposits")
    op.drop_column("p2p_deposits", "target")

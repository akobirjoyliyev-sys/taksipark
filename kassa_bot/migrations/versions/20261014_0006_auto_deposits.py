"""auto deposits (🤖 Avto to‘lov: ID ro‘yxatiga ommaviy depozit)

Revision ID: 0006_auto_deposits
Revises: 0005_cashdesk
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_auto_deposits"
down_revision: str | None = "0005_cashdesk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
MONEY = sa.Numeric(18, 2)


def upgrade() -> None:
    op.create_table(
        "auto_deposit_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bookmaker_id", sa.BigInteger(), nullable=True),
        sa.Column("kassa_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("default_amount", MONEY, nullable=True),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_amount", MONEY, server_default="0", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("started_by", sa.BigInteger(), nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("pause_reason", sa.String(255), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auto_deposit_batches"),
    )
    op.create_index(
        "ix_auto_deposit_batches_bookmaker_id", "auto_deposit_batches", ["bookmaker_id"]
    )
    op.create_index("ix_auto_deposit_batches_status", "auto_deposit_batches", ["status"])

    op.create_table(
        "auto_deposit_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("payer_id", sa.String(32), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("nickname", sa.String(128), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("processed_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["auto_deposit_batches.id"],
            name="fk_auto_deposit_items_batch_id_auto_deposit_batches",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auto_deposit_items"),
        sa.UniqueConstraint("batch_id", "payer_id", name="uq_auto_deposit_items_batch_payer"),
    )
    op.create_index("ix_auto_deposit_items_batch_id", "auto_deposit_items", ["batch_id"])
    op.create_index("ix_auto_deposit_items_payer_id", "auto_deposit_items", ["payer_id"])
    op.create_index("ix_auto_deposit_items_status", "auto_deposit_items", ["status"])


def downgrade() -> None:
    op.drop_table("auto_deposit_items")
    op.drop_table("auto_deposit_batches")

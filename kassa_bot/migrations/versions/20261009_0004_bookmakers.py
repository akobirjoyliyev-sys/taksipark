"""bookmakers (bir nechta Mob-Cash kassa) + webapp

Revision ID: 0004_bookmakers
Revises: 0003_p2p_target
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_bookmakers"
down_revision: str | None = "0003_p2p_target"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "bookmakers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("cashbox_code", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(128), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False, server_default="—"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_bookmakers"),
        sa.UniqueConstraint("cashbox_code", "login", name="uq_bookmakers_code_login"),
    )
    for table in ("p2p_deposits", "mobcash_withdrawals"):
        op.add_column(table, sa.Column("bookmaker_id", sa.BigInteger()))
        op.create_foreign_key(
            f"fk_{table}_bookmaker_id_bookmakers",
            table,
            "bookmakers",
            ["bookmaker_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_bookmaker_id", table, ["bookmaker_id"])
    op.add_column(
        "users",
        sa.Column(
            "payer_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "payer_ids")
    for table in ("p2p_deposits", "mobcash_withdrawals"):
        op.drop_index(f"ix_{table}_bookmaker_id", table_name=table)
        op.drop_constraint(f"fk_{table}_bookmaker_id_bookmakers", table, type_="foreignkey")
        op.drop_column(table, "bookmaker_id")
    op.drop_table("bookmakers")

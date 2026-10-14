"""mobcash, p2p deposits, userbot

Revision ID: 0002_mobcash_p2p
Revises: 0001_initial
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_mobcash_p2p"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)
TS = sa.DateTime(timezone=True)
ENUM = sa.String(32)


def _created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False)


def _updated() -> sa.Column:
    return sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.add_column("users", sa.Column("mobcash_payer_id", sa.String(32)))
    op.add_column("users", sa.Column("payout_card_number", sa.String(19)))

    op.create_table(
        "p2p_cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(19), nullable=False),
        sa.Column("holder", sa.String(128), nullable=False, server_default=""),
        sa.Column("bank", sa.String(32), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_p2p_cards"),
        sa.UniqueConstraint("number", name="uq_p2p_cards_number"),
    )

    op.create_table(
        "userbot_accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger()),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("session_encrypted", sa.Text(), nullable=False),
        sa.Column("status", ENUM, nullable=False, server_default="active"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("last_seen_at", TS),
        sa.Column("added_by", sa.BigInteger()),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_userbot_accounts"),
        sa.UniqueConstraint("phone", name="uq_userbot_accounts_phone"),
    )

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger()),
        sa.Column("owner_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("card_last4", sa.String(4)),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", ENUM, nullable=False, server_default="unmatched"),
        sa.Column("deposit_id", sa.BigInteger()),
        sa.Column("message_date", TS),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_bank_transactions"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["userbot_accounts.id"],
            name="fk_bank_transactions_account_id_userbot_accounts",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "owner_tg_id", "source_chat_id", "message_id", name="uq_bank_transactions_message"
        ),
    )
    op.create_index("ix_bank_transactions_account_id", "bank_transactions", ["account_id"])
    op.create_index("ix_bank_transactions_status", "bank_transactions", ["status"])
    op.create_index("ix_bank_transactions_deposit_id", "bank_transactions", ["deposit_id"])

    op.create_table(
        "p2p_deposits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("payer_id", sa.String(32), nullable=False),
        sa.Column("payer_nickname", sa.String(128)),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("unique_amount", MONEY, nullable=False),
        sa.Column("credit_amount", MONEY),
        sa.Column("card_id", sa.BigInteger()),
        sa.Column("status", ENUM, nullable=False, server_default="pending"),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("paid_at", TS),
        sa.Column("credited_at", TS),
        sa.Column("bank_tx_id", sa.BigInteger()),
        sa.Column("credit_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500)),
        sa.Column("mobcash_result", postgresql.JSONB()),
        sa.Column("chat_message_id", sa.BigInteger()),
        sa.Column("reviewed_by", sa.BigInteger()),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_p2p_deposits"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_p2p_deposits_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["p2p_cards.id"],
            name="fk_p2p_deposits_card_id_p2p_cards",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bank_tx_id"],
            ["bank_transactions.id"],
            name="fk_p2p_deposits_bank_tx_id_bank_transactions",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("bank_tx_id", name="uq_p2p_deposits_bank_tx_id"),
    )
    op.create_index("ix_p2p_deposits_user_id", "p2p_deposits", ["user_id"])
    op.create_index("ix_p2p_deposits_status", "p2p_deposits", ["status"])
    op.create_index("ix_p2p_deposits_expires_at", "p2p_deposits", ["expires_at"])
    op.create_index(
        "uq_p2p_deposits_pending_amount",
        "p2p_deposits",
        ["unique_amount"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "mobcash_withdrawals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("payer_id", sa.String(32), nullable=False),
        sa.Column("code_mask", sa.String(32), nullable=False, server_default=""),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("fee", MONEY, nullable=False, server_default="0"),
        sa.Column("payout_amount", MONEY, nullable=False),
        sa.Column("card_number", sa.String(19), nullable=False),
        sa.Column("status", ENUM, nullable=False, server_default="awaiting_payout"),
        sa.Column("mobcash_result", postgresql.JSONB()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("processed_by", sa.BigInteger()),
        sa.Column("paid_at", TS),
        sa.Column("comment", sa.String(255)),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_mobcash_withdrawals"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_mobcash_withdrawals_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_mobcash_withdrawals_user_id", "mobcash_withdrawals", ["user_id"])
    op.create_index("ix_mobcash_withdrawals_status", "mobcash_withdrawals", ["status"])


def downgrade() -> None:
    op.drop_table("mobcash_withdrawals")
    op.drop_index("uq_p2p_deposits_pending_amount", table_name="p2p_deposits")
    op.drop_table("p2p_deposits")
    op.drop_table("bank_transactions")
    op.drop_table("userbot_accounts")
    op.drop_table("p2p_cards")
    op.drop_column("users", "payout_card_number")
    op.drop_column("users", "mobcash_payer_id")

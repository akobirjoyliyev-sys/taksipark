"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(18, 2)
TS = sa.DateTime(timezone=True)
ENUM = sa.String(32)


def _created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False)


def _updated() -> sa.Column:
    return sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False)


def _money(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(name, MONEY, nullable=nullable, server_default="0" if default else None)


IMMUTABLE_TABLES = ("ledger_entries", "audit_logs", "withdrawal_status_history")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("last_name", sa.String(128)),
        sa.Column("phone", sa.String(20)),
        sa.Column("contact_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("onboarding_done", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("language", sa.String(8), server_default="uz", nullable=False),
        sa.Column("is_banned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ban_reason", sa.String(255)),
        sa.Column("referrer_id", sa.BigInteger()),
        sa.Column("last_seen_at", TS, server_default=sa.func.now(), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        sa.ForeignKeyConstraint(
            ["referrer_id"], ["users.id"], name="fk_users_referrer_id_users", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "wallets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        _money("available"),
        _money("blocked"),
        _money("bonus_balance"),
        _money("total_deposit"),
        _money("total_withdraw"),
        _money("referral_earned"),
        _money("referral_withdrawn"),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_wallets"),
        sa.UniqueConstraint("user_id", name="uq_wallets_user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_wallets_user_id_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("available >= 0", name="ck_wallets_available_non_negative"),
        sa.CheckConstraint("blocked >= 0", name="ck_wallets_blocked_non_negative"),
        sa.CheckConstraint("bonus_balance >= 0", name="ck_wallets_bonus_non_negative"),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("account", ENUM, nullable=False),
        sa.Column("direction", ENUM, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("balance_after", MONEY),
        sa.Column("reason", ENUM, nullable=False),
        sa.Column("status", ENUM, server_default="completed", nullable=False),
        sa.Column("reference_type", sa.String(32)),
        sa.Column("reference_id", sa.String(64)),
        sa.Column("external_tx_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger()),
        sa.Column("comment", sa.Text()),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_entries"),
        sa.UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ledger_entries_user_id_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
    )
    op.create_index("ix_ledger_entries_user_id", "ledger_entries", ["user_id"])
    op.create_index("ix_ledger_entries_reason", "ledger_entries", ["reason"])
    op.create_index("ix_ledger_entries_created_at", "ledger_entries", ["created_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        _money("fee"),
        _money("credited_amount"),
        sa.Column("currency", sa.String(3), server_default="UZS", nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("external_id", sa.String(128)),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("is_test", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("paid_at", TS),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("chat_message_id", sa.BigInteger()),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("ref", name="uq_payments_ref"),
        sa.UniqueConstraint("provider", "external_id", name="uq_payments_provider_ext"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_payments_user_id_users", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_expires_at", "payments", ["expires_at"])

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("kind", ENUM, nullable=False),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_events"),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_events_event"),
    )
    op.create_index("ix_webhook_events_reference", "webhook_events", ["reference"])

    op.create_table(
        "payout_cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("masked_pan", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_payout_cards"),
        sa.UniqueConstraint("provider", "token", name="uq_payout_cards_token"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_payout_cards_user_id_users", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_payout_cards_user_id", "payout_cards", ["user_id"])

    op.create_table(
        "mass_payout_batches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("file_name", sa.String(128), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("approved_by", sa.BigInteger()),
        sa.Column("approved_at", TS),
        sa.Column("completed_at", TS),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default="0", nullable=False),
        _money("total_amount"),
        sa.Column("paid_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_mass_payout_batches"),
    )
    op.create_index("ix_mass_payout_batches_status", "mass_payout_batches", ["status"])

    op.create_table(
        "withdrawals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", ENUM, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("card_id", sa.BigInteger()),
        sa.Column("card_mask", sa.String(32), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        _money("fee"),
        sa.Column("net_amount", MONEY, nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("manual_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("external_id", sa.String(128)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", TS),
        sa.Column("last_error", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("processed_by", sa.BigInteger()),
        sa.Column("processed_at", TS),
        sa.Column("paid_at", TS),
        sa.Column("batch_id", sa.BigInteger()),
        sa.Column("is_test", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_withdrawals"),
        sa.UniqueConstraint("ref", name="uq_withdrawals_ref"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_withdrawals_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["payout_cards.id"],
            name="fk_withdrawals_card_id_payout_cards",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["mass_payout_batches.id"],
            name="fk_withdrawals_batch_id_mass_payout_batches",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_withdrawals_user_id", "withdrawals", ["user_id"])
    op.create_index("ix_withdrawals_status", "withdrawals", ["status"])
    op.create_index("ix_withdrawals_next_attempt_at", "withdrawals", ["next_attempt_at"])
    op.create_index("ix_withdrawals_batch_id", "withdrawals", ["batch_id"])

    op.create_table(
        "withdrawal_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("withdrawal_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger()),
        sa.Column("actor_role", sa.String(16), server_default="system", nullable=False),
        sa.Column("comment", sa.Text()),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_withdrawal_status_history"),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["withdrawals.id"],
            name="fk_withdrawal_status_history_withdrawal_id_withdrawals",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_withdrawal_status_history_withdrawal_id",
        "withdrawal_status_history",
        ["withdrawal_id"],
    )

    op.create_table(
        "mass_payout_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("recipient_telegram_id", sa.BigInteger()),
        sa.Column("user_id", sa.BigInteger()),
        sa.Column("amount", MONEY),
        sa.Column("provider", sa.String(32)),
        sa.Column("fingerprint", sa.String(128)),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("error", sa.String(255)),
        sa.Column("withdrawal_id", sa.BigInteger()),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_mass_payout_items"),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["mass_payout_batches.id"],
            name="fk_mass_payout_items_batch_id_mass_payout_batches",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_mass_payout_items_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["withdrawals.id"],
            name="fk_mass_payout_items_withdrawal_id_withdrawals",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_mass_payout_items_batch_id", "mass_payout_items", ["batch_id"])
    op.create_index("ix_mass_payout_items_fingerprint", "mass_payout_items", ["fingerprint"])
    op.create_index("ix_mass_payout_items_withdrawal_id", "mass_payout_items", ["withdrawal_id"])

    op.create_table(
        "promo_codes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bonus_type", ENUM, nullable=False),
        sa.Column("bonus_value", MONEY, nullable=False),
        sa.Column("max_bonus", MONEY),
        _money("min_deposit"),
        sa.Column("total_limit", sa.Integer()),
        sa.Column("per_user_limit", sa.Integer(), server_default="1", nullable=False),
        sa.Column("used_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_from", TS),
        sa.Column("valid_until", TS),
        sa.Column("created_by", sa.BigInteger()),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_promo_codes"),
        sa.UniqueConstraint("code", name="uq_promo_codes_code"),
    )

    op.create_table(
        "promo_activations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("promo_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("payment_id", sa.BigInteger()),
        _money("bonus_amount"),
        _created(),
        sa.Column("applied_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_promo_activations"),
        sa.ForeignKeyConstraint(
            ["promo_id"],
            ["promo_codes.id"],
            name="fk_promo_activations_promo_id_promo_codes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_promo_activations_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_promo_activations_payment_id_payments",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_promo_activations_promo_id", "promo_activations", ["promo_id"])
    op.create_index("ix_promo_activations_user_id", "promo_activations", ["user_id"])

    op.create_table(
        "vip_levels",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("min_total_deposit", MONEY, nullable=False),
        sa.Column("bonus_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_vip_levels"),
    )

    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_id", sa.BigInteger(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("deposit_amount", MONEY, nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_referral_rewards"),
        sa.UniqueConstraint("payment_id", name="uq_referral_rewards_payment_id"),
        sa.ForeignKeyConstraint(
            ["referrer_id"],
            ["users.id"],
            name="fk_referral_rewards_referrer_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["referred_id"],
            ["users.id"],
            name="fk_referral_rewards_referred_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_referral_rewards_payment_id_payments",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_referral_rewards_referrer_id", "referral_rewards", ["referrer_id"])
    op.create_index("ix_referral_rewards_referred_id", "referral_rewards", ["referred_id"])
    op.create_index("ix_referral_rewards_created_at", "referral_rewards", ["created_at"])

    op.create_table(
        "admins",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("role", ENUM, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("from_env", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("added_by", sa.BigInteger()),
        sa.Column("note", sa.String(128)),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_admins"),
        sa.UniqueConstraint("telegram_id", name="uq_admins_telegram_id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger()),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("comment", sa.Text()),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_actor_telegram_id", "audit_logs", ["actor_telegram_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.BigInteger()),
        _updated(),
        sa.PrimaryKeyConstraint("key", name="pk_system_settings"),
    )

    op.create_table(
        "required_channels",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger()),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("invite_link", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bot_is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("checked_at", TS),
        _created(),
        _updated(),
        sa.PrimaryKeyConstraint("id", name="pk_required_channels"),
        sa.UniqueConstraint("chat_id", name="uq_required_channels_chat_id"),
        sa.UniqueConstraint("username", name="uq_required_channels_username"),
    )

    op.create_table(
        "join_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_title", sa.String(128)),
        sa.Column("user_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("full_name", sa.String(128)),
        sa.Column("status", ENUM, nullable=False),
        sa.Column("processed_by", sa.BigInteger()),
        sa.Column("processed_at", TS),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_join_requests"),
    )
    op.create_index("ix_join_requests_chat_user", "join_requests", ["chat_id", "user_telegram_id"])
    op.create_index("ix_join_requests_status", "join_requests", ["status"])

    # Append-only jadvallar: UPDATE va DELETE taqiqlanadi.
    op.execute("""
        CREATE OR REPLACE FUNCTION kassa_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Jadval % faqat qo‘shish uchun (append-only)', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """)
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kassa_forbid_mutation();"
        )


def downgrade() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};")
    op.execute("DROP FUNCTION IF EXISTS kassa_forbid_mutation();")
    for table in (
        "join_requests",
        "required_channels",
        "system_settings",
        "audit_logs",
        "admins",
        "referral_rewards",
        "vip_levels",
        "promo_activations",
        "promo_codes",
        "mass_payout_items",
        "withdrawal_status_history",
        "withdrawals",
        "mass_payout_batches",
        "payout_cards",
        "webhook_events",
        "payments",
        "ledger_entries",
        "wallets",
        "users",
    ):
        op.drop_table(table)

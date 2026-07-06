"""Persist immutable point-in-time universe eligibility snapshots.

Revision ID: 0015_universe_eligibility
Revises: 0014_ui_exposure_ledger
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0015_universe_eligibility"
down_revision = "0014_ui_exposure_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market.universe_eligibility_snapshots (
                id UUID NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL,
                mode VARCHAR(20) NOT NULL,
                eligibility_schema VARCHAR(80) NOT NULL,
                policy JSONB NOT NULL,
                policy_hash VARCHAR(64) NOT NULL,
                decisions JSONB NOT NULL,
                selected_symbols JSONB NOT NULL,
                total_instruments INTEGER NOT NULL,
                ticker_count INTEGER NOT NULL,
                eligible_before_limit INTEGER NOT NULL,
                selected_count INTEGER NOT NULL,
                release_version VARCHAR(40) NOT NULL,
                record_hash VARCHAR(64) NOT NULL,
                CONSTRAINT pk_universe_eligibility_snapshots PRIMARY KEY (id),
                CONSTRAINT uq_universe_eligibility_snapshots_record_hash UNIQUE (record_hash),
                CONSTRAINT ck_universe_eligibility_snapshots_mode
                    CHECK (mode IN ('static', 'dynamic')),
                CONSTRAINT ck_universe_eligibility_snapshots_counts_nonnegative
                    CHECK (
                        total_instruments >= 0
                        AND ticker_count >= 0
                        AND eligible_before_limit >= 0
                        AND selected_count >= 0
                    ),
                CONSTRAINT ck_universe_eligibility_snapshots_count_order
                    CHECK (
                        selected_count <= eligible_before_limit
                        AND eligible_before_limit <= total_instruments
                    ),
                CONSTRAINT ck_universe_eligibility_snapshots_policy_hash_length
                    CHECK (length(policy_hash) = 64),
                CONSTRAINT ck_universe_eligibility_snapshots_record_hash_length
                    CHECK (length(record_hash) = 64),
                CONSTRAINT ck_universe_eligibility_snapshots_policy_object
                    CHECK (jsonb_typeof(policy) = 'object'),
                CONSTRAINT ck_universe_eligibility_snapshots_decisions_array
                    CHECK (jsonb_typeof(decisions) = 'array'),
                CONSTRAINT ck_universe_eligibility_snapshots_selected_array
                    CHECK (jsonb_typeof(selected_symbols) = 'array'),
                CONSTRAINT ck_universe_eligibility_snapshots_record_time
                    CHECK (observed_at <= recorded_at + interval '5 seconds')
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_universe_eligibility_observed
            ON market.universe_eligibility_snapshots (observed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION market.reject_universe_eligibility_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'universe eligibility snapshots are immutable';
            END;
            $$
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_universe_eligibility_immutable
            ON market.universe_eligibility_snapshots
            """
        )
    )
    op.execute(
        text(
            """
            CREATE TRIGGER trg_universe_eligibility_immutable
            BEFORE UPDATE OR DELETE ON market.universe_eligibility_snapshots
            FOR EACH ROW EXECUTE FUNCTION market.reject_universe_eligibility_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_universe_eligibility_immutable
            ON market.universe_eligibility_snapshots
            """
        )
    )
    op.execute(text("DROP FUNCTION IF EXISTS market.reject_universe_eligibility_mutation()"))
    op.execute(text("DROP TABLE IF EXISTS market.universe_eligibility_snapshots"))

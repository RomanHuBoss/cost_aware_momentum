"""Persist immutable ex-ante operator-selection experiment opportunities.

Revision ID: 0011_selection_experiment
Revises: 0010_orderbook_exec_evidence
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0011_selection_experiment"
down_revision = "0010_orderbook_exec_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS advisory.selection_experiment_ledger (
                id UUID NOT NULL,
                plan_id UUID NOT NULL,
                signal_id UUID NOT NULL,
                profile_id UUID NOT NULL,
                plan_version INTEGER NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                eligible BOOLEAN NOT NULL,
                eligibility_status VARCHAR(40) NOT NULL,
                ledger_schema VARCHAR(80) NOT NULL,
                feature_schema VARCHAR(80) NOT NULL,
                features JSONB NOT NULL,
                feature_hash VARCHAR(64) NOT NULL,
                release_version VARCHAR(40) NOT NULL,
                CONSTRAINT pk_selection_experiment_ledger PRIMARY KEY (id),
                CONSTRAINT uq_selection_experiment_plan UNIQUE (plan_id),
                CONSTRAINT fk_selection_experiment_plan
                    FOREIGN KEY(plan_id) REFERENCES advisory.execution_plans (id),
                CONSTRAINT fk_selection_experiment_signal
                    FOREIGN KEY(signal_id) REFERENCES advisory.market_signals (id),
                CONSTRAINT fk_selection_experiment_profile
                    FOREIGN KEY(profile_id) REFERENCES advisory.capital_profiles (id),
                CONSTRAINT ck_selection_experiment_plan_version_positive CHECK (plan_version > 0),
                CONSTRAINT ck_selection_experiment_hash_length CHECK (length(feature_hash) = 64)
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_selection_experiment_observed
            ON advisory.selection_experiment_ledger (observed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_selection_experiment_eligible
            ON advisory.selection_experiment_ledger (eligible, observed_at)
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS advisory.selection_experiment_ledger"))

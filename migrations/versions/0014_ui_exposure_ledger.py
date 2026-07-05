"""Persist immutable operator UI exposure evidence.

Revision ID: 0014_ui_exposure_ledger
Revises: 0013_experiment_preregistration
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0014_ui_exposure_ledger"
down_revision = "0013_experiment_preregistration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS advisory.selection_exposure_ledger (
                id UUID NOT NULL,
                plan_id UUID NOT NULL,
                signal_id UUID NOT NULL,
                profile_id UUID NOT NULL,
                plan_version INTEGER NOT NULL,
                exposed_at TIMESTAMPTZ NOT NULL,
                received_at TIMESTAMPTZ NOT NULL,
                operator_id VARCHAR(80) NOT NULL,
                surface VARCHAR(40) NOT NULL,
                viewport_ratio NUMERIC(20, 12) NOT NULL,
                dwell_ms INTEGER NOT NULL,
                client_event_id UUID NOT NULL,
                page_instance_id UUID NOT NULL,
                exposure_schema VARCHAR(80) NOT NULL,
                evidence_hash VARCHAR(64) NOT NULL,
                release_version VARCHAR(40) NOT NULL,
                CONSTRAINT pk_selection_exposure_ledger PRIMARY KEY (id),
                CONSTRAINT uq_selection_exposure_plan UNIQUE (plan_id),
                CONSTRAINT uq_selection_exposure_client_event UNIQUE (client_event_id),
                CONSTRAINT fk_selection_exposure_plan
                    FOREIGN KEY(plan_id) REFERENCES advisory.execution_plans (id),
                CONSTRAINT fk_selection_exposure_signal
                    FOREIGN KEY(signal_id) REFERENCES advisory.market_signals (id),
                CONSTRAINT fk_selection_exposure_profile
                    FOREIGN KEY(profile_id) REFERENCES advisory.capital_profiles (id),
                CONSTRAINT ck_selection_exposure_plan_version_positive CHECK (plan_version > 0),
                CONSTRAINT ck_selection_exposure_viewport_ratio
                    CHECK (viewport_ratio >= 0.5 AND viewport_ratio <= 1),
                CONSTRAINT ck_selection_exposure_dwell_ms
                    CHECK (dwell_ms >= 1000 AND dwell_ms <= 600000),
                CONSTRAINT ck_selection_exposure_surface
                    CHECK (surface = 'RECOMMENDATION_TILE'),
                CONSTRAINT ck_selection_exposure_hash_length CHECK (length(evidence_hash) = 64),
                CONSTRAINT ck_selection_exposure_time_order
                    CHECK (exposed_at <= received_at + interval '5 seconds'),
                CONSTRAINT ck_selection_exposure_event_age
                    CHECK (exposed_at >= received_at - interval '15 minutes')
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_selection_exposure_exposed
            ON advisory.selection_exposure_ledger (exposed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_selection_exposure_operator
            ON advisory.selection_exposure_ledger (operator_id, exposed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION advisory.reject_selection_exposure_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'selection exposure evidence is immutable';
            END;
            $$
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_selection_exposure_immutable
            ON advisory.selection_exposure_ledger
            """
        )
    )
    op.execute(
        text(
            """
            CREATE TRIGGER trg_selection_exposure_immutable
            BEFORE UPDATE OR DELETE ON advisory.selection_exposure_ledger
            FOR EACH ROW EXECUTE FUNCTION advisory.reject_selection_exposure_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_selection_exposure_immutable
            ON advisory.selection_exposure_ledger
            """
        )
    )
    op.execute(text("DROP FUNCTION IF EXISTS advisory.reject_selection_exposure_mutation()"))
    op.execute(text("DROP TABLE IF EXISTS advisory.selection_exposure_ledger"))

"""Persist append-only research experiment attempts for PBO and DSR governance.

Revision ID: 0012_experiment_selection
Revises: 0011_selection_experiment
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0012_experiment_selection"
down_revision = "0011_selection_experiment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS research.experiment_events (
                id UUID NOT NULL,
                trial_id UUID NOT NULL,
                experiment_family VARCHAR(160) NOT NULL,
                event_sequence INTEGER NOT NULL,
                event_type VARCHAR(20) NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                configuration_hash VARCHAR(64) NOT NULL,
                configuration JSONB NOT NULL,
                evidence JSONB NOT NULL,
                previous_event_hash VARCHAR(64),
                record_hash VARCHAR(64) NOT NULL,
                CONSTRAINT pk_experiment_events PRIMARY KEY (id),
                CONSTRAINT uq_experiment_event_trial_sequence
                    UNIQUE (trial_id, event_sequence),
                CONSTRAINT uq_experiment_events_record_hash UNIQUE (record_hash),
                CONSTRAINT ck_experiment_event_sequence_nonnegative
                    CHECK (event_sequence >= 0),
                CONSTRAINT ck_experiment_configuration_hash_length
                    CHECK (length(configuration_hash) = 64),
                CONSTRAINT ck_experiment_record_hash_length
                    CHECK (length(record_hash) = 64)
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_experiment_event_family_time
            ON research.experiment_events (experiment_family, observed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_experiment_events_trial_id
            ON research.experiment_events (trial_id)
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS research.experiment_events"))

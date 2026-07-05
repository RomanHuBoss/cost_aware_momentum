"""Persist immutable experiment-family preregistrations.

Revision ID: 0013_experiment_preregistration
Revises: 0012_experiment_selection
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0013_experiment_preregistration"
down_revision = "0012_experiment_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS research.experiment_family_registrations (
                experiment_family VARCHAR(160) NOT NULL,
                registered_at TIMESTAMPTZ NOT NULL,
                registration_schema VARCHAR(100) NOT NULL,
                specification JSONB NOT NULL,
                release_version VARCHAR(40) NOT NULL,
                record_hash VARCHAR(64) NOT NULL,
                CONSTRAINT pk_experiment_family_registrations PRIMARY KEY (experiment_family),
                CONSTRAINT uq_experiment_family_registrations_record_hash UNIQUE (record_hash),
                CONSTRAINT ck_experiment_family_registration_record_hash_length
                    CHECK (length(record_hash) = 64)
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_experiment_family_registration_time
            ON research.experiment_family_registrations (registered_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION research.reject_experiment_family_registration_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'experiment family preregistrations are immutable';
            END;
            $$
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_experiment_family_registration_immutable
            ON research.experiment_family_registrations
            """
        )
    )
    op.execute(
        text(
            """
            CREATE TRIGGER trg_experiment_family_registration_immutable
            BEFORE UPDATE OR DELETE ON research.experiment_family_registrations
            FOR EACH ROW EXECUTE FUNCTION research.reject_experiment_family_registration_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_experiment_family_registration_immutable
            ON research.experiment_family_registrations
            """
        )
    )
    op.execute(text("DROP FUNCTION IF EXISTS research.reject_experiment_family_registration_mutation()"))
    op.execute(text("DROP TABLE IF EXISTS research.experiment_family_registrations"))

"""Persist immutable all-opportunity model inference observations.

Revision ID: 0018_inference_observations
Revises: 0017_model_artifact_blobs
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0018_inference_observations"
down_revision = "0017_model_artifact_blobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 creates current ORM metadata on a clean database. Keep this
    # migration idempotent so a fresh install can traverse the released chain.
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS model.model_inference_observations (
                id UUID NOT NULL,
                symbol VARCHAR(40) NOT NULL,
                event_time TIMESTAMPTZ NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                model_version VARCHAR(100) NOT NULL,
                calibration_version VARCHAR(100) NOT NULL,
                feature_schema_version VARCHAR(100) NOT NULL,
                feature_snapshot JSONB NOT NULL,
                directional_predictions JSONB NOT NULL,
                CONSTRAINT pk_model_inference_observations PRIMARY KEY (id),
                CONSTRAINT uq_model_inference_observation
                    UNIQUE (model_version, symbol, event_time),
                CONSTRAINT ck_model_inference_observations_event_not_after_observation
                    CHECK (event_time <= observed_at),
                CONSTRAINT ck_model_inference_observations_model_version_nonempty
                    CHECK (length(model_version) > 0),
                CONSTRAINT ck_model_inference_observations_calibration_version_nonempty
                    CHECK (length(calibration_version) > 0),
                CONSTRAINT ck_model_inference_observations_feature_schema_version_nonempty
                    CHECK (length(feature_schema_version) > 0),
                CONSTRAINT ck_model_inference_observations_feature_snapshot_object
                    CHECK (jsonb_typeof(feature_snapshot) = 'object'),
                CONSTRAINT ck_model_inference_observations_directional_predictions_object
                    CHECK (jsonb_typeof(directional_predictions) = 'object')
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_model_inference_observation_version_observed
            ON model.model_inference_observations (model_version, observed_at)
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION model.reject_model_inference_observation_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'model inference observations are immutable';
            END;
            $$
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_model_inference_observations_immutable
            ON model.model_inference_observations
            """
        )
    )
    op.execute(
        text(
            """
            CREATE TRIGGER trg_model_inference_observations_immutable
            BEFORE UPDATE OR DELETE ON model.model_inference_observations
            FOR EACH ROW EXECUTE FUNCTION model.reject_model_inference_observation_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_model_inference_observations_immutable
            ON model.model_inference_observations
            """
        )
    )
    op.execute(text("DROP FUNCTION IF EXISTS model.reject_model_inference_observation_mutation()"))
    op.execute(text("DROP TABLE IF EXISTS model.model_inference_observations"))

"""Persist immutable model artifact bytes for release-safe recovery.

Revision ID: 0017_model_artifact_blobs
Revises: 0016_universe_replay_asof
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0017_model_artifact_blobs"
down_revision = "0016_universe_replay_asof"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS model.model_artifact_blobs (
                model_registry_id UUID NOT NULL,
                version VARCHAR(80) NOT NULL,
                artifact_sha256 VARCHAR(64) NOT NULL,
                size_bytes BIGINT NOT NULL,
                payload BYTEA NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT pk_model_artifact_blobs PRIMARY KEY (model_registry_id),
                CONSTRAINT uq_model_artifact_blobs_version UNIQUE (version),
                CONSTRAINT fk_model_artifact_blobs_registry
                    FOREIGN KEY (model_registry_id)
                    REFERENCES model.model_registry (id)
                    ON DELETE RESTRICT,
                CONSTRAINT ck_model_artifact_blobs_size_positive
                    CHECK (size_bytes > 0),
                CONSTRAINT ck_model_artifact_blobs_size_limit
                    CHECK (size_bytes <= 268435456),
                CONSTRAINT ck_model_artifact_blobs_sha256_length
                    CHECK (length(artifact_sha256) = 64),
                CONSTRAINT ck_model_artifact_blobs_payload_size
                    CHECK (octet_length(payload) = size_bytes)
            )
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE model.model_artifact_blobs
            ALTER COLUMN created_at SET DEFAULT now()
            """
        )
    )
    op.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION model.reject_model_artifact_blob_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'model artifact blobs are immutable';
            END;
            $$
            """
        )
    )
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_model_artifact_blobs_immutable
            ON model.model_artifact_blobs
            """
        )
    )
    op.execute(
        text(
            """
            CREATE TRIGGER trg_model_artifact_blobs_immutable
            BEFORE UPDATE OR DELETE ON model.model_artifact_blobs
            FOR EACH ROW EXECUTE FUNCTION model.reject_model_artifact_blob_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP TRIGGER IF EXISTS trg_model_artifact_blobs_immutable
            ON model.model_artifact_blobs
            """
        )
    )
    op.execute(text("DROP FUNCTION IF EXISTS model.reject_model_artifact_blob_mutation()"))
    op.execute(text("DROP TABLE IF EXISTS model.model_artifact_blobs"))

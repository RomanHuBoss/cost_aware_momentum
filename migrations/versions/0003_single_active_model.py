"""Enforce one registry-active model at a time.

Revision ID: 0003_single_active_model
Revises: 0002_one_signal_per_symbol
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0003_single_active_model"
down_revision = "0002_one_signal_per_symbol"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS active_rank
                FROM model.model_registry
                WHERE active = TRUE
            )
            UPDATE model.model_registry AS registry
            SET active = FALSE, updated_at = CURRENT_TIMESTAMP
            FROM ranked
            WHERE ranked.active_rank > 1
              AND registry.id = ranked.id
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_model_registry_single_active
            ON model.model_registry (active)
            WHERE active = TRUE
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS model.uq_model_registry_single_active"))

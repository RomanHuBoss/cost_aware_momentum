"""Index point-in-time universe snapshot lookup by mode and commit time.

Revision ID: 0016_universe_replay_asof
Revises: 0015_universe_eligibility
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0016_universe_replay_asof"
down_revision = "0015_universe_eligibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_universe_eligibility_mode_recorded_at
            ON market.universe_eligibility_snapshots (mode, recorded_at)
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP INDEX IF EXISTS market.ix_universe_eligibility_mode_recorded_at
            """
        )
    )

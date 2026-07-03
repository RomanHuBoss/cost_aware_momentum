"""Make candle availability reflect actual database observability.

Revision ID: 0009_candle_receipt_availability
Revises: 0008_outcome_path_unavailable
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0009_candle_receipt_availability"
down_revision = "0008_outcome_path_unavailable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows do not contain their true first receipt timestamp. Moving
    # confirmed candles forward to migration time is deliberately conservative:
    # historical replay before the migration can no longer treat a late backfill
    # as if it had been available at candle close.
    op.execute(
        text(
            """
            UPDATE market.candles
            SET available_at = GREATEST(available_at, CURRENT_TIMESTAMP)
            WHERE confirmed IS TRUE
            """
        )
    )


def downgrade() -> None:
    # The original receipt time was never stored, so the correction is not
    # reversible. Keeping the later timestamp is safer than recreating the known
    # look-ahead defect and remains compatible with the previous application.
    pass

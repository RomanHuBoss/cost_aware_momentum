"""Persist account identity for read-only position snapshots.

Revision ID: 0007_position_account_scope
Revises: 0006_manual_trade_remaining_risk
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0007_position_account_scope"
down_revision = "0006_manual_trade_remaining_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh databases receive the current ORM column/index in revision 0001.
    # IF NOT EXISTS also makes recovery from a partially prepared schema safe.
    op.execute(
        text(
            """
            ALTER TABLE advisory.position_snapshots
            ADD COLUMN IF NOT EXISTS account_id VARCHAR(120)
            """
        )
    )
    op.execute(
        text(
            """
            UPDATE advisory.position_snapshots
            SET account_id = CASE
                WHEN source = 'bybit-read-only' THEN 'bybit-unified'
                ELSE 'legacy-unknown'
            END
            WHERE account_id IS NULL
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE advisory.position_snapshots
            ALTER COLUMN account_id SET NOT NULL
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_position_account_time
            ON advisory.position_snapshots (account_id, source_time)
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS advisory.ix_position_account_time"))
    op.execute(
        text(
            """
            ALTER TABLE advisory.position_snapshots
            DROP COLUMN IF EXISTS account_id
            """
        )
    )

"""Persist account identity for read-only position snapshots.

Revision ID: 0007_position_account_scope
Revises: 0006_manual_trade_remaining_risk
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0007_position_account_scope"
down_revision = "0006_manual_trade_remaining_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "position_snapshots",
        sa.Column("account_id", sa.String(length=120), nullable=True),
        schema="advisory",
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
    op.alter_column(
        "position_snapshots",
        "account_id",
        existing_type=sa.String(length=120),
        nullable=False,
        schema="advisory",
    )
    op.create_index(
        "ix_position_account_time",
        "position_snapshots",
        ["account_id", "source_time"],
        unique=False,
        schema="advisory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_position_account_time",
        table_name="position_snapshots",
        schema="advisory",
    )
    op.drop_column("position_snapshots", "account_id", schema="advisory")

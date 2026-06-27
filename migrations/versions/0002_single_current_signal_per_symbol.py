"""Keep only one current published recommendation per symbol.

Revision ID: 0002_one_signal_per_symbol
Revises: 0001_initial
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0002_one_signal_per_symbol"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


_RANKED_PUBLISHED = """
    SELECT
        id,
        row_number() OVER (
            PARTITION BY symbol
            ORDER BY publish_time DESC, event_time DESC, created_at DESC, id DESC
        ) AS symbol_rank
    FROM advisory.market_signals
    WHERE status = 'PUBLISHED'
"""


def upgrade() -> None:
    bind = op.get_bind()

    # Retire pending plans first, while duplicate signals are still identifiable
    # by their PUBLISHED status.  Plans already in the trade lifecycle are kept.
    bind.execute(
        text(
            f"""
            WITH ranked AS ({_RANKED_PUBLISHED})
            UPDATE advisory.execution_plans AS plan
            SET status = 'SUPERSEDED', updated_at = CURRENT_TIMESTAMP
            FROM ranked
            WHERE ranked.symbol_rank > 1
              AND plan.signal_id = ranked.id
              AND plan.status NOT IN (
                  'ACCEPTED', 'ENTERED', 'PARTIAL', 'CLOSED',
                  'REJECTED', 'EXPIRED'
              )
            """
        )
    )

    bind.execute(
        text(
            f"""
            WITH ranked AS ({_RANKED_PUBLISHED})
            UPDATE advisory.market_signals AS signal
            SET
                status = 'SUPERSEDED',
                invalidation_reason = COALESCE(
                    signal.invalidation_reason,
                    'Заменено более свежей рекомендацией при миграции 0002'
                ),
                updated_at = CURRENT_TIMESTAMP
            FROM ranked
            WHERE ranked.symbol_rank > 1
              AND signal.id = ranked.id
            """
        )
    )

    # IF NOT EXISTS is important because migration 0001 uses current metadata on
    # a fresh installation and may already have created this model index.
    bind.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_market_signal_one_published_per_symbol
            ON advisory.market_signals (symbol)
            WHERE status = 'PUBLISHED'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DROP INDEX IF EXISTS advisory.uq_market_signal_one_published_per_symbol
            """
        )
    )

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0006_manual_trade_remaining_risk"
down_revision = "0005_plan_outcome_invalid_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 creates the current ORM metadata on a fresh database. These
    # guards also recover a database where a previous 0006 attempt added one or
    # both columns before Alembic rolled the revision back/noted no progress.
    op.execute(
        text(
            """
            ALTER TABLE advisory.manual_trades
            ADD COLUMN IF NOT EXISTS initial_stress_loss NUMERIC(28, 12),
            ADD COLUMN IF NOT EXISTS remaining_stress_loss NUMERIC(28, 12)
            """
        )
    )
    op.execute(
        text(
            """
            UPDATE advisory.manual_trades AS trade
            SET initial_stress_loss = COALESCE(
                    trade.initial_stress_loss,
                    CASE
                        WHEN trade.status IN ('OPEN', 'PARTIAL') THEN plan.actual_stress_loss
                        ELSE 0
                    END
                ),
                remaining_stress_loss = COALESCE(
                    trade.remaining_stress_loss,
                    CASE
                        WHEN trade.status IN ('OPEN', 'PARTIAL') AND trade.qty > 0
                            THEN plan.actual_stress_loss * trade.remaining_qty / trade.qty
                        ELSE 0
                    END
                )
            FROM advisory.execution_plans AS plan
            WHERE plan.id = trade.plan_id
              AND (
                  trade.initial_stress_loss IS NULL
                  OR trade.remaining_stress_loss IS NULL
              )
            """
        )
    )
    # Recreate the exact constraints transactionally. This is safe both when
    # current metadata already supplied them and when upgrading an older schema.
    op.execute(
        text(
            """
            ALTER TABLE advisory.manual_trades
            DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_lte_initial,
            DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_non_negative,
            DROP CONSTRAINT IF EXISTS ck_manual_trades_initial_stress_loss_non_negative
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE advisory.manual_trades
            ALTER COLUMN initial_stress_loss SET NOT NULL,
            ALTER COLUMN remaining_stress_loss SET NOT NULL,
            ADD CONSTRAINT ck_manual_trades_initial_stress_loss_non_negative
                CHECK (initial_stress_loss >= 0),
            ADD CONSTRAINT ck_manual_trades_remaining_stress_loss_non_negative
                CHECK (remaining_stress_loss >= 0),
            ADD CONSTRAINT ck_manual_trades_remaining_stress_loss_lte_initial
                CHECK (remaining_stress_loss <= initial_stress_loss)
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            ALTER TABLE advisory.manual_trades
            DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_lte_initial,
            DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_non_negative,
            DROP CONSTRAINT IF EXISTS ck_manual_trades_initial_stress_loss_non_negative,
            DROP COLUMN IF EXISTS remaining_stress_loss,
            DROP COLUMN IF EXISTS initial_stress_loss
            """
        )
    )

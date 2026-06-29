from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0006_manual_trade_remaining_risk"
down_revision = "0005_plan_outcome_invalid_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        ALTER TABLE advisory.manual_trades
        ADD COLUMN initial_stress_loss NUMERIC(28, 12),
        ADD COLUMN remaining_stress_loss NUMERIC(28, 12)
    """))
    op.execute(text("""
        UPDATE advisory.manual_trades AS trade
        SET initial_stress_loss = CASE
                WHEN trade.status IN ('OPEN', 'PARTIAL') THEN plan.actual_stress_loss
                ELSE 0
            END,
            remaining_stress_loss = CASE
                WHEN trade.status IN ('OPEN', 'PARTIAL') AND trade.qty > 0
                    THEN plan.actual_stress_loss * trade.remaining_qty / trade.qty
                ELSE 0
            END
        FROM advisory.execution_plans AS plan
        WHERE plan.id = trade.plan_id
    """))
    op.execute(text("""
        ALTER TABLE advisory.manual_trades
        ALTER COLUMN initial_stress_loss SET NOT NULL,
        ALTER COLUMN remaining_stress_loss SET NOT NULL,
        ADD CONSTRAINT ck_manual_trades_initial_stress_loss_non_negative
            CHECK (initial_stress_loss >= 0),
        ADD CONSTRAINT ck_manual_trades_remaining_stress_loss_non_negative
            CHECK (remaining_stress_loss >= 0),
        ADD CONSTRAINT ck_manual_trades_remaining_stress_loss_lte_initial
            CHECK (remaining_stress_loss <= initial_stress_loss)
    """))


def downgrade() -> None:
    op.execute(text("""
        ALTER TABLE advisory.manual_trades
        DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_lte_initial,
        DROP CONSTRAINT IF EXISTS ck_manual_trades_remaining_stress_loss_non_negative,
        DROP CONSTRAINT IF EXISTS ck_manual_trades_initial_stress_loss_non_negative,
        DROP COLUMN remaining_stress_loss,
        DROP COLUMN initial_stress_loss
    """))

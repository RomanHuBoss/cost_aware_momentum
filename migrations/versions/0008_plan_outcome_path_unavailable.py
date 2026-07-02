"""Allow fail-closed plan outcomes without an entry-aligned price path.

Revision ID: 0008_plan_outcome_path_unavailable
Revises: 0007_position_account_scope
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0008_plan_outcome_path_unavailable"
down_revision = "0007_position_account_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            ALTER TABLE advisory.plan_outcomes
            DROP CONSTRAINT IF EXISTS ck_plan_outcomes_plan_outcome_valuation_status
            """
        )
    )
    op.execute(
        text(
            """
            UPDATE advisory.plan_outcomes AS plan_outcome
            SET valuation_status = 'PATH_UNAVAILABLE',
                gross_pnl = 0,
                estimated_trading_costs = 0,
                estimated_funding_cash_flow = 0,
                estimated_net_pnl = 0,
                counterfactual_r = NULL,
                cost_assumptions = plan_outcome.cost_assumptions || jsonb_build_object(
                    'validation_error',
                    'price path is unavailable from plan.planning_time; '
                    'the stored signal outcome starts at signal.event_time',
                    'price_path_source', 'unavailable_after_signal_anchor',
                    'funding', jsonb_build_object(
                        'source', 'path_unavailable',
                        'settlements', 0,
                        'validation_error',
                        'price path is unavailable from plan.planning_time; '
                        'the stored signal outcome starts at signal.event_time'
                    )
                )
            FROM advisory.execution_plans AS execution_plan
            JOIN advisory.market_signals AS market_signal
              ON market_signal.id = execution_plan.signal_id
            WHERE plan_outcome.plan_id = execution_plan.id
              AND plan_outcome.valuation_status IN ('VALUED', 'FUNDING_UNAVAILABLE')
              AND execution_plan.sizing_snapshot ? 'planning_time'
              AND (execution_plan.sizing_snapshot ->> 'planning_time')::timestamptz
                    > market_signal.event_time
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE advisory.plan_outcomes
            ADD CONSTRAINT ck_plan_outcomes_plan_outcome_valuation_status
            CHECK (
                valuation_status IN (
                    'VALUED', 'NOT_SIZED', 'FUNDING_UNAVAILABLE',
                    'PATH_UNAVAILABLE', 'INVALID_INPUT'
                )
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM advisory.plan_outcomes
                    WHERE valuation_status = 'PATH_UNAVAILABLE'
                ) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade while PATH_UNAVAILABLE plan outcomes exist';
                END IF;
            END
            $$
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE advisory.plan_outcomes
            DROP CONSTRAINT IF EXISTS ck_plan_outcomes_plan_outcome_valuation_status
            """
        )
    )
    op.execute(
        text(
            """
            ALTER TABLE advisory.plan_outcomes
            ADD CONSTRAINT ck_plan_outcomes_plan_outcome_valuation_status
            CHECK (
                valuation_status IN (
                    'VALUED', 'NOT_SIZED', 'FUNDING_UNAVAILABLE', 'INVALID_INPUT'
                )
            )
            """
        )
    )

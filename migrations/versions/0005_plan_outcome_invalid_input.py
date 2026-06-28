"""Allow fail-closed invalid counterfactual plan valuations.

Revision ID: 0005_plan_outcome_invalid_input
Revises: 0004_counterfactual_outcomes
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0005_plan_outcome_invalid_input"
down_revision = "0004_counterfactual_outcomes"
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


def downgrade() -> None:
    op.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM advisory.plan_outcomes
                    WHERE valuation_status = 'INVALID_INPUT'
                ) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade while INVALID_INPUT plan outcomes exist';
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
            CHECK (valuation_status IN ('VALUED', 'NOT_SIZED', 'FUNDING_UNAVAILABLE'))
            """
        )
    )

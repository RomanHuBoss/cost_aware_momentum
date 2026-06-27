"""Store automatic counterfactual outcomes for signals and plan versions.

Revision ID: 0004_counterfactual_outcomes
Revises: 0003_single_active_model
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0004_counterfactual_outcomes"
down_revision = "0003_single_active_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Migration 0001 intentionally creates current metadata on a fresh database.
    # IF NOT EXISTS therefore keeps both a fresh install and an upgrade from 1.5.0
    # reproducible without rewriting the already released initial migration.
    bind.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS advisory.signal_outcomes (
                id UUID NOT NULL,
                signal_id UUID NOT NULL,
                outcome VARCHAR(16) NOT NULL,
                exit_price NUMERIC(28, 12) NOT NULL,
                exit_time TIMESTAMPTZ NOT NULL,
                horizon_end TIMESTAMPTZ NOT NULL,
                source_candle_id BIGINT NOT NULL,
                bars_evaluated INTEGER NOT NULL,
                ambiguous BOOLEAN NOT NULL DEFAULT FALSE,
                evaluation_version VARCHAR(80) NOT NULL,
                resolved_at TIMESTAMPTZ NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                CONSTRAINT pk_signal_outcomes PRIMARY KEY (id),
                CONSTRAINT uq_signal_outcome_signal UNIQUE (signal_id),
                CONSTRAINT fk_signal_outcomes_signal_id_market_signals
                    FOREIGN KEY(signal_id) REFERENCES advisory.market_signals (id),
                CONSTRAINT ck_signal_outcomes_signal_outcome_value
                    CHECK (outcome IN ('TP', 'SL', 'TIMEOUT')),
                CONSTRAINT ck_signal_outcomes_signal_outcome_exit_price_positive
                    CHECK (exit_price > 0),
                CONSTRAINT ck_signal_outcomes_signal_outcome_bars_positive
                    CHECK (bars_evaluated > 0)
            )
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_signal_outcome_resolved
            ON advisory.signal_outcomes (resolved_at)
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_advisory_signal_outcomes_signal_id
            ON advisory.signal_outcomes (signal_id)
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS advisory.plan_outcomes (
                id UUID NOT NULL,
                signal_outcome_id UUID NOT NULL,
                plan_id UUID NOT NULL,
                plan_version INTEGER NOT NULL,
                outcome VARCHAR(16) NOT NULL,
                valuation_status VARCHAR(24) NOT NULL,
                qty NUMERIC(28, 12) NOT NULL,
                entry_price NUMERIC(28, 12) NOT NULL,
                exit_price NUMERIC(28, 12) NOT NULL,
                gross_pnl NUMERIC(28, 12) NOT NULL,
                estimated_trading_costs NUMERIC(28, 12) NOT NULL,
                estimated_funding_cash_flow NUMERIC(28, 12) NOT NULL,
                estimated_net_pnl NUMERIC(28, 12) NOT NULL,
                counterfactual_r NUMERIC(20, 12),
                cost_assumptions JSONB NOT NULL DEFAULT '{}'::jsonb,
                resolved_at TIMESTAMPTZ NOT NULL,
                CONSTRAINT pk_plan_outcomes PRIMARY KEY (id),
                CONSTRAINT uq_plan_outcome_plan UNIQUE (plan_id),
                CONSTRAINT fk_plan_outcomes_signal_outcome_id_signal_outcomes
                    FOREIGN KEY(signal_outcome_id) REFERENCES advisory.signal_outcomes (id),
                CONSTRAINT fk_plan_outcomes_plan_id_execution_plans
                    FOREIGN KEY(plan_id) REFERENCES advisory.execution_plans (id),
                CONSTRAINT ck_plan_outcomes_plan_outcome_value
                    CHECK (outcome IN ('TP', 'SL', 'TIMEOUT')),
                CONSTRAINT ck_plan_outcomes_plan_outcome_valuation_status
                    CHECK (valuation_status IN ('VALUED', 'NOT_SIZED', 'FUNDING_UNAVAILABLE')),
                CONSTRAINT ck_plan_outcomes_plan_outcome_qty_non_negative
                    CHECK (qty >= 0),
                CONSTRAINT ck_plan_outcomes_plan_outcome_prices_positive
                    CHECK (entry_price > 0 AND exit_price > 0)
            )
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_plan_outcome_signal_outcome
            ON advisory.plan_outcomes (signal_outcome_id)
            """
        )
    )
    bind.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_advisory_plan_outcomes_plan_id
            ON advisory.plan_outcomes (plan_id)
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS advisory.plan_outcomes"))
    op.execute(text("DROP TABLE IF EXISTS advisory.signal_outcomes"))

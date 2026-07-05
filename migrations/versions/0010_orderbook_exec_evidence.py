"""Persist point-in-time orderbook depth for advisory execution evidence.

Revision ID: 0010_orderbook_exec_evidence
Revises: 0009_candle_receipt_availability
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0010_orderbook_exec_evidence"
down_revision = "0009_candle_receipt_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migration 0001 intentionally creates current metadata on a fresh database.
    # IF NOT EXISTS therefore supports both a clean install and an upgrade from
    # an already released schema without rewriting historical migrations.
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS market.orderbook_snapshots (
                id BIGSERIAL NOT NULL,
                symbol VARCHAR(40) NOT NULL,
                source_time TIMESTAMPTZ NOT NULL,
                system_time TIMESTAMPTZ NOT NULL,
                received_at TIMESTAMPTZ NOT NULL,
                update_id BIGINT NOT NULL,
                sequence BIGINT NOT NULL,
                depth INTEGER NOT NULL,
                best_bid NUMERIC(28, 12) NOT NULL,
                best_ask NUMERIC(28, 12) NOT NULL,
                bids JSONB NOT NULL,
                asks JSONB NOT NULL,
                raw JSONB NOT NULL DEFAULT '{}'::jsonb,
                CONSTRAINT pk_orderbook_snapshots PRIMARY KEY (id),
                CONSTRAINT uq_orderbook_symbol_source_update UNIQUE (symbol, source_time, update_id),
                CONSTRAINT ck_orderbook_depth_positive CHECK (depth > 0),
                CONSTRAINT ck_orderbook_prices_positive CHECK (best_bid > 0 AND best_ask > 0),
                CONSTRAINT ck_orderbook_not_crossed CHECK (best_ask >= best_bid)
            )
            """
        )
    )
    op.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_orderbook_symbol_source_time
            ON market.orderbook_snapshots (symbol, source_time)
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS market.orderbook_snapshots"))

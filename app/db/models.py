from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(28, 12)
RATE = Numeric(20, 12)


class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"
    __table_args__ = ({"schema": "reference"},)

    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), default="linear", nullable=False)
    base_coin: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_coin: Mapped[str] = mapped_column(String(20), nullable=False)
    settle_coin: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    launch_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_pre_listing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class InstrumentSpecHistory(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "instrument_spec_history"
    __table_args__ = (
        UniqueConstraint("symbol", "valid_from", name="uq_spec_symbol_valid_from"),
        {"schema": "reference"},
    )

    symbol: Mapped[str] = mapped_column(ForeignKey("reference.instruments.symbol"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tick_size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty_step: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    min_qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_qty: Mapped[Decimal | None] = mapped_column(MONEY)
    min_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_leverage: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    funding_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "open_time", "price_type", name="uq_candle_natural"),
        Index("ix_candles_symbol_open_time", "symbol", "open_time"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_type: Mapped[str] = mapped_column(String(20), default="last", nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    volume: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    turnover: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ingestion_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="bybit_v5", nullable=False)


class TickerSnapshot(Base):
    __tablename__ = "ticker_snapshots"
    __table_args__ = (Index("ix_ticker_symbol_source_time", "symbol", "source_time"), {"schema": "market"})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(MONEY)
    index_price: Mapped[Decimal | None] = mapped_column(MONEY)
    bid_price: Mapped[Decimal | None] = mapped_column(MONEY)
    ask_price: Mapped[Decimal | None] = mapped_column(MONEY)
    turnover_24h: Mapped[Decimal | None] = mapped_column(MONEY)
    volume_24h: Mapped[Decimal | None] = mapped_column(MONEY)
    open_interest: Mapped[Decimal | None] = mapped_column(MONEY)
    funding_rate: Mapped[Decimal | None] = mapped_column(RATE)
    next_funding_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class FundingRate(Base):
    __tablename__ = "funding"
    __table_args__ = (
        UniqueConstraint("symbol", "funding_time", name="uq_funding_symbol_time"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)


class OpenInterest(Base):
    __tablename__ = "open_interest"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "event_time", name="uq_oi_natural"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class ModelRegistry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_registry"
    __table_args__ = (
        Index(
            "uq_model_registry_single_active",
            "active",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        {"schema": "model"},
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    model_type: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    feature_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    calibration_version: Mapped[str | None] = mapped_column(String(80))
    training_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    training_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class CapitalProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "capital_profiles"
    __table_args__ = ({"schema": "advisory"},)

    user_id: Mapped[str] = mapped_column(String(80), default="local-operator", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    allocated_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    risk_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    max_total_risk_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    default_leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    max_leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    margin_reserve_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    source_account_id: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capital_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AccountEquitySnapshot(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "account_equity_snapshots"
    __table_args__ = (Index("ix_equity_account_time", "account_id", "source_time"), {"schema": "advisory"})

    account_id: Mapped[str] = mapped_column(String(120), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    available_margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    day_start_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quality_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class MarketSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "market_signals"
    __table_args__ = (
        UniqueConstraint("natural_key", name="uq_market_signal_natural_key"),
        Index("ix_market_signal_active", "status", "expires_at"),
        Index(
            "uq_market_signal_one_published_per_symbol",
            "symbol",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
        {"schema": "advisory"},
    )

    natural_key: Mapped[str] = mapped_column(String(180), nullable=False)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CANDIDATE")
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    publish_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_reference: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    take_profit_1: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    take_profit_2: Mapped[Decimal | None] = mapped_column(MONEY)
    tp1_weight: Mapped[Decimal] = mapped_column(RATE, default=Decimal("1"), nullable=False)
    p_tp: Mapped[float] = mapped_column(Float, nullable=False)
    p_sl: Mapped[float] = mapped_column(Float, nullable=False)
    p_timeout: Mapped[float] = mapped_column(Float, nullable=False)
    gross_rr: Mapped[float] = mapped_column(Float, nullable=False)
    net_rr: Mapped[float] = mapped_column(Float, nullable=False)
    net_ev_r: Mapped[float] = mapped_column(Float, nullable=False)
    gross_edge_rate: Mapped[float] = mapped_column(Float, nullable=False)
    fee_rate_round_trip: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_rate: Mapped[float] = mapped_column(Float, nullable=False)
    funding_rate_scenario: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stress_downside_rate: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    calibration_version: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    feature_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    invalidation_reason: Mapped[str | None] = mapped_column(Text)

    plans: Mapped[list[ExecutionPlan]] = relationship(back_populates="signal")


class ExecutionPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "execution_plans"
    __table_args__ = (
        UniqueConstraint("signal_id", "profile_id", "version", name="uq_plan_signal_profile_version"),
        Index("ix_execution_plan_status", "status", "created_at"),
        {"schema": "advisory"},
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.market_signals.id"), nullable=False, index=True
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.capital_profiles.id"), nullable=False, index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("advisory.execution_plans.id"))
    effective_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    capital_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    risk_budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    actual_stress_loss: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty_raw: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    margin_estimate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    liquidation_buffer_rate: Mapped[float] = mapped_column(Float, nullable=False)
    limiting_cap: Mapped[str | None] = mapped_column(String(60))
    primary_warning: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    sizing_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    signal: Mapped[MarketSignal] = relationship(back_populates="plans")
    profile: Mapped[CapitalProfile] = relationship()


class SignalOutcome(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "signal_outcomes"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signal_outcome_signal"),
        CheckConstraint("outcome IN ('TP', 'SL', 'TIMEOUT')", name="signal_outcome_value"),
        CheckConstraint("exit_price > 0", name="signal_outcome_exit_price_positive"),
        CheckConstraint("bars_evaluated > 0", name="signal_outcome_bars_positive"),
        Index("ix_signal_outcome_resolved", "resolved_at"),
        {"schema": "advisory"},
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.market_signals.id"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_candle_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bars_evaluated: Mapped[int] = mapped_column(Integer, nullable=False)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evaluation_version: Mapped[str] = mapped_column(String(80), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PlanOutcome(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "plan_outcomes"
    __table_args__ = (
        UniqueConstraint("plan_id", name="uq_plan_outcome_plan"),
        CheckConstraint("outcome IN ('TP', 'SL', 'TIMEOUT')", name="plan_outcome_value"),
        CheckConstraint(
            "valuation_status IN ('VALUED', 'NOT_SIZED', 'FUNDING_UNAVAILABLE', 'INVALID_INPUT')",
            name="plan_outcome_valuation_status",
        ),
        CheckConstraint("qty >= 0", name="plan_outcome_qty_non_negative"),
        CheckConstraint("entry_price > 0 AND exit_price > 0", name="plan_outcome_prices_positive"),
        Index("ix_plan_outcome_signal_outcome", "signal_outcome_id"),
        {"schema": "advisory"},
    )

    signal_outcome_id: Mapped[UUID] = mapped_column(ForeignKey("advisory.signal_outcomes.id"), nullable=False)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.execution_plans.id"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    valuation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    estimated_trading_costs: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    estimated_funding_cash_flow: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    estimated_net_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    counterfactual_r: Mapped[Decimal | None] = mapped_column(RATE)
    cost_assumptions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatorDecision(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "operator_decisions"
    __table_args__ = (UniqueConstraint("plan_id", name="uq_decision_plan"), {"schema": "advisory"})

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("advisory.execution_plans.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    comment: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[str] = mapped_column(String(80), default="local-operator", nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ManualTrade(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "manual_trades"
    __table_args__ = (
        CheckConstraint(
            "initial_stress_loss >= 0",
            name="initial_stress_loss_non_negative",
        ),
        CheckConstraint(
            "remaining_stress_loss >= 0",
            name="remaining_stress_loss_non_negative",
        ),
        CheckConstraint(
            "remaining_stress_loss <= initial_stress_loss",
            name="remaining_stress_loss_lte_initial",
        ),
        {"schema": "advisory"},
    )

    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.execution_plans.id"), nullable=False, unique=True
    )
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    initial_stress_loss: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    remaining_stress_loss: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    funding_cash_flow: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Fill(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "fills"
    __table_args__ = ({"schema": "advisory"},)

    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("advisory.manual_trades.id"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    fill_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    funding: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PositionSnapshot(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "position_snapshots"
    __table_args__ = (Index("ix_position_symbol_time", "symbol", "source_time"), {"schema": "advisory"})

    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    avg_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    mark_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)


class UIGlossary(Base):
    __tablename__ = "ui_glossary"
    __table_args__ = (
        UniqueConstraint("help_key", "locale", "version", name="uq_glossary_key_locale_version"),
        {"schema": "advisory"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    help_key: Mapped[str] = mapped_column(String(80), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="ru")
    short_text: Mapped[str] = mapped_column(Text, nullable=False)
    long_text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OperatorPreference(Base, TimestampMixin):
    __tablename__ = "operator_preferences"
    __table_args__ = ({"schema": "advisory"},)

    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    active_profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("advisory.capital_profiles.id"))
    locale: Mapped[str] = mapped_column(String(10), default="ru", nullable=False)
    tooltip_mode: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    compact_view: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditEvent(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_audit_entity_time", "entity_type", "entity_id", "event_time"),
        {"schema": "audit"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DataQualityIssue(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "data_quality_issues"
    __table_args__ = ({"schema": "audit"},)

    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class JobRun(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("job_name", "scheduled_for", name="uq_job_scheduled"),
        {"schema": "ops"},
    )

    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    __table_args__ = ({"schema": "ops"},)

    service_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = ({"schema": "ops"},)

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    scope: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_created", "id", "created_at"), {"schema": "ops"})

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "backtest_runs"
    __table_args__ = ({"schema": "research"},)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(Text)

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import Settings
from app.db.models import Instrument, UniverseEligibilitySnapshot
from app.json_utils import json_compatible

UNIVERSE_ELIGIBILITY_SCHEMA = "universe-eligibility-snapshot-v1"
UNIVERSE_POLICY_SCHEMA = "universe-selection-policy-v1"


@dataclass(frozen=True)
class UniverseEligibilityDecision:
    symbol: str
    eligible_before_limit: bool
    selected: bool
    rank: int | None
    reason_code: str
    category: str | None
    base_coin: str | None
    quote_coin: str | None
    settle_coin: str | None
    instrument_status: str | None
    launch_time: datetime | None
    age_seconds: int | None
    is_pre_listing: bool | None
    contract_type: str | None
    symbol_type: str | None
    ticker_present: bool
    last_price: Decimal | None
    bid_price: Decimal | None
    ask_price: Decimal | None
    turnover_24h: Decimal | None
    spread_bps: Decimal | None

    def payload(self) -> dict[str, Any]:
        return json_compatible(
            {
                "symbol": self.symbol,
                "eligible_before_limit": self.eligible_before_limit,
                "selected": self.selected,
                "rank": self.rank,
                "reason_code": self.reason_code,
                "instrument": {
                    "category": self.category,
                    "base_coin": self.base_coin,
                    "quote_coin": self.quote_coin,
                    "settle_coin": self.settle_coin,
                    "status": self.instrument_status,
                    "launch_time": self.launch_time,
                    "age_seconds": self.age_seconds,
                    "is_pre_listing": self.is_pre_listing,
                    "contract_type": self.contract_type,
                    "symbol_type": self.symbol_type,
                },
                "ticker": {
                    "present": self.ticker_present,
                    "last_price": self.last_price,
                    "bid_price": self.bid_price,
                    "ask_price": self.ask_price,
                    "turnover_24h": self.turnover_24h,
                    "spread_bps": self.spread_bps,
                },
            }
        )


@dataclass(frozen=True)
class UniverseSelection:
    refresh_id: UUID
    observed_at: datetime
    mode: str
    symbols: tuple[str, ...]
    total_instruments: int
    ticker_count: int
    eligible_before_limit: int
    excluded_counts: dict[str, int]
    policy: dict[str, Any]
    policy_hash: str
    decisions: tuple[UniverseEligibilityDecision, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "eligibility_schema": UNIVERSE_ELIGIBILITY_SCHEMA,
            "refresh_id": str(self.refresh_id),
            "observed_at": self.observed_at.isoformat(),
            "policy_hash": self.policy_hash,
            "total_instruments": self.total_instruments,
            "ticker_count": self.ticker_count,
            "eligible_before_limit": self.eligible_before_limit,
            "selected_count": len(self.symbols),
            "selected_symbols": list(self.symbols),
            "selected_sample": list(self.symbols[:25]),
            "decision_count": len(self.decisions),
            "excluded_counts": dict(sorted(self.excluded_counts.items())),
        }


def _canonical(value: Any) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc_hash_timestamp(value: datetime, *, name: str) -> str:
    """Canonicalize TIMESTAMPTZ values independently of the PostgreSQL session timezone."""
    return _require_aware(value, name=name).astimezone(UTC).isoformat()


def _universe_policy(settings: Settings) -> dict[str, Any]:
    return json_compatible(
        {
            "schema": UNIVERSE_POLICY_SCHEMA,
            "mode": settings.universe_mode,
            "static_symbols": list(dict.fromkeys(symbol.upper() for symbol in settings.symbols)),
            "minimum_age_days": settings.universe_min_age_days,
            "minimum_turnover_24h": Decimal(str(settings.universe_min_turnover_24h)),
            "maximum_spread_bps": Decimal(str(settings.universe_max_spread_bps)),
            "maximum_symbols": settings.universe_max_symbols,
            "excluded_symbols": sorted(set(settings.universe_excluded_symbols)),
            "excluded_base_coins": sorted(set(settings.universe_excluded_base_coins)),
            "allow_non_crypto_symbol_types": settings.universe_allow_non_crypto_symbol_types,
        }
    )


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _spread_bps_from_prices(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    if mid <= 0:
        return None
    return (ask - bid) / mid * Decimal("10000")


def _spread_bps(ticker: dict) -> Decimal | None:
    return _spread_bps_from_prices(
        _decimal(ticker.get("bid1Price")),
        _decimal(ticker.get("ask1Price")),
    )


def _decision_base(
    instrument: Instrument,
    ticker: dict | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    raw = instrument.raw or {}
    bid = _decimal(ticker.get("bid1Price")) if ticker else None
    ask = _decimal(ticker.get("ask1Price")) if ticker else None
    launch_time = instrument.launch_time
    age_seconds = int((now - launch_time).total_seconds()) if launch_time else None
    return {
        "symbol": instrument.symbol.upper(),
        "category": instrument.category,
        "base_coin": instrument.base_coin,
        "quote_coin": instrument.quote_coin,
        "settle_coin": instrument.settle_coin,
        "instrument_status": instrument.status,
        "launch_time": launch_time,
        "age_seconds": age_seconds,
        "is_pre_listing": instrument.is_pre_listing,
        "contract_type": raw.get("contractType"),
        "symbol_type": str(raw.get("symbolType") or "").strip().lower(),
        "ticker_present": ticker is not None,
        "last_price": _decimal(ticker.get("lastPrice")) if ticker else None,
        "bid_price": bid,
        "ask_price": ask,
        "turnover_24h": _decimal(ticker.get("turnover24h")) if ticker else None,
        "spread_bps": _spread_bps_from_prices(bid, ask),
    }


def _final_decision(
    data: dict[str, Any],
    *,
    eligible_before_limit: bool,
    selected: bool,
    rank: int | None,
    reason_code: str,
) -> UniverseEligibilityDecision:
    return UniverseEligibilityDecision(
        **data,
        eligible_before_limit=eligible_before_limit,
        selected=selected,
        rank=rank,
        reason_code=reason_code,
    )


def select_dynamic_universe(
    instruments: Iterable[Instrument],
    ticker_items: Iterable[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UniverseSelection:
    now = _require_aware(now or datetime.now(UTC), name="universe observed_at")
    instrument_list = sorted(instruments, key=lambda item: item.symbol.upper())
    ticker_map = {
        str(item.get("symbol") or "").upper(): item
        for item in ticker_items
        if item.get("symbol")
    }
    excluded = Counter()
    candidates: list[tuple[str, Decimal]] = []
    decision_data: dict[str, dict[str, Any]] = {}
    exclusion_reason: dict[str, str] = {}
    excluded_symbols = set(settings.universe_excluded_symbols)
    excluded_bases = set(settings.universe_excluded_base_coins)
    minimum_launch_time = now - timedelta(days=max(0, settings.universe_min_age_days))

    for instrument in instrument_list:
        symbol = instrument.symbol.upper()
        ticker = ticker_map.get(symbol)
        data = _decision_base(instrument, ticker, now=now)
        decision_data[symbol] = data
        raw = instrument.raw or {}
        reason: str | None = None

        if instrument.category != "linear":
            reason = "not_linear"
        elif instrument.settle_coin != "USDT" or instrument.quote_coin != "USDT":
            reason = "not_usdt_settled"
        elif instrument.status != "Trading":
            reason = "not_trading"
        elif instrument.is_pre_listing:
            reason = "pre_listing"
        elif raw.get("contractType") != "LinearPerpetual":
            reason = "not_perpetual"
        elif symbol in excluded_symbols:
            reason = "excluded_symbol"
        elif instrument.base_coin.upper() in excluded_bases:
            reason = "excluded_base_coin"
        else:
            symbol_type = data["symbol_type"]
            if (
                symbol_type in {"xstocks", "xstock", "stock", "forex", "commodity"}
                and not settings.universe_allow_non_crypto_symbol_types
            ):
                reason = "non_crypto_symbol_type"
            elif instrument.launch_time and instrument.launch_time > minimum_launch_time:
                reason = "insufficient_age"
            elif ticker is None:
                reason = "missing_ticker"
            elif data["last_price"] is None or data["last_price"] <= 0:
                reason = "invalid_last_price"
            elif data["spread_bps"] is None:
                reason = "invalid_bid_ask"
            elif settings.universe_min_turnover_24h > 0 and (
                data["turnover_24h"] is None
                or data["turnover_24h"] < Decimal(str(settings.universe_min_turnover_24h))
            ):
                reason = "low_turnover"
            elif settings.universe_max_spread_bps > 0 and data["spread_bps"] > Decimal(
                str(settings.universe_max_spread_bps)
            ):
                reason = "wide_spread"

        if reason is not None:
            excluded[reason] += 1
            exclusion_reason[symbol] = reason
            continue
        candidates.append((symbol, data["turnover_24h"] or Decimal("0")))

    candidates.sort(key=lambda item: (-item[1], item[0]))
    eligible_before_limit = len(candidates)
    ranks = {symbol: rank for rank, (symbol, _turnover) in enumerate(candidates, start=1)}
    if settings.universe_max_symbols > 0:
        selected_candidates = candidates[: settings.universe_max_symbols]
    else:
        selected_candidates = candidates
    symbols = tuple(symbol for symbol, _turnover in selected_candidates)
    selected_set = set(symbols)

    decisions: list[UniverseEligibilityDecision] = []
    for symbol in sorted(decision_data):
        if symbol in exclusion_reason:
            decisions.append(
                _final_decision(
                    decision_data[symbol],
                    eligible_before_limit=False,
                    selected=False,
                    rank=None,
                    reason_code=exclusion_reason[symbol],
                )
            )
            continue
        selected = symbol in selected_set
        decisions.append(
            _final_decision(
                decision_data[symbol],
                eligible_before_limit=True,
                selected=selected,
                rank=ranks[symbol],
                reason_code="selected" if selected else "rank_limit",
            )
        )

    policy = _universe_policy(settings)
    return UniverseSelection(
        refresh_id=uuid4(),
        observed_at=now,
        mode="dynamic",
        symbols=symbols,
        total_instruments=len(instrument_list),
        ticker_count=len(ticker_map),
        eligible_before_limit=eligible_before_limit,
        excluded_counts=dict(excluded),
        policy=policy,
        policy_hash=_sha256(policy),
        decisions=tuple(decisions),
    )


def select_static_universe(
    settings: Settings,
    *,
    ticker_count: int,
    now: datetime | None = None,
) -> UniverseSelection:
    now = _require_aware(now or datetime.now(UTC), name="universe observed_at")
    symbols = tuple(dict.fromkeys(symbol.upper() for symbol in settings.symbols))
    decisions = tuple(
        UniverseEligibilityDecision(
            symbol=symbol,
            eligible_before_limit=True,
            selected=True,
            rank=rank,
            reason_code="static_configured",
            category=None,
            base_coin=None,
            quote_coin=None,
            settle_coin=None,
            instrument_status=None,
            launch_time=None,
            age_seconds=None,
            is_pre_listing=None,
            contract_type=None,
            symbol_type=None,
            ticker_present=False,
            last_price=None,
            bid_price=None,
            ask_price=None,
            turnover_24h=None,
            spread_bps=None,
        )
        for rank, symbol in enumerate(symbols, start=1)
    )
    policy = _universe_policy(settings)
    return UniverseSelection(
        refresh_id=uuid4(),
        observed_at=now,
        mode="static",
        symbols=symbols,
        total_instruments=len(symbols),
        ticker_count=ticker_count,
        eligible_before_limit=len(symbols),
        excluded_counts={},
        policy=policy,
        policy_hash=_sha256(policy),
        decisions=decisions,
    )


def build_universe_eligibility_record_hash(payload: dict[str, Any]) -> str:
    return _sha256(payload)


def _snapshot_payload(
    selection: UniverseSelection,
    *,
    recorded_at: datetime,
    release_version: str,
) -> dict[str, Any]:
    return json_compatible(
        {
            "id": selection.refresh_id,
            "observed_at": _utc_hash_timestamp(
                selection.observed_at, name="universe observed_at"
            ),
            "recorded_at": _utc_hash_timestamp(recorded_at, name="universe recorded_at"),
            "mode": selection.mode,
            "eligibility_schema": UNIVERSE_ELIGIBILITY_SCHEMA,
            "policy": selection.policy,
            "policy_hash": selection.policy_hash,
            "decisions": [decision.payload() for decision in selection.decisions],
            "selected_symbols": list(selection.symbols),
            "total_instruments": selection.total_instruments,
            "ticker_count": selection.ticker_count,
            "eligible_before_limit": selection.eligible_before_limit,
            "selected_count": len(selection.symbols),
            "release_version": release_version,
        }
    )


def _validate_selection(selection: UniverseSelection) -> None:
    _require_aware(selection.observed_at, name="universe observed_at")
    if selection.mode not in {"static", "dynamic"}:
        raise ValueError("Unsupported universe selection mode")
    if selection.policy.get("schema") != UNIVERSE_POLICY_SCHEMA:
        raise ValueError("Universe policy schema is missing or incompatible")
    if _sha256(selection.policy) != selection.policy_hash:
        raise ValueError("Universe policy hash mismatch")
    if len(selection.decisions) != selection.total_instruments:
        raise ValueError("Universe decision coverage is incomplete")
    symbols = [decision.symbol for decision in selection.decisions]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Universe decisions contain duplicate symbols")
    selected = tuple(
        decision.symbol
        for decision in sorted(
            (item for item in selection.decisions if item.selected),
            key=lambda item: item.rank or 0,
        )
    )
    if selected != selection.symbols:
        raise ValueError("Universe selected symbols do not match decision evidence")
    for decision in selection.decisions:
        if decision.selected and not decision.eligible_before_limit:
            raise ValueError("Selected universe decision must be eligible before limit")
        if decision.eligible_before_limit and decision.rank is None:
            raise ValueError("Eligible universe decision must have a rank")
        if not decision.eligible_before_limit and decision.rank is not None:
            raise ValueError("Ineligible universe decision cannot have a rank")


def validate_universe_eligibility_snapshot_record(
    snapshot: UniverseEligibilitySnapshot,
    *,
    expected_mode: str | None = None,
) -> dict[str, Any]:
    """Validate a persisted snapshot before research replay and return its hash payload."""
    if expected_mode is not None and snapshot.mode != expected_mode:
        raise ValueError(
            "Universe eligibility snapshot mode is incompatible: "
            f"expected {expected_mode}, got {snapshot.mode}"
        )
    policy = json_compatible(snapshot.policy)
    decisions = json_compatible(snapshot.decisions)
    selected_symbols = [str(item).strip().upper() for item in snapshot.selected_symbols]
    if snapshot.eligibility_schema != UNIVERSE_ELIGIBILITY_SCHEMA:
        raise ValueError("Universe eligibility snapshot schema is incompatible")
    if policy.get("schema") != UNIVERSE_POLICY_SCHEMA:
        raise ValueError("Universe eligibility snapshot policy schema is incompatible")
    if _sha256(policy) != snapshot.policy_hash:
        raise ValueError("Universe eligibility snapshot policy hash mismatch")
    if not isinstance(decisions, list) or len(decisions) != snapshot.total_instruments:
        raise ValueError("Universe eligibility snapshot decision coverage is incomplete")
    if len(selected_symbols) != snapshot.selected_count or len(selected_symbols) != len(set(selected_symbols)):
        raise ValueError("Universe eligibility snapshot selected symbol count is invalid")
    selected_from_decisions = [
        str(item.get("symbol") or "").strip().upper()
        for item in sorted(
            (item for item in decisions if isinstance(item, dict) and item.get("selected") is True),
            key=lambda item: int(item.get("rank") or 0),
        )
    ]
    if selected_from_decisions != selected_symbols:
        raise ValueError("Universe eligibility snapshot selected symbols contradict decisions")
    payload = json_compatible(
        {
            "id": snapshot.id,
            "observed_at": _utc_hash_timestamp(
                snapshot.observed_at, name="universe snapshot observed_at"
            ),
            "recorded_at": _utc_hash_timestamp(
                snapshot.recorded_at, name="universe snapshot recorded_at"
            ),
            "mode": snapshot.mode,
            "eligibility_schema": snapshot.eligibility_schema,
            "policy": policy,
            "policy_hash": snapshot.policy_hash,
            "decisions": decisions,
            "selected_symbols": selected_symbols,
            "total_instruments": snapshot.total_instruments,
            "ticker_count": snapshot.ticker_count,
            "eligible_before_limit": snapshot.eligible_before_limit,
            "selected_count": snapshot.selected_count,
            "release_version": snapshot.release_version,
        }
    )
    if build_universe_eligibility_record_hash(payload) != snapshot.record_hash:
        raise ValueError("Universe eligibility snapshot record hash mismatch")
    return payload


async def persist_universe_selection(
    session: AsyncSession,
    selection: UniverseSelection,
    *,
    recorded_at: datetime | None = None,
    release_version: str = __version__,
) -> UniverseEligibilitySnapshot:
    _validate_selection(selection)
    recorded_at = _require_aware(recorded_at or datetime.now(UTC), name="universe recorded_at")
    payload = _snapshot_payload(
        selection,
        recorded_at=recorded_at,
        release_version=release_version,
    )
    snapshot = UniverseEligibilitySnapshot(
        id=selection.refresh_id,
        observed_at=selection.observed_at,
        recorded_at=recorded_at,
        mode=selection.mode,
        eligibility_schema=UNIVERSE_ELIGIBILITY_SCHEMA,
        policy=selection.policy,
        policy_hash=selection.policy_hash,
        decisions=payload["decisions"],
        selected_symbols=list(selection.symbols),
        total_instruments=selection.total_instruments,
        ticker_count=selection.ticker_count,
        eligible_before_limit=selection.eligible_before_limit,
        selected_count=len(selection.symbols),
        release_version=release_version,
        record_hash=build_universe_eligibility_record_hash(payload),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def resolve_universe(
    session: AsyncSession,
    ticker_items: Iterable[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UniverseSelection:
    ticker_list = list(ticker_items)
    if settings.universe_mode == "static":
        return select_static_universe(settings, ticker_count=len(ticker_list), now=now)

    instruments = (await session.execute(select(Instrument))).scalars().all()
    return select_dynamic_universe(instruments, ticker_list, settings, now=now)

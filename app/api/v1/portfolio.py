from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import desc, select

from app.api.deps import SessionDep, SettingsDep
from app.db.models import (
    AccountEquitySnapshot,
    CapitalProfile,
    ExecutionPlan,
    ManualTrade,
    MarketSignal,
    PositionSnapshot,
)
from app.risk.policy import validate_capital_profile_policy
from app.services.execution import execution_plan_scope_clause, reconciliation_issues

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


@router.get("/risk")
async def portfolio_risk(session: SessionDep, settings: SettingsDep) -> dict:
    active_profile = (
        await session.execute(select(CapitalProfile).where(CapitalProfile.active.is_(True)).limit(1))
    ).scalar_one_or_none()
    rows = []
    if active_profile is not None:
        rows = (
            await session.execute(
                select(ManualTrade, ExecutionPlan, MarketSignal)
                .join(ExecutionPlan, ManualTrade.plan_id == ExecutionPlan.id)
                .join(MarketSignal, ExecutionPlan.signal_id == MarketSignal.id)
                .join(CapitalProfile, ExecutionPlan.profile_id == CapitalProfile.id)
                .where(
                    ManualTrade.status.in_(["OPEN", "PARTIAL"]),
                    execution_plan_scope_clause(active_profile),
                )
            )
        ).all()
    total_open_risk = sum((trade.remaining_stress_loss for trade, _, _ in rows), Decimal("0"))
    long_notional = sum(
        (trade.remaining_qty * trade.entry_price for trade, _, signal in rows if signal.direction == "LONG"),
        Decimal("0"),
    )
    short_notional = sum(
        (trade.remaining_qty * trade.entry_price for trade, _, signal in rows if signal.direction == "SHORT"),
        Decimal("0"),
    )
    capital = active_profile.allocated_capital if active_profile else Decimal("0")
    risk_policy_issues: list[str] = []
    effective_total_risk_rate = Decimal("0")
    if active_profile is not None:
        try:
            effective_total_risk_rate = validate_capital_profile_policy(
                active_profile, settings=settings
            ).max_total_risk_rate
        except (TypeError, ValueError) as exc:
            risk_policy_issues.append(str(exc))
            effective_total_risk_rate = Decimal(str(settings.max_total_open_risk_rate))
    risk_limit = capital * effective_total_risk_rate
    account_snapshot = None
    exchange_positions = []
    reconciliation: list[str] = []
    if active_profile is not None:
        reconciliation = await reconciliation_issues(session, profile=active_profile)
    if (
        active_profile is not None
        and active_profile.mode == "bybit_read_only"
        and active_profile.source_account_id
    ):
        account_id = active_profile.source_account_id
        account_snapshot = (
            await session.execute(
                select(AccountEquitySnapshot)
                .where(AccountEquitySnapshot.account_id == account_id)
                .order_by(desc(AccountEquitySnapshot.source_time))
                .limit(1)
            )
        ).scalar_one_or_none()
        if account_snapshot is not None:
            exchange_positions = (
                (
                    await session.execute(
                        select(PositionSnapshot).where(
                            PositionSnapshot.account_id == account_id,
                            PositionSnapshot.source_time == account_snapshot.source_time,
                        )
                    )
                )
                .scalars()
                .all()
            )
    clusters: dict[str, dict] = {}
    for trade, _plan, signal in rows:
        cluster = "BTC" if signal.symbol == "BTCUSDT" else "ETH" if signal.symbol == "ETHUSDT" else "ALT_BETA"
        item = clusters.setdefault(
            cluster, {"risk_usdt": Decimal("0"), "notional": Decimal("0"), "positions": 0}
        )
        item["risk_usdt"] += trade.remaining_stress_loss
        item["notional"] += trade.remaining_qty * trade.entry_price
        item["positions"] += 1
    return {
        "profile": {
            "id": str(active_profile.id) if active_profile else None,
            "name": active_profile.name if active_profile else None,
            "capital": float(capital),
        },
        "total_open_risk_usdt": float(total_open_risk),
        "total_open_risk_rate": float(total_open_risk / capital) if capital else 0.0,
        "risk_limit_usdt": float(risk_limit),
        "risk_remaining_usdt": float(max(Decimal("0"), risk_limit - total_open_risk)),
        "directional_notional": {"long": float(long_notional), "short": float(short_notional)},
        "clusters": {
            key: {
                "risk_usdt": float(value["risk_usdt"]),
                "notional": float(value["notional"]),
                "positions": value["positions"],
            }
            for key, value in clusters.items()
        },
        "blocks": (
            (["TOTAL_RISK_LIMIT"] if total_open_risk >= risk_limit and risk_limit > 0 else [])
            + (["RECONCILIATION_MISMATCH"] if reconciliation else [])
            + (["INVALID_CAPITAL_PROFILE_POLICY"] if risk_policy_issues else [])
        ),
        "risk_policy_issues": risk_policy_issues,
        "effective_max_total_risk_rate": float(effective_total_risk_rate),
        "reconciliation_issues": reconciliation,
        "exchange_snapshot_time": account_snapshot.source_time.isoformat() if account_snapshot else None,
        "exchange_positions": [
            {
                "symbol": position.symbol,
                "side": position.side,
                "qty": float(position.qty),
                "avg_price": float(position.avg_price),
                "mark_price": float(position.mark_price),
                "unrealized_pnl": float(position.unrealized_pnl),
            }
            for position in exchange_positions
        ],
        "positions": [
            {
                "trade_id": str(trade.id),
                "symbol": signal.symbol,
                "direction": signal.direction,
                "remaining_qty": float(trade.remaining_qty),
                "entry_price": float(trade.entry_price),
                "planned_risk_usdt": float(plan.actual_stress_loss),
                "remaining_risk_usdt": float(trade.remaining_stress_loss),
            }
            for trade, plan, signal in rows
        ],
    }

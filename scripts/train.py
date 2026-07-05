from __future__ import annotations

import argparse

from sqlalchemy import desc, select

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import ModelRegistry
from app.ml.lifecycle import (
    build_model_candidate,
    evaluate_quality_gate,
    incumbent_from_registry,
    load_training_market_data,
    policy_evaluation_config,
    register_and_activate_model_candidate,
    register_model_candidate,
)


async def active_model() -> ModelRegistry | None:
    async with SessionFactory() as session:
        return (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
            )
        ).scalar_one_or_none()


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.horizon not in settings.horizons_hours:
        raise ValueError(f"Horizon {args.horizon} is not listed in HORIZONS_HOURS={settings.horizons_hours}")

    incumbent_model = await active_model()
    symbols = settings.symbols if settings.universe_mode == "static" else None
    market_data = await load_training_market_data(
        symbols,
        lookback_days=args.lookback_days,
        max_symbols=settings.auto_train_max_symbols,
    )
    candidate = build_model_candidate(
        market_data.candles,
        mark_candles=market_data.mark_candles,
        index_candles=market_data.index_candles,
        open_interest=market_data.open_interest,
        horizon=args.horizon,
        model_type=args.model_type,
        model_dir=settings.model_dir,
        entry_spread_bps=settings.model_entry_spread_bps,
        funding_history=market_data.funding,
        funding_interval_minutes=market_data.funding_interval_minutes,
        funding_interval_history=market_data.funding_interval_history,
        version=args.version,
        output=args.output,
        incumbent=incumbent_from_registry(incumbent_model),
        source="manual_cli",
        minimum_rows_for_coverage=settings.auto_train_min_bars_per_symbol,
        policy_config=policy_evaluation_config(settings),
    )
    quality_gate = evaluate_quality_gate(candidate, settings)
    activation = None
    if args.activate and quality_gate["passed"]:
        registry, activation = await register_and_activate_model_candidate(
            candidate,
            source="manual_cli",
            quality_gate=quality_gate,
            actor="training-cli",
            expected_previous_version=incumbent_model.version if incumbent_model else None,
            expected_horizon_hours=settings.default_horizon_hours,
        )
    else:
        registry = await register_model_candidate(
            candidate,
            source="manual_cli",
            quality_gate=quality_gate,
            activation_requested=args.activate,
            actor="training-cli",
        )

    print(
        {
            "artifact": str(candidate.path),
            "registry_id": str(registry.id),
            "version": candidate.version,
            "active": activation is not None,
            "metrics": candidate.metrics,
            "incumbent_version": candidate.incumbent_version,
            "incumbent_metrics_same_holdout": candidate.incumbent_metrics,
            "quality_gate": quality_gate,
            "note": (
                "Worker will load the registry-active model on its next refresh."
                if activation is not None
                else (
                    "Activation was requested but the quality gate failed; the candidate was registered inactive."
                    if args.activate and not quality_gate["passed"]
                    else "Model is registered inactive. Review holdout metrics, then run model-registry activate --version <version>."
                )
            ),
        }
    )
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=8)
    parser.add_argument(
        "--model-type",
        choices=["logistic", "hist_gradient_boosting"],
        default="logistic",
    )
    parser.add_argument("--version")
    parser.add_argument("--output", type=str)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="Optional rolling training window. Omit to use all confirmed candles.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Deactivate the previous registry model and activate this artifact after training.",
    )
    args = parser.parse_args()
    if args.output:
        from pathlib import Path

        args.output = Path(args.output)
    run_with_compatible_event_loop(run(args))


if __name__ == "__main__":
    main()

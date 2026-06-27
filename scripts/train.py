from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import select

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import Candle, ModelRegistry
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    MODEL_FEATURE_NAMES,
    TemporalCalibratedBarrierModel,
    chronological_split,
    evaluate_model,
    make_barrier_dataset,
)
from scripts.model_registry import activate_registered_model


def as_datetime(value) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime-like value, got {type(value)!r}")
    return value


async def load_candles(symbols: list[str] | None) -> pd.DataFrame:
    async with SessionFactory() as session:
        query = select(Candle).where(
            Candle.interval == "60",
            Candle.price_type == "last",
            Candle.confirmed.is_(True),
        )
        if symbols is not None:
            query = query.where(Candle.symbol.in_(symbols))
        rows = (await session.execute(query.order_by(Candle.open_time))).scalars().all()
    return pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "turnover": float(row.turnover),
            }
            for row in rows
        ]
    )


async def register(
    path: Path,
    version: str,
    metrics: dict,
    start: datetime,
    end: datetime,
    *,
    horizon: int,
    model_type: str,
    activate: bool,
) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    async with SessionFactory() as session:
        session.add(
            ModelRegistry(
                name=f"Hourly direction-conditional barrier {model_type} h{horizon}",
                version=version,
                model_type=f"barrier_{model_type}",
                artifact_path=str(path),
                artifact_sha256=digest,
                feature_schema_version="hourly-barrier-v1",
                calibration_version=f"sigmoid-ovr-{version}",
                training_start=start,
                training_end=end,
                metrics={
                    **metrics,
                    "task": "barrier_outcome_v1",
                    "horizon_hours": horizon,
                    "stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
                    "tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
                    "activation_requested": activate,
                },
                active=False,
            )
        )
        await session.commit()
    if activate:
        await activate_registered_model(version, actor="training-cli")


async def run(args) -> None:
    settings = get_settings()
    if args.horizon not in settings.horizons_hours:
        raise ValueError(
            f"Horizon {args.horizon} is not listed in HORIZONS_HOURS={settings.horizons_hours}"
        )
    frame = await load_candles(settings.symbols if settings.universe_mode == "static" else None)
    dataset = make_barrier_dataset(frame, horizon=args.horizon)
    if dataset.empty:
        raise RuntimeError("No direction-specific barrier labels could be built from PostgreSQL candles")
    split = chronological_split(dataset, purge_rows=args.horizon)
    model = TemporalCalibratedBarrierModel(args.model_type).fit(
        split.x_train,
        split.y_train,
        split.x_cal,
        split.y_cal,
    )
    metrics = evaluate_model(model, split)
    version = args.version or (
        f"barrier-{args.model_type}-h{args.horizon}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    )
    path = Path(args.output or settings.model_dir / f"{version}.joblib").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "task": "barrier_outcome_v1",
        "model": model,
        "model_type": args.model_type,
        "version": version,
        "calibration_version": f"sigmoid-ovr-{version}",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": "hourly-barrier-v1",
        "horizon_hours": args.horizon,
        "stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
        "tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
        "metrics": metrics,
        "created_at": datetime.now(UTC).isoformat(),
    }
    joblib.dump(bundle, path)
    await register(
        path,
        version,
        metrics,
        as_datetime(dataset.open_time.min()),
        as_datetime(dataset.open_time.max()),
        horizon=args.horizon,
        model_type=args.model_type,
        activate=args.activate,
    )
    print(
        {
            "artifact": str(path),
            "version": version,
            "active": args.activate,
            "metrics": metrics,
            "note": (
                "Worker will load the registry-active model on its next refresh."
                if args.activate
                else "Model is registered inactive. Review holdout metrics, then run model-registry activate --version <version>."
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
    parser.add_argument("--output")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Deactivate the previous registry model and activate this artifact after training.",
    )
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import select, update

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import Candle, ModelRegistry
from app.ml.features import FEATURE_NAMES
from app.ml.training import (
    TemporalCalibratedDirectionModel,
    chronological_split,
    evaluate_model,
    make_direction_dataset,
)


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


async def register(path: Path, version: str, metrics: dict, start: datetime, end: datetime) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    async with SessionFactory() as session:
        await session.execute(update(ModelRegistry).values(active=False))
        session.add(
            ModelRegistry(
                name="Hourly pooled direction logistic",
                version=version,
                model_type="logistic_temporal_sigmoid",
                artifact_path=str(path),
                artifact_sha256=digest,
                feature_schema_version="hourly-core-v1",
                calibration_version=f"sigmoid-{version}",
                training_start=start,
                training_end=end,
                metrics=metrics,
                active=True,
            )
        )
        await session.commit()


async def run(args) -> None:
    settings = get_settings()
    frame = await load_candles(settings.symbols if settings.universe_mode == "static" else None)
    dataset = make_direction_dataset(frame, horizon=args.horizon)
    split = chronological_split(dataset, purge_rows=args.horizon)
    model = TemporalCalibratedDirectionModel().fit(split.x_train, split.y_train, split.x_cal, split.y_cal)
    metrics = evaluate_model(model, split)
    version = args.version or f"logistic-h{args.horizon}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    path = Path(args.output or settings.model_dir / f"{version}.joblib")
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "version": version,
        "calibration_version": f"sigmoid-{version}",
        "feature_names": FEATURE_NAMES,
        "horizon_hours": args.horizon,
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
    )
    print({"artifact": str(path), "version": version, "metrics": metrics})
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=8)
    parser.add_argument("--version")
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

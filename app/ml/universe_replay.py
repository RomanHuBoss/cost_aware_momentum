from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import DateTime, String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UniverseEligibilitySnapshot
from app.json_utils import json_compatible
from app.services.universe import validate_universe_eligibility_snapshot_record

UNIVERSE_REPLAY_SCHEMA_VERSION = "point-in-time-universe-replay-v1"

POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA = "postgresql-native-universe-asof-loader-v1"
_COMPACT_SNAPSHOT_COLUMNS = [
    "observed_at",
    "recorded_at",
    "selected_symbols",
    "policy_hash",
    "record_hash",
]

UNIVERSE_REPLAY_ASOF_SQL = (
    text(
        """
        WITH requested_decision_times AS (
            SELECT DISTINCT item.decision_time
            FROM unnest(CAST(:decision_times AS TIMESTAMPTZ[]))
                AS item(decision_time)
        ),
        matched_recorded_at AS (
            SELECT DISTINCT latest.recorded_at
            FROM requested_decision_times AS decision
            LEFT JOIN LATERAL (
                SELECT snapshot.recorded_at
                FROM market.universe_eligibility_snapshots AS snapshot
                WHERE snapshot.mode = :mode
                  AND snapshot.recorded_at <= decision.decision_time
                ORDER BY snapshot.recorded_at DESC
                LIMIT 1
            ) AS latest ON TRUE
        ),
        rollout_recorded_at AS (
            SELECT MIN(snapshot.recorded_at) AS recorded_at
            FROM market.universe_eligibility_snapshots AS snapshot
            WHERE snapshot.mode = :mode
        )
        SELECT snapshot.*
        FROM market.universe_eligibility_snapshots AS snapshot
        WHERE snapshot.mode = :mode
          AND (
              snapshot.recorded_at IN (
                  SELECT matched.recorded_at
                  FROM matched_recorded_at AS matched
                  WHERE matched.recorded_at IS NOT NULL
              )
              OR snapshot.recorded_at = (
                  SELECT rollout.recorded_at
                  FROM rollout_recorded_at AS rollout
              )
          )
        ORDER BY snapshot.recorded_at, snapshot.observed_at, snapshot.record_hash
        """
    )
    .bindparams(
        bindparam(
            "decision_times",
            type_=ARRAY(DateTime(timezone=True)),
        ),
        bindparam("mode", type_=String(20)),
    )
    .execution_options(stream_results=True, yield_per=128)
)


def _normalize_decision_times(values: Iterable[datetime]) -> list[datetime]:
    normalized: set[datetime] = set()
    for value in values:
        if not isinstance(value, datetime):
            raise ValueError("Universe replay decision_time must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Universe replay decision_time must be timezone-aware")
        normalized.add(value.astimezone(UTC))
    return sorted(normalized)


async def load_point_in_time_universe_snapshots(
    session: AsyncSession,
    decision_times: Iterable[datetime],
    *,
    expected_mode: str = "dynamic",
) -> pd.DataFrame:
    """Stream only snapshots required by the requested decision timestamps.

    PostgreSQL performs the latest-prior lookup by committed ``recorded_at``.
    Full immutable rows are streamed and hash-validated incrementally in bounded
    batches; only the compact replay fields are retained after validation. All rows
    that share a selected ``recorded_at`` are returned so ambiguous availability still
    fails closed in :func:`apply_point_in_time_universe_replay`.
    """

    if expected_mode not in {"dynamic", "static"}:
        raise ValueError("Unsupported universe replay mode")
    normalized_times = _normalize_decision_times(decision_times)
    if not normalized_times:
        frame = pd.DataFrame(columns=_COMPACT_SNAPSHOT_COLUMNS)
        frame.attrs["universe_snapshot_loader"] = {
            "schema": POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA,
            "requested_decision_timestamps": 0,
            "snapshot_rows_streamed": 0,
            "compact_rows_retained": 0,
        }
        return frame

    stream = await session.stream(
        UNIVERSE_REPLAY_ASOF_SQL,
        {"decision_times": normalized_times, "mode": expected_mode},
    )
    compact_records: list[dict[str, object]] = []
    streamed_rows = 0
    model_columns = [column.name for column in UniverseEligibilitySnapshot.__table__.columns]
    async for row in stream.mappings():
        streamed_rows += 1
        missing = set(model_columns).difference(row.keys())
        if missing:
            raise ValueError(
                "Universe as-of loader returned an incomplete snapshot row: "
                f"{sorted(missing)}"
            )
        snapshot = UniverseEligibilitySnapshot(
            **{column: row[column] for column in model_columns}
        )
        try:
            validate_universe_eligibility_snapshot_record(
                snapshot,
                expected_mode=expected_mode,
            )
        except ValueError as exc:
            raise ValueError(
                "Universe eligibility snapshot validation failed "
                f"(id={snapshot.id}, mode={snapshot.mode}, "
                f"recorded_at={snapshot.recorded_at.isoformat()}): {exc}"
            ) from exc
        compact_records.append(
            {
                "observed_at": snapshot.observed_at,
                "recorded_at": snapshot.recorded_at,
                "selected_symbols": list(snapshot.selected_symbols),
                "policy_hash": snapshot.policy_hash,
                "record_hash": snapshot.record_hash,
            }
        )

    frame = pd.DataFrame.from_records(compact_records, columns=_COMPACT_SNAPSHOT_COLUMNS)
    frame.attrs["universe_snapshot_loader"] = {
        "schema": POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA,
        "requested_decision_timestamps": len(normalized_times),
        "snapshot_rows_streamed": streamed_rows,
        "compact_rows_retained": len(compact_records),
    }
    return frame


_REQUIRED_SNAPSHOT_COLUMNS = {
    "observed_at",
    "recorded_at",
    "selected_symbols",
    "policy_hash",
    "record_hash",
}


def _empty_evidence(*, required: bool, max_snapshot_age_seconds: int) -> dict[str, Any]:
    return json_compatible(
        {
            "schema": UNIVERSE_REPLAY_SCHEMA_VERSION,
            "status": "not_required" if not required else "missing",
            "required": required,
            "max_snapshot_age_seconds": max_snapshot_age_seconds,
            "input_rows": 0,
            "pre_rollout_rows_excluded": 0,
            "ineligible_rows_excluded": 0,
            "eligible_rows": 0,
            "decision_timestamps": 0,
            "snapshot_count_available": 0,
            "snapshot_count_used": 0,
            "rollout_start": None,
            "replay_start": None,
            "replay_end": None,
            "policy_hashes": [],
            "record_hashes": [],
            "snapshot_loader": None,
        }
    )


def _normalize_selected_symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("Universe eligibility selected_symbols must be an array")
    symbols = tuple(str(item).strip().upper() for item in value)
    if any(not symbol for symbol in symbols) or len(symbols) != len(set(symbols)):
        raise ValueError("Universe eligibility selected_symbols are invalid")
    return symbols


def apply_point_in_time_universe_replay(
    dataset: pd.DataFrame,
    snapshots: pd.DataFrame | None,
    *,
    max_snapshot_age_seconds: int,
    required: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter decision rows by the latest committed universe snapshot available then.

    Rows before the first prospective snapshot are excluded rather than fabricated.
    Once rollout has started, every decision timestamp must have a non-stale prior
    snapshot. Missing or stale evidence blocks the whole research run instead of
    falling back to a candle-coverage cohort.
    """

    if max_snapshot_age_seconds <= 0:
        raise ValueError("max_snapshot_age_seconds must be positive")
    if dataset.empty:
        evidence = _empty_evidence(
            required=required,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
        )
        return dataset.copy(), evidence
    missing_dataset = {"decision_time", "symbol"}.difference(dataset.columns)
    if missing_dataset:
        raise ValueError(
            f"Universe replay dataset is missing columns: {sorted(missing_dataset)}"
        )
    if not required:
        evidence = _empty_evidence(
            required=False,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
        )
        evidence.update(
            {
                "input_rows": int(len(dataset)),
                "eligible_rows": int(len(dataset)),
                "decision_timestamps": int(dataset["decision_time"].nunique()),
            }
        )
        return dataset.copy(), json_compatible(evidence)
    if snapshots is None or snapshots.empty:
        raise ValueError("Dynamic research requires universe eligibility snapshots")
    loader_evidence = json_compatible(
        snapshots.attrs.get("universe_snapshot_loader")
    ) if snapshots.attrs.get("universe_snapshot_loader") else None
    missing_snapshots = _REQUIRED_SNAPSHOT_COLUMNS.difference(snapshots.columns)
    if missing_snapshots:
        raise ValueError(
            "Universe eligibility snapshots are missing columns: "
            f"{sorted(missing_snapshots)}"
        )

    frame = dataset.copy()
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    if frame["decision_time"].isna().any():
        raise ValueError("Universe replay dataset contains invalid decision_time")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if (frame["symbol"] == "").any():
        raise ValueError("Universe replay dataset contains an empty symbol")

    ledger = snapshots.copy()
    ledger["observed_at"] = pd.to_datetime(ledger["observed_at"], utc=True, errors="coerce")
    ledger["recorded_at"] = pd.to_datetime(ledger["recorded_at"], utc=True, errors="coerce")
    if ledger[["observed_at", "recorded_at"]].isna().any().any():
        raise ValueError("Universe eligibility snapshots contain invalid timestamps")
    if (ledger["recorded_at"] < ledger["observed_at"]).any():
        raise ValueError("Universe eligibility snapshot was recorded before observation")
    ledger["selected_symbols"] = ledger["selected_symbols"].map(_normalize_selected_symbols)
    for column in ("policy_hash", "record_hash"):
        values = ledger[column].astype(str)
        if (~values.str.fullmatch(r"[0-9a-f]{64}", case=False)).any():
            raise ValueError(f"Universe eligibility snapshots contain invalid {column}")
        ledger[column] = values.str.lower()

    ledger = ledger.sort_values(["recorded_at", "observed_at", "record_hash"], kind="mergesort")
    if ledger["recorded_at"].duplicated().any():
        raise ValueError("Universe eligibility snapshots contain ambiguous duplicate recorded_at")

    rollout_start = pd.Timestamp(ledger["recorded_at"].iloc[0])
    pre_rollout_mask = frame["decision_time"] < rollout_start
    post_rollout = frame.loc[~pre_rollout_mask].copy()
    if post_rollout.empty:
        raise ValueError("Universe replay has no decision rows at or after the prospective rollout")

    decisions = (
        post_rollout[["decision_time"]]
        .drop_duplicates()
        .sort_values("decision_time", kind="mergesort")
    )
    joined = pd.merge_asof(
        decisions,
        ledger[
            [
                "observed_at",
                "recorded_at",
                "selected_symbols",
                "policy_hash",
                "record_hash",
            ]
        ],
        left_on="decision_time",
        right_on="recorded_at",
        direction="backward",
        allow_exact_matches=True,
    )
    if joined["recorded_at"].isna().any():
        raise ValueError("Universe replay is missing a committed prior snapshot after rollout")
    joined["snapshot_age_seconds"] = (
        joined["decision_time"] - joined["observed_at"]
    ).dt.total_seconds()
    stale = joined["snapshot_age_seconds"] > float(max_snapshot_age_seconds)
    if stale.any():
        first = joined.loc[stale].iloc[0]
        raise ValueError(
            "stale universe eligibility snapshot at "
            f"{pd.Timestamp(first['decision_time']).isoformat()}: "
            f"age={float(first['snapshot_age_seconds']):.3f}s, "
            f"limit={max_snapshot_age_seconds}s"
        )

    post_rollout = post_rollout.merge(joined, on="decision_time", how="left", validate="many_to_one")
    eligible_mask = post_rollout.apply(
        lambda row: row["symbol"] in row["selected_symbols"], axis=1
    )
    filtered = post_rollout.loc[eligible_mask, dataset.columns].copy()
    if filtered.empty:
        raise ValueError("Universe replay produced no production-eligible decision rows")

    used = joined.drop_duplicates("record_hash")
    evidence = json_compatible(
        {
            "schema": UNIVERSE_REPLAY_SCHEMA_VERSION,
            "status": "applied",
            "required": True,
            "max_snapshot_age_seconds": max_snapshot_age_seconds,
            "input_rows": int(len(frame)),
            "pre_rollout_rows_excluded": int(pre_rollout_mask.sum()),
            "ineligible_rows_excluded": int((~eligible_mask).sum()),
            "eligible_rows": int(len(filtered)),
            "decision_timestamps": int(filtered["decision_time"].nunique()),
            "snapshot_count_available": int(len(ledger)),
            "snapshot_count_used": int(len(used)),
            "rollout_start": rollout_start.isoformat(),
            "replay_start": pd.Timestamp(filtered["decision_time"].min()).isoformat(),
            "replay_end": pd.Timestamp(filtered["decision_time"].max()).isoformat(),
            "maximum_observed_snapshot_age_seconds": float(
                joined["snapshot_age_seconds"].max()
            ),
            "policy_hashes": sorted(set(used["policy_hash"])),
            "record_hashes": list(used["record_hash"]),
            "snapshot_loader": loader_evidence,
        }
    )
    filtered.attrs.update(dataset.attrs)
    filtered.attrs["universe_replay"] = evidence
    return filtered, evidence

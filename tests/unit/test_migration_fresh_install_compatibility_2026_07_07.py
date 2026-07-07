from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = PROJECT_ROOT / "migrations" / "versions"


def _sql_source(filename: str) -> str:
    return " ".join((MIGRATIONS / filename).read_text(encoding="utf-8").split()).upper()


def test_post_initial_revisions_tolerate_objects_created_by_current_metadata() -> None:
    initial = _sql_source("0001_initial.py")
    assert "BASE.METADATA.CREATE_ALL(BIND=BIND)" in initial

    manual_risk = _sql_source("0006_manual_trade_remaining_risk.py")
    assert "ADD COLUMN IF NOT EXISTS INITIAL_STRESS_LOSS" in manual_risk
    assert "ADD COLUMN IF NOT EXISTS REMAINING_STRESS_LOSS" in manual_risk
    assert "SET INITIAL_STRESS_LOSS = COALESCE(" in manual_risk
    assert "TRADE.INITIAL_STRESS_LOSS IS NULL" in manual_risk
    assert "TRADE.REMAINING_STRESS_LOSS IS NULL" in manual_risk
    assert "DROP CONSTRAINT IF EXISTS CK_MANUAL_TRADES_INITIAL_STRESS_LOSS_NON_NEGATIVE" in manual_risk
    assert "DROP CONSTRAINT IF EXISTS CK_MANUAL_TRADES_REMAINING_STRESS_LOSS_NON_NEGATIVE" in manual_risk
    assert "DROP CONSTRAINT IF EXISTS CK_MANUAL_TRADES_REMAINING_STRESS_LOSS_LTE_INITIAL" in manual_risk

    account_scope = _sql_source("0007_position_account_scope.py")
    assert "ADD COLUMN IF NOT EXISTS ACCOUNT_ID" in account_scope
    assert "CREATE INDEX IF NOT EXISTS IX_POSITION_ACCOUNT_TIME" in account_scope

    artifact_store = _sql_source("0017_model_artifact_blobs.py")
    assert "CREATE TABLE IF NOT EXISTS MODEL.MODEL_ARTIFACT_BLOBS" in artifact_store
    assert "ALTER COLUMN CREATED_AT SET DEFAULT NOW()" in artifact_store
    assert "CREATE OR REPLACE FUNCTION MODEL.REJECT_MODEL_ARTIFACT_BLOB_MUTATION" in artifact_store

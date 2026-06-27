from pathlib import Path

import pytest

from app.api.deps import sign_session, verify_session
from app.bybit.client import BybitClient
from app.config import Settings
from app.ml.runtime import ModelRuntime


def test_postgresql_is_mandatory() -> None:
    with pytest.raises(ValueError):
        Settings(database_url="sqlite:///bad.db")


def test_session_signature_round_trip() -> None:
    settings = Settings(secret_key="x" * 40, database_url="postgresql+psycopg://u:p@localhost/db")
    token = sign_session(settings, "operator")
    assert verify_session(settings, token) == "operator"
    assert verify_session(settings, token + "x") is None


def test_baseline_prediction_is_normalized() -> None:
    runtime = ModelRuntime(None, allow_baseline=True)
    runtime.load()
    prediction = runtime.predict({"ret_6h": 0.02, "atr_pct_14": 0.01})
    assert prediction.direction == "LONG"
    assert prediction.p_tp + prediction.p_sl + prediction.p_timeout == pytest.approx(1.0)


def test_bybit_client_has_no_order_methods() -> None:
    public_names = {name for name in dir(BybitClient) if not name.startswith("_")}
    forbidden = {"create_order", "place_order", "amend_order", "cancel_order", "withdraw"}
    assert not (public_names & forbidden)
    source = Path("app/bybit/client.py").read_text(encoding="utf-8")
    for endpoint in ("/v5/order/create", "/v5/order/amend", "/v5/order/cancel", "/v5/asset/withdraw"):
        assert endpoint not in source


def test_empty_active_model_path_is_none() -> None:
    settings = Settings(
        active_model_path="",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.active_model_path is None

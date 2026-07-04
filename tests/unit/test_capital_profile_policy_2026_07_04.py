from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.schemas import CapitalProfileCreate
from app.api.v1.capital import resolve_create_profile_policy, resolve_patch_profile_policy
from app.config import Settings
from app.risk.policy import configured_capital_risk_policy, validate_capital_profile_policy

D = Decimal


def _settings(**overrides: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db", **overrides)


def _profile(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "risk_rate": D("0.0035"),
        "max_total_risk_rate": D("0.02"),
        "default_leverage": 3,
        "max_leverage": 5,
        "margin_reserve_rate": D("0.25"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_defaults_are_the_source_of_truth_for_omitted_create_fields() -> None:
    settings = _settings(
        default_risk_rate=0.002,
        max_total_open_risk_rate=0.01,
        default_leverage=2,
        max_leverage=4,
        margin_reserve_rate=0.30,
    )
    payload = CapitalProfileCreate(name="Conservative", allocated_capital=D("10000"))

    policy = resolve_create_profile_policy(payload, settings=settings)

    assert policy == configured_capital_risk_policy(settings)
    assert policy.risk_rate == D("0.002")
    assert policy.max_total_risk_rate == D("0.01")
    assert policy.default_leverage == 2
    assert policy.max_leverage == 4
    assert policy.margin_reserve_rate == D("0.3")


def test_profile_total_risk_cannot_exceed_global_open_risk_cap() -> None:
    with pytest.raises(ValueError, match="MAX_TOTAL_OPEN_RISK_RATE"):
        validate_capital_profile_policy(
            _profile(max_total_risk_rate=D("0.20")),
            settings=_settings(max_total_open_risk_rate=0.02),
        )


def test_per_trade_risk_cannot_exceed_profile_total_risk() -> None:
    with pytest.raises(ValueError, match="risk_rate cannot exceed"):
        validate_capital_profile_policy(
            _profile(risk_rate=D("0.03"), max_total_risk_rate=D("0.02")),
            settings=_settings(),
        )


def test_profile_leverage_cannot_exceed_global_leverage_cap() -> None:
    with pytest.raises(ValueError, match="MAX_LEVERAGE"):
        validate_capital_profile_policy(
            _profile(default_leverage=6, max_leverage=8),
            settings=_settings(max_leverage=5),
        )


def test_patch_is_validated_before_persisted_profile_is_mutated() -> None:
    profile = _profile()

    with pytest.raises(ValueError, match="MAX_TOTAL_OPEN_RISK_RATE"):
        resolve_patch_profile_policy(
            profile,
            {"max_total_risk_rate": D("0.20")},
            settings=_settings(max_total_open_risk_rate=0.02),
        )

    assert profile.max_total_risk_rate == D("0.02")


def test_explicit_unsafe_create_policy_is_rejected_by_runtime_cap() -> None:
    payload = CapitalProfileCreate(
        name="Unsafe",
        allocated_capital=D("10000"),
        risk_rate=D("0.01"),
        max_total_risk_rate=D("0.20"),
        default_leverage=3,
        max_leverage=5,
    )

    with pytest.raises(ValueError, match="MAX_TOTAL_OPEN_RISK_RATE"):
        resolve_create_profile_policy(payload, settings=_settings())


def test_frontend_does_not_override_runtime_total_risk_or_margin_defaults() -> None:
    source = (Path(__file__).parents[2] / "web" / "js" / "app.js").read_text(encoding="utf-8")

    assert "max_total_risk_rate: 0.02" not in source
    assert "margin_reserve_rate: 0.25" not in source
    assert "общий лимит" in source

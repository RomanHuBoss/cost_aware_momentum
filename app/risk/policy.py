from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.config import Settings
from app.risk.math import finite_decimal, positive_finite_decimal, positive_integer


class CapitalPolicySource(Protocol):
    risk_rate: object
    max_total_risk_rate: object
    default_leverage: object
    max_leverage: object
    margin_reserve_rate: object


@dataclass(frozen=True)
class CapitalRiskPolicy:
    risk_rate: Decimal
    max_total_risk_rate: Decimal
    default_leverage: int
    max_leverage: int
    margin_reserve_rate: Decimal


def configured_capital_risk_policy(settings: Settings) -> CapitalRiskPolicy:
    """Return the validated runtime defaults used for omitted profile fields."""

    return validate_capital_risk_policy(
        risk_rate=Decimal(str(settings.default_risk_rate)),
        max_total_risk_rate=Decimal(str(settings.max_total_open_risk_rate)),
        default_leverage=settings.default_leverage,
        max_leverage=settings.max_leverage,
        margin_reserve_rate=Decimal(str(settings.margin_reserve_rate)),
        settings=settings,
    )


def validate_capital_profile_policy(
    profile: CapitalPolicySource,
    *,
    settings: Settings,
) -> CapitalRiskPolicy:
    """Validate persisted profile values against the process-wide safety policy."""

    try:
        values = {
            "risk_rate": profile.risk_rate,
            "max_total_risk_rate": profile.max_total_risk_rate,
            "default_leverage": profile.default_leverage,
            "max_leverage": profile.max_leverage,
            "margin_reserve_rate": profile.margin_reserve_rate,
        }
    except AttributeError as exc:
        raise ValueError(f"capital profile policy is incomplete: {exc}") from exc
    return validate_capital_risk_policy(**values, settings=settings)


def validate_capital_risk_policy(
    *,
    risk_rate: object,
    max_total_risk_rate: object,
    default_leverage: object,
    max_leverage: object,
    margin_reserve_rate: object,
    settings: Settings,
) -> CapitalRiskPolicy:
    """Validate one capital-profile policy without silently clamping unsafe values."""

    per_trade = positive_finite_decimal(risk_rate, "profile risk_rate")
    total = positive_finite_decimal(max_total_risk_rate, "profile max_total_risk_rate")
    global_total = positive_finite_decimal(
        Decimal(str(settings.max_total_open_risk_rate)),
        "MAX_TOTAL_OPEN_RISK_RATE",
    )
    if per_trade > total:
        raise ValueError("profile risk_rate cannot exceed profile max_total_risk_rate")
    if total > global_total:
        raise ValueError(
            f"profile max_total_risk_rate exceeds MAX_TOTAL_OPEN_RISK_RATE ({total} > {global_total})"
        )

    default_lev = positive_integer(default_leverage, "profile default_leverage")
    maximum_lev = positive_integer(max_leverage, "profile max_leverage")
    if default_lev > maximum_lev:
        raise ValueError("profile default_leverage cannot exceed profile max_leverage")
    if maximum_lev > settings.max_leverage:
        raise ValueError(
            f"profile max_leverage exceeds MAX_LEVERAGE ({maximum_lev} > {settings.max_leverage})"
        )

    reserve = finite_decimal(margin_reserve_rate, "profile margin_reserve_rate")
    if reserve < 0 or reserve >= 1:
        raise ValueError("profile margin_reserve_rate must be in [0, 1)")

    return CapitalRiskPolicy(
        risk_rate=per_trade,
        max_total_risk_rate=total,
        default_leverage=default_lev,
        max_leverage=maximum_lev,
        margin_reserve_rate=reserve,
    )

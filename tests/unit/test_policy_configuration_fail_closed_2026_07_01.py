from __future__ import annotations

import pytest

from app.config import Settings

DB_URL = "postgresql+psycopg://u:p@localhost/db"


def test_negative_minimum_net_ev_is_rejected() -> None:
    with pytest.raises(ValueError, match="MIN_NET_EV_R"):
        Settings(database_url=DB_URL, min_net_ev_r=-0.01)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("auto_train_min_policy_realized_mean_r", -0.01, "REALIZED_MEAN_R"),
        ("auto_train_min_policy_profit_factor", 0.99, "PROFIT_FACTOR"),
    ],
)
def test_auto_activation_rejects_economically_losing_absolute_gate(
    field: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(
            database_url=DB_URL,
            auto_train_enabled=True,
            auto_train_auto_activate=True,
            **{field: value},
        )


def test_permissive_research_thresholds_remain_available_without_auto_activation() -> None:
    settings = Settings(
        database_url=DB_URL,
        auto_train_auto_activate=False,
        auto_train_min_policy_realized_mean_r=-0.25,
        auto_train_min_policy_profit_factor=0.5,
    )

    assert settings.auto_train_min_policy_realized_mean_r == -0.25
    assert settings.auto_train_min_policy_profit_factor == 0.5

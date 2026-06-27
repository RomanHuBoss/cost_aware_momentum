from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_mode: Literal["development", "backtest", "paper", "shadow", "production"] = "paper"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    secret_key: str = "replace-with-at-least-32-random-characters"
    operator_password: str = "change-me-now"
    operator_api_token: str | None = None
    cookie_secure: bool = False
    allow_demo_seed: bool = True

    database_url: str = "postgresql+psycopg://cost_momentum:cost_momentum@localhost:5432/cost_momentum"
    postgres_admin_url: str | None = None
    test_database_url: str | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 10

    bybit_base_url: str = "https://api.bybit.com"
    bybit_api_key: str | None = None
    bybit_api_secret: str | None = None
    bybit_recv_window: int = 5000
    bybit_read_only_account: bool = False

    # Static mode remains available for controlled experiments. Dynamic mode scans the
    # complete Bybit linear USDT perpetual catalogue and derives a tradable subset.
    universe_mode: Literal["static", "dynamic"] = "dynamic"
    symbols: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    )
    universe_min_age_days: int = 7
    universe_min_turnover_24h: float = 2_000_000.0
    universe_max_spread_bps: float = 30.0
    universe_max_symbols: int = 0
    universe_refresh_seconds: int = 300
    universe_min_history_bars: int = 72
    universe_excluded_symbols: Annotated[list[str], NoDecode] = Field(default_factory=list)
    universe_excluded_base_coins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "USDC",
            "USDE",
            "FDUSD",
            "TUSD",
            "USDP",
            "BUSD",
            "PYUSD",
            "DAI",
            "EURC",
            "EUR",
        ]
    )
    universe_allow_non_crypto_symbol_types: bool = False
    universe_backfill_batch_size: int = 40
    universe_sync_mark_price: bool = False
    universe_enrich_funding_oi: bool = False
    ticker_retention_hours: int = 48

    candle_interval: str = "60"
    initial_backfill_bars: int = 500
    market_poll_seconds: int = 60
    instrument_refresh_seconds: int = 21600
    inference_delay_seconds: int = 75

    horizons_hours: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [4, 8, 12])
    default_horizon_hours: int = 8
    default_leverage: int = 3
    max_leverage: int = 5
    default_risk_rate: float = 0.0035
    max_total_open_risk_rate: float = 0.02
    margin_reserve_rate: float = 0.25
    min_net_rr: float = 1.2
    min_net_ev_r: float = 0.05
    max_spread_bps: float = 18.0
    max_ticker_age_seconds: int = 120
    max_candle_age_seconds: int = 4200
    signal_ttl_minutes: int = 90
    fee_rate_taker: float = 0.00055
    base_slippage_bps: float = 3.0
    stop_gap_reserve_bps: float = 10.0

    model_dir: Path = Path("models")
    active_model_path: Path | None = None
    allow_baseline_model: bool = True

    worker_id: str = "worker-1"
    heartbeat_seconds: int = 15

    @staticmethod
    def _parse_env_list(value: str) -> list[object]:
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError("Expected a comma-separated list or a valid JSON array") from exc
            if not isinstance(parsed, list):
                raise ValueError("Expected a comma-separated list or a JSON array")
            return parsed
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @field_validator(
        "symbols",
        "universe_excluded_symbols",
        "universe_excluded_base_coins",
        mode="before",
    )
    @classmethod
    def parse_symbol_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [str(item).strip().upper() for item in cls._parse_env_list(value) if str(item).strip()]
        return value

    @field_validator("horizons_hours", mode="before")
    @classmethod
    def parse_horizons(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in cls._parse_env_list(value)]
        return value

    @field_validator("active_model_path", mode="before")
    @classmethod
    def empty_model_path_is_none(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return value

    @field_validator("postgres_admin_url", "test_database_url", mode="before")
    @classmethod
    def empty_optional_database_url_is_none(cls, value: object) -> object:
        if value in (None, ""):
            return None
        return value

    @field_validator("database_url", "postgres_admin_url", "test_database_url")
    @classmethod
    def reject_non_postgres(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ValueError("PostgreSQL URLs must use a PostgreSQL scheme")
        return value

    @property
    def mutating_auth_configured(self) -> bool:
        return bool(self.operator_api_token or self.operator_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()

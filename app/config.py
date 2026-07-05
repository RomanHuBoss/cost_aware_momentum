from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
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
    universe_sync_mark_price: bool = True
    universe_enrich_funding_oi: bool = True
    ticker_retention_hours: int = 48
    orderbook_depth_levels: int = 200
    max_orderbook_age_seconds: int = 90
    max_vwap_impact_bps: float = 12.0
    orderbook_retention_hours: int = 48

    candle_interval: str = "60"
    initial_backfill_bars: int = 1000
    history_backfill_enabled: bool = True
    history_backfill_target_days: int = 365
    history_backfill_interval_seconds: int = 60
    history_backfill_symbols_per_cycle: int = 5
    history_backfill_pages_per_symbol: int = 2
    history_backfill_page_size: int = 1000
    market_poll_seconds: int = 60
    instrument_refresh_seconds: int = 21600
    inference_delay_seconds: int = 75
    outcome_intrabar_interval: Literal["1", "3", "5"] = "5"
    outcome_intrabar_max_windows_per_cycle: int = 100

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
    max_account_snapshot_age_seconds: int = 180
    max_candle_age_seconds: int = 4200
    signal_ttl_minutes: int = 90
    fee_rate_taker: float = 0.00055
    base_slippage_bps: float = 3.0
    model_entry_spread_bps: float = 18.0
    stop_gap_reserve_bps: float = 10.0
    timeout_gross_return_rate: float = -0.002

    model_dir: Path = Path("models")
    active_model_path: Path | None = None
    allow_baseline_model: bool = True
    # Baseline remains available for diagnostics/bootstrap, but cannot produce
    # an actionable plan unless explicitly enabled outside production.
    allow_baseline_actionable: bool = False
    model_refresh_seconds: int = 300

    # Production drift monitoring is diagnostic and fail-closed. It can degrade
    # operational status but never weakens promotion gates or auto-deactivates a model.
    drift_monitor_enabled: bool = True
    drift_window_hours: int = 168
    drift_min_feature_observations: int = 48
    drift_min_outcome_observations: int = 30
    drift_min_coverage_rate: float = 0.80
    drift_max_missing_rate: float = 0.02
    drift_warning_psi: float = 0.10
    drift_critical_psi: float = 0.25
    drift_max_log_loss_delta: float = 0.10
    drift_max_brier_delta: float = 0.05
    drift_max_actionability_rate_delta: float = 0.20

    # Research experiment-selection governance. These thresholds only classify
    # experiment reports; they never activate, deactivate, or roll back a model.
    experiment_pbo_segments: int = 6
    experiment_min_trials: int = 4
    experiment_min_periods: int = 60
    experiment_max_pbo: float = 0.20
    experiment_min_dsr_probability: float = 0.95

    # Background model lifecycle. The trainer creates immutable candidates in a
    # separate process so CPU-heavy fitting never blocks API or inference work.
    auto_train_enabled: bool = True
    auto_train_auto_activate: bool = True
    auto_train_model_type: Literal["logistic", "hist_gradient_boosting"] = "logistic"
    auto_train_interval_hours: int = 168
    auto_train_retry_hours: int = 6
    auto_train_recovery_retry_minutes: int = 15
    auto_train_check_seconds: int = 300
    auto_train_initial_delay_seconds: int = 120
    auto_train_lookback_days: int = 365
    auto_train_max_symbols: int = 100
    auto_train_min_new_timestamps: int = 168
    auto_train_data_change_cooldown_hours: int = 6
    auto_train_min_new_rows: int = 10000
    auto_train_min_dataset_growth_ratio: float = 0.10
    auto_train_min_new_symbols: int = 5
    auto_train_min_universe_change_ratio: float = 0.10
    auto_train_min_bars_per_symbol: int = 300
    auto_train_min_symbol_coverage_ratio: float = 0.80
    auto_train_min_holdout_rows: int = 180
    auto_train_min_holdout_span_hours: int = 168
    auto_train_min_class_fraction: float = 0.02
    auto_train_max_log_loss: float = 1.20
    auto_train_max_multiclass_brier: float = 0.75
    auto_train_max_ece: float = 0.15
    auto_train_max_log_loss_regression: float = 0.01
    auto_train_max_brier_regression: float = 0.01
    auto_train_min_metric_improvement: float = 0.002
    auto_train_min_policy_trades: int = 20
    auto_train_min_policy_trade_rate: float = 0.01
    auto_train_min_policy_cohorts: int = 20
    auto_train_min_policy_realized_mean_r: float = 0.0
    auto_train_policy_bootstrap_samples: int = 2000
    auto_train_policy_confidence_level: float = 0.95
    auto_train_min_policy_mean_r_lcb: float = 0.0
    auto_train_min_policy_profit_factor: float = 1.0
    auto_train_max_policy_drawdown_r: float = 30.0
    auto_train_max_policy_mean_r_regression: float = 0.02
    auto_train_max_policy_drawdown_regression_r: float = 2.0
    auto_train_min_policy_improvement_r: float = 0.01
    auto_train_require_improvement: bool = True

    worker_id: str = "worker-1"
    trainer_id: str = "trainer-1"
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

    @model_validator(mode="after")
    def validate_cross_field_policy(self) -> Settings:
        if not self.horizons_hours:
            raise ValueError("HORIZONS_HOURS must contain at least one horizon")
        if any(item <= 0 for item in self.horizons_hours):
            raise ValueError("All HORIZONS_HOURS values must be positive")
        if self.default_horizon_hours <= 0:
            raise ValueError("DEFAULT_HORIZON_HOURS must be positive")
        if self.default_horizon_hours not in self.horizons_hours:
            raise ValueError("DEFAULT_HORIZON_HOURS must be included in HORIZONS_HOURS")
        finite_fields = {
            "DEFAULT_RISK_RATE": self.default_risk_rate,
            "MAX_TOTAL_OPEN_RISK_RATE": self.max_total_open_risk_rate,
            "MARGIN_RESERVE_RATE": self.margin_reserve_rate,
            "MIN_NET_RR": self.min_net_rr,
            "MIN_NET_EV_R": self.min_net_ev_r,
            "MAX_SPREAD_BPS": self.max_spread_bps,
            "MAX_VWAP_IMPACT_BPS": self.max_vwap_impact_bps,
            "FEE_RATE_TAKER": self.fee_rate_taker,
            "BASE_SLIPPAGE_BPS": self.base_slippage_bps,
            "MODEL_ENTRY_SPREAD_BPS": self.model_entry_spread_bps,
            "STOP_GAP_RESERVE_BPS": self.stop_gap_reserve_bps,
            "UNIVERSE_MIN_TURNOVER_24H": self.universe_min_turnover_24h,
            "UNIVERSE_MAX_SPREAD_BPS": self.universe_max_spread_bps,
            "AUTO_TRAIN_MIN_DATASET_GROWTH_RATIO": self.auto_train_min_dataset_growth_ratio,
            "AUTO_TRAIN_MIN_UNIVERSE_CHANGE_RATIO": self.auto_train_min_universe_change_ratio,
            "AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO": self.auto_train_min_symbol_coverage_ratio,
            "AUTO_TRAIN_MIN_CLASS_FRACTION": self.auto_train_min_class_fraction,
            "AUTO_TRAIN_MAX_LOG_LOSS": self.auto_train_max_log_loss,
            "AUTO_TRAIN_MAX_MULTICLASS_BRIER": self.auto_train_max_multiclass_brier,
            "AUTO_TRAIN_MAX_ECE": self.auto_train_max_ece,
            "AUTO_TRAIN_MAX_LOG_LOSS_REGRESSION": self.auto_train_max_log_loss_regression,
            "AUTO_TRAIN_MAX_BRIER_REGRESSION": self.auto_train_max_brier_regression,
            "AUTO_TRAIN_MIN_METRIC_IMPROVEMENT": self.auto_train_min_metric_improvement,
            "AUTO_TRAIN_MIN_POLICY_TRADE_RATE": self.auto_train_min_policy_trade_rate,
            "AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R": self.auto_train_min_policy_realized_mean_r,
            "AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR": self.auto_train_min_policy_profit_factor,
            "AUTO_TRAIN_MAX_POLICY_DRAWDOWN_R": self.auto_train_max_policy_drawdown_r,
            "AUTO_TRAIN_MAX_POLICY_MEAN_R_REGRESSION": self.auto_train_max_policy_mean_r_regression,
            "AUTO_TRAIN_MAX_POLICY_DRAWDOWN_REGRESSION_R": self.auto_train_max_policy_drawdown_regression_r,
            "AUTO_TRAIN_MIN_POLICY_IMPROVEMENT_R": self.auto_train_min_policy_improvement_r,
        }
        non_finite = [name for name, value in finite_fields.items() if not math.isfinite(float(value))]
        if non_finite:
            raise ValueError("Numeric configuration must be finite: " + ", ".join(non_finite))
        if not 0 < self.default_risk_rate <= 1:
            raise ValueError("DEFAULT_RISK_RATE must be in (0, 1]")
        if not 0 < self.max_total_open_risk_rate <= 1:
            raise ValueError("MAX_TOTAL_OPEN_RISK_RATE must be in (0, 1]")
        if self.default_risk_rate > self.max_total_open_risk_rate:
            raise ValueError("DEFAULT_RISK_RATE cannot exceed MAX_TOTAL_OPEN_RISK_RATE")
        if not 0 <= self.margin_reserve_rate < 1:
            raise ValueError("MARGIN_RESERVE_RATE must be in [0, 1)")
        if self.min_net_rr < 0:
            raise ValueError("MIN_NET_RR cannot be negative")
        if self.min_net_ev_r < 0:
            raise ValueError("MIN_NET_EV_R cannot be negative")
        if self.max_spread_bps < 0:
            raise ValueError("MAX_SPREAD_BPS cannot be negative")
        if not 1 <= self.orderbook_depth_levels <= 1000:
            raise ValueError("ORDERBOOK_DEPTH_LEVELS must be between 1 and 1000")
        if self.max_orderbook_age_seconds <= 0:
            raise ValueError("MAX_ORDERBOOK_AGE_SECONDS must be positive")
        if self.max_vwap_impact_bps < 0:
            raise ValueError("MAX_VWAP_IMPACT_BPS cannot be negative")
        if self.orderbook_retention_hours < 1:
            raise ValueError("ORDERBOOK_RETENTION_HOURS must be positive")
        if not 0 <= self.fee_rate_taker < 1:
            raise ValueError("FEE_RATE_TAKER must be in [0, 1)")
        if self.base_slippage_bps < 0:
            raise ValueError("BASE_SLIPPAGE_BPS cannot be negative")
        if self.model_entry_spread_bps < 0:
            raise ValueError("MODEL_ENTRY_SPREAD_BPS cannot be negative")
        if self.stop_gap_reserve_bps < 0:
            raise ValueError("STOP_GAP_RESERVE_BPS cannot be negative")
        if self.max_ticker_age_seconds <= 0:
            raise ValueError("MAX_TICKER_AGE_SECONDS must be positive")
        if self.max_candle_age_seconds <= 0:
            raise ValueError("MAX_CANDLE_AGE_SECONDS must be positive")
        if self.signal_ttl_minutes <= 0:
            raise ValueError("SIGNAL_TTL_MINUTES must be positive")
        if self.default_leverage < 1 or self.max_leverage < self.default_leverage:
            raise ValueError("Leverage policy is inconsistent")
        if self.model_refresh_seconds < 30:
            raise ValueError("MODEL_REFRESH_SECONDS must be at least 30")
        if self.drift_window_hours < 24:
            raise ValueError("DRIFT_WINDOW_HOURS must be at least 24")
        if self.drift_min_feature_observations < 1:
            raise ValueError("DRIFT_MIN_FEATURE_OBSERVATIONS must be positive")
        if self.drift_min_outcome_observations < 1:
            raise ValueError("DRIFT_MIN_OUTCOME_OBSERVATIONS must be positive")
        if not 0 < self.drift_min_coverage_rate <= 1:
            raise ValueError("DRIFT_MIN_COVERAGE_RATE must be in (0, 1]")
        if not 0 <= self.drift_max_missing_rate < 1:
            raise ValueError("DRIFT_MAX_MISSING_RATE must be in [0, 1)")
        if not 0 < self.drift_warning_psi < self.drift_critical_psi:
            raise ValueError(
                "DRIFT_WARNING_PSI must be positive and lower than DRIFT_CRITICAL_PSI"
            )
        if self.drift_max_log_loss_delta < 0:
            raise ValueError("DRIFT_MAX_LOG_LOSS_DELTA cannot be negative")
        if self.drift_max_brier_delta < 0:
            raise ValueError("DRIFT_MAX_BRIER_DELTA cannot be negative")
        if not 0 <= self.drift_max_actionability_rate_delta <= 1:
            raise ValueError("DRIFT_MAX_ACTIONABILITY_RATE_DELTA must be in [0, 1]")
        if self.experiment_pbo_segments < 4 or self.experiment_pbo_segments % 2:
            raise ValueError("EXPERIMENT_PBO_SEGMENTS must be an even integer of at least four")
        if self.experiment_min_trials < 2:
            raise ValueError("EXPERIMENT_MIN_TRIALS must be at least two")
        if self.experiment_min_periods < self.experiment_pbo_segments * 2:
            raise ValueError(
                "EXPERIMENT_MIN_PERIODS must provide at least two rows per PBO segment"
            )
        if not 0 <= self.experiment_max_pbo <= 1:
            raise ValueError("EXPERIMENT_MAX_PBO must be in [0, 1]")
        if not 0 <= self.experiment_min_dsr_probability <= 1:
            raise ValueError("EXPERIMENT_MIN_DSR_PROBABILITY must be in [0, 1]")
        if self.max_account_snapshot_age_seconds < 30:
            raise ValueError("MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS must be at least 30")
        if self.initial_backfill_bars < self.universe_min_history_bars:
            raise ValueError("INITIAL_BACKFILL_BARS must cover UNIVERSE_MIN_HISTORY_BARS")
        if self.history_backfill_target_days < 30:
            raise ValueError("HISTORY_BACKFILL_TARGET_DAYS must be at least 30")
        if self.history_backfill_interval_seconds < 30:
            raise ValueError("HISTORY_BACKFILL_INTERVAL_SECONDS must be at least 30")
        if self.history_backfill_symbols_per_cycle < 1:
            raise ValueError("HISTORY_BACKFILL_SYMBOLS_PER_CYCLE must be positive")
        if self.history_backfill_pages_per_symbol < 1:
            raise ValueError("HISTORY_BACKFILL_PAGES_PER_SYMBOL must be positive")
        if not 50 <= self.history_backfill_page_size <= 1000:
            raise ValueError("HISTORY_BACKFILL_PAGE_SIZE must be between 50 and 1000")
        if self.outcome_intrabar_max_windows_per_cycle < 1:
            raise ValueError("OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE must be positive")
        if self.auto_train_interval_hours < 1:
            raise ValueError("AUTO_TRAIN_INTERVAL_HOURS must be at least 1")
        if self.auto_train_retry_hours < 1:
            raise ValueError("AUTO_TRAIN_RETRY_HOURS must be at least 1")
        if self.auto_train_recovery_retry_minutes < 1:
            raise ValueError("AUTO_TRAIN_RECOVERY_RETRY_MINUTES must be at least 1")
        if (
            not math.isfinite(self.timeout_gross_return_rate)
            or not -1 < self.timeout_gross_return_rate < 1
        ):
            raise ValueError("TIMEOUT_GROSS_RETURN_RATE must be finite and in (-1, 1)")
        if self.auto_train_check_seconds < 30:
            raise ValueError("AUTO_TRAIN_CHECK_SECONDS must be at least 30")
        if self.auto_train_initial_delay_seconds < 0:
            raise ValueError("AUTO_TRAIN_INITIAL_DELAY_SECONDS cannot be negative")
        if self.auto_train_lookback_days < 30:
            raise ValueError("AUTO_TRAIN_LOOKBACK_DAYS must be at least 30")
        if self.auto_train_max_symbols < 0:
            raise ValueError("AUTO_TRAIN_MAX_SYMBOLS cannot be negative")
        if self.auto_train_min_new_timestamps < 1:
            raise ValueError("AUTO_TRAIN_MIN_NEW_TIMESTAMPS must be positive")
        if self.auto_train_data_change_cooldown_hours < 1:
            raise ValueError("AUTO_TRAIN_DATA_CHANGE_COOLDOWN_HOURS must be at least 1")
        if self.auto_train_min_new_rows < 1:
            raise ValueError("AUTO_TRAIN_MIN_NEW_ROWS must be positive")
        if not 0 < self.auto_train_min_dataset_growth_ratio <= 1:
            raise ValueError("AUTO_TRAIN_MIN_DATASET_GROWTH_RATIO must be in (0, 1]")
        if self.auto_train_min_new_symbols < 1:
            raise ValueError("AUTO_TRAIN_MIN_NEW_SYMBOLS must be positive")
        if not 0 < self.auto_train_min_universe_change_ratio <= 1:
            raise ValueError("AUTO_TRAIN_MIN_UNIVERSE_CHANGE_RATIO must be in (0, 1]")
        if self.auto_train_min_bars_per_symbol < 72:
            raise ValueError("AUTO_TRAIN_MIN_BARS_PER_SYMBOL must be at least 72")
        if not 0 < self.auto_train_min_symbol_coverage_ratio <= 1:
            raise ValueError("AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO must be in (0, 1]")
        if self.auto_train_min_holdout_rows < 90:
            raise ValueError("AUTO_TRAIN_MIN_HOLDOUT_ROWS must be at least 90")
        if self.auto_train_min_holdout_span_hours < 24:
            raise ValueError("AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS must be at least 24")
        if self.auto_train_min_holdout_span_hours < self.default_horizon_hours:
            raise ValueError(
                "AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS cannot be shorter than "
                "DEFAULT_HORIZON_HOURS"
            )
        if not 0 < self.auto_train_min_class_fraction < 1 / 3:
            raise ValueError("AUTO_TRAIN_MIN_CLASS_FRACTION must be between 0 and 1/3")
        if self.auto_train_max_log_loss <= 0 or self.auto_train_max_multiclass_brier <= 0:
            raise ValueError("Automatic training quality limits must be positive")
        if not 0 < self.auto_train_max_ece < 1:
            raise ValueError("AUTO_TRAIN_MAX_ECE must be between 0 and 1")
        if self.auto_train_max_log_loss_regression < 0 or self.auto_train_max_brier_regression < 0:
            raise ValueError("Automatic training regression tolerances cannot be negative")
        if self.auto_train_min_metric_improvement < 0:
            raise ValueError("AUTO_TRAIN_MIN_METRIC_IMPROVEMENT cannot be negative")
        if self.auto_train_min_policy_trades < 1:
            raise ValueError("AUTO_TRAIN_MIN_POLICY_TRADES must be positive")
        if not 0 < self.auto_train_min_policy_trade_rate <= 1:
            raise ValueError("AUTO_TRAIN_MIN_POLICY_TRADE_RATE must be in (0, 1]")
        if self.auto_train_min_policy_cohorts < 1:
            raise ValueError("AUTO_TRAIN_MIN_POLICY_COHORTS must be positive")
        if self.auto_train_policy_bootstrap_samples < 500:
            raise ValueError("AUTO_TRAIN_POLICY_BOOTSTRAP_SAMPLES must be at least 500")
        if not 0.80 <= self.auto_train_policy_confidence_level < 1.0:
            raise ValueError("AUTO_TRAIN_POLICY_CONFIDENCE_LEVEL must be in [0.80, 1.0)")
        if not math.isfinite(self.auto_train_min_policy_mean_r_lcb):
            raise ValueError("AUTO_TRAIN_MIN_POLICY_MEAN_R_LCB must be finite")
        if self.auto_train_min_policy_profit_factor < 0:
            raise ValueError("AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR cannot be negative")
        if self.auto_train_max_policy_drawdown_r <= 0:
            raise ValueError("AUTO_TRAIN_MAX_POLICY_DRAWDOWN_R must be positive")
        if self.auto_train_max_policy_mean_r_regression < 0:
            raise ValueError("AUTO_TRAIN_MAX_POLICY_MEAN_R_REGRESSION cannot be negative")
        if self.auto_train_max_policy_drawdown_regression_r < 0:
            raise ValueError("AUTO_TRAIN_MAX_POLICY_DRAWDOWN_REGRESSION_R cannot be negative")
        if self.auto_train_min_policy_improvement_r < 0:
            raise ValueError("AUTO_TRAIN_MIN_POLICY_IMPROVEMENT_R cannot be negative")
        if self.auto_train_enabled and self.auto_train_auto_activate:
            if self.auto_train_min_policy_realized_mean_r < 0:
                raise ValueError(
                    "AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R cannot be negative when auto-activation is enabled"
                )
            if self.auto_train_min_policy_mean_r_lcb < 0:
                raise ValueError(
                    "AUTO_TRAIN_MIN_POLICY_MEAN_R_LCB cannot be negative when auto-activation is enabled"
                )
            if self.auto_train_min_policy_profit_factor < 1:
                raise ValueError(
                    "AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR must be at least 1 when auto-activation is enabled"
                )
        if self.app_mode == "production":
            errors: list[str] = []
            if self.allow_demo_seed:
                errors.append("ALLOW_DEMO_SEED must be false")
            if self.allow_baseline_model:
                errors.append("ALLOW_BASELINE_MODEL must be false")
            if self.allow_baseline_actionable:
                errors.append("ALLOW_BASELINE_ACTIONABLE must be false")
            if self.secret_key.startswith("replace-with") or len(self.secret_key) < 32:
                errors.append("SECRET_KEY must be a non-default value of at least 32 characters")
            if self.operator_password == "change-me-now" or len(self.operator_password) < 12:
                errors.append("OPERATOR_PASSWORD must be changed and contain at least 12 characters")
            if (
                self.auto_train_enabled
                and self.auto_train_auto_activate
                and not self.auto_train_require_improvement
            ):
                errors.append(
                    "AUTO_TRAIN_REQUIRE_IMPROVEMENT must be true when production auto-activation is enabled"
                )
            if errors:
                raise ValueError("Unsafe production configuration: " + "; ".join(errors))
        return self

    @property
    def mutating_auth_configured(self) -> bool:
        return bool(self.operator_api_token or self.operator_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()

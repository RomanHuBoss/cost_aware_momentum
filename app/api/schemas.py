from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class CapitalProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    mode: Literal["manual", "paper", "bybit_read_only"] = "manual"
    allocated_capital: Decimal = Field(gt=0)
    risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("1"))
    max_total_risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("1"))
    default_leverage: int | None = Field(default=None, ge=1)
    max_leverage: int | None = Field(default=None, ge=1)
    margin_reserve_rate: Decimal | None = Field(default=None, ge=0, lt=Decimal("1"))
    source_account_id: str | None = None


class CapitalProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    allocated_capital: Decimal | None = Field(default=None, gt=0)
    risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("1"))
    max_total_risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("1"))
    default_leverage: int | None = Field(default=None, ge=1)
    max_leverage: int | None = Field(default=None, ge=1)
    margin_reserve_rate: Decimal | None = Field(default=None, ge=0, lt=Decimal("1"))


class RecommendationExposureRequest(BaseModel):
    plan_id: UUID
    plan_version: int = Field(ge=1)
    client_event_id: UUID
    page_instance_id: UUID
    observed_at: datetime
    viewport_ratio: Decimal = Field(ge=Decimal("0.50"), le=Decimal("1"))
    dwell_ms: int = Field(ge=1000, le=600_000)
    surface: Literal["RECOMMENDATION_TILE"] = "RECOMMENDATION_TILE"

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class RecommendationExposureBatchRequest(BaseModel):
    exposures: list[RecommendationExposureRequest] = Field(min_length=1, max_length=100)


class DecisionRequest(BaseModel):
    plan_id: UUID | None = None
    reason_code: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)


class ManualEntryRequest(BaseModel):
    plan_id: UUID
    entry_time: datetime
    entry_price: Decimal = Field(gt=0)
    qty: Decimal = Field(gt=0)
    leverage: int = Field(ge=1)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("entry_time")
    @classmethod
    def entry_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("entry_time must include a timezone")
        return value


class TradeCloseRequest(BaseModel):
    fill_time: datetime
    exit_price: Decimal = Field(gt=0)
    qty: Decimal = Field(gt=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    funding: Decimal = Decimal("0")
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("fill_time")
    @classmethod
    def fill_time_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fill_time must include a timezone")
        return value


class TrainerControlRequest(BaseModel):
    action: Literal["CHECK_NOW", "RECOVER_NOW", "CANCEL_EXPERIMENT"]
    experiment_family: str | None = Field(default=None, min_length=1, max_length=160)
    candidate_version: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_exact_experiment_target(self) -> TrainerControlRequest:
        family = (self.experiment_family or "").strip() or None
        candidate = (self.candidate_version or "").strip() or None
        if self.action == "CANCEL_EXPERIMENT":
            if family is None or candidate is None:
                raise ValueError(
                    "CANCEL_EXPERIMENT requires experiment_family and candidate_version"
                )
        elif family is not None or candidate is not None:
            raise ValueError(
                "Experiment target fields are only valid for CANCEL_EXPERIMENT"
            )
        self.experiment_family = family
        self.candidate_version = candidate
        return self


class DemoSeedRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

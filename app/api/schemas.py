from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
    action: Literal["CHECK_NOW", "RECOVER_NOW"]


class DemoSeedRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

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
    risk_rate: Decimal = Field(default=Decimal("0.0035"), gt=0, le=Decimal("0.02"))
    max_total_risk_rate: Decimal = Field(default=Decimal("0.02"), gt=0, le=Decimal("0.20"))
    default_leverage: int = Field(default=3, ge=1, le=5)
    max_leverage: int = Field(default=5, ge=1, le=5)
    margin_reserve_rate: Decimal = Field(default=Decimal("0.25"), ge=0, le=Decimal("0.9"))
    source_account_id: str | None = None

    @field_validator("max_leverage")
    @classmethod
    def validate_leverage(cls, value: int, info):
        default = info.data.get("default_leverage", 1)
        if value < default:
            raise ValueError("max_leverage cannot be lower than default_leverage")
        return value


class CapitalProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    allocated_capital: Decimal | None = Field(default=None, gt=0)
    risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("0.02"))
    max_total_risk_rate: Decimal | None = Field(default=None, gt=0, le=Decimal("0.20"))
    default_leverage: int | None = Field(default=None, ge=1, le=5)
    max_leverage: int | None = Field(default=None, ge=1, le=5)
    margin_reserve_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.9"))


class DecisionRequest(BaseModel):
    plan_id: UUID | None = None
    reason_code: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)


class ManualEntryRequest(BaseModel):
    plan_id: UUID
    entry_time: datetime
    entry_price: Decimal = Field(gt=0)
    qty: Decimal = Field(gt=0)
    leverage: int = Field(ge=1, le=5)
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


class DemoSeedRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

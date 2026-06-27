"""Initial PostgreSQL schemas, core tables, glossary and baseline profiles.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from alembic import op
from sqlalchemy import text

from app.db import models  # noqa: F401
from app.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["reference", "market", "research", "model", "advisory", "audit", "ops"]

GLOSSARY = {
    "long": (
        "Рекомендация рассмотреть длинную позицию: прибыль предполагается при росте цены.",
        "LONG не является приказом на вход. Перед ручным исполнением проверьте цену, срок действия и риск-план.",
    ),
    "short": (
        "Рекомендация рассмотреть короткую позицию: прибыль предполагается при снижении цены.",
        "SHORT не является приказом на вход. Перед ручным исполнением проверьте цену, срок действия и риск-план.",
    ),
    "no_trade": (
        "После издержек и риск-фильтров достаточного преимущества не найдено.",
        "NO TRADE формируется решающим слоем, а не отдельным состоянием рынка. Причина доступна в подробностях.",
    ),
    "watch": (
        "Кандидат близок к условиям публикации, но обязательное условие еще не выполнено.",
        "Например, цена находится вне зоны входа или ожидается подтверждение свежих данных.",
    ),
    "blocked": (
        "Рыночный сигнал существует, но исполнение запрещено конкретным ограничением.",
        "Блокировка может быть связана с минимальным ордером, маржой, ликвидностью, портфелем или устаревшими данными.",
    ),
    "entry_zone": (
        "Диапазон допустимой цены входа.",
        "Вход за пределами зоны требует нового расчета, поскольку меняются издержки, R/R и размер позиции.",
    ),
    "sl": (
        "Цена защитного выхода; фактический убыток может быть больше при проскальзывании или разрыве цены.",
        "Stop Loss ограничивает плановый риск, но не гарантирует исполнение ровно по указанной цене.",
    ),
    "tp": (
        "Цена плановой фиксации прибыли.",
        "При нескольких целях итоговый расчет учитывает долю позиции на каждом уровне.",
    ),
    "rr_net": (
        "Отношение чистой прибыли по плану к стресс-убытку при SL. Это не вероятность успеха.",
        "Например, 1,91 означает 1,91 единицы потенциальной чистой прибыли на одну единицу планового риска.",
    ),
    "ev_net_r": (
        "Средний модельный результат сопоставимых OOS-сделок после издержек, выраженный в R.",
        "Положительный EV не гарантирует прибыль конкретной сделки и зависит от качества калибровки и модели издержек.",
    ),
    "risk_usdt": (
        "Максимальный плановый стресс-убыток для выбранного профиля капитала.",
        "Он включает расстояние до SL, комиссии, ожидаемое проскальзывание и резерв на неблагоприятное исполнение.",
    ),
    "notional": (
        "Полная стоимость позиции без учета плеча.",
        "Notional не равен марже и не равен максимальному убытку; риск определяется торговым планом и стопом.",
    ),
    "margin": (
        "Оценка средств, резервируемых для позиции.",
        "Маржа не является риском. При одинаковом notional повышение плеча уменьшает initial margin, но повышает риск ликвидации.",
    ),
    "leverage": (
        "Отношение notional к используемой марже.",
        "Плечо не улучшает R/R и EV на notional; оно меняет требования к марже и запас до ликвидации.",
    ),
    "mark_price": (
        "Расчетная цена Bybit для P&L и ликвидации; может отличаться от последней сделки.",
        "Для контроля ликвидационного риска используется mark price, а не только last price.",
    ),
    "funding": (
        "Периодический платеж между LONG и SHORT в момент settlement.",
        "Funding учитывается только если позиция открыта в конкретный момент расчета; интервал зависит от инструмента.",
    ),
    "p_tp": (
        "Калиброванная вероятность достижения TP раньше SL на указанном горизонте.",
        "Она относится к конкретным барьерам, модели, горизонту и версии калибровки; это не общая уверенность системы.",
    ),
    "capital_profile": (
        "Набор параметров капитала и риск-политики, для которого рассчитываются qty, маржа и исполнимость.",
        "Смена профиля не меняет рыночное направление, entry, SL/TP, net R/R и EV сигнала.",
    ),
    "c_eff": (
        "Консервативный капитал, используемый для расчета размера позиции.",
        "В live-режиме обычно равен минимуму выделенного капитала, текущей equity и equity начала дня.",
    ),
    "stale_data": (
        "Обязательные данные старше допустимого порога.",
        "При stale data система блокирует действие, а не подставляет устаревшее значение молча.",
    ),
    "liquidation_buffer": (
        "Запас между защитным планом и расчетной областью ликвидации.",
        "Недостаточный запас блокирует увеличение плеча даже при наличии свободной маржи.",
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    for schema in SCHEMAS:
        bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    Base.metadata.create_all(bind=bind)

    now = datetime.now(UTC)
    glossary_table = Base.metadata.tables["advisory.ui_glossary"]
    op.bulk_insert(
        glossary_table,
        [
            {
                "help_key": key,
                "locale": "ru",
                "short_text": short,
                "long_text": long,
                "version": "ru-2026-06-25",
                "valid_from": now,
                "active": True,
            }
            for key, (short, long) in GLOSSARY.items()
        ],
    )

    profile_table = Base.metadata.tables["advisory.capital_profiles"]
    profiles = [
        {
            "id": UUID("50000000-0000-4000-8000-000000000001"),
            "user_id": "local-operator",
            "name": "Личный 500",
            "mode": "manual",
            "allocated_capital": Decimal("500"),
            "risk_rate": Decimal("0.0035"),
            "max_total_risk_rate": Decimal("0.02"),
            "default_leverage": 3,
            "max_leverage": 5,
            "margin_reserve_rate": Decimal("0.25"),
            "source_account_id": None,
            "active": True,
            "version": 1,
            "capital_verified": False,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": UUID("50000000-0000-4000-8000-000000000002"),
            "user_id": "local-operator",
            "name": "Основной 5 000",
            "mode": "manual",
            "allocated_capital": Decimal("5000"),
            "risk_rate": Decimal("0.0035"),
            "max_total_risk_rate": Decimal("0.02"),
            "default_leverage": 3,
            "max_leverage": 5,
            "margin_reserve_rate": Decimal("0.25"),
            "source_account_id": None,
            "active": False,
            "version": 1,
            "capital_verified": False,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": UUID("50000000-0000-4000-8000-000000000003"),
            "user_id": "local-operator",
            "name": "Paper 10 000",
            "mode": "paper",
            "allocated_capital": Decimal("10000"),
            "risk_rate": Decimal("0.0035"),
            "max_total_risk_rate": Decimal("0.02"),
            "default_leverage": 3,
            "max_leverage": 5,
            "margin_reserve_rate": Decimal("0.25"),
            "source_account_id": None,
            "active": False,
            "version": 1,
            "capital_verified": False,
            "created_at": now,
            "updated_at": now,
        },
    ]
    op.bulk_insert(profile_table, profiles)

    pref_table = Base.metadata.tables["advisory.operator_preferences"]
    op.bulk_insert(
        pref_table,
        [
            {
                "user_id": "local-operator",
                "active_profile_id": UUID("50000000-0000-4000-8000-000000000001"),
                "locale": "ru",
                "tooltip_mode": "auto",
                "compact_view": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    op.execute(
        text(
            """
            INSERT INTO model.model_registry (
                id, name, version, model_type, artifact_path, artifact_sha256,
                feature_schema_version, calibration_version, training_start, training_end,
                metrics, active, created_at, updated_at
            ) VALUES (
                '60000000-0000-4000-8000-000000000001',
                'Deterministic momentum baseline',
                'baseline-momentum-v1',
                'deterministic_baseline',
                NULL, NULL,
                'hourly-core-v1',
                'baseline-calibration-v1',
                NULL, NULL,
                '{"warning": "Baseline is operational scaffolding, not evidence of profitability."}'::jsonb,
                TRUE,
                :created_at,
                :updated_at
            )
            """
        ).bindparams(created_at=now, updated_at=now)
    )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    for schema in reversed(SCHEMAS):
        bind.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

# Configuration

Основной шаблон: `.env.example`. Значения читаются `app.config.Settings`.

Критические группы:

- Runtime: `APP_MODE`, `APP_HOST`, `APP_PORT`, `SECRET_KEY`, `OPERATOR_PASSWORD`.
- PostgreSQL: `DATABASE_URL`; для integration tests — отдельный `TEST_DATABASE_URL` или безопасный admin URL для создания временной БД.
- Bybit: `BYBIT_BASE_URL`, optional read-only credentials и `BYBIT_READ_ONLY_ACCOUNT`.
- Universe/ingestion: `UNIVERSE_*`, `INITIAL_BACKFILL_BARS`, `HISTORY_BACKFILL_*`, `MARKET_POLL_SECONDS`, `INSTRUMENT_REFRESH_SECONDS`.
- Risk/economics: `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE`, `MIN_NET_RR`, `MIN_NET_EV_R`, fee/slippage/gap reserve и freshness limits.
- Model lifecycle: `AUTO_TRAIN_*`, `MODEL_DIR`, `ACTIVE_MODEL_PATH`.

## Изменения 1.9.1

Новых `.env`-переменных нет. Требуется migration `0009_candle_receipt_availability`. После остановки процессов и backup выполните `python manage.py migrate`; текущий Alembic head — `0009_candle_receipt_availability`.

Новые свечи сохраняют `available_at` равным фактическому post-response receipt time. Migration консервативно сдвигает существующие confirmed candles к времени migration, поскольку их истинное первое receipt time восстановить невозможно. Downgrade не возвращает старые значения: более поздний timestamp остаётся безопасным и совместимым с предыдущим кодом.

## Изменения 1.9.0

Новых `.env`-переменных и migration нет. `TIMEOUT_GROSS_RETURN_RATE` теперь является только fallback для deterministic baseline и legacy diagnostic paths. Для нового ML artifact trainer вычисляет отдельно для LONG/SHORT медиану фактических train-window TIMEOUT returns в единицах gross stop-risk. Final holdout при оценке candidate не участвует в fit этой величины.

Artifact обязан содержать `timeout_return_schema_version=training-direction-median-r-v1`; policy evidence использует `policy_metric_schema=decision-open-entry-exit-time-cohort-v10`. Artifact 1.8.x без нового контракта runtime отклоняет fail-closed. После замены release tree остановите старые процессы и запустите штатный trainer; вручную активировать старый artifact нельзя.

Значение `TIMEOUT_GROSS_RETURN_RATE=-0.002` сохранять допустимо, но его изменение не меняет TIMEOUT economics нового ML artifact. Оно влияет только на baseline/fallback и должно оставаться конечным в `(-1, 1)`.

## Изменения 1.8.36

Новых `.env`-переменных и migration нет. Изменена семантика обучающей выборки: entry proxy берётся из `open` первой свечи после `decision_time`, барьеры рассчитываются как `entry_price × atr_pct_14 × multiplier`.

`label_path_schema_version=decision-open-entry-ohlc-path-v2` и `policy_metric_schema=decision-open-entry-exit-time-cohort-v9`. Старые candidate/active artifacts и policy evidence несовместимы с новой задачей и не должны активироваться вручную. После обновления запустите штатный trainer; incumbent останется fail-closed отклонён runtime при несовместимой label schema, пока не будет активирован новый прошедший gate artifact.

## Изменения 1.8.35

Новых `.env`-переменных нет. Trainer вычисляет минимальную теоретически достаточную часовую историю из текущих `DEFAULT_HORIZON_HOURS`, `AUTO_TRAIN_MIN_HOLDOUT_ROWS` и `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS`. При defaults (`8`, `180`, `168`) требуется минимум **1206** уникальных hourly timestamps до запуска candidate.

Причина `not_enough_history_for_bootstrap` означает, что configured final holdout ещё математически невозможен. Уменьшать holdout gates ради запуска не следует; дождитесь progressive history backfill или увеличьте доступную историю. Это только preflight: gaps/invalid candles, class collapse и policy gates проверяются позже fail-closed.

Promotion дополнительно требует `log_loss_skill_vs_prior > 0`. Отдельной настройки порога нет: прогноз хуже либо равный class-prior baseline не является допустимым основанием для auto-activation.

## Изменения 1.8.34

- `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168` — минимальная разница между первой и последней decision-time точкой final holdout. Rows по множеству символов не компенсируют слишком короткий календарный период. Минимально допустимое значение — 24 часа и не меньше `DEFAULT_HORIZON_HOURS`.
- `AUTO_TRAIN_MIN_POLICY_COHORTS=20` теперь означает число greedily выбранных decision-time когорт, разделённых не менее чем на `DEFAULT_HORIZON_HOURS`; raw hourly cohorts сохраняются только как диагностическая метрика `policy_cohorts`.
- После `quality_gate_failed` bootstrap/recovery не повторяется на том же training-data profile. После cooldown нужен `AUTO_TRAIN_MIN_NEW_TIMESTAMPS` либо material dataset change; техническая ошибка обучения по-прежнему использует короткий recovery backoff.

Новая переменная имеет безопасный default. Migration не требуется. Старые policy metrics schema v7 не совместимы с promotion gate v8 и должны быть пересчитаны штатным trainer.

## Изменения 1.8.33

Новые обратно совместимые переменные:

- `ALLOW_BASELINE_ACTIONABLE=false` — deterministic baseline остаётся диагностическим fallback и не может создавать/сохранять исполнимый план. В `production` значение `true` запрещено.
- `TIMEOUT_GROSS_RETURN_RATE=-0.002` — в релизах 1.8.x это была общая gross return гипотеза исхода TIMEOUT до fee/slippage. Начиная с 1.9.0 она остаётся только baseline/legacy fallback.
- `AUTO_TRAIN_MIN_POLICY_COHORTS=20` — минимальное число независимых decision-time когорт. Оно больше не наследуется от `AUTO_TRAIN_MIN_POLICY_TRADES`.

Изменение `.env` не обязательно: указанные defaults сохраняют совместимость. После обновления рекомендуется явно добавить переменные, чтобы policy assumptions были видны оператору.

## Изменения 1.8.32

Новых или переименованных переменных нет.

- Alembic graph снова имеет единственный head `0008_outcome_path_unavailable`; ошибочно включённая дублирующая migration удалена.
- Policy metric schema повышена до `exit-time-open-gap-single-symbol-cohort-v7`. Candidate и incumbent пересчитываются текущим trainer на одном holdout; старые v6 evidence не подходят для promotion.
- Backtest теперь возвращает `actionable_candidates` и `overlap_blocked_trades`; promotion metrics — `policy_actionable_candidates` и `policy_overlap_blocked_trades`.
- Пороговые значения риска, fee/slippage/funding и auto-activation не менялись.

## Изменения 1.8.31

Новых или переименованных переменных нет.

- Архив 1.8.30 не следует развёртывать: его Alembic revision ID имел 34 символа и не помещался в стандартный `alembic_version.version_num VARCHAR(32)`.
- Исправленный head: `0008_outcome_path_unavailable` (29 символов).
- Не расширяйте `alembic_version.version_num` вручную. После неудачной попытки 1.8.30 PostgreSQL штатно откатывает транзакцию; замените код на 1.8.31 и повторите `python manage.py migrate`.

## Изменения 1.8.30

Новых или переименованных переменных нет.

- Требуется Alembic migration `0008_outcome_path_unavailable`.
- Policy metric schema повышена до `exit-time-open-gap-propagated-cohort-weighted-v6`; новые candidate/incumbent evidence должны быть пересчитаны текущим trainer.
- Пороговые значения риска, fee/slippage/funding и auto-activation не менялись.

## Изменения 1.8.29

Новых или переименованных переменных нет.

- `scripts/backtest.py` принимает optional `--model-sha256` для fail-closed проверки ожидаемого artifact hash.
- Активные/исследовательские artifacts обязаны содержать совместимые `feature_schema_version`, `label_path_schema_version` и `temporal_split_schema`. Legacy artifact необходимо переобучить, а не обходить проверку.
- Пороговые значения риска, fee/slippage/funding и auto-activation не менялись.

## Изменения 1.8.28

Новых переменных нет.

- `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=false` теперь явно исключает известные Bybit TradFi product families `stock`, `forex`, `commodity`, `xstocks` и `xstock` из crypto model domain.
- Значения `symbolType`, обозначающие обычные криптовалютные регионы/сегменты (например, `innovation`), не блокируются.
- `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true` сохраняет прежний явный opt-in и допускает эти типы. Используйте его только при отдельной модели, данных и risk policy для соответствующего market domain.
- Bybit credentials, endpoints, PostgreSQL schema и остальные policy defaults не изменены.

## Семантика 1.8.27

- Для `manual`/`paper` `allocated_capital` является также теоретической базой доступной маржи; к ней применяется существующий `margin_reserve_rate`.
- Account/profile-scoped margin уже принятых планов, а для manual/paper также открытых journal trades, вычитается до sizing и acceptance.
- Денежная `fee` ручного входа заменяет модельную entry-leg комиссию при расчёте stress loss.
- Фактический stress loss и margin requirement не могут превышать reservations принятого immutable execution plan.

# Iteration report — historical dynamic bootstrap

Дата: 2026-07-07  
Версия: 1.52.0

## Исходный симптом

На чистой PostgreSQL базе trainer в `UNIVERSE_MODE=dynamic` показывал `0 из 1206`, хотя historical candles уже загружались. Причина состояла не в скорости обучения: pre-installation rows принудительно исключались до первого prospective universe snapshot. При hourly accumulation минимальное ожидание составляло примерно 50 суток.

## Подтверждённые дефекты

1. Dynamic replay был единственным допустимым background-training path и отбрасывал весь pre-rollout backfill.
2. Historical bootstrap невозможно было корректно запустить простым отключением replay: local `InstrumentSpecHistory.received_at` относится к моменту установки, поэтому historical decision rows не имели point-in-time tick size.
3. Full-sample coverage cap перед exact dynamic replay создавал риск survivorship/selection look-ahead.
4. Trainer мог загружать большой candle set каждые пять минут, даже когда prospective snapshot span математически не мог покрыть minimum history.
5. Training scope не имел отдельной формализованной provenance для frozen bootstrap и exact prospective replay.
6. Bootstrap snapshot cohort не был связан с artifact quality gate отдельным immutable evidence contract.
7. Background trigger profile parsing недостаточно жёстко проверял timestamps, counts и hashes.
8. Scheduled timestamp delta мог включать часы инструментов вне exact fitted cohort.
9. Не было автоматического перехода bootstrap artifact → exact prospective replay artifact.
10. Freshness текущего snapshot не проверялась как отдельная bootstrap boundary.

## Реализация

### Universe scope

Добавлены три режима:

- `static_configured`;
- `historical_frozen_dynamic_bootstrap`;
- `prospective_dynamic_replay`.

Clean-install dynamic trainer:

1. Проверяет span committed prospective snapshots без тяжёлой загрузки candles.
2. Если exact replay уже достаточен, использует только его.
3. Иначе берёт последний свежий hash-validated dynamic snapshot.
4. Из snapshot извлекает execution-eligible symbols с текущим executable-spread limit.
5. После top-N cap канонизирует cohort и сохраняет ranked/canonical lists, hashes, timestamps и ограничения.
6. Профилирует historical candles только этого frozen cohort.
7. Перед fit повторно требует совпадение evidence symbols с preflight profile.
8. После fit quality gate ещё раз сверяет cohort/profile и mode/replay/spec contracts.

### Instrument specification

Для bootstrap разрешён только pre-observation fallback:

- выбирается earliest locally observed tick;
- fallback доступен только для decision time раньше первого local `received_at`;
- после начала локальной истории никакие gaps не заполняются будущей спецификацией;
- LONG/SHORT entry дополнительно ухудшается на заданное число ticks;
- использование отражается в dataset/artifact diagnostics.

### Econometric safeguards

Не изменялись и не ослаблялись:

- feature warm-up и label horizon;
- purged temporal split;
- expanding walk-forward;
- separate final holdout;
- minimum class fractions;
- log-loss/Brier/ECE gates;
- opportunity-weighted policy evaluation;
- overlap/horizon-phase checks;
- direction, symbol, cluster, regime и interaction robustness;
- bootstrap LCB, drawdown и profit-factor limits;
- preregistered experiment selection и cost stress;
- guarded activation.

## Regression evidence

Добавлен `tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py`, покрывающий:

- strict vs pre-observation tick resolution;
- rejection forged/naive training profiles;
- bootstrap hash/symbol evidence contract;
- historical bootstrap selection before sufficient rollout;
- automatic exact prospective upgrade;
- absence full-sample max-symbol cap в exact dynamic replay.

Полный результат: `846 passed, 8 skipped`.

## Не проверено в этой среде

- PostgreSQL integration suite: отдельная `TEST_DATABASE_URL` не предоставлена.
- Live Bybit/network smoke: credentials и внешняя торговая среда не использовались.
- Фактическая продолжительность initial backfill зависит от числа symbols, Bybit API rate limits и настроек history worker.
- Прибыльность не следует из unit/static validation и должна подтверждаться paper/shadow/forward evidence.

## Остаточный модельный риск

`historical_frozen_dynamic_bootstrap` является честно маркированным cold-start approximation, а не реконструкцией исторического dynamic universe. Поэтому exact prospective model остаётся целевым artifact и автоматически заменяет bootstrap после накопления достаточной глубины.

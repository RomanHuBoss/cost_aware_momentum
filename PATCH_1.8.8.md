# Patch 1.8.8 — quant correctness hardening

## Подтвержденные ошибки

Аудит воспроизвел 10 дефектов: 7 critical и 3 medium.

Critical:

1. EMA и другие stateful features продолжали использовать данные до разрыва часового ряда.
2. Нулевая/невалидная OHLCV-свеча внутри обязательного окна могла попасть в live feature vector.
3. `triple_barrier_outcome` принимал NaN/некогерентный future bar и мог вернуть ложный `TIMEOUT`.
4. Runtime доверял произвольному `predict_proba` active artifact.
5. Decimal EV/R math принимала отрицательные и несуммирующиеся probabilities.
6. Direction selector мог публиковать выбор без парного LONG/SHORT сравнения.
7. Auto-activation policy drawdown учитывал исходы в `decision_time`, создавая look-ahead и неверный порядок перекрывающихся сделок.

Medium:

8. Holdout tie-break зависел от порядка строк вместо production-порядка `EV/R → net RR → LONG`.
9. Research backtest не валидировал probability simplex.
10. `max_leverage < 1` молча превращался в 1x.

## Решение

- Feature engineering сегментирован по непрерывным валидным часовым сериям; gap, duplicate и invalid OHLCV сбрасывают EMA/ATR/rolling state.
- Live snapshot fail-closed помечает поврежденное обязательное окно `INVALID_MARKET_BAR`.
- Barrier labels валидируют future high/low/close до сравнения с барьерами.
- Добавлены общие validators probability matrix и Decimal simplex; они применены в runtime, holdout evaluation, EV/R math и backtest.
- Signal selector требует ровно один LONG и один SHORT и использует детерминированный production tie-break.
- Holdout policy строит exit events из `decision_time + exit_index + 1h`, equal-weight внутри decision cohort и считает drawdown по времени реализации.
- Некорректный exchange max leverage блокируется как `BLOCKED_INVALID_INPUT`.

## Миграции и конфигурация

- Alembic migration не требуется; head остается `0005_plan_outcome_invalid_input`.
- Новых `.env` переменных нет.
- Публичный API и advisory-only boundary не изменены.
- Рекомендуется переобучение модели: strict-hourly feature schema сохранила имя, но исправлена ее ранее нарушенная реализация. Старые и новые holdout policy metrics нельзя напрямую сравнивать без повторного расчета.

## Проверки

- Red: `tests/unit/test_quant_correctness_hardening.py` — `10 failed` на исходном 1.8.7.
- Green: тот же модуль — `10 passed`.
- Полный suite: baseline `184 passed, 4 skipped`; post `194 passed, 4 skipped`.
- `pip check`, `compileall`, Ruff и `node --check web/js/app.js`: PASSED.
- PostgreSQL integration tests не выполнялись: безопасная отдельная `TEST_DATABASE_URL` отсутствовала.

# QA Report — 1.8.36

Дата: 2026-07-02

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `df82eab5721cf1922170594a20aef114eb6b8049a3387eef16696a33e7d23ec7`.
- Исходная версия: `1.8.35`; Python requirement: `>=3.12`.
- Исходный состав: 70 production Python files, 49 test modules, 18 documentation files.
- Alembic revisions: `0001`–`0008`; один head `0008_outcome_path_unavailable`.
- Входной release не содержал `CHANGELOG.md`, `PATCH_*.md` и `SHA256SUMS`, хотя предыдущий QA report утверждал, что они восстановлены. Это подтверждённый release-integrity defect.
- Заявления о десятках ошибок не сопровождались путями, stack traces или reproductions. Severity и исправления ниже основаны только на воспроизводимых доказательствах.

## Baseline до правок

Проверки выполнены в чистом внешнем virtualenv с установкой project/dev dependencies:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **422 passed, 4 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |
| release manifest/check | PASSED | 166 eligible files; 166 manifest entries |

System Python не считался project baseline: в нём был внешний конфликт MoviePy/Pillow, отсутствовал Ruff и не был установлен `psycopg`.

`python manage.py doctor` и `python manage.py test --require-integration` не запускались до completion: штатная project `.venv`, локальный `.env` и отдельная безопасная PostgreSQL test database отсутствовали. Четыре integration tests корректно остались skipped.

## Подтверждённые defects

### HIGH — pre-entry gap contaminates ML labels and promotion evidence

- Путь: `app/ml/training.py::make_barrier_dataset`.
- Фактическое старое поведение: feature row доступен только после close, но `entry = current["close"]`; label path начинался со следующего bar open.
- Reproduction: completed close около 100, first post-decision open 110. Старый dataset дал LONG `TP`, `exit_at_open=True`, `realized_gross_return=+0.01804`; SHORT получил opening-gap `SL=-0.10`.
- Ожидаемое: entry не может предшествовать `decision_time`; для этого пути LONG должен войти около 110 и завершиться TIMEOUT с observed return около `+0.004545`.
- Влияние: искажённые targets, probabilities, holdout P&L/profit factor и auto-promotion evidence; возможна систематическая разница между research и live results.
- Почему тесты не поймали: проверялись OHLC gap execution и temporal boundaries, но не проверялось, что entry price доступен только после feature close.

### MEDIUM — release provenance contradicted archive contents

`CHANGELOG.md`, `PATCH_*.md` и `SHA256SUMS` отсутствовали при наличии документационных утверждений об обратном.

## Исправления

- Decision-time entry proxy — первая observable `open` label-свечи.
- Barrier rates сохраняют live parity: `entry_price × atr_pct_14 × multiplier`.
- Dataset и real holdout metadata содержат `entry_price`; metadata validation проверяет finite positive value.
- Label schema: `decision-open-entry-ohlc-path-v2`.
- Policy metric schema: `decision-open-entry-exit-time-cohort-v9`.
- Старые artifacts/evidence блокируются, а не переиспользуются молча.
- Восстановлены changelog, patch note, iteration report и release manifest.

## Red → green

1. `test_dataset_uses_first_post_decision_open_as_executable_entry_proxy`
   - Red №1: `KeyError: 'entry_price'` на исходном коде.
   - После первого изменения дополнительная независимая assertion выявила geometry mismatch: получено `0.01640`, ожидалось `atr_pct_14 × 2.20 = 0.01804`.
   - Green: entry `110`, LONG `TIMEOUT`, realized return `(110.5-110)/110`.
2. `test_short_dataset_does_not_book_down_gap_before_executable_entry`
   - Green после симметричного исправления: short entry `90`, pre-entry down-gap не записан как TP.
3. Runtime compatibility matrix теперь отдельно проверяет отказ artifact schema `ohlc-open-first-stop-gap-v1`.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **425 passed, 4 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |
| PostgreSQL integration | NOT RUN | отдельная test DB не предоставлена |
| `manage.py doctor` | NOT RUN | local `.env`/PostgreSQL runtime отсутствуют |

## Вывод

Исправлена доказанная temporal/econometric ошибка, способная завышать или искажать research evidence за счёт движения цены до исполнимого входа. Это не доказательство прибыльности и не гарантирует больше рекомендаций. После обновления старые artifacts должны быть переобучены; частые `NO_TRADE` могут остаться корректным следствием costs, EV/RR, liquidity, freshness и model-quality gates.

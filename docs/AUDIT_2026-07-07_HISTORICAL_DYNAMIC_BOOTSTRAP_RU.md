# Аудит и исправления Cost-aware hourly ML momentum 1.52.0

Дата: 7 июля 2026 года  
Исходный архив: `cost_aware_momentum-1.51.1-release-integrity(1).zip`

## Вывод

Заявленные внешними экспертами числа «15 критических + 4 средних» и «ещё 8 критических» невозможно независимо подтвердить без их протоколов, тест-кейсов и указания модулей. Я не приписываю им найденные мною дефекты и не подгоняю число результатов под эти заявления.

В переданном коде подтверждён практический блокирующий дефект clean-install training: dynamic mode исключал historical candle backfill до первого prospective universe snapshot, поэтому при default minimum `1206` часов новая установка могла ждать около 50 суток. Исправлена архитектура cold start, а также связанные нарушения provenance, point-in-time tick geometry, scheduling scope и profile integrity.

## Подтверждённые дефекты и коррекции

### Критические / высокие

| № | Модуль | Дефект | Последствие | Исправление |
|---|---|---|---|---|
| 1 | `app/ml/universe_replay.py`, `app/workers/trainer.py` | Единственный dynamic training path удалял все rows до первого prospective snapshot | Около 50 суток до первой попытки обучения | Добавлен hash-bound frozen-cohort historical bootstrap |
| 2 | `app/ml/training.py` | Historical rows не имели допустимого tick size: local spec `received_at` всегда позже historical decision time | Даже простой static fallback давал пустую/резко усечённую label выборку | Ограниченный pre-observation fallback + adverse extra-tick stress |
| 3 | `app/ml/lifecycle.py` | Exact dynamic profile мог предварительно выбирать symbols по full-sample candle coverage | Survivorship/selection look-ahead | Для exact replay принудительно `max_symbols=0`; cap оставлен только frozen cohort |
| 4 | `app/ml/lifecycle.py`, `app/workers/trainer.py` | Bootstrap/exact/static происхождение model dataset не было отдельным обязательным контрактом | Artifact мог неверно интерпретироваться как прошедший exact replay | Введены `training_universe_mode` и mode-specific quality checks |
| 5 | `app/workers/trainer.py` | Bootstrap cohort не был повторно связан с preflight profile перед fit | TOCTOU/scope drift между проверкой и обучением | Evidence symbols канонизируются и должны точно совпасть с profile symbols |
| 6 | `app/ml/lifecycle.py` | Quality gate не проверял соответствие frozen cohort фактически fitted profile | Подмена/расширение cohort могла остаться незамеченной | Добавлен `historical_bootstrap_cohort_profile_mismatch` fail-closed check |
| 7 | `app/ml/data_profile.py` | Profile parser принимал недостаточно проверенные counts/time/hashes; zero-symbol profile мог заявить 1206 timestamps | Forged trigger evidence мог обойти minimum-history preflight | Полная проверка timezone, counts, ranges, `unique_timestamps <= candle_rows`, coverage и SHA-256 identity |
| 8 | `app/workers/trainer.py` | New timestamp trigger мог считать данные symbols вне fitted cohort | Ложные retraining triggers | Delta считается по exact profile или SQL-фильтру symbols |
| 9 | `app/workers/trainer.py` | Не было автоматического перехода cold-start model к exact prospective model | Bootstrap approximation могла оставаться активной бессрочно | Mode change создаёт отдельный retraining trigger |
| 10 | `app/ml/lifecycle.py` | Тяжёлый replay выполнялся при каждом check до того, как snapshot span мог достичь minimum | Ненужная DB/CPU нагрузка и задержки trainer | Добавлен дешёвый prospective rollout precheck |
| 11 | `app/ml/lifecycle.py` | Bootstrap мог использовать устаревший current-universe snapshot | Frozen cohort не отражал текущую execution eligibility | Snapshot freshness boundary; stale/future snapshot отклоняется |
| 12 | `app/ml/lifecycle.py` | Manual dynamic training без явного mode мог маркироваться static при включённом replay | Противоречивый artifact/gate contract | Mode выводится из `require_universe_replay`, если не задан явно |

### Средние

| № | Модуль | Дефект | Исправление |
|---|---|---|---|
| M1 | `app/config.py` | Bootstrap minimum symbols мог противоречить max-symbol cap | Добавлена cross-field validation |
| M2 | `app/config.py` | Tick-stress parameter не имел жёсткого безопасного диапазона | Разрешено только 1–5 ticks |
| M3 | `app/ml/data_profile.py` | Нулевая row count могла сочетаться с time range, а positive count — без range | Добавлена per-symbol temporal consistency validation |
| M4 | `README.md`, operator/config docs | Документация описывала 50-дневное ожидание как обязательное | Описан новый bootstrap, его ограничения и automatic prospective upgrade |
| M5 | `app/ml/universe_replay.py` | Spread limit helper сравнивал `Decimal` с caller value без единой runtime normalization | Лимит теперь валидируется и канонизируется через `Decimal(str(value))` |

## Почему это ускоряет обучение

При default quality gate по-прежнему требуется не менее 1206 уникальных label-eligible часовых отметок. Теперь эти часы могут быть взяты из уже загруженной истории для свежего, неизменяемого dynamic cohort. Trainer больше не ждёт 1206 часов настенного времени.

Ожидаемый cold-start pipeline:

1. Worker сохраняет свежий dynamic universe snapshot.
2. Worker загружает historical last/mark/index candles, funding/context и current instrument specs.
3. Trainer фиксирует execution-eligible cohort и проверяет его hashes/freshness.
4. После появления 1206+ пригодных часов запускается fit.
5. Candidate проходит прежние temporal/econometric/policy/experiment gates.
6. После накопления полной prospective universe history создаётся replacement candidate с exact dynamic replay.

Практический срок зависит от backfill. При уже загруженных данных это может быть ближайший пятиминутный trainer check плюс время fit/experiment; на пустой базе обычно ограничителем становится history worker и API rate limits, а не 50 суток.

## Почему «без потери качества» требует оговорки

Ни один численный quality/promotion/risk threshold не снижен. Однако frozen current cohort не является точной реконструкцией того, какие инструменты dynamic policy выбрала бы год назад. Это неизбежный cold-start компромисс при отсутствии исторических eligibility snapshots.

Чтобы не скрывать риск:

- artifact явно маркируется `historical_frozen_dynamic_bootstrap`;
- historical dynamic membership не фабрикуется;
- snapshot schema/policy/record hashes и freshness обязательны;
- historical pre-observation tick получает консервативный adverse stress;
- exact prospective replay имеет приоритет и автоматически заменяет bootstrap;
- все temporal, calibration, policy, cost-stress и activation gates сохранены.

## Проверки

| Проверка | Результат |
|---|---|
| `pytest -q` | `846 passed, 8 skipped` |
| `ruff check app tests scripts manage.py` | passed |
| `python -m compileall -q app scripts tests manage.py` | passed |
| `node --check web/js/app.js` | passed |
| `alembic heads` | `0018_inference_observations (head)` |
| Release integrity | выполняется после очистки и формирования final manifest |
| PostgreSQL integration | не выполнялась: отсутствует отдельная `TEST_DATABASE_URL` |
| Live Bybit smoke | не выполнялся: сеть/credentials не использовались |
| `mypy app scripts --ignore-missing-imports` | 449 ошибок в 42 файлах; существующий typing debt, release не объявляется mypy-clean |

`pip check` в общей среде сообщил внешний конфликт `moviepy`/`pillow`, не относящийся к зависимостям или runtime-коду проекта. Поэтому этот результат не используется как доказательство дефекта проекта.

## Остаточные ограничения

- Исторические bid/ask, depth, queue position и фактическая latency/fill trajectory не реконструируются.
- Историческое время получения market-context данных до начала локального ledger неизвестно.
- Earliest locally observed tick — conservative proxy, а не доказанная historical specification.
- Frozen-cohort bootstrap содержит current-cohort selection/survivorship limitation; она явно записана в artifact.
- Unit tests и quality gate не доказывают прибыльность; необходимы paper/shadow/forward наблюдения.
- Полный typing cleanup и PostgreSQL integration прогон следует выполнять отдельной итерацией.

## Файлы основных изменений

- `app/workers/trainer.py`
- `app/ml/lifecycle.py`
- `app/ml/training.py`
- `app/ml/universe_replay.py`
- `app/ml/data_profile.py`
- `app/config.py`
- `tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py`
- `.env.example`, `README.md`, `docs/*`

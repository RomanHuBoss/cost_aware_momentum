# Operator Manual

## Upgrade to 1.16.0

1. Остановите API, worker и trainer; сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники. Migration отсутствует; ожидаемый Alembic head остаётся `0011_selection_experiment`.
3. В существующем `.env` установите `UNIVERSE_SYNC_MARK_PRICE=true` и `UNIVERSE_ENRICH_FUNDING_OI=true`.
4. Запустите worker и проверьте `history_backfill.index_price_history` и `history_backfill.open_interest_history` для всех training symbols. Не подставляйте last price вместо index/mark и не заполняйте OI гэпы нулями.
5. Дождитесь достаточного покрытия, затем переобучите candidate. Artifact 1.15.0 несовместим с `hourly-barrier-market-context-v4` и должен быть отклонён fail-closed.
6. Перед activation проверьте artifact metadata: context/availability/ablation schemas, complete/incomplete row counts, final ablation benefit и число non-inferior walk-forward folds.
7. Проведите новый paper/shadow период. Расширение feature schema не является доказательством прибыльности.

## Upgrade to 1.15.0

1. Остановите процессы и сохраните backup PostgreSQL.
2. Обновите исходники; новые `.env` параметры и retraining ML artifact не требуются.
3. Выполните `python manage.py migrate`; ожидаемый head — `0011_selection_experiment`.
4. Запустите `python manage.py doctor` и обычные API/worker/trainer процессы.
5. Убедитесь, что новые execution plans создают строки в `advisory.selection_experiment_ledger`. Legacy opportunities до 1.15.0 намеренно не backfill-ятся.
6. После накопления минимум нескольких десятков ACCEPT и непринятых eligible plans выполните `python manage.py selection-report -- --days 90`.
7. Основной показатель — all-eligible counterfactual mean R. Selected-only mean показывает результат выбранного подмножества; IPSW является диагностикой смещения, а не доказательством того, что ручной выбор добавляет доходность.
8. При `LEDGER_INTEGRITY_ERROR`, class collapse, poor overlap или low ESS не используйте corrected estimate и не редактируйте ledger вручную.

## Интерпретация decision classes

- `ACCEPT`: оператор принял конкретную plan version.
- `REJECT`: оператор явно отклонил её.
- `NO_DECISION`: outcome уже доступен, но terminal operator decision отсутствует.
- Ineligible plans сохраняются для полноты ledger, но не входят в propensity/IPSW cohort.

Unit наблюдения — созданная plan version. Система пока не доказывает, что оператор действительно видел каждую карточку; автоматические пересчёты могут создавать коррелированные версии одной рекомендации.

## Upgrade to 1.14.0

1. Остановите API, worker и trainer; сохраните backup PostgreSQL и текущий model registry/artifact.
2. Обновите исходники и перенесите четыре orderbook-параметра из `.env.example` в локальный `.env` либо подтвердите defaults.
3. Выполните `python manage.py migrate`; ожидаемый head — `0010_orderbook_exec_evidence`.
4. Выполните `python manage.py doctor` и затем запустите worker.
5. В heartbeat/job details проверьте `orderbooks.requested/stored/duplicates/failed`. Повторные snapshots могут быть idempotent duplicates; систематические failures требуют расследования.
6. Дождитесь свежих snapshots для symbols. План без свежего depth evidence будет `BLOCKED_STALE_DATA`.
7. Existing `ACTIONABLE` plans 1.13.0 не принимайте как legacy contract: endpoint создаст новую версию с depth/VWAP evidence.
8. Перед ручным входом проверьте complete-fill VWAP, impact, worst level и operator latency в details. `PARTIAL/NO_FILL` означает запрет, а не предложение вручную округлить qty вверх.
9. Изменение `MAX_VWAP_IMPACT_BPS` или depth требует пересчёта plan; retraining модели не требуется.

## Как интерпретировать execution evidence

- `FULL`: весь плановый объём помещается в доступную snapshot depth внутри impact band. Это не гарантия фактического fill после задержки.
- `PARTIAL`: только часть объёма доступна; система блокирует plan/acceptance.
- `NO_FILL`: допустимая ликвидность отсутствует или snapshot некорректен; действие блокируется.
- `operator_latency_seconds`: время от plan calculation до acceptance revalidation. Большая задержка требует нового snapshot и обычно приводит к plan version change.

## Upgrade to 1.13.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники; Alembic migration и новые `.env` переменные не требуются.
3. Запустите worker и дождитесь progressive `history_backfill`, включая отдельный `mark_price_history` для всех training symbols.
4. Не обходите gaps: training требует точные consecutive hourly mark candles до каждого modeled exit.
5. Проверьте `DEFAULT_LEVERAGE`; это значение становится частью research artifact contract. Его изменение требует нового candidate.
6. Переобучите candidate. Artifact 1.12.0 не содержит обязательный intrahorizon-margin contract и должен быть отклонён runtime fail-closed.
7. Проверьте metadata: margin schema/status, mark source, research leverage, reserve, liquidation count/rate, MAE/MFE и minimum equity.
8. При `intrahorizon_*` gate reason не редактируйте joblib и не снижайте severity. Исправьте coverage/assumptions и переобучите.
9. После gates выполните новый paper/shadow период. Метрики 1.12.0 без mark-MTM напрямую несопоставимы с 1.13.0.

## Интерпретация liquidation evidence

`mark_liquidated=true` означает срабатывание консервативного hourly isolated-margin proxy. Это не подтверждение точного historical liquidation event на Bybit. Proxy намеренно ставит ambiguous same-bar mark liquidation раньше более позднего last-price TP/SL и не знает sub-hour order, historical risk tier/MMR, liquidation fee или cross/portfolio margin. Используйте его как fail-closed стресс для realized evidence, а не как точную цену ликвидации.

## Upgrade to 1.12.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники; Alembic migration и новые `.env` переменные не требуются.
3. Запустите worker и дождитесь progressive `history_backfill`, включая вложенный `funding_history` progress.
4. Проверьте покрытие всех training symbols до требуемого `HISTORY_BACKFILL_TARGET_DAYS`; ошибки или незавершённые symbols не обходите.
5. Переобучите candidate. Artifact 1.11.0 не содержит обязательный historical-funding contract и должен быть отклонён runtime fail-closed.
6. Проверьте artifact metadata: funding schema, symbols, settlements, start/end time и policy funding sources.
7. После gates выполните новый paper/shadow период. Старые backtest/policy metrics без settlement replay напрямую несопоставимы с 1.12.0.

## Upgrade to 1.11.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники. Alembic migration и новые `.env` переменные не требуются.
3. Запустите `python manage.py doctor` в настроенном локальном окружении.
4. Переобучите candidate: artifact 1.10.0 не содержит обязательную walk-forward schema и должен быть отклонён runtime fail-closed.
5. Проверьте diagnostics каждого fold: временные границы, rows, skill vs prior, Brier и policy mean R.
6. Не ослабляйте gate при `walk_forward_*` reason code. Сначала увеличьте историческое покрытие или исследуйте временную нестабильность.
7. После прохождения gates выполните paper/shadow validation; historical walk-forward не заменяет forward evidence.

## Требование к истории

При default horizon и quality settings trainer по-прежнему требует минимум 1206 уникальных hourly timestamps. Это теоретический минимум для непрерывной истории. Гэпы, invalid bars, class collapse или недостаточные TIMEOUT observations могут потребовать больше данных и должны блокировать обучение.

## Entry spread interpretation

`MODEL_ENTRY_SPREAD_BPS=18` означает полный 18 bps spread stress, то есть 9 bps adverse offset от next-hour open для каждой стороны. Это не historical orderbook reconstruction. Значение должно быть зафиксировано до OOS evaluation.

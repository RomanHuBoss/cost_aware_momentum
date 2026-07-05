# Operator Manual

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

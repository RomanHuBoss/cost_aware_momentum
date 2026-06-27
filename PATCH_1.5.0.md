# Patch 1.5.0 — dataset-aware retraining and progressive history backfill

## Исправленная проблема

Версия 1.4.0 запускала автоматическое переобучение главным образом по числу новых часовых timestamps после `training_end`. Массовая загрузка старых свечей для десятков новых символов почти не меняла максимальный timestamp, поэтому trainer мог ошибочно ждать еще 168 часов и продолжать использовать модель, обученную на старом узком датасете.

Кроме того, `AUTO_TRAIN_LOOKBACK_DAYS=365` ограничивал выборку, но сам worker загружал для нового символа только один REST-срез. Фактической годовой истории в PostgreSQL могло не быть.

## Изменения

- каждый artifact и registry metrics содержат полный `training_data_profile`;
- профиль включает candle rows, unique timestamps, полный список символов, границы времени, coverage и SHA256-подписи;
- trainer сравнивает текущий профиль PostgreSQL с профилем active-модели;
- крупный исторический backfill, добавление символов и существенное изменение top-N universe запускают досрочное переобучение;
- для dataset-change используется отдельный короткий cooldown, а недельное расписание сохраняется для обычного обновления;
- legacy active-модель без dataset profile автоматически рассматривается как требующая обновления;
- bootstrap блокируется, пока недостаточная доля символов имеет минимальную глубину истории;
- worker выполняет progressive `history_backfill` небольшими пакетами до целевой глубины 365 дней;
- для молодых инструментов нижняя граница истории ограничивается launch time;
- API status показывает настройки backfill, dataset-change gates и профиль active-модели;
- active recommendations фильтруются по текущему worker universe; старые карточки исключенных символов не остаются на главном экране;
- UI обновляет status/universe/trainer автоматически каждые 30 секунд;
- auto-activation дополнительно проверяет cost-aware holdout policy: число сделок, mean R, profit factor и drawdown;
- candidate может быть продвинут только при отсутствии существенной деградации относительно incumbent;
- начальный backfill увеличен до 1000 часовых свечей, глубокая история загружается отдельно без длительной блокировки старта.

## Новые параметры `.env`

```env
HISTORY_BACKFILL_ENABLED=true
HISTORY_BACKFILL_TARGET_DAYS=365
HISTORY_BACKFILL_INTERVAL_SECONDS=60
HISTORY_BACKFILL_SYMBOLS_PER_CYCLE=5
HISTORY_BACKFILL_PAGES_PER_SYMBOL=2
HISTORY_BACKFILL_PAGE_SIZE=1000

AUTO_TRAIN_DATA_CHANGE_COOLDOWN_HOURS=6
AUTO_TRAIN_MIN_NEW_ROWS=10000
AUTO_TRAIN_MIN_DATASET_GROWTH_RATIO=0.10
AUTO_TRAIN_MIN_NEW_SYMBOLS=5
AUTO_TRAIN_MIN_UNIVERSE_CHANGE_RATIO=0.10
AUTO_TRAIN_MIN_BARS_PER_SYMBOL=300
AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO=0.80

AUTO_TRAIN_MIN_POLICY_TRADES=20
AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R=0.0
AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR=1.0
AUTO_TRAIN_MAX_POLICY_DRAWDOWN_R=30.0
AUTO_TRAIN_MAX_POLICY_MEAN_R_REGRESSION=0.02
AUTO_TRAIN_MAX_POLICY_DRAWDOWN_REGRESSION_R=2.0
AUTO_TRAIN_MIN_POLICY_IMPROVEMENT_R=0.01
```

Новой Alembic migration не требуется: dataset profile хранится внутри JSONB `model_registry.metrics`, а progress history backfill — в `job_runs` и worker heartbeat.

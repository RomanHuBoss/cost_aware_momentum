# Model card

## Назначение

Прогноз вероятностей `TP first`, `SL first`, `timeout` для условного LONG/SHORT сценария на горизонте нескольких часов. Решение `NO TRADE` принимает policy engine после учета издержек и риска.

## Текущая поставка

В репозитории присутствует детерминированный momentum baseline. Он нужен для проверки ingestion → features → recommendation → UI → audit и не должен использоваться как доказательство экономического преимущества.

## Обучаемый pipeline

- point-in-time universe и contract specs;
- только confirmed свечи и `available_at` timestamps;
- direction-specific triple-barrier labels;
- консервативное разрешение свечей, где TP и SL касаются внутри одного часа;
- temporal folds с purging/embargo;
- отдельная probability calibration;
- final holdout, не используемый при выборе признаков/порогов;
- cost-aware event backtest с no-fill, latency и portfolio constraints.

## Метрики допуска

Brier score, log loss, calibration error, net EV/trade, drawdown, cost/gross-profit ratio, turnover, stability по времени/symbol/liquidity/direction/horizon/regime. Результат должен переживать cost x1.5/x2, operator delays и удаление лучших сделок/монет.

## Известные ограничения

- историческая глубина стакана не предоставляется текущим snapshot API автоматически; impact-модель уточняется после накопления snapshots;
- часовой OHLC не определяет порядок внутрисвечных касаний;
- cross-sectional dependence уменьшает эффективный размер выборки;
- ручной выбор оператора создает selection bias, поэтому сохраняется counterfactual outcome всех сигналов;
- крипторынок нестационарен, calibration и costs могут деградировать.

## Активация

Новая версия активируется только после воспроизводимого артефакта, SHA256, сохраненного dataset snapshot, fold metrics, final holdout, paper/shadow evidence и rollback-плана. Одновременно активна одна production-модель на конкретную feature/calibration schema.

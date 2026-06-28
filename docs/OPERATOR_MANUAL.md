# Руководство оператора

## 1. Вход и проверка состояния

После входа убедитесь, что верхняя строка показывает `Готово`, PostgreSQL доступен, worker не stale, а последняя синхронизация рынка актуальна. Красная блокировка данных имеет приоритет над направлением сигнала.

## 2. Профиль капитала

Выберите профиль в шапке. Смена профиля не меняет LONG/SHORT, entry, SL/TP и качество market signal. Пересчитываются risk budget, qty, notional, margin и исполнимость. Ручной капитал помечается как неподтвержденный биржей.

## 3. Разделы экрана

- **Активные рекомендации**: рыночный сигнал и execution plan прошли проверки.
- **Наблюдение**: цена вне зоны входа или условие еще не выполнено.
- **Заблокированные**: сигнал существует, но min order, margin, liquidity, portfolio либо stale data запрещают действие.
- **Без сделки**: net edge не прошел policy thresholds.

Цвет обозначает направление, текстовый статус — исполнимость. Зеленая LONG-плитка может быть заблокирована.

Если в последних 24 часах отсутствует или дублируется hourly candle, новая плитка для символа не публикуется. Это fail-closed контроль качества данных; не заменяйте пропуск искусственным значением.

## 4. Проверка плитки

До открытия деталей оцените срок, текущую цену/entry-zone, SL/основной TP, чистый доход/риск, ожидаемый результат, риск USDT, notional и предупреждение. Термины имеют tooltip по hover/focus/tap.

## 5. Подробный диалог

Проверьте вкладки:

1. торговый план и условия отмены;
2. капитал, qty, margin, leverage и liquidation buffer;
3. breakdown издержек, net EV и контрфактический TP1/SL/TIMEOUT после разрешения;
4. причины сигнала без причинной интерпретации feature importance;
5. модель/калибровка/OOS-аналоги и drift;
6. audit: signal ID, plan version, timestamps, data/model/policy versions.

## 6. Принятие и отклонение

`Принять` фиксирует решение, но не отправляет ордер. Перед переходом система повторно проверяет expiry, entry-zone, freshness, profile version, margin и portfolio caps. При изменении входных данных создается новый plan version, старый становится `SUPERSEDED`.

`Отклонить` требует код причины. Это необходимо для оценки operator selection bias.

## 7. Ручная регистрация сделки

После фактического исполнения на Bybit внесите entry time, fill price, qty, leverage и fee. Частичные/полные выходы вводятся отдельно вместе с fee и funding cash flow. Система рассчитывает gross и realized net P&L, но не сверяет биржевой ордер автоматически без read-only reconciliation.

## 8. Контрфактический исход

После достижения первичного TP/SL либо завершения горизонта во вкладке «Экономика» появляется независимый от решения оператора исход. Базовый путь строится по confirmed часовым свечам. Если один час одновременно содержит TP и SL, worker запрашивает точное 1/3/5-минутное окно и определяет первое касание по непрерывному intrabar path. При неполном окне исход остается pending. Консервативный SL с `ambiguous=true` используется только если TP и SL остаются внутри одного самого мелкого доступного бара.

Для выбранной plan version показываются оценочный net P&L и R по сохраненным cost/sizing assumptions. Статус `Funding timeline недоступен` означает legacy-plan: система не смогла доказать пересеченные settlements и поэтому не публикует R. Это контроль selection bias и качества прогнозов, а не отчет о фактической ручной сделке. Фактический P&L берется только из manual fills, fee и funding cash flow.

Статус `Некорректный snapshot плана` (`INVALID_INPUT`) означает, что immutable qty/risk/cost/funding данные этой версии повреждены или нечисловые. Система сохраняет нулевую оценку без R и продолжает обработку других планов. Не интерпретируйте ноль как безубыточный результат: исправьте источник/legacy-import и сохраните audit trail.

## 9. Запрещенные действия

- не увеличивать qty выше плана ради достижения min order;
- не входить по просроченному плану;
- не трактовать маржу как максимальный убыток;
- не повышать плечо для «улучшения R/R»;
- не скрывать/игнорировать stale data, liquidation или portfolio block;
- не считать baseline-модель подтвержденной стратегией.

## Фоновое дообучение модели

В системной строке рядом с active-version отображается состояние trainer: ожидание новых данных, загрузка, обучение, регистрация, активация либо ошибка. Во время обучения рекомендации продолжают рассчитываться текущей active-моделью.

Новая версия не становится active только по факту завершения fitting. Сначала она проходит quality gate и сравнение с действующей моделью на одном final holdout. При провале проверки текущая модель остается без изменений. Начиная с 1.7.8 успешная регистрация нового candidate и auto-activation атомарны: при ошибке переключения или audit/outbox в registry не остается промежуточного candidate с незавершенной активацией. Все candidates и решения доступны через:

```bash
python manage.py model-registry list
```

Начиная с 1.7.7 верхняя строка отдельно показывает зарегистрированный inactive candidate, причины quality gate и незарегистрированный файл в `models/`. Если usable active artifact отсутствует, а валидный orphan создан штатным trainer до завершения registry transaction, выполните:

```bash
python manage.py model-registry recover-artifact --artifact models/<artifact>.joblib
```

Команда не является обходом gate: она работает только вне production, повторно проверяет artifact и активирует его только после абсолютного ML/policy gate. Если файл уже зарегистрирован с failed gate, он останется inactive.

Для режима обязательного ручного утверждения установите `AUTO_TRAIN_AUTO_ACTIVATE=false`.
## Работа после удаления model artifacts

В версии 1.7.3 paper/shadow/development запуск не требует ручной активации baseline, если `ALLOW_BASELINE_MODEL=true`. При stale active registry row и отсутствующем `.joblib`:

- верхняя строка показывает «Система доступна с ограничениями»;
- effective model равна `baseline-momentum-v1`;
- worker heartbeat имеет `DEGRADED`;
- рекомендации продолжают формироваться, но содержат предупреждение о некалиброванном baseline;
- trainer после `AUTO_TRAIN_INITIAL_DELAY_SECONDS` проверяет достаточность истории и запускает `bootstrap_recovery`, не ожидая weekly/data-change trigger.

Нормальное восстановление завершено, когда `/api/v1/status.active_model.worker_runtime.baseline=false`, worker heartbeat снова `RUNNING`, а registry version совпадает с effective runtime. Не включайте ручную активацию кандидата, который не прошел quality gate.

Если предыдущий `model_retraining` относился к обычному scheduled/data-change cycle, он не задерживает новый recovery episode. Повторная техническая ошибка именно `bootstrap_training`/`bootstrap_recovery` ожидает только `AUTO_TRAIN_RECOVERY_RETRY_MINUTES` (default 15). Успешно обученный, но отклоненный quality gate кандидат остается inactive; следующий recovery cycle использует более длинный controlled cooldown, чтобы не повторять fitting на почти идентичных данных.

Начиная с 1.7.9 в `metrics` нового candidate присутствуют `classification_metric_schema=ordered-probability-v2`, `raw_log_loss`, `class_prior_log_loss`, `uniform_log_loss`, `calibration_log_loss_improvement` и `log_loss_skill_vs_prior`. Кандидаты, рассчитанные до 1.7.9, могут содержать завышенный `log_loss` из-за перестановки столбцов `TP / SL / TIMEOUT`; такие исторические строки не следует вручную активировать только по старому gate result. Перезапустите trainer и получите новый candidate либо выполните контролируемое повторное исследовательское обучение.

Начиная с 1.7.11 новые model artifacts сохраняют `hourly_continuity`: сколько timestamps исключено из-за разрыва feature-lookback и label-horizon. Рост этих счетчиков требует проверки market/history sync, а не ослабления gate.

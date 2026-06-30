# Руководство оператора

## Проверка внешнего состояния в 1.8.19

- После перезапуска дождитесь успешных `instrument_sync`, market-data и account jobs. Неполный funding snapshot теперь отображается как блокировка данных, а не как нулевая стоимость.
- Ошибка обязательного `tickSize`, `qtyStep`, min/max order, min notional, max leverage или funding interval означает, что спецификация биржи не подтверждена. Не вводите эти значения вручную в БД.
- Read-only account считается подтвержденным только после валидного equity/available-balance ответа и полной пагинации открытых позиций.
- `policy_profit_factor = null` при отсутствии убыточных exit-events является недостатком статистического свидетельства, а не бесконечной прибыльностью; такой кандидат не проходит автоматический gate по profit factor.

## Профили и биржевые аккаунты в 1.8.18

- Manual и paper профили имеют независимые журналы риска. Сделка одного такого профиля не должна блокировать другой профиль.
- Несколько read-only профилей с одинаковым `source_account_id` считаются представлениями одного биржевого аккаунта и совместно расходуют его portfolio-risk budget.
- Reconciliation сравнивает позиции только со снимками и журналом того же аккаунта.
- Перед первым запуском 1.8.18 выполните `python manage.py migrate`; до появления свежего account snapshot система остается fail-closed.
- Значение `legacy-unknown` после миграции означает, что историческую позицию нельзя безопасно связать с конкретным аккаунтом; не исправляйте такие строки вручную без проверяемого источника и audit trail.

## Раздельная экономика сигнала и плана в 1.8.17

На плитке `Net R/R сигнала` и `Net EV сигнала` относятся к опубликованному market signal и не зависят от капитала. В деталях отдельная карточка `Execution plan · сохраненный расчет` показывает экономику для фактической planning entry, funding и издержек конкретной версии плана. Именно plan-карточка согласована с qty, margin и executability status.

`Порог P(TP) при текущем P(timeout)` рассчитан для трёх исходов; это не бинарное `1/(1+R/R)`. Если plan snapshot повреждён, неполон или не согласуется с повторным расчётом, интерфейс показывает ошибку целостности и не выводит числа как достоверные. Не принимайте такой план; пересчитайте его и проверьте журнал. Read-only профиль без привязанного `source_account_id` также блокируется и не наследует ручной капитал.

## Acceptance revalidation in 1.8.16

Нажатие `Принять` не гарантирует сохранение старого размера. Непосредственно перед фиксацией решения система повторно проверяет текущие капитал и доступную маржу, индивидуальный и общий risk limits, projected funding, net `R/R`/`EV/R`, а также актуальные `tickSize`, `qtyStep`, min order, max qty и max leverage. При изменении любого критичного входа возвращается HTTP 409 и формируется новая версия плана; используйте только новую версию.

Новые entry/SL/TP отображаются в допустимых шагах цены. Округление намеренно консервативно и может немного уменьшить ожидаемую прибыль либо увеличить расчетный downside. Это защита от ручного переноса технически недопустимого уровня, а не обещание исполнения или прибыльности.

## Quote and target semantics in 1.8.15

Статус зоны входа рассчитывается по ask для LONG и bid для SHORT. Если bid/ask отсутствует, non-finite или инвертирован, плитка показывает отсутствие исполнимой цены, а публикация/принятие блокируются.

Текущий план содержит один тейк-профит TP1 на 100% позиции. Не интерпретируйте nullable TP2-поля старых записей как действующую рекомендацию: полноценный partial-exit path пока не входит в labels, EV/R, sizing и outcome accounting.


## Execution-plan lifecycle hardening in 1.8.14

A plan in `ACCEPTED`, `ENTERED`, `PARTIAL` or `CLOSED` is immutable to recalculation. The API returns HTTP 409 instead of creating a parallel plan, and bulk profile recalculation skips those states. Complete the current trade/decision lifecycle before requesting a new recommendation. This prevents duplicate reservation and ambiguous plan ownership.

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

`Принять` фиксирует решение, но не отправляет ордер. Перед переходом система повторно проверяет expiry, entry-zone, freshness, profile version, margin и portfolio caps. Для LONG зона входа проверяется по текущему ask, для SHORT — по bid; `last_price` не считается гарантированной исполнимой ценой. Read-only account snapshot должен быть свежее `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS`. Проверка общего open risk сериализуется в PostgreSQL, поэтому два параллельных принятия не могут независимо использовать один и тот же свободный риск. При изменении входных данных создается новый plan version, старый становится `SUPERSEDED`. Начиная с 1.8.10 adverse executable price не наследует старый размер: новая версия пересчитывает qty, stress loss, margin, liquidation, net R/R и EV. Future-dated ticker или instrument spec блокирует действие.

`Отклонить` требует код причины. Это необходимо для оценки operator selection bias.

## 7. Ручная регистрация сделки

После фактического исполнения на Bybit внесите entry time, fill price, qty, leverage и fee. Частичные/полные выходы вводятся отдельно вместе с fee и funding cash flow. Система рассчитывает gross и realized net P&L, но не сверяет биржевой ордер автоматически без read-only reconciliation.

Время entry и выхода должно быть timezone-aware и не может находиться в будущем относительно сервера. Время выхода также не может быть раньше entry или уже сохраненного partial fill. При нескольких fills с одинаковым timestamp используйте одинаковое время; система это допускает. Ошибка хронологии возвращает HTTP 422 и не изменяет remaining qty или P&L.

С версии 1.8.10 при entry сохраняется фактический initial stress loss по fill price и qty. Partial close уменьшает remaining stress loss пропорционально оставшемуся qty; именно это значение входит в общий portfolio open-risk. Поэтому после обновления обязательно выполните migration `0006` до запуска API/worker/trainer.

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
- не принимать LONG по `last_price`, если текущий ask уже вышел из entry-zone, и аналогично SHORT при bid вне зоны;
- не считать baseline-модель подтвержденной стратегией.

## Фоновое дообучение модели

Начиная с версии 1.8.0 в верхней панели доступна отдельная кнопка **«Обучатель»**. Она открывает окно состояния фонового trainer. Во время обучения рекомендации продолжают рассчитываться текущей active-моделью.

Окно показывает:

- работает ли отдельный trainer-процесс и насколько свежий его heartbeat;
- текущую фазу: стартовая задержка, проверка данных, загрузка, fitting, регистрация, активация, ожидание или ошибка;
- время следующей штатной проверки;
- точную причину ожидания;
- прогресс минимальной истории, symbol coverage или новых размеченных timestamps;
- registry version, effective runtime и состояние `.joblib`;
- последнюю попытку `model_retraining`, кандидата, quality gate и факт активации;
- последнюю команду оператора и ее статус.

Доступны две безопасные команды:

1. **«Проверить данные сейчас»** — ставит в PostgreSQL команду `CHECK_NOW`. Trainer немедленно повторяет обычную scheduler-проверку и либо начинает штатный цикл, либо возвращает актуальную причину ожидания.
2. **«Запустить восстановительное обучение»** — ставит `RECOVER_NOW`. Кнопка доступна только при отсутствующей active-модели, registry baseline либо физически отсутствующем recoverable artifact. Команда может пропустить cooldown текущего recovery episode, но не minimum history, coverage, temporal validation, quality gate, activation guard или advisory lock.

Обе команды требуют входа оператора и CSRF-защиты. API только записывает команду; fitting выполняется отдельным trainer-процессом. При остановленном/stale trainer запрос отклоняется, а не создает ложное ожидание фоновой работы.

Начиная с 1.8.1 авария trainer после захвата команды не оставляет очередь заблокированной навсегда. Если claim остается `RUNNING` не менее пяти минут и heartbeat его владельца stale/missing, система фиксирует старую попытку как `FAILED` с причиной `stale_trainer_control_owner`, создает новый `PENDING`-retry и показывает связь через `retry_of`/`recovery_count`. Не переводите такую строку вручную в `PENDING`: это разрушает audit trail и не защищает от позднего завершения старого процесса.

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

С версии 1.8.10 active artifact обязан иметь exact current feature schema, positive integer horizon, non-empty calibration version и полный finite runtime feature vector. Ошибка `feature_schema_version`, `missing_features` или `non_finite_feature` требует штатного retraining/recovery; не подставляйте нули и не отключайте validator.

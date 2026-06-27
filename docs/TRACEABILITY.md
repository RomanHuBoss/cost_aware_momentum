# Трассировка требований

| Требование спецификации | Реализация |
|---|---|
| FastAPI/Uvicorn, PostgreSQL only | `app/main.py`, `app/db/*`, `.env.example`; validator запрещает SQLite |
| Ручное исполнение, без отправки ордеров | `app/bybit/client.py` содержит только GET; accept и fills разделены |
| Часовое решение после закрытой свечи | `sync_candles.confirmed`, `_candles_frame(...confirmed=True)`, worker delay |
| LONG/SHORT/NO TRADE как model + policy | `ModelRuntime`, `publish_hourly_signals`, `create_execution_plan` |
| Издержки, net R/R и net EV | `app/risk/math.py`, economics в detail serializer |
| Funding только по сценарию/settlement | отдельный funding series и sign-correct cash-flow helper |
| Разные капиталы | `capital_profiles`, `effective_capital`, versioned execution plans |
| Min-order/margin/liquidity/portfolio checks | `calculate_position_plan`, `create_execution_plan` |
| Компактные плитки и подробный диалог | `web/index.html`, `web/js/app.js`, `web/css/app.css` |
| Доступные подсказки | `ui_glossary`, keyboard/touch/hover tooltip, Help dialog |
| Accept/reject только из деталей | UI actions находятся в modal; API повторно валидирует план |
| Audit и counterfactual journal | market signals/plans сохраняются независимо от решения; `audit.events` |
| Idempotency и advisory locks | `ops.idempotency_keys`, `app/db/locks.py`, worker job lock |
| Backtest без random split | `chronological_split` с purge gaps; отдельные train/cal/test windows |
| Baselines и calibration | deterministic runtime baseline; logistic + later-window sigmoid calibration |
| Нативный backup/restore | `scripts/backup.py`, `scripts/restore_check.py`, `docs/INCIDENT_RUNBOOK.md` |
| Кроссплатформенный запуск | `manage.py`, `scripts/run_local.py`, `docs/NATIVE_INSTALL.md` |
| Нативная инициализация PostgreSQL | `scripts/db_init.py`, `scripts/doctor.py` |
| Tests и CI с PostgreSQL | `tests/unit`, `tests/integration_postgres`, `.github/workflows/ci.yml` |

## Осознанные границы поставки

Поставка является законченным advisory/paper/shadow продуктом и исследовательским каркасом. Она не утверждает прибыльность, не включает auto-order execution и не имитирует точный исторический market impact без накопленной истории orderbook snapshots. Production-активация обученной модели требует OOS/final holdout и forward evidence согласно model card.

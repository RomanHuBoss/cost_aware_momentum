# Operator Manual

## Запуск

Используйте `manage.py setup`, `configure`, `db-init`, `migrate`, `doctor`, затем `run`. Web UI по умолчанию доступен только на `127.0.0.1:8000`.

## Интерпретация

- Market signal не зависит от капитала профиля.
- Execution plan зависит от капитала, account snapshot, текущего ask/bid, маржи, ликвидности и exchange constraints.
- `BLOCKED`/`NO TRADE` нельзя трактовать как LONG или SHORT.
- `NO_TRADE` с предупреждением о цене вне зоны означает, что рыночный сигнал существует, но вход по текущей исполнимой цене запрещен.
- `BLOCKED_DATA` при отсутствии bid/ask нельзя обходить использованием last/mark или старой reference price.
- Перед ACCEPTED система повторно валидирует freshness, entry-zone, risk, margin, funding, instrument specs и plan version.

## После обновления на 1.8.26

Migration и новые env-переменные не нужны. Перезапустите API/worker/trainer штатной командой. Проверьте `.env`: `MIN_NET_EV_R` должен быть неотрицательным; при включенной auto-activation minimum realized mean R должен быть неотрицательным, а minimum profit factor — не ниже 1. Небезопасная конфигурация теперь не запускается.

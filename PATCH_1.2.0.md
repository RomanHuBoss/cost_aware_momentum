# Patch 1.2.0 — Dynamic full futures universe

Патч заменяет фиксированный список BTC/ETH/SOL на динамическое формирование universe из полного каталога активных Bybit linear USDT perpetuals.

## После установки

Добавьте или измените в `.env`:

```env
UNIVERSE_MODE=dynamic
UNIVERSE_MIN_AGE_DAYS=7
UNIVERSE_MIN_TURNOVER_24H=2000000
UNIVERSE_MAX_SPREAD_BPS=30
UNIVERSE_MAX_SYMBOLS=0
UNIVERSE_REFRESH_SECONDS=300
UNIVERSE_MIN_HISTORY_BARS=72
```

`UNIVERSE_MAX_SYMBOLS=0` означает отсутствие top-N ограничения. Фильтры качества и ликвидности продолжают применяться.

Миграция базы данных не требуется. После копирования файлов достаточно перезапустить приложение:

```powershell
py -3.12 manage.py doctor
py -3.12 manage.py run
```

Первый запуск может занять несколько минут: worker выполнит backfill часовых свечей для всех отобранных контрактов.

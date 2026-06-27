# Patch 1.1.3 — Windows API/worker event loop

Version 1.1.2 set `WindowsSelectorEventLoopPolicy`, but recent Uvicorn releases can explicitly create `ProactorEventLoop` on Windows and bypass the global policy. As a result, FastAPI startup still failed when async psycopg opened the first PostgreSQL connection.

Version 1.1.3 fixes the actual process entry points:

- FastAPI is started through `uvicorn.Server(...).serve()` inside an explicit asyncio runner;
- the runner receives a loop factory that directly creates `SelectorEventLoop` on Windows;
- the worker, training, backtest, report and replay entry points use the same runner;
- the policy setup remains as an additional compatibility layer for third-party code;
- no Docker or Docker Compose files are introduced.

After applying the patch:

```powershell
py -3.12 manage.py migrate
py -3.12 manage.py doctor
py -3.12 manage.py run
```

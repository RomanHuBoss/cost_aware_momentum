from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.responses import FileResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1 import admin, capital, charts, events, portfolio, recommendations, session, status, trades, ui
from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.health import current_revision, database_health
from app.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def expected_revision() -> str:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    return ScriptDirectory.from_config(cfg).get_current_head() or "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionFactory() as db:
        await database_health(db)
        current = await current_revision(db)
        expected = expected_revision()
        if current != expected:
            raise RuntimeError(f"Database migration mismatch: current={current}, expected={expected}")
    if settings.secret_key.startswith("replace-with"):
        logger.warning("Default SECRET_KEY is in use", extra={"event": "insecure_default_secret"})
    if settings.operator_password == "change-me-now":
        logger.warning("Default operator password is in use", extra={"event": "insecure_default_password"})
    yield
    await dispose_engine()


app = FastAPI(
    title="Cost-aware hourly ML momentum",
    version=__version__,
    description="Human-in-the-loop Bybit advisory terminal. This API never places exchange orders.",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

for router in (
    status.router,
    session.router,
    capital.router,
    ui.router,
    recommendations.router,
    trades.router,
    portfolio.router,
    charts.router,
    events.router,
    admin.router,
):
    app.include_router(router)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/{path:path}", include_in_schema=False)
async def spa_fallback(path: str) -> FileResponse:
    if path.startswith("api/") or path.startswith("health/"):
        return FileResponse(WEB_DIR / "404.html", status_code=404)
    return FileResponse(WEB_DIR / "index.html")


def run() -> None:
    # Do not call uvicorn.run() here. Recent Uvicorn releases explicitly choose
    # ProactorEventLoop on Windows, which async psycopg cannot use. Running the
    # server coroutine ourselves guarantees SelectorEventLoop on Windows.
    config = uvicorn.Config(
        app,
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    run_with_compatible_event_loop(server.serve())


if __name__ == "__main__":
    run()

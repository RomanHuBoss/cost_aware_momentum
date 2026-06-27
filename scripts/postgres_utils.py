from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.engine import URL, make_url


def parse_url(value: str) -> URL:
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("Ожидался PostgreSQL URL")
    return url


def connection_kwargs(value: str, *, database: str | None = None) -> dict[str, object]:
    url = parse_url(value)
    kwargs: dict[str, object] = {
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "dbname": database or url.database or "postgres",
    }
    if url.username:
        kwargs["user"] = url.username
    if url.password:
        kwargs["password"] = url.password
    return kwargs


def pg_environment(value: str, *, database: str | None = None) -> dict[str, str]:
    url = parse_url(value)
    env = os.environ.copy()
    env["PGHOST"] = url.host or "localhost"
    env["PGPORT"] = str(url.port or 5432)
    env["PGDATABASE"] = database or url.database or "postgres"
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def replace_database(value: str, database: str) -> str:
    url = parse_url(value)
    return url.set(database=database).render_as_string(hide_password=False)


def build_url(
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str | None,
    driver: str = "postgresql+psycopg",
) -> str:
    user = quote(username, safe="")
    password_part = f":{quote(password, safe='')}" if password else ""
    return f"{driver}://{user}{password_part}@{host}:{port}/{quote(database, safe='')}"


def require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"Не найден {name}. Добавьте каталог bin установленного PostgreSQL в PATH."
        )
    return found


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]

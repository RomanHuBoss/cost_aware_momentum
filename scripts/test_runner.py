from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.config import get_settings
from scripts.postgres_utils import connection_kwargs, replace_database


def create_test_database(admin_url: str, database: str, owner: str | None) -> None:
    with psycopg.connect(**connection_kwargs(admin_url), autocommit=True) as conn:
        owner_clause = sql.SQL(" OWNER {} ").format(sql.Identifier(owner)) if owner else sql.SQL(" ")
        conn.execute(sql.SQL("CREATE DATABASE {}{}").format(sql.Identifier(database), owner_clause))


def drop_test_database(admin_url: str, database: str) -> None:
    with psycopg.connect(**connection_kwargs(admin_url), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск unit и PostgreSQL integration tests")
    parser.add_argument("--unit-only", action="store_true")
    parser.add_argument("--require-integration", action="store_true")
    parser.add_argument("--admin-url", default=os.getenv("POSTGRES_ADMIN_URL"))
    args, pytest_args = parser.parse_known_args()

    if args.unit_only:
        raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", "tests/unit", *pytest_args]))

    env = os.environ.copy()
    settings = get_settings()
    configured_test_url = env.get("TEST_DATABASE_URL") or settings.test_database_url
    if configured_test_url:
        env["DATABASE_URL"] = configured_test_url
        raise SystemExit(
            subprocess.call([sys.executable, "-m", "pytest", "-q", *pytest_args], env=env)
        )

    admin_url = args.admin_url or settings.postgres_admin_url
    if not admin_url:
        if args.require_integration:
            raise SystemExit(
                "Для integration tests задайте POSTGRES_ADMIN_URL или TEST_DATABASE_URL."
            )
        print("POSTGRES_ADMIN_URL не задан: запускаются только unit tests.")
        raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", "tests/unit", *pytest_args]))

    app_url = make_url(settings.database_url)
    test_database = f"cost_momentum_test_{uuid.uuid4().hex[:10]}"
    test_url = replace_database(settings.database_url, test_database)
    created = False
    try:
        create_test_database(admin_url, test_database, app_url.username)
        created = True
        env["DATABASE_URL"] = test_url
        env["TEST_DATABASE_URL"] = test_url
        code = subprocess.call([sys.executable, "-m", "pytest", "-q", *pytest_args], env=env)
    finally:
        if created:
            drop_test_database(admin_url, test_database)
    raise SystemExit(code)


if __name__ == "__main__":
    main()

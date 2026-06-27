from __future__ import annotations

import argparse
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.config import get_settings
from scripts.postgres_utils import (
    connection_kwargs,
    pg_environment,
    project_root,
    replace_database,
    require_tool,
)


def latest_backup() -> Path | None:
    files = sorted((project_root() / "backups").glob("*.dump"), key=lambda path: path.stat().st_mtime)
    return files[-1] if files else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка восстановления резервной копии")
    parser.add_argument("backup", nargs="?", type=Path)
    parser.add_argument("--admin-url", default=os.getenv("POSTGRES_ADMIN_URL"))
    args = parser.parse_args()

    backup = args.backup or latest_backup()
    if backup is None or not backup.exists():
        raise SystemExit("Резервная копия не найдена. Сначала выполните: python manage.py backup")

    settings = get_settings()
    admin_url = (
        args.admin_url
        or settings.postgres_admin_url
        or replace_database(settings.database_url, "postgres")
    )
    app_url = make_url(settings.database_url)
    app_owner = app_url.username
    test_database = f"cost_momentum_restore_{uuid.uuid4().hex[:10]}"

    try:
        with psycopg.connect(**connection_kwargs(admin_url), autocommit=True) as conn:
            owner_clause = (
                sql.SQL(" OWNER {} ").format(sql.Identifier(app_owner)) if app_owner else sql.SQL(" ")
            )
            conn.execute(
                sql.SQL("CREATE DATABASE {}{}").format(sql.Identifier(test_database), owner_clause)
            )

        restore_env = pg_environment(admin_url, database=test_database)
        subprocess.run(
            [
                require_tool("pg_restore"),
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                str(backup),
            ],
            env=restore_env,
            check=True,
        )

        with psycopg.connect(**connection_kwargs(admin_url, database=test_database)) as conn:
            signals = conn.execute("SELECT count(*) FROM advisory.market_signals").fetchone()[0]
            audit_events = conn.execute("SELECT count(*) FROM audit.events").fetchone()[0]
            models = conn.execute("SELECT count(*) FROM model.model_registry").fetchone()[0]
        print(
            "Восстановление проверено: "
            f"signals={signals}, audit_events={audit_events}, models={models}"
        )
    finally:
        try:
            with psycopg.connect(**connection_kwargs(admin_url), autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (test_database,),
                )
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database)))
        except psycopg.Error as exc:
            print(f"Предупреждение: не удалось удалить тестовую базу {test_database}: {exc}")


if __name__ == "__main__":
    main()

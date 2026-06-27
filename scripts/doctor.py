from __future__ import annotations

import shutil
import sys
from pathlib import Path

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import get_settings
from scripts.postgres_utils import connection_kwargs, project_root


def status(ok: bool, title: str, details: str = "") -> None:
    marker = "OK" if ok else "FAIL"
    suffix = f" — {details}" if details else ""
    print(f"[{marker}] {title}{suffix}")


def main() -> None:
    root = project_root()
    failures = 0

    python_ok = sys.version_info >= (3, 12)
    status(python_ok, "Python", sys.version.split()[0])
    failures += int(not python_ok)

    env_ok = (root / ".env").exists()
    status(env_ok, ".env", str(root / ".env"))
    failures += int(not env_ok)

    settings = get_settings()
    defaults_ok = not settings.secret_key.startswith("replace-with") and settings.operator_password != "change-me-now"
    status(defaults_ok, "Секреты приложения", "значения по умолчанию заменены" if defaults_ok else "замените SECRET_KEY и OPERATOR_PASSWORD")
    failures += int(not defaults_ok)

    for tool in ("psql", "pg_dump", "pg_restore"):
        found = shutil.which(tool)
        status(bool(found), tool, found or "не найден в PATH")
        failures += int(not bool(found))

    try:
        with psycopg.connect(**connection_kwargs(settings.database_url)) as conn:
            server_version, database = conn.execute(
                "SELECT version(), current_database()"
            ).fetchone()
            status(True, "PostgreSQL", f"{database}; {server_version.split(',')[0]}")
            revision_row = conn.execute(
                "SELECT to_regclass('public.alembic_version')"
            ).fetchone()
            current = None
            if revision_row and revision_row[0]:
                current = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            cfg = Config(str(root / "alembic.ini"))
            cfg.set_main_option("script_location", str(root / "migrations"))
            expected = ScriptDirectory.from_config(cfg).get_current_head()
            migration_ok = current == expected
            status(migration_ok, "Alembic revision", f"current={current}, expected={expected}")
            failures += int(not migration_ok)
    except Exception as exc:  # noqa: BLE001
        status(False, "PostgreSQL", str(exc))
        failures += 1

    for directory in ("models", "reports", "backups"):
        path = Path(root / directory)
        path.mkdir(exist_ok=True)
        writable = path.is_dir()
        status(writable, f"Каталог {directory}", str(path))
        failures += int(not writable)

    if failures:
        raise SystemExit(f"Диагностика завершена: ошибок {failures}.")
    print("Диагностика завершена успешно.")


if __name__ == "__main__":
    main()

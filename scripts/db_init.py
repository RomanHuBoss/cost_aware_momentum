from __future__ import annotations

import argparse
import getpass
import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.config import get_settings
from scripts.postgres_utils import build_url, connection_kwargs, parse_url


def admin_url_from_args(args: argparse.Namespace) -> str:
    if args.admin_url:
        return args.admin_url
    settings = get_settings()
    env_value = os.getenv("POSTGRES_ADMIN_URL") or settings.postgres_admin_url
    if env_value:
        return env_value
    app_url = parse_url(settings.database_url)
    password = args.admin_password
    if password is None:
        password = getpass.getpass(
            f"Пароль администратора PostgreSQL '{args.admin_user}' на {app_url.host or 'localhost'}: "
        )
    return build_url(
        host=app_url.host or "localhost",
        port=app_url.port or 5432,
        database=args.admin_database,
        username=args.admin_user,
        password=password or None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Создание локальной роли и базы PostgreSQL")
    parser.add_argument("--admin-url", help="Административный PostgreSQL URL")
    parser.add_argument("--admin-user", default="postgres")
    parser.add_argument("--admin-password")
    parser.add_argument("--admin-database", default="postgres")
    parser.add_argument(
        "--keep-role-password",
        action="store_true",
        help="Не менять пароль существующей прикладной роли",
    )
    args = parser.parse_args()

    app_url = make_url(get_settings().database_url)
    app_user = app_url.username
    app_password = app_url.password
    app_database = app_url.database
    if not app_user or not app_password or not app_database:
        raise SystemExit("DATABASE_URL должен содержать имя пользователя, пароль и имя базы.")

    admin_url = admin_url_from_args(args)
    try:
        with psycopg.connect(**connection_kwargs(admin_url), autocommit=True) as conn:
            role_exists = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,)
            ).fetchone()
            if role_exists is None:
                conn.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(app_user), sql.Literal(app_password)
                    )
                )
                print(f"Создана роль PostgreSQL: {app_user}")
            elif args.keep_role_password:
                print(f"Роль {app_user} уже существует; пароль не изменялся.")
            else:
                conn.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(app_user), sql.Literal(app_password)
                    )
                )
                print(f"Пароль роли {app_user} синхронизирован с DATABASE_URL.")

            database_exists = conn.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (app_database,),
            ).fetchone()
            if database_exists is None:
                conn.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(app_database), sql.Identifier(app_user)
                    )
                )
                print(f"Создана база PostgreSQL: {app_database}")
            else:
                current_owner = database_exists[0]
                if current_owner != app_user:
                    conn.execute(
                        sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                            sql.Identifier(app_database), sql.Identifier(app_user)
                        )
                    )
                    print(f"Владелец базы {app_database} изменен на {app_user}.")
                else:
                    print(f"База {app_database} уже существует.")
    except psycopg.Error as exc:
        raise SystemExit(
            "Не удалось выполнить административное подключение к PostgreSQL. "
            "Проверьте службу, пароль администратора и POSTGRES_ADMIN_URL. "
            f"Причина: {exc}"
        ) from exc

    print("Далее выполните: python manage.py migrate")


if __name__ == "__main__":
    main()

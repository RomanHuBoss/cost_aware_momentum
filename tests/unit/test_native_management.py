from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings
from scripts.configure_env import update_env
from scripts.postgres_utils import build_url, connection_kwargs, replace_database


def test_postgres_url_helpers() -> None:
    url = "postgresql+psycopg://app:p%40ss@localhost:5433/main"
    kwargs = connection_kwargs(url)
    assert kwargs == {
        "host": "localhost",
        "port": 5433,
        "dbname": "main",
        "user": "app",
        "password": "p@ss",
    }
    assert replace_database(url, "test_db").endswith("/test_db")
    assert build_url(
        host="localhost",
        port=5432,
        database="main",
        username="app",
        password="p@ss",
    ) == "postgresql+psycopg://app:p%40ss@localhost:5432/main"


def test_optional_postgres_urls_from_settings() -> None:
    settings = Settings(postgres_admin_url="", test_database_url="")
    assert settings.postgres_admin_url is None
    assert settings.test_database_url is None


def test_configure_env_quotes_special_characters(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_KEY=old\nOPERATOR_PASSWORD=old\n", encoding="utf-8")
    update_env(
        env_path,
        {
            "SECRET_KEY": 'secret\\value"x',
            "OPERATOR_PASSWORD": "Pass # with spaces",
        },
    )

    class Parsed(BaseSettings):
        model_config = SettingsConfigDict(env_file=env_path)
        secret_key: str
        operator_password: str

    parsed = Parsed()
    assert parsed.secret_key == 'secret\\value"x'
    assert parsed.operator_password == "Pass # with spaces"

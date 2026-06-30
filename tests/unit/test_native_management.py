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


def test_comma_separated_complex_settings_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT\nHORIZONS_HOURS=4,8,12\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert settings.horizons_hours == [4, 8, 12]


def test_json_array_complex_settings_are_also_supported(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'SYMBOLS=["BTCUSDT","ETHUSDT"]\nHORIZONS_HOURS=[4,12]\nDEFAULT_HORIZON_HOURS=4\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.symbols == ["BTCUSDT", "ETHUSDT"]
    assert settings.horizons_hours == [4, 12]


def test_ui_requests_full_recommendation_page_and_shows_universe_count() -> None:
    js = Path("web/js/app.js").read_text(encoding="utf-8")
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "limit: '2000'" in js
    assert "updateUniverseState" in js
    assert 'id="universe-state"' in html


def test_worker_contains_dynamic_universe_catchup_inference() -> None:
    runner = Path("app/workers/runner.py").read_text(encoding="utf-8")
    assert "catchup_inference_job" in runner
    assert "startup_backfill" in runner
    assert "universe_expanded" in runner


def test_worker_and_ui_expose_counterfactual_outcomes() -> None:
    runner = Path("app/workers/runner.py").read_text(encoding="utf-8")
    js = Path("web/js/app.js").read_text(encoding="utf-8")
    assert "counterfactual_outcome_job" in runner
    assert "COUNTERFACTUAL_OUTCOME_RESOLVED" in js
    assert "Контрфактический исход" in js

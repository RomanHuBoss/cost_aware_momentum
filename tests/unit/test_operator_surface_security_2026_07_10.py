from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.api.v1 import capital, events, portfolio, recommendations, session, status, trades
from app.config import Settings


def _route(router: APIRouter, path: str, method: str) -> APIRoute:
    matches = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    ]
    assert len(matches) == 1, f"Expected exactly one {method} {path} route"
    return matches[0]


def _dependency_names(route: APIRoute) -> set[str]:
    return {dependency.call.__name__ for dependency in route.dependant.dependencies}


def test_sensitive_financial_read_endpoints_require_operator_authentication() -> None:
    protected_routes = (
        (capital.router, "/api/v1/capital-profiles"),
        (recommendations.router, "/api/v1/recommendations"),
        (recommendations.router, "/api/v1/recommendations/{signal_id}"),
        (trades.router, "/api/v1/trades"),
        (portfolio.router, "/api/v1/portfolio/risk"),
    )
    for router, path in protected_routes:
        assert "current_operator" in _dependency_names(_route(router, path, "GET")), path


def test_operational_status_endpoints_require_operator_authentication() -> None:
    for path in ("/health/ready", "/api/v1/status"):
        assert "current_operator" in _dependency_names(_route(status.router, path, "GET")), path
    assert "current_operator" not in _dependency_names(_route(status.router, "/health/live", "GET"))


def test_outbox_event_stream_requires_operator_authentication() -> None:
    assert "current_operator" in _dependency_names(
        _route(events.router, "/api/v1/events", "GET")
    )


def test_production_requires_secure_authentication_cookies() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(
            app_mode="production",
            allow_demo_seed=False,
            allow_baseline_model=False,
            allow_baseline_actionable=False,
            secret_key="s" * 40,
            operator_password="p" * 16,
            cookie_secure=False,
            database_url="postgresql+psycopg://u:p@localhost/db",
        )


def test_logout_requires_authenticated_csrf_protection() -> None:
    assert "require_csrf" in _dependency_names(
        _route(session.router, "/api/v1/session/logout", "POST")
    )

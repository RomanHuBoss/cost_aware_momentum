from __future__ import annotations

from types import SimpleNamespace

import app.asyncio_compat as compat


def test_event_loop_compatibility_is_noop_outside_windows(monkeypatch) -> None:
    monkeypatch.setattr(compat.sys, "platform", "linux")
    assert compat.configure_windows_selector_event_loop() is False


def test_event_loop_compatibility_replaces_proactor_policy(monkeypatch) -> None:
    class SelectorPolicy:
        pass

    current = object()
    installed: list[object] = []
    fake_asyncio = SimpleNamespace(
        WindowsSelectorEventLoopPolicy=SelectorPolicy,
        get_event_loop_policy=lambda: current,
        set_event_loop_policy=installed.append,
    )
    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat, "asyncio", fake_asyncio)

    assert compat.configure_windows_selector_event_loop() is True
    assert len(installed) == 1
    assert isinstance(installed[0], SelectorPolicy)


def test_event_loop_compatibility_is_idempotent(monkeypatch) -> None:
    class SelectorPolicy:
        pass

    current = SelectorPolicy()
    installed: list[object] = []
    fake_asyncio = SimpleNamespace(
        WindowsSelectorEventLoopPolicy=SelectorPolicy,
        get_event_loop_policy=lambda: current,
        set_event_loop_policy=installed.append,
    )
    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat, "asyncio", fake_asyncio)

    assert compat.configure_windows_selector_event_loop() is False
    assert installed == []


def test_explicit_factory_constructs_selector_loop_on_windows(monkeypatch) -> None:
    sentinel = object()
    fake_asyncio = SimpleNamespace(SelectorEventLoop=lambda: sentinel)
    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat, "asyncio", fake_asyncio)

    assert compat.compatible_event_loop_factory() is sentinel


def test_runner_passes_explicit_factory(monkeypatch) -> None:
    captured: dict[str, object] = {}
    result = object()
    coro = object()

    def fake_run(value, *, loop_factory):
        captured["value"] = value
        captured["factory"] = loop_factory
        return result

    monkeypatch.setattr(compat.asyncio, "run", fake_run)
    assert compat.run_with_compatible_event_loop(coro) is result
    assert captured == {"value": coro, "factory": compat.compatible_event_loop_factory}

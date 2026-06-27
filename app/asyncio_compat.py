from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def configure_windows_selector_event_loop() -> bool:
    """Install the selector policy on Windows for code honoring asyncio policies.

    Recent Uvicorn releases may choose ProactorEventLoop explicitly and therefore
    do not necessarily honor this policy. Entry points in this project also use
    :func:`run_with_compatible_event_loop`, which passes a loop factory directly.
    """

    if sys.platform != "win32":
        return False

    selector_policy_class = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy_class is None:
        raise RuntimeError(
            "This Python build does not provide WindowsSelectorEventLoopPolicy, "
            "which is required by psycopg async mode on Windows."
        )

    current_policy = asyncio.get_event_loop_policy()
    if isinstance(current_policy, selector_policy_class):
        return False

    asyncio.set_event_loop_policy(selector_policy_class())
    return True


def compatible_event_loop_factory() -> asyncio.AbstractEventLoop:
    """Create an event loop compatible with async psycopg on every platform.

    On Windows this deliberately constructs SelectorEventLoop directly. This is
    stronger than setting a policy because Uvicorn 0.48+ explicitly selects a
    ProactorEventLoop when it owns the runner.
    """

    if sys.platform == "win32":
        selector_loop_class = getattr(asyncio, "SelectorEventLoop", None)
        if selector_loop_class is None:
            raise RuntimeError(
                "This Python build does not provide SelectorEventLoop, "
                "which is required by psycopg async mode on Windows."
            )
        return selector_loop_class()
    return asyncio.new_event_loop()


def run_with_compatible_event_loop[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine with an explicit psycopg-compatible loop factory."""

    return asyncio.run(coro, loop_factory=compatible_event_loop_factory)

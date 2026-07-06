from app.asyncio_compat import configure_windows_selector_event_loop

configure_windows_selector_event_loop()

__all__ = ["__version__"]
__version__ = "1.35.5"

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID


def json_compatible(value: Any) -> Any:
    """Return a PostgreSQL/strict-JSON-compatible copy of a value.

    PostgreSQL JSONB rejects IEEE-754 non-finite values even though Python's
    default JSON encoder can emit NaN/Infinity tokens.  Model metrics can also
    contain NumPy scalar values, so normalize those without importing NumPy in
    the runtime utility.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, Enum):
        return json_compatible(value.value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (Path, UUID)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_compatible(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [json_compatible(item) for item in sorted(value, key=repr)]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        native = item_method()
        if native is not value:
            return json_compatible(native)

    raise TypeError(f"Unsupported JSON value type: {type(value)!r}")

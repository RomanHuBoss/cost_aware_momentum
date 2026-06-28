from __future__ import annotations

import json
import math
from decimal import Decimal

import numpy as np

from app.json_utils import json_compatible


def test_json_compatible_normalizes_nested_non_finite_and_numpy_values() -> None:
    result = json_compatible(
        {
            "positive_infinity": math.inf,
            "negative_infinity": -math.inf,
            "not_a_number": math.nan,
            "nested": [np.float64(1.25), np.int64(7), Decimal("NaN")],
        }
    )

    assert result == {
        "positive_infinity": None,
        "negative_infinity": None,
        "not_a_number": None,
        "nested": [1.25, 7, None],
    }
    json.dumps(result, allow_nan=False)

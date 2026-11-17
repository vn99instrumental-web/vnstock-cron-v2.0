"""Regression tests for nested vendor market payloads and JSON cache safety."""

import json
import unittest
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from scripts.vnstock6_json_safe import dumps_json, to_json_safe


class JsonSafeTest(unittest.TestCase):
    def test_nested_order_book_pandas_timestamp_round_trip(self):
        frame = pd.DataFrame({
            "time": pd.to_datetime(["2026-11-17 09:30:00"]),
            "bid_price_1": np.array([101.5], dtype=np.float64),
            "bid_volume_1": np.array([5000], dtype=np.int64),
        })
        payload = {"symbols": {"FPT": {"raw": {"order_book": frame.to_dict("records")}}}}
        decoded = json.loads(dumps_json(payload))
        order = decoded["symbols"]["FPT"]["raw"]["order_book"][0]
        self.assertEqual(order["time"], "2026-11-17T09:30:00")
        self.assertEqual(order["bid_price_1"], 101.5)
        self.assertEqual(order["bid_volume_1"], 5000)

    def test_invalid_numeric_values_and_missing_dates_are_null(self):
        payload = {
            "numpy_nan": np.float64("nan"),
            "numpy_inf": np.float32("inf"),
            "python_inf": float("-inf"),
            "missing": pd.NA,
            "nat": pd.NaT,
            "np_nat": np.datetime64("NaT"),
            "items": [np.float64(0.6), np.int64(9), np.bool_(True)],
        }
        result = json.loads(dumps_json(payload))
        for key in ("numpy_nan", "numpy_inf", "python_inf", "missing", "nat", "np_nat"):
            self.assertIsNone(result[key])
        self.assertEqual(result["items"], [0.6, 9, True])

    def test_dates_durations_arrays_and_timezone(self):
        payload = {
            "date": date(2026, 11, 17),
            "datetime": datetime(2026, 11, 17, 2, 30, tzinfo=timezone.utc),
            "numpy_date": np.datetime64("2026-11-17"),
            "duration": timedelta(minutes=5),
            "array": np.array([1, 2, 3], dtype=np.int32),
            "date_array": np.array(["2026-11-17"], dtype="datetime64[ns]"),
            "tuple": (pd.Timestamp("2026-11-17"),),
        }
        result = json.loads(dumps_json(payload))
        self.assertEqual(result["date"], "2026-11-17")
        self.assertEqual(result["datetime"], "2026-11-17T02:30:00+00:00")
        self.assertEqual(result["numpy_date"], "2026-11-17T00:00:00")
        self.assertEqual(result["duration"], "P0DT0H5M0S")
        self.assertEqual(result["array"], [1, 2, 3])
        self.assertEqual(result["date_array"], ["2026-11-17T00:00:00"])
        self.assertEqual(result["tuple"], ["2026-11-17T00:00:00"])

    def test_unsupported_objects_raise_instead_of_disguising_data(self):
        with self.assertRaisesRegex(TypeError, "Unsupported JSON value type"):
            to_json_safe({"unknown": object()})


if __name__ == "__main__":
    unittest.main()

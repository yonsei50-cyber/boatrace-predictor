"""Tests for the pure Natural Environment v1 tide calculation."""
from datetime import datetime
import unittest

from scripts.natural_environment_tide_v1 import (
    SOURCE_TABLE,
    VENUE_TO_CHITEN_CODE,
    derive_tide_feature,
    race_deadline_timestamp,
)


def row(kind, date, time, height, chiten="WH"):
    return {
        "data_kubun": kind,
        "chiten_code": chiten,
        "kaisai_nen": date[:4],
        "kaisai_tsukihi": date[4:],
        "jikoku": time,
        "choi": height,
    }


class NaturalEnvironmentTideV1Tests(unittest.TestCase):
    def test_confirmed_venue_mapping(self):
        self.assertEqual(VENUE_TO_CHITEN_CODE, {
            "19": "WH", "16": "UN", "03": "TK", "04": "TK",
            "22": "QF", "18": "QA", "17": "Q8", "24": "NS",
            "20": "N1", "06": "MI", "14": "KM", "15": "AX",
        })

    def test_rising_interpolation_crosses_previous_day(self):
        result = derive_tide_feature("19", datetime(2024, 7, 2, 1, 0), [
            row("1", "20240701", "2300", "10"),
            row("2", "20240702", "0300", "30"),
        ])
        self.assertEqual(result["tide_status"], "AVAILABLE")
        self.assertTrue(result["tide_source_available"])
        self.assertEqual(result["tide_direction"], "RISING")
        self.assertAlmostEqual(result["tide_height"], 20.0)
        self.assertAlmostEqual(result["tide_change_speed"], 5.0)
        self.assertEqual(len(result["tide_extrema_lineage"]), 2)
        self.assertEqual(result["tide_extrema_lineage"][0]["source_table"], SOURCE_TABLE)
        self.assertEqual(result["tide_extrema_lineage"][0]["choi_raw"], "10")

    def test_falling_interpolation_crosses_next_day(self):
        result = derive_tide_feature("19", datetime(2024, 7, 1, 23, 0), [
            row(2, "20240701", "2100", 50),
            row(1, "20240702", "0100", 10),
        ])
        self.assertEqual(result["tide_direction"], "FALLING")
        self.assertAlmostEqual(result["tide_height"], 30.0)
        self.assertAlmostEqual(result["tide_change_speed"], 10.0)

    def test_exact_low_and_high_use_source_height_and_zero_speed(self):
        for kind, direction, height in (("1", "LOW_TIDE", "12.5"),
                                         ("2", "HIGH_TIDE", "98")):
            with self.subTest(kind=kind):
                result = derive_tide_feature("19", datetime(2024, 6, 1, 12, 0), [
                    row(kind, "20240601", "1200", height),
                ])
                self.assertEqual(result["tide_status"], "AVAILABLE")
                self.assertEqual(result["tide_direction"], direction)
                self.assertEqual(result["tide_height"], float(height))
                self.assertEqual(result["tide_change_speed"], 0.0)
                self.assertEqual(len(result["tide_extrema_lineage"]), 1)

    def test_not_applicable_is_distinct_from_unresolved(self):
        not_applicable = derive_tide_feature(
            "01", datetime(2024, 1, 1, 12, 0), [],
        )
        self.assertEqual(not_applicable["tide_status"], "NOT_APPLICABLE")
        self.assertFalse(not_applicable["tide_source_available"])
        self.assertIsNone(not_applicable["tide_height"])

        unresolved = derive_tide_feature(
            "19", datetime(2024, 1, 1, 12, 0), [],
        )
        self.assertEqual(unresolved["tide_status"], "UNRESOLVED")
        self.assertTrue(unresolved["tide_source_available"])
        self.assertEqual(unresolved["tide_unresolved_reason"], "NO_EXTREMA_FOR_LOCATION")
        self.assertIsNone(unresolved["tide_change_speed"])

    def test_non_bracketing_duplicate_and_nonalternating_rows_are_unresolved(self):
        cases = [
            ([row(1, "20240601", "1000", 10)], "NO_BRACKETING_EXTREMA"),
            ([row(1, "20240601", "1000", 10),
              row(2, "20240601", "1000", 20)], "DUPLICATE_EXTREMUM_TIMESTAMP"),
            ([row(1, "20240601", "1000", 10),
              row(1, "20240601", "1400", 20)], "INVALID_EXTREMUM_SEQUENCE"),
        ]
        for rows, reason in cases:
            with self.subTest(reason=reason):
                result = derive_tide_feature("19", datetime(2024, 6, 1, 12, 0), rows)
                self.assertEqual(result["tide_status"], "UNRESOLVED")
                self.assertEqual(result["tide_unresolved_reason"], reason)
                self.assertIsNone(result["tide_height"])

    def test_invalid_source_values_are_unresolved(self):
        for field, value in (("data_kubun", "9"), ("choi", ""),
                             ("jikoku", "2500")):
            with self.subTest(field=field):
                bad = row(1, "20240601", "1000", 10)
                bad[field] = value
                result = derive_tide_feature("19", datetime(2024, 6, 1, 12, 0), [bad])
                self.assertEqual(result["tide_status"], "UNRESOLVED")
                self.assertEqual(result["tide_unresolved_reason"], "INVALID_EXTREMUM_ROW")

    def test_other_station_rows_are_ignored(self):
        result = derive_tide_feature("19", datetime(2024, 6, 1, 12, 0), [
            row(1, "20240601", "1000", 10, chiten="QA"),
            row(1, "20240601", "1000", 20),
            row(2, "20240601", "1400", 40),
        ])
        self.assertEqual(result["tide_status"], "AVAILABLE")
        self.assertAlmostEqual(result["tide_height"], 30.0)

    def test_deadline_parser_and_preholdout_boundary(self):
        self.assertEqual(
            race_deadline_timestamp("2024", "0102", "0930"),
            datetime(2024, 1, 2, 9, 30),
        )
        with self.assertRaises(ValueError):
            race_deadline_timestamp("2025", "0101", "0000")
        with self.assertRaises(ValueError):
            derive_tide_feature("19", datetime(2025, 1, 1), [])
        result = derive_tide_feature("19", datetime(2024, 12, 31, 23, 0), [
            row(2, "20241231", "2100", 50),
            row(1, "20250101", "0100", 10),
        ])
        self.assertEqual(result["tide_status"], "UNRESOLVED")
        self.assertEqual(result["tide_unresolved_reason"], "INVALID_EXTREMUM_ROW")


if __name__ == "__main__":
    unittest.main()

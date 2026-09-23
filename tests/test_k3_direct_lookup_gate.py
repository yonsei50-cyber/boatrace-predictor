"""Focused tests for K3 race-key normalization used by the direct lookup gate."""

from datetime import date
import unittest

from scripts.k3_direct_lookup_gate import normalized_key


class NormalizedKeyTests(unittest.TestCase):
    def test_normalizes_padded_and_compact_numeric_key_fields(self):
        cases = [
            (('2025', '0101', '01', '01'), (date(2025, 1, 1), 1, 1)),
            ((' 2025 ', '101', ' 1 ', ' 1 '), (date(2025, 1, 1), 1, 1)),
            (('2025', '1231', '24', '12'), (date(2025, 12, 31), 24, 12)),
        ]
        for raw_key, expected in cases:
            with self.subTest(raw_key=raw_key):
                self.assertEqual(normalized_key(*raw_key), expected)

    def test_rejects_missing_or_non_numeric_key_fields(self):
        cases = [
            (None, '0101', '01', '01'),
            ('2025', None, '01', '01'),
            ('25', '0101', '01', '01'),
            ('2025', '0101', 'venue', '01'),
            ('2025', '0101', '01', 'race'),
            ('2025', '0101', '001', '01'),
            ('2025', '0101', '01', '001'),
        ]
        for raw_key in cases:
            with self.subTest(raw_key=raw_key):
                self.assertIsNone(normalized_key(*raw_key))

    def test_rejects_impossible_calendar_dates(self):
        for month_day in ('0000', '0230', '1301'):
            with self.subTest(month_day=month_day):
                self.assertIsNone(normalized_key('2025', month_day, '01', '01'))


if __name__ == '__main__':
    unittest.main()

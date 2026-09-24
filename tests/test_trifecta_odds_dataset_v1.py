"""Narrow normalization checks for the two independent odds sources."""
import unittest

import numpy as np

from scripts.build_trifecta_odds_dataset_v1 import (
    STATUS, coverage, dump_value, o6_value, odds_or_none,
)


class OddsNormalizationTest(unittest.TestCase):
    def test_o6_raw_states_keep_non_prices_null(self):
        self.assertEqual(o6_value('000084'), (8.4, STATUS['VALID']))
        for token, status in (('000000', 'NO_VOTES'), ('******', 'SCRATCHED'),
                              ('099999', 'CAPPED'), ('ABCDEF', 'INVALID_RAW')):
            value, actual_status = o6_value(token)
            self.assertTrue(np.isnan(value))
            self.assertEqual(actual_status, STATUS[status])
            self.assertIsNone(odds_or_none(value, actual_status))

    def test_five_minute_null_and_invalid_are_not_filled(self):
        value, status = dump_value('17.5', r'\N')
        self.assertEqual((odds_or_none(value, status), status), (17.5, STATUS['VALID']))
        for token, reason, expected in ((r'\N', 'source_nonpositive', 'SOURCE_NONPOSITIVE'),
                                        (r'\N', r'\N', 'SOURCE_MISSING'),
                                        ('0.0', r'\N', 'INVALID_RAW'),
                                        ('', r'\N', 'INVALID_RAW')):
            value, status = dump_value(token, reason)
            self.assertTrue(np.isnan(value))
            self.assertEqual(status, STATUS[expected])
            self.assertIsNone(odds_or_none(value, status))

    def test_partial_race_counts_only_valid_prices(self):
        states = np.full(3 * 120, STATUS['MISSING_SOURCE'], dtype=np.uint8)
        states[:120] = STATUS['VALID']
        states[120] = STATUS['VALID']
        states[121] = STATUS['SOURCE_NONPOSITIVE']
        self.assertEqual(coverage(states), {
            'target_races': 3, 'complete_races': 1, 'partial_races': 1,
            'all_missing_races': 1, 'valid_rows': 121, 'missing_rows': 239,
            'races_with_any_valid_odds': 2})


if __name__ == '__main__':
    unittest.main()

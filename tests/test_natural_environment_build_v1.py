"""Narrow, database-free checks for the pre-holdout source boundary."""
import unittest
from datetime import datetime

from scripts.build_natural_environment_v1 import (
    RACE_SQL, SOURCE_SQL, TIDE_SQL, c2_features, tide_for_race,
)


class NaturalEnvironmentBuildV1Tests(unittest.TestCase):
    def test_wind_rotation_and_calm(self):
        cases = ([(d, 'LEFT_CROSSWIND') for d in (15, 0, 1)]
                 + [(d, 'HEADWIND') for d in range(2, 7)]
                 + [(d, 'RIGHT_CROSSWIND') for d in range(7, 10)]
                 + [(d, 'TAILWIND') for d in range(10, 15)])
        for difference, expected in cases:
            with self.subTest(d=difference):
                fuko = (1 + difference - 1) % 16 + 1
                d, category, speed, weather, air = c2_features(
                    '01', f'{fuko:02d}', '03', '2', '250')
                self.assertEqual((d, category, speed, weather, air),
                                 (difference, expected, 3.0, '2', 25.0))
        self.assertEqual(c2_features('01', '16', '00', '1', '000')[1], 'CALM')

    def test_missing_stays_missing_and_wave_is_absent(self):
        value = c2_features('01', None, None, None, None)
        self.assertEqual(value, (None, 'MISSING', None, 'MISSING', None))
        for sql in (RACE_SQL, SOURCE_SQL, TIDE_SQL):
            self.assertNotIn('hako', sql)
            self.assertNotIn('2026', sql)
        self.assertIn("< '2025'", SOURCE_SQL)
        self.assertIn("< '2025'", TIDE_SQL)
        self.assertIn("< DATE '2025-01-01'", RACE_SQL)

    def test_tide_index_selects_neighboring_extrema(self):
        from decimal import Decimal
        rows = [
            {'data_kubun': '1', 'chiten_code': 'WH', 'kaisai_nen': '2024',
             'kaisai_tsukihi': '0101', 'jikoku': '2330', 'choi': Decimal('10')},
            {'data_kubun': '2', 'chiten_code': 'WH', 'kaisai_nen': '2024',
             'kaisai_tsukihi': '0102', 'jikoku': '0130', 'choi': Decimal('30')},
        ]
        index = {'WH': ([datetime(2024, 1, 1, 23, 30),
                         datetime(2024, 1, 2, 1, 30)], rows)}
        feature = tide_for_race(19, datetime(2024, 1, 2, 0, 30), index)
        self.assertEqual(feature['tide_height'], 20.0)
        self.assertEqual(feature['tide_direction'], 'RISING')
        self.assertEqual(feature['tide_change_speed'], 10.0)


if __name__ == '__main__':
    unittest.main()

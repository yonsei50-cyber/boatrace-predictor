"""Identity and boundary checks for the frozen Rating v1 K3 replay harness."""

from datetime import date
import json
import unittest

from scripts.compare_rating_methods import Entry, Race
from scripts.reevaluate_rating_v1_k3 import (
    EXTRACT_SQL, EXPECTED_FREEZE_SHA256, checked_freeze, frozen_models,
    sha, FREEZE, DEV_OUT, YEAR_2025_OUT, DIFF_OUT, state_fingerprint,
)


class K3RatingReplayTests(unittest.TestCase):
    def test_frozen_identity_and_exact_selected_models(self):
        freeze = checked_freeze()
        self.assertEqual(sha(FREEZE), EXPECTED_FREEZE_SHA256)
        course, overall, short = frozen_models(freeze)
        self.assertEqual(course.config['learning_rate'], 16.0)
        self.assertEqual(overall.config['k_factor'], 120.0)
        self.assertEqual(overall.config['pair_weight'], 'RACE_NORMALIZED')
        self.assertEqual(short.config['basis'], 'VALID_RESULT')
        self.assertEqual(short.config['fallback'], 'AVAILABLE_HISTORY')
        self.assertIn("r.race_date >= DATE '2017-01-01'", EXTRACT_SQL)
        self.assertIn("r.race_date < DATE '2026-01-01'", EXTRACT_SQL)

    def test_course_prediction_ignores_current_race_actual_course(self):
        course = frozen_models(checked_freeze())[0]
        players = tuple(range(101, 107))
        course.prepare_day(set(players), {})
        def item(courses):
            entries = tuple(Entry(i + 1, players[i], 'NUMERIC_VALID', i + 1,
                                  courses[i], True) for i in range(6))
            return Race(1, date(2023, 1, 1), 1, 1,
                        'RESULT_RECORDS_PRESENT', True, entries)
        self.assertEqual(course.predict(item((1, 2, 3, 4, 5, 6))),
                         course.predict(item((6, 5, 4, 3, 2, 1))))

    def test_state_fingerprint_is_deterministic(self):
        models = frozen_models(checked_freeze())
        initial = state_fingerprint(models, set())
        self.assertEqual(initial, state_fingerprint(models, set()))
        for model in models:
            model.prepare_day({101}, {})
        changed = state_fingerprint(models, {101})
        self.assertNotEqual(initial['sha256'], changed['sha256'])

    def test_source_corrected_artifacts_and_differences_reconcile(self):
        dev = json.loads(DEV_OUT.read_text(encoding='utf-8'))
        holdout = json.loads(YEAR_2025_OUT.read_text(encoding='utf-8'))
        comparison = json.loads(DIFF_OUT.read_text(encoding='utf-8'))
        self.assertEqual(dev['freeze_sha256'], EXPECTED_FREEZE_SHA256)
        self.assertEqual(holdout['freeze_sha256'], EXPECTED_FREEZE_SHA256)
        self.assertEqual(dev['deterministic_sha256'],
                         holdout['deterministic_sha256'])
        self.assertEqual(dev['deterministic_sha256'],
                         comparison['new_replay_deterministic_sha256'])
        self.assertEqual(dev['counts']['2022']['strict_races'], 51264)
        self.assertEqual(holdout['counts']['strict_races'], 51311)
        self.assertEqual(sum(holdout['counts'][key] for key in
                             ('strict_races', 'excluded_races')),
                         holdout['counts']['total_races'])
        for year, values in comparison['years'].items():
            for item in values.values():
                self.assertAlmostEqual(item['absolute_difference'],
                                       abs(item['new'] - item['old']))
                self.assertAlmostEqual(item['signed_difference'],
                                       item['new'] - item['old'])
                self.assertAlmostEqual(item['relative_difference'],
                                       item['signed_difference'] / item['old'])
                self.assertAlmostEqual(item['absolute_relative_difference'],
                                       item['absolute_difference'] / abs(item['old']))


if __name__ == '__main__':
    unittest.main()

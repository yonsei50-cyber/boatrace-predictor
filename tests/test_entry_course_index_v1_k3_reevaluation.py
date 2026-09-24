"""Fixture checks for K3-only replay of the unchanged Entry Course v1."""
from datetime import date
import unittest

from scripts.entry_course_index_v1 import COURSES, probabilities_from_counts, window_start
from scripts.reevaluate_entry_course_index_v1_k3 import (
    EXPECTED_RESULT_VERSION, EXTRACT_SQL, checked_freeze, replay_rows,
    source_identity,
)


def race_rows(day, race_id, courses=COURSES, venue=1, result=True):
    return [(day, venue, race_id, boat, courses[boat - 1] if result else None,
             boat if result else None, 'NORMAL' if result else None,
             'NORMALIZED' if result else None,
             'RESULT_RECORDS_PRESENT' if result else 'R2_EVENT_STATE_PRESENT')
            for boat in COURSES]


class SourceCorrectedEntryCourseTests(unittest.TestCase):
    def test_non_k3_canonical_lineage_is_rejected(self):
        class Cursor:
            def __init__(self):
                self.calls = 0
                self.description = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, _sql):
                self.calls += 1
                if self.calls == 2:
                    self.description = [(key,) for key in (
                        'version_id', 'authoritative_source', 'date_start', 'date_end',
                        'source_manifest_hash', 'normalization_version', 'result_races',
                        'result_boats')]

            def fetchone(self):
                if self.calls == 1:
                    return ('boatrace_predictor', 'on')
                if self.calls == 2:
                    return (EXPECTED_RESULT_VERSION, 'brd_k3', date(2017, 1, 1),
                            date(2025, 12, 31), 'manifest', 'k3-only-result-v1', 1, 6)
                return (6, 1)

        class Connection:
            def cursor(self):
                return Cursor()

        # Keep one cursor across the context manager in this fixture.
        cursor = Cursor()
        connection = Connection()
        connection.cursor = lambda: cursor
        with self.assertRaisesRegex(RuntimeError, 'non-K3 Canonical result lineage'):
            source_identity(connection)

    def test_freeze_and_no_old_source_sql(self):
        freeze = checked_freeze()
        self.assertEqual(freeze['method']['selected_candidate_id'], 'RECENT_1Y')
        self.assertEqual(freeze['edogawa']['entry_fixed_basis'], 'EDOGAWA_MODEL_RULE')
        self.assertNotIn('brd_' + 'r3', EXTRACT_SQL.lower())
        self.assertIn('core.race_result', EXTRACT_SQL)

    def test_calendar_window_probability_and_zero_history(self):
        self.assertEqual(window_start(date(2024, 2, 29)), date(2023, 2, 28))
        self.assertEqual(window_start(date(2025, 1, 1)), date(2024, 1, 1))
        self.assertEqual(probabilities_from_counts((2, 0, 0, 0, 0, 0)).probabilities,
                         (1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(probabilities_from_counts((0,) * 6).status, 'NOT_EVALUABLE')

    def test_same_day_isolation_edogawa_exclusion_and_determinism(self):
        swapped = (2, 1, 3, 4, 5, 6)
        source = (race_rows(date(2022, 1, 2), 1)
                  + race_rows(date(2022, 6, 1), 2, swapped, venue=3)
                  + race_rows(date(2023, 1, 1), 3)
                  + race_rows(date(2023, 1, 1), 4, swapped)
                  + race_rows(date(2023, 1, 2), 5, swapped)
                  + race_rows(date(2025, 8, 12), 6, result=False))
        one = replay_rows(iter(source))
        two = replay_rows(iter(source))
        self.assertEqual(one, two)
        year = one['years']['2023']
        self.assertEqual(year['counts']['national_eligible_races'], 3)
        self.assertEqual(year['counts'].get('not_evaluable_entries', 0), 0)
        self.assertEqual(year['overall']['zero_probability_actuals'], 2)
        self.assertEqual(year['overall']['log_loss_status'], 'INFINITE_ZERO_PROBABILITY')
        self.assertEqual(year['zero_audit']['min_boat_history_total'],
                         {str(b): 1 for b in COURSES})
        self.assertEqual(one['years']['2025']['counts']['national_excluded_races'], 1)
        self.assertEqual(one['all_year_eligible_national_races']['2022'], 1)

    def test_zero_history_is_not_evaluable(self):
        replay = replay_rows(iter(race_rows(date(2023, 1, 1), 1)))
        self.assertEqual(replay['years']['2023']['counts']['not_evaluable_entries'], 6)
        self.assertEqual(replay['years']['2023']['overall']['evaluated_entries'], 0)
        self.assertEqual(replay['years']['2023']['zero_audit']['zero_history_boat_days'], 6)


if __name__ == '__main__':
    unittest.main()

"""Frozen Entry Course Index v1 contract tests; no database is required."""
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
import unittest

from scripts.entry_course_index_v1 import (
    CourseEntry, CourseRace, NOT_EVALUABLE, READY, course_counts_for_day,
    eligible, probabilities_for_day, probabilities_from_counts, window_start,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts" / "entry_course_index_method_freeze_v1.json"
CODE = ROOT / "scripts" / "entry_course_index_v1.py"


def race(day, venue=1, courses=(1, 2, 3, 4, 5, 6), finishes=(1, 2, 3, 4, 5, 6)):
    return CourseRace(day, venue, "RESULT_RECORDS_PRESENT", tuple(
        CourseEntry(boat_no, course, finish)
        for boat_no, (course, finish) in enumerate(zip(courses, finishes), 1)
    ))


class EntryCourseV1Tests(unittest.TestCase):
    def test_window_is_previous_calendar_date_inclusive_and_d_exclusive(self):
        self.assertEqual(window_start(date(2024, 2, 29)), date(2023, 2, 28))
        self.assertEqual(window_start(date(2025, 2, 28)), date(2024, 2, 28))
        self.assertEqual(window_start(date(2024, 1, 1)), date(2023, 1, 1))
        races = [race(date(2023, 1, 1)), race(date(2022, 12, 31)),
                 race(date(2024, 1, 1), courses=(2, 1, 3, 4, 5, 6))]
        counts = course_counts_for_day(date(2024, 1, 1), races)
        self.assertEqual(counts[1], (1, 0, 0, 0, 0, 0))
        leap_counts = course_counts_for_day(date(2024, 2, 29), [
            race(date(2023, 2, 27), courses=(2, 1, 3, 4, 5, 6)),
            race(date(2023, 2, 28)),
            race(date(2024, 2, 29), courses=(2, 1, 3, 4, 5, 6)),
        ])
        self.assertEqual(leap_counts[1], (1, 0, 0, 0, 0, 0))
        self.assertEqual(course_counts_for_day(date(2017, 1, 2), [race(date(2016, 12, 31))])[1],
                         (0, 0, 0, 0, 0, 0))

    def test_course_eligibility_does_not_require_rating_strict_finish(self):
        special = race(date(2024, 1, 1), finishes=(1, None, None, None, None, None))
        self.assertTrue(eligible(special))
        self.assertFalse(eligible(race(date(2024, 1, 1), finishes=(None,) * 6)))
        self.assertFalse(eligible(replace(special, result_state="R2_EVENT_STATE_PRESENT")))
        self.assertFalse(eligible(replace(special, entries=special.entries[:5])))
        no_result = replace(special.entries[1], has_result=False)
        self.assertFalse(eligible(replace(special, entries=(special.entries[0], no_result, *special.entries[2:]))))
        missing_course = replace(special.entries[1], actual_course=None)
        self.assertFalse(eligible(replace(special, entries=(special.entries[0], missing_course, *special.entries[2:]))))
        duplicate_course = replace(special.entries[1], actual_course=1)
        self.assertFalse(eligible(replace(special, entries=(special.entries[0], duplicate_course, *special.entries[2:]))))

    def test_edogawa_does_not_enter_national_counts(self):
        day = date(2024, 6, 1)
        national = race(date(2024, 5, 1))
        edogawa = race(date(2024, 5, 2), venue=3, courses=(2, 1, 3, 4, 5, 6))
        counts = course_counts_for_day(day, (national, edogawa))
        self.assertEqual(counts[1], (1, 0, 0, 0, 0, 0))

    def test_same_day_results_cannot_change_the_d_state(self):
        day = date(2024, 6, 1)
        prior = race(date(2024, 5, 1))
        today = race(day, courses=(2, 1, 3, 4, 5, 6))
        self.assertEqual(probabilities_for_day(day, [prior]),
                         probabilities_for_day(day, [prior, today]))
        tomorrow = probabilities_for_day(date(2024, 6, 2), [prior, today])
        self.assertEqual(tomorrow[1].probabilities, (0.5, 0.5, 0.0, 0.0, 0.0, 0.0))

    def test_probability_range_sum_zero_cell_and_zero_history(self):
        result = probabilities_from_counts((2, 1, 0, 0, 0, 0))
        self.assertEqual(result.status, READY)
        self.assertEqual(result.probabilities, (2 / 3, 1 / 3, 0.0, 0.0, 0.0, 0.0))
        self.assertTrue(all(0 <= p <= 1 for p in result.probabilities))
        self.assertAlmostEqual(sum(result.probabilities), 1.0)
        self.assertEqual(probabilities_from_counts((0,) * 6).status, NOT_EVALUABLE)
        self.assertIsNone(probabilities_from_counts((0,) * 6).probabilities)
        with self.assertRaises(ValueError):
            probabilities_from_counts((-1, 1, 0, 0, 0, 0))

    def test_freeze_artifact_matches_reference_code_and_development_choice(self):
        frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(frozen["freeze_id"], "ENTRY_COURSE_INDEX_METHOD_FREEZE_V1")
        self.assertEqual(frozen["status"], "METHOD_FROZEN")
        self.assertEqual(frozen["method"]["selected_candidate_id"], "RECENT_1Y")
        self.assertEqual(frozen["method"]["smoothing"], "NONE")
        self.assertEqual(frozen["window"]["start_inclusive"], "previous calendar year's same month and day; Feb 29 maps to Feb 28")
        self.assertEqual(frozen["window"]["end_exclusive"], "prediction date D")
        self.assertEqual(frozen["zero_history"]["status"], NOT_EVALUABLE)
        self.assertEqual(frozen["holdout_2025"]["status"], "SEALED_NOT_EVALUATED")
        self.assertEqual(frozen["development_evidence"]["scoring_period_2024"]["RECENT_1Y"]["entries"], 316062)
        metrics = frozen["development_evidence"]["scoring_period_2024"]
        self.assertLess(metrics["RECENT_1Y"]["log_loss"], metrics["RECENT_2Y"]["log_loss"])
        self.assertEqual(round(metrics["RECENT_1Y"]["log_loss"], 6), 0.400248)
        self.assertEqual(round(frozen["development_evidence"]["scoring_period_2023"]["RECENT_1Y"]["log_loss"], 6), 0.422372)
        canonical_code = CODE.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
        self.assertEqual(frozen["hashes"]["reference_code_sha256_lf"], hashlib.sha256(canonical_code).hexdigest())


if __name__ == "__main__":
    unittest.main()

"""Fixture-only checks for the one-shot Entry Course Index v1 holdout."""
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.entry_course_index_v1 import (
    CourseEntry, CourseRace, NOT_EVALUABLE, course_counts_for_day,
    eligible, probabilities_for_day, window_start,
)
from scripts.evaluate_entry_course_index_v1_holdout_2025 import (
    EXPECTED_HEAD, Metrics, checked_freeze, evaluate, evaluate_stream,
    mark_started,
)


def rows(day, race_id, venue=1, courses=(1, 2, 3, 4, 5, 6),
         finishes=(1, 2, 3, 4, 5, 6), state="RESULT_RECORDS_PRESENT"):
    return [(day, venue, race_id, boat, courses[boat - 1], finishes[boat - 1],
             "NORMAL" if finishes[boat - 1] is not None else "F", "NORMALIZED", state)
            for boat in range(1, 7)]


class EntryCourseHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fixture checks remain valid after the holdout checkpoint changes HEAD.
        with patch("scripts.evaluate_entry_course_index_v1_holdout_2025.git_head",
                   return_value=EXPECTED_HEAD):
            cls.freeze = checked_freeze()

    def test_real_execution_still_requires_the_original_freeze_head(self):
        with patch("scripts.evaluate_entry_course_index_v1_holdout_2025.git_head",
                   return_value="different-head"):
            with self.assertRaisesRegex(RuntimeError, "freeze checkpoint"):
                checked_freeze()

    def test_freeze_identity_window_and_eligibility(self):
        self.assertEqual(self.freeze["method"]["selected_candidate_id"], "RECENT_1Y")
        self.assertEqual(self.freeze["method"]["smoothing"], "NONE")
        self.assertEqual(self.freeze["holdout_2025"]["status"], "SEALED_NOT_EVALUATED")
        self.assertEqual(window_start(date(2024, 2, 29)), date(2023, 2, 28))
        self.assertEqual(window_start(date(2025, 1, 1)), date(2024, 1, 1))
        special = CourseRace(date(2024, 6, 1), 1, "RESULT_RECORDS_PRESENT", tuple(
            CourseEntry(b, b, 1 if b == 1 else None) for b in range(1, 7)))
        self.assertTrue(eligible(special))
        self.assertFalse(eligible(CourseRace(special.race_date, 1, special.result_state,
                                             special.entries[:5])))

    def test_one_frozen_state_per_day_and_edogawa_exclusion(self):
        history = rows(date(2024, 1, 1), 1)
        edo = rows(date(2024, 6, 1), 2, venue=3, courses=(2, 1, 3, 4, 5, 6))
        day = rows(date(2025, 1, 1), 3) + rows(date(2025, 1, 1), 4,
                                               courses=(2, 1, 3, 4, 5, 6))
        next_day = rows(date(2025, 1, 2), 5, courses=(2, 1, 3, 4, 5, 6))
        limited_freeze = json.loads(json.dumps(self.freeze))
        limited_freeze["development_evidence"]["scoring_period_2024"]["RECENT_1Y"]["entries"] = 6
        result = evaluate_stream(iter(history + edo + day + next_day), limited_freeze)
        self.assertEqual(result["counts"]["national_eligible_races"], 3)
        self.assertEqual(result["overall"]["evaluated_entries"], 18)
        self.assertEqual(result["counts"].get("edogawa_races", 0), 0)
        self.assertEqual(result["overall"]["zero_probability_actuals"], 2)
        self.assertEqual(result["overall"]["log_loss_status"], "INFINITE_ZERO_PROBABILITY")
        self.assertIsNone(result["overall"]["log_loss"])
        self.assertEqual([(x["date"], x["boat_no"], x["actual_course"]) for x in
                          result["zero_probability_actuals"]],
                         [("2025-01-01", 1, 2), ("2025-01-01", 2, 1)])
        race = CourseRace(date(2024, 1, 1), 1, "RESULT_RECORDS_PRESENT", tuple(
            CourseEntry(b, b, b) for b in range(1, 7)))
        edo_race = CourseRace(date(2024, 6, 1), 3, "RESULT_RECORDS_PRESENT", tuple(
            CourseEntry(b, (2, 1, 3, 4, 5, 6)[b - 1], b) for b in range(1, 7)))
        self.assertEqual(course_counts_for_day(date(2025, 1, 1), [race, edo_race])[1],
                         (1, 0, 0, 0, 0, 0))
        self.assertEqual(probabilities_for_day(date(2025, 1, 1), [race])[1],
                         probabilities_for_day(date(2025, 1, 1), [race,
                             CourseRace(date(2025, 1, 1), 1, "RESULT_RECORDS_PRESENT", tuple(
                                 CourseEntry(b, (2, 1, 3, 4, 5, 6)[b - 1], b)
                                 for b in range(1, 7)))] )[1])

    def test_zero_history_is_not_evaluable_without_fallback(self):
        limited_freeze = json.loads(json.dumps(self.freeze))
        limited_freeze["development_evidence"]["scoring_period_2024"]["RECENT_1Y"]["entries"] = 0
        result = evaluate_stream(iter(rows(date(2025, 1, 1), 1)), limited_freeze)
        self.assertEqual(result["counts"]["national_eligible_races"], 1)
        self.assertEqual(result["counts"]["not_evaluable_entries"], 6)
        self.assertEqual(result["overall"]["evaluated_entries"], 0)
        self.assertEqual(result["overall"]["log_loss_status"], NOT_EVALUABLE)
        self.assertEqual(len(result["zero_history_boat_days"]), 6)

    def test_edogawa_2025_is_diagnostic_only(self):
        limited_freeze = json.loads(json.dumps(self.freeze))
        limited_freeze["development_evidence"]["scoring_period_2024"]["RECENT_1Y"]["entries"] = 6
        source = rows(date(2024, 1, 1), 1)
        edogawa = rows(date(2025, 1, 1), 2, venue=3,
                       courses=(2, 1, 3, 4, 5, 6))
        national = rows(date(2025, 1, 1), 3)
        result = evaluate_stream(iter(source + edogawa + national), limited_freeze)
        self.assertEqual(result["counts"]["edogawa_eligible_races"], 1)
        self.assertEqual(result["counts"]["edogawa_mismatched_entries"], 2)
        self.assertEqual(result["counts"]["national_eligible_races"], 1)
        self.assertEqual(result["overall"]["evaluated_entries"], 6)
        self.assertEqual(result["overall"]["zero_probability_actuals"], 0)

    def test_metrics_validate_normalization_and_do_not_epsilon_clip(self):
        metric = Metrics()
        self.assertTrue(metric.add((1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 2))
        self.assertIsNone(metric.result()["log_loss"])
        with self.assertRaisesRegex(RuntimeError, "invalid frozen probability"):
            metric.add((0.5, 0.4, 0.0, 0.0, 0.0, 0.0), 1)

    def test_single_run_gate_rejects_reentry_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            gate_path = Path(directory) / "gate.json"
            result_path = Path(directory) / "result.json"
            gate_path.write_text(json.dumps({"status": "READY", "identity": {"head": "frozen"},
                                             "dataset": {"full_shard_chain_sha256": "source"}}),
                                 encoding="utf-8")
            gate = mark_started(gate_path, result_path, {"head": "frozen"}, "source", "snapshot")
            self.assertEqual(gate["status"], "STARTED")
            self.assertIn("evaluation_started_utc", gate)
            with self.assertRaisesRegex(RuntimeError, "already consumed"):
                mark_started(gate_path, result_path, {"head": "frozen"}, "source", "snapshot")
            gate["status"] = "COMPLETED"
            gate_path.write_text(json.dumps(gate), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already consumed"):
                mark_started(gate_path, result_path, {"head": "frozen"}, "source", "snapshot")
            result_path.write_text("{}", encoding="utf-8")
            with (patch("scripts.evaluate_entry_course_index_v1_holdout_2025.GATE", gate_path),
                  patch("scripts.evaluate_entry_course_index_v1_holdout_2025.RESULT", result_path),
                  patch("scripts.evaluate_entry_course_index_v1_holdout_2025.target_connection") as connect):
                with self.assertRaisesRegex(RuntimeError, "unique READY gate"):
                    evaluate()
                connect.assert_not_called()

    def test_2026_rows_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "extraction crossed"):
            evaluate_stream(iter(rows(date(2026, 1, 1), 1)), self.freeze)


if __name__ == "__main__":
    unittest.main()

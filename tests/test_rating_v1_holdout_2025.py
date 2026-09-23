"""Deterministic checks for the one-shot Rating v1 holdout harness."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from datetime import date
from unittest.mock import patch

from scripts.compare_rating_methods import Entry, Race
from scripts.evaluate_rating_v1_holdout_2025 import (
    BinaryMetric, EXPECTED_CHECKPOINT, EXTRACT_SQL, FROZEN_EXTRACT_SQL,
    checked_freeze, evaluate, model_state, selected_models,
)


class HoldoutHarnessTest(unittest.TestCase):
    @staticmethod
    def frozen_models():
        with patch("scripts.evaluate_rating_v1_holdout_2025.git_head",
                   return_value=EXPECTED_CHECKPOINT):
            return selected_models(checked_freeze())

    def test_frozen_head_passes_and_different_head_is_rejected(self):
        self.assertEqual(EXPECTED_CHECKPOINT,
                         "240044f92975fa6f6c426d899660ec134f2666dc")
        with patch("scripts.evaluate_rating_v1_holdout_2025.git_head",
                   return_value=EXPECTED_CHECKPOINT):
            self.assertEqual(checked_freeze()["status"], "RATING_METHOD_FROZEN")
        with patch("scripts.evaluate_rating_v1_holdout_2025.git_head",
                   return_value="0" * 40):
            with self.assertRaisesRegex(RuntimeError, "unexpected Git checkpoint"):
                checked_freeze()

    def test_completed_gate_rejects_holdout_rerun(self):
        with TemporaryDirectory() as temporary:
            gate = Path(temporary) / "gate.json"
            gate.write_text(json.dumps({"status": "COMPLETED"}), encoding="utf-8")
            report = Path(temporary) / "absent_result.json"
            with patch("scripts.evaluate_rating_v1_holdout_2025.GATE", gate), \
                 patch("scripts.evaluate_rating_v1_holdout_2025.REPORT", report):
                with self.assertRaisesRegex(RuntimeError, "execution already started"):
                    evaluate()

    def test_only_query_change_is_exclusive_2026_upper_bound(self):
        self.assertEqual(EXTRACT_SQL, FROZEN_EXTRACT_SQL.replace(
            "DATE '2025-01-01'", "DATE '2026-01-01'"))

    def test_frozen_selected_methods_and_parameters_resolve(self):
        models = self.frozen_models()
        self.assertEqual([model.candidate_id for model in models], [
            "A-lr16-WARMUP_2017_2022-STRICT",
            "B-k120-RACE_NORMALIZED-WARMUP_2017_2022-STRICT",
            "SHORT50-VALID_RESULT-AVAILABLE_HISTORY",
        ])

    def test_same_day_predictions_do_not_change_rating_state(self):
        models = self.frozen_models()
        day = date(2025, 1, 1)
        entries = tuple(Entry(i, 100 + i, "NUMERIC_VALID", i, i, True)
                        for i in range(1, 7))
        races = [Race(n, day, 1, n, "RESULT_RECORDS_PRESENT", True, entries)
                 for n in (1, 2)]
        players = {entry.player_id for entry in entries}
        for model in models:
            model.prepare_day(players, {})
        before = model_state(models)
        first = [model.predict(races[0]) for model in models]
        second = [model.predict(races[1]) for model in models]
        self.assertEqual(first, second)
        models[0].deltas(races[0])
        models[1].deltas(races[0])
        self.assertEqual(model_state(models), before)

    def test_course_binary_metric(self):
        metric = BinaryMetric()
        metric.add(0.8, True)
        metric.add(0.2, False)
        value = metric.json()
        self.assertEqual(value["boats"], 2)
        self.assertEqual(value["events"], 1)
        self.assertAlmostEqual(value["binary_brier"], 0.04)


if __name__ == "__main__":
    unittest.main()

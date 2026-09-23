"""Motor A v1 freeze contract: synthetic, deterministic, and database-free."""
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import json
import unittest

from scripts.motor_a_v1 import (
    FINISH_POINTS, NOT_EVALUABLE, READY, MeetingDay, MotorEntry, MotorIdentity,
    build_meeting_days, eligibility_reason, motor_residual, replay_development,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "artifacts" / "motor_a_method_freeze_v1.json"
MOTOR = MotorIdentity(1, 2023, 7)


def entry(day, residual=1.0, motor=MOTOR, race_no=1, player=101):
    return MotorEntry(
        day, 1, race_no, 1, player, motor, "NUMERIC_VALID", 1, True,
        "VALID", 10.0 - residual,
    )


def certified(start, end, venue=1):
    return {(venue, start + timedelta(days=n)): MeetingDay(
        "CERTIFIED", start, end, (),
    ) for n in range((end - start).days + 1)}


class MotorAV1Tests(unittest.TestCase):
    def test_finish_points_residual_and_eligibility(self):
        self.assertEqual(FINISH_POINTS, {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1})
        e = entry(date(2024, 1, 1), residual=1.75)
        self.assertEqual(motor_residual(e), 1.75)
        self.assertIsNone(eligibility_reason(e))
        self.assertEqual(eligibility_reason(replace(e, finish_state="UNRESOLVED_SPECIAL",
                                                    finish_position=None)),
                         "FINISH_UNRESOLVED_SPECIAL")
        self.assertEqual(eligibility_reason(replace(e, has_canonical_result=False)),
                         "RESULT_MISSING")
        self.assertEqual(eligibility_reason(replace(e, national_win_rate_status="UNRESOLVED",
                                                    national_win_rate=None)),
                         "RATE_UNRESOLVED")
        self.assertEqual(eligibility_reason(replace(e, motor=None)), "MOTOR_UNKNOWN")
        self.assertEqual(eligibility_reason(replace(e, player_id=None)), "PLAYER_UNKNOWN")
        with self.assertRaises(ValueError):
            motor_residual(replace(e, national_win_rate_status="UNRESOLVED"))

    def test_source_meeting_identity_blank_support_gap_and_uncertainty(self):
        d1, d2, d3 = date(2024, 1, 1), date(2024, 1, 3), date(2024, 1, 4)
        l1 = {(1, d1): ("1", "A"), (1, d2): ("", "A"), (1, d3): ("9", "A")}
        b1 = {(1, d1): ("1", "A"), (1, d2): ("2", "A"), (1, d3): ("3", "A")}
        k1 = dict(b1)
        mapped = build_meeting_days(l1, b1, k1)
        self.assertEqual(mapped[(1, d2)].status, "CERTIFIED")
        self.assertEqual(mapped[(1, d2)].start, d1)
        self.assertEqual(mapped[(1, d2)].end, d3)
        # The two-day date gap does not create a new meeting.
        self.assertEqual(len(mapped), 3)
        no_final = build_meeting_days({(1, d1): ("1", "A")},
                                      {(1, d1): ("1", "A")},
                                      {(1, d1): ("1", "A")})[(1, d1)]
        self.assertEqual(no_final.reasons, ("NO_FINAL_9",))
        self.assertTrue(no_final.current_known)
        no_start = build_meeting_days({(1, d3): ("9", "B")},
                                      {(1, d3): ("2", "B")},
                                      {(1, d3): ("2", "B")})[(1, d3)]
        self.assertIn("NO_START_1", no_start.reasons)
        self.assertFalse(no_start.current_known)
        mismatch = build_meeting_days(l1, b1, {**k1, (1, d2): ("3", "A")})
        self.assertEqual(mismatch[(1, d1)].status, "UNKNOWN")
        self.assertFalse(mismatch[(1, d1)].current_known)

    def test_day_block_current_same_player_and_base_after_final(self):
        d1, d2, d3 = (date(2024, 1, n) for n in (1, 2, 3))
        days = {**certified(d1, d2), **certified(d3, d3)}
        rows = [entry(d1, 1, race_no=1), entry(d1, 3, race_no=2),
                entry(d2, 5), entry(d3, 7, player=202)]
        a, b, c, d = replay_development(rows, days)
        self.assertEqual((a.motor_a_current, b.motor_a_current), (None, None))
        self.assertEqual((a.current_n_uses, b.current_n_uses), (0, 0))
        self.assertEqual(c.motor_a_current, 2)
        self.assertEqual(c.current_n_uses, 2)
        self.assertEqual(c.motor_a_base3, None)  # Current meeting excluded.
        self.assertEqual(d.motor_a_base3, 3)  # (1+3+5)/3, after final D.
        self.assertEqual((d.base_n_meetings, d.base_n_uses), (1, 3))
        self.assertIsNone(d.motor_a_current)
        self.assertEqual(c.current_status, READY)
        self.assertEqual(d.current_status, NOT_EVALUABLE)

    def test_equal_meeting_weight_max_three_and_generation_separation(self):
        days = {}
        rows = []
        for i, values in enumerate(((0, 2), (5,), (9,), (4,), (6,))):
            start = date(2024, 1, 1 + i * 2)
            days.update(certified(start, start))
            rows.extend(entry(start, residual, race_no=j + 1)
                        for j, residual in enumerate(values))
        other = MotorIdentity(1, 2024, 7)
        rows.append(entry(date(2024, 1, 9), 8, motor=other, race_no=3))
        features = replay_development(rows, days)
        fourth = next(f for f in features if f.day == date(2024, 1, 7))
        fifth = next(f for f in features if f.day == date(2024, 1, 9) and f.motor == MOTOR)
        other_feature = next(f for f in features if f.motor == other)
        self.assertEqual(fourth.motor_a_base3, (1 + 5 + 9) / 3)
        self.assertNotEqual(fourth.motor_a_base3, (0 + 2 + 5 + 9) / 4)
        self.assertEqual((fourth.base_n_meetings, fourth.base_n_uses), (3, 4))
        self.assertEqual(fourth.base_residual_sum, 16)
        self.assertNotEqual(fourth.motor_a_base3 * fourth.base_n_uses,
                            fourth.base_residual_sum)
        self.assertEqual(fifth.motor_a_base3, (5 + 9 + 4) / 3)
        self.assertEqual((fifth.base_n_meetings, fifth.base_n_uses), (3, 3))
        self.assertIsNone(other_feature.motor_a_base3)
        self.assertEqual((other_feature.base_n_meetings, other_feature.base_n_uses), (0, 0))

    def test_unknown_meetings_reproduce_development_boundaries(self):
        d1, d2, d3, d4 = (date(2024, 2, n) for n in (1, 2, 3, 4))
        days = {**certified(d1, d1),
                (1, d2): MeetingDay("UNKNOWN", d2, None, ("NO_FINAL_9",)),
                (1, d3): MeetingDay("UNKNOWN", d2, None, ("NO_FINAL_9",)),
                **certified(d4, d4)}
        a, b, c, d = replay_development(
            [entry(d1, 2), entry(d2, 4), entry(d3, 6), entry(d4, 8)], days,
        )
        self.assertIsNone(a.motor_a_base3)
        self.assertEqual(b.motor_a_base3, 2)  # Prior certified Base still visible.
        self.assertEqual(c.motor_a_current, 4)
        self.assertEqual(c.current_n_uses, 1)
        self.assertIsNone(d.motor_a_base3)  # Unfinalized intervening meeting resets.
        no_start = {(1, d2): MeetingDay("UNKNOWN", None, d2, ("NO_START_1",))}
        days = {**certified(d1, d1), **no_start, **certified(d3, d3)}
        first, unknown, after = replay_development(
            [entry(d1, 2), entry(d2, 4), entry(d3, 6)], days,
        )
        self.assertEqual((unknown.motor_a_base3, unknown.motor_a_current), (None, None))
        self.assertEqual((unknown.base_n_uses, unknown.current_n_uses), (0, 0))
        self.assertIsNone(after.motor_a_base3)

    def test_ineligible_visit_still_breaks_unknown_continuity(self):
        d1, d2, d3 = (date(2024, 3, n) for n in (1, 2, 3))
        days = {**certified(d1, d1),
                (1, d2): MeetingDay("UNKNOWN", None, d2, ("NO_START_1",)),
                **certified(d3, d3)}
        bad = replace(entry(d2), finish_state="UNRESOLVED_SPECIAL",
                      finish_position=None)
        a, b = replay_development([entry(d1), bad, entry(d3)], days)
        self.assertIsNone(b.motor_a_base3)

    def test_freeze_consistency_and_continuous_not_probability(self):
        frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(frozen["freeze_id"], "MOTOR_A_METHOD_FREEZE_V1")
        self.assertEqual(frozen["status"], "METHOD_FROZEN")
        self.assertEqual({int(k): v for k, v in frozen["residual"]["finish_points"].items()},
                         FINISH_POINTS)
        self.assertEqual(frozen["features"]["motor_a_base3"]["meeting_weight"],
                         "EQUAL; do not pool all races across meetings")
        self.assertFalse(frozen["meeting_identity"]["date_gap_inference"])
        self.assertEqual(frozen["development_evidence"]["meeting_counts"]["unknown"], 55)
        self.assertEqual(frozen["development_period"]["independent_holdout_2025"],
                         "SEALED_NOT_EVALUATED")
        d1, d2 = date(2024, 1, 1), date(2024, 1, 2)
        feature = replay_development([entry(d1, 8), entry(d2, -2)],
                                     certified(d1, d2))[1]
        self.assertEqual(feature.motor_a_current, 8)
        self.assertGreater(feature.motor_a_current, 1)  # Continuous residual.
        self.assertIsNone(feature.motor_a_base3)
        self.assertFalse(hasattr(feature, "observed_residual"))


if __name__ == "__main__":
    unittest.main()

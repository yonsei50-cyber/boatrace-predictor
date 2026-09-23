"""Boundary checks for the unchanged K3-only daily F state machine."""

from datetime import date, timedelta
import unittest

from scripts.f_suspension_k3_only_probe import State


class DailyFSuspensionTests(unittest.TestCase):
    def test_29_30_31_day_gap(self):
        start = date(2024, 1, 1)
        for days, expected in ((29,'ACTIVE_UNSERVED'),(30,'CLEAR'),(31,'CLEAR')):
            with self.subTest(days=days):
                state = State()
                state.day(start,confirmed=1,f_events=1)
                self.assertEqual(state.day(start+timedelta(days=days))['before'],expected)

    def test_same_day_evidence_is_applied_after_prediction(self):
        state = State()
        result = state.day(date(2017, 1, 1),confirmed=2,f_events=1)
        self.assertEqual(result['before'],'UNRESOLVED')
        self.assertEqual(result['after'],'ACTIVE_UNSERVED')
        self.assertEqual(state.day(date(2017, 1, 2))['before'],'ACTIVE_UNSERVED')

    def test_second_f_and_one_gap_clears_all_pending(self):
        state = State()
        state.day(date(2024, 1, 1),confirmed=1,f_events=1)
        second = state.day(date(2024, 1, 5),confirmed=1,f_events=1)
        self.assertEqual(second['f2'],1)
        self.assertEqual(state.pending_f,2)
        self.assertEqual(state.day(date(2024, 2, 4))['before'],'CLEAR')
        self.assertEqual(state.pending_f,0)

    def test_period_boundary_does_not_reset(self):
        state = State()
        state.day(date(2024, 12, 31),confirmed=1,f_events=1)
        self.assertEqual(state.day(date(2025, 1, 1))['before'],'ACTIVE_UNSERVED')

    def test_2017_seed_is_active_and_unknown_stays_unknown(self):
        self.assertEqual(State(date(2016, 12, 31)).day(date(2017, 1, 1))['before'],
                         'ACTIVE_UNSERVED')
        self.assertEqual(State().day(date(2017, 1, 1))['before'],'UNRESOLVED')


if __name__ == '__main__':
    unittest.main()

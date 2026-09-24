"""Focused Prediction Dataset v1 grain, label, and D-1 join tests."""
import os
import unittest
from datetime import date

from scripts.build_prediction_dataset_v1 import (
    Builder, COLUMNS, current_term_value, f_evidence, label_flags,
)
from scripts.motor_a_v1 import MeetingDay
from scripts.db import target_connection


def race_rows(day, race_id, race_no, finishes=(1, 2, 3, 4, 5, 6), venue=1):
    rows = []
    for boat, finish in enumerate(finishes, 1):
        valid = finish in range(1, 7) if isinstance(finish, int) else False
        rows.append(dict(
            race_id=race_id, race_date=day, venue_code=venue, race_no=race_no,
            boat_no=boat, player_id=2000 + boat, motor_id=100 + boat,
            generation_start_year=2017, generation_start_date=date(2017, 1, 1),
            generation_end_date=date(2027, 1, 1), motor_no=boat,
            identity_rule_version='user-fixed-month-day-v1',
            national_win_rate=5.0, national_win_rate_status='VALID',
            f_count_current_term_raw='0', f_count_current_term=0,
            finish_state='NUMERIC_VALID' if valid else 'UNRESOLVED_SPECIAL',
            finish_position=finish if valid else None, actual_course=boat,
            result_state='RESULT_RECORDS_PRESENT', has_verified_r2_event_code=False,
            k3_finish_position=finish if valid else None,
            finish_raw=f'{finish:02}' if valid else finish,
            start_timing_raw='123', has_k3_result=True,
            result_source='brd_k3', entry_source='brd_l3',
        ))
    return rows


class DatasetV1Tests(unittest.TestCase):
    def test_label_requires_six_unique_numeric_k3_results_without_course_requirement(self):
        rows = race_rows(date(2023, 1, 1), 1, 1)
        self.assertTrue(label_flags(rows))
        rows[0]['actual_course'] = None
        self.assertTrue(label_flags(rows))
        rows[0]['finish_state'] = 'UNRESOLVED_SPECIAL'
        rows[0]['finish_position'] = None
        self.assertFalse(label_flags(rows))
        rows = race_rows(date(2023, 1, 1), 1, 1)
        rows[0]['result_source'] = 'other'
        self.assertFalse(label_flags(rows))
        self.assertFalse(label_flags(rows[:5]))

    def test_same_day_f_and_rating_and_course_wait_until_next_day(self):
        d1, d2 = date(2017, 1, 1), date(2017, 1, 2)
        days = {(1, d1): MeetingDay('CERTIFIED', d1, d2, ()),
                (1, d2): MeetingDay('CERTIFIED', d1, d2, ())}
        builder = Builder(days, {})
        first = race_rows(d1, 1, 1)
        first[0]['finish_raw'] = 'F'
        first[0]['finish_state'] = 'UNRESOLVED_SPECIAL'
        first[0]['finish_position'] = None
        first[0]['k3_finish_position'] = None
        later = race_rows(d1, 2, 2)
        later[0]['finish_raw'] = 'F'
        later[0]['finish_state'] = 'UNRESOLVED_SPECIAL'
        later[0]['finish_position'] = None
        later[0]['k3_finish_position'] = None
        day1 = builder.process_day(d1, [first, later])
        col = {name: i for i, name in enumerate(COLUMNS)}
        self.assertEqual(len(day1), 12)
        self.assertEqual(len({(r[0], r[4]) for r in day1}), 12)
        self.assertEqual(day1[0][col['f_suspension_state']],
                         day1[6][col['f_suspension_state']])
        self.assertEqual(day1[0][col['rating_overall']],
                         day1[6][col['rating_overall']])
        self.assertIsNone(day1[0][col['entry_course_prob_1_to_6']])
        self.assertFalse(day1[0][col['label_eligible']])
        self.assertIsNone(day1[0][col['label_p1']])
        self.assertIsNone(day1[0][col['label_p2']])
        day2 = builder.process_day(d2, [race_rows(d2, 3, 1)])
        self.assertEqual(day2[0][col['f_suspension_state']], 'ACTIVE_UNSERVED')
        self.assertIsNotNone(day2[0][col['entry_course_prob_1_to_6']])
        self.assertTrue(day2[0][col['label_eligible']])
        self.assertEqual(sum(r[col['label_p1']] for r in day2), 1)
        self.assertEqual(sum(r[col['label_p2']] for r in day2), 1)
        self.assertEqual(day2[0][col['current_term_f_count']], 0)

    def test_edogawa_and_missing_status(self):
        day = date(2017, 1, 1)
        rows = race_rows(day, 1, 1, venue=3)
        for row in rows:
            row['f_count_current_term_raw'] = '?'
            row['f_count_current_term'] = None
        builder = Builder({(3, day): MeetingDay('UNKNOWN', None, None,
                                               ('NO_START_1',))}, {})
        output = builder.process_day(day, [rows])
        col = {name: i for i, name in enumerate(COLUMNS)}
        self.assertEqual(output[0][col['entry_course_status']], 'EDOGAWA_MODEL_RULE')
        self.assertEqual(output[0][col['entry_course_prob_1_to_6']], '{1,0,0,0,0,0}')
        self.assertEqual(output[0][col['current_term_f_count_status']], 'UNRESOLVED')
        self.assertIsNone(output[0][col['current_term_f_count']])
        self.assertIsNone(output[0][col['motor_a_current']])

    def test_current_term_and_f_evidence(self):
        row = race_rows(date(2017, 1, 1), 1, 1)[0]
        row['f_count_current_term_raw'] = '02'
        row['f_count_current_term'] = 2
        self.assertEqual(current_term_value(row), 2)
        row['entry_source'] = 'other'
        self.assertIsNone(current_term_value(row))
        row['has_k3_result'] = False
        self.assertEqual(f_evidence(row), (0, 1, 0))


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                     'explicit local DB test opt-in required')
class DatasetV1DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = target_connection()
        cls.conn.commit()
        cls.conn.set_session(readonly=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def scalar(self, sql):
        with self.conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute(sql)
            return cur.fetchone()

    def test_primary_grain_and_six_boat_labels(self):
        rows, entries = self.scalar("""
            SELECT (SELECT count(*) FROM core.prediction_dataset_v1),
                   (SELECT count(*) FROM core.race_entry e JOIN core.race r USING(race_id)
                    WHERE r.race_date>=DATE '2017-01-01')
        """)
        self.assertEqual(rows, entries)
        (bad,) = self.scalar("""
            SELECT count(*) FROM (
                SELECT race_id,count(*) n,sum(label_p1) p1,sum(label_p2) p2
                FROM core.prediction_dataset_v1 WHERE label_eligible
                GROUP BY race_id HAVING count(*)<>6 OR sum(label_p1)<>1 OR sum(label_p2)<>1
            ) x
        """)
        self.assertEqual(bad, 0)

    def test_entry_and_motor_state_fixed_within_day(self):
        (entry_bad,) = self.scalar("""
            SELECT count(*) FROM (
                SELECT race_date,boat_no FROM core.prediction_dataset_v1
                WHERE venue_code<>3 GROUP BY 1,2
                HAVING count(DISTINCT entry_course_prob_1_to_6)>1
                    OR count(DISTINCT entry_course_status)>1
            ) x
        """)
        (motor_bad,) = self.scalar("""
            SELECT count(*) FROM (
                SELECT race_date,motor_id FROM core.prediction_dataset_v1
                WHERE motor_id IS NOT NULL GROUP BY 1,2
                HAVING count(DISTINCT motor_a_base3)>1
                    OR count(DISTINCT motor_a_current)>1
                    OR count(DISTINCT motor_a_base3_status)>1
                    OR count(DISTINCT motor_a_current_status)>1
            ) x
        """)
        self.assertEqual((entry_bad, motor_bad), (0, 0))

    def test_missing_and_special_are_not_zero_labels(self):
        missing, bad = self.scalar("""
            SELECT count(*) FILTER (WHERE NOT label_eligible),
                   count(*) FILTER (WHERE NOT label_eligible AND
                       (label_p1 IS NOT NULL OR label_p2 IS NOT NULL))
            FROM core.prediction_dataset_v1
        """)
        self.assertGreater(missing, 0)
        self.assertEqual(bad, 0)

    def test_frozen_canonical_join_and_same_day_state(self):
        mismatch, rows = self.scalar("""
            SELECT count(*) FILTER (WHERE d.national_win_rate IS DISTINCT FROM e.national_win_rate
                OR d.national_win_rate_status IS DISTINCT FROM e.national_win_rate_status
                OR d.current_term_f_count IS DISTINCT FROM f.current_term_f_count
                OR d.current_term_f_count_status IS DISTINCT FROM f.current_term_f_count_status),
                   count(*)
            FROM core.prediction_dataset_v1 d
            JOIN core.race_entry e USING(race_id,boat_no)
            JOIN core.race_entry_current_term_f_count_v1 f USING(race_id,boat_no)
            WHERE d.race_date=DATE '2025-05-01'
        """)
        self.assertGreater(rows, 0)
        self.assertEqual(mismatch, 0)
        (bad,) = self.scalar("""
            SELECT count(*) FROM (
                SELECT race_date,player_id
                FROM core.prediction_dataset_v1
                GROUP BY race_date,player_id
                HAVING count(DISTINCT rating_overall)>1
                    OR count(DISTINCT f_suspension_state)>1
                    OR count(DISTINCT rating_short_50)>1
            ) x
        """)
        self.assertEqual(bad, 0)

    def test_f_suspension_matches_sealed_canonical_replay_population(self):
        # Frozen replay scope ends on 2026-09-18; 2026-09-19 is a later entry day.
        rows = self.scalar("""
            SELECT count(*),
                   count(*) FILTER (WHERE f_suspension_state='CLEAR'),
                   count(*) FILTER (WHERE f_suspension_state='ACTIVE_UNSERVED'),
                   count(*) FILTER (WHERE f_suspension_state='UNRESOLVED')
            FROM core.prediction_dataset_v1
            WHERE race_date<=DATE '2026-09-18'
        """)
        self.assertEqual(rows, (3252024, 2565857, 329543, 356624))


if __name__ == '__main__':
    unittest.main()

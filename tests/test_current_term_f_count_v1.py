"""Focused contract checks against the local canonical database."""
import unittest
from datetime import date

from scripts.db import target_connection


class CurrentTermFCountV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = target_connection()

    @classmethod
    def tearDownClass(cls):
        cls.connection.rollback()
        cls.connection.close()

    def scalar(self, query, args=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.fetchone()

    def test_f0_and_f2_plus_are_integers(self):
        count, low, high = self.scalar("""
            SELECT count(*), min(current_term_f_count), max(current_term_f_count)
            FROM core.race_entry_current_term_f_count_v1
            WHERE race_date = DATE '2025-05-01'
              AND current_term_f_count_status = 'VALID'
        """)
        self.assertGreater(count, 0)
        self.assertEqual(low, 0)
        self.assertEqual(high, 0)
        (f2_plus,) = self.scalar("""
            SELECT count(*) FROM core.race_entry
            WHERE f_count_current_term >= 2
        """)
        self.assertGreater(f2_plus, 0)
        self.assertEqual(self.scalar("""
            SELECT core.current_term_f_count_value_v1('2', 2)
        """), (2,))

    def test_f_is_applied_after_day_not_on_day(self):
        # A result is used only as independent test evidence, never by the view.
        count, violations = self.scalar("""
            WITH f AS (
                SELECT r.race_date AS f_day, e.player_id,
                       e.f_count_current_term AS on_day
                FROM core.race_result z
                JOIN core.race r USING (race_id)
                JOIN core.race_entry e USING (race_id, boat_no)
                WHERE z.start_timing_status = 'F'
                  AND r.race_date >= DATE '2025-01-01'
                  AND r.race_date < DATE '2026-01-01'
            ), follow AS (
                SELECT f.on_day, next_entry.f_count_current_term AS next_count
                FROM f JOIN LATERAL (
                    SELECT e.f_count_current_term
                    FROM core.race_entry e JOIN core.race r USING (race_id)
                    WHERE e.player_id = f.player_id
                      AND r.race_date > f.f_day
                      AND r.race_date < f.f_day + INTERVAL '30 days'
                      AND r.race_date < CASE
                          WHEN extract(month FROM f.f_day) BETWEEN 5 AND 10
                          THEN make_date(extract(year FROM f.f_day)::int, 11, 1)
                          WHEN extract(month FROM f.f_day) <= 4
                          THEN make_date(extract(year FROM f.f_day)::int, 5, 1)
                          ELSE make_date(extract(year FROM f.f_day)::int + 1, 5, 1)
                      END
                    ORDER BY r.race_date LIMIT 1
                ) next_entry ON true
            )
            SELECT count(*), count(*) FILTER (WHERE next_count <> on_day + 1)
            FROM follow
        """)
        self.assertGreater(count, 0)
        self.assertEqual(violations, 0)

    def test_same_day_later_race_does_not_receive_f(self):
        count, violations = self.scalar("""
            SELECT count(*),
                   count(*) FILTER (WHERE later.f_count_current_term
                                           IS DISTINCT FROM earlier.f_count_current_term)
            FROM core.race_result z
            JOIN core.race first_r ON first_r.race_id = z.race_id
            JOIN core.race_entry earlier ON earlier.race_id = z.race_id
                                        AND earlier.boat_no = z.boat_no
            JOIN core.race next_r ON next_r.race_date = first_r.race_date
                                 AND next_r.race_no > first_r.race_no
            JOIN core.race_entry later ON later.race_id = next_r.race_id
                                      AND later.player_id = earlier.player_id
            WHERE z.start_timing_status = 'F'
              AND first_r.race_date >= DATE '2025-01-01'
              AND first_r.race_date < DATE '2026-01-01'
        """)
        self.assertGreater(count, 0)
        self.assertEqual(violations, 0)

    def test_next_day_receives_f(self):
        count, violations = self.scalar("""
            WITH f AS (
                SELECT r.race_date AS f_day, e.player_id,
                       e.f_count_current_term AS on_day
                FROM core.race_result z
                JOIN core.race r USING (race_id)
                JOIN core.race_entry e USING (race_id, boat_no)
                WHERE z.start_timing_status = 'F'
                  AND r.race_date >= DATE '2025-01-01'
                  AND r.race_date < DATE '2026-01-01'
            )
            SELECT count(*), count(*) FILTER (
                WHERE later.f_count_current_term IS DISTINCT FROM f.on_day + 1)
            FROM f
            JOIN core.race next_r ON next_r.race_date = f.f_day + 1
            JOIN core.race_entry later ON later.race_id = next_r.race_id
                                      AND later.player_id = f.player_id
            WHERE core.current_term_start_v1(next_r.race_date)
                = core.current_term_start_v1(f.f_day)
        """)
        self.assertGreater(count, 0)
        self.assertEqual(violations, 0)

    def test_term_resets(self):
        rows = self.scalar("""
            SELECT core.current_term_start_v1(DATE '2025-04-30'),
                   core.current_term_start_v1(DATE '2025-05-01'),
                   core.current_term_start_v1(DATE '2025-10-31'),
                   core.current_term_start_v1(DATE '2025-11-01')
        """)
        self.assertEqual(rows, (date(2024, 11, 1), date(2025, 5, 1),
                                date(2025, 5, 1), date(2025, 11, 1)))
        days, nonzero = self.scalar("""
            SELECT count(DISTINCT race_date),
                   count(*) FILTER (WHERE f_count_current_term <> 0)
            FROM core.race_entry JOIN core.race USING (race_id)
            WHERE race_date >= DATE '2017-01-01'
              AND ((extract(month FROM race_date) = 5 AND extract(day FROM race_date) = 1)
                OR (extract(month FROM race_date) = 11 AND extract(day FROM race_date) = 1))
        """)
        self.assertGreater(days, 0)
        self.assertEqual(nonzero, 0)

    def test_missing_and_invalid_are_unresolved_not_f0(self):
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT core.current_term_f_count_value_v1(raw_value, parsed_value),
                       core.current_term_f_count_status_v1(raw_value, parsed_value)
                FROM (VALUES (NULL::text, NULL::integer), ('', NULL),
                             ('?', NULL), ('0', NULL), ('1', 0),
                             (' 02 ', 2)) AS inputs(raw_value, parsed_value)
            """)
            rows = cursor.fetchall()
        self.assertEqual(rows[:5], [(None, 'UNRESOLVED')] * 5)
        self.assertEqual(rows[5], (2, 'VALID'))


if __name__ == '__main__':
    unittest.main()

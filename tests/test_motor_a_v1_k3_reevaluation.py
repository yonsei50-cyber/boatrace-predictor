"""Small integration checks for the K3 replay around the frozen day boundary."""
from datetime import date
import unittest

from scripts.motor_a_v1 import MeetingDay
from scripts.reevaluate_motor_a_v1_k3 import DEV_END, replay


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.itersize = None

    def execute(self, sql, params):
        assert params == (date(2017, 1, 1), DEV_END)
        assert "brd_" + "r3" not in sql.lower()

    def __iter__(self):
        return iter(self.rows)

    def close(self):
        pass


class Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, name):
        assert name == "motor_a_k3_scan"
        return Cursor(self.rows)


def row(day, race_no, rate, *, has_result=True, generation=2023):
    return (day, 1, race_no, 1, 101, generation,
            date(generation, 1, 1), date(generation + 1, 1, 1), 7,
            "user-fixed-month-day-v1", "VALID", rate,
            "NUMERIC_VALID" if has_result else "NO_INDIVIDUAL_RESULT",
            1 if has_result else None, 1 if has_result else None, has_result)


class K3ReplayTests(unittest.TestCase):
    def test_same_day_isolation_completed_base_and_missing_result(self):
        d1, d2, d3 = (date(2023, 1, n) for n in (1, 2, 3))
        days = {
            (1, d1): MeetingDay("CERTIFIED", d1, d2, ()),
            (1, d2): MeetingDay("CERTIFIED", d1, d2, ()),
            (1, d3): MeetingDay("CERTIFIED", d3, d3, ()),
        }
        rows = [row(d1, 1, 8), row(d1, 2, 6), row(d2, 1, 4),
                row(d2, 2, None, has_result=False), row(d3, 1, 2)]
        result = replay(Connection(rows), DEV_END, days, (2023,))
        scored = result["series"][2023]
        self.assertEqual(list(scored["y"]), [2, 4, 6, 8])
        self.assertTrue(all(x != x for x in list(scored["current"])[:2]))
        self.assertEqual(scored["current"][2], 3)
        self.assertEqual(scored["base3"][3], 4)
        self.assertEqual(scored["current"][3] != scored["current"][3], True)
        self.assertEqual(result["counts"]["2023"]["eligible_residuals"], 4)
        self.assertEqual(result["counts"]["2023"]["excluded_RESULT_MISSING"], 1)

    def test_generation_isolation(self):
        d1, d2 = date(2023, 12, 31), date(2024, 1, 1)
        days = {(1, d1): MeetingDay("CERTIFIED", d1, d1, ()),
                (1, d2): MeetingDay("CERTIFIED", d2, d2, ())}
        rows = [row(d1, 1, 8), row(d2, 1, 2, generation=2024)]
        result = replay(Connection(rows), DEV_END, days, (2023, 2024))
        new_generation_base = result["series"][2024]["base3"][0]
        self.assertTrue(new_generation_base != new_generation_base)


if __name__ == "__main__":
    unittest.main()

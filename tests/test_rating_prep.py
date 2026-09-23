"""Small adversarial fixtures for the read-only Rating preparation counters."""
import unittest
from collections import Counter, defaultdict
from datetime import date

from scripts.audit_rating_prep import cohort_month, finish_race


def counters():
    return (defaultdict(Counter),
            defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
            defaultdict(Counter),
            defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
            defaultdict(Counter))


def boat(race_id, boat_no, finish_state='NUMERIC_VALID', course=None,
         finish=None, timing='NORMAL', raw=None):
    return (race_id,date(2023,1,2),boat_no,1000+boat_no,
            finish_state,finish,course,timing,raw,True)


class RatingPrepTest(unittest.TestCase):
    def test_strict_requires_six_normal_results_and_real_courses(self):
        counts,symbols,fl,courses,overall = counters()
        state = {1:'RESULT_RECORDS_PRESENT',2:'RESULT_RECORDS_PRESENT',
                 3:'RESULT_RECORDS_PRESENT'}
        complete = [boat(1,i,course=i,finish=i) for i in range(1,7)]
        finish_race(complete,state,counts,symbols,fl,courses,overall)
        self.assertEqual(counts[2023]['strict_races'],1)
        self.assertEqual(counts[2023]['course_strict_races'],1)
        self.assertEqual(courses[2023]['2']['exact_second'],1)
        self.assertEqual(courses[2023]['2']['first'],0)
        partial = [boat(2,i,course=i,finish=i) for i in range(1,6)]
        partial.append(boat(2,6,'UNRESOLVED_SPECIAL',None,None,'F','転'))
        finish_race(partial,state,counts,symbols,fl,courses,overall)
        self.assertEqual(counts[2023]['strict_races'],1)
        self.assertEqual(counts[2023]['numeric_valid_with_course_boats'],11)
        self.assertEqual(symbols[2023]['転']['sole_special_blocker_races'],1)
        self.assertEqual(fl[2023]['F:special_finish'],1)
        self.assertEqual(fl[2023]['other_numeric_valid'],5)
        no_canonical = [boat(3,i,course=i,finish=i) for i in range(1,7)]
        no_canonical[0] = (*no_canonical[0][:-1],False)
        finish_race(no_canonical,state,counts,symbols,fl,courses,overall)
        self.assertEqual(counts[2023]['strict_races'],1)
        self.assertEqual(counts[2023]['full_numeric_races'],2)

    def test_training_class_month_anchor(self):
        self.assertEqual(cohort_month(139),date(2026,11,1))
        self.assertEqual(cohort_month(138),date(2026,5,1))
        self.assertEqual(cohort_month(137),date(2025,11,1))
        self.assertEqual(cohort_month(120),date(2017,5,1))
        self.assertEqual(cohort_month(119),date(2016,11,1))
        self.assertIsNone(cohort_month(None))


if __name__ == '__main__':
    unittest.main()

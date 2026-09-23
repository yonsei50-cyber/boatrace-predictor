import copy
from datetime import date, timedelta
from decimal import Decimal
import unittest
from scripts.foundation import (MOTOR_STARTS, digest, integer, motor_generation,
                                women_only, results_before, identity_observation)
from scripts.normalize import normalize_result, normalize_sex


class RuleTests(unittest.TestCase):
    def test_all_venue_motor_boundaries(self):
        for venue,(month,day) in enumerate(MOTOR_STARTS,1):
            boundary=date(2026,month,day)
            with self.subTest(venue=venue):
                old=motor_generation(venue,boundary-timedelta(days=1))
                new=motor_generation(venue,boundary)
                self.assertEqual(old[0],2025)
                self.assertEqual(new[0],2026)
                self.assertEqual(old[2],new[1])
                self.assertEqual(new[1],boundary)

    def test_kiryu_january_uses_previous_generation(self):
        self.assertEqual(motor_generation(1,date(2026,1,10)),
                         (2025,date(2025,12,27),date(2026,12,27)))

    def test_women_requires_complete_six_boats(self):
        self.assertEqual(women_only(['FEMALE']*6,list(range(1,7))),(True,'CONFIRMED'))
        self.assertEqual(women_only(['FEMALE']*5,list(range(1,6))),(None,'UNKNOWN'))
        self.assertEqual(women_only(['FEMALE']*6,[1,2,3,4,5,5]),(None,'UNKNOWN'))
        self.assertEqual(women_only(['FEMALE']*5+[None],list(range(1,7))),(None,'UNKNOWN'))
        self.assertEqual(women_only(['MALE',None],[1,2]),(False,'CONFIRMED'))

    def test_missing_and_invalid_numbers_are_not_zero(self):
        for value in [None,'','   ','?','-1','０']:
            self.assertIsNone(integer(value))
        self.assertEqual(integer('0'),0)
        self.assertIsNone(integer('0',1,6))
        self.assertIsNone(integer('7',1,6))

    def test_sex_preserves_unknown(self):
        self.assertEqual(normalize_sex('1')[0],'MALE')
        self.assertEqual(normalize_sex('2')[0],'FEMALE')
        self.assertIsNone(normalize_sex('9')[0])
        self.assertIsNone(normalize_sex(None)[0])

    def test_later_ki_cannot_fill_older_missing_identity(self):
        later={'kaisai_nen':'2025','ki':'2','seibetsu_code':'2'}
        self.assertIsNone(identity_observation([later],'2024'))
        self.assertIsNone(identity_observation([later],'2025'))
        self.assertEqual(identity_observation([later],'2026'),later)

    def test_k3_finish_token_controls_result_status(self):
        result = normalize_result(dict(chakujun='F ',shinnyu_course='1',st='003'))
        self.assertEqual(result['result_status'],'F')
        self.assertEqual(result['start_timing_status'],'F')
        self.assertEqual(result['finish_raw'],'F ')
        self.assertIsNone(result['start_timing'])

    def test_k3_nonfinish_codes_stay_raw_and_unresolved(self):
        for token in ('K0','K1','S0','S1','S2','00'):
            with self.subTest(token=token):
                result = normalize_result(dict(chakujun=token,shinnyu_course='1',st='014'))
                self.assertEqual(result['finish_raw'],token)
                self.assertIsNone(result['finish_position'])
                self.assertEqual(result['result_status'],'UNRESOLVED')
                self.assertEqual(result['normalization_status'],'UNRESOLVED')

    def test_normal_st_and_raw_preservation(self):
        row=dict(shinnyu_course='2',chakujun='01',st='014')
        result=normalize_result(row)
        self.assertEqual(result['start_timing_raw'],'014')
        self.assertEqual(result['start_timing'],Decimal('0.14'))
        self.assertEqual(result['finish_raw'],'01')
        self.assertEqual(result['finish_position'],1)
        self.assertEqual(result['actual_course'],2)

    def test_f_l_raw_preserved_without_invented_numeric_st(self):
        for finish,st,status in [('F','002','F'),('L0','   ','L'),('L1','   ','L')]:
            with self.subTest(status=status):
                result=normalize_result(dict(shinnyu_course='4',chakujun=finish,st=st))
                self.assertEqual(result['result_status'],status)
                self.assertEqual(result['start_timing_status'],status)
                self.assertEqual(result['finish_raw'],finish)
                self.assertIsNone(result['result_symbol_raw'])
                self.assertEqual(result['start_timing_raw'],st)
                self.assertIsNone(result['start_timing'])
                self.assertIsNone(result['finish_position'])

    def test_actual_course_not_filled_from_boat(self):
        for course in [' ','0','9',None]:
            result=normalize_result(dict(shinnyu_course=course,chakujun='欠',st='   ',teiban='3'))
            self.assertIsNone(result['actual_course'])
            self.assertEqual(result['actual_course_raw'],course)

    def test_unknown_result_is_not_normal(self):
        result=normalize_result(dict(shinnyu_course='1',chakujun='?',st='abc'))
        self.assertIsNone(result['finish_position'])
        self.assertIsNone(result['start_timing'])
        self.assertNotEqual(result['normalization_status'],'NORMALIZED')

    def test_cutoff_excludes_d_and_future_without_mutation(self):
        snapshot={'race':[{'race_id':i,'race_date':d} for i,d in
                         [(1,'2026-08-31'),(2,'2026-09-01'),(3,'2026-09-02')]],
                  'race_result':[{'race_id':i,'boat_no':1} for i in (1,2,3)]}
        original=copy.deepcopy(snapshot)
        self.assertEqual(results_before(snapshot,date(2026,9,1)),[{'race_id':1,'boat_no':1}])
        self.assertEqual(snapshot,original)

    def test_hash_order_and_raw_whitespace(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
        self.assertNotEqual(digest({'raw':' '}),digest({'raw':''}))


if __name__=='__main__':
    unittest.main()

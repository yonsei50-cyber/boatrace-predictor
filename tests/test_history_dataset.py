"""Portable dataset identity and the 2017 / D-1 boundaries."""
from copy import deepcopy
from datetime import date
import unittest
from scripts.foundation import digest, results_before
from scripts.freeze_history import logical_snapshot, month_bounds


class HistoryDatasetTests(unittest.TestCase):
    def test_scope_rejects_2016(self):
        with self.assertRaises(ValueError):
            month_bounds('2016-12')

    def test_scope_start_and_year_boundary(self):
        self.assertEqual(month_bounds('2017-01'),(date(2017,1,1),date(2017,2,1)))
        self.assertEqual(month_bounds('2025-12'),(date(2025,12,1),date(2026,1,1)))

    def test_leap_month_boundary(self):
        self.assertEqual(month_bounds('2024-02'),(date(2024,2,1),date(2024,3,1)))

    def test_portable_snapshot_ignores_surrogate_identity(self):
        a={'race':[dict(race_id=1,race_date='2017-01-01',venue_code=3,race_no=1,source_record_id=10)],
           'motor':[dict(motor_id=2,venue_code=3,generation_start_year=2016,motor_no=5,source_record_id=11)],
           'race_entry':[dict(race_id=1,motor_id=2,player_id=4000,boat_no=1,source_record_id=11)],
           'race_result':[dict(race_id=1,boat_no=1,actual_course=None,finish_raw='転',source_record_id=12)]}
        b=deepcopy(a)
        for rows in b.values():
            for r in rows:
                if 'race_id' in r:r['race_id']+=100
                if 'motor_id' in r:r['motor_id']+=100
                r['source_record_id']+=100
        records={i:{'record_hash':str(i)*32} for i in (10,11,12)}
        moved={i+100:r for i,r in records.items()}
        self.assertEqual(digest(logical_snapshot(a,records)),digest(logical_snapshot(b,moved)))
        b['race_result'][0]['finish_raw']='欠'
        self.assertNotEqual(digest(logical_snapshot(a,records)),digest(logical_snapshot(b,moved)))

    def test_d_result_excluded_even_if_shard_contains_it(self):
        snapshot={'race':[{'race_id':1,'race_date':'2026-01-07'}, {'race_id':2,'race_date':'2026-01-08'}],
                  'race_result':[{'race_id':1,'boat_no':1},{'race_id':2,'boat_no':1}]}
        self.assertEqual(results_before(snapshot,date(2026,1,8)),[{'race_id':1,'boat_no':1}])


if __name__=='__main__':unittest.main()

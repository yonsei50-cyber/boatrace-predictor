"""C2/C3 immutable acquisition contract, always rolled back."""
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import patch
from scripts.db import target_connection
from scripts.import_environment_preinfo import preserve, run


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1', 'explicit local DB opt-in required')
class EnvironmentRawTests(unittest.TestCase):
    def setUp(self):
        self.conn = target_connection()
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.conn.rollback(); self.conn.close()

    def rows(self, table):
        row = dict(kaisai_nen='2098', kaisai_tsukihi='0101', kyoteijo_code='01', race_no='01')
        return [dict(row, teiban=str(b), tenji_st='016', tenji_kigo=' ') for b in range(1,7)] if table=='brd_c3' else [dict(row, hako='01')]

    def check_replay(self, table):
        rows = self.rows(table)
        batch, added = preserve(self.cur, table, '2098-01', rows, self.now)
        self.assertTrue(added)
        self.assertEqual(preserve(self.cur, table, '2098-01', rows, self.now), (batch,False))
        self.cur.execute('SELECT count(*),min(source_position),max(source_position) FROM raw.source_record WHERE source_batch_id=%s',(batch,))
        self.assertEqual(self.cur.fetchone(),(len(rows),1,len(rows)))
        changed = [dict(r) for r in rows]; changed[0]['changed']='yes'
        with self.assertRaises(RuntimeError):
            preserve(self.cur, table, '2098-01', changed, self.now)

    def test_c2_idempotency_and_changed_content(self): self.check_replay('brd_c2')
    def test_c3_idempotency_and_six_boats(self): self.check_replay('brd_c3')

    def test_empty_is_successful_explicit_batch(self):
        for table in ('brd_c2','brd_c3'):
            batch, added = preserve(self.cur, table, '2098-02', [], self.now)
            self.assertTrue(added)
            self.cur.execute('SELECT status,row_count FROM raw.source_batch WHERE source_batch_id=%s',(batch,))
            self.assertEqual(self.cur.fetchone(),('SOURCE_EMPTY',0))
            self.assertEqual(preserve(self.cur,table,'2098-02',[],self.now),(batch,False))

    def test_boundary_and_c4_rejected(self):
        for table in ('brd_c2','brd_c3'):
            with self.assertRaises(ValueError): preserve(self.cur,table,'2016-12',[],self.now)
            self.assertTrue(preserve(self.cur,table,'2017-01',[],self.now)[1])
        with self.assertRaises(ValueError): preserve(self.cur,'brd_c4','2098-01',[],self.now)

    def test_duplicate_order_and_identity_rejected(self):
        rows = self.rows('brd_c3')
        for bad in (rows+rows[:1],list(reversed(rows)),[dict(rows[0],teiban='7')], [dict(rows[0],kaisai_tsukihi='0132')]):
            with self.assertRaises(ValueError): preserve(self.cur,'brd_c3','2098-01',bad,self.now)

    def test_failed_acquisition_does_not_call_preserve(self):
        with patch('scripts.import_environment_preinfo.source_connection',side_effect=RuntimeError('injected acquisition failure')), \
             patch('scripts.import_environment_preinfo.preserve') as mocked:
            with self.assertRaises(RuntimeError): run()
            mocked.assert_not_called()

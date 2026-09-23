"""Focused gates and opt-in DB checks for the K3 result migration."""

from datetime import date
import os
from unittest import TestCase, skipUnless
from unittest.mock import patch

from scripts.db import target_connection
from scripts.import_history import VERSION
from scripts.migrate_k3_results import apply, stage_month
from scripts.result_dataset_version import record_k3_result_dataset_version


class MigrationGateTests(TestCase):
    def test_failed_direct_lookup_gate_never_opens_target(self):
        with patch('scripts.migrate_k3_results.target_connection') as connect:
            with self.assertRaisesRegex(RuntimeError,'direct K3 lookup gate'):
                apply({'candidate_races':60,'candidate_boats':360,
                       'k3_absent':59,'k3_present_probe_bug':1,'races':[]},
                      {'status':'RAW_COMPLETE','raw_rows':1,'source_rows':1},{})
            connect.assert_not_called()


@skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
            'explicit local DB test opt-in required')
class MigrationDatabaseTests(TestCase):
    def test_raw_stage_and_version_metadata(self):
        conn=target_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='0'")
                cur.execute('''CREATE TEMP TABLE k3_stage (
                    race_date date NOT NULL,venue_code smallint NOT NULL,
                    race_no smallint NOT NULL,boat_no smallint NOT NULL,
                    player_id integer NOT NULL,actual_course_raw text,
                    actual_course smallint,finish_raw text,finish_position smallint,
                    result_status text NOT NULL,result_symbol_raw text,
                    start_timing_raw text,start_timing numeric(6,3),
                    start_timing_status text NOT NULL,normalization_status text NOT NULL,
                    normalization_version text NOT NULL,source_record_id bigint NOT NULL,
                    PRIMARY KEY(race_date,venue_code,race_no,boat_no)) ON COMMIT DROP''')
                staged=stage_month(cur,'2017-01')
                cur.execute("""SELECT row_count FROM raw.source_batch WHERE source_table='brd_k3'
                    AND extraction_condition->>'version'=%s
                    AND extraction_condition->>'partition'='2017-01'""",(VERSION,))
                self.assertEqual(staged,cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM k3_stage WHERE result_symbol_raw IS NOT NULL OR (start_timing_status IN ('F','L') AND start_timing IS NOT NULL)")
                self.assertEqual(cur.fetchone()[0],0)
                cur.execute('SELECT date_end,version_id FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1')
                end,version_id=cur.fetchone()
                recorded=record_k3_result_dataset_version(cur,date_start=date(2017,1,1),
                    date_end=end,extraction_version=VERSION)
                self.assertEqual(recorded['version_id'],version_id)
                self.assertFalse(recorded['inserted'])
        finally:
            conn.rollback();conn.close()

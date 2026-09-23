"""Phase 3B result-state views over immutable R2/K3 evidence."""
from datetime import date, datetime, timezone
from pathlib import Path
import os
import unittest

from scripts.db import target_connection
from scripts.foundation import digest, results_before
from scripts.import_result_evidence import preserve_r2
from scripts.import_sample import RACE_KEY, insert
from scripts.normalize import normalize_result


MIGRATION = Path(__file__).resolve().parents[1] / 'sql/migrations/0004_result_states.sql'


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                     'explicit local DB test opt-in required')
class ResultStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = target_connection()
        cls.cur = cls.conn.cursor()
        cls.cur.execute("SET LOCAL statement_timeout='0'")
        cls.cur.execute('SELECT to_jsonb(z) FROM core.race_result z ORDER BY race_id,boat_no LIMIT 1')
        cls.existing_result = cls.cur.fetchone()[0]
        cls.cur.execute('SELECT canonical_content_hash FROM core.dataset_version ORDER BY dataset_version_id')
        cls.dataset_hashes = cls.cur.fetchall()
        cls.cur.execute('DROP VIEW IF EXISTS core.boat_finish_state, '
                        'core.race_result_state, core.result_source_evidence CASCADE')
        cls.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        cls._build_fixtures()
        fixture_races = list(cls.races.values())
        cls.cur.execute('CREATE TEMP TABLE result_state_fixture ON COMMIT DROP AS '
                        'SELECT * FROM core.race_result_state WHERE race_id=ANY(%s)',
                        (fixture_races,))
        cls.cur.execute('CREATE TEMP TABLE finish_state_fixture ON COMMIT DROP AS '
                        'SELECT * FROM core.boat_finish_state WHERE race_id=ANY(%s)',
                        (fixture_races,))
        cls.cur.execute('CREATE UNIQUE INDEX ON result_state_fixture(race_id)')
        cls.cur.execute('CREATE UNIQUE INDEX ON finish_state_fixture(race_id,boat_no)')

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    @classmethod
    def _batch(cls, table, rows, version):
        batch = insert(cls.cur, 'raw.source_batch', dict(
            source_name='TEST', source_type='TEST_FIXTURE',
            source_locator='test.'+table, extraction_condition={'version':version},
            source_database='test', source_schema='public', source_table=table,
            retrieved_at=None, extracted_at=datetime(2099,1,1,tzinfo=timezone.utc),
            content_hash=digest(rows), row_count=len(rows), metadata={'test':True},
            status='TEST_FIXTURE'), 'source_batch_id')
        ids = []
        keys = RACE_KEY + (('teiban',) if table in ('brd_l3','brd_k3') else ())
        for position,row in enumerate(rows,1):
            ids.append(insert(cls.cur, 'raw.source_record', dict(
                source_batch_id=batch, source_record_key={k:row[k] for k in keys},
                source_position=position, raw_payload=row, record_hash=digest(row),
                interpretation_status='TEST_FIXTURE'), 'source_record_id'))
        return batch,ids

    @classmethod
    def _build_fixtures(cls):
        cls.cur.execute('SELECT player_id FROM core.player ORDER BY player_id LIMIT 6')
        players = [r[0] for r in cls.cur.fetchall()]
        if len(players) != 6:
            raise RuntimeError('six existing players required for result-state DB fixtures')
        cls.cur.execute('SELECT to_jsonb(r) FROM core.race r ORDER BY race_id LIMIT 1')
        race_template = cls.cur.fetchone()[0]
        cls.cur.execute("""SELECT s.source_record_id FROM raw.source_record s
            JOIN raw.source_batch b USING(source_batch_id)
            WHERE b.source_table='brd_l2' ORDER BY s.source_record_id LIMIT 1""")
        l2_source = cls.cur.fetchone()[0]

        scenarios = {
            'normal': (date(2099,1,1), ['01','02','03','04','05','06']),
            'event': (date(2099,1,2), [' ',' ',' ',' ',' ',' ']),
            'payout': (date(2099,1,3), [' ',' ',' ',' ',' ',' ']),
            'unresolved': (date(2099,1,4), [' ',' ',' ',' ',' ',' ']),
            'duplicate': (date(2099,1,5), ['01','02','02','04','05','06']),
            'special': (date(2099,1,6), ['F','L0','転','欠','落','失']),
            'no_k3': (date(2099,1,7), None),
            'partial': (date(2099,1,8), ['01','02']),
            'r2_conflict': (date(2099,1,9), [' ',' ',' ',' ',' ',' ']),
            'k3_conflict': (date(2099,1,10), ['01','02','03','04','05','06']),
        }
        l3_rows = []
        k3_rows = []
        for name,(day,finishes) in scenarios.items():
            for boat,player in enumerate(players,1):
                common = dict(kaisai_nen='2099', kaisai_tsukihi=day.strftime('%m%d'),
                              kyoteijo_code='01', race_no='01', teiban=str(boat))
                l3_rows.append(dict(common, toroku_bango=str(player).zfill(4),
                                    zenkoku_ritsu_1='0500'))
                if finishes is not None and boat <= len(finishes):
                    finish = finishes[boat-1]
                    k3_rows.append(dict(common, toroku_bango=str(player).zfill(4),
                                        chakujun=finish,
                                        st='002' if finish=='F' else ('   ' if finish in ('L0','L1') else '014'),
                                        shinnyu_course=str(boat), data_kubun='0'))
        _,l3_ids = cls._batch('brd_l3',l3_rows,'phase3b-test-l3')
        _,k3_ids = cls._batch('brd_k3',k3_rows,'phase3b-test-k3')
        l3_by_key = {tuple(row[k] for k in RACE_KEY+('teiban',)):rid
                     for row,rid in zip(l3_rows,l3_ids)}
        k3_by_key = {tuple(row[k] for k in RACE_KEY+('teiban',)):(row,rid)
                     for row,rid in zip(k3_rows,k3_ids)}

        cls.races = {}
        for name,(day,_) in scenarios.items():
            race = {k:v for k,v in race_template.items() if k!='race_id'}
            race.update(race_date=day,venue_code=1,race_no=1,source_record_id=l2_source,
                        race_status='TEST_FIXTURE')
            race_id = insert(cls.cur,'core.race',race,'race_id')
            cls.races[name] = race_id
            for boat,player in enumerate(players,1):
                raw_key=('2099',day.strftime('%m%d'),'01','01',str(boat))
                insert(cls.cur,'core.race_entry',dict(
                    race_id=race_id,boat_no=boat,venue_code=1,player_id=player,
                    motor_id=None,motor_no_raw=None,f_count_current_term_raw=None,
                    f_count_current_term=None,l_count_current_term_raw=None,
                    source_record_id=l3_by_key[raw_key],provenance={'test':True}))
                if name == 'special':
                    raw,source = k3_by_key[raw_key]
                    insert(cls.cur,'core.race_result',dict(
                        race_id=race_id,boat_no=boat,**normalize_result(raw),
                        source_record_id=source,provenance={'test':True}))

        r2_rows = []
        for name,code,payout in (
                ('event','9','000'),('payout','0','123'),('unresolved','0','000'),
                ('r2_conflict','9','000')):
            day = scenarios[name][0]
            r2_rows.append(dict(kaisai_nen='2099',kaisai_tsukihi=day.strftime('%m%d'),
                                kyoteijo_code='01',race_no='01',data_kubun=code,
                                haraimodoshi_sanrentan_1a=payout))
        batch,added = preserve_r2(cls.cur,'2099-01',r2_rows,datetime(2099,1,1,tzinfo=timezone.utc))
        cls.r2_batch = batch
        cls.assert_preserved_new = added
        same_batch,added_again = preserve_r2(
            cls.cur,'2099-01',r2_rows,datetime(2099,1,2,tzinfo=timezone.utc))
        cls.r2_replay = (same_batch,added_again)

        conflict = dict(r2_rows[-1],data_kubun='0',haraimodoshi_sanrentan_1a='123')
        cls._batch('brd_r2',[conflict],'phase3b-test-conflicting-revision')
        k3_conflict = dict(k3_rows[-6],chakujun='02')
        cls._batch('brd_k3',[k3_conflict],'phase3b-test-conflicting-k3-revision')
        cls.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cls.cur.execute('SET CONSTRAINTS ALL DEFERRED')

    def state(self, name):
        self.cur.execute('SELECT result_state FROM result_state_fixture WHERE race_id=%s',
                         (self.races[name],))
        return self.cur.fetchone()[0]

    def finishes(self, name):
        self.cur.execute('SELECT boat_no,finish_raw,finish_position,finish_state '
                         'FROM finish_state_fixture WHERE race_id=%s ORDER BY boat_no',
                         (self.races[name],))
        return self.cur.fetchall()

    def test_normal_six_numeric_finishes(self):
        self.assertEqual(self.state('normal'),'RESULT_RECORDS_PRESENT')
        rows = self.finishes('normal')
        self.assertEqual([r[2] for r in rows],list(range(1,7)))
        self.assertEqual({r[3] for r in rows},{'NUMERIC_VALID'})

    def test_blank_k3_r2_event_and_payout_evidence(self):
        self.assertEqual(self.state('event'),'R2_EVENT_STATE_PRESENT')
        self.assertEqual(self.state('payout'),'R2_PAYOUT_PRESENT_K3_MISSING')
        self.assertEqual({r[3] for r in self.finishes('event')},{'NO_INDIVIDUAL_RESULT'})

    def test_fully_unresolved_and_no_k3(self):
        self.assertEqual(self.state('unresolved'),'UNRESOLVED')
        self.assertEqual(self.state('no_k3'),'SOURCE_INCOMPLETE')
        self.assertEqual({r[3] for r in self.finishes('no_k3')},{'NO_INDIVIDUAL_RESULT'})

    def test_partial_k3_is_source_incomplete(self):
        self.assertEqual(self.state('partial'),'SOURCE_INCOMPLETE')
        states = [r[3] for r in self.finishes('partial')]
        self.assertEqual(states.count('NUMERIC_VALID'),2)
        self.assertEqual(states.count('NO_INDIVIDUAL_RESULT'),4)

    def test_numeric_duplicates_keep_original_value(self):
        self.assertEqual(self.state('duplicate'),'RESULT_RECORDS_PRESENT')
        duplicate = [r for r in self.finishes('duplicate') if r[2]==2]
        self.assertEqual([(r[1],r[3]) for r in duplicate],
                         [('02','NUMERIC_DUPLICATE_UNRESOLVED')]*2)
        self.assertEqual({r[3] for r in self.finishes('duplicate') if r[2]!=2},
                         {'NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED'})

    def test_k3_conflict_invalidates_race_without_selecting_a_revision(self):
        self.assertEqual(self.state('k3_conflict'),'UNRESOLVED')
        self.assertEqual({r[3] for r in self.finishes('k3_conflict')},
                         {'UNRESOLVED_SOURCE_CONFLICT'})
        self.cur.execute('SELECT finish_raw,finish_raw_values,k3_distinct_revision_count '
                         'FROM finish_state_fixture WHERE race_id=%s AND boat_no=1',
                         (self.races['k3_conflict'],))
        self.assertEqual(self.cur.fetchone(),(None,['01','02'],2))

    def test_special_finish_and_f_l_independence(self):
        self.assertEqual(self.state('special'),'RESULT_RECORDS_PRESENT')
        self.assertEqual({r[3] for r in self.finishes('special')},{'UNRESOLVED_SPECIAL'})
        self.cur.execute('SELECT boat_no,finish_state,start_symbol_raw,start_timing_status,start_timing '
                         'FROM finish_state_fixture WHERE race_id=%s AND boat_no IN (1,2) ORDER BY boat_no',
                         (self.races['special'],))
        self.assertEqual(self.cur.fetchall(),[
            (1,'UNRESOLVED_SPECIAL',None,'F',None),
            (2,'UNRESOLVED_SPECIAL',None,'L',None)])

    def test_r2_lineage_idempotency_and_hash(self):
        self.assertTrue(self.assert_preserved_new)
        self.assertEqual(self.r2_replay,(self.r2_batch,False))
        self.cur.execute("""SELECT e.source_record_id,e.source_batch_id,e.record_hash,e.source_batch_hash,
            e.raw_payload FROM core.result_source_evidence e
            WHERE e.race_id=%s AND e.evidence_type='brd_r2'""",(self.races['event'],))
        source,batch,record_hash,batch_hash,payload = self.cur.fetchone()
        self.assertIsNotNone(source)
        self.assertEqual(batch,self.r2_batch)
        self.assertEqual(record_hash,digest(payload))
        self.cur.execute('SELECT content_hash FROM raw.source_batch WHERE source_batch_id=%s',(batch,))
        self.assertEqual(batch_hash,self.cur.fetchone()[0])

    def test_r2_scope_before_2017_rejected_without_batch(self):
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        before = self.cur.fetchone()[0]
        with self.assertRaises(ValueError):
            preserve_r2(self.cur,'2016-12',[],datetime(2099,1,1,tzinfo=timezone.utc))
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        self.assertEqual(self.cur.fetchone()[0],before)

    def test_r2_duplicate_source_key_rejected_without_batch(self):
        row = dict(kaisai_nen='2099',kaisai_tsukihi='0201',kyoteijo_code='01',
                   race_no='01',data_kubun='0',haraimodoshi_sanrentan_1a='000')
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        before = self.cur.fetchone()[0]
        with self.assertRaises(ValueError):
            preserve_r2(self.cur,'2099-02',[row,dict(row)],
                        datetime(2099,1,1,tzinfo=timezone.utc))
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        self.assertEqual(self.cur.fetchone()[0],before)

    def test_r2_changed_partition_rejected_without_new_batch(self):
        changed = dict(kaisai_nen='2099',kaisai_tsukihi='0102',kyoteijo_code='01',
                       race_no='01',data_kubun='0',haraimodoshi_sanrentan_1a='123')
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        before = self.cur.fetchone()[0]
        with self.assertRaises(RuntimeError):
            preserve_r2(self.cur,'2099-01',[changed],
                        datetime(2099,1,1,tzinfo=timezone.utc))
        self.cur.execute("SELECT count(*) FROM raw.source_batch WHERE source_table='brd_r2'")
        self.assertEqual(self.cur.fetchone()[0],before)

    def test_conflicting_r2_revision_not_silently_selected(self):
        self.cur.execute('SELECT result_state,r2_source_record_count,r2_distinct_revision_count,'
                         'r2_revision_conflict,array_length(r2_source_record_ids,1) '
                         'FROM result_state_fixture WHERE race_id=%s',(self.races['r2_conflict'],))
        self.assertEqual(self.cur.fetchone(),('UNRESOLVED',2,2,True,2))

    def test_migration_reapply_and_existing_state_preserved(self):
        self.cur.execute("SELECT c.relname,pg_get_viewdef(c.oid) FROM pg_class c "
                         "JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname='core' AND c.relname IN "
                         "('result_source_evidence','race_result_state','boat_finish_state') ORDER BY 1")
        before = self.cur.fetchall()
        self.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        self.cur.execute("SELECT c.relname,pg_get_viewdef(c.oid) FROM pg_class c "
                         "JOIN pg_namespace n ON n.oid=c.relnamespace "
                         "WHERE n.nspname='core' AND c.relname IN "
                         "('result_source_evidence','race_result_state','boat_finish_state') ORDER BY 1")
        self.assertEqual(self.cur.fetchall(),before)
        self.cur.execute('SELECT to_jsonb(z) FROM core.race_result z ORDER BY race_id,boat_no LIMIT 1')
        self.assertEqual(self.cur.fetchone()[0],self.existing_result)
        self.cur.execute('SELECT canonical_content_hash FROM core.dataset_version ORDER BY dataset_version_id')
        self.assertEqual(self.cur.fetchall(),self.dataset_hashes)

    def test_d_minus_one_contract_unchanged(self):
        snapshot={'race':[{'race_id':1,'race_date':'2099-01-01'},
                          {'race_id':2,'race_date':'2099-01-02'}],
                  'race_result':[{'race_id':1},{'race_id':2}]}
        self.assertEqual(results_before(snapshot,date(2099,1,2)),[{'race_id':1}])
        self.cur.execute('SELECT count(*) FROM core.dataset_version '
                         'WHERE results_cutoff_date<>effective_date-1')
        self.assertEqual(self.cur.fetchone()[0],0)


if __name__=='__main__':
    unittest.main()

"""Database behavior against the disposable real-source sample; all writes rollback."""
from datetime import date
from decimal import Decimal
import os
import unittest
import psycopg2
from scripts.db import target_connection
from scripts.foundation import digest, results_before
from scripts.freeze_history import snapshot_month
from scripts.import_sample import insert, snapshot_before
from scripts.migrate import schema_signature
from scripts.national_win_rate import MIGRATION, audit, protected_state, raw_coverage, upgrade


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1', 'explicit local DB test opt-in required')
class NationalRateTests(unittest.TestCase):
    def setUp(self):
        self.conn = target_connection()
        self.cur = self.conn.cursor()
        self.cur.execute('SELECT race_id,boat_no,source_record_id FROM core.race_entry ORDER BY 1,2 LIMIT 1')
        self.race, self.boat, self.source = self.cur.fetchone()

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def parse(self, raw):
        self.cur.execute('SELECT core.l3_national_rate_value_v1(%s),core.l3_national_rate_status_v1(%s)', (raw, raw))
        return self.cur.fetchone()

    def reject(self, query, params=()):
        self.cur.execute('SAVEPOINT rejected_rate')
        with self.assertRaises(psycopg2.Error):
            self.cur.execute(query, params)
        self.cur.execute('ROLLBACK TO SAVEPOINT rejected_rate')

    def new_source(self, raw, overrides=None):
        self.cur.execute('SELECT s.raw_payload,to_jsonb(b) FROM raw.source_record s '
                         'JOIN raw.source_batch b USING(source_batch_id) WHERE source_record_id=%s', (self.source,))
        payload,batch = self.cur.fetchone()
        payload['zenkoku_ritsu_1'] = raw
        payload.update(overrides or {})
        del batch['source_batch_id']
        batch.update(row_count=1, content_hash=digest([payload]))
        batch_id = insert(self.cur, 'raw.source_batch', batch, 'source_batch_id')
        return insert(self.cur, 'raw.source_record', dict(source_batch_id=batch_id,
            source_record_key={k:payload[k] for k in ('kaisai_nen','kaisai_tsukihi','kyoteijo_code','race_no','teiban')},
            source_position=1, raw_payload=payload, record_hash=digest(payload),
            interpretation_status='TEST_FIXTURE'), 'source_record_id')

    def adopt(self, raw):
        record_id = self.new_source(raw)
        self.cur.execute('UPDATE core.race_entry SET source_record_id=%s WHERE race_id=%s AND boat_no=%s',
                         (record_id,self.race,self.boat))
        self.cur.execute('SELECT national_win_rate_raw,national_win_rate,national_win_rate_status '
                         'FROM core.race_entry WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        return self.cur.fetchone()

    def test_normal_parse(self):
        self.assertEqual(self.parse('0654'), (Decimal('6.54'),'VALID'))
        self.assertEqual(self.parse('0580'), (Decimal('5.80'),'VALID'))

    def test_raw_retained(self):
        self.assertEqual(self.adopt('0654'), ('0654',Decimal('6.54'),'VALID'))

    def test_zero_unresolved_not_imputed(self):
        self.assertEqual(self.adopt('0000'), ('0000',None,'UNRESOLVED'))

    def test_invalid_preserved(self):
        for raw in ('6.54','065','06540',' 654','-654','０６５４','NaN'):
            with self.subTest(raw=raw):
                self.assertEqual(self.adopt(raw), (raw,None,'INVALID'))

    def test_missing_distinct(self):
        for raw in (None,'','    '):
            self.assertEqual(self.adopt(raw), (raw,None,'MISSING'))

    def test_cannot_forge_raw_or_numeric(self):
        self.adopt('0654')
        self.cur.execute("UPDATE core.race_entry SET national_win_rate_raw='9999' WHERE race_id=%s AND boat_no=%s",
                         (self.race,self.boat))
        self.cur.execute('SELECT national_win_rate_raw FROM core.race_entry WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        self.assertEqual(self.cur.fetchone()[0], '0654')
        self.reject('UPDATE core.race_entry SET national_win_rate=0 WHERE race_id=%s', (self.race,))

    def test_lineage(self):
        report = audit(self.cur)
        for k in ('raw_mismatch','value_mismatch','status_mismatch','key_mismatch','registration_mismatch','missing_lineage','duplicates'):
            self.assertEqual(report['lineage'][k], 0)
        self.cur.execute('SELECT source_record_id,source_batch_id,source_record_key,information_kind,'
                         'historical_availability_status FROM core.race_entry_national_win_rate '
                         'WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        source,batch,key,kind,availability = self.cur.fetchone()
        self.assertEqual(source,self.source)
        self.assertIsNotNone(batch)
        self.assertEqual(key['teiban'],str(self.boat))
        self.assertEqual((kind,availability),('RACE_ENTRY_INFORMATION','NOT_VERIFIED'))
        coverage = raw_coverage(self.cur)
        self.assertEqual(coverage['distinct_entry_keys'],report['overall']['total_entries'])
        self.assertEqual(coverage['raw_without_matching_canonical'],0)

    def test_race_boat_source_mismatch_rejected(self):
        self.cur.execute('SELECT source_record_id FROM core.race_entry WHERE race_id=%s AND boat_no<>%s LIMIT 1', (self.race,self.boat))
        other = self.cur.fetchone()[0]
        self.reject('UPDATE core.race_entry SET source_record_id=%s WHERE race_id=%s AND boat_no=%s', (other,self.race,self.boat))

    def test_registration_mismatch_rejected(self):
        self.cur.execute('SELECT player_id FROM core.player WHERE player_id<>(SELECT player_id FROM core.race_entry '
                         'WHERE race_id=%s AND boat_no=%s) LIMIT 1', (self.race,self.boat))
        self.reject('UPDATE core.race_entry SET player_id=%s WHERE race_id=%s AND boat_no=%s', (self.cur.fetchone()[0],self.race,self.boat))

    def test_duplicate_rejected(self):
        self.reject('UPDATE core.race_entry SET boat_no=%s WHERE race_id=%s AND boat_no<>%s', (self.boat,self.race,self.boat))

    def test_parent_identity_correction_rejected(self):
        self.reject('UPDATE core.race SET race_date=race_date+1 WHERE race_id=%s', (self.race,))

    def test_migration_reapply_and_idempotency(self):
        before = schema_signature(self.cur)
        protected = protected_state(self.cur)
        self.assertEqual(upgrade(self.cur),0)
        self.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        self.assertEqual(schema_signature(self.cur), before)
        self.assertEqual(upgrade(self.cur),0)
        self.assertEqual(protected_state(self.cur),protected)

    def test_replay_from_raw(self):
        expected = self.adopt('0654')
        self.cur.execute('UPDATE core.race_entry SET source_record_id=source_record_id WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        self.cur.execute('SELECT national_win_rate_raw,national_win_rate,national_win_rate_status FROM core.race_entry '
                         'WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        self.assertEqual(self.cur.fetchone(), expected)

    def test_upgrade_populated_legacy_schema(self):
        before = protected_state(self.cur)
        self.cur.execute('SELECT count(*) FROM core.race_entry WHERE national_win_rate_raw IS NOT NULL')
        expected = self.cur.fetchone()[0]
        self.cur.execute('ALTER TABLE core.race_entry DROP COLUMN national_win_rate_raw CASCADE, '
                         'DROP COLUMN IF EXISTS national_win_rate CASCADE, '
                         'DROP COLUMN IF EXISTS national_win_rate_status CASCADE')
        self.assertEqual(upgrade(self.cur),expected)
        self.assertEqual(audit(self.cur)['lineage']['raw_mismatch'],0)
        self.assertEqual(protected_state(self.cur),before)

    def test_2017_and_d_minus_one(self):
        # A new entry attribute cannot relax the unchanged date-only result cutoff.
        snapshot = {'race':[{'race_id':1,'race_date':'2016-12-31'}, {'race_id':2,'race_date':'2017-01-01'}],
                    'race_entry':[{'race_id':2,'national_win_rate':'6.54'}],
                    'race_result':[{'race_id':1},{'race_id':2}]}
        self.assertEqual(results_before(snapshot,date(2017,1,1)),[{'race_id':1}])
        self.assertEqual(len(results_before(snapshot,date(2017,1,2))),2)
        self.cur.execute('SELECT min(race_date) FROM core.race')
        first = self.cur.fetchone()[0]
        self.assertEqual(snapshot_before(self.cur,first)['race_entry'],[])
        self.cur.execute('SELECT count(*) FROM core.dataset_version WHERE results_cutoff_date<>effective_date-1')
        self.assertEqual(self.cur.fetchone()[0],0)

    def test_result_snapshot_contract_unchanged(self):
        for snapshot in (snapshot_before(self.cur,date(2100,1,1)),snapshot_month(self.cur,'2026-09')):
            self.assertTrue(snapshot['race_entry'])
            self.assertTrue(all(not any(k.startswith('national_win_rate') for k in e) for e in snapshot['race_entry']))

    def test_upgrade_and_audit_actual_2017_boundary(self):
        self.cur.execute('SELECT to_jsonb(r) FROM core.race r WHERE race_id=%s', (self.race,))
        race_template = self.cur.fetchone()[0]
        self.cur.execute('SELECT to_jsonb(e) FROM core.race_entry e WHERE race_id=%s AND boat_no=%s', (self.race,self.boat))
        entry_template = self.cur.fetchone()[0]
        added = []
        for day in ('2016-12-31','2017-01-01'):
            race = {k:v for k,v in race_template.items() if k!='race_id'}
            race['race_date'] = day
            race_id = insert(self.cur,'core.race',race,'race_id')
            entry = {k:v for k,v in entry_template.items() if not k.startswith('national_win_rate')}
            entry.update(race_id=race_id,motor_id=None,
                         source_record_id=self.new_source('0654',{'kaisai_nen':day[:4],'kaisai_tsukihi':day[5:7]+day[8:10]}))
            insert(self.cur,'core.race_entry',entry)
            added.append(race_id)
        # Simulate legacy unpopulated columns in this rollback-only disposable fixture.
        self.cur.execute('ALTER TABLE core.race_entry DISABLE TRIGGER entry_l3_national_rate')
        self.cur.execute('UPDATE core.race_entry SET national_win_rate_raw=NULL WHERE race_id=ANY(%s)', (added,))
        self.cur.execute('ALTER TABLE core.race_entry ENABLE TRIGGER entry_l3_national_rate')
        self.assertEqual(upgrade(self.cur),1)
        self.cur.execute('SELECT national_win_rate_raw FROM core.race_entry WHERE race_id=ANY(%s) ORDER BY race_id', (added,))
        self.assertEqual(self.cur.fetchall(),[(None,),('0654',)])
        report = audit(self.cur)
        self.assertEqual(report['lineage']['min_date'],date(2017,1,1))
        self.assertEqual(report['lineage']['raw_mismatch'],0)

"""Opt-in real sample tests: BOATRACE_TEST_DB=1. Target changes always rollback."""
from datetime import date
import os
import unittest
import psycopg2
from scripts.db import source_connection, target_connection
from scripts.foundation import digest, integer, motor_generation, results_before, women_only
from scripts.import_sample import extract_source, snapshot_before, insert
from scripts.normalize import normalize_result, normalize_sex


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1','explicit local DB test opt-in required')
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn=target_connection()
        self.cur=self.conn.cursor()
        self.cur.execute('SELECT min(race_id) FROM core.race')
        self.first_race=self.cur.fetchone()[0]

    def tearDown(self):
        self.conn.rollback()
        self.conn.close()

    def reject(self, query, params=()):
        self.cur.execute('SAVEPOINT rejected_write')
        with self.assertRaises(psycopg2.Error):
            self.cur.execute(query,params)
        self.cur.execute('ROLLBACK TO SAVEPOINT rejected_write')
        self.cur.execute('RELEASE SAVEPOINT rejected_write')

    def test_nine_tables_and_non_superuser(self):
        self.cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('raw','core') AND table_type='BASE TABLE'")
        self.assertEqual(self.cur.fetchone()[0],9)
        self.cur.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')
        self.assertFalse(self.cur.fetchone()[0])

    def test_natural_and_entry_keys_reject_duplicates(self):
        self.cur.execute('SELECT race_id,race_date,venue_code,race_no FROM core.race ORDER BY race_id LIMIT 2')
        first,second=self.cur.fetchall()
        self.reject('UPDATE core.race SET race_date=%s,venue_code=%s,race_no=%s WHERE race_id=%s',(*first[1:],second[0]))
        self.reject('UPDATE core.race_entry SET boat_no=1 WHERE race_id=%s AND boat_no=2',(first[0],))
        self.cur.execute('SELECT race_id,count(*),count(DISTINCT boat_no) FROM core.race_entry GROUP BY race_id')
        for _,count,distinct in self.cur:
            self.assertEqual((count,distinct),(6,6))

    def test_boat_bounds_and_player_fk(self):
        self.reject('UPDATE core.race_entry SET boat_no=0 WHERE race_id=%s AND boat_no=1',(self.first_race,))
        self.reject('UPDATE core.race_entry SET boat_no=7 WHERE race_id=%s AND boat_no=1',(self.first_race,))
        self.reject('UPDATE core.race_entry SET player_id=-1 WHERE race_id=%s AND boat_no=1',(self.first_race,))

    def test_motor_period_parent_corrections_rejected(self):
        self.reject("UPDATE core.race SET race_date=race_date+interval '10 years' WHERE race_id=%s",(self.first_race,))
        self.cur.execute('SELECT motor_id FROM core.race_entry WHERE race_id=%s AND boat_no=1',(self.first_race,))
        motor=self.cur.fetchone()[0]
        self.reject("UPDATE core.motor SET generation_end_date=generation_start_date+1 WHERE motor_id=%s",(motor,))

    def test_motor_identity_venue_and_period(self):
        self.cur.execute('''SELECT r.venue_code,r.race_date,m.generation_start_year,
            m.generation_start_date,m.generation_end_date FROM core.race_entry e
            JOIN core.race r USING(race_id) JOIN core.motor m USING(motor_id)''')
        for venue,day,year,start,end in self.cur.fetchall():
            self.assertEqual((year,start,end),motor_generation(venue,day))
        self.cur.execute('''SELECT e.race_id,e.boat_no,m.motor_id FROM core.race_entry e
            JOIN core.motor m ON m.venue_code <> e.venue_code LIMIT 1''')
        race,boat,motor=self.cur.fetchone()
        self.reject('UPDATE core.race_entry SET motor_id=%s WHERE race_id=%s AND boat_no=%s',(motor,race,boat))
        self.cur.execute('''SELECT e.race_id,e.boat_no,m.motor_id FROM core.race_entry e
            JOIN core.race r USING(race_id) JOIN core.motor m ON m.venue_code=e.venue_code
            WHERE r.race_date<m.generation_start_date OR r.race_date>=m.generation_end_date LIMIT 1''')
        race,boat,motor=self.cur.fetchone()
        self.reject('UPDATE core.race_entry SET motor_id=%s WHERE race_id=%s AND boat_no=%s',(motor,race,boat))

    def test_two_real_venue_boundaries(self):
        for venue,before,after in [(3,date(2024,5,6),date(2024,5,7)),(7,date(2024,7,18),date(2024,7,19))]:
            self.cur.execute('''SELECT r.race_date,min(m.generation_start_year),max(m.generation_start_year)
                FROM core.race r JOIN core.race_entry e USING(race_id) JOIN core.motor m USING(motor_id)
                WHERE r.venue_code=%s AND r.race_date IN (%s,%s) GROUP BY r.race_date ORDER BY r.race_date''',
                (venue,before,after))
            self.assertEqual(self.cur.fetchall(),[(before,2023,2023),(after,2024,2024)])

    def test_result_raw_and_normalized_lineage(self):
        self.cur.execute('''SELECT to_jsonb(r),s.raw_payload FROM core.race_result r
            JOIN raw.source_record s USING(source_record_id) ORDER BY race_id,boat_no''')
        rows=self.cur.fetchall()
        self.assertEqual(len(rows),54)
        for canonical,raw in rows:
            expected=normalize_result(raw)
            for field,value in expected.items():
                actual=canonical[field]
                if field=='start_timing' and value is not None:
                    self.assertAlmostEqual(float(actual),float(value))
                else:
                    self.assertEqual(actual,value)
            self.assertEqual(canonical['boat_no'],int(raw['teiban']))
        self.cur.execute('SELECT count(*) FROM core.race_result WHERE boat_no<>actual_course')
        self.assertGreater(self.cur.fetchone()[0],0)

    def test_official_normal_result_crosscheck(self):
        # Independently checked official 2026-09-01 Tamagawa 4R. See source_mapping.md.
        self.cur.execute('''SELECT e.boat_no,e.player_id,z.finish_position,z.actual_course,z.start_timing
            FROM core.race r JOIN core.race_entry e USING(race_id)
            JOIN core.race_result z USING(race_id,boat_no)
            WHERE race_date='2026-09-01' AND r.venue_code=5 AND race_no=4 ORDER BY e.boat_no''')
        actual=[(b,p,f,c,float(st)) for b,p,f,c,st in self.cur.fetchall()]
        self.assertEqual(actual,[(1,4910,1,1,.05),(2,4876,6,2,.15),(3,3805,4,3,.09),
                                 (4,5091,3,5,.16),(5,5301,5,6,.14),(6,3909,2,4,.13)])

    def test_f_l_preservation_and_unknown_specials(self):
        self.cur.execute("SELECT result_status,finish_raw,result_symbol_raw,start_timing_raw,start_timing FROM core.race_result WHERE result_status IN ('F','L') ORDER BY result_status,start_timing_raw")
        self.assertEqual(self.cur.fetchall(),[('F','Ｆ','F','001',None),('F','Ｆ','F','002',None),('L','Ｌ','L','   ',None)])
        self.cur.execute("SELECT count(*) FROM core.race_result WHERE result_status='UNRESOLVED' AND finish_raw IS NOT NULL AND finish_position IS NULL")
        self.assertGreater(self.cur.fetchone()[0],0)

    def test_sex_provenance_and_women_derivation(self):
        self.cur.execute('''SELECT p.player_id,p.sex,p.sex_raw,s.raw_payload FROM core.player p
            JOIN raw.source_record s ON s.source_record_id=p.sex_source_record_id''')
        sexes=set()
        for player,sex,raw,payload in self.cur.fetchall():
            self.assertEqual(player,int(payload['toroku_bango']))
            self.assertEqual(raw,payload['seibetsu_code'])
            self.assertEqual(sex,normalize_sex(raw)[0])
            sexes.add(sex)
        self.assertEqual(sexes,{'MALE','FEMALE'})
        self.cur.execute('SELECT sex_raw,sex_source_record_id,sex_normalization_status FROM core.player WHERE sex IS NULL')
        for raw,reference,status in self.cur.fetchall():
            self.assertIsNone(raw)
            self.assertIsNone(reference)
            self.assertEqual(status,'MISSING')
        self.cur.execute('''SELECT count(*) FROM core.player p JOIN raw.source_record s
            ON s.source_record_id=p.sex_source_record_id JOIN core.race_entry e USING(player_id)
            JOIN core.race r USING(race_id) WHERE (s.raw_payload->>'kaisai_nen')::int>=extract(year FROM r.race_date)''')
        self.assertEqual(self.cur.fetchone()[0],0)
        self.cur.execute('''SELECT r.women_only_derived,r.women_only_status,array_agg(p.sex ORDER BY e.boat_no),
            array_agg(e.boat_no ORDER BY e.boat_no) FROM core.race r JOIN core.race_entry e USING(race_id)
            JOIN core.player p USING(player_id) GROUP BY r.race_id''')
        for value,status,sexes,boats in self.cur.fetchall():
            self.assertEqual((value,status),women_only(sexes,boats))

    def test_edogawa_source_separate_from_model_rule(self):
        self.cur.execute("SELECT entry_fixed_effective,entry_fixed_basis FROM core.race WHERE venue_code=3")
        self.assertEqual(self.cur.fetchall(),[(True,'EDOGAWA_MODEL_RULE')]*2)
        self.cur.execute('SELECT count(*) FROM core.race WHERE stabilizer_available_for_prediction IS NOT NULL')
        self.assertEqual(self.cur.fetchone()[0],0)

    def test_raw_hashes_batches_and_all_canonical_references(self):
        self.cur.execute('SELECT raw_payload,record_hash FROM raw.source_record')
        for payload,hash_value in self.cur.fetchall():
            self.assertEqual(digest(payload),hash_value)
        self.cur.execute('''SELECT b.content_hash,b.row_count,jsonb_agg(s.raw_payload ORDER BY s.source_position)
            FROM raw.source_batch b JOIN raw.source_record s USING(source_batch_id)
            GROUP BY b.source_batch_id ORDER BY b.source_batch_id''')
        for hash_value,count,rows in self.cur.fetchall():
            self.assertEqual(len(rows),count)
            self.assertEqual(digest(rows),hash_value)
        for table in ('race','player','motor','race_entry','race_result'):
            self.cur.execute('SELECT count(*) FROM core.'+table+' c LEFT JOIN raw.source_record s USING(source_record_id) WHERE s.source_record_id IS NULL')
            self.assertEqual(self.cur.fetchone()[0],0)
        self.cur.execute('SELECT count(*) FROM raw.source_batch WHERE retrieved_at IS NOT NULL')
        self.assertEqual(self.cur.fetchone()[0],0)

    def test_immutable_source_and_dataset_and_revision_append(self):
        self.reject('UPDATE raw.source_record SET raw_payload=raw_payload')
        self.reject('DELETE FROM raw.source_record')
        self.reject('TRUNCATE raw.source_record')
        self.reject('UPDATE raw.source_batch SET status=status')
        self.reject('UPDATE core.dataset_version SET status=status')
        self.reject('''INSERT INTO raw.source_record
            (source_batch_id,source_record_key,source_race_id,source_position,raw_payload,record_hash,interpretation_status)
            SELECT source_batch_id,source_record_key,source_race_id,99999,raw_payload,record_hash,interpretation_status
            FROM raw.source_record ORDER BY source_record_id LIMIT 1''')
        self.cur.execute('SELECT to_jsonb(b),to_jsonb(s) FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id) ORDER BY source_record_id LIMIT 1')
        batch,record=self.cur.fetchone()
        batch.pop('source_batch_id');batch.pop('ingested_at')
        batch['row_count']=1;batch['content_hash']=digest([record['raw_payload']])
        batch_id=insert(self.cur,'raw.source_batch',batch,'source_batch_id')
        record.pop('source_record_id')
        record['source_batch_id']=batch_id;record['source_position']=1
        insert(self.cur,'raw.source_record',record)
        self.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertEqual(self.cur.rowcount,-1)  # A new batch can retain the same source key.

    def test_incomplete_batch_cannot_commit(self):
        self.cur.execute('SAVEPOINT incomplete')
        self.cur.execute('SELECT to_jsonb(b) FROM raw.source_batch b LIMIT 1')
        batch=self.cur.fetchone()[0];batch.pop('source_batch_id');batch.pop('ingested_at')
        insert(self.cur,'raw.source_batch',batch)
        with self.assertRaises(psycopg2.Error):
            self.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.cur.execute('ROLLBACK TO SAVEPOINT incomplete')

    def test_fixed_dataset_reproducibility_and_manifest_cutoff(self):
        self.cur.execute('SELECT effective_date,canonical_snapshot,canonical_content_hash,source_manifest,manifest_hash FROM core.dataset_version ORDER BY effective_date')
        versions=self.cur.fetchall()
        self.assertEqual(len(versions),2)
        for day,snapshot,hash_value,manifest,manifest_hash in versions:
            self.assertEqual(digest(snapshot),hash_value)
            self.assertEqual(digest(manifest),manifest_hash)
            self.assertEqual(snapshot_before(self.cur,day),snapshot)
            self.assertEqual(len(results_before(snapshot,day)),len(snapshot['race_result']))
            raw_ids=[r['source_record_id'] for r in manifest['records']]
            self.cur.execute('SELECT source_record_id,record_hash,raw_payload FROM raw.source_record WHERE source_record_id=ANY(%s)',(raw_ids,))
            actual={r:(h,p) for r,h,p in self.cur.fetchall()}
            for record in manifest['records']:
                h,p=actual[record['source_record_id']]
                self.assertEqual(h,record['record_hash'])
                if p['record_id']=='R3':
                    self.assertLess(p['kaisai_nen']+p['kaisai_tsukihi'],day.strftime('%Y%m%d'))
        before,after=versions
        self.assertEqual(len(before[1]['race_result']),30)
        self.assertEqual(len(after[1]['race_result']),54)
        # A current-canonical correction must never silently change the frozen input.
        self.cur.execute("UPDATE core.player SET player_name_raw='TEST_ROLLBACK_ONLY' WHERE player_id=(SELECT min(player_id) FROM core.player)")
        self.cur.execute('SELECT canonical_snapshot,canonical_content_hash FROM core.dataset_version')
        for snapshot,hash_value in self.cur.fetchall():
            self.assertEqual(digest(snapshot),hash_value)

    def test_source_read_only_and_exact_sample_unchanged(self):
        source=source_connection()
        try:
            with source.cursor() as cursor:
                cursor.execute("SELECT current_setting('transaction_read_only'),current_setting('default_transaction_read_only')")
                self.assertEqual(cursor.fetchone(),('on','on'))
        finally:
            source.rollback();source.close()
        records,_,_,session=extract_source()
        self.assertEqual(session['read_only'],'on')
        self.cur.execute('''SELECT b.source_table,jsonb_agg(s.raw_payload ORDER BY s.source_position)
            FROM raw.source_batch b JOIN raw.source_record s USING(source_batch_id)
            GROUP BY b.source_batch_id ORDER BY b.source_table''')
        for table,payloads in self.cur.fetchall():
            self.assertEqual(payloads,records[table])


if __name__=='__main__':
    unittest.main()

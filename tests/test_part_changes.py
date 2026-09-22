"""C3 part-change canonicalization; all database writes roll back."""
from datetime import datetime, timezone
from pathlib import Path
import os
import unittest

import psycopg2

from scripts.db import target_connection
from scripts.foundation import digest, results_before
from scripts.import_sample import RACE_KEY, insert


MIGRATION = (Path(__file__).resolve().parents[1] / 'sql/migrations' /
             '0006_race_boat_part_change.sql')
PART_FIELDS = ('propeller', 'piston', 'piston_ring', 'denki_isshiki',
               'carburetor', 'cylinder', 'crankshaft', 'gearcase', 'careerbody')


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                     'explicit local DB test opt-in required')
class PartChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = target_connection()
        cls.cur = cls.conn.cursor()
        cls.cur.execute('SELECT canonical_content_hash FROM core.dataset_version '
                        'ORDER BY dataset_version_id')
        cls.dataset_hashes = cls.cur.fetchall()
        cls.cur.execute('SELECT count(*) FROM core.race_environment_preinfo')
        cls.c2_count = cls.cur.fetchone()[0]
        cls.cur.execute('SELECT count(*) FROM core.race_boat_preinfo')
        cls.c3_count = cls.cur.fetchone()[0]
        cls.cur.execute(MIGRATION.read_text(encoding='utf-8'))

        cls.cur.execute('''SELECT r.race_id,r.race_date,r.venue_code,r.race_no
            FROM core.race r WHERE r.race_date >= DATE '2017-01-01'
              AND (SELECT count(*) FROM core.race_entry e WHERE e.race_id=r.race_id)>=4
            ORDER BY r.race_id LIMIT 1''')
        row = cls.cur.fetchone()
        if row is None:
            raise RuntimeError('an existing 2017+ race with four entries is required')
        cls.race, day, venue, race_no = row
        cls.common = dict(kaisai_nen=day.strftime('%Y'),
                          kaisai_tsukihi=day.strftime('%m%d'),
                          kyoteijo_code=str(venue).zfill(2),
                          race_no=str(race_no).zfill(2))

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def setUp(self):
        self.cur.execute('SAVEPOINT part_change_test')

    def tearDown(self):
        self.cur.execute('ROLLBACK TO SAVEPOINT part_change_test')
        self.cur.execute('RELEASE SAVEPOINT part_change_test')

    def _batch(self, rows, version, table='brd_c3'):
        batch = insert(self.cur, 'raw.source_batch', dict(
            source_name='TEST', source_type='TEST_FIXTURE',
            source_locator='test.' + table,
            extraction_condition={'version': 'phase3c-environment-preinfo-v1',
                                  'fixture': version}, source_database='test',
            source_schema='public', source_table=table, retrieved_at=None,
            extracted_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            content_hash=digest(rows), row_count=len(rows), metadata={'test': True},
            status='TEST_FIXTURE'), 'source_batch_id')
        keys = RACE_KEY + (('teiban',) if table in ('brd_l3', 'brd_c3') else ())
        sources = []
        for position, row in enumerate(rows, 1):
            sources.append(insert(self.cur, 'raw.source_record', dict(
                source_batch_id=batch,
                source_record_key={key: row[key] for key in keys},
                source_position=position, raw_payload=row, record_hash=digest(row),
                interpretation_status='TEST_FIXTURE'), 'source_record_id'))
        self.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.cur.execute('SET CONSTRAINTS ALL DEFERRED')
        return batch, sources

    def _row(self, boat, **parts):
        values = {field: '0' for field in PART_FIELDS}
        values.update(parts)
        return dict(self.common, teiban=str(boat), **values)

    def _backfill(self, batch):
        self.cur.execute('SELECT core.backfill_race_boat_part_change_v1(%s)', (batch,))
        return self.cur.fetchone()[0]

    def reject(self, query, params=()):
        self.cur.execute('SAVEPOINT rejected_part_change')
        with self.assertRaises(psycopg2.Error):
            self.cur.execute(query, params)
        self.cur.execute('ROLLBACK TO SAVEPOINT rejected_part_change')
        self.cur.execute('RELEASE SAVEPOINT rejected_part_change')

    def test_single_change_quantity_unknown_and_raw_preserved(self):
        batch, sources = self._batch([self._row(1, piston='1')], 'single')
        self.assertEqual(self._backfill(batch), 1)
        self.cur.execute('''SELECT race_id,boat_no,part_type_raw,part_type,source_field,
            ordinal,raw_value,quantity_raw,quantity,status,source_record_id
            FROM core.race_boat_part_change WHERE source_record_id=%s''', (sources[0],))
        self.assertEqual(self.cur.fetchone(),
                         (self.race, 1, 'piston', 'PISTON', 'piston', 1,
                          '1', '1', None, 'UNRESOLVED_QUANTITY', sources[0]))

    def test_multiple_changes_same_boat_are_independent_rows(self):
        batch, sources = self._batch([
            self._row(2, piston='2', piston_ring='4', gearcase='1')], 'multiple')
        self.assertEqual(self._backfill(batch), 3)
        self.cur.execute('''SELECT part_type,quantity_raw,quantity,status
            FROM core.race_boat_part_change WHERE source_record_id=%s
            ORDER BY source_field''', (sources[0],))
        self.assertEqual(self.cur.fetchall(), [
            ('GEARCASE', '1', None, 'UNRESOLVED_QUANTITY'),
            ('PISTON', '2', None, 'UNRESOLVED_QUANTITY'),
            ('PISTON_RING', '4', None, 'UNRESOLVED_QUANTITY')])

    def test_blank_invalid_and_unresolved_type_are_not_normalized(self):
        batch, sources = self._batch([
            self._row(3, denki_isshiki='   ', carburetor='?', cylinder=0,
                      crankshaft='2', gearcase=1)], 'unresolved')
        self.assertEqual(self._backfill(batch), 5)
        self.cur.execute('''SELECT source_field,raw_value,quantity_raw,quantity,status
            FROM core.race_boat_part_change WHERE source_record_id=%s
            ORDER BY source_field''', (sources[0],))
        self.assertEqual(self.cur.fetchall(), [
            ('carburetor', '?', '?', None, 'UNRESOLVED_VALUE'),
            ('crankshaft', '2', '2', None, 'UNRESOLVED_VALUE'),
            ('cylinder', 0, '0', None, 'UNRESOLVED_VALUE'),
            ('denki_isshiki', '   ', '   ', None, 'UNRESOLVED_BLANK'),
            ('gearcase', 1, '1', None, 'UNRESOLVED_VALUE')])
        self.cur.execute("SELECT core.part_change_type_v1('unknown_source_field'), "
                         "core.part_change_status_v1('unknown_source_field','\"1\"'::jsonb)")
        self.assertEqual(self.cur.fetchone(), (None, 'UNRESOLVED_TYPE'))

    def test_zero_is_not_emitted_and_replay_is_idempotent(self):
        batch, zero_sources = self._batch([self._row(1)], 'zero')
        self.assertEqual(self._backfill(batch), 0)
        self.assertEqual(self._backfill(batch), 0)
        batch, sources = self._batch([self._row(1, cylinder='1')], 'idempotent')
        self.assertEqual(self._backfill(batch), 1)
        self.assertEqual(self._backfill(batch), 0)
        self.cur.execute('''SELECT count(*) FROM core.race_boat_part_change
            WHERE source_record_id=ANY(%s)''', (zero_sources + sources,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_duplicate_observations_are_retained_without_sum(self):
        first_batch, first_sources = self._batch([
            self._row(1, piston='1')], 'duplicate-first')
        second_batch, second_sources = self._batch([
            self._row(1, piston='2')], 'duplicate-second')
        self.assertEqual(self._backfill(first_batch), 1)
        self.assertEqual(self._backfill(second_batch), 1)
        self.cur.execute('''SELECT quantity_raw,quantity,source_record_id
            FROM core.race_boat_part_change WHERE source_record_id=ANY(%s)
            ORDER BY source_record_id''', (first_sources + second_sources,))
        self.assertEqual(self.cur.fetchall(), [
            ('1', None, first_sources[0]), ('2', None, second_sources[0])])

    def test_lineage_and_source_identity_rejection(self):
        batch, sources = self._batch([self._row(1, crankshaft='1')], 'lineage')
        self.assertEqual(self._backfill(batch), 1)
        self.cur.execute('''SELECT source_record_id,source_batch_id,source_field,record_hash,
            source_batch_hash,provenance->>'result_dependency'
            FROM core.race_boat_part_change_lineage WHERE source_record_id=%s''',
                         (sources[0],))
        source, source_batch, field, record_hash, batch_hash, dependency = self.cur.fetchone()
        self.assertEqual((source, source_batch, field, dependency),
                         (sources[0], batch, 'crankshaft', 'false'))
        self.cur.execute('SELECT record_hash FROM raw.source_record WHERE source_record_id=%s',
                         (source,))
        self.assertEqual(record_hash, self.cur.fetchone()[0])
        self.cur.execute('SELECT content_hash FROM raw.source_batch WHERE source_batch_id=%s',
                         (batch,))
        self.assertEqual(batch_hash, self.cur.fetchone()[0])
        self.reject('''INSERT INTO core.race_boat_part_change
            (race_id,boat_no,part_type_raw,source_field,raw_value,quantity_raw,quantity,
             status,source_record_id,provenance)
            VALUES (%s,2,'crankshaft','crankshaft','"1"','1',NULL,
                    'UNRESOLVED_QUANTITY',%s,'{}')''', (self.race, sources[0]))

    def test_orphan_and_non_part_source_field_rejected(self):
        _, sources = self._batch([self._row(1, piston='1')], 'orphan')
        values = (self.race + 1000000000, sources[0])
        self.reject('''INSERT INTO core.race_boat_part_change
            (race_id,boat_no,part_type_raw,source_field,status,source_record_id,provenance)
            VALUES (%s,1,'piston','piston','UNRESOLVED_QUANTITY',%s,'{}')''', values)
        self.reject('''INSERT INTO core.race_boat_part_change
            (race_id,boat_no,part_type_raw,source_field,status,source_record_id,provenance)
            VALUES (%s,1,'tenji_time','tenji_time','UNRESOLVED_TYPE',%s,'{}')''',
                    (self.race, sources[0]))

    def test_2017_boundary_excludes_older_source(self):
        old_common = dict(kaisai_nen='2016', kaisai_tsukihi='0101',
                          kyoteijo_code=self.common['kyoteijo_code'], race_no='01')
        self.cur.execute('''SELECT e.player_id FROM core.race_entry e
            WHERE e.race_id=%s AND e.boat_no=1''', (self.race,))
        player = self.cur.fetchone()[0]
        l3 = dict(old_common, teiban='1', toroku_bango=str(player).zfill(4),
                  zenkoku_ritsu_1='0500')
        _, l3_sources = self._batch([l3], 'before-boundary-l3', table='brd_l3')
        self.cur.execute('SELECT to_jsonb(r) FROM core.race r WHERE race_id=%s',
                         (self.race,))
        race = self.cur.fetchone()[0]
        race.pop('race_id')
        race.update(race_date=datetime(2016, 1, 1).date(),
                    venue_code=int(old_common['kyoteijo_code']), race_no=1,
                    source_record_id=l3_sources[0], grade_source_record_id=None,
                    race_status='TEST_FIXTURE')
        old_race = insert(self.cur, 'core.race', race, 'race_id')
        insert(self.cur, 'core.race_entry', dict(
            race_id=old_race, boat_no=1, venue_code=int(old_common['kyoteijo_code']),
            player_id=player, motor_id=None, motor_no_raw=None,
            f_count_current_term_raw=None, f_count_current_term=None,
            l_count_current_term_raw=None, source_record_id=l3_sources[0],
            provenance={'test': True}))
        old = dict(old_common, teiban='1',
                   **{field: ('1' if field == 'piston' else '0')
                      for field in PART_FIELDS})
        batch, sources = self._batch([old], 'before-boundary')
        self.cur.execute('''SELECT count(*) FROM raw.source_record s
            JOIN core.race r ON r.race_date=to_date(
                (s.raw_payload->>'kaisai_nen')||(s.raw_payload->>'kaisai_tsukihi'),'YYYYMMDD')
              AND r.venue_code=(s.raw_payload->>'kyoteijo_code')::smallint
              AND r.race_no=(s.raw_payload->>'race_no')::smallint
            JOIN core.race_entry e ON e.race_id=r.race_id
              AND e.boat_no=(s.raw_payload->>'teiban')::smallint
            WHERE s.source_record_id=%s''', (sources[0],))
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertEqual(self._backfill(batch), 0)
        self.cur.execute('''SELECT count(*) FROM core.race_boat_part_change
            WHERE source_record_id=%s''', (sources[0],))
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_migration_reapply_preserves_c2_c3_frozen_and_d_minus_one(self):
        batch, sources = self._batch([self._row(1, careerbody='1')], 'reapply')
        self.assertEqual(self._backfill(batch), 1)
        self.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        self.cur.execute('''SELECT count(*) FROM core.race_boat_part_change
            WHERE source_record_id=%s''', (sources[0],))
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.cur.execute('SELECT count(*) FROM core.race_environment_preinfo')
        self.assertEqual(self.cur.fetchone()[0], self.c2_count)
        self.cur.execute('SELECT count(*) FROM core.race_boat_preinfo')
        self.assertEqual(self.cur.fetchone()[0], self.c3_count)
        self.cur.execute('SELECT canonical_content_hash FROM core.dataset_version '
                         'ORDER BY dataset_version_id')
        self.assertEqual(self.cur.fetchall(), self.dataset_hashes)
        self.cur.execute('SELECT count(*) FROM core.dataset_version '
                         'WHERE results_cutoff_date<>effective_date-1')
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.assertEqual(results_before(
            {'race': [{'race_id': 1, 'race_date': '2017-01-01'},
                      {'race_id': 2, 'race_date': '2017-01-02'}],
             'race_result': [{'race_id': 1}, {'race_id': 2}]},
            datetime(2017, 1, 2).date()), [{'race_id': 1}])


if __name__ == '__main__':
    unittest.main()

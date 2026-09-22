"""Phase 3C C2/C3 normalization and canonical lineage; writes always roll back."""
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import os
import unittest

import psycopg2

from scripts.db import target_connection
from scripts.foundation import digest, results_before
from scripts.import_sample import RACE_KEY, insert


MIGRATION = Path(__file__).resolve().parents[1] / 'sql/migrations/0005_environment_preinfo.sql'


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                     'explicit local DB test opt-in required')
class EnvironmentPreinfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = target_connection()
        cls.cur = cls.conn.cursor()
        cls.cur.execute('SELECT canonical_content_hash FROM core.dataset_version '
                        'ORDER BY dataset_version_id')
        cls.dataset_hashes = cls.cur.fetchall()
        cls.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        cls._build_fixtures()

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def setUp(self):
        self.cur.execute('SAVEPOINT environment_preinfo_test')

    def tearDown(self):
        self.cur.execute('ROLLBACK TO SAVEPOINT environment_preinfo_test')
        self.cur.execute('RELEASE SAVEPOINT environment_preinfo_test')

    @classmethod
    def _batch(cls, table, rows, version):
        batch = insert(cls.cur, 'raw.source_batch', dict(
            source_name='TEST', source_type='TEST_FIXTURE',
            source_locator='test.' + table,
            extraction_condition={'version': version}, source_database='test',
            source_schema='public', source_table=table, retrieved_at=None,
            extracted_at=datetime(2098, 12, 1, tzinfo=timezone.utc),
            content_hash=digest(rows), row_count=len(rows), metadata={'test': True},
            status='TEST_FIXTURE'), 'source_batch_id')
        keys = RACE_KEY + (('teiban',) if table in ('brd_l3', 'brd_c3') else ())
        record_ids = []
        for position, row in enumerate(rows, 1):
            record_ids.append(insert(cls.cur, 'raw.source_record', dict(
                source_batch_id=batch,
                source_record_key={key: row[key] for key in keys},
                source_position=position, raw_payload=row, record_hash=digest(row),
                interpretation_status='TEST_FIXTURE'), 'source_record_id'))
        return batch, record_ids

    @classmethod
    def _build_fixtures(cls):
        cls.cur.execute('SELECT e.player_id FROM core.race_entry e GROUP BY e.race_id,e.player_id '
                        'HAVING e.race_id=(SELECT race_id FROM core.race_entry GROUP BY race_id '
                        'HAVING count(*)=6 ORDER BY race_id LIMIT 1) ORDER BY e.player_id LIMIT 6')
        players = [row[0] for row in cls.cur.fetchall()]
        if len(players) != 6:
            raise RuntimeError('six existing players required for preinfo DB fixtures')
        day = date(2098, 12, 1)
        common = dict(kaisai_nen='2098', kaisai_tsukihi='1201',
                      kyoteijo_code='01', race_no='01')
        l3_rows = [dict(common, teiban=str(boat), toroku_bango=str(player).zfill(4),
                        zenkoku_ritsu_1='0500')
                   for boat, player in enumerate(players, 1)]
        _, l3_ids = cls._batch('brd_l3', l3_rows, 'phase3c-test-l3')

        cls.cur.execute('SELECT to_jsonb(r) FROM core.race r ORDER BY race_id LIMIT 1')
        race = cls.cur.fetchone()[0]
        race.pop('race_id')
        race.update(race_date=day, venue_code=1, race_no=1, race_status='TEST_FIXTURE')
        cls.race = insert(cls.cur, 'core.race', race, 'race_id')
        for boat, (player, source) in enumerate(zip(players, l3_ids), 1):
            insert(cls.cur, 'core.race_entry', dict(
                race_id=cls.race, boat_no=boat, venue_code=1, player_id=player,
                motor_id=None, motor_no_raw=None, f_count_current_term_raw=None,
                f_count_current_term=None, l_count_current_term_raw=None,
                source_record_id=source, provenance={'test': True}))

        c2_row = dict(common, kion='250', suion='-30', tenki_code='1',
                      fuko_code='16', hogaku_code='01', fusoku='00', hako='00',
                      suimenkisho_joho='    ')
        cls.c2_batch, cls.c2_sources = cls._batch(
            'brd_c2', [c2_row], 'phase3c-environment-preinfo-v1')
        c3_values = [
            ('0671', ' 05', '1', '016', ' '),
            ('0680', '-05', '2', '004', 'F'),
            ('0690', ' 00', '3', '   ', 'L'),
            ('0000', ' 10', '4', '000', ' '),
            ('6.71', 'bad', '7', '0.1', ' '),
            ('    ', '   ', ' ', '   ', ' '),
        ]
        c3_rows = [dict(common, teiban=str(boat), tenji_time=values[0], tilt=values[1],
                        tenji_shinnyu_course=values[2], tenji_st=values[3],
                        tenji_kigo=values[4])
                   for boat, values in enumerate(c3_values, 1)]
        cls.c3_batch, cls.c3_sources = cls._batch(
            'brd_c3', c3_rows, 'phase3c-environment-preinfo-v1')
        cls.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cls.cur.execute('SET CONSTRAINTS ALL DEFERRED')

    def reject(self, query, params=()):
        self.cur.execute('SAVEPOINT rejected_preinfo')
        with self.assertRaises(psycopg2.Error):
            self.cur.execute(query, params)
        self.cur.execute('ROLLBACK TO SAVEPOINT rejected_preinfo')

    def backfill(self):
        self.cur.execute('SELECT core.backfill_race_environment_preinfo_v1(%s)',
                         (self.c2_batch,))
        c2 = self.cur.fetchone()[0]
        self.cur.execute('SELECT core.backfill_race_boat_preinfo_v1(%s)',
                         (self.c3_batch,))
        return c2, self.cur.fetchone()[0]

    def test_c2_normalization_and_unresolved_units(self):
        self.assertEqual(self.backfill(), (1, 6))
        self.cur.execute('''SELECT air_temperature_raw,air_temperature_c,air_temperature_status,
            water_temperature_raw,water_temperature_c,water_temperature_status,
            weather_code,weather_status,wind_direction_code,wind_direction_status,
            venue_direction_code,venue_direction_status,wind_speed_raw,wind_speed_status,
            wave_height_raw,wave_height_status,surface_weather_marker_status
            FROM core.race_environment_preinfo WHERE race_id=%s''', (self.race,))
        self.assertEqual(self.cur.fetchone(), (
            '250', Decimal('25.0'), 'VALID', '-30', Decimal('-3.0'), 'VALID',
            1, 'VALID', 16, 'VALID', 1, 'VALID', '00', 'UNRESOLVED',
            '00', 'UNRESOLVED', 'MISSING'))

    def test_c3_statuses_f_l_sentinel_and_invalid(self):
        self.backfill()
        self.cur.execute('''SELECT boat_no,exhibition_time_seconds,exhibition_time_status,
            tilt_degrees,tilt_status,exhibition_course,exhibition_course_status,
            exhibition_start_timing,exhibition_start_symbol_raw,exhibition_start_status
            FROM core.race_boat_preinfo WHERE race_id=%s ORDER BY boat_no''', (self.race,))
        rows = self.cur.fetchall()
        self.assertEqual(rows[0], (1, Decimal('6.71'), 'VALID', Decimal('0.5'), 'VALID',
                                   1, 'VALID', Decimal('0.16'), ' ', 'VALID'))
        self.assertEqual(rows[1][-3:], (None, 'F', 'F'))
        self.assertEqual(rows[2][-3:], (None, 'L', 'L'))
        self.assertEqual((rows[3][1], rows[3][2], rows[3][7], rows[3][9]),
                         (None, 'SOURCE_SENTINEL', Decimal('0.00'), 'VALID'))
        self.assertEqual((rows[4][1], rows[4][2], rows[4][3], rows[4][4],
                          rows[4][5], rows[4][6], rows[4][7], rows[4][9]),
                         (None, 'INVALID', None, 'INVALID', None, 'INVALID', None, 'INVALID'))
        self.assertEqual({rows[5][2], rows[5][4], rows[5][6], rows[5][9]}, {'MISSING'})

    def test_lineage_provenance_and_raw_cannot_be_forged(self):
        self.backfill()
        self.cur.execute('''SELECT source_record_id,source_batch_id,source_record_key,record_hash,
            source_batch_hash,normalization_version,provenance
            FROM core.race_boat_preinfo_status WHERE race_id=%s AND boat_no=1''', (self.race,))
        source, batch, key, record_hash, batch_hash, version, provenance = self.cur.fetchone()
        self.assertEqual((source, batch), (self.c3_sources[0], self.c3_batch))
        self.assertEqual(key['teiban'], '1')
        self.assertEqual(version, 'phase3c-environment-preinfo-v1')
        self.assertEqual(provenance['result_dependency'], False)
        self.assertEqual(provenance['source_table'], 'brd_c3')
        self.cur.execute('SELECT record_hash FROM raw.source_record WHERE source_record_id=%s',
                         (source,))
        self.assertEqual(record_hash, self.cur.fetchone()[0])
        self.cur.execute('SELECT content_hash FROM raw.source_batch WHERE source_batch_id=%s',
                         (batch,))
        self.assertEqual(batch_hash, self.cur.fetchone()[0])
        self.cur.execute("UPDATE core.race_boat_preinfo SET exhibition_time_raw='9999', "
                         "provenance='{}' WHERE race_id=%s AND boat_no=1", (self.race,))
        self.cur.execute('SELECT exhibition_time_raw,provenance->>\'source_table\' '
                         'FROM core.race_boat_preinfo WHERE race_id=%s AND boat_no=1',
                         (self.race,))
        self.assertEqual(self.cur.fetchone(), ('0671', 'brd_c3'))

    def test_source_identity_mismatch_rejected(self):
        self.reject('INSERT INTO core.race_boat_preinfo '
                    '(race_id,boat_no,source_record_id,provenance) VALUES (%s,1,%s,\'{}\')',
                    (self.race, self.c3_sources[1]))
        self.reject('INSERT INTO core.race_environment_preinfo '
                    '(race_id,source_record_id,provenance) VALUES (%s,%s,\'{}\')',
                    (self.race, self.c3_sources[0]))

    def test_backfill_replay_and_conflicting_revision_rejected(self):
        self.assertEqual(self.backfill(), (1, 6))
        self.assertEqual(self.backfill(), (0, 0))
        self.cur.execute('SELECT raw_payload FROM raw.source_record WHERE source_record_id=%s',
                         (self.c2_sources[0],))
        changed = self.cur.fetchone()[0]
        changed['kion'] = '251'
        conflict_batch, _ = self._batch('brd_c2', [changed], 'conflicting-revision')
        self.cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.cur.execute('SET CONSTRAINTS ALL DEFERRED')
        self.reject('SELECT core.backfill_race_environment_preinfo_v1(%s)',
                    (conflict_batch,))

    def test_missing_source_views_and_c4_metadata(self):
        self.backfill()
        self.cur.execute('DELETE FROM core.race_boat_preinfo WHERE race_id=%s AND boat_no=6',
                         (self.race,))
        self.cur.execute('SELECT coverage_status FROM core.race_boat_preinfo_status '
                         'WHERE race_id=%s ORDER BY boat_no', (self.race,))
        self.assertEqual([row[0] for row in self.cur.fetchall()],
                         ['AVAILABLE'] * 5 + ['MISSING_SOURCE'])
        self.cur.execute("SELECT venue_code,source_field,structural_status "
                         "FROM core.c4_field_structural_status WHERE "
                         "(venue_code=1 AND source_field='isshu') OR venue_code=3 OR "
                         "(venue_code IN (12,13,18) AND source_field='chokusen')")
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 8)
        self.assertEqual({row[2] for row in rows}, {'STRUCTURALLY_NOT_PROVIDED'})
        self.cur.execute("SELECT count(*) FROM information_schema.tables "
                         "WHERE table_schema='core' AND table_type='BASE TABLE' "
                         "AND table_name LIKE '%c4%'")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_exhibition_course_and_st_are_independent_of_result_fields(self):
        self.backfill()
        self.cur.execute('SELECT exhibition_course,exhibition_start_timing '
                         'FROM core.race_boat_preinfo WHERE race_id=%s AND boat_no=1',
                         (self.race,))
        self.assertEqual(self.cur.fetchone(), (1, Decimal('0.16')))
        self.cur.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='core' "
                         "AND table_name='race_boat_preinfo' AND column_name IN "
                         "('actual_course','start_timing')")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_migration_reapply_and_d_minus_one_contract(self):
        self.assertEqual(self.backfill(), (1, 6))
        self.cur.execute('SELECT count(*) FROM core.race_environment_preinfo')
        c2_count = self.cur.fetchone()[0]
        self.cur.execute('SELECT count(*) FROM core.race_boat_preinfo')
        c3_count = self.cur.fetchone()[0]
        self.cur.execute(MIGRATION.read_text(encoding='utf-8'))
        self.cur.execute('SELECT count(*) FROM core.race_environment_preinfo')
        self.assertEqual(self.cur.fetchone()[0], c2_count)
        self.cur.execute('SELECT count(*) FROM core.race_boat_preinfo')
        self.assertEqual(self.cur.fetchone()[0], c3_count)
        self.assertEqual(results_before(
            {'race': [{'race_id': 1, 'race_date': '2098-12-01'},
                      {'race_id': 2, 'race_date': '2098-12-02'}],
             'race_result': [{'race_id': 1}, {'race_id': 2}]}, date(2098, 12, 2)),
            [{'race_id': 1}])
        self.cur.execute('SELECT count(*) FROM core.dataset_version '
                         'WHERE results_cutoff_date<>effective_date-1')
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.cur.execute('SELECT canonical_content_hash FROM core.dataset_version '
                         'ORDER BY dataset_version_id')
        self.assertEqual(self.cur.fetchall(), self.dataset_hashes)


if __name__ == '__main__':
    unittest.main()

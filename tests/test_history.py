"""Offline history importer tests; no source or target database is opened."""
from copy import deepcopy
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts import history_source, import_history
from scripts.foundation import digest


def entry(boat=1, **changes):
    row = dict(kaisai_nen='2024', kaisai_tsukihi='0506', kyoteijo_code='03',
               race_no='01', teiban=str(boat), toroku_bango=str(4000 + boat),
               shimei='source name ', motor_no=' ', f_kaisu=' ', l_kaisu=None)
    row.update(changes)
    return row


def ki(player='4001', year='2023', sex='2', term='1'):
    return dict(toroku_bango=player, kaisai_nen=year, ki=term,
                seibetsu_code=sex, shimei_kanji='identity name ', yosei_ki='100')


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.cur = MagicMock()
        self.rows = [entry()]
        self.at = datetime(2026, 9, 22, tzinfo=timezone.utc)

    def preserve(self):
        return import_history.preserve(self.cur, 'brd_l3', '2024-05', self.rows, self.at)

    def test_identical_partition_is_reused_without_writes(self):
        self.cur.fetchall.return_value = [(10, digest(self.rows))]
        with patch.object(import_history, 'insert') as insert, patch.object(import_history, 'bulk') as bulk:
            self.assertEqual(self.preserve(), (10, False, False))
        insert.assert_not_called()
        bulk.assert_not_called()
        self.cur.copy_expert.assert_not_called()

    def test_changed_partition_is_preserved_as_conflict(self):
        self.cur.fetchall.return_value = [(10, digest([entry(shimei='older')]))]
        with patch.object(import_history, 'insert', return_value=11) as insert, patch.object(import_history, 'bulk') as bulk:
            self.assertEqual(self.preserve(), (11, True, True))
        batch = insert.call_args.args[2]
        self.assertEqual(batch['content_hash'], digest(self.rows))
        self.assertIsNone(batch['retrieved_at'])
        self.assertEqual(batch['extracted_at'], self.at)
        values = list(csv.reader(io.StringIO(self.cur.copy_expert.call_args.args[1].getvalue())))[0]
        self.assertEqual(json.loads(values[3]), self.rows[0])
        self.assertEqual(values[4], digest(self.rows[0]))
        self.assertEqual(json.loads(values[1])['teiban'], '1')

    def test_matching_one_revision_does_not_clear_existing_conflict(self):
        self.cur.fetchall.return_value = [(10, digest(self.rows)), (11, digest([entry(shimei='changed')]))]
        with patch.object(import_history, 'insert') as insert:
            self.assertEqual(self.preserve(), (10, False, True))
        insert.assert_not_called()

    def test_successfully_extracted_empty_partition_has_explicit_status(self):
        self.rows = []
        self.cur.fetchall.return_value = []
        with patch.object(import_history, 'insert', return_value=10) as insert, patch.object(import_history, 'bulk') as bulk:
            self.assertEqual(self.preserve(), (10, True, False))
        batch = insert.call_args.args[2]
        self.assertEqual((batch['row_count'], batch['status']), (0, 'SOURCE_EMPTY'))
        self.assertEqual(batch['content_hash'], digest([]))
        self.assertEqual(self.cur.copy_expert.call_args.args[1].getvalue(), '')

    def test_copy_roundtrip_retains_unicode_quotes_newlines_and_null(self):
        self.rows = [entry(shimei='選手,"quoted"\r\nname ', l_kaisu=None)]
        import_history.copy_raw(self.cur, 10, 'brd_l3', self.rows)
        values = list(csv.reader(io.StringIO(self.cur.copy_expert.call_args.args[1].getvalue())))[0]
        self.assertEqual(values[0], '10')
        self.assertEqual(values[2], '1')
        self.assertEqual(json.loads(values[3]), self.rows[0])
        self.assertEqual(values[4], digest(self.rows[0]))

    def test_stored_partition_rejects_missing_or_ambiguous_versions(self):
        for batches in ([], [(10,), (11,)]):
            with self.subTest(batches=batches):
                self.cur.fetchall.return_value = batches
                with self.assertRaisesRegex(RuntimeError, 'absent/ambiguous'):
                    import_history.stored(self.cur, 'brd_l3', '2024-05')

    def test_stored_empty_partition_is_distinct_from_missing_partition(self):
        self.cur.fetchall.side_effect = [[(10,)], []]
        self.assertEqual(import_history.stored(self.cur, 'brd_l3', '2024-05'), [])


class ExtractionTests(unittest.TestCase):
    def test_pre_2017_full_raw_partitions_are_disabled(self):
        for table,partition in [('brd_l3','2016-12'),('brd_ki','2016')]:
            with self.subTest(table=table):
                with self.assertRaisesRegex(ValueError,'2017-01-01'):
                    history_source.extract(MagicMock(),table,partition)
                with self.assertRaisesRegex(ValueError,'2017-01-01'):
                    import_history.preserve(MagicMock(),table,partition,[],datetime.now(timezone.utc))

    def test_unknown_source_table_rejected_before_query(self):
        conn = MagicMock()
        with self.assertRaises(ValueError):
            history_source.extract(conn, 'untrusted', '2024-05')
        conn.cursor.assert_not_called()

    def test_month_and_ki_year_filters_are_bound_parameters(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [entry()]
        self.assertEqual(history_source.extract(conn, 'brd_l3', '2024-05'), [entry()])
        query, params = cur.execute.call_args.args
        self.assertEqual(params, ('2024', '05'))
        self.assertIn('left(kaisai_tsukihi,2)=%s', query)
        self.assertTrue(query.endswith('ORDER BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban'))
        history_source.extract(conn, 'brd_ki', '2023')
        self.assertEqual(cur.execute.call_args.args[1], ('2023',))

    def test_source_select_failure_propagates(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('injected SELECT failure')
        with self.assertRaisesRegex(RuntimeError, 'SELECT failure'):
            history_source.extract(conn, 'brd_l2', '2024-05')

    def test_inventory_keeps_invalid_date_rows_in_total_and_partition(self):
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [
            [('2024', '0228', '03', 2), ('2024', '0230', '03', 1)],
            [('2023', '1', 4, 4)],
        ]
        with patch.object(history_source, 'TABLES', ('brd_l2', 'brd_ki')), \
             patch.object(history_source, 'identity_support', return_value=[]):
            report = history_source.inventory(conn)
        self.assertEqual(report['brd_l2']['rows'], 3)
        self.assertEqual(report['brd_l2']['date_count'], 1)
        self.assertEqual(report['brd_l2']['partitions'], ['2024-02'])
        self.assertEqual(report['brd_l2']['invalid_date_groups'], [['2024', '0230', '03', 1]])
        self.assertEqual(report['brd_ki']['rows'], 4)

    def test_failed_select_never_reaches_raw_preservation(self):
        source, target = MagicMock(), MagicMock()
        target.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
        report = {'brd_l2': {'rows': 1, 'partitions': ['2024-05']},
                  'brd_ki': {'rows': 0, 'terms': []}}
        with patch.object(import_history, 'source_connection', return_value=source), \
             patch.object(import_history, 'target_connection', return_value=target), \
             patch.object(import_history, 'TABLES', ('brd_l2', 'brd_ki')), \
             patch.object(import_history, 'inventory', return_value=report), \
             patch.object(import_history, 'extract', side_effect=RuntimeError('injected SELECT failure')), \
             patch.object(import_history, 'preserve') as preserve:
            with self.assertRaisesRegex(RuntimeError, 'SELECT failure'):
                import_history.run(raw_only=True)
        preserve.assert_not_called()
        target.rollback.assert_called_once()
        source.rollback.assert_called_once()
        source.close.assert_called_once()
        target.close.assert_called_once()

    def test_inventory_extraction_count_mismatch_blocks_completion(self):
        source, target = MagicMock(), MagicMock()
        target.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
        report = {'brd_l2': {'rows': 2, 'partitions': ['2024-05']},
                  'brd_ki': {'rows': 0, 'terms': []}}
        with patch.object(import_history, 'source_connection', return_value=source), \
             patch.object(import_history, 'target_connection', return_value=target), \
             patch.object(import_history, 'TABLES', ('brd_l2', 'brd_ki')), \
             patch.object(import_history, 'inventory', return_value=report), \
             patch.object(import_history, 'extract', return_value=[entry()]), \
             patch.object(import_history, 'preserve', return_value=(1, True, False)), \
             patch.object(import_history, 'canonical_month') as canonical:
            with self.assertRaisesRegex(RuntimeError, 'does not cover inventory'):
                import_history.run(raw_only=True)
        canonical.assert_not_called()


class PlayerBoundaryTests(unittest.TestCase):
    def test_duplicate_ki_key_blocks_selection(self):
        with self.assertRaisesRegex(RuntimeError,'duplicate KI'):
            self.initialize([(1,ki()),(2,ki())])

    def initialize(self, observations):
        first = {'4001': ('2024', 100, entry())}
        original = deepcopy(observations)
        with patch.object(import_history, 'bulk') as bulk:
            sexes = import_history.initialize_players(MagicMock(), observations, first)
        self.assertEqual(observations, original)
        return sexes, bulk.call_args.args[2][0]

    def test_same_year_and_future_ki_do_not_fill_earliest_identity(self):
        sexes, row = self.initialize([(1, ki(year='2024')), (2, ki(year='2025'))])
        self.assertEqual(sexes, {4001: None})
        self.assertIsNone(row['sex_source_record_id'])
        self.assertIsNone(row['training_class'])
        self.assertEqual(row['source_record_id'], 100)
        self.assertEqual(row['player_name_raw'], 'source name ')

    def test_earlier_ki_is_selected_without_later_conflict_contamination(self):
        sexes, row = self.initialize([(1, ki()), (2, ki(year='2024', sex='1'))])
        self.assertEqual(sexes, {4001: 'FEMALE'})
        self.assertEqual(row['sex_source_record_id'], 1)
        self.assertEqual(row['training_class'], 100)
        self.assertEqual(row['provenance']['historical_availability'], 'UNKNOWN')

    def test_conflicting_eligible_sexes_remain_unresolved(self):
        sexes, row = self.initialize([(1, ki(year='2022')), (2, ki(sex='1'))])
        self.assertEqual(sexes, {4001: None})
        self.assertEqual(row['sex_normalization_status'], 'UNRESOLVED')
        self.assertTrue(row['provenance']['eligible_sex_conflict'])
        self.assertIsNone(row['sex_source_record_id'])

    def test_missing_ki_does_not_invent_sex(self):
        sexes, row = self.initialize([])
        self.assertEqual(sexes, {4001: None})
        self.assertEqual(row['sex_normalization_status'], 'MISSING')


class CanonicalMappingTests(unittest.TestCase):
    def test_pre_2017_canonical_partition_rejected(self):
        with self.assertRaisesRegex(ValueError,'2017-01-01'):
            import_history.canonical_month(MagicMock(),'2016-12',{})

    def setUp(self):
        self.sources = {t: [] for t in history_source.TABLES}
        self.sources['brd_l2'] = [(1, dict(entry(), shinnyukotei='0', anteiban_shiyo='0'))]
        self.sources['brd_l3'] = [(10 + b, entry(b)) for b in range(1, 7)]
        self.sources['brd_r3'] = [(20 + b, dict(entry(b), shinnyu_course=str(b),
            chakujun=f'{b:02}', st='014', kigo=' ')) for b in range(1, 7)]
        self.sexes = {4000 + b: 'FEMALE' for b in range(1, 7)}

    def canonical(self, existing=None):
        cur = MagicMock()
        def query_rows():
            query = cur.execute.call_args.args[0]
            if query.startswith('SELECT race_id,race_date'):
                return [(101, date(2024, 5, 6), 3, 1)]
            if query.startswith('SELECT s.raw_payload,s.record_hash'):
                for table, rows in (existing or {}).items():
                    if 'FROM core.' + table + ' c ' in query:
                        return rows
            return []
        cur.fetchall.side_effect = query_rows
        written = {}
        def capture(_cur, table, rows, conflict=''):
            written[table] = deepcopy(rows)
        with patch.object(import_history, 'stored', side_effect=lambda _c, t, _p: self.sources[t]), \
             patch.object(import_history, 'bulk', side_effect=capture):
            report = import_history.canonical_month(cur, '2024-05', self.sexes)
        return report, written

    def test_existing_canonical_revision_is_rejected(self):
        previous = entry(f_kaisu='1')
        with self.assertRaisesRegex(RuntimeError, 'existing canonical source revision race_entry'):
            self.canonical({'race_entry': [(previous, digest(previous))]})

    def test_existing_identical_source_may_be_reused(self):
        previous = entry()
        report, _ = self.canonical({'race_entry': [(previous, digest(previous))]})
        self.assertEqual(report['eligible_rows']['entry'], 6)

    def test_duplicate_source_key_blocks_before_writes(self):
        self.sources['brd_l3'].append((99, entry()))
        with self.assertRaisesRegex(RuntimeError, 'duplicate source natural key brd_l3'):
            self.canonical()

    def test_course_not_replaced_by_boat_or_edogawa_rule(self):
        self.sources['brd_r3'][0][1]['shinnyu_course'] = '3'
        self.sources['brd_r3'][1][1]['shinnyu_course'] = ' '
        report, written = self.canonical()
        race = written['core.race'][0]
        self.assertTrue(race['entry_fixed_effective'])
        self.assertIsNone(race['entry_fixed_source'])
        self.assertIsNone(race['stabilizer_available_for_prediction'])
        results = written['core.race_result']
        self.assertEqual(results[0]['actual_course'], 3)
        self.assertIsNone(results[1]['actual_course'])
        self.assertEqual(results[0]['boat_no'], 1)
        self.assertEqual(results[0]['start_timing'], Decimal('0.14'))
        self.assertEqual(report['eligible_rows']['result'], 6)

    def test_unknown_result_preserved_without_normal_rank(self):
        self.sources['brd_r3'][0][1].update(chakujun='転', kigo='?', st='abc')
        _, written = self.canonical()
        result = written['core.race_result'][0]
        self.assertEqual(result['finish_raw'], '転')
        self.assertIsNone(result['finish_position'])
        self.assertIsNone(result['start_timing'])
        self.assertEqual(result['normalization_status'], 'UNRESOLVED')

    def test_registration_conflict_excludes_result_but_preserves_entry(self):
        self.sources['brd_r3'][0][1]['toroku_bango'] = '4999'
        report, written = self.canonical()
        self.assertEqual(report['issues']['REGISTRATION_CONFLICT'], 1)
        self.assertEqual(report['example_raw_ids']['REGISTRATION_CONFLICT'], 21)
        self.assertEqual(len(written['core.race_entry']), 6)
        self.assertEqual(len(written['core.race_result']), 5)
        self.assertNotIn(1, [r['boat_no'] for r in written['core.race_result']])

    def test_conflicting_finish_and_symbol_excludes_result_with_evidence(self):
        self.sources['brd_r3'][0][1]['kigo'] = 'F'
        report, written = self.canonical()
        self.assertEqual(report['issues']['RESULT_CODE_CONFLICT'], 1)
        self.assertEqual(report['example_raw_ids']['RESULT_CODE_CONFLICT'], 21)
        self.assertEqual(len(written['core.race_result']), 5)

    def test_missing_result_and_orphan_rows_are_distinguished(self):
        self.sources['brd_r3'] = self.sources['brd_r3'][1:]
        self.sources['brd_l3'].append((99, entry(race_no='02')))
        report, written = self.canonical()
        self.assertEqual(report['issues']['ENTRY_WITHOUT_RESULT'], 1)
        self.assertEqual(report['issues']['L3_WITHOUT_L2'], 1)
        self.assertEqual(len(written['core.race']), 1)
        self.assertEqual(written['core.race'][0]['race_status'], 'SOURCE_INCOMPLETE')
        self.assertEqual(written['core.race'][0]['women_only_derived'], True)


if __name__ == '__main__':
    unittest.main()

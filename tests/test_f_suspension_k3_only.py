"""Boundary checks for the unchanged K3-only daily F state machine."""

from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import unittest

from scripts.f_suspension_k3_only_probe import State, fetch_initial_seed, prediction_features
from scripts.f_suspension_seed_k3 import audit as seed_audit, construct_seed


ROOT = Path(__file__).resolve().parents[1]


class DailyFSuspensionTests(unittest.TestCase):
    def test_frozen_artifacts_reconstruct_declared_counts(self):
        artifact_dir = ROOT / 'artifacts'
        frozen = json.loads((artifact_dir / 'f_suspension_method_freeze_v1.json')
                            .read_text(encoding='utf-8'))
        seed = json.loads((artifact_dir / 'f_suspension_initial_seed_k3_v1.json')
                          .read_text(encoding='utf-8'))
        replay = json.loads((artifact_dir / 'f_suspension_canonical_replay_v1.json')
                            .read_text(encoding='utf-8'))
        direct = json.loads((artifact_dir / 'f_suspension_direct_k3_replay_v1.json')
                            .read_text(encoding='utf-8'))
        comparison = json.loads((artifact_dir / 'f_suspension_seed_legacy_comparison_v1.json')
                                .read_text(encoding='utf-8'))
        self.assertEqual(seed['status'], 'PASS')
        self.assertEqual((seed['cohort_players'], seed['active'], seed['unresolved']),
                         (617, 48, 569))
        self.assertEqual((seed['source_window_cohort_l3_missing'],
                          seed['source_window_cohort_l3_player_mismatch']), (0, 0))
        self.assertEqual(comparison['player_state_difference_count'], 0)
        self.assertEqual(comparison['old_only_player_ids'], [])
        self.assertEqual(comparison['k3_only_player_ids'], [])
        self.assertEqual(replay['counts']['f_events'], 12635)
        self.assertEqual(replay['counts']['f2_additional_events'], 808)
        self.assertEqual(replay['prediction_entry_state'],
                         frozen['formal_reconstruction']['prediction_before_entry'])
        self.assertEqual(replay['final_state'],
                         frozen['formal_reconstruction']['period_end'])
        for key in ('scope', 'initial_jan1_players', 'initial_jan1_active_seed',
                    'initial_jan1_unresolved', 'counts', 'prediction_entry_state',
                    'final_state', 'initial_unknown_first_resolution', 'yearly_f'):
            self.assertEqual(direct[key], replay[key], key)
        for name, field in (
                ('f_suspension_initial_seed_k3_v1.json', 'initial_seed_artifact_sha256'),
                ('f_suspension_canonical_replay_v1.json', 'canonical_replay_artifact_sha256'),
                ('f_suspension_direct_k3_replay_v1.json',
                 'direct_k3_replay_artifact_sha256'),
                ('f_suspension_seed_legacy_comparison_v1.json',
                 'legacy_comparison_artifact_sha256')):
            digest = hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest().upper()
            self.assertEqual(digest, frozen['evidence'][field])

    def test_29_30_31_day_gap(self):
        start = date(2024, 1, 1)
        for days, expected in ((29,'ACTIVE_UNSERVED'),(30,'CLEAR'),(31,'CLEAR')):
            with self.subTest(days=days):
                state = State()
                state.day(start,confirmed=1,f_events=1)
                self.assertEqual(state.day(start+timedelta(days=days))['before'],expected)

    def test_same_day_evidence_is_applied_after_prediction(self):
        state = State()
        result = state.day(date(2017, 1, 1),confirmed=2,f_events=1)
        self.assertEqual(result['before'],'UNRESOLVED')
        self.assertEqual(result['after'],'ACTIVE_UNSERVED')
        self.assertEqual(state.day(date(2017, 1, 2))['before'],'ACTIVE_UNSERVED')

    def test_same_day_later_race_does_not_see_earlier_f(self):
        state = State()
        day = date(2017, 1, 1)
        first_and_later_race_prediction = state.value
        result = state.day(day, confirmed=2, f_events=1)
        self.assertEqual(first_and_later_race_prediction, 'UNRESOLVED')
        self.assertEqual(result['before'], first_and_later_race_prediction)
        self.assertEqual(result['after'], 'ACTIVE_UNSERVED')
        self.assertEqual(state.day(day + timedelta(days=1))['before'], 'ACTIVE_UNSERVED')

    def test_second_f_and_one_gap_clears_all_pending(self):
        state = State()
        state.day(date(2024, 1, 1),confirmed=1,f_events=1)
        second = state.day(date(2024, 1, 5),confirmed=1,f_events=1)
        self.assertEqual(second['f2'],1)
        self.assertEqual(state.pending_f,2)
        self.assertEqual(state.day(date(2024, 2, 4))['before'],'CLEAR')
        self.assertEqual(state.pending_f,0)

    def test_period_boundary_does_not_reset(self):
        for previous, boundary in ((date(2024, 4, 30), date(2024, 5, 1)),
                                   (date(2024, 10, 31), date(2024, 11, 1))):
            with self.subTest(boundary=boundary):
                state = State()
                state.day(previous, confirmed=1, f_events=1)
                self.assertEqual(state.day(boundary)['before'], 'ACTIVE_UNSERVED')

    def test_active_normal_race_resets_gap_anchor_after_day(self):
        state = State()
        state.day(date(2024, 1, 1), confirmed=1, f_events=1)
        ordinary = state.day(date(2024, 1, 20), confirmed=1)
        self.assertEqual(ordinary['before'], 'ACTIVE_UNSERVED')
        self.assertEqual(ordinary['after'], 'ACTIVE_UNSERVED')
        self.assertEqual(state.last_confirmed_race, date(2024, 1, 20))
        self.assertEqual(state.day(date(2024, 2, 18))['before'], 'ACTIVE_UNSERVED')
        self.assertEqual(state.day(date(2024, 2, 19))['before'], 'CLEAR')

    def test_initial_unresolved_resolution(self):
        with_f = State()
        first = with_f.day(date(2017, 1, 1), confirmed=1, f_events=1)
        self.assertEqual((first['before'], first['after']),
                         ('UNRESOLVED', 'ACTIVE_UNSERVED'))
        without_race = State()
        self.assertEqual(without_race.day(date(2017, 1, 29))['before'], 'UNRESOLVED')
        self.assertEqual(without_race.day(date(2017, 1, 30))['before'], 'CLEAR')

    def test_feature_contract_preserves_unknown(self):
        self.assertEqual(prediction_features('ACTIVE_UNSERVED'),
                         {'f_suspension_state':'ACTIVE_UNSERVED',
                          'has_unserved_f_suspension':True})
        self.assertEqual(prediction_features('CLEAR')['has_unserved_f_suspension'], False)
        self.assertIsNone(prediction_features('UNRESOLVED')['has_unserved_f_suspension'])
        with self.assertRaises(ValueError):
            prediction_features('F1')

    def test_k3_seed_construction_keeps_no_f_unresolved(self):
        rows = construct_seed({1001, 1002}, [(1001, '2016', '1203', '01', '01',
                                              '1', 'F ')])
        self.assertEqual([row['state'] for row in rows],
                         ['ACTIVE_UNSERVED', 'UNRESOLVED'])
        self.assertEqual(rows[0]['latest_f_date'], '2016-12-03')
        with self.assertRaises(ValueError):
            construct_seed({1001}, [(1001, '2016', '1202', '01', '01', '1', 'F ')])

    def test_2017_seed_is_active_and_unknown_stays_unknown(self):
        self.assertEqual(State(date(2016, 12, 31)).day(date(2017, 1, 1))['before'],
                         'ACTIVE_UNSERVED')
        self.assertEqual(State().day(date(2017, 1, 1))['before'],'UNRESOLVED')


@unittest.skipUnless(os.environ.get('BOATRACE_TEST_DB') == '1',
                     'explicit local DB test opt-in required')
class FormalFSuspensionDatabaseTests(unittest.TestCase):
    def test_initial_seed_artifact_matches_live_k3_and_canonical_cohort(self):
        live = seed_audit()
        saved = json.loads((ROOT / 'artifacts/f_suspension_initial_seed_k3_v1.json')
                           .read_text(encoding='utf-8'))
        self.assertEqual(live['status'], 'PASS', live['issues'])
        self.assertEqual(live['cohort_players'], 617)
        self.assertEqual((live['active'], live['unresolved']), (48, 569))
        self.assertEqual(live['players'], saved['players'])
        self.assertEqual(live['player_rows_sha256'], saved['player_rows_sha256'])
        self.assertEqual(live['result_dataset_version'], saved['result_dataset_version'])
        from scripts.db import source_connection
        source = source_connection()
        try:
            with source.cursor() as cur:
                cohort = {row['player_id'] for row in saved['players']}
                replay_seed = fetch_initial_seed(cur, cohort)
            artifact_seed = {row['player_id']: date.fromisoformat(row['latest_f_date'])
                             for row in saved['players'] if row['latest_f_date']}
            self.assertEqual(replay_seed, artifact_seed)
        finally:
            source.rollback()
            source.close()

    def test_formal_f_events_are_exclusively_k3_lineage(self):
        from scripts.db import target_connection
        connection = target_connection()
        connection.commit()
        connection.set_session(readonly=True)
        try:
            with connection.cursor() as cur:
                cur.execute('''SELECT count(*), count(*) FILTER (
                    WHERE b.source_table='brd_k3' AND btrim(z.finish_raw)='F'
                      AND s.raw_payload->>'chakujun'=z.finish_raw)
                    FROM core.race_result z
                    JOIN raw.source_record s ON s.source_record_id=z.source_record_id
                    JOIN raw.source_batch b USING(source_batch_id)
                    WHERE z.result_status='F' ''')
                self.assertEqual(cur.fetchone(), (12635, 12635))
        finally:
            connection.rollback()
            connection.close()


if __name__ == '__main__':
    unittest.main()

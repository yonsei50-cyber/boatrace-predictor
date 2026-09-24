"""Narrow tests for Natural Environment Feature v1 model development."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts import p1_p2_baseline_v1 as baseline
from scripts.natural_environment_model_v1 import (
    COURSE_NAMES, ENV_FIELDS, fit_environment_preprocessor,
    load_environment_cache, select, transform_environment,
)


class NaturalEnvironmentModelV1Tests(unittest.TestCase):
    def synthetic(self):
        races = 4
        numeric = np.full((races * 6, len(baseline.NUMERIC)), 2.0, dtype=np.float32)
        course_indices = [baseline.NUMERIC.index(name) for name in COURSE_NAMES]
        for boat in range(6):
            numeric[boat::6, course_indices] = np.array([.4, .2, .1, .1, .1, .1])
            numeric[boat::6, course_indices[0]] += boat * .02
        numeric[0, course_indices[1]] = np.nan
        data = {'numeric': numeric, 'race_ids': np.array([10, 11, 12, 13]),
                'years': np.array([2021, 2021, 2022, 2022], dtype=np.int16)}
        env = {'race_ids': data['race_ids'].copy(), 'years': data['years'].copy(),
               'wind_speed': np.array([1., np.nan, 999., 999.]),
               'air_temperature': np.array([20., 22., 999., 999.]),
               'tide_height': np.array([1., 2., 999., 999.]),
               'tide_change_speed': np.array([.2, .3, 999., 999.]),
               'wind_category': np.array(['HEADWIND', 'CALM', 'FUTURE', 'FUTURE']),
               'weather': np.array(['SUNNY', 'RAIN', 'FUTURE', 'FUTURE']),
               'tide_direction': np.array(['RISING', 'FALLING', 'FUTURE', 'FUTURE']),
               'tide_source_available': np.array([True, True, False, False]),
               'tide_status': np.array(['AVAILABLE', 'AVAILABLE', 'NOT_APPLICABLE', 'NOT_APPLICABLE'])}
        return data, env

    def test_preprocessor_uses_training_only_and_allowed_interactions(self):
        data, env = self.synthetic()
        train = data['years'] < 2022
        prep = fit_environment_preprocessor(data, env, 'E2', train)
        self.assertEqual(prep['fitted_years'], [2021])
        self.assertNotIn('FUTURE', sum(prep['levels'].values(), []))
        order = ' '.join(prep['feature_order'])
        for forbidden in ('boat_no', 'actual_course', 'venue', 'rating', 'motor'):
            self.assertNotIn(forbidden, order)
        self.assertNotIn('tide_status', order)
        self.assertNotIn('tide_source_available', order)

    def test_transform_is_finite_race_centered_and_unseen_all_zero(self):
        data, env = self.synthetic()
        train = data['years'] < 2022
        prep = fit_environment_preprocessor(data, env, 'E1', train)
        x = transform_environment(data, env, prep, data['years'] == 2022)
        self.assertTrue(np.isfinite(x).all())
        # Extreme future-only values exercise float32 centering; the residual
        # stays tiny relative to the transformed magnitude.
        np.testing.assert_allclose(x.mean(axis=1), 0.0, atol=2e-3)
        categorical_start = 2 * len(prep['numeric_names'])
        np.testing.assert_allclose(x[:, :, categorical_start:], 0.0, atol=1e-7)

    def test_race_common_environment_without_course_difference_cancels(self):
        data, env = self.synthetic()
        course_indices = [baseline.NUMERIC.index(name) for name in COURSE_NAMES]
        data['numeric'][:, course_indices] = .25
        train = data['years'] < 2022
        prep = fit_environment_preprocessor(data, env, 'E1', train)
        x = transform_environment(data, env, prep, train)
        np.testing.assert_allclose(x, 0.0, atol=1e-7)

    def test_cache_alignment_is_exact(self):
        data, env = self.synthetic()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'env.npz'
            np.savez(path, **env)
            loaded = load_environment_cache(data, path)
            self.assertEqual(set(ENV_FIELDS) - set(loaded), set())
            env['race_ids'] = env['race_ids'][::-1]
            np.savez(path, **env)
            with self.assertRaisesRegex(RuntimeError, 'race_ids'):
                load_environment_cache(data, path)

    def test_selection_tie_prefers_simpler_bundle_then_lower_penalty(self):
        candidates = [
            {'bundle': 'E2', 'penalty': .01, 'mean_log_loss': 1., 'mean_brier': .8},
            {'bundle': 'E1', 'penalty': .1, 'mean_log_loss': 1.000001, 'mean_brier': .800001},
            {'bundle': 'E0', 'penalty': .01, 'mean_log_loss': 1.000009, 'mean_brier': .800009},
        ]
        self.assertEqual(select(candidates)['bundle'], 'E0')

    def test_tide_applicability_and_unresolved_are_management_only(self):
        data, env = self.synthetic()
        env['tide_direction'][2] = 'NOT_APPLICABLE'
        env['tide_direction'][3] = 'UNRESOLVED'
        env['tide_status'][2] = 'NOT_APPLICABLE'
        env['tide_status'][3] = 'UNRESOLVED'
        prep = fit_environment_preprocessor(data, env, 'E2', data['years'] < 2022)
        self.assertEqual(prep['levels']['tide_direction'], ['FALLING', 'RISING'])
        self.assertFalse(any('tide_direction=NOT_APPLICABLE' in x or
                             'tide_direction=UNRESOLVED' in x
                             for x in prep['feature_order']))
        x = transform_environment(data, env, prep, data['years'] == 2022)
        tide_start = (2 * len(prep['numeric_names'])
                      + 6 * len(prep['levels']['wind_category'])
                      + 6 * len(prep['levels']['weather']))
        np.testing.assert_allclose(x[:, :, tide_start:], 0.0, atol=1e-7)


if __name__ == '__main__':
    unittest.main()

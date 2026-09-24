"""Narrow pre-holdout checks for the baseline's label and time boundaries."""
import unittest

import numpy as np

from scripts.p1_p2_baseline_v1 import (
    CATEGORICAL, EXTRACT_SQL, NUMERIC, bundle_columns, fit_model, fit_preprocessor,
    metrics, probabilities, transform,
)


class BaselineV1Tests(unittest.TestCase):
    def synthetic(self):
        numeric = np.full((18, len(NUMERIC)), 2.0, dtype=np.float32)
        numeric[0, 0] = np.nan
        numeric[12:18, 0] = 1000.0  # future-only distribution shift
        categories = np.zeros((18, len(CATEGORICAL)), dtype=np.uint8)
        return dict(numeric=numeric, categories=categories,
                    years=np.array([2021, 2021, 2022], dtype=np.int16),
                    vocabulary=[{'one': 0} for _ in CATEGORICAL])

    def test_extract_boundary_is_literal_and_labels_come_from_dataset(self):
        self.assertIn("race_date < DATE '2025-01-01'", EXTRACT_SQL)
        self.assertIn('label_eligible = TRUE', EXTRACT_SQL)
        self.assertIn('label_p1,label_p2', EXTRACT_SQL)
        self.assertNotIn('brd_r3', EXTRACT_SQL.lower())

    def test_bundle_stays_inside_requested_features(self):
        core, _ = bundle_columns('CORE')
        short, _ = bundle_columns('CORE_SHORT')
        motor, _ = bundle_columns('CORE_MOTOR')
        full, _ = bundle_columns('FULL')
        self.assertNotIn('entry_course_history_count', full)
        self.assertNotIn('rating_short_50_history_count', full)
        self.assertEqual(set(short) - set(core), {'rating_short_50'})
        self.assertEqual(set(motor) - set(core), {
            'motor_a_base3', 'base_n_meetings', 'base_n_uses',
            'base_residual_sum', 'motor_a_current', 'current_n_uses',
        })
        self.assertEqual(set(full), set(short) | set(motor))

    def test_preprocessing_is_fitted_without_validation_year(self):
        data = self.synthetic()
        prep = fit_preprocessor(data, 'CORE', data['years'] < 2022)
        self.assertEqual(prep['fitted_years'], [2021])
        self.assertEqual(prep['medians'][0], 2.0)
        self.assertEqual(prep['means'][0], 2.0)
        self.assertEqual(prep['scales'][0], 1.0)
        validation = transform(data, prep, data['years'] == 2022)
        self.assertTrue(np.isfinite(validation).all())
        self.assertEqual(validation.shape[0], 1)

    def test_independent_exact_labels_and_probability_constraints(self):
        # Winner and runner-up are deliberately different boats.
        x = np.zeros((2, 6, 2), dtype=np.float32)
        x[:, :, 0] = np.array([3, 2, 1, 0, -1, -2])
        x[:, :, 1] = -x[:, :, 0]
        first = np.array([0, 0], dtype=np.uint8)
        second = np.array([5, 5], dtype=np.uint8)
        for label in (first, second):
            coef, _ = fit_model(x, label, 0.01)
            scores = (x.reshape(-1, 2) @ coef).reshape(-1, 6)
            p = probabilities(scores)
            self.assertTrue(np.isfinite(p).all())
            self.assertTrue(((p >= 0) & (p <= 1)).all())
            np.testing.assert_allclose(p.sum(axis=1), np.ones(2), atol=1e-12)
            self.assertEqual(metrics(scores, label)['top1'], 1.0)


if __name__ == '__main__':
    unittest.main()

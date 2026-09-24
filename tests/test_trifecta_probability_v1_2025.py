"""Narrow checks for the frozen P1/P2 to trifecta evaluation."""
import inspect
import unittest

import numpy as np

from scripts import evaluate_trifecta_probability_v1_2025 as trifecta


class TrifectaProbabilityV1Tests(unittest.TestCase):
    def synthetic(self):
        p1 = np.array([[.40, .25, .15, .10, .06, .04]], dtype=np.float64)
        p2 = np.array([[.09, .30, .25, .18, .11, .07]], dtype=np.float64)
        data = {
            'race_id': np.array([1]),
            'race_date_yyyymmdd': np.array([20250101]),
            'label_p1': np.array([[1, 0, 0, 0, 0, 0]], dtype=np.uint8),
            'label_p2': np.array([[0, 1, 0, 0, 0, 0]], dtype=np.uint8),
            'pred_p1': p1, 'pred_p2': p2,
        }
        return data

    def test_120_distinct_combinations_sum_and_actual(self):
        data = self.synthetic()
        scores, probabilities, valid = trifecta.evaluate(data, np.array([3], dtype=np.uint8))
        self.assertEqual(trifecta.COMBINATIONS.shape, (120, 3))
        self.assertEqual(len({tuple(x) for x in trifecta.COMBINATIONS}), 120)
        self.assertTrue(all(len(set(x)) == 3 for x in trifecta.COMBINATIONS))
        self.assertTrue(valid[0])
        self.assertTrue(np.isfinite(probabilities).all())
        self.assertTrue((probabilities >= 0).all())
        np.testing.assert_allclose(probabilities.sum(axis=1), [1], atol=2e-10)
        actual = trifecta.actual_indices(data, np.array([3], dtype=np.uint8))
        rows = trifecta.output_arrays(data, probabilities, valid, actual)
        self.assertEqual(len(rows['race_id']), 120)
        self.assertEqual(int(rows['is_actual'].sum()), 1)
        self.assertEqual(tuple(trifecta.COMBINATIONS[actual[0]]), (1, 2, 3))
        self.assertGreater(scores['trifecta_log_loss'], 0)

    def test_zero_denominator_is_not_evaluable_without_fallback(self):
        data = self.synthetic()
        data['pred_p2'] = np.array([[1., 0., 0., 0., 0., 0.]])
        probabilities, valid = trifecta.probabilities(data['pred_p1'], data['pred_p2'])
        self.assertFalse(valid[0])
        self.assertTrue(np.isnan(probabilities[0]).all())

    def test_deterministic_rerun_and_frozen_input_boundary(self):
        data = self.synthetic()
        first = trifecta.evaluate(data, np.array([3], dtype=np.uint8))
        second = trifecta.evaluate(data, np.array([3], dtype=np.uint8))
        self.assertEqual(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])
        np.testing.assert_array_equal(first[2], second[2])
        source = inspect.getsource(trifecta)
        self.assertNotIn('brd_r3', source.lower())
        self.assertNotIn('fit_model', source)
        self.assertNotIn('fit_preprocessor', source)
        self.assertNotIn('transform(', source)
        self.assertIn('with np.load(INPUT, allow_pickle=False)', source)
        self.assertIn("source != 'brd_k3'", source)


if __name__ == '__main__':
    unittest.main()

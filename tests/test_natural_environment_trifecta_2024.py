import unittest

import numpy as np

from scripts.natural_environment_trifecta_2024 import (
    COMBINATIONS, THIRD_SQL, sequential_probabilities,
)


class NaturalEnvironmentTrifecta2024Tests(unittest.TestCase):
    def test_uniform_probabilities_are_120_class_uniform(self):
        p = np.full((2, 6), 1 / 6, dtype=np.float64)
        result = sequential_probabilities(p, p)
        np.testing.assert_allclose(result, 1 / 120, atol=1e-14)

    def test_nonuniform_sequential_formula(self):
        p1 = np.array([[.4, .2, .15, .1, .1, .05]])
        p2 = np.array([[.1, .25, .2, .2, .15, .1]])
        result = sequential_probabilities(p1, p2)
        index = np.flatnonzero(np.all(COMBINATIONS == [0, 1, 2], axis=1))[0]
        expected = p1[0, 0] * p2[0, 1] / (1 - p2[0, 0]) * p2[0, 2] / (1 - p2[0, 0] - p2[0, 1])
        self.assertAlmostEqual(result[0, index], expected)
        self.assertAlmostEqual(result.sum(), 1)

    def test_result_query_is_2024_k3_only(self):
        self.assertIn("DATE '2024-01-01'", THIRD_SQL)
        self.assertIn("DATE '2025-01-01'", THIRD_SQL)
        self.assertIn('d.label_eligible=TRUE', THIRD_SQL)


if __name__ == '__main__':
    unittest.main()

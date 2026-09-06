"""test_moo.py —— code/moo.py（NSGA-II 与多目标评价指标）的单元测试。

论文 16（NSGA-II 种群 30、代数 100）与论文 15（种群 100、每代 10 子代）都使用 NSGA-II，
因此本模块的对照参数也按这两个量级选取。

运行方式（仓库根目录）：
    python tests/test_moo.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import moo


class TestDominance(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(moo.dominates([1, 1], [2, 2]))
        self.assertFalse(moo.dominates([1, 2], [2, 1]))
        self.assertFalse(moo.dominates([1, 1], [1, 1]))
        self.assertFalse(moo.dominates([2, 2], [1, 1]))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            moo.dominates([1, 2], [1, 2, 3])


class TestNonDominatedSort(unittest.TestCase):
    def setUp(self):
        self.F = np.array([[1.0, 5.0], [2.0, 4.0], [3.0, 3.0], [4.0, 2.0], [5.0, 1.0],
                           [2.0, 6.0], [3.0, 5.0], [6.0, 6.0]])

    def test_three_fronts(self):
        rank, fronts = moo.non_dominated_sort(self.F)
        self.assertEqual(len(fronts), 3)
        self.assertEqual(fronts[0], [0, 1, 2, 3, 4])
        self.assertEqual(fronts[1], [5, 6])
        self.assertEqual(fronts[2], [7])
        np.testing.assert_array_equal(rank, [0, 0, 0, 0, 0, 1, 1, 2])

    def test_pareto_front(self):
        self.assertEqual(set(moo.pareto_front(self.F).tolist()), {0, 1, 2, 3, 4})

    def test_empty(self):
        rank, fronts = moo.non_dominated_sort(np.zeros((0, 2)))
        self.assertEqual(len(fronts), 0)
        self.assertEqual(rank.size, 0)


class TestCrowdingDistance(unittest.TestCase):
    def test_boundaries_infinite(self):
        F = np.array([[1.0, 5.0], [2.0, 4.0], [3.0, 3.0]])
        cd = moo.crowding_distance(F, [0, 1, 2])
        self.assertTrue(np.isinf(cd[0]) and np.isinf(cd[2]))
        self.assertGreater(cd[1], 0.0)

    def test_small_front(self):
        F = np.array([[1.0, 1.0], [2.0, 2.0]])
        cd = moo.crowding_distance(F, [0, 1])
        self.assertTrue(np.all(np.isinf(cd)))


class TestIndicators(unittest.TestCase):
    def test_hypervolume_monotone(self):
        ref = [6.5, 6.5]
        hv1 = moo.hypervolume_2d(np.array([[3.0, 3.0]]), ref)
        hv2 = moo.hypervolume_2d(np.array([[3.0, 3.0], [2.0, 2.0]]), ref)
        self.assertGreater(hv2, hv1)
        self.assertGreater(hv1, 0.0)

    def test_hypervolume_mc_matches_exact(self):
        ref = [6.5, 6.5]
        F = np.array([[3.0, 3.0], [2.0, 2.0], [1.5, 4.0]])
        exact = moo.hypervolume_2d(F, ref)
        mc = moo.hypervolume_mc(F, ref, n_mc=200000, seed=1)
        self.assertLess(abs(mc - exact) / exact, 0.02)

    def test_igd(self):
        ref_front = np.column_stack([np.linspace(0, 1, 21), 1 - np.linspace(0, 1, 21) ** 2])
        self.assertAlmostEqual(moo.igd(ref_front, ref_front), 0.0, places=9)
        self.assertGreater(moo.igd(ref_front + 0.5, ref_front), 0.0)
        self.assertEqual(moo.igd(np.zeros((0, 2)), ref_front), float("inf"))

    def test_spread(self):
        uniform = np.column_stack([np.linspace(0, 1, 50), 1 - np.linspace(0, 1, 50)])
        self.assertLess(moo.spread(uniform), 0.1, "等距前沿的 spread 应接近 0")


class TestNSGA2(unittest.TestCase):
    @staticmethod
    def _zdt_like(P):
        P = np.atleast_2d(np.asarray(P, float))
        f1 = P[:, 0]
        g = 1.0 + 9.0 * np.mean(P[:, 1:], axis=1)
        return np.column_stack([f1, g * (1.0 - np.sqrt(np.maximum(f1 / g, 0.0)))])

    def test_approximates_front(self):
        bounds = [(0.0, 1.0)] * 6
        X, F, hist = moo.nsga2(self._zdt_like, bounds, pop_size=60, n_gen=120,
                               seed=7, return_history=True)
        pf = F[moo.pareto_front(F)]
        self.assertGreaterEqual(pf.shape[0], 40)
        self.assertLess(np.min(pf[:, 0]), 0.05)
        self.assertLess(np.min(pf[:, 1]), 0.15)
        # 输出解集里不应存在互相支配的点
        for i in range(0, pf.shape[0], 7):
            for j in range(0, pf.shape[0], 7):
                if i != j:
                    self.assertFalse(moo.dominates(pf[i], pf[j]))
        ref_true = np.column_stack([np.linspace(0, 1, 51),
                                    1 - np.sqrt(np.linspace(0, 1, 51))])
        self.assertLess(moo.igd(pf, ref_true), 0.05)

    def test_more_generations_helps(self):
        bounds = [(0.0, 1.0)] * 6
        ref_true = np.column_stack([np.linspace(0, 1, 51),
                                    1 - np.sqrt(np.linspace(0, 1, 51))])
        _, F_short = moo.nsga2(self._zdt_like, bounds, pop_size=60, n_gen=20, seed=7)
        _, F_long = moo.nsga2(self._zdt_like, bounds, pop_size=60, n_gen=120, seed=7)
        igd_short = moo.igd(F_short[moo.pareto_front(F_short)], ref_true)
        igd_long = moo.igd(F_long[moo.pareto_front(F_long)], ref_true)
        self.assertLess(igd_long, igd_short)

    def test_population_size_and_offspring(self):
        bounds = [(0.0, 1.0)] * 3
        X, F = moo.nsga2(self._zdt_like, bounds, pop_size=30, n_gen=10,
                         n_offspring=10, seed=1)
        self.assertEqual(X.shape, (30, 3))
        self.assertEqual(F.shape[1], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

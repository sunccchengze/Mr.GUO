"""test_benchmarks.py —— code/benchmarks.py（优化算法测试函数集）的单元测试。

这些函数是论文 01（CR-EI）、论文 06/08（GMFoO / KT-ASO）、论文 07（GSDE）与
论文 11（DA-EGO）用来验证算法的标准算例，本文件保证"最优值登记无误"。

运行方式（仓库根目录）：
    python tests/test_benchmarks.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import benchmarks


class TestRegistry(unittest.TestCase):
    def test_expected_problems_exist(self):
        names = set(benchmarks.list_problems())
        for must in ("hartman6", "shekel4", "camel6", "trid10",
                     "ackley5", "ackley6", "rosenbrock6"):
            self.assertIn(must, names, f"缺少论文使用的基准问题 {must}")

    def test_bounds_match_dimension(self):
        for name in benchmarks.list_problems():
            p = benchmarks.get_problem(name)
            with self.subTest(problem=name):
                self.assertEqual(len(p.bounds), p.dim)
                for lo, hi in p.bounds:
                    self.assertGreater(hi, lo)

    def test_get_problem_is_fresh(self):
        """每次 get_problem 都应返回一个新的、计数清零的实例。"""
        p1 = benchmarks.get_problem("hartman6")
        p1(np.zeros(6))
        self.assertEqual(p1.eval_count, 1)
        p2 = benchmarks.get_problem("hartman6")
        self.assertEqual(p2.eval_count, 0)

    def test_unknown_problem(self):
        with self.assertRaises(KeyError):
            benchmarks.get_problem("no_such_problem")


class TestKnownOptima(unittest.TestCase):
    CASES = [
        ("sphere5", np.zeros(5), 0.0),
        ("branin2", np.array([-np.pi, 12.275]), 0.397887),
        ("camel6", np.array([0.0898, -0.7126]), -1.0316),
        ("hartman6",
         np.array([0.20169, 0.150011, 0.476874, 0.275332, 0.311652, 0.6573]),
         -3.32237),
        ("trid10", np.arange(1, 11) * (11 - np.arange(1, 11)), -210.0),
        ("ackley5", np.zeros(5), 0.0),
        ("ackley6", np.zeros(6), 0.0),
        ("rosenbrock6", np.full(6, 0.4), 0.0),
        ("griewank10", np.zeros(10), 0.0),
        ("levy10", np.ones(10), 0.0),
    ]

    def test_optimum_values(self):
        for name, xstar, fstar in self.CASES:
            with self.subTest(problem=name):
                p = benchmarks.get_problem(name)
                self.assertAlmostEqual(float(p(xstar)), fstar, delta=5e-3)
                self.assertLessEqual(float(p(xstar)), p.fmin + 5e-3)

    def test_trid10_matches_formula(self):
        """论文 01 用的 Trid10 最优值为 -d(d+4)(d-1)/6 = -210。"""
        d = 10
        self.assertAlmostEqual(-d * (d + 4) * (d - 1) / 6.0, -210.0)
        self.assertAlmostEqual(benchmarks.get_problem("trid10").fmin, -210.0)

    def test_shifted_rosenbrock_used_by_paper08(self):
        """论文 08 的平移 Rosenbrock：最优在 x_i = 0.4，最优值 0。"""
        p = benchmarks.get_problem("rosenbrock6")
        np.testing.assert_allclose(p.xmin, np.full(6, 0.4))
        self.assertAlmostEqual(float(p(np.full(6, 0.4))), 0.0, places=10)
        # 标准 Rosenbrock 的最优在全 1 向量，与平移版本不同
        self.assertGreater(float(p(np.ones(6))), 0.0)


class TestEvaluationAccounting(unittest.TestCase):
    def test_counter_and_history(self):
        p = benchmarks.get_problem("hartman6")
        rng = np.random.default_rng(7)
        for _ in range(10):
            p(rng.random(6))
        self.assertEqual(p.eval_count, 10)
        self.assertEqual(len(p.history), 10)
        self.assertAlmostEqual(p.best_so_far(), min(p.history))
        p.reset()
        self.assertEqual(p.eval_count, 0)
        self.assertEqual(len(p.history), 0)

    def test_regret_is_non_negative(self):
        p = benchmarks.get_problem("camel6")
        p(np.array([0.0898, -0.7126]))
        # 在最优点处 regret 应≈0；登记的最优值只有 6 位小数，故给 1e-3 的容差
        self.assertLess(abs(p.regret()), 1e-3)

    def test_wrong_dimension(self):
        p = benchmarks.get_problem("hartman6")
        with self.assertRaises(ValueError):
            p(np.zeros(5))


if __name__ == "__main__":
    unittest.main(verbosity=2)

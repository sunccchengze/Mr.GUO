"""test_sampling.py —— code/sampling.py 的单元测试。

运行方式（仓库根目录）：
    python tests/test_sampling.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402  保证 code/ 在 sys.path 中

import numpy as np

import sampling


class TestLatinHypercube(unittest.TestCase):
    def test_shape_and_unit_range(self):
        X = sampling.latin_hypercube(32, 3, rng=np.random.default_rng(1))
        self.assertEqual(X.shape, (32, 3))
        self.assertTrue(np.all(X >= 0.0))
        self.assertTrue(np.all(X < 1.0))

    def test_stratification(self):
        """LHS 的核心性质：每一维的每个分层区间里恰好有一个样本。"""
        n, d = 40, 2
        X = sampling.latin_hypercube(n, d, rng=np.random.default_rng(7))
        for j in range(d):
            bins = np.clip((X[:, j] * n).astype(int), 0, n - 1)
            self.assertEqual(sorted(bins.tolist()), list(range(n)))

    def test_center_criterion_is_deterministic(self):
        """criterion='center' 取每层中点：每列的取值集合与随机种子无关（只有行序会变）。"""
        a = sampling.latin_hypercube(12, 2, rng=np.random.default_rng(0), criterion="center")
        b = sampling.latin_hypercube(12, 2, rng=np.random.default_rng(99), criterion="center")
        np.testing.assert_allclose(np.sort(a, axis=0), np.sort(b, axis=0))
        # 每一维的取值应为 (perm + 0.5)/n
        self.assertTrue(np.allclose(np.unique(a[:, 0]), (np.arange(12) + 0.5) / 12))

    def test_reproducible_with_same_rng(self):
        a = sampling.latin_hypercube(16, 4, rng=np.random.default_rng(5))
        b = sampling.latin_hypercube(16, 4, rng=np.random.default_rng(5))
        c = sampling.latin_hypercube(16, 4, rng=np.random.default_rng(6))
        np.testing.assert_allclose(a, b)
        self.assertFalse(np.allclose(a, c))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            sampling.latin_hypercube(0, 3)
        with self.assertRaises(ValueError):
            sampling.latin_hypercube(5, 0)
        with self.assertRaises(ValueError):
            sampling.latin_hypercube(5, 2, criterion="maximin")


class TestUniformAndScaling(unittest.TestCase):
    def test_random_uniform_bounds(self):
        bounds = [(0.0, 1.0), (5.0, 9.0)]
        X = sampling.random_uniform(200, bounds, rng=np.random.default_rng(2))
        self.assertEqual(X.shape, (200, 2))
        self.assertTrue(np.all(X[:, 1] >= 5.0) and np.all(X[:, 1] <= 9.0))
        self.assertTrue(np.all(X[:, 0] >= 0.0) and np.all(X[:, 0] <= 1.0))

    def test_scale_matrix_roundtrip(self):
        bounds = [(0.0, 1.0), (-2.0, 3.5), (1e-3, 2e-3)]
        lo, span = sampling.scale_matrix(bounds)
        np.testing.assert_allclose(lo, [0.0, -2.0, 1e-3])
        np.testing.assert_allclose(span, [1.0, 5.5, 1e-3])
        Z = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [0.5, 0.5, 0.5]])
        X = sampling.from_unit(Z, bounds)
        Z2 = sampling.to_unit(X, bounds)
        np.testing.assert_allclose(Z, Z2, atol=1e-12)
        np.testing.assert_allclose(X[0], [b[0] for b in bounds])
        np.testing.assert_allclose(X[1], [b[1] for b in bounds])
        # 50% 处
        np.testing.assert_allclose(X[2], [0.5, 0.75, 1.5e-3])

    def test_bounds_validation(self):
        with self.assertRaises(ValueError):
            sampling.random_uniform(3, [(1.0, 0.0)])
        with self.assertRaises(ValueError):
            sampling.to_unit(np.zeros((2, 3)), [(0.0, 1.0)] * 2)


class TestSobolCoarse(unittest.TestCase):
    """注意：sampling.sobol_first_order_indices 是**中位数分组的粗估计**（模块文档已说明），
    只用于快速判断"哪个变量看起来更重要"，不是严格的 Sobol 指数。因此这里只测
    "排序正确"与"取值范围"，不测具体数值。严格版本见 gp.first_order_effects 与
    decomposition.interaction_scores。"""

    @staticmethod
    def _f(X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        return 5.0 * X[:, 0] + 0.1 * X[:, 1] + 0.5 * np.sin(X[:, 2])

    def test_ranking(self):
        rng = np.random.default_rng(3)
        X = rng.random((4000, 3))
        y = self._f(X)
        s = sampling.sobol_first_order_indices(X, y)
        self.assertEqual(s.shape, (3,))
        self.assertTrue(np.all(s >= 0.0) and np.all(s <= 1.0))
        self.assertGreater(s[0], s[1], f"x0 的影响应远大于 x1：{s}")
        self.assertGreater(s[0], s[2], f"线性项应比有界正弦项更能解释方差：{s}")

    def test_constant_response(self):
        X = np.random.default_rng(0).random((50, 3))
        s = sampling.sobol_first_order_indices(X, np.full(50, 2.0))
        np.testing.assert_allclose(s, np.zeros(3))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            sampling.sobol_first_order_indices(np.zeros((5, 2)), np.zeros(4))


if __name__ == "__main__":
    unittest.main(verbosity=2)

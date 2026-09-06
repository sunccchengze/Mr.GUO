"""test_gp.py —— code/gp.py（普通 Kriging + 采集函数 + 方差分解）的单元测试。

运行方式（仓库根目录）：
    python tests/test_gp.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import gp
from sampling import random_uniform


def camel6(X: np.ndarray) -> np.ndarray:
    X = np.atleast_2d(np.asarray(X, float))
    x1, x2 = X[:, 0], X[:, 1]
    return ((4.0 - 2.1 * x1 ** 2 + x1 ** 4 / 3.0) * x1 ** 2
            + x1 * x2 + (-4.0 + 4.0 * x2 ** 2) * x2 ** 2)


BOUNDS = [(-3.0, 3.0), (-2.0, 2.0)]


class TestCorrelation(unittest.TestCase):
    def test_diagonal_and_symmetry(self):
        rng = np.random.default_rng(0)
        X = rng.random((6, 3))
        R = gp.squared_exponential_corr(X, X, np.array([1.0, 2.0, 3.0]))
        np.testing.assert_allclose(np.diag(R), np.ones(6))
        np.testing.assert_allclose(R, R.T)
        self.assertTrue(np.all(R >= 0.0) and np.all(R <= 1.0))

    def test_lengthscale_shrinks_correlation(self):
        X = np.array([[0.0], [1.0]])
        r_small = gp.squared_exponential_corr(X, X, np.array([10.0]))[0, 1]
        r_large = gp.squared_exponential_corr(X, X, np.array([0.1]))[0, 1]
        self.assertLess(r_small, r_large, "θ 越大（长度尺度越短）相关性应越低")

    def test_scalar_theta_broadcasts(self):
        rng = np.random.default_rng(1)
        X = rng.random((4, 3))
        R1 = gp.squared_exponential_corr(X, X, np.array([2.0]))
        R2 = gp.squared_exponential_corr(X, X, np.array([2.0, 2.0, 2.0]))
        np.testing.assert_allclose(R1, R2)


class TestKriging(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(20240905)
        lo = np.array([-3.0, -2.0])
        span = np.array([6.0, 4.0])
        self.X = lo + rng.random((40, 2)) * span
        self.y = camel6(self.X)
        self.Xt = lo + rng.random((300, 2)) * span
        self.yt = camel6(self.Xt)
        self.mdl = gp.Kriging(n_restarts=2, seed=1).fit(self.X, self.y)

    def test_interpolation(self):
        mu, sd = self.mdl.predict(self.X)
        rel = float(np.max(np.abs(mu - self.y)) / (self.y.max() - self.y.min()))
        self.assertLess(rel, 1e-3, f"Kriging 应精确通过训练点，相对误差 {rel:.2e}")
        self.assertTrue(np.all(sd >= 0.0))

    def test_generalization(self):
        r2 = self.mdl.r2(self.Xt, self.yt)
        self.assertGreater(r2, 0.9, f"测试集 R² 偏低：{r2:.4f}")

    def test_uncertainty_grows_away_from_data(self):
        _, sd_near = self.mdl.predict(self.X[:1])
        _, sd_far = self.mdl.predict(np.array([[2.95, 1.95]]))
        self.assertGreater(float(sd_far[0]), float(sd_near[0]))

    def test_leave_one_out(self):
        loo = self.mdl.leave_one_out_rmse()
        rng = self.yt.max() - self.yt.min()
        self.assertLess(loo, 0.2 * rng, f"留一 RMSE 偏大：{loo}")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            gp.Kriging().fit(np.zeros((5, 2)), np.zeros(4))
        with self.assertRaises(ValueError):
            gp.Kriging().fit(np.zeros((1, 2)), np.zeros(1))


class TestAcquisitions(unittest.TestCase):
    def test_ei_properties(self):
        mean = np.array([0.0, 1.0, 2.0])
        sd = np.ones(3)
        ei = gp.expected_improvement(mean, sd, f_best=0.0)
        self.assertTrue(np.all(ei >= -1e-12))
        self.assertGreater(ei[0], ei[1])
        self.assertGreater(ei[1], ei[2])
        # 零方差 → 零 EI
        np.testing.assert_allclose(
            gp.expected_improvement(np.array([0.5]), np.array([0.0]), 0.0), [0.0])
        # 不确定性越大 EI 越大
        self.assertGreater(
            gp.expected_improvement(np.array([1.0]), np.array([3.0]), 0.0)[0],
            gp.expected_improvement(np.array([1.0]), np.array([0.5]), 0.0)[0])

    def test_gei_g1_equals_ei(self):
        rng = np.random.default_rng(0)
        mean = rng.normal(size=20)
        sd = rng.uniform(0.1, 2.0, size=20)
        np.testing.assert_allclose(
            gp.generalized_expected_improvement(mean, sd, f_best=0.0, g=1),
            gp.expected_improvement(mean, sd, f_best=0.0), atol=1e-10)

    def test_gei_higher_order_explores_more(self):
        """g 越大越偏向全局探索：高 g 应更偏好**方差大**的点。"""
        mean = np.array([0.0, 0.3])   # 点 0 均值更低（开发）
        sd = np.array([0.2, 0.4])     # 点 1 不确定性更大（探索）
        i1 = int(np.argmax(gp.generalized_expected_improvement(mean, sd, 0.0, g=1)))
        i3 = int(np.argmax(gp.generalized_expected_improvement(mean, sd, 0.0, g=3)))
        self.assertEqual(i1, 0, "g=1 应偏好均值更低的点（开发）")
        self.assertEqual(i3, 1, "g=3 应偏好不确定性更大的点（探索）")


class TestAnova(unittest.TestCase):
    def test_dominant_variable(self):
        """y = 5·x1 + 0.2·x2：x1 的一阶指数应远大于 x2。"""
        rng = np.random.default_rng(2)
        bounds = [(0.0, 1.0), (0.0, 1.0)]

        def f(X):
            X = np.atleast_2d(X)
            return 5.0 * X[:, 0] + 0.2 * X[:, 1]

        X = random_uniform(60, bounds, rng=rng)
        mdl = gp.Kriging(n_restarts=1, seed=2).fit(X, f(X))
        s1, eff = gp.first_order_effects(lambda Z: mdl.predict(Z)[0],
                                         bounds, n_mc=1024, seed=5)
        self.assertEqual(s1.shape, (2,))
        self.assertGreater(s1[0], s1[1])
        self.assertTrue(np.all(s1 >= 0.0) and np.all(s1 <= 1.0))
        shares = gp.anova_variance_shares(lambda Z: mdl.predict(Z)[0],
                                          bounds, n_mc=1024, seed=5)
        self.assertAlmostEqual(float(np.sum(shares)), 100.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

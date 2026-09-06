"""test_rbf.py —— code/rbf.py（径向基函数代理模型）的单元测试。

GSDE（论文 07）在 126 维叶栅优化中选择 **三次 RBF + 线性尾项**，理由是高维下
RBF 的精度与训练成本都优于其他常见代理。本文件把 RBF 的两条理论性质（插值性、
线性再生性）与实际使用中的边界情况逐一验证。

运行方式（仓库根目录）：
    python tests/test_rbf.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import rbf


def smooth2d(X):
    X = np.atleast_2d(np.asarray(X, float))
    return np.sin(2.0 * X[:, 0]) + 0.5 * X[:, 1] ** 2


class TestInterpolation(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(11)
        self.X = rng.uniform(-2.0, 2.0, size=(50, 2))
        self.y = smooth2d(self.X)
        self.mdl = rbf.fit_rbf(self.X, self.y)

    def test_exact_interpolation(self):
        self.assertLess(np.max(np.abs(self.mdl(self.X) - self.y)), 1e-6)

    def test_test_set_accuracy(self):
        rng = np.random.default_rng(99)
        Xt = rng.uniform(-2.0, 2.0, size=(400, 2))
        self.assertGreater(self.mdl.r2(Xt, smooth2d(Xt)), 0.9)

    def test_leave_one_out(self):
        loo = rbf.leave_one_out_rmse(self.X, self.y)
        self.assertLess(loo, 0.2 * (self.y.max() - self.y.min()))

    def test_smooth_breaks_interpolation(self):
        ms = rbf.fit_rbf(self.X, self.y, smooth=1e-2)
        self.assertGreater(np.max(np.abs(ms(self.X) - self.y)), 1e-6)


class TestLinearReproduction(unittest.TestCase):
    def test_reproduces_linear(self):
        rng = np.random.default_rng(3)
        w = np.array([1.5, -2.0, 0.7])
        X = rng.uniform(-1.0, 1.0, size=(40, 2))
        mdl = rbf.fit_rbf(X, w[0] + X @ w[1:])
        Xt = rng.uniform(-1.0, 1.0, size=(200, 2))
        err = np.max(np.abs(mdl(Xt) - (w[0] + Xt @ w[1:])))
        self.assertLess(err, 1e-6, f"线性尾项未能再生线性函数，误差 {err:.2e}")


class TestKernels(unittest.TestCase):
    def test_all_kernels_usable(self):
        rng = np.random.default_rng(11)
        X = rng.uniform(-2.0, 2.0, size=(50, 2))
        y = smooth2d(X)
        Xt = rng.uniform(-2.0, 2.0, size=(200, 2))
        yt = smooth2d(Xt)
        for kern in (rbf.cubic_kernel, rbf.linear_kernel,
                     rbf.thin_plate_kernel,
                     lambda r: rbf.gaussian_kernel(r, eps=1.0)):
            with self.subTest(kernel=getattr(kern, "__name__", "gaussian")):
                m = rbf.fit_rbf(X, y, kernel=kern)
                self.assertGreater(m.r2(Xt, yt), 0.5)

    def test_kernel_values(self):
        r = np.array([0.0, 1.0, 2.0])
        np.testing.assert_allclose(rbf.cubic_kernel(r), [0.0, 1.0, 8.0])
        np.testing.assert_allclose(rbf.linear_kernel(r), r)
        self.assertAlmostEqual(rbf.thin_plate_kernel(np.array([0.0]))[0], 0.0)
        self.assertAlmostEqual(rbf.gaussian_kernel(np.array([0.0]), 1.0)[0], 1.0)


class TestBadInput(unittest.TestCase):
    def test_mismatched_shapes(self):
        with self.assertRaises(ValueError):
            rbf.fit_rbf(np.zeros((5, 2)), np.zeros(4))
        with self.assertRaises(ValueError):
            rbf.fit_rbf(np.zeros((3, 2)), np.zeros(3))   # 样本数 < d+2

    def test_wrong_prediction_dim(self):
        m = rbf.fit_rbf(np.random.default_rng(0).random((10, 2)),
                        np.random.default_rng(0).random(10))
        with self.assertRaises((ValueError, IndexError)):
            m(np.random.default_rng(1).random((3, 5)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

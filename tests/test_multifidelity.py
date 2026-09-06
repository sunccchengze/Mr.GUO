"""test_multifidelity.py —— code/multifidelity.py 的单元测试。

覆盖：AR1 Co-Kriging、论文 02 的自适应权重 ω 与阈值 T、层次聚类去重叠、
DBSCAN（论文 13）、EMFS 集成、以及多采集函数的对冲选择。

运行方式（仓库根目录）：
    python tests/test_multifidelity.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import multifidelity as mf


def lf_fun(X):
    X = np.atleast_2d(np.asarray(X, float))
    return (np.sin(2.0 * np.pi * X[:, 0]) + 0.5 * X[:, 1]).ravel()


def hf_fun(X):
    X = np.atleast_2d(np.asarray(X, float))
    return (1.6 * (np.sin(2.0 * np.pi * X[:, 0]) + 0.5 * X[:, 1])
            + 0.8 * (X[:, 0] - 0.5) ** 2).ravel()


class TestFilterGEI(unittest.TestCase):
    def test_omega_limits(self):
        w, T = mf.filter_gei_threshold(0.0, 1.0, y_hf_min=2.0, y_hf_mean=5.0)
        self.assertAlmostEqual(w, 1.0)
        self.assertAlmostEqual(T, 2.0)
        w, T = mf.filter_gei_threshold(1.0, 1.0, 2.0, 5.0)
        self.assertAlmostEqual(w, 0.5)
        self.assertAlmostEqual(T, 3.5)

    def test_monotonicity(self):
        """σ²_DF 越大（LF 与 HF 相关性越差）→ ω 越小、T 越靠近历史均值。"""
        ws = [mf.filter_gei_threshold(s, 1.0, 2.0, 5.0) for s in (0.0, 0.25, 1.0, 4.0, 25.0)]
        for i in range(len(ws) - 1):
            self.assertGreater(ws[i][0], ws[i + 1][0])
            self.assertLess(ws[i][1], ws[i + 1][1])
        self.assertLess(ws[-1][0], 0.2)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mf.filter_gei_threshold(1.0, 0.0, 1.0, 2.0)
        with self.assertRaises(ValueError):
            mf.filter_gei_threshold(-1.0, 1.0, 1.0, 2.0)


class TestDecluster(unittest.TestCase):
    def test_merge_nearest_only(self):
        X = np.array([[0.0], [0.01], [1.0], [5.0]])
        cl = mf.hierarchical_decluster(X, d_T=0.1)
        self.assertEqual(len(cl), 3)
        self.assertIn([0, 1], cl)
        self.assertEqual(sorted(sum(cl, [])), [0, 1, 2, 3])

    def test_threshold_extremes(self):
        X = np.array([[0.0], [0.01], [1.0], [5.0]])
        self.assertEqual(len(mf.hierarchical_decluster(X, d_T=10.0)), 1)
        self.assertEqual(len(mf.hierarchical_decluster(X, d_T=0.0)), 4)
        self.assertEqual(mf.hierarchical_decluster(np.zeros((0, 2)), 1.0), [])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mf.hierarchical_decluster(np.zeros((3, 2)), d_T=-1.0)


class TestFidelitySplit(unittest.TestCase):
    def test_split(self):
        pred = np.array([1.0, 3.0, 5.0])
        hf, lf = mf.fidelity_split(pred, T=3.5)
        self.assertEqual(list(hf), [0, 1])
        self.assertEqual(list(lf), [2])

    def test_budget(self):
        rep = mf.budget_report(10, 50, cost_ratio=0.1)
        self.assertAlmostEqual(rep["equivalent_hf"], 15.0)
        with self.assertRaises(ValueError):
            mf.budget_report(1, 1, cost_ratio=0.0)


class TestDBSCAN(unittest.TestCase):
    def test_two_clusters_and_noise(self):
        rng = np.random.default_rng(0)
        X = np.vstack([rng.normal(0.0, 0.05, size=(20, 2)),
                       rng.normal(5.0, 0.05, size=(20, 2)),
                       np.array([[20.0, 20.0]])])
        lab = mf.dbscan(X, eps=0.5, min_samples=4)
        self.assertEqual(len(set(lab) - {-1}), 2)
        self.assertEqual(lab[-1], -1)
        self.assertTrue(np.all(lab[:20] == lab[0]))
        self.assertTrue(np.all(lab[20:40] == lab[20]))
        self.assertNotEqual(lab[0], lab[20])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mf.dbscan(np.zeros((3, 2)), eps=0.0)
        with self.assertRaises(ValueError):
            mf.dbscan(np.zeros((3, 2)), eps=0.5, min_samples=0)


class TestCoKriging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20240905)
        cls.Xlf = rng.random((40, 2))
        cls.ylf = lf_fun(cls.Xlf)
        cls.Xhf = rng.random((6, 2))
        cls.yhf = hf_fun(cls.Xhf)
        cls.Xt = rng.random((300, 2))
        cls.yt = hf_fun(cls.Xt)
        cls.ck = mf.CoKriging().fit(cls.Xlf, cls.ylf, cls.Xhf, cls.yhf)

    @staticmethod
    def _r2(y, yhat):
        return 1.0 - np.sum((y - yhat) ** 2) / np.sum((y - np.mean(y)) ** 2)

    def test_beats_hf_only(self):
        mu, sd = self.ck.predict(self.Xt)
        r2_ck = self._r2(self.yt, mu)
        mu_hf, _ = mf._TinyKriging().fit(self.Xhf, self.yhf).predict(self.Xt)
        r2_hf = self._r2(self.yt, mu_hf)
        self.assertGreater(r2_ck, r2_hf)
        self.assertGreater(r2_ck, 0.8)
        self.assertTrue(np.all(sd >= 0.0))

    def test_rho_estimation(self):
        self.assertGreater(self.ck.rho, 0.8)
        self.assertLess(self.ck.rho, 2.5)

    def test_training_points(self):
        mu, _ = self.ck.predict(self.Xhf)
        scale = self.yhf.max() - self.yhf.min() + 1e-12
        self.assertLess(np.max(np.abs(mu - self.yhf)), 0.35 * scale)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mf.CoKriging().fit(np.zeros((3, 2)), np.zeros(3),
                               np.zeros((3, 3)), np.zeros(3))
        with self.assertRaises(ValueError):
            mf.CoKriging().fit(np.zeros((2, 2)), np.zeros(2),
                               np.zeros((2, 2)), np.zeros(2))


class TestEMFS(unittest.TestCase):
    def test_ensemble_runs_and_is_finite(self):
        rng = np.random.default_rng(7)
        Xlf = rng.random((40, 2))
        Xhf = rng.random((8, 2))
        em = mf.EMFSEnsemble(eps=0.9, min_samples=4).fit(Xlf, lf_fun(Xlf), Xhf, hf_fun(Xhf))
        Xt = rng.random((120, 2))
        mu, sd = em.predict(Xt)
        self.assertTrue(np.all(np.isfinite(mu)))
        self.assertTrue(np.all(sd >= 0.0))
        yt = hf_fun(Xt)
        r2 = 1.0 - np.sum((yt - mu) ** 2) / np.sum((yt - np.mean(yt)) ** 2)
        self.assertGreater(r2, 0.5, f"EMFS 精度过低：{r2:.3f}")


class TestHedge(unittest.TestCase):
    def test_uniform_when_tied(self):
        picks = [mf.hedge_choose([0.0, 0.0, 0.0], eta=1.0,
                                 rng=np.random.default_rng(s)) for s in range(300)]
        self.assertEqual(set(picks), {0, 1, 2})

    def test_prefers_higher_gain(self):
        picks = [mf.hedge_choose([0.0, 5.0, 0.0], eta=1.0,
                                 rng=np.random.default_rng(s)) for s in range(200)]
        self.assertGreater(np.mean(np.array(picks) == 1), 0.9)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            mf.hedge_choose([], eta=1.0)
        with self.assertRaises(ValueError):
            mf.hedge_choose([1.0], eta=0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

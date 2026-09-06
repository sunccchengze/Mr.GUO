"""test_optimizer.py —— code/optimizer.py（DE / PSO / CR-EI / EGO / GSDE）的单元测试。

运行方式（仓库根目录）：
    python tests/test_optimizer.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import optimizer


def branin(x) -> float:
    x = np.atleast_1d(np.asarray(x, float))
    x1, x2 = x[0], x[1]
    a, b, c, r, s, t = 1.0, 5.1 / (4 * np.pi ** 2), 5 / np.pi, 6.0, 10.0, 1 / (8 * np.pi)
    return float(a * (x2 - b * x1 ** 2 + c * x1 - r) ** 2 + s * (1 - t) * np.cos(x1) + s)


BOUNDS = [(-5.0, 10.0), (0.0, 15.0)]
FSTAR = 0.397887


def sphere(x) -> float:
    x = np.atleast_1d(np.asarray(x, float))
    return float(np.sum(x ** 2))


class TestDifferentialEvolution(unittest.TestCase):
    def test_converges_all_variants(self):
        for strat in ("best/1", "rand/1"):
            for cx in ("bin", "exp"):
                with self.subTest(strategy=strat, crossover=cx):
                    xb, fb, hist = optimizer.differential_evolution(
                        branin, BOUNDS, pop_size=30, max_nfe=1200,
                        strategy=strat, crossover=cx, seed=3, return_history=True)
                    self.assertLess(fb, 0.5, f"{strat}/{cx} 未收敛：{fb}")
                    self.assertLessEqual(hist[-1], hist[0] + 1e-12, "历史应单调不增")

    def test_sphere_high_dim(self):
        bounds = [(-5.12, 5.12)] * 10
        _, f, _ = optimizer.differential_evolution(
            sphere, bounds, pop_size=60, max_nfe=6000, seed=1, return_history=True)
        self.assertLess(f, 1.0, f"10 维 Sphere 未收敛：{f}")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            optimizer.differential_evolution(branin, BOUNDS, pop_size=3)
        with self.assertRaises(ValueError):
            optimizer.differential_evolution(branin, BOUNDS, strategy="cur/1")
        with self.assertRaises(ValueError):
            optimizer.differential_evolution(branin, BOUNDS, crossover="weird")


class TestPSO(unittest.TestCase):
    def test_converges(self):
        _, f, hist = optimizer.pso(branin, BOUNDS, n_particles=40, n_iter=200,
                                   seed=5, return_history=True)
        self.assertLess(f, 0.6, f"PSO 未收敛：{f}")
        self.assertLessEqual(hist[-1], hist[0] + 1e-12)

    def test_sphere(self):
        _, f = optimizer.pso(sphere, [(-2.0, 2.0)] * 5, n_particles=40,
                             n_iter=300, seed=2)
        self.assertLess(f, 1e-3, f"5 维 Sphere 未收敛：{f}")


class TestCR_EI(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.X = rng.random((200, 2))
        self.x_pbs = np.array([0.5, 0.5])
        self.d_T = 0.3
        self.mean = np.zeros(200)
        self.sd = np.ones(200)
        self.y = np.linspace(-3.0, 3.0, 200)

    def test_partitions_are_complementary(self):
        cei = optimizer.calibrated_ei(self.mean, self.sd, xi_calibrated=1.0)
        rei = optimizer.recalibrated_ei(self.mean, self.sd, 1.0, self.X,
                                        self.x_pbs, self.d_T)
        dist = np.linalg.norm(self.X - self.x_pbs, axis=1)
        delta1 = ((dist > 1e-3) & (dist <= self.d_T)).astype(float)
        np.testing.assert_allclose(cei * delta1 + rei, cei, atol=1e-12)
        near = dist <= self.d_T
        self.assertTrue(np.all(rei[near] == 0.0), "REI 不应在近处取点")
        self.assertTrue(np.any(rei[~near] > 0.0), "REI 应在远处有值")

    def test_scheduling_modes(self):
        r0 = optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y,
                                  self.x_pbs, self.d_T, n_breakthrough=0)
        self.assertEqual(r0["mode"], "EI")
        self.assertEqual(len(r0["indices"]), 1)
        r1 = optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y,
                                  self.x_pbs, self.d_T, n_breakthrough=5)
        self.assertIn(r1["mode"], ("EI+REI", "CEI+REI"))
        self.assertLessEqual(len(r1["indices"]), 2)
        self.assertTrue(all(0 <= i < 200 for i in r1["indices"]))

    def test_beta_raises_incumbent(self):
        a = optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y,
                                 self.x_pbs, self.d_T, beta=0.1, n_breakthrough=1)
        b = optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y,
                                 self.x_pbs, self.d_T, beta=0.5, n_breakthrough=1)
        self.assertGreater(b["xi_calibrated"], a["xi_calibrated"])
        self.assertGreater(a["xi_calibrated"], float(np.min(self.y)))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y[:10],
                                 self.x_pbs, self.d_T)
        with self.assertRaises(ValueError):
            optimizer.cr_ei_step(self.mean, self.sd, self.X, self.y,
                                 self.x_pbs, self.d_T, beta=1.5)


class TestEGO(unittest.TestCase):
    def test_improves_over_initial_design(self):
        xb, fb, hist = optimizer.ego(branin, BOUNDS, optimizer._DemoSurrogate,
                                     n_init=15, n_iter=40, n_candidates=1500,
                                     seed=11, return_history=True)
        self.assertLess(fb, 0.45, f"EGO 未收敛：{fb}")
        self.assertLess(hist[-1], hist[0], "EGO 应相对初始采样有改进")
        self.assertLessEqual(hist[-1], hist[0] + 1e-12)


class TestSurrogateAssistedDE(unittest.TestCase):
    def test_beats_random_search(self):
        xb, fb, hist = optimizer.surrogate_assisted_de(
            branin, BOUNDS, optimizer._DemoSurrogate, pop_size=20, top_T=5,
            pso_particles=10, pso_iters=20, max_nfe=240, seed=13,
            return_history=True)
        lo = np.array([b[0] for b in BOUNDS])
        sp = np.array([b[1] - b[0] for b in BOUNDS])
        rand = [min(branin(lo + np.random.default_rng(s).random(2) * sp)
                    for _ in range(240)) for s in (99, 7, 11)]
        self.assertLess(fb, float(np.mean(rand)),
                        f"GSDE({fb:.4f}) 未优于随机搜索均值({np.mean(rand):.4f})")
        self.assertLessEqual(hist[-1], hist[0] + 1e-12)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            optimizer.surrogate_assisted_de(branin, BOUNDS, optimizer._DemoSurrogate,
                                            pop_size=5, top_T=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)

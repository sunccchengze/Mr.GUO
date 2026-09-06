"""test_metrics.py —— code/metrics.py（叶轮机械气动 / 传热指标）的单元测试。

指标定义均为行业通行的教科书定义；本文件把"边界条件、量纲、口径"逐一钉死，
避免论文复现时出现"我说的 η 和你说的不一样"这类问题。

运行方式（仓库根目录）：
    python tests/test_metrics.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import metrics


class TestAveraging(unittest.TestCase):
    def test_area_average(self):
        self.assertAlmostEqual(metrics.area_average(np.full(10, 3.0), np.ones(10)), 3.0)
        self.assertAlmostEqual(
            metrics.area_average(np.array([1.0, 2.0]), np.array([3.0, 1.0])), 1.25)

    def test_mass_average_matches_area_with_same_weights(self):
        v = np.array([1.0, 5.0, 9.0])
        w = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(metrics.area_average(v, w), metrics.mass_average(v, w))

    def test_weighted_std(self):
        mu, sd = metrics.area_average_with_std(np.array([1.0, 3.0]), np.array([1.0, 1.0]))
        self.assertAlmostEqual(mu, 2.0)
        self.assertAlmostEqual(sd, 1.0)
        self.assertEqual(metrics.area_average_with_std(np.full(5, 2.0), np.ones(5))[1], 0.0)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            metrics.area_average(np.ones(3), np.ones(4))
        with self.assertRaises(ValueError):
            metrics.area_average(np.ones(3), np.zeros(3))
        with self.assertRaises(ValueError):
            metrics.area_average(np.ones(3), -np.ones(3))


class TestAero(unittest.TestCase):
    def test_loss_coefficient_bounds(self):
        self.assertAlmostEqual(metrics.total_pressure_loss_coefficient(100.0, 100.0, 90.0), 0.0)
        self.assertAlmostEqual(metrics.total_pressure_loss_coefficient(100.0, 90.0, 90.0), 1.0)
        with self.assertRaises(ValueError):
            metrics.total_pressure_loss_coefficient(100.0, 90.0, 100.0)

    def test_static_pressure_coefficient(self):
        self.assertAlmostEqual(
            metrics.static_pressure_coefficient(101325.0, 100000.0, 5000.0), 0.265, places=3)

    def test_turbine_efficiency(self):
        # 等熵过程 → 效率为 1
        Tout_ideal = 1600.0 * (550.0 / 1000.0) ** ((1.33 - 1.0) / 1.33)
        self.assertAlmostEqual(
            metrics.isentropic_efficiency(1000.0, 550.0, 1600.0, Tout_ideal, 1.33), 1.0, places=9)
        # 实际温降小于理想温降 → 效率 < 1
        eta = metrics.isentropic_efficiency(1000.0, 550.0, 1600.0, 1400.0, 1.33)
        self.assertGreater(eta, 0.8)
        self.assertLess(eta, 1.0)
        # 涡轮压比 > 1 非法
        with self.assertRaises(ValueError):
            metrics.isentropic_efficiency(550.0, 1000.0, 1600.0, 1250.0)

    def test_compressor_efficiency(self):
        eta = metrics.compressor_efficiency(100.0, 300.0, 288.0, 480.0, 1.4)
        self.assertGreater(eta, 0.0)
        self.assertLess(eta, 1.0)
        with self.assertRaises(ValueError):
            metrics.compressor_efficiency(300.0, 100.0, 288.0, 480.0)


class TestHeat(unittest.TestCase):
    def setUp(self):
        self.Tinf, self.Tc = 1500.0, 600.0

    def test_film_effectiveness_bounds(self):
        self.assertAlmostEqual(
            metrics.adiabatic_film_effectiveness(self.Tinf, self.Tinf, self.Tc), 0.0)
        self.assertAlmostEqual(
            metrics.adiabatic_film_effectiveness(self.Tinf, self.Tc, self.Tc), 1.0)
        self.assertAlmostEqual(
            metrics.adiabatic_film_effectiveness(self.Tinf, 1050.0, self.Tc), 0.5)

    def test_overall_cooling_effectiveness(self):
        self.assertAlmostEqual(
            metrics.overall_cooling_effectiveness(self.Tinf, 900.0, self.Tc), 2.0 / 3.0)
        self.assertAlmostEqual(
            metrics.overall_cooling_effectiveness(self.Tinf, self.Tinf, self.Tc), 0.0)

    def test_overall_ge_film_at_same_wall_temp(self):
        """同一壁温下，综合冷却效率应不低于气膜有效度（真实壁温 ≤ 绝热壁温）。"""
        self.assertGreaterEqual(
            metrics.overall_cooling_effectiveness(self.Tinf, 900.0, self.Tc),
            metrics.adiabatic_film_effectiveness(self.Tinf, 1000.0, self.Tc))

    def test_nusselt_roundtrip(self):
        h, L, k = 850.0, 0.02, 0.06
        nu = metrics.nusselt_number(h, L, k)
        self.assertAlmostEqual(nu, 283.3333333, places=4)
        self.assertAlmostEqual(metrics.heat_transfer_coefficient(nu, L, k), h, places=9)
        with self.assertRaises(ValueError):
            metrics.nusselt_number(h, L, 0.0)
        with self.assertRaises(ValueError):
            metrics.heat_transfer_coefficient(nu, 0.0, k)


class TestChangeReporting(unittest.TestCase):
    def test_relative_vs_percentage_point(self):
        # 论文 10 的 +0.42% 是"效率增量"，属百分点口径
        self.assertAlmostEqual(metrics.percentage_point_change(91.62, 91.20), 0.42, places=9)
        self.assertAlmostEqual(metrics.relative_change(91.62, 91.20), 0.4605, places=3)
        # 论文 09 的 −14.0% 是相对变化口径
        self.assertAlmostEqual(metrics.relative_change(0.0430, 0.0500), -14.0, places=6)
        with self.assertRaises(ValueError):
            metrics.relative_change(1.0, 0.0)

    def test_deviation_band(self):
        lo, hi = metrics.deviation_band(0.35, 0.05, k=2.0)
        self.assertAlmostEqual(lo, 0.25)
        self.assertAlmostEqual(hi, 0.45)


class TestDescribe(unittest.TestCase):
    def test_summary(self):
        rng = np.random.default_rng(5)
        x = rng.normal(10.0, 2.0, size=5000)
        s = metrics.describe(x)
        self.assertEqual(s["n"], 5000)
        self.assertAlmostEqual(s["mean"], 10.0, delta=0.2)
        self.assertAlmostEqual(s["std"], 2.0, delta=0.2)
        self.assertLessEqual(s["min"], s["p05"])
        self.assertLessEqual(s["p05"], s["p95"])
        self.assertLessEqual(s["p95"], s["max"])
        sw = metrics.describe(x, weights=np.ones_like(x))
        self.assertAlmostEqual(sw["mean"], s["mean"], places=9)
        with self.assertRaises(ValueError):
            metrics.describe(np.zeros(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)

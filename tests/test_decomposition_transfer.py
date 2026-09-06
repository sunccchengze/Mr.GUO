"""test_decomposition_transfer.py —— code/decomposition.py 与 code/transfer.py 的单元测试。

decomposition.py 对应论文 11（DA-EGO）的动态分解与聚合；
transfer.py 对应论文 08（SW-VAE / KT-ASO）的知识迁移链路。

运行方式（仓库根目录）：
    python tests/test_decomposition_transfer.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _path  # noqa: F401,E402

import numpy as np

import decomposition as dc
import transfer as tf


# --------------------------------------------------------------------------- decomposition
def truth(X):
    """(0,1) 强交互；(2,3) 弱交互；其余项可加分离（交互应恰为 0）。"""
    X = np.atleast_2d(np.asarray(X, float))
    return (5.0 * X[:, 0] * X[:, 1] + 0.3 * X[:, 2] * X[:, 3]
            + 1.0 * X[:, 2] + 0.8 * X[:, 3] ** 2 + 0.05 * X[:, 4])


class TestInteractionScores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bounds = [(0.0, 1.0)] * 5
        cls.scores = dc.interaction_scores(truth, cls.bounds, n_mc=4096, seed=3)

    def test_detects_strong_pair(self):
        top = max(self.scores.items(), key=lambda kv: kv[1])[0]
        self.assertEqual(top, (0, 1))
        self.assertGreater(self.scores[(0, 1)], 5 * self.scores[(0, 2)])

    def test_additive_pairs_are_zero(self):
        self.assertLess(self.scores[(0, 4)], 1e-12)
        self.assertLess(self.scores[(1, 4)], 1e-12)

    def test_weak_pair_detected_but_smaller(self):
        self.assertGreater(self.scores[(2, 3)], 0.0)
        self.assertLess(self.scores[(2, 3)], 0.05 * self.scores[(0, 1)])

    def test_all_non_negative(self):
        self.assertTrue(all(v >= 0 for v in self.scores.values()))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            dc.interaction_scores(truth, self.bounds, pairs=[(0, 0)])
        with self.assertRaises(ValueError):
            dc.interaction_scores(truth, self.bounds, pairs=[(0, 9)])


class TestPairSelection(unittest.TestCase):
    def test_partition(self):
        scores = dc.interaction_scores(truth, [(0.0, 1.0)] * 5, n_mc=2048, seed=3)
        sel = dc.select_interaction_pairs(scores, confirmed=[(0, 1)],
                                          n_suspected=3, threshold=1e-4)
        self.assertIn((0, 1), sel["confirmed"])
        self.assertNotIn((0, 1), sel["suspected"])
        self.assertLessEqual(len(sel["suspected"]), 3)
        self.assertGreaterEqual(len(sel["suspected"]), 1)
        self.assertIn((2, 3), sel["suspected"])
        self.assertEqual(len(sel["confirmed"]) + len(sel["suspected"])
                         + len(sel["ignored"]), len(scores))
        self.assertFalse(set(sel["confirmed"]) & set(sel["suspected"]))


class TestGrouping(unittest.TestCase):
    def test_pairs_grouped_together(self):
        groups = dc.group_variables(5, [(0, 1)])
        self.assertIn([0, 1], groups)
        self.assertEqual(len(groups), 4)
        self.assertEqual(sorted(sum(groups, [])), list(range(5)))

    def test_transitivity(self):
        groups = dc.group_variables(5, [(0, 1), (1, 4)])
        self.assertIn([0, 1, 4], groups)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            dc.group_variables(5, [(0, 7)])

    def test_subspace_bounds(self):
        bounds = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
        groups = dc.group_variables(3, [(0, 2)])
        sb = dc.subspace_bounds(bounds, groups)
        self.assertEqual(len(sb), len(groups))
        np.testing.assert_allclose(sb[0], np.array([[0.0, 1.0], [4.0, 5.0]]))


class TestElite(unittest.TestCase):
    def test_combine(self):
        elite = np.zeros(5)
        new = dc.combine_into_elite(elite, [([0, 1], np.array([0.9, 0.8])),
                                            ([2], np.array([0.3]))])
        np.testing.assert_allclose(new, [0.9, 0.8, 0.3, 0.0, 0.0])
        np.testing.assert_allclose(elite, np.zeros(5), err_msg="不应原地修改")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            dc.combine_into_elite(np.zeros(5), [([0, 1], np.array([1.0]))])
        with self.assertRaises(ValueError):
            dc.combine_into_elite(np.zeros(5), [([9], np.array([1.0]))])


class TestShrinkBounds(unittest.TestCase):
    def test_shrink_inside_original(self):
        bounds = [(0.0, 1.0)] * 5
        hist = [np.full(5, 0.4), np.full(5, 0.6)]
        nb = dc.shrink_bounds(bounds, hist, rate=0.5)
        self.assertTrue(np.all(nb[:, 0] >= 0.0) and np.all(nb[:, 1] <= 1.0))
        self.assertTrue(np.all((nb[:, 1] - nb[:, 0]) <= 0.5 + 1e-12))
        self.assertTrue(np.all((nb[:, 1] - nb[:, 0]) > 0))

    def test_single_history_no_shrink(self):
        bounds = [(0.0, 1.0)] * 3
        nb = dc.shrink_bounds(bounds, [np.full(3, 0.5)], rate=0.5)
        np.testing.assert_allclose(nb, np.asarray(bounds, float))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            dc.shrink_bounds([(0.0, 1.0)] * 3, [np.full(3, 0.4), np.full(3, 0.6)], rate=1.5)


# --------------------------------------------------------------------------- transfer
class TestMMD(unittest.TestCase):
    def test_properties(self):
        rng = np.random.default_rng(0)
        X = rng.normal(0.0, 1.0, size=(200, 3))
        Y = rng.normal(0.0, 1.0, size=(200, 3))
        Z = rng.normal(6.0, 1.0, size=(200, 3))
        self.assertAlmostEqual(tf.mmd2(X, X), 0.0, places=12)
        self.assertAlmostEqual(tf.mmd2(X, Y), tf.mmd2(Y, X), places=12)
        self.assertLess(tf.mmd2(X, Y), tf.mmd2(X, Z))
        self.assertGreaterEqual(tf.mmd2(X, Z), 0.0)

    def test_ranking(self):
        rng = np.random.default_rng(1)
        T = rng.normal(0.0, 1.0, size=(100, 2))
        near = rng.normal(0.2, 1.0, size=(100, 2))
        far = rng.normal(5.0, 1.0, size=(100, 2))
        ranked = tf.rank_source_tasks(T, [("far", far), ("near", near)])
        self.assertEqual([n for n, _ in ranked], ["near", "far"])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            tf.mmd2(np.zeros((3, 2)), np.zeros((3, 3)))
        with self.assertRaises(ValueError):
            tf.mmd2(np.zeros((0, 2)), np.zeros((3, 2)))


class TestNegativeTransfer(unittest.TestCase):
    def test_detection(self):
        r = tf.negative_transfer_check(0.30, 0.20)
        self.assertTrue(r["negative"])
        self.assertAlmostEqual(r["delta"], 0.10)
        self.assertAlmostEqual(r["ratio"], 0.5)
        self.assertFalse(tf.negative_transfer_check(0.15, 0.20)["negative"])
        self.assertFalse(tf.negative_transfer_check(0.2005, 0.20, tol=1e-3)["negative"])


class TestWeightedBatches(unittest.TestCase):
    def test_fixed_ratio(self):
        batches = tf.weighted_batches(n_source=40, n_unlabeled=1010,
                                      n_source_per_batch=8, ratio=1.0,
                                      n_batches=12, seed=1)
        self.assertEqual(len(batches), 12)
        for s, u in batches:
            self.assertEqual(s.size, 8)
            self.assertEqual(u.size, 8)
            self.assertTrue(np.all(s < 40) and np.all(u < 1010))
            self.assertEqual(len(set(s.tolist())), 8)

    def test_ratio_changes_unlabeled_count(self):
        b = tf.weighted_batches(40, 1010, 8, ratio=0.5, n_batches=3, seed=1)
        self.assertEqual(b[0][1].size, 16)

    def test_source_coverage(self):
        batches = tf.weighted_batches(40, 1010, 8, ratio=1.0, n_batches=12, seed=1)
        used = set(np.concatenate([b[0] for b in batches]).tolist())
        self.assertGreaterEqual(len(used), 30)

    def test_bad_input(self):
        for kw in [dict(n_source=0, n_unlabeled=10, n_source_per_batch=2),
                   dict(n_source=5, n_unlabeled=10, n_source_per_batch=9),
                   dict(n_source=5, n_unlabeled=10, n_source_per_batch=2, ratio=0.0),
                   dict(n_source=5, n_unlabeled=10, n_source_per_batch=2, n_batches=0),
                   dict(n_source=5, n_unlabeled=3, n_source_per_batch=2, ratio=0.1)]:
            with self.subTest(**kw):
                with self.assertRaises(ValueError):
                    tf.weighted_batches(**kw)


class TestGeometryLoss(unittest.TestCase):
    def test_trailing_edge_penalty(self):
        self.assertEqual(tf.trailing_edge_penalty(np.array([1.0, 1.2]), 1.0), 0.0)
        self.assertAlmostEqual(tf.trailing_edge_penalty(np.array([0.5]), 1.0), 0.25)
        self.assertAlmostEqual(tf.trailing_edge_penalty(np.array([0.0, 1.0]), 1.0), 0.5)

    def test_monotone(self):
        vals = [tf.trailing_edge_penalty(np.array([t]), 1.0) for t in (1.0, 0.8, 0.6, 0.4)]
        for i in range(len(vals) - 1):
            self.assertLess(vals[i], vals[i + 1])

    def test_vae_loss_weights(self):
        self.assertAlmostEqual(tf.vae_loss(0.0, 0.0, 0.0), 0.0)
        self.assertAlmostEqual(tf.vae_loss(1.0, 2.0, 3.0), 1.0 + 2.0 + 1.5e6, places=6)
        self.assertGreater(tf.vae_loss(0.0, 0.0, 1e-4), tf.vae_loss(1.0, 1.0, 0.0))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            tf.trailing_edge_penalty(np.array([1.0]), 0.0)
        with self.assertRaises(ValueError):
            tf.trailing_edge_penalty(np.zeros(0), 1.0)


class TestFFD(unittest.TestCase):
    def test_grid(self):
        grid, n = tf.ffd_control_grid(6, 5)
        self.assertEqual(grid.shape, (30, 2))
        self.assertEqual(n, 30)
        self.assertAlmostEqual(grid[0, 0], 0.0)
        self.assertAlmostEqual(grid[-1, 0], 1.0)
        with self.assertRaises(ValueError):
            tf.ffd_control_grid(1, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

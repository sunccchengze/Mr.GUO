"""sampling.py —— 试验设计（DoE）与尺度变换工具

本模块只依赖 numpy 与标准库，提供全书各讲算法都要用到的两件小事：

1. **拉丁超立方采样（Latin Hypercube Sampling, LHS）**
   把每一维等分成 n 个区间，每维在每个区间内恰好取一个点，再随机配对。
   相比纯随机采样，LHS 在样本量很少时也能保证一维投影上的均匀覆盖，
   这正是昂贵黑箱优化（HEB）第一步最需要的性质。

   依据：本全集的论文 07（GSDE）、论文 08（KT-ASO）、论文 11（DA-EGO）、
   论文 16（TNO）、论文 18（P-ResUNet）、论文 19（SHAP）均明确使用 LHS
   生成初始样本（如论文 11 用 50 个、论文 08 用 11·d_L 个）。

2. **单位立方体 <-> 物理空间的线性尺度变换**
   绝大多数代理模型假设输入已归一化到 [0,1]^d，因此需要在"优化器看到的
   空间"与"仿真器看到的空间"之间来回变换。

运行自检：
    python code/sampling.py
自检内容：LHS 的分层性质（每维每个区间恰一个点）、边界正确性、往返变换一致性。
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "latin_hypercube",
    "random_uniform",
    "to_unit",
    "from_unit",
    "scale_matrix",
    "sobol_first_order_indices",
]


def _as_bounds(bounds: Sequence[Sequence[float]]) -> np.ndarray:
    b = np.asarray(bounds, dtype=float)
    if b.ndim != 2 or b.shape[1] != 2:
        raise ValueError("bounds 必须是形如 [(lo, hi), ...] 的 (d, 2) 数组")
    if np.any(b[:, 1] <= b[:, 0]):
        raise ValueError("每个维度的上界必须严格大于下界")
    return b


def latin_hypercube(n: int,
                    dim: int,
                    rng: Optional[np.random.Generator] = None,
                    criterion: str = "random") -> np.ndarray:
    """生成 n 个 dim 维拉丁超立方样本，返回值域为 [0, 1]^dim。

    参数
    ----
    n      : 样本数（必须 >= 1）
    dim    : 维度（必须 >= 1）
    rng    : numpy 随机发生器；为 None 时用 default_rng()
    criterion :
        "random"  —— 每层内随机取点（标准 LHS）
        "center"  —— 每层取区间中点（即确定性分层，等价于均匀设计的近似）

    返回
    ----
    (n, dim) 数组，每行一个样本，取值在 [0, 1) 内。

    实现要点
    --------
    先对每一维独立生成一个 0..n-1 的随机排列（决定"第 k 个样本落在第几层"），
    再在层内加一个 [0,1) 的随机偏移。这样可保证：对任意一维，n 个样本
    恰好落在 n 个互不重叠的等宽区间中 —— 这就是 LHS 的"分层性"。
    """
    if n < 1 or dim < 1:
        raise ValueError("n 与 dim 都必须 >= 1")
    rng = np.random.default_rng() if rng is None else rng

    u = np.empty((n, dim), dtype=float)
    for j in range(dim):
        perm = rng.permutation(n)
        if criterion == "center":
            offset = 0.5
        elif criterion == "random":
            offset = rng.random(n)
        else:
            raise ValueError("criterion 只支持 'random' 或 'center'")
        u[:, j] = (perm + offset) / float(n)
    return u


def random_uniform(n: int,
                   bounds: Sequence[Sequence[float]],
                   rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """在给定 bounds 内生成 n 个均匀随机样本（作为 LHS 的对照基线）。"""
    b = _as_bounds(bounds)
    rng = np.random.default_rng() if rng is None else rng
    u = rng.random((n, b.shape[0]))
    return from_unit(u, b)


def to_unit(x: np.ndarray, bounds: Sequence[Sequence[float]]) -> np.ndarray:
    """把物理空间的点线性变换到 [0,1]^d。"""
    b = _as_bounds(bounds)
    x = np.atleast_2d(np.asarray(x, dtype=float))
    if x.shape[1] != b.shape[0]:
        raise ValueError("x 的维度与 bounds 不一致")
    return (x - b[:, 0]) / (b[:, 1] - b[:, 0])


def from_unit(u: np.ndarray, bounds: Sequence[Sequence[float]]) -> np.ndarray:
    """把 [0,1]^d 的点线性变换回物理空间。"""
    b = _as_bounds(bounds)
    u = np.atleast_2d(np.asarray(u, dtype=float))
    if u.shape[1] != b.shape[0]:
        raise ValueError("u 的维度与 bounds 不一致")
    return b[:, 0] + u * (b[:, 1] - b[:, 0])


def scale_matrix(bounds: Sequence[Sequence[float]]) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (下界向量, 缩放向量)，便于手写 x = lo + u * span。"""
    b = _as_bounds(bounds)
    return b[:, 0].copy(), (b[:, 1] - b[:, 0]).copy()


def sobol_first_order_indices(samples: np.ndarray, values: np.ndarray) -> np.ndarray:
    """给定 (n, d) 样本与 (n,) 目标值，用"按维分组求条件均值"估计一阶敏感性。

    这是一个**教学用的粗估计**（把每一维当作单一分组，直接比较组内均值波动
    与总体方差），用于快速判断"哪个变量看起来更重要"。

    严格的 Sobol 一阶指数需要成对（A/B/A_B^i）采样设计，本模块不提供；
    需要严格版本请使用蒙特卡洛 Sobol 设计。

    返回
    ----
    (d,) 数组，每个元素是该维的"解释方差比"（越大越重要）。
    """
    x = np.atleast_2d(np.asarray(samples, dtype=float))
    y = np.asarray(values, dtype=float).ravel()
    if x.shape[0] != y.shape[0]:
        raise ValueError("samples 与 values 的样本数不一致")
    n, d = x.shape
    total_var = np.var(y)
    if total_var <= 1e-300:
        return np.zeros(d)

    # 把每一维按中位数分成两组，比较组间均值差所解释的方差
    idx = np.zeros(d)
    for j in range(d):
        med = np.median(x[:, j])
        mask = x[:, j] <= med
        if mask.sum() < 2 or (~mask).sum() < 2:
            idx[j] = 0.0
            continue
        m1, m2 = y[mask].mean(), y[~mask].mean()
        n1, n2 = mask.sum(), (~mask).sum()
        # 组间方差（加权）
        grand = y.mean()
        between = (n1 * (m1 - grand) ** 2 + n2 * (m2 - grand) ** 2) / n
        idx[j] = between / total_var
    return np.clip(idx, 0.0, 1.0)


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)

    # 1) LHS 的分层性：每维在 n 个等宽区间内各恰有一个点
    n, d = 32, 6
    u = latin_hypercube(n, d, rng=rng)
    assert u.shape == (n, d), "LHS 形状错误"
    assert (u >= 0).all() and (u < 1).all(), "LHS 越界"
    for j in range(d):
        bins = np.floor(u[:, j] * n).astype(int)
        assert sorted(bins.tolist()) == list(range(n)), f"第 {j} 维不满足分层性"

    # 2) center 模式是确定性的，且每层落在中点附近
    uc = latin_hypercube(n, d, criterion="center")
    assert np.allclose(uc * n - np.floor(uc * n), 0.5), "center 模式未落在层中点"

    # 3) 尺度变换往返一致
    bounds = [(0.0, 1.0), (-2.0, 3.5), (1.0e-3, 2.0e-3)]
    up = to_unit(np.array([[0.5, 1.0, 1.5e-3]]), bounds)
    back = from_unit(up, bounds)
    assert np.allclose(back, [[0.5, 1.0, 1.5e-3]]), "往返变换不一致"
    lo, span = scale_matrix(bounds)
    # lo=[0,-2,1e-3]，span=[1,5.5,1e-3]，故 50% 处应为 [0.5, 0.75, 1.5e-3]
    assert np.allclose(lo + 0.5 * span, [0.5, 0.75, 1.5e-3]), "scale_matrix 结果不符"

    # 4) 敏感性粗估计：y 只依赖第 1 维时，第 1 维应显著更重要
    xs = rng.random((400, 3))
    ys = np.sin(3.0 * xs[:, 1]) + 0.02 * rng.standard_normal(400)
    s = sobol_first_order_indices(xs, ys)
    assert np.argmax(s) == 1, f"敏感性排序错误：{s}"

    # 5) 错误输入应报错
    for bad in ([(1.0, 0.0)], [(0.0, 1.0, 2.0)]):
        try:
            _as_bounds(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("非法 bounds 未报错")

    print("[sampling.py] 自检通过：LHS 分层性 / 边界 / 往返变换 / 敏感性排序 / 异常输入")


if __name__ == "__main__":
    _self_test()

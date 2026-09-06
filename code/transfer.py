"""transfer.py —— 知识迁移：源任务筛选、负迁移检测、样本加权（论文 08 / KT-ASO）

第 07 讲（**论文 08，SW-VAE / KT-ASO**）要解决的问题是：上一个型号的优化已经产生了
成百上千个样本，能不能把它们当成"免费的知识"用到新型号上，从而少做 CFD？原文的结论是
**取得相近最优解时，KT-ASO 至少减少 50% 的函数调用**［原文 P08 摘要］。

但这条路有个致命陷阱 —— **负迁移**。原文引用 Tripp et al. 的观察：VAE 所学设计空间中的
样本分布**大致正比于其在训练集中的出现频率**。源样本只有几十个（本文每轮用 **40** 个），
而无标签叶型有上千个（本文 **1010** 个），直接混训会让源样本的特征被彻底淹没；更糟的是
源样本是"已完成任务的优化解"，往往落在训练集分布之外，重参数化回来就已经失真。

本模块把这条链路中**可计算、可验证**的几个环节实现出来：

| 函数 | 作用 | 与论文的对应 |
| :--- | :--- | :--- |
| `mmd2` | 用 MMD² 量化源/目标样本的分布差异 | 判断源样本是否"落在分布之外" |
| `rank_source_tasks` | 按相似度给候选源任务排序 | 选哪个历史任务来迁移 |
| `negative_transfer_check` | 用验证集误差判定是否发生负迁移 | 原文反复强调的失败模式 |
| `weighted_batches` | 每 batch 固定 n_S/n_U 比例的采样器 | **SW-VAE 的核心**：论文取 n_S/n_U = 1 |
| `trailing_edge_penalty` | 叶片几何正则项 L_P | 原文公式：E[(max{0,(r_ref_min−r_min)/r_ref_min})²] |
| `vae_loss` | 加权总损失 | 原文：L = KL + λ₁·MSE + λ₂·L_P，λ₁=1、λ₂=5×10⁵ |
| `ffd_control_grid` | FFD 控制点网格 | 论文 08 的解码器末端 FFD 层：6×5 网格 |

**未包含的部分**：VAE 本身的网络结构与训练循环（需要深度学习框架，本代码库限定
只依赖 numpy）。"把源样本当**低保真数据**"的多保真 GP 部分，请用
`code/multifidelity.py` 的 `CoKriging`（把源任务样本作为 X_lf/y_lf、目标任务样本作为
X_hf/y_hf），这正是原文 ρ 相关结构的用法。

**只依赖 numpy**。运行自检：
    python code/transfer.py
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "mmd2", "rank_source_tasks", "negative_transfer_check",
    "weighted_batches", "trailing_edge_penalty", "vae_loss",
    "ffd_control_grid",
]

_TINY = 1e-12


# --------------------------------------------------------------------------- 分布差异
def mmd2(X: np.ndarray, Y: np.ndarray, sigma: Optional[float] = None) -> float:
    """高斯核 MMD²（最大均值差异的平方），衡量两组样本的分布差异。

        MMD² = E[k(x,x')] + E[k(y,y')] − 2·E[k(x,y)],   k(a,b)=exp(−‖a−b‖²/(2σ²))

    MMD² = 0 当且仅当两个分布相同（在核的特征空间意义下）；值越大差异越大。
    sigma 未给定时，用两组样本合并后的**中位距离**启发式设定（常用做法）。
    """
    X = np.atleast_2d(np.asarray(X, float))
    Y = np.atleast_2d(np.asarray(Y, float))
    if X.shape[1] != Y.shape[1]:
        raise ValueError("两组样本的维度不一致")
    if X.shape[0] == 0 or Y.shape[0] == 0:
        raise ValueError("样本集不能为空")

    def sqdist(A: np.ndarray, B: np.ndarray) -> np.ndarray:
        diff = A[:, None, :] - B[None, :, :]
        return np.einsum("nmk,nmk->nm", diff, diff)

    if sigma is None:
        allsq = np.concatenate([sqdist(X, X).ravel(), sqdist(Y, Y).ravel()])
        med = float(np.median(allsq))
        sigma = float(np.sqrt(med / 2.0)) if med > _TINY else 1.0
    if sigma <= 0:
        raise ValueError("sigma 必须为正")

    g = 2.0 * sigma ** 2
    kxx = float(np.mean(np.exp(-sqdist(X, X) / g)))
    kyy = float(np.mean(np.exp(-sqdist(Y, Y) / g)))
    kxy = float(np.mean(np.exp(-sqdist(X, Y) / g)))
    return float(max(kxx + kyy - 2.0 * kxy, 0.0))


def rank_source_tasks(X_target: np.ndarray,
                      sources: Sequence[Tuple[str, np.ndarray]],
                      sigma: Optional[float] = None) -> List[Tuple[str, float]]:
    """按"与目标的分布差异"给候选源任务排序（MMD² 越小越相似，越适合迁移）。

    返回 [(任务名, MMD²), ...]，按 MMD² 升序。
    """
    out = [(name, mmd2(X_target, Xs, sigma=sigma)) for name, Xs in sources]
    return sorted(out, key=lambda kv: kv[1])


# --------------------------------------------------------------------------- 负迁移判定
def negative_transfer_check(err_with_source: float,
                            err_without_source: float,
                            tol: float = 0.0) -> Dict[str, object]:
    """判定是否发生**负迁移**：加入源样本后，验证集误差反而变差。

    返回 dict：{'negative': bool, 'delta': 误差变化量, 'ratio': 相对恶化幅度}
    tol 允许一个容忍带（例如 1e-3），避免把数值噪声当成负迁移。
    """
    a = float(err_with_source)
    b = float(err_without_source)
    delta = a - b
    ratio = (delta / abs(b)) if abs(b) > _TINY else float("nan")
    return {"negative": bool(delta > tol), "delta": delta, "ratio": ratio}


# --------------------------------------------------------------------------- 样本加权批次（SW-VAE）
def weighted_batches(n_source: int,
                     n_unlabeled: int,
                     n_source_per_batch: int,
                     ratio: float = 1.0,
                     n_batches: int = 10,
                     seed: int = 0) -> List[Tuple[np.ndarray, np.ndarray]]:
    """生成**每个 batch 内源样本数与无标签样本数比例固定**的采样方案。

    这是 SW-VAE 的第一层解法［原文 P08 §第三步］：在每个 epoch 的每个 batch 中，
    固定源样本数 n⁽ˢ⁾ 与无标签样本数 n⁽ᵀ⁾ 的比例（**实验中取 n⁽ˢ⁾/n⁽ᵀ⁾ = 1**），
    分别从源样本集 X_S 与无标签集 X_U 中随机抽取。

    这样哪怕源样本只占全集的极小一部分，它们的特征也能被稳定地学进去，
    从而避免"源样本被淹没"。

    返回 [(源样本下标数组, 无标签样本下标数组), ...]，共 n_batches 个 batch。
    """
    if n_source <= 0 or n_unlabeled <= 0:
        raise ValueError("源样本数与无标签样本数均需为正")
    if n_source_per_batch <= 0 or n_source_per_batch > n_source:
        raise ValueError("每批源样本数应落在 [1, n_source]")
    if n_batches <= 0:
        raise ValueError("batch 数量必须为正")
    if ratio <= 0:
        raise ValueError("比例必须为正")

    n_unl_per_batch = max(1, int(round(n_source_per_batch / ratio)))
    if n_unl_per_batch > n_unlabeled:
        raise ValueError("按比例算出的无标签样本数超过其总量")

    rng = np.random.default_rng(seed)
    batches = []
    for _ in range(int(n_batches)):
        s = rng.choice(n_source, size=n_source_per_batch, replace=False)
        u = rng.choice(n_unlabeled, size=n_unl_per_batch, replace=False)
        batches.append((np.sort(s), np.sort(u)))
    return batches


# --------------------------------------------------------------------------- 几何正则项
def trailing_edge_penalty(r_min: np.ndarray, r_min_ref: float) -> float:
    """叶片几何专属正则项 L_P［原文 P08 公式］：

        L_P = E[ ( max{ 0, (r_min^ref − r_min) / r_min^ref } )² ]

    含义：**约束尾缘不薄于基准**，防止生成畸形叶型。
    r_min 是一批叶型的尾缘最小厚度（或半径），r_min^ref 是基准值。
    """
    r = np.asarray(r_min, float).ravel()
    if r.size == 0:
        raise ValueError("r_min 不能为空")
    if abs(float(r_min_ref)) <= _TINY:
        raise ValueError("基准尾缘厚度 r_min^ref 必须非零")
    viol = np.maximum(0.0, (float(r_min_ref) - r) / float(r_min_ref))
    return float(np.mean(viol ** 2))


def vae_loss(kl: float, mse: float, lp: float,
             lam1: float = 1.0, lam2: float = 500000.0) -> float:
    """SW-VAE 的总损失［原文 P08 公式］：L = KL + λ₁·MSE + λ₂·L_P。

    实验取值 **λ₁ = 1、λ₂ = 500000**（原文明确给出）。
    """
    return float(kl) + float(lam1) * float(mse) + float(lam2) * float(lp)


# --------------------------------------------------------------------------- FFD 控制网格
def ffd_control_grid(nu: int = 6, nv: int = 5) -> Tuple[np.ndarray, int]:
    """生成 FFD（自由变形）控制点网格的坐标与总数。

    论文 08 在解码器末端嵌入 FFD 层，**控制点网格为 6×5，主动变量共 50 个**
    ［原文 Table 3、§5.2］，用以保证生成叶型的光顺性。

    返回 (坐标数组 (nu·nv, 2), 控制点总数)。
    """
    if nu < 2 or nv < 2:
        raise ValueError("网格至少为 2×2")
    u = np.linspace(0.0, 1.0, int(nu))
    v = np.linspace(0.0, 1.0, int(nv))
    U, V = np.meshgrid(u, v, indexing="ij")
    return np.column_stack([U.ravel(), V.ravel()]), int(nu) * int(nv)


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)

    # ---- 1) MMD²
    X = rng.normal(0.0, 1.0, size=(200, 3))
    Y = rng.normal(0.0, 1.0, size=(200, 3))
    Z = rng.normal(6.0, 1.0, size=(200, 3))
    assert abs(mmd2(X, X)) < 1e-12, "同分布样本与自身的 MMD² 应为 0"
    assert abs(mmd2(X, Y) - mmd2(Y, X)) < 1e-12, "MMD² 应对称"
    assert mmd2(X, Y) < mmd2(X, Z), "分布差异更大的一组 MMD² 应更大"
    assert mmd2(X, Y) >= 0.0, "MMD² 不应为负"

    # ---- 2) 源任务排序：越相似的排得越前
    T = rng.normal(0.0, 1.0, size=(100, 2))
    S_near = rng.normal(0.2, 1.0, size=(100, 2))
    S_far = rng.normal(5.0, 1.0, size=(100, 2))
    ranked = rank_source_tasks(T, [("far", S_far), ("near", S_near)])
    assert [n for n, _ in ranked] == ["near", "far"], f"源任务排序错误：{ranked}"

    # ---- 3) 负迁移判定
    r = negative_transfer_check(0.30, 0.20)
    assert r["negative"] and abs(r["delta"] - 0.10) < 1e-12, "负迁移判定错误"
    assert abs(r["ratio"] - 0.5) < 1e-12, "相对恶化幅度计算错误"
    r2 = negative_transfer_check(0.15, 0.20)
    assert not r2["negative"], "误差下降不应判为负迁移"
    assert negative_transfer_check(0.2005, 0.20, tol=1e-3)["negative"] is False, \
        "容忍带内的波动不应判为负迁移"

    # ---- 4) SW-VAE 的加权批次采样：每个 batch 内源/无标签比例固定
    batches = weighted_batches(n_source=40, n_unlabeled=1010,
                               n_source_per_batch=8, ratio=1.0,
                               n_batches=12, seed=1)
    assert len(batches) == 12, "batch 数量不对"
    for s_idx, u_idx in batches:
        assert s_idx.size == 8, "每个 batch 的源样本数不固定"
        assert u_idx.size == 8, "ratio=1 时无标签样本数应与源样本数相同"
        assert np.all(s_idx < 40) and np.all(u_idx < 1010), "下标越界"
        assert len(set(s_idx.tolist())) == s_idx.size, "batch 内源样本重复"
    # 比例随 ratio 变化
    b2 = weighted_batches(40, 1010, 8, ratio=0.5, n_batches=3, seed=1)
    assert b2[0][1].size == 16, "ratio=0.5 时无标签样本数应为源样本的 2 倍"
    # 源样本被"轮转"使用：多个 batch 合起来应覆盖到大部分源样本
    used = set(np.concatenate([b[0] for b in batches]).tolist())
    assert len(used) >= 30, f"源样本覆盖率偏低：{len(used)}/40"

    # ---- 5) 尾缘正则项 L_P
    assert trailing_edge_penalty(np.array([1.0, 1.2]), r_min_ref=1.0) == 0.0, \
        "不薄于基准时惩罚应为 0"
    p = trailing_edge_penalty(np.array([0.5]), r_min_ref=1.0)
    assert abs(p - 0.25) < 1e-12, f"半厚时的惩罚应为 0.25，实为 {p}"
    p2 = trailing_edge_penalty(np.array([0.0, 1.0]), r_min_ref=1.0)
    assert abs(p2 - 0.5) < 1e-12, f"期望 0.5，实为 {p2}"
    # 越薄惩罚越大（单调）
    vals = [trailing_edge_penalty(np.array([t]), 1.0) for t in (1.0, 0.8, 0.6, 0.4)]
    assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), "L_P 应随厚度减小而增大"

    # ---- 6) VAE 总损失：λ₁=1、λ₂=5×10⁵（原文取值）
    assert abs(vae_loss(0.0, 0.0, 0.0)) < 1e-12
    assert abs(vae_loss(1.0, 2.0, 3.0) - (1.0 + 2.0 + 1.5e6)) < 1e-6, "损失加权错误"
    assert vae_loss(0.0, 0.0, 1e-4) > vae_loss(1.0, 1.0, 0.0), \
        "尾缘惩罚被 λ₂ 放大后应主导损失（这正是原文取 λ₂=5e5 的用意）"

    # ---- 7) FFD 控制点网格：论文 08 为 6×5
    grid, n = ffd_control_grid(6, 5)
    assert grid.shape == (30, 2) and n == 30, f"6×5 网格应有 30 个控制点，实为 {n}"
    assert abs(grid[0, 0]) < 1e-12 and abs(grid[-1, 0] - 1.0) < 1e-12, "网格端点不对"

    # ---- 8) 异常输入
    for bad in [lambda: mmd2(np.zeros((3, 2)), np.zeros((3, 3))),
                lambda: mmd2(np.zeros((0, 2)), np.zeros((3, 2))),
                lambda: weighted_batches(0, 10, 2),
                lambda: weighted_batches(5, 10, 9),
                lambda: weighted_batches(5, 10, 2, ratio=0.0),
                lambda: weighted_batches(5, 10, 2, n_batches=0),
                lambda: weighted_batches(5, 3, 2, ratio=0.1),
                lambda: trailing_edge_penalty(np.array([1.0]), 0.0),
                lambda: trailing_edge_penalty(np.zeros(0), 1.0),
                lambda: ffd_control_grid(1, 5)]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")

    print(f"[transfer.py] 自检通过：MMD²(近 {mmd2(T, S_near):.4f} < 远 {mmd2(T, S_far):.4f}) / "
          f"源任务排序 / 负迁移判定 / 加权批次(8+8) / L_P / 损失加权 / FFD 6×5={n}")


if __name__ == "__main__":
    _self_test()

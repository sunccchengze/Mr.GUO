"""moo.py —— 多目标优化：非支配排序、拥挤距离、NSGA-II 与性能评价指标

本全集中有两处明确使用 **NSGA-II** 做多目标优化：
  * **论文 16（第 10 讲，TNO）**：NSGA-II，种群 30、代数 100［原文 P16 Table 10］
  * **论文 15（第 14 讲，流固耦合数字孪生）**：NSGA-II，种群 100、每代 10 个子代，
    以 POD 模态系数为设计变量，优化目标为效率与最大应力［原文 P15 §III］
此外，第 16 讲与第 20 讲在"审稿人批判"里都指出：**只做若干次单目标优化，无法刻画
目标之间的权衡曲面（Pareto 前沿）**，因此"最佳折中方案"其实没被真正找到
［原文 P16 §局限；原文 P05 讨论］。多目标模块因此是本代码库必要的一环。

本模块提供：
  * `dominates` / `non_dominated_sort` / `crowding_distance` —— NSGA-II 的两个核心算子
  * `nsga2` —— 完整的多目标进化算法（SBX 交叉 + 多项式变异 + (μ+λ) 精英保留）
  * `hypervolume_2d` / `hypervolume_mc` —— 超体积指标（2 目标精确、多目标蒙特卡洛）
  * `igd` / `spread` —— 与参考前沿的距离与分布均匀性
  * `pareto_front` —— 从一堆解里筛出非支配解

**只依赖 numpy**。运行自检：
    python code/moo.py
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "dominates", "non_dominated_sort", "crowding_distance", "pareto_front",
    "nsga2", "hypervolume_2d", "hypervolume_mc", "igd", "spread",
]

_TINY = 1e-12


# --------------------------------------------------------------------------- 支配关系
def dominates(a: Sequence[float], b: Sequence[float]) -> bool:
    """（最小化意义下）a 支配 b：a 在所有目标上不劣于 b，且至少一维严格更优。"""
    a = np.asarray(a, float).ravel()
    b = np.asarray(b, float).ravel()
    if a.size != b.size:
        raise ValueError("目标维数不一致")
    return bool(np.all(a <= b) and np.any(a < b))


def non_dominated_sort(F: np.ndarray) -> Tuple[np.ndarray, List[List[int]]]:
    """快速非支配排序（NSGA-II 原文算法）。

    返回 (rank, fronts)：rank[i] 是个体 i 所属前沿编号（0 为最优前沿），
    fronts[k] 是第 k 层前沿的个体下标列表。
    """
    F = np.asarray(F, float)
    n = F.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int), []

    # 暴力 O(n²m)：n 为种群规模（几十~几百），完全够用，代码也最直白
    dom_sets: List[List[int]] = [[] for _ in range(n)]   # i 支配了谁
    be_dominated = np.zeros(n, dtype=int)                # 有多少个体支配 i
    for i in range(n):
        for j in range(i + 1, n):
            if dominates(F[i], F[j]):
                dom_sets[i].append(j)
                be_dominated[j] += 1
            elif dominates(F[j], F[i]):
                dom_sets[j].append(i)
                be_dominated[i] += 1

    rank = np.full(n, -1, dtype=int)
    fronts: List[List[int]] = []
    cur = [i for i in range(n) if be_dominated[i] == 0]
    k = 0
    while cur:
        fronts.append(sorted(cur))
        for i in cur:
            rank[i] = k
        nxt: List[int] = []
        for i in cur:
            for j in dom_sets[i]:
                be_dominated[j] -= 1
                if be_dominated[j] == 0:
                    nxt.append(j)
        cur = nxt
        k += 1
    return rank, fronts


def crowding_distance(F: np.ndarray, front: Sequence[int]) -> np.ndarray:
    """同一前沿内的拥挤距离（边界个体记为 +inf，保证多样性）。

    距离越大代表该个体周围越"空旷"，越应被保留。
    """
    F = np.asarray(F, float)
    idx = list(front)
    m = len(idx)
    dist = np.zeros(m)
    if m <= 2:
        dist[:] = np.inf
        return dist

    sub = F[idx]
    rng = sub.max(axis=0) - sub.min(axis=0)
    for j in range(F.shape[1]):
        order = np.argsort(sub[:, j])
        dist[order[0]] = np.inf
        dist[order[-1]] = np.inf
        span = rng[j]
        if span <= _TINY:
            continue
        for t in range(1, m - 1):
            dist[order[t]] += (sub[order[t + 1], j] - sub[order[t - 1], j]) / span
    return dist


def pareto_front(F: np.ndarray) -> np.ndarray:
    """返回非支配解的下标（第 0 层前沿）。"""
    _, fronts = non_dominated_sort(F)
    return np.array(fronts[0], dtype=int)


# --------------------------------------------------------------------------- 遗传算子
def _sbx(p1: np.ndarray, p2: np.ndarray, eta: float, rng: np.random.Generator,
         lo: np.ndarray, hi: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """模拟二进制交叉 SBX。"""
    u = rng.random(p1.size)
    beta = np.where(u <= 0.5,
                    (2.0 * u) ** (1.0 / (eta + 1.0)),
                    (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (eta + 1.0)))
    c1 = 0.5 * ((1 + beta) * p1 + (1 - beta) * p2)
    c2 = 0.5 * ((1 - beta) * p1 + (1 + beta) * p2)
    return np.clip(c1, lo, hi), np.clip(c2, lo, hi)


def _poly_mutate(x: np.ndarray, eta: float, pm: float, rng: np.random.Generator,
                 lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """多项式变异。"""
    out = x.copy()
    mask = rng.random(x.size) < pm
    if not np.any(mask):
        return out
    u = rng.random(np.sum(mask))
    delta = np.where(u < 0.5,
                     (2.0 * u) ** (1.0 / (eta + 1.0)) - 1.0,
                     1.0 - (2.0 * (1.0 - u)) ** (1.0 / (eta + 1.0)))
    out[mask] = out[mask] + delta * (hi[mask] - lo[mask])
    return np.clip(out, lo, hi)


# --------------------------------------------------------------------------- NSGA-II
def nsga2(func: Callable[[np.ndarray], np.ndarray],
          bounds: Sequence[Tuple[float, float]],
          pop_size: int = 100,
          n_gen: int = 100,
          n_offspring: Optional[int] = None,
          eta_c: float = 20.0,
          eta_m: float = 20.0,
          p_cross: float = 0.9,
          seed: int = 0,
          return_history: bool = False):
    """NSGA-II 主循环（(μ+λ) 精英保留）。

    参数
    ----
    func         : 目标函数，输入 (d,) 或 (n,d)，输出 (m,) 或 (n,m)；统一按**最小化**
    bounds       : 变量上下界
    pop_size     : 种群规模 μ（论文 16 用 30，论文 15 用 100）
    n_gen        : 代数（论文 16 用 100 代）
    n_offspring  : 每代子代数 λ，默认 = pop_size（论文 15 用每代 10 个子代）
    return_history : 是否返回每代的最优目标值轨迹

    返回 (X, F) 或 (X, F, history)。
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    d = bounds.shape[0]
    lam = int(n_offspring) if n_offspring else int(pop_size)
    pm = 1.0 / d

    def evaluate(P: np.ndarray) -> np.ndarray:
        F = np.asarray(func(P), float)
        if F.ndim == 1:
            F = F.reshape(1, -1)
        return F

    # 初始化：均匀随机种群
    P = lo + rng.random((pop_size, d)) * (hi - lo)
    F = evaluate(P)
    m = F.shape[1]
    history: List[float] = []

    for _ in range(n_gen):
        # --- 繁殖
        children = []
        while len(children) < lam:
            i, j = rng.integers(0, pop_size, size=2)
            if rng.random() < p_cross:
                c1, c2 = _sbx(P[i], P[j], eta_c, rng, lo, hi)
            else:
                c1, c2 = P[i].copy(), P[j].copy()
            children.append(_poly_mutate(c1, eta_m, pm, rng, lo, hi))
            if len(children) < lam:
                children.append(_poly_mutate(c2, eta_m, pm, rng, lo, hi))
        C = np.array(children[:lam])
        FC = evaluate(C)

        # --- (μ+λ) 合并后按 非支配层级 → 拥挤距离 排序截断
        Pall = np.vstack([P, C])
        Fall = np.vstack([F, FC])
        rank, fronts = non_dominated_sort(Fall)
        keep: List[int] = []
        for fr in fronts:
            if len(keep) + len(fr) <= pop_size:
                keep.extend(fr)
            else:
                cd = crowding_distance(Fall, fr)
                order = np.argsort(-cd)          # 拥挤距离大的优先
                need = pop_size - len(keep)
                keep.extend(np.array(fr)[order][:need].tolist())
                break
        P, F = Pall[keep], Fall[keep]

        if return_history:
            history.append(float(np.min(F[:, 0])))
    return (P, F, np.array(history)) if return_history else (P, F)


# --------------------------------------------------------------------------- 评价指标
def hypervolume_2d(F: np.ndarray, ref: Sequence[float]) -> float:
    """2 目标超体积（精确，梯形累加法）。ref 为被所有解支配的参考点。"""
    F = np.asarray(F, float)
    ref = np.asarray(ref, float).ravel()
    if F.size == 0:
        return 0.0
    front = F[pareto_front(F)]
    front = front[np.argsort(front[:, 0])]
    hv = 0.0
    for k in range(len(front)):
        width = (ref[0] - front[k, 0]) if k == len(front) - 1 \
            else (front[k + 1, 0] - front[k, 0])
        hv += width * (ref[1] - front[k, 1])
    return float(max(hv, 0.0))


def hypervolume_mc(F: np.ndarray, ref: Sequence[float], n_mc: int = 100000,
                   seed: int = 0) -> float:
    """任意目标数的超体积（蒙特卡洛估计）：在 [最优点, ref] 盒子里随机撒点，
    统计被至少一个解支配的比例，乘以盒子体积。"""
    F = np.asarray(F, float)
    ref = np.asarray(ref, float).ravel()
    if F.size == 0:
        return 0.0
    lo = np.minimum(F.min(axis=0), ref)
    box = float(np.prod(ref - lo))
    if box <= _TINY:
        return 0.0
    rng = np.random.default_rng(seed)
    pts = lo + rng.random((n_mc, F.shape[1])) * (ref - lo)
    hit = np.zeros(n_mc, dtype=bool)
    for i in range(F.shape[0]):
        hit |= np.all(F[i] <= pts, axis=1)
    return float(box * np.mean(hit))


def igd(F: np.ndarray, ref_front: np.ndarray) -> float:
    """反世代距离 IGD：参考前沿上每个点到最近解的平均距离（越小越好）。"""
    F = np.asarray(F, float)
    R = np.asarray(ref_front, float)
    if F.size == 0 or R.size == 0:
        return float("inf")
    d2 = np.sum((R[:, None, :] - F[None, :, :]) ** 2, axis=2)
    return float(np.mean(np.sqrt(np.min(d2, axis=1))))


def spread(F: np.ndarray) -> float:
    """分布均匀性（越小越均匀）：前沿上相邻点距离的标准差除以均值。

    仅对 2 目标有意义；目标数 >2 时退化为对第一维排序后的相邻距离统计。
    """
    front = np.asarray(F, float)
    if front.shape[0] < 3:
        return 0.0
    front = front[np.argsort(front[:, 0])]
    gaps = np.linalg.norm(np.diff(front, axis=0), axis=1)
    mean = float(np.mean(gaps))
    if mean <= _TINY:
        return 0.0
    return float(np.std(gaps) / mean)


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)

    # 1) 支配关系
    assert dominates([1, 1], [2, 2]), "支配判定错误"
    assert not dominates([1, 2], [2, 1]), "不可比却判为支配"
    assert not dominates([1, 1], [1, 1]), "相同点不应互相支配"
    assert not dominates([2, 2], [1, 1]), "支配方向反了"

    # 2) 非支配排序：构造三层前沿
    F = np.array([[1.0, 5.0], [2.0, 4.0], [3.0, 3.0], [4.0, 2.0], [5.0, 1.0],
                  [2.0, 6.0], [3.0, 5.0], [6.0, 6.0]])
    rank, fronts = non_dominated_sort(F)
    assert len(fronts) == 3, f"前沿层数应为 3，实为 {len(fronts)}"
    assert fronts[0] == [0, 1, 2, 3, 4], f"第一层前沿不对：{fronts[0]}"
    assert fronts[1] == [5, 6], f"第二层前沿不对：{fronts[1]}"
    assert fronts[2] == [7], f"第三层前沿不对：{fronts[2]}"
    assert np.array_equal(rank, [0, 0, 0, 0, 0, 1, 1, 2]), "rank 数组不对"
    assert set(pareto_front(F).tolist()) == {0, 1, 2, 3, 4}, "pareto_front 不对"

    # 3) 拥挤距离：边界必须最大
    cd = crowding_distance(F, fronts[0])
    assert np.isinf(cd[0]) and np.isinf(cd[-1]), "边界个体拥挤距离应为 inf"
    assert cd[2] > 0, "中间个体拥挤距离应为正"

    # 4) 超体积：加入更优解后 HV 必须变大；MC 估计应接近 2 目标精确值
    ref = [6.5, 6.5]
    hv1 = hypervolume_2d(np.array([[3.0, 3.0]]), ref)
    hv2 = hypervolume_2d(np.array([[3.0, 3.0], [2.0, 2.0]]), ref)
    assert hv2 > hv1 > 0, "超体积单调性错误"
    hvmc = hypervolume_mc(np.array([[3.0, 3.0], [2.0, 2.0]]), ref, n_mc=200000, seed=1)
    assert abs(hvmc - hv2) / hv2 < 0.02, f"MC 超体积与精确值偏差过大：{hvmc} vs {hv2}"

    # 5) IGD：解集越贴近参考前沿，IGD 越小；重复解不降低 IGD
    ref_front = np.column_stack([np.linspace(0, 1, 21), 1 - np.linspace(0, 1, 21) ** 2])
    good = ref_front.copy()
    bad = ref_front + 0.5
    assert igd(good, ref_front) < igd(bad, ref_front), "IGD 未反映贴近程度"
    assert abs(igd(good, ref_front)) < 1e-9, "完全重合时 IGD 应为 0"

    # 6) NSGA-II 真的能逼近已知 Pareto 前沿
    #    经典双目标问题：f1 = x1，f2 = g·(1 - sqrt(x1/g))，g = 1 + 9·mean(x2:)
    def zdt1_like(P: np.ndarray) -> np.ndarray:
        P = np.atleast_2d(np.asarray(P, float))
        f1 = P[:, 0]
        g = 1.0 + 9.0 * np.mean(P[:, 1:], axis=1)
        f2 = g * (1.0 - np.sqrt(np.maximum(f1 / g, 0.0)))
        return np.column_stack([f1, f2])

    bounds = [(0.0, 1.0)] * 6
    X, Fp, hist = nsga2(zdt1_like, bounds, pop_size=60, n_gen=120,
                        seed=7, return_history=True)
    pf = Fp[pareto_front(Fp)]
    assert pf.shape[0] >= 40, f"非支配解数量偏少：{pf.shape[0]}"
    assert np.min(pf[:, 0]) < 0.05, "未能找到 f1 极小端"
    assert np.min(pf[:, 1]) < 0.15, "未能找到 f2 极小端"
    # 前沿上任意两点不应互相支配
    for i in range(0, pf.shape[0], 7):
        for j in range(0, pf.shape[0], 7):
            if i != j:
                assert not dominates(pf[i], pf[j]), "输出解集中存在互相支配的点"

    ref_true = np.column_stack([np.linspace(0, 1, 51), 1 - np.sqrt(np.linspace(0, 1, 51))])
    igd_now = igd(pf, ref_true)
    assert igd_now < 0.05, f"IGD 偏大，前沿质量不足：{igd_now:.4f}"
    assert spread(pf) < 2.0, f"前沿分布过于不均：{spread(pf):.3f}"

    # 7) 进化过程应当是"有效"的：跑到 120 代的前沿应优于只跑 20 代
    _, F_short, _ = nsga2(zdt1_like, bounds, pop_size=60, n_gen=20, seed=7,
                          return_history=True)
    igd_short = igd(F_short[pareto_front(F_short)], ref_true)
    assert igd_now < igd_short, "多跑代数后前沿质量没有提升"

    # 8) 异常输入
    try:
        dominates([1, 2], [1, 2, 3])
    except ValueError:
        pass
    else:
        raise AssertionError("目标维数不一致未报错")
    assert igd(np.zeros((0, 2)), ref_true) == float("inf"), "空解集 IGD 应为 inf"
    assert hypervolume_2d(np.zeros((0, 2)), [1, 1]) == 0.0, "空解集 HV 应为 0"

    print(f"[moo.py] 自检通过：排序3层 / 拥挤距离 / HV单调(MC误差{abs(hvmc - hv2) / hv2:.2%}) / "
          f"NSGA-II 前沿 {pf.shape[0]} 点，IGD={igd_now:.4f}")


if __name__ == "__main__":
    _self_test()

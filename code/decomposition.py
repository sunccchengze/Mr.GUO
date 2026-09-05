"""decomposition.py —— 高维分解：变量交互检测、子空间分组、精英点聚合（DA-EGO）

第 04 讲（**论文 11，DA-EGO**）要解决的是第 03 讲（论文 07，GSDE）留下的另一个方向：
GSDE 选择"放弃贝叶斯、拥抱进化"，DA-EGO 则反问"能不能改造贝叶斯框架本身来扛高维"。
它的答案是 **动态分解与聚合**：

    [知识] → 构造子任务（分解方案 + 搜索范围）
                ↓
         各子空间独立做基于代理的优化
                ↓
       子任务数据挖掘（摄动法 + ANOVA 检测交互）
                ↓
    [知识更新] → 下一轮的分解方案与搜索范围

其中的三个关键构件，本模块都给出了可运行实现：

| 函数 | 对应论文 11 的环节 |
| :--- | :--- |
| `interaction_scores` | 变量交互强度打分（对应原文的 PCE 灵敏度系数 SPCE_ij） |
| `select_interaction_pairs` | 把变量对分成 **确认交互 P_C / 疑似交互 P_S / 非交互** |
| `group_variables` | 据已确认的交互对把 d 维空间切成若干低维子空间 |
| `combine_into_elite` | **精英点（elite-point）**：把各子空间的最优解拼回全空间 |
| `shrink_bounds` | 依据历史精英点收缩搜索范围 |

> ⚠️ **两处必须说清楚的实现差异**：
> 1. 原文的交互打分用**多项式混沌展开（PCE）的灵敏度系数 SPCE_ij**；本模块用的是
>    **在代理模型上做蒙特卡洛 ANOVA 的二阶交互效应**。PCE 需要专门的基函数与系数
>    求解（且原文自己都承认"高维 PCE 代理精度有限，会导致交互变量对选取出现误差"），
>    本实现选择了一个同样基于方差分解、但更省事且行为可预期的替代方案。
> 2. 原文 P_S 中的疑似交互还要**再用低维代理模型验证确认**；本模块把这一步留成
>     `confirm_pairs` 的回调接口（可用 `code/gp.py` 的 Kriging 实现）。

**只依赖 numpy**。运行自检：
    python code/decomposition.py
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "interaction_scores", "select_interaction_pairs", "group_variables",
    "combine_into_elite", "shrink_bounds", "subspace_bounds",
]

_TINY = 1e-12


# --------------------------------------------------------------------------- 交互强度
def interaction_scores(model: Callable[[np.ndarray], np.ndarray],
                       bounds: Sequence[Tuple[float, float]],
                       pairs: Optional[Iterable[Tuple[int, int]]] = None,
                       n_mc: int = 1024,
                       seed: int = 0) -> Dict[Tuple[int, int], float]:
    """估计每一对变量的**二阶交互效应**（归一化到总方差，越大越该放同一子空间）。

    采用 pick-freeze（Sobol 经典套路）在**代理模型**上做蒙特卡洛：给定两张独立的
    随机矩阵 A、B，记 A^{i←B} 为把 A 的第 i 列换成 B 的第 i 列，则"纯交互"部分可用
    混合二阶差分刻画：

        Δ_ij = f(A) − f(A^{i←B}) − f(A^{j←B}) + f(A^{ij←B})
        S_ij^int = E[Δ_ij²] / (4·Var(f))

    若 x_i 与 x_j 可加分离（无交互），Δ_ij ≡ 0，故该分数为 0。

    成本提示：每个变量对需要 4 次长度为 n_mc 的代理评估；d=126 时共 7875 对
    （126×125/2），即约 3 万次批量评估。这正是为什么必须先用**便宜的代理**而不是 CFD。
    """
    bounds = np.asarray(bounds, float)
    d = bounds.shape[0]
    lo, span = bounds[:, 0], bounds[:, 1] - bounds[:, 0]
    rng = np.random.default_rng(seed)

    if pairs is None:
        pairs = [(i, j) for i in range(d) for j in range(i + 1, d)]
    pairs = [tuple(sorted(p)) for p in pairs]
    for i, j in pairs:
        if not (0 <= i < d and 0 <= j < d) or i == j:
            raise ValueError(f"非法的变量对：({i}, {j})")

    A = lo + rng.random((n_mc, d)) * span
    B = lo + rng.random((n_mc, d)) * span

    def f(X: np.ndarray) -> np.ndarray:
        return np.asarray(model(X), float).ravel()

    fA = f(A)
    tot = float(np.var(np.concatenate([fA, f(B)])))
    if tot <= _TINY:
        return {p: 0.0 for p in pairs}

    cache: Dict[int, np.ndarray] = {}
    def col_swap(src: np.ndarray, k: int) -> np.ndarray:
        """把 src 的第 k 列换成 B 的第 k 列。"""
        key = (id(src), k)
        if key in cache:
            return cache[key]
        out = src.copy()
        out[:, k] = B[:, k]
        cache[key] = out
        return out

    scores: Dict[Tuple[int, int], float] = {}
    for (i, j) in pairs:
        Ai = col_swap(A, i)
        Aj = col_swap(A, j)
        Aij = col_swap(Ai, j)
        delta = fA - f(Ai) - f(Aj) + f(Aij)
        scores[(i, j)] = float(np.mean(delta ** 2) / (4.0 * tot))
    return scores


def select_interaction_pairs(scores: Dict[Tuple[int, int], float],
                             confirmed: Optional[Iterable[Tuple[int, int]]] = None,
                             n_suspected: int = 10,
                             threshold: float = 0.01) -> Dict[str, List[Tuple[int, int]]]:
    """把变量对分成三类［原文 P11 §3.2.1］：

    * `confirmed`（P_C）：已确认有交互的变量对
    * `suspected`（P_S）：在**剩余**变量对里分数最高的一批，待验证
    * `ignored`：其余（认为交互很弱，可以安全地分进不同子空间）

    threshold 是"分数低于此值就认为无交互"的门槛；n_suspected 控制 P_S 的规模。
    """
    confirmed = [tuple(sorted(c)) for c in (confirmed or [])]
    rest = {p: s for p, s in scores.items()
            if p not in set(confirmed) and s >= threshold}
    ranked = sorted(rest.items(), key=lambda kv: -kv[1])
    suspected = [p for p, _ in ranked[:max(0, int(n_suspected))]]
    suspected_set = set(suspected)
    return {
        "confirmed": confirmed,
        "suspected": suspected,
        "ignored": [p for p in scores if p not in set(confirmed) and p not in suspected_set],
    }


# --------------------------------------------------------------------------- 子空间分组
def group_variables(d: int, pairs: Iterable[Tuple[int, int]]) -> List[List[int]]:
    """据交互对做并查集分组：有交互的变量必须落进**同一个**子空间，
    相互独立的变量单独成组。返回若干组变量下标。"""
    parent = list(range(d))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, j in pairs:
        if not (0 <= i < d and 0 <= j < d):
            raise ValueError(f"非法的变量对：({i}, {j})")
        union(int(i), int(j))

    groups: Dict[int, List[int]] = {}
    for v in range(d):
        groups.setdefault(find(v), []).append(v)
    return [sorted(g) for _, g in sorted(groups.items(), key=lambda kv: kv[1][0])]


def subspace_bounds(bounds: Sequence[Tuple[float, float]],
                    groups: Sequence[Sequence[int]]) -> List[np.ndarray]:
    """取出每个子空间对应的变量边界，便于在各子空间里独立跑 EGO。"""
    b = np.asarray(bounds, float)
    out = []
    for g in groups:
        idx = list(g)
        out.append(b[idx].copy())
    return out


# --------------------------------------------------------------------------- 精英点聚合
def combine_into_elite(elite: np.ndarray,
                       solutions: Sequence[Tuple[Sequence[int], np.ndarray]]) -> np.ndarray:
    """精英点（elite-point）聚合［原文 P11 §3］。

    `solutions` 是一串 (变量下标, 该子空间的最优解) 对；函数把每个子空间的最优片段
    **写回精英点对应的维度**，得到一个全空间的完整可行解。

    这一步的意义：子空间是低维的、好优化的，但只有"局部视野"；精英点把各局部视野的
    最优解**拼装成一个全局可行解**，保证子空间优化不会跑偏到全空间的劣解上。
    """
    out = np.array(elite, dtype=float).copy()
    for idx, vals in solutions:
        idx = list(idx)
        vals = np.asarray(vals, float).ravel()
        if len(idx) != vals.size:
            raise ValueError("子空间变量下标数与解的长度不一致")
        if np.max(idx) >= out.size:
            raise ValueError("子空间下标越界")
        out[idx] = vals
    return out


# --------------------------------------------------------------------------- 搜索范围收缩
def shrink_bounds(bounds: Sequence[Tuple[float, float]],
                  elite_history: Sequence[np.ndarray],
                  rate: float = 0.5,
                  keep_center_last: bool = True) -> np.ndarray:
    """依据历史精英点收缩搜索范围［原文 P11 §3.2.2］。

    若此前求解过**相似子任务**（变量相同、精英点不同），可依据累积经验缩小搜索范围，
    从而同时提升优化效率与交互分析的精度。

    做法：以历史精英点的取值范围为基准，按 `rate` 向中心收缩（rate=0.5 表示新区间
    宽度是历史精英点范围的一半），并与原边界取交集，保证不越界。
    """
    b = np.asarray(bounds, float).copy()
    H = np.atleast_2d(np.asarray(elite_history, float))
    if H.size == 0 or H.shape[0] < 2:
        return b
    if not (0.0 < rate <= 1.0):
        raise ValueError("rate 应落在 (0, 1]")

    lo_h, hi_h = H.min(axis=0), H.max(axis=0)
    center = 0.5 * (lo_h + hi_h) if not keep_center_last else H[-1]
    half = 0.5 * rate * (hi_h - lo_h)
    new_lo = np.maximum(b[:, 0], center - half)
    new_hi = np.minimum(b[:, 1], center + half)
    bad = new_hi <= new_lo
    new_lo[bad], new_hi[bad] = b[bad, 0], b[bad, 1]
    return np.column_stack([new_lo, new_hi])


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)
    d = 5
    bounds = [(0.0, 1.0)] * d

    # 真值函数：(0,1) 强交互；(2,3) 弱交互；其余项可加分离（交互应恰为 0）
    def truth(X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, float))
        strong = 5.0 * X[:, 0] * X[:, 1]                  # 强交互
        weak = 0.3 * X[:, 2] * X[:, 3]                    # 弱交互
        additive = 1.0 * X[:, 2] + 0.8 * X[:, 3] ** 2     # 可加项
        tiny = 0.05 * X[:, 4]                             # 几乎无影响
        return strong + weak + additive + tiny

    scores = interaction_scores(truth, bounds, n_mc=4096, seed=3)
    assert len(scores) == d * (d - 1) // 2, "变量对数量不对"
    pairs_sorted = sorted(scores.items(), key=lambda kv: -kv[1])
    top = pairs_sorted[0][0]
    assert top == (0, 1), f"最强交互对应被误判：{top}"
    assert scores[(0, 1)] > 5 * scores[(0, 2)], "交互项未显著高于无关变量对"
    # 可加部分（1·x2 + 0.8·x3²）之间不应产生交互，估计值应恰为 0
    assert scores[(0, 4)] < 1e-12, f"可加项被误判为有交互：{scores[(0, 4)]}"
    assert scores[(1, 4)] < 1e-12, f"可加项被误判为有交互：{scores[(1, 4)]}"
    # 弱交互应被检出，但量级远小于强交互
    assert 0 < scores[(2, 3)] < 0.05 * scores[(0, 1)], \
        f"弱交互量级不对：{scores[(2, 3)]}"
    assert all(v >= 0 for v in scores.values()), "交互分数不应为负"

    # 分类：确认对 + 疑似对 + 其余（三者必须构成全集的划分）
    sel = select_interaction_pairs(scores, confirmed=[(0, 1)],
                                   n_suspected=3, threshold=1e-4)
    assert (0, 1) in sel["confirmed"], "已确认对丢失"
    assert len(sel["suspected"]) <= 3 and len(sel["suspected"]) >= 1, "疑似对数量不对"
    assert (0, 1) not in sel["suspected"], "已确认对不应再进疑似集"
    assert (2, 3) in sel["suspected"], "弱交互对应进入疑似集待验证"
    assert len(sel["confirmed"]) + len(sel["suspected"]) + len(sel["ignored"]) == len(scores)
    assert not (set(sel["confirmed"]) & set(sel["suspected"])), "三类划分存在重叠"

    # 分组：有交互的必须同组，其余各自成组
    groups = group_variables(d, [(0, 1)])
    assert [0, 1] in groups, f"(0,1) 未分到同组：{groups}"
    assert len(groups) == 4, f"应分成 4 组，实为 {len(groups)}：{groups}"
    assert sorted(sum(groups, [])) == list(range(d)), "分组未覆盖全部变量"
    # 传递性：(0,1) 与 (1,4) → {0,1,4} 必须同组
    g2 = group_variables(d, [(0, 1), (1, 4)])
    assert [0, 1, 4] in g2, f"并查集未体现传递性：{g2}"

    # 子空间边界
    sb = subspace_bounds(bounds, groups)
    assert len(sb) == len(groups), "子空间边界数量不对"
    assert sb[0].shape == (2, 2), "含 2 个变量的子空间应有 2 条边界"

    # 精英点聚合：把两个子空间的最优片段写回
    elite = np.zeros(d)
    new_elite = combine_into_elite(elite, [([0, 1], np.array([0.9, 0.8])),
                                           ([2], np.array([0.3]))])
    assert np.allclose(new_elite, [0.9, 0.8, 0.3, 0.0, 0.0]), "精英点聚合错误"
    assert np.allclose(elite, np.zeros(d)), "聚合不应修改原精英点（应返回新数组）"

    # 搜索范围收缩：新区间必须落在原区间内，且不宽于原区间
    hist = [np.array([0.4, 0.4, 0.4, 0.4, 0.4]),
            np.array([0.6, 0.6, 0.6, 0.6, 0.6])]
    nb = shrink_bounds(bounds, hist, rate=0.5)
    assert np.all(nb[:, 0] >= 0.0) and np.all(nb[:, 1] <= 1.0), "收缩后越界"
    assert np.all((nb[:, 1] - nb[:, 0]) <= 0.5 + 1e-12), "收缩幅度不足"
    assert np.all((nb[:, 1] - nb[:, 0]) > 0), "收缩后区间退化"
    # 只有一个历史精英点时不收缩
    assert np.allclose(shrink_bounds(bounds, hist[:1]), np.asarray(bounds, float))

    # 端到端：在这个"只有一对交互"的函数上，分解后应识别出 1 个 2 维子空间 + 3 个 1 维
    sel2 = select_interaction_pairs(scores, n_suspected=8, threshold=0.005)
    confirmed = [p for p in sel2["suspected"] if scores[p] > 0.2 * scores[(0, 1)]]
    g3 = group_variables(d, confirmed)
    assert [0, 1] in g3, f"端到端分解未把 (0,1) 归入同组：{g3}"

    # 异常输入
    for bad in [lambda: interaction_scores(truth, bounds, pairs=[(0, 0)]),
                lambda: interaction_scores(truth, bounds, pairs=[(0, 9)]),
                lambda: group_variables(d, [(0, 7)]),
                lambda: combine_into_elite(np.zeros(d), [([0, 1], np.array([1.0]))]),
                lambda: combine_into_elite(np.zeros(d), [([9], np.array([1.0]))]),
                lambda: shrink_bounds(bounds, hist, rate=1.5)]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")

    print(f"[decomposition.py] 自检通过：交互检测(top={top}, S={scores[(0, 1)]:.3f}) / "
          f"三类划分 / 并查集分组{g3} / 精英点聚合 / 边界收缩")


if __name__ == "__main__":
    _self_test()

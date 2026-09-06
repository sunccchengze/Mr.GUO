"""optimizer.py —— 昂贵黑箱优化器：DE / PSO / EGO / CR-EI / 代理辅助 DE

本模块把本全集讨论过的几类"搜索策略"实现成可直接调用的函数，方便对照：

| 函数 | 对应论文 | 要点 |
| :--- | :--- | :--- |
| `differential_evolution` | 论文 07（GSDE 的底座） | best/1 与 rand/1 变异、二项/指数交叉 |
| `pso` | 论文 07（GSDE 用 PSO 在局部 RBF 上找预测父点） | 标准惯性权重 + 个体/群体最优 |
| `ego` | 论文 01/02/04/11 的公共底座 | 代理 + 期望改善（EI）的序贯加点 |
| `calibrated_ei` / `recalibrated_ei` / `cr_ei_step` | **论文 01（CR-EI）** | 抬高原 incumbent 治过度探索、互补分区治过度开发 |
| `surrogate_assisted_de` | **论文 07（GSDE）** | 代理**直接参与生成子代基因**（紧耦合），而非只做筛选 |

关于 CR-EI 的一句话原理（第 01 讲）：
EI 的 incumbent 固定为当前最优 y_PBS 时，建议点会越来越"往远处瞎逛"。
CR-EI 不动 σ，而是**改 incumbent ξ**：把 ξ 抬高到 ξ_Calibrated 得到 CEI（收紧到近处
开发），并用与 CEI 采样区**互补**的 REI 保持全局探索；三者由一个"突破计数器 + 中位数
阈值"调度切换［原文 P01 式 17–18］。

代理模型的**鸭子接口**（本模块不 import 任何具体模型，避免耦合）：
    obj = factory()            # 工厂，每次调用返回新模型
    obj.fit(X, y)              # X:(n,d) 原始尺度，y:(n,)
    obj.predict(Xs) -> (mean, sd)   # 两个数组，形状均为 (m,)
`code/gp.py` 的 `Kriging.predict` 正好符合；`code/rbf.py` 的 RBF 只有均值，需要包一层。

**只依赖 numpy**。运行自检：
    python code/optimizer.py
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "differential_evolution", "pso", "expected_improvement",
    "calibrated_ei", "recalibrated_ei", "cr_ei_step",
    "ego", "surrogate_assisted_de",
]

_TINY = 1e-12
_ERF = np.vectorize(math.erf, otypes=[float])


# --------------------------------------------------------------------------- 公共工具
def _norm_pdf(u: np.ndarray) -> np.ndarray:
    return np.exp(-0.5 * np.asarray(u, float) ** 2) / math.sqrt(2.0 * math.pi)


def _norm_cdf(u: np.ndarray) -> np.ndarray:
    erf = _ERF
    return 0.5 * (1.0 + erf(np.asarray(u, float) / math.sqrt(2.0)))


def expected_improvement(mean: np.ndarray, sd: np.ndarray,
                         incumbent: float) -> np.ndarray:
    """标准 EI：EI = (ξ − μ)·Φ(u) + s·φ(u)，u = (ξ − μ)/s。"""
    mean = np.asarray(mean, float)
    sd = np.asarray(sd, float)
    imp = float(incumbent) - mean
    out = np.zeros_like(mean)
    pos = sd > _TINY
    u = np.zeros_like(mean)
    u[pos] = imp[pos] / sd[pos]
    out[pos] = imp[pos] * _norm_cdf(u[pos]) + sd[pos] * _norm_pdf(u[pos])
    return out


# --------------------------------------------------------------------------- 差分进化
def differential_evolution(func: Callable[[np.ndarray], float],
                           bounds: Sequence[Tuple[float, float]],
                           pop_size: int = 50,
                           F: float = 0.7,
                           CR: float = 0.9,
                           max_nfe: int = 1000,
                           strategy: str = "best/1",
                           crossover: str = "bin",
                           seed: int = 0,
                           return_history: bool = False):
    """差分进化（DE）。

    strategy  : 'best/1'（开发强）或 'rand/1'（探索强）
    crossover : 'bin'（二项交叉）或 'exp'（指数交叉，GSDE 用的是指数交叉）
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    d = bounds.shape[0]
    if pop_size < 4:
        raise ValueError("pop_size 至少为 4（DE 需要 3 个不同的随机个体）")

    P = lo + rng.random((pop_size, d)) * (hi - lo)
    f = np.array([float(func(x)) for x in P])
    nfe = pop_size
    best_idx = int(np.argmin(f))
    hist: List[float] = [float(f[best_idx])]

    while nfe < max_nfe:
        for i in range(pop_size):
            if nfe >= max_nfe:
                break
            # --- 变异
            idxs = [j for j in range(pop_size) if j != i]
            r1, r2, r3 = rng.choice(idxs, size=3, replace=False)
            if strategy == "best/1":
                base = P[best_idx]                 # v = x_best + F·(x_r1 − x_r2)
            elif strategy == "rand/1":
                base = P[r3]                       # v = x_r3 + F·(x_r1 − x_r2)
            else:
                raise ValueError(f"未知策略：{strategy}")
            v = np.clip(base + F * (P[r1] - P[r2]), lo, hi)

            # --- 交叉
            u = P[i].copy()
            if crossover == "bin":
                jrand = int(rng.integers(0, d))
                mask = rng.random(d) < CR
                mask[jrand] = True            # 至少一维来自变异向量
                u = np.where(mask, v, u)
            elif crossover == "exp":
                k = int(rng.integers(0, d))
                L = 0
                while rng.random() < CR and L < d:
                    u[k] = v[k]
                    k = (k + 1) % d
                    L += 1
            else:
                raise ValueError(f"未知交叉方式：{crossover}")

            fu = float(func(u))
            nfe += 1
            if fu <= f[i]:                    # 贪婪替换
                P[i], f[i] = u, fu
                if fu < f[best_idx]:
                    best_idx = i
            hist.append(float(f[best_idx]))

    if return_history:
        return P[best_idx], float(f[best_idx]), np.array(hist)
    return P[best_idx], float(f[best_idx])


# --------------------------------------------------------------------------- 粒子群
def pso(func: Callable[[np.ndarray], float],
        bounds: Sequence[Tuple[float, float]],
        n_particles: int = 50,
        n_iter: int = 100,
        w: float = 0.72,
        c1: float = 1.49,
        c2: float = 1.49,
        seed: int = 0,
        return_history: bool = False):
    """标准粒子群优化（PSO）。

    论文 07（GSDE）在**局部 RBF 代理**上用 PSO（种群 50、迭代 100 次）寻找"预测父点"
    x_i*，因此这里的 PSO 既可直接用于真实函数，也可用于代理模型。
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    d = bounds.shape[0]

    X = lo + rng.random((n_particles, d)) * (hi - lo)
    V = rng.uniform(-1.0, 1.0, size=(n_particles, d)) * (hi - lo) * 0.1
    f = np.array([float(func(x)) for x in X])
    pbest_x, pbest_f = X.copy(), f.copy()
    gbest_i = int(np.argmin(pbest_f))
    gbest_x, gbest_f = pbest_x[gbest_i].copy(), float(pbest_f[gbest_i])
    hist = [gbest_f]

    for _ in range(n_iter):
        r1 = rng.random((n_particles, d))
        r2 = rng.random((n_particles, d))
        V = w * V + c1 * r1 * (pbest_x - X) + c2 * r2 * (gbest_x - X)
        X = np.clip(X + V, lo, hi)
        f = np.array([float(func(x)) for x in X])
        improved = f < pbest_f
        pbest_x[improved] = X[improved]
        pbest_f[improved] = f[improved]
        i = int(np.argmin(pbest_f))
        if pbest_f[i] < gbest_f:
            gbest_f, gbest_x = float(pbest_f[i]), pbest_x[i].copy()
        hist.append(gbest_f)

    if return_history:
        return gbest_x, gbest_f, np.array(hist)
    return gbest_x, gbest_f


# --------------------------------------------------------------------------- CR-EI（论文 01）
def calibrated_ei(mean: np.ndarray, sd: np.ndarray, xi_calibrated: float) -> np.ndarray:
    """CEI：把 incumbent 抬到 ξ_Calibrated（> y_PBS）后的 EI。

    抬高 incumbent 会让原本 z ≤ 0 的点变成 z̃ > 0，从而把采样区重新约束在
    ŷ(x*) < ξ_Calibrated 之内，抑制"过度探索"。
    """
    return expected_improvement(mean, sd, xi_calibrated)


def recalibrated_ei(mean: np.ndarray, sd: np.ndarray, xi_calibrated: float,
                    X: np.ndarray, x_pbs: np.ndarray,
                    d_T: float, eps: float = 1e-3) -> np.ndarray:
    """REI：CEI 乘以**互补**分区掩码 δ₂ —— 只在 x_PBS 的 d_T 邻域**之外**取点。

    δ₁ = 1 当 ε < ‖x − x_PBS‖ ≤ d_T（近处，归 CEI）
    δ₂ = 1 − δ₁                              （远处，归 REI）
    三者合起来覆盖整个设计空间，这是 CR-EI 同时抗过度探索与过度开发的关键。
    """
    dist = np.linalg.norm(np.asarray(X, float) - np.asarray(x_pbs, float).ravel(), axis=1)
    d1 = ((dist > eps) & (dist <= d_T)).astype(float)
    return calibrated_ei(mean, sd, xi_calibrated) * (1.0 - d1)


def cr_ei_step(mean: np.ndarray, sd: np.ndarray, X: np.ndarray,
               y: np.ndarray, x_pbs: np.ndarray,
               d_T: float, beta: float = 0.1,
               n_breakthrough: int = 0, eps: float = 1e-3) -> Dict[str, object]:
    """CR-EI 一步决策［原文 P01 式 17–18］。

    参数
    ----
    mean, sd : 候选点上的代理预测
    X, y     : 已评估样本（用于取中位数阈值 y_T 与当前最优 y_PBS）
    x_pbs    : 当前最优样本坐标
    d_T      : 距离阈值，划分"近处/远处"
    beta     : incumbent 参数，原文扫描后取 β=0.1 综合最优
    n_breakthrough : 突破计数器（>0 表示 EI 仍在取得进展）

    返回 dict：{'mode': ..., 'indices': [...]}，indices 是本轮建议评估的候选点下标
    （最多 2 个，对应原论文的"EI + REI 并行"）。
    """
    X = np.asarray(X, float)
    y = np.asarray(y, float).ravel()
    if X.shape[0] != y.size:
        raise ValueError("X 与 y 样本数不一致")
    if not 0.0 < beta < 1.0:
        raise ValueError("beta 应落在 (0,1)")

    y_pbs = float(np.min(y))
    y_T = float(np.median(y))
    # ξ_Calibrated：把 incumbent 从 y_PBS 抬高，抬升幅度按 |y| 量级缩放
    scale = max(abs(y_pbs), abs(y_T), _TINY)
    xi_calibrated = y_pbs + beta * abs(y_T - y_pbs) if abs(y_T - y_pbs) > _TINY \
        else y_pbs + beta * scale

    ei = expected_improvement(mean, sd, y_pbs)
    i_ei = int(np.argmax(ei))

    if n_breakthrough == 0:
        return {"mode": "EI", "indices": [i_ei],
                "xi_calibrated": xi_calibrated, "y_T": y_T}

    cei = calibrated_ei(mean, sd, xi_calibrated)
    dist = np.linalg.norm(X - np.asarray(x_pbs, float).ravel(), axis=1)
    d1 = ((dist > eps) & (dist <= d_T)).astype(float)
    i_cei = int(np.argmax(cei * d1)) if np.any(d1 > 0) else i_ei

    rei = recalibrated_ei(mean, sd, xi_calibrated, X, x_pbs, d_T, eps)
    i_rei = int(np.argmax(rei))

    if float(y[i_ei]) < y_T or n_breakthrough > 0 and float(ei[i_ei]) > 0:
        # EI 有进展：继续用 EI，同时派 REI 去远处
        mode = "EI+REI"
        idxs = [i_ei, i_rei]
    else:
        # EI 疑似过度探索：换 CEI（近处开发）+ REI（远处探索）
        mode = "CEI+REI"
        idxs = [i_cei, i_rei]

    out: List[int] = []
    for i in idxs:
        if i not in out:
            out.append(i)
    return {"mode": mode, "indices": out, "xi_calibrated": xi_calibrated, "y_T": y_T}


# --------------------------------------------------------------------------- EGO 主循环
def ego(func: Callable[[np.ndarray], float],
        bounds: Sequence[Tuple[float, float]],
        surrogate_factory: Callable[[], object],
        n_init: int = 20,
        n_iter: int = 30,
        n_candidates: int = 2048,
        seed: int = 0,
        return_history: bool = False):
    """贝叶斯优化的标准 EGO 循环：初始采样 → 循环 {拟合代理 → 最大化 EI → 真实评估}。

    surrogate_factory 是**工厂函数**，每轮返回一个新模型（鸭子接口见模块文档）。
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    lo, span = bounds[:, 0], bounds[:, 1] - bounds[:, 0]
    d = bounds.shape[0]

    X = lo + rng.random((n_init, d)) * span
    y = np.array([float(func(x)) for x in X])
    hist = [float(np.min(y))]

    for _ in range(n_iter):
        mdl = surrogate_factory().fit(X, y)
        Xc = lo + rng.random((n_candidates, d)) * span
        mean, sd = mdl.predict(Xc)
        ei = expected_improvement(mean, sd, float(np.min(y)))
        x_new = Xc[int(np.argmax(ei))]
        y_new = float(func(x_new))
        X = np.vstack([X, x_new])
        y = np.append(y, y_new)
        hist.append(float(np.min(y)))

    i = int(np.argmin(y))
    if return_history:
        return X[i], float(y[i]), np.array(hist)
    return X[i], float(y[i])


# --------------------------------------------------------------------------- GSDE（论文 07）
def surrogate_assisted_de(func: Callable[[np.ndarray], float],
                          bounds: Sequence[Tuple[float, float]],
                          surrogate_factory: Callable[[], object],
                          pop_size: int = 50,
                          F: float = 0.7,
                          CR: float = 0.9,
                          top_T: int = 9,
                          pso_particles: int = 50,
                          pso_iters: int = 100,
                          local_k: Optional[int] = None,
                          local_radius: float = 0.25,
                          max_nfe: int = 300,
                          seed: int = 0,
                          return_history: bool = False):
    """代理辅助差分进化——GSDE 的骨架（论文 07）。

    与"松散耦合"的差别：代理模型**直接参与生成子代基因**。流程为
      1. 对每个父代 x_i，取它的 k 个最近邻样本建**局部代理**（GSDE 用局部 RBF）；
      2. 用 PSO 在这个局部代理上、于 x_i 的邻域内找"预测父点" x_i*；
      3. best/1 变异得到 v_i，再用**指数交叉**把 v_i 与 x_i* 缝合成候选 u_i；
      4. 按**父代适应度**给候选排序，只挑前 T 个做真实评估（原文 T=9）并替换最差的 T 个。

    > 原文的关键工程动机：每轮若把全部候选都送去做 CFD，开销不可承受；而"优秀父代
    > 产生的子代更可能携带好基因"，所以只评估最好的 T 个［原文 P07 §Proposed algorithm］。
    >
    > **实现说明**：原文未公开 k（邻居数）与局部邻域半径的取值，本实现的
    > `local_k` 与 `local_radius` 是我们自己的工程选择，不是论文数值。
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    d = bounds.shape[0]
    lo_arr, span_arr = lo, hi - lo
    if top_T < 1 or top_T > pop_size:
        raise ValueError("top_T 应落在 [1, pop_size]")

    P = lo + rng.random((pop_size, d)) * span_arr
    f = np.array([float(func(x)) for x in P])
    nfe = pop_size
    hist = [float(np.min(f))]

    def unit_to_raw(Z: np.ndarray) -> np.ndarray:
        return lo_arr + np.asarray(Z, float) * span_arr

    while nfe < max_nfe:
        # 0. 归一化坐标（代理一律在 [0,1]^d 上工作）
        Z = (P - lo_arr) / span_arr
        k_nb = int(local_k) if local_k else min(pop_size, max(d + 2, 3 * d + 6))

        # 1~2. 逐父代建**局部**代理，并用 PSO 在其邻域内找"预测父点" x_i*
        x_stars = np.empty_like(P)
        for i in range(pop_size):
            dist = np.linalg.norm(Z - Z[i], axis=1)
            nb = np.argsort(dist)[:k_nb]
            try:
                mdl = surrogate_factory().fit(Z[nb], f[nb])
            except ValueError:
                mdl = None

            if mdl is None:
                x_stars[i] = P[i]
                continue

            def neg_pred(z: np.ndarray, _mdl=mdl) -> float:
                z = np.atleast_2d(np.asarray(z, float))
                val = _mdl.predict(z)
                mean = val[0] if isinstance(val, tuple) else val
                return float(np.asarray(mean).ravel()[0])

            # 局部邻域：以父代为中心、半径 local_radius（归一化尺度），并被设计域截断
            zc = Z[i]
            box = [(max(0.0, zc[j] - local_radius), min(1.0, zc[j] + local_radius))
                   for j in range(d)]
            zbest, fbest_sur, = pso(neg_pred, box, n_particles=pso_particles,
                                    n_iter=pso_iters, seed=int(rng.integers(1 << 30)))
            # 代理的建议若不如父代本身，就退回父代（避免代理误导 —— 即"负迁移"的同类风险）
            x_stars[i] = P[i] if float(fbest_sur) >= float(f[i]) else unit_to_raw(zbest)

        # 3. best/1 变异 + 与预测父点的指数交叉
        i_best = int(np.argmin(f))
        cand, parent_idx = [], []
        for i in range(pop_size):
            idxs = [j for j in range(pop_size) if j != i]
            r1, r2 = rng.choice(idxs, size=2, replace=False)
            v = np.clip(P[i_best] + F * (P[r1] - P[r2]), lo, hi)
            u = v.copy()
            k = int(rng.integers(0, d))
            L = 0
            while rng.random() < CR and L < d:
                u[k] = x_stars[i][k]          # 代理的"好基因"直接进入子代
                k = (k + 1) % d
                L += 1
            cand.append(np.clip(u, lo, hi))
            parent_idx.append(i)
        cand = np.array(cand)

        # 4. 按父代适应度排序，只评估前 T 个
        order = np.argsort(f[np.array(parent_idx)])
        pick = order[:top_T]
        for i in pick:
            fu = float(func(cand[i]))
            nfe += 1
            j = parent_idx[i]
            if fu < f[j]:
                P[j], f[j] = cand[i], fu
            hist.append(float(np.min(f)))
            if nfe >= max_nfe:
                break

    i = int(np.argmin(f))
    if return_history:
        return P[i], float(f[i]), np.array(hist)
    return P[i], float(f[i])


# --------------------------------------------------------------------------- 自检
class _DemoSurrogate:
    """自检用的轻量代理（三次 RBF + 线性尾项，sd 用"到最近样本的距离"近似）。

    放在自检里而不是模块顶层，是为了保持 `optimizer.py` 与具体代理模型解耦。
    """

    def __init__(self):
        self.X = None
        self.y = None
        self.nn_scale = 1.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_DemoSurrogate":
        X = np.asarray(X, float)
        y = np.asarray(y, float).ravel()
        self.X, self.y = X, y
        diff = X[:, None, :] - X[None, :, :]
        D = np.sqrt(np.einsum("nmk,nmk->nm", diff, diff))
        Phi = D ** 3
        Pd = np.hstack([np.ones((X.shape[0], 1)), X])
        m = Pd.shape[1]
        A = np.zeros((X.shape[0] + m, X.shape[0] + m))
        A[:X.shape[0], :X.shape[0]] = Phi
        A[:X.shape[0], X.shape[0]:] = Pd
        A[X.shape[0]:, :X.shape[0]] = Pd.T
        self.sol = np.linalg.lstsq(A, np.concatenate([y, np.zeros(m)]), rcond=None)[0]
        self.d = X.shape[1]
        off = D[~np.eye(X.shape[0], dtype=bool)]
        self.nn_scale = float(np.mean(off)) if off.size else 1.0
        return self

    def predict(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        Xs = np.atleast_2d(np.asarray(Xs, float))
        diff = Xs[:, None, :] - self.X[None, :, :]
        D = np.sqrt(np.einsum("nmk,nmk->nm", diff, diff))
        Phi = D ** 3
        Pd = np.hstack([np.ones((Xs.shape[0], 1)), Xs])
        mean = Phi @ self.sol[:self.X.shape[0]] + Pd @ self.sol[self.X.shape[0]:]
        nn = D.min(axis=1)
        sd = np.clip(nn / max(self.nn_scale, _TINY), 1e-6, 1.0) * (np.std(self.y) + 1e-9)
        return mean, sd


def _self_test() -> None:
    # ---- 目标函数（2 维 Branin，全局最优 0.397887）
    def branin(x: np.ndarray) -> float:
        x = np.atleast_1d(np.asarray(x, float))
        x1, x2 = x[0], x[1]
        a, b, c, r, s, t = 1.0, 5.1 / (4 * np.pi ** 2), 5 / np.pi, 6.0, 10.0, 1 / (8 * np.pi)
        return float(a * (x2 - b * x1 ** 2 + c * x1 - r) ** 2 + s * (1 - t) * np.cos(x1) + s)

    b2 = [(-5.0, 10.0), (0.0, 15.0)]

    # 1) DE：两种策略、两种交叉都能收敛到接近全局最优
    for strat in ("best/1", "rand/1"):
        for cx in ("bin", "exp"):
            xb, fb, hist = differential_evolution(branin, b2, pop_size=30, max_nfe=1500,
                                                  strategy=strat, crossover=cx,
                                                  seed=3, return_history=True)
            assert fb < 0.5, f"DE {strat}/{cx} 未收敛：{fb}"
            assert hist[-1] <= hist[0] + 1e-12, "最优值历史应单调不增"

    # 2) PSO：能找到合理解
    xp, fp, hp = pso(branin, b2, n_particles=40, n_iter=200, seed=5, return_history=True)
    assert fp < 0.6, f"PSO 未收敛：{fp}"
    assert hp[-1] <= hp[0] + 1e-12, "PSO 历史应单调不增"

    # 3) EI 的数学性质
    mean = np.array([0.0, 1.0, 2.0])
    sd = np.array([1.0, 1.0, 1.0])
    ei = expected_improvement(mean, sd, incumbent=0.0)
    assert np.all(ei >= -1e-12), "EI 应为非负"
    # 最小化问题：预测均值越低（看似越好），EI 越大
    assert ei[0] > ei[1] > ei[2], "均值越低 EI 应越大"
    assert expected_improvement(np.array([0.0]), np.array([0.0]), 0.0)[0] == 0.0
    # 方差越大（越不确定）EI 越大
    assert expected_improvement(np.array([1.0]), np.array([2.0]), 0.0)[0] > \
        expected_improvement(np.array([1.0]), np.array([0.5]), 0.0)[0]

    # 4) CEI / REI 的分区互补性（论文 01 的核心结构）
    rng = np.random.default_rng(0)
    X = rng.random((200, 2))
    x_pbs = np.array([0.5, 0.5])
    d_T = 0.3
    mean = np.zeros(200)
    sd = np.ones(200)
    cei = calibrated_ei(mean, sd, xi_calibrated=1.0)
    rei = recalibrated_ei(mean, sd, 1.0, X, x_pbs, d_T)
    near = np.linalg.norm(X - x_pbs, axis=1) <= d_T
    assert np.all(rei[near] == 0.0), "REI 不应在近处取点"
    assert np.any(rei[~near] > 0.0), "REI 应在远处有值"
    # 互补性：CEI·δ₁ + REI ≡ CEI（近处归 CEI，远处归 REI，合起来覆盖全空间）
    dist_all = np.linalg.norm(X - x_pbs, axis=1)
    delta1 = ((dist_all > 1e-3) & (dist_all <= d_T)).astype(float)
    assert np.allclose(cei * delta1 + rei, cei), "CEI 与 REI 的分区不互补"

    # 5) CR-EI 的三种调度模式都能被触发，且返回合法下标
    y = np.linspace(-3.0, 3.0, 200)
    res0 = cr_ei_step(mean, sd, X, y, x_pbs, d_T, beta=0.1, n_breakthrough=0)
    assert res0["mode"] == "EI" and len(res0["indices"]) == 1
    res1 = cr_ei_step(mean, sd, X, y, x_pbs, d_T, beta=0.1, n_breakthrough=5)
    assert res1["mode"] in ("EI+REI", "CEI+REI"), res1["mode"]
    assert len(res1["indices"]) <= 2 and all(0 <= i < 200 for i in res1["indices"])
    # ξ_Calibrated 必须高于当前最优（这是 CEI 的定义）
    assert res1["xi_calibrated"] > float(np.min(y))
    # beta 越大，抬升幅度越大
    a = cr_ei_step(mean, sd, X, y, x_pbs, d_T, beta=0.1, n_breakthrough=1)["xi_calibrated"]
    bb = cr_ei_step(mean, sd, X, y, x_pbs, d_T, beta=0.5, n_breakthrough=1)["xi_calibrated"]
    assert bb > a, "β 越大 incumbent 抬升应越多"

    # 6) EGO：在 Branin 上，30 轮加点后应显著优于初始随机采样
    xg, fg, hg = ego(branin, b2, _DemoSurrogate, n_init=15, n_iter=40,
                     n_candidates=1500, seed=11, return_history=True)
    assert fg < 0.45, f"EGO 未收敛：{fg}"
    assert hg[-1] <= hg[0] + 1e-12, "EGO 历史应单调不增"
    assert hg[-1] < hg[0], "EGO 相对初始采样应有改进"

    # 7) GSDE 骨架：同样的真实评估预算（240 次）下，应优于纯随机搜索。
    #    随机搜索单次结果波动很大，故取 3 个随机种子的平均最优值做基线。
    xs, fs, hs = surrogate_assisted_de(branin, b2, _DemoSurrogate,
                                       pop_size=20, top_T=5,
                                       pso_particles=10, pso_iters=20,
                                       max_nfe=240, seed=13, return_history=True)
    lo = np.array([b[0] for b in b2])
    sp = np.array([b[1] - b[0] for b in b2])
    rand_bests = []
    for rs in (99, 7, 11):
        r = np.random.default_rng(rs)
        rand_bests.append(min(float(branin(lo + r.random(2) * sp)) for _ in range(240)))
    rand_mean = float(np.mean(rand_bests))
    assert fs < rand_mean, f"GSDE({fs:.4f}) 未优于随机搜索均值({rand_mean:.4f})"
    assert hs[-1] <= hs[0] + 1e-12, "GSDE 历史应单调不增"

    # 8) 异常输入
    for bad in [lambda: differential_evolution(branin, b2, pop_size=3),
                lambda: differential_evolution(branin, b2, strategy="cur/1"),
                lambda: differential_evolution(branin, b2, crossover="weird"),
                lambda: surrogate_assisted_de(branin, b2, _DemoSurrogate,
                                              pop_size=5, top_T=9),
                lambda: cr_ei_step(mean, sd, X, y[:10], x_pbs, d_T),
                lambda: cr_ei_step(mean, sd, X, y, x_pbs, d_T, beta=1.5)]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")

    print(f"[optimizer.py] 自检通过：DE(4 组合)/PSO({fp:.4f})/EI性质/"
          f"CR-EI三模式/EGO({fg:.4f})/GSDE({fs:.4f} vs 随机均值 {rand_mean:.4f})")


if __name__ == "__main__":
    _self_test()

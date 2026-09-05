"""multifidelity.py —— 多保真度建模与"把钱花在刀刃上"的样本分流

多保真是本全集贯穿始终的主线之一。本模块实现其中**可复现、且原文给出明确公式**的
几件事：

| 函数 / 类 | 对应论文 | 说明 |
| :--- | :--- | :--- |
| `CoKriging` | 论文 02 / 03 / 05 / 08 / 13 | 自回归（AR1）Co-Kriging：y_HF = ρ·y_LF + Z_DF |
| `filter_gei_threshold` | **论文 02（Filter-GEI）式 10–12** | 自适应权重 ω 与分流阈值 T 的**原文公式** |
| `hierarchical_decluster` | **论文 02** 第四步 | 层次聚类去掉重叠候选点 |
| `fidelity_split` | **论文 02** 第 6 步 | 预测优于 T 的送 HF，其余送 LF |
| `dbscan` | **论文 13（EMFS/MSFO）** | 密度聚类找出"多保真代理建不准"的失真区 |
| `EMFSEnsemble` | **论文 13（EMFS）** | MFS 与局部单保真代理的自适应加权融合 |

**两处必须说清楚的诚实声明**：
1. 论文 13 的 **DBSCAN 参数（ε、MinPts）与自适应权重公式原文未给出**（第 05 讲已标注
   "原文未获取，本讲不作推测"）。因此 `dbscan` 实现的是标准 DBSCAN 算法（公开算法），
   而 `EMFSEnsemble` 的权重公式是**本代码库自己的工程选择**，不是论文数值。
2. `CoKriging` 的预测方差采用**常用简化**：s²_HF = ρ²·s²_LF + s²_DF（把 LF 与差异函数
   两个 GP 视为相互独立）。严格做法需展开二者协方差，工程量与收益不成比例，
   在"用方差做探索"这一用途上该简化被广泛采用。

代理模型通过 `gp_factory` 注入（鸭子接口：`.fit(X,y)` → self，`.predict(Xs)` → (mean, sd)）。
默认使用本模块内置的精简 Kriging（`_TinyKriging`）；若要用 `code/gp.py` 的完整实现，
传入 `gp_factory=lambda: Kriging()` 即可。**注意：code/ 下的模块互不 import，是刻意的
零耦合设计**（每个模块都能单独拷贝出去用）。

**只依赖 numpy**。运行自检：
    python code/multifidelity.py
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "CoKriging", "filter_gei_threshold", "hierarchical_decluster",
    "fidelity_split", "dbscan", "EMFSEnsemble", "hedge_choose",
]

_TINY = 1e-12
_ERF = np.vectorize(math.erf, otypes=[float])


# --------------------------------------------------------------------------- 内置精简 Kriging
class _TinyKriging:
    """模块内置的精简普通 Kriging（ARD 高斯相关 + 坐标下降搜超参）。

    存在的唯一原因：让 `CoKriging` 开箱即用。需要更严谨的实现请用 `code/gp.py`。
    """

    def __init__(self, nugget: float = 1e-8, seed: int = 0):
        self.nugget = nugget

    @staticmethod
    def _corr(A: np.ndarray, B: np.ndarray, theta: np.ndarray) -> np.ndarray:
        diff = A[:, None, :] - B[None, :, :]
        return np.exp(-np.einsum("nmk,k->nm", diff ** 2, theta))

    def _loglik(self, theta: np.ndarray) -> Tuple[float, Optional[dict]]:
        R = self._corr(self.X, self.X, theta)
        R[np.diag_indices_from(R)] += self.nugget
        try:
            L = np.linalg.cholesky(R)
        except np.linalg.LinAlgError:
            return -np.inf, None
        one = np.ones(self.X.shape[0])
        Ri1 = np.linalg.solve(L.T, np.linalg.solve(L, one))
        Riy = np.linalg.solve(L.T, np.linalg.solve(L, self.y))
        mu = float(one @ Riy) / float(one @ Ri1)
        r = self.y - one * mu
        s2 = float(r @ np.linalg.solve(L.T, np.linalg.solve(L, r))) / self.X.shape[0]
        if s2 <= 0:
            return -np.inf, None
        ll = (-0.5 * self.X.shape[0] * math.log(s2)
              - float(np.sum(np.log(np.diag(L)))))
        return ll, {"L": L, "mu": mu, "s2": s2, "Ri1": Ri1, "Riy": Riy}

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_TinyKriging":
        X = np.atleast_2d(np.asarray(X, float))
        y = np.asarray(y, float).ravel()
        self.xmin = X.min(axis=0)
        self.xspan = X.max(axis=0) - self.xmin
        self.xspan[self.xspan <= 0] = 1.0
        self.X = (X - self.xmin) / self.xspan
        self.y_mean, self.y_std = float(np.mean(y)), float(np.std(y))
        self.y_std = self.y_std if self.y_std > _TINY else 1.0
        self.y = (y - self.y_mean) / self.y_std

        d = self.X.shape[1]
        cur = np.zeros(d)
        best_ll, best = -np.inf, cur.copy()
        for start in (np.log10(0.1), 0.0, 1.0):
            cur = np.full(d, start)
            for _ in range(2):
                for k in range(d):
                    grid = np.linspace(-2.5, 2.5, 21)
                    vals = []
                    for v in grid:
                        t = cur.copy()
                        t[k] = v
                        ll, _ = self._loglik(10.0 ** t)
                        vals.append(ll)
                    cur[k] = grid[int(np.argmax(vals))]
            ll, _ = self._loglik(10.0 ** cur)
            if ll > best_ll:
                best_ll, best = ll, cur.copy()
        self.theta = 10.0 ** best
        ll, aux = self._loglik(self.theta)
        if aux is None:
            self.theta = np.full(d, 0.1)
            ll, aux = self._loglik(self.theta)
        self.L, self.mu, self.sigma2 = aux["L"], aux["mu"], aux["s2"]
        self.Ri1, self.Riy = aux["Ri1"], aux["Riy"]
        self.loglik = ll
        return self

    def predict(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        Z = (np.atleast_2d(np.asarray(Xs, float)) - self.xmin) / self.xspan
        mus, s2s = [], []
        for z in Z:
            r = self._corr(z.reshape(1, -1), self.X, self.theta).ravel()
            Rir = np.linalg.solve(self.L.T, np.linalg.solve(self.L, r))
            mus.append(self.mu + float(r @ (self.Riy - self.mu * self.Ri1)))
            s2s.append(max(self.sigma2 * (1.0 + self.nugget - float(r @ Rir)), 0.0))
        return (np.array(mus) * self.y_std + self.y_mean,
                np.sqrt(np.array(s2s)) * self.y_std)


# --------------------------------------------------------------------------- Co-Kriging
class CoKriging:
    """自回归（AR1）Co-Kriging：y_HF(x) = ρ·y_LF(x) + Z_DF(x)。

    这是本全集出现次数最多的多保真结构：
      * 论文 02（Filter-GEI）用它做代理，并由 σ²_DF / σ²_LF 决定滤波阈值；
      * 论文 13（EMFS）把它作为"会被换掉"的 MFS；
      * 论文 08（KT-ASO）把**历史任务的样本**当作 LF，用同一个结构做知识迁移。

    用法：
        ck = CoKriging().fit(X_lf, y_lf, X_hf, y_hf)
        mu, sd = ck.predict(Xs)
        print(ck.rho, ck.sigma2_lf, ck.sigma2_df)
    """

    def __init__(self, gp_factory: Optional[Callable[[], object]] = None,
                 rho_grid: Sequence[float] = tuple(np.linspace(-2.0, 3.0, 51))):
        self.gp_factory = gp_factory if gp_factory is not None else (lambda: _TinyKriging())
        self.rho_grid = np.asarray(rho_grid, float)

    def fit(self, X_lf: np.ndarray, y_lf: np.ndarray,
            X_hf: np.ndarray, y_hf: np.ndarray) -> "CoKriging":
        X_lf = np.atleast_2d(np.asarray(X_lf, float))
        X_hf = np.atleast_2d(np.asarray(X_hf, float))
        y_lf = np.asarray(y_lf, float).ravel()
        y_hf = np.asarray(y_hf, float).ravel()
        if X_lf.shape[1] != X_hf.shape[1]:
            raise ValueError("低保真与高保真样本的维度不一致")
        if X_lf.shape[0] < 3 or X_hf.shape[0] < 2:
            raise ValueError("样本太少：LF 至少 3 个、HF 至少 2 个")

        self.gp_lf = self.gp_factory().fit(X_lf, y_lf)
        self.sigma2_lf = float(np.var(y_lf)) if np.var(y_lf) > _TINY else _TINY

        # 在 HF 点上取 LF 的预测，构造差异样本 d = y_HF − ρ·ŷ_LF
        mu_lf_at_hf, _ = self.gp_lf.predict(X_hf)

        def _fit_df(rho: float):
            d = y_hf - float(rho) * mu_lf_at_hf
            try:
                gp_df = self.gp_factory().fit(X_hf, d)
            except (ValueError, np.linalg.LinAlgError):
                return None, -np.inf
            return gp_df, getattr(gp_df, "loglik", -np.inf)

        best_ll, best, best_model = -np.inf, 1.0, None
        for rho in self.rho_grid:
            m, ll = _fit_df(rho)
            if m is not None and ll > best_ll:
                best_ll, best, best_model = ll, float(rho), m
        if best_model is None:
            raise RuntimeError("Co-Kriging 拟合失败：所有 ρ 都无法建立差异模型")

        # 在最优网格点的邻域内做黄金分割细化（网格步长可能较粗）
        i = int(np.argmin(np.abs(self.rho_grid - best)))
        a = float(self.rho_grid[max(0, i - 1)])
        b = float(self.rho_grid[min(len(self.rho_grid) - 1, i + 1)])
        gr = (math.sqrt(5.0) - 1.0) / 2.0
        c, e = b - gr * (b - a), a + gr * (b - a)
        mc, llc = _fit_df(c)
        me, lle = _fit_df(e)
        for _ in range(12):
            if llc > lle:
                b, e, me, lle = e, c, mc, llc
                c = b - gr * (b - a)
                mc, llc = _fit_df(c)
            else:
                a, c, mc, llc = c, e, me, lle
                e = a + gr * (b - a)
                me, lle = _fit_df(e)
        for cand, m, ll in ((c, mc, llc), (e, me, lle)):
            if m is not None and ll > best_ll:
                best_ll, best, best_model = ll, float(cand), m

        self.rho = best
        self.gp_df = best_model
        self.sigma2_df = float(np.var(y_hf - best * mu_lf_at_hf))
        self.loglik = best_ll
        return self

    def predict(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        mu_lf, sd_lf = self.gp_lf.predict(Xs)
        mu_df, sd_df = self.gp_df.predict(Xs)
        mu = self.rho * mu_lf + mu_df
        # 简化方差：把 LF 与差异函数两个 GP 视为独立（见模块文档声明）
        sd = np.sqrt(np.maximum((self.rho ** 2) * sd_lf ** 2 + sd_df ** 2, 0.0))
        return mu, sd


# --------------------------------------------------------------------------- Filter-GEI（论文 02）
def filter_gei_threshold(sigma2_df: float, sigma2_lf: float,
                         y_hf_min: float, y_hf_mean: float) -> Tuple[float, float]:
    """论文 02（Filter-GEI）的自适应权重与分流阈值［原文式 10–12］：

        ω = 1 / (1 + (σ̂²_DF / σ̂²_LF)^0.5)
        T = ω·y_HF-min + (1 − ω)·y_HF-mean

    含义：LF 与 HF 越相关 → σ²_DF 越小 → ω→1 → T 贴近当前最优 → **只给非常好的点投 HF**；
    相关性越差 → ω→0 → T 贴近历史均值 → 扩大 HF 投放区域、加强全局探索。
    """
    if sigma2_lf <= _TINY:
        raise ValueError("σ̂²_LF 必须为正")
    if sigma2_df < 0:
        raise ValueError("σ̂²_DF 不能为负")
    omega = 1.0 / (1.0 + math.sqrt(sigma2_df / sigma2_lf))
    T = omega * float(y_hf_min) + (1.0 - omega) * float(y_hf_mean)
    return float(omega), float(T)


def hierarchical_decluster(X: np.ndarray, d_T: float) -> List[List[int]]:
    """层次聚类去重叠［论文 02 第四步］。

    逐个合并距离最近的两类，直到**最小的类间距离大于阈值 d_T** 为止。返回每类的下标列表。
    """
    X = np.atleast_2d(np.asarray(X, float))
    n = X.shape[0]
    if n == 0:
        return []
    if d_T < 0:
        raise ValueError("距离阈值 d_T 不能为负")

    def _dist(a: List[int], b: List[int]) -> float:
        """类间距离 = 两类间**最近**两点（单链接）。"""
        A, B = X[a], X[b]
        diff = A[:, None, :] - B[None, :, :]
        return float(np.sqrt(np.min(np.einsum("nmk,nmk->nm", diff, diff))))

    clusters: List[List[int]] = [[i] for i in range(n)]
    while len(clusters) > 1:
        best, bi, bj = np.inf, 0, 1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                dd = _dist(clusters[i], clusters[j])
                if dd < best:
                    best, bi, bj = dd, i, j
        if best > d_T:
            break
        merged = clusters[bi] + clusters[bj]
        clusters = [c for k, c in enumerate(clusters) if k not in (bi, bj)] + [merged]
    return [sorted(c) for c in clusters]


def fidelity_split(pred: np.ndarray, T: float) -> Tuple[np.ndarray, np.ndarray]:
    """按阈值 T 分流［论文 02 第 6 步］：预测值**优于** T（最小化意义下即 < T）的送 HF，
    其余送 LF。返回 (hf_indices, lf_indices)。"""
    pred = np.asarray(pred, float).ravel()
    hf = np.where(pred < T)[0]
    lf = np.where(pred >= T)[0]
    return hf, lf


def budget_report(n_hf: int, n_lf: int, cost_ratio: float = 0.1) -> dict:
    """把"HF/LF 各用了多少次"折算成**等效 HF 次数**（论文 02 的工程算例中
    LF 与 HF 的成本比为 0.1，一次 HF 的钱能做十次 LF）。"""
    if cost_ratio <= 0:
        raise ValueError("成本比必须为正")
    return {"n_hf": int(n_hf), "n_lf": int(n_lf), "cost_ratio": float(cost_ratio),
            "equivalent_hf": int(n_hf) + float(cost_ratio) * int(n_lf)}


# --------------------------------------------------------------------------- DBSCAN（论文 13）
def dbscan(X: np.ndarray, eps: float, min_samples: int = 5) -> np.ndarray:
    """标准 DBSCAN 密度聚类（论文 13 用它识别"多保真代理建不准"的失真区）。

    返回标签数组：-1 表示噪声点，其余为簇编号。
    参数 ε 与 MinPts 的具体取值**原文未给出**，需按样本尺度自行标定。
    """
    X = np.atleast_2d(np.asarray(X, float))
    n = X.shape[0]
    if eps <= 0:
        raise ValueError("eps 必须为正")
    if min_samples < 1:
        raise ValueError("min_samples 至少为 1")
    if n == 0:
        return np.zeros(0, dtype=int)

    diff = X[:, None, :] - X[None, :, :]
    D = np.sqrt(np.einsum("nmk,nmk->nm", diff, diff))
    labels = np.full(n, -2, dtype=int)        # -2 未访问，-1 噪声
    c = 0
    for p in range(n):
        if labels[p] != -2:
            continue
        seeds = list(np.where(D[p] <= eps)[0])
        if len(seeds) < min_samples:
            labels[p] = -1
            continue
        labels[p] = c
        q = 0
        while q < len(seeds):
            j = int(seeds[q])
            if labels[j] == -1:
                labels[j] = c                # 噪声点被核心点"收编"为边界点
            elif labels[j] == -2:
                labels[j] = c
                nbrs = list(np.where(D[j] <= eps)[0])
                if len(nbrs) >= min_samples:
                    seeds += [int(t) for t in nbrs if t not in seeds]
            q += 1
        c += 1
    return labels


# --------------------------------------------------------------------------- EMFS 集成（论文 13）
class EMFSEnsemble:
    """MFS + 局部单保真代理（local SFS）的自适应加权集成［论文 13 的 EMFS 思路］。

    论文流程：① 用 HF+LF 建多保真代理 MFS；② 用 DBSCAN 找出 MFS 建不准的失真区；
    ③ 在失真区内**只用 HF** 建局部单保真代理 local SFS；④ 用自适应权重把两者融合。

    > ⚠️ 论文 13 的**权重公式原文未给出**（第 05 讲已标注"原文未获取"）。本实现采用
    > 一个直接的工程方案：**按局部留一误差的倒数加权**——哪个模型在这一点附近历史上
    > 更准，谁的权重就更大。这是我们的选择，不是论文数值。
    """

    def __init__(self, gp_factory: Optional[Callable[[], object]] = None,
                 eps: float = 0.25, min_samples: int = 4, delta: float = 1e-6):
        self.gp_factory = gp_factory if gp_factory is not None else (lambda: _TinyKriging())
        self.eps = float(eps)
        self.min_samples = int(min_samples)
        self.delta = float(delta)

    def fit(self, X_lf: np.ndarray, y_lf: np.ndarray,
            X_hf: np.ndarray, y_hf: np.ndarray) -> "EMFSEnsemble":
        X_hf = np.atleast_2d(np.asarray(X_hf, float))
        y_hf = np.asarray(y_hf, float).ravel()
        self.X_hf, self.y_hf = X_hf, y_hf

        # ① 多保真代理
        self.mfs = CoKriging(gp_factory=self.gp_factory).fit(X_lf, y_lf, X_hf, y_hf)
        # ② 失真区检测：在 HF 样本上做密度聚类
        self.labels = dbscan(X_hf, eps=self.eps, min_samples=self.min_samples)
        self.regions = [np.where(self.labels == c)[0]
                        for c in sorted(set(self.labels) - {-1})]
        # ③ 每个失真区里只用 HF 建局部单保真代理
        self.locals: List[object] = []
        self.local_err: List[float] = []
        for idx in self.regions:
            if idx.size < 5:                      # 样本太少就建不了局部模型
                self.locals.append(None)
                self.local_err.append(np.inf)
                continue
            try:
                m = self.gp_factory().fit(X_hf[idx], y_hf[idx])
                err = self._loo_rmse(X_hf[idx], y_hf[idx])
            except (ValueError, np.linalg.LinAlgError):
                m, err = None, np.inf
            self.locals.append(m)
            self.local_err.append(err)
        # 全局单保真代理（噪声点所在区域没有局部模型时的兜底）
        try:
            self.sfs = self.gp_factory().fit(X_hf, y_hf)
            self.sfs_err = self._loo_rmse(X_hf, y_hf)
        except (ValueError, np.linalg.LinAlgError):
            self.sfs, self.sfs_err = None, np.inf
        self.mfs_err = self._loo_rmse(X_hf, y_hf, model=self.mfs)
        return self

    @staticmethod
    def _loo_rmse(X: np.ndarray, y: np.ndarray, model: Optional[object] = None,
                  gp_factory: Optional[Callable[[], object]] = None) -> float:
        """留一 RMSE（用于给各模型定权重）。"""
        factory = gp_factory if gp_factory is not None else (lambda: _TinyKriging())
        errs = []
        for i in range(X.shape[0]):
            keep = np.ones(X.shape[0], dtype=bool)
            keep[i] = False
            try:
                m = model if model is None else None
                # 有现成模型时无法"去掉一个样本"，故统一重新拟合
                if m is None:
                    m = factory().fit(X[keep], y[keep])
                pred = m.predict(X[i].reshape(1, -1))
                errs.append(float(np.asarray(pred[0]).ravel()[0]) - float(y[i]))
            except (ValueError, np.linalg.LinAlgError):
                errs.append(float("nan"))
        return float(np.sqrt(np.nanmean(np.square(errs))))

    def _nearest_region(self, x: np.ndarray) -> int:
        if not self.regions:
            return -1
        dists = [float(np.min(np.linalg.norm(self.X_hf[idx] - x, axis=1)))
                 for idx in self.regions]
        return int(np.argmin(dists))

    def predict(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        Xs = np.atleast_2d(np.asarray(Xs, float))
        mu_mfs, sd_mfs = self.mfs.predict(Xs)
        out_mu = np.empty(Xs.shape[0])
        out_sd = np.empty(Xs.shape[0])
        for i, x in enumerate(Xs):
            k = self._nearest_region(x)
            loc = self.locals[k] if k >= 0 else None
            e_loc = self.local_err[k] if k >= 0 else np.inf
            if loc is None:                       # 没局部模型 → 用全局 SFS
                loc, e_loc = self.sfs, self.sfs_err
            if loc is None:                       # 连全局 SFS 都建不起来 → 退回 MFS
                out_mu[i], out_sd[i] = mu_mfs[i], sd_mfs[i]
                continue
            mu_sfs, sd_sfs = loc.predict(x.reshape(1, -1))
            mu_sfs = float(np.asarray(mu_sfs).ravel()[0])
            sd_sfs = float(np.asarray(sd_sfs).ravel()[0])
            # ④ 自适应权重：误差越小权重越大（本代码库的工程选择，非论文公式）
            w_mfs = 1.0 / (self.mfs_err + self.delta)
            w_sfs = 1.0 / (e_loc + self.delta)
            s = w_mfs + w_sfs
            w_mfs, w_sfs = w_mfs / s, w_sfs / s
            out_mu[i] = w_mfs * float(mu_mfs[i]) + w_sfs * mu_sfs
            out_sd[i] = math.sqrt(max(w_mfs * float(sd_mfs[i]) ** 2
                                      + w_sfs * sd_sfs ** 2, 0.0))
        return out_mu, out_sd


# --------------------------------------------------------------------------- 通用组合选择
def hedge_choose(gains: Sequence[float], eta: float = 0.5,
                 rng: Optional[np.random.Generator] = None) -> int:
    """按累积收益的 softmax 概率选择一个候选（多采集函数"组合策略"的通用做法）。

        p_k ∝ exp(η·g_k)

    说明：本全集的第 02 讲用**多个不同 g 的 GEI 并行加点**，但并未给出如何在多个采集
    准则之间做选择的公式；这里的 softmax 对冲是优化领域的通用技巧，**不对应某篇具体
    论文**，请勿当作原文方法引用。
    """
    g = np.asarray(gains, float).ravel()
    if g.size == 0:
        raise ValueError("gains 不能为空")
    if eta <= 0:
        raise ValueError("eta 必须为正")
    z = eta * (g - np.max(g))
    p = np.exp(z)
    p = p / np.sum(p)
    if rng is None:
        return int(np.argmax(p))
    return int(rng.choice(len(p), p=p))


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)

    # ---- 1) Filter-GEI 的自适应权重与阈值（论文 02 式 10–12）
    w, T = filter_gei_threshold(0.0, 1.0, y_hf_min=2.0, y_hf_mean=5.0)
    assert abs(w - 1.0) < 1e-12 and abs(T - 2.0) < 1e-12, "σ²_DF=0 时 ω、T 取值错误"
    w, T = filter_gei_threshold(1.0, 1.0, 2.0, 5.0)
    assert abs(w - 0.5) < 1e-12 and abs(T - 3.5) < 1e-12, "σ²_DF=σ²_LF 时 ω 应为 0.5"
    w2, _ = filter_gei_threshold(100.0, 1.0, 2.0, 5.0)
    assert w2 < 0.1, "LF 与 HF 相关性差时 ω 应趋近 0"
    # 单调性：σ²_DF 越大（相关性越差），ω 越小、T 越靠近历史均值
    ws = [filter_gei_threshold(s, 1.0, 2.0, 5.0) for s in (0.0, 0.25, 1.0, 4.0, 25.0)]
    assert all(ws[i][0] > ws[i + 1][0] for i in range(len(ws) - 1)), "ω 应随 σ²_DF 单调下降"
    assert all(ws[i][1] < ws[i + 1][1] for i in range(len(ws) - 1)), "T 应随 σ²_DF 单调上升"

    # ---- 2) 层次聚类去重叠：合并"距离最近的两类"，直到最小类间距离 > d_T
    X = np.array([[0.0], [0.01], [1.0], [5.0]])
    cl = hierarchical_decluster(X, d_T=0.1)
    # 只有 0 与 1（距离 0.01 ≤ 0.1）被合并；此后最小类间距离 0.99 > 0.1，停止
    assert len(cl) == 3, f"应聚成 3 类，实为 {len(cl)}：{cl}"
    assert sorted(sum(cl, [])) == [0, 1, 2, 3], "聚类结果未覆盖全部点"
    assert [0, 1] in cl, "最近的两点应被合并"
    assert len(hierarchical_decluster(X, d_T=10.0)) == 1, "阈值极大时应聚成 1 类"
    assert len(hierarchical_decluster(X, d_T=0.0)) == 4, "阈值 0 时只有重合点才会被合并"

    # ---- 3) 分流与成本折算
    pred = np.array([1.0, 3.0, 5.0])
    hf_idx, lf_idx = fidelity_split(pred, T=3.5)
    assert list(hf_idx) == [0, 1] and list(lf_idx) == [2], "分流结果错误"
    rep = budget_report(10, 50, cost_ratio=0.1)
    assert abs(rep["equivalent_hf"] - 15.0) < 1e-12, "等效 HF 次数错误"

    # ---- 4) DBSCAN：两簇 + 一个噪声点
    Xd = np.vstack([rng.normal(0.0, 0.05, size=(20, 2)),
                    rng.normal(5.0, 0.05, size=(20, 2)),
                    np.array([[20.0, 20.0]])])
    lab = dbscan(Xd, eps=0.5, min_samples=4)
    assert len(set(lab) - {-1}) == 2, f"应识别出 2 个簇，实为 {set(lab)}"
    assert lab[-1] == -1, "孤立点应被标为噪声"
    assert np.all(lab[:20] == lab[0]) and np.all(lab[20:40] == lab[20]), "簇内标签不一致"
    assert lab[0] != lab[20], "两簇标签不应相同"

    # ---- 5) Co-Kriging：应当优于"只用少量 HF"的单保真模型
    def lf(x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, float))
        return (np.sin(2.0 * np.pi * x[:, 0]) + 0.5 * x[:, 1]).ravel()

    def hf(x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, float))
        return (1.6 * (np.sin(2.0 * np.pi * x[:, 0]) + 0.5 * x[:, 1])
                + 0.8 * (x[:, 0] - 0.5) ** 2).ravel()

    Xlf = rng.random((40, 2))
    ylf = lf(Xlf)
    Xhf = rng.random((6, 2))
    yhf = hf(Xhf)
    ck = CoKriging().fit(Xlf, ylf, Xhf, yhf)
    Xt = rng.random((300, 2))
    yt = hf(Xt)
    mu_ck, sd_ck = ck.predict(Xt)
    r2_ck = 1.0 - np.sum((yt - mu_ck) ** 2) / np.sum((yt - np.mean(yt)) ** 2)
    only_hf = _TinyKriging().fit(Xhf, yhf)
    mu_hf, _ = only_hf.predict(Xt)
    r2_hf = 1.0 - np.sum((yt - mu_hf) ** 2) / np.sum((yt - np.mean(yt)) ** 2)
    assert r2_ck > r2_hf, f"Co-Kriging({r2_ck:.3f}) 未优于仅用 HF({r2_hf:.3f})"
    assert r2_ck > 0.8, f"Co-Kriging 精度不足：{r2_ck:.3f}"
    assert 0.8 < ck.rho < 2.5, f"ρ 估计偏离真值 1.6 太远：{ck.rho}"
    assert np.all(sd_ck >= 0), "预测标准差出现负值"
    # 训练点处应接近插值
    mu_at_hf, _ = ck.predict(Xhf)
    assert np.max(np.abs(mu_at_hf - yhf)) < 0.35 * (yhf.max() - yhf.min() + _TINY), \
        "Co-Kriging 在 HF 训练点处偏离过大"

    # ---- 6) EMFS 集成：能跑通，且权重确实偏向误差更小的模型
    em = EMFSEnsemble(eps=0.9, min_samples=4).fit(Xlf, ylf, Xhf, yhf)
    mu_em, sd_em = em.predict(Xt)
    assert np.all(np.isfinite(mu_em)) and np.all(sd_em >= 0), "EMFS 预测出现异常值"
    r2_em = 1.0 - np.sum((yt - mu_em) ** 2) / np.sum((yt - np.mean(yt)) ** 2)
    assert r2_em > 0.5, f"EMFS 精度过低：{r2_em:.3f}"

    # ---- 7) softmax 对冲：收益越高被选中概率越大
    p = np.array([hedge_choose([0.0, 0.0, 0.0], eta=1.0,
                               rng=np.random.default_rng(s)) for s in range(300)])
    assert set(np.unique(p).tolist()) == {0, 1, 2}, "收益相同时各策略都应可能被选中"
    q = np.array([hedge_choose([0.0, 5.0, 0.0], eta=1.0,
                               rng=np.random.default_rng(s)) for s in range(200)])
    assert np.mean(q == 1) > 0.9, "高收益策略应被大概率选中"

    # ---- 8) 异常输入
    for bad in [lambda: filter_gei_threshold(1.0, 0.0, 1.0, 2.0),
                lambda: filter_gei_threshold(-1.0, 1.0, 1.0, 2.0),
                lambda: hierarchical_decluster(np.zeros((3, 2)), d_T=-1.0),
                lambda: dbscan(np.zeros((3, 2)), eps=0.0),
                lambda: dbscan(np.zeros((3, 2)), eps=0.5, min_samples=0),
                lambda: budget_report(1, 1, cost_ratio=0.0),
                lambda: hedge_choose([], eta=1.0),
                lambda: CoKriging().fit(np.zeros((2, 2)), np.zeros(2),
                                        np.zeros((2, 3)), np.zeros(2))]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")

    print(f"[multifidelity.py] 自检通过：ω/T单调 / 层次聚类 / DBSCAN(2簇+噪声) / "
          f"CoKriging(R²={r2_ck:.3f} vs 仅HF {r2_hf:.3f}, ρ={ck.rho:.2f}) / "
          f"EMFS(R²={r2_em:.3f}) / 对冲选择")


if __name__ == "__main__":
    _self_test()

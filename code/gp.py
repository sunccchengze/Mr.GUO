"""gp.py —— 普通 Kriging（高斯过程回归）与 EGO 采集函数

本全集中以 **Kriging / 高斯过程** 为方法核心或基础组件的论文（均可在 corpus/ 中核对）：
  * 论文 01（CR-EI）、论文 02（Filter-GEI）—— 在 Kriging 上构造期望改善类采集函数［原文 P01 §2 / P02 §2］
  * 论文 03 —— 端壁造型三项指标各建 Kriging 代理，再用 EGO 分别优化［原文 P03 §2.4］
  * 论文 04 —— 基于 Kriging 代理的高效 UQ + 全局灵敏度分析［出版商页面 摘要，论文 04］
  * 论文 06（GMFoO）、论文 08（KT-ASO）—— 贝叶斯优化内核以 GP 为代理［原文 P06 §III / P08 §3］
  * 论文 17（GTO）—— 对比"co-kriging 型 MFS"与 EMFS 两种多保真代理［原文 P17 §4］
  * 论文 16 —— 仅把 GPR 作为与 TNO 对比的 5 种传统代理之一［原文 P16 Table 7］
本模块给出"单保真度普通 Kriging"的最小可用实现：各向异性高斯相关函数、ARD 长度尺度
的集中似然估计、预测均值/方差，以及 EI / GEI 形式（论文 02）的采集函数。
（本模块不实现任何论文专有变体；论文 05 用的是均匀设计 + 方差分解而非 Kriging，见 sampling.py。）

数学形式（普通 Kriging 的标准写法）：
     Y(x) = μ + Z(x),   Corr[Z(x), Z(x')] = exp( - Σ_j θ_j (x_j - x'_j)² )
超参数 (μ, σ², θ) 由**集中对数似然**最大化得到：
     ln L = -n/2·ln σ̂² - 1/2·ln|R|
其中 σ̂² = (y-1μ̂)' R⁻¹ (y-1μ̂)/n，μ̂ = (1'R⁻¹y)/(1'R⁻¹1)。

**只依赖 numpy**：超参数搜索用"坐标方向黄金分割 + 随机重启"实现（不引入 scipy）。

运行自检：
    python code/gp.py
自检内容：训练点插值性质、留一误差量级、超参数恢复、EI 在已知最优处为 0、
    预测方差 ≥0、以及 GP 代 ANOVA 一阶效应（论文 04 思路）的排序正确性。
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "Kriging",
    "squared_exponential_corr",
    "expected_improvement",
    "generalized_expected_improvement",
    "first_order_effects",
    "anova_variance_shares",
]

_TINY = 1e-12
_ERF = np.vectorize(math.erf, otypes=[float])


# --------------------------------------------------------------------------- 相关函数
def squared_exponential_corr(X: np.ndarray, Y: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """各向异性（ARD）高斯相关矩阵：R[i,j] = exp(-Σ_k θ_k (X_ik - Y_jk)²)。

    X: (n, d)，Y: (m, d)，theta: (d,)。X 与 Y 应已按同一尺度归一化。
    """
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    theta = np.asarray(theta, dtype=float).ravel()
    if X.ndim == 1:
        X = X.reshape(1, -1)
    if Y.ndim == 1:
        Y = Y.reshape(1, -1)
    if X.shape[1] != Y.shape[1]:
        raise ValueError("X 与 Y 的维度不一致")
    if theta.size == 1 and X.shape[1] > 1:
        theta = np.repeat(theta, X.shape[1])
    # (n,1,d) - (1,m,d) -> (n,m,d) -> 加权平方 -> (n,m)
    diff = X[:, None, :] - Y[None, :, :]
    d2 = np.einsum("nmk,k->nm", diff ** 2, theta)
    return np.exp(-d2)


def _chol_solve(L: np.ndarray, b: np.ndarray) -> np.ndarray:
    """用下三角 Cholesky 因子 L 解 (L Lᵀ) z = b。"""
    y = np.linalg.solve(L, b)
    return np.linalg.solve(L.T, y)


def _stable_chol(R: np.ndarray) -> Optional[np.ndarray]:
    """尝试 Cholesky 分解；失败返回 None（表明 θ 过大/样本重复导致矩阵接近奇异）。"""
    try:
        return np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        return None


# --------------------------------------------------------------------------- 主类
class Kriging:
    """普通 Kriging（常数趋势 + 高斯相关 + 小 nugget）。

    典型用法：:
        gp = Kriging().fit(X, y)          # X: (n,d) 原始尺度；y: (n,)
        mu, sd = gp.predict(Xs)           # 返回均值与标准差
        loocv = gp.leave_one_out_rmse()   # 模型可信度自检
    """

    def __init__(self,
                 nugget: float = 1e-8,
                 theta0: Optional[np.ndarray] = None,
                 n_restarts: int = 3,
                 seed: int = 0):
        self.nugget = float(nugget)
        self.theta0 = None if theta0 is None else np.asarray(theta0, float).ravel()
        self.n_restarts = int(n_restarts)
        self.seed = int(seed)

        # 拟合后写入
        self.X: Optional[np.ndarray] = None      # 归一化后的训练点 (n,d)
        self.y: Optional[np.ndarray] = None      # **标准化后**的响应（零均值单位方差）
        self.y_mean: float = 0.0                 # 标准化用的均值
        self.y_std: float = 1.0                  # 标准化用的标准差
        self.theta: Optional[np.ndarray] = None  # ARD 长度尺度参数（归一化尺度）
        self.mu: float = 0.0                    # 常数趋势 μ̂
        self.sigma2: float = 1.0                # 过程方差 σ̂²
        self.xmin: Optional[np.ndarray] = None  # 原始尺度下界
        self.xspan: Optional[np.ndarray] = None  # 原始尺度跨度
        self.Rinv_y: Optional[np.ndarray] = None
        self.loglik: float = -np.inf

    # ---------------- 归一化工具
    def _to_unit(self, A: np.ndarray) -> np.ndarray:
        return (np.asarray(A, float) - self.xmin) / self.xspan

    def _from_unit(self, A: np.ndarray) -> np.ndarray:
        return np.asarray(A, float) * self.xspan + self.xmin

    # ---------------- 集中似然
    def _loglik(self, theta: np.ndarray) -> Tuple[float, Optional[dict]]:
        """给定 θ 计算集中对数似然；同时返回中间量，避免重复分解。"""
        R = squared_exponential_corr(self.X, self.X, theta)
        R[np.diag_indices_from(R)] += self.nugget
        L = _stable_chol(R)
        if L is None:
            return -np.inf, None
        one = np.ones(self.X.shape[0])
        Rinv_one = _chol_solve(L, one)
        Rinv_y = _chol_solve(L, self.y)
        mu = float(one @ Rinv_y) / float(one @ Rinv_one)
        resid = self.y - one * mu
        sigma2 = float(resid @ _chol_solve(L, resid)) / self.X.shape[0]
        if sigma2 <= 0:
            return -np.inf, None
        logdet = 2.0 * float(np.sum(np.log(np.diag(L))))
        ll = -0.5 * self.X.shape[0] * math.log(sigma2) - 0.5 * logdet
        return ll, {"L": L, "mu": mu, "sigma2": sigma2, "Rinv_y": Rinv_y,
                    "Rinv_one": Rinv_one, "theta": np.asarray(theta, float).copy()}

    def _search_theta(self, d: int) -> np.ndarray:
        """坐标方向黄金分割 + 随机重启搜索 log10(θ) ∈ [-3, 2]。"""
        rng = np.random.default_rng(self.seed)

        def golden(f: Callable[[float], float], a: float, b: float, iters: int = 18) -> float:
            gr = (math.sqrt(5.0) - 1.0) / 2.0
            c, dd = b - gr * (b - a), a + gr * (b - a)
            fc, fd = f(c), f(dd)
            for _ in range(iters):
                if fc > fd:
                    b, dd, fd = dd, c, fc
                    c = b - gr * (b - a)
                    fc = f(c)
                else:
                    a, c, fc = c, dd, fd
                    dd = a + gr * (b - a)
                    fd = f(dd)
            return (a + b) / 2.0

        starts: List[np.ndarray] = []
        if self.theta0 is not None and self.theta0.size == d:
            starts.append(np.log10(np.clip(self.theta0, 1e-3, 1e2)))
        starts.append(np.zeros(d))            # θ = 1
        starts.append(np.full(d, -1.0))       # θ = 0.1（平滑）
        for _ in range(max(0, self.n_restarts - len(starts))):
            starts.append(rng.uniform(-2.5, 1.5, size=d))

        best_ll, best = -np.inf, np.zeros(d)
        for s in starts:
            cur = s.copy()
            cur_ll, _ = self._loglik(10.0 ** cur)
            if not np.isfinite(cur_ll):
                cur_ll = -np.inf
            for _ in range(3):                 # 3 轮坐标扫描
                for k in range(d):
                    def f(v: float, k=k, cur=cur) -> float:
                        trial = cur.copy()
                        trial[k] = v
                        ll, _ = self._loglik(10.0 ** trial)
                        return -np.inf if not np.isfinite(ll) else ll
                    cur[k] = golden(f, -3.0, 2.0)
                cur_ll, _ = self._loglik(10.0 ** cur)
            if np.isfinite(cur_ll) and cur_ll > best_ll:
                best_ll, best = cur_ll, cur.copy()
        return 10.0 ** best

    # ---------------- 拟合
    def fit(self, X: np.ndarray, y: np.ndarray) -> "Kriging":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        if X.shape[0] != y.shape[0]:
            raise ValueError("X 与 y 的样本数不一致")
        if X.shape[0] < 2:
            raise ValueError("至少需要 2 个样本")

        self.xmin = X.min(axis=0)
        self.xspan = X.max(axis=0) - self.xmin
        self.xspan[self.xspan <= 0] = 1.0      # 常数列保护
        # 输入归一化到 [0,1]^d，输出标准化到零均值单位方差
        # ——两步都只为数值稳定：Kriging 的相关矩阵在原始量纲下条件数可能高达 1e8 以上，
        #   会使"训练点处精确插值"这一理论性质在浮点运算中丢失。
        self.X = self._to_unit(X)
        self.y_mean = float(np.mean(y))
        self.y_std = float(np.std(y))
        self.y_std = self.y_std if self.y_std > _TINY else 1.0
        self.y = (y - self.y_mean) / self.y_std

        self.theta = self._search_theta(X.shape[1])
        ll, aux = self._loglik(self.theta)
        if aux is None:                        # 极端退化时退回平滑先验
            self.theta = np.full(X.shape[1], 0.1)
            ll, aux = self._loglik(self.theta)
        if aux is None:                        # pragma: no cover
            raise RuntimeError("Kriging 拟合失败：相关矩阵奇异")
        self.mu = aux["mu"]
        self.sigma2 = aux["sigma2"]
        self.Rinv_y = aux["Rinv_y"]
        self.Rinv_one = aux["Rinv_one"]
        self.L = aux["L"]
        self.loglik = ll
        return self

    # ---------------- 预测
    def predict(self, Xs: np.ndarray, return_var: bool = False):
        """返回 (均值, 标准差)；return_var=True 时第二项改为方差。"""
        Xs = np.asarray(Xs, dtype=float)
        if Xs.ndim == 1:
            Xs = Xs.reshape(1, -1)
        Zs = self._to_unit(Xs)
        n = self.X.shape[0]
        mu_list, s2_list = [], []
        for z in Zs:                            # 逐点（n 通常不大，代码保持直白）
            r = squared_exponential_corr(z.reshape(1, -1), self.X, self.theta).ravel()
            Rinv_r = _chol_solve(self.L, r)
            mu = self.mu + float(r @ (self.Rinv_y - self.mu * self.Rinv_one))
            s2 = self.sigma2 * max(0.0, 1.0 + self.nugget - float(r @ Rinv_r))
            mu_list.append(mu)
            s2_list.append(max(s2, 0.0))
        mean = np.array(mu_list) * self.y_std + self.y_mean
        var = np.array(s2_list) * (self.y_std ** 2)
        return (mean, var) if return_var else (mean, np.sqrt(var))

    # ---------------- 诊断
    def leave_one_out_rmse(self) -> float:
        """留一交叉验证 RMSE（衡量代理模型可信度；论文 03/14 的模型验证思路）。"""
        n = self.X.shape[0]
        errs = []
        for i in range(n):
            keep = np.ones(n, dtype=bool)
            keep[i] = False
            sub = Kriging(nugget=self.nugget, theta0=self.theta,
                          n_restarts=1, seed=self.seed).fit(self.X[keep], self.y[keep])
            # 子模型直接在"标准化坐标"里拟合与预测，故误差也是标准化单位
            mu, _ = sub.predict(self.X[i].reshape(1, -1), return_var=False)
            errs.append(float(mu[0]) - float(self.y[i]))
        # 换算回原始量纲
        return float(np.sqrt(np.mean(np.square(errs))) * self.y_std)

    def r2(self, X: np.ndarray, y: np.ndarray) -> float:
        """在独立测试集上的决定系数 R²。"""
        mu, _ = self.predict(X)
        y = np.asarray(y, float).ravel()
        ss_res = float(np.sum((y - mu) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= _TINY:
            return 1.0 if ss_res <= _TINY else 0.0
        return 1.0 - ss_res / ss_tot


# --------------------------------------------------------------------------- 采集函数
def expected_improvement(mean: np.ndarray, sd: np.ndarray, f_best: float,
                         xi: float = 0.0) -> np.ndarray:
    """经典 EI（论文 01 的 CR-EI 即在此基础上替换"当前最优"的定义）。

    EI(x) = (f_best - ξ - μ)·Φ(u) + s·φ(u)，u = (f_best - ξ - μ)/s
    其中 φ、Φ 为标准正态密度与分布函数（用 math.erf 实现，不依赖 scipy）。
    """
    mean = np.asarray(mean, float)
    sd = np.asarray(sd, float)
    imp = f_best - xi - mean
    out = np.zeros_like(mean)
    pos = sd > _TINY
    u = np.zeros_like(mean)
    u[pos] = imp[pos] / sd[pos]
    phi = np.exp(-0.5 * u ** 2) / math.sqrt(2.0 * math.pi)
    Phi = 0.5 * (1.0 + _ERF(u / math.sqrt(2.0)))
    out[pos] = imp[pos] * Phi[pos] + sd[pos] * phi[pos]
    return out


def generalized_expected_improvement(mean: np.ndarray, sd: np.ndarray,
                                     f_best: float, g: int = 1) -> np.ndarray:
    """广义期望改善 GEI（论文 02 的 Filter-GEI 所用准则）：

        GEI_g(x) = s^g · Σ_{k=0}^{g} (-1)^k · C(g,k) · u^{g-k} · T_k
    其中 u = (f_best - μ)/s，T_k 由递推 T_0 = Φ(u)、T_1 = -φ(u)、
    T_k = -u^{k-1} φ(u) + (k-1) T_{k-2} 给出。g=1 时退化为经典 EI。
    """
    mean = np.asarray(mean, float)
    sd = np.asarray(sd, float)
    u = np.where(sd > _TINY, (f_best - mean) / np.where(sd > _TINY, sd, 1.0), 0.0)
    phi = np.exp(-0.5 * u ** 2) / math.sqrt(2.0 * math.pi)
    Phi = 0.5 * (1.0 + _ERF(u / math.sqrt(2.0)))

    T = [Phi, -phi]
    for k in range(2, g + 1):
        T.append(-(u ** (k - 1)) * phi + (k - 1) * T[k - 2])

    out = np.zeros_like(mean)
    for k in range(g + 1):
        coef = math.comb(g, k) * ((-1.0) ** k)
        out += coef * (u ** (g - k)) * T[k]
    return (sd ** g) * out


# --------------------------------------------------------------------------- 方差分解（论文 04/05）
def first_order_effects(model: Callable[[np.ndarray], np.ndarray],
                        bounds: Sequence[Tuple[float, float]],
                        n_mc: int = 4096,
                        seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """用代理模型（如拟合好的 Kriging）做一阶效应分析，对应论文 04 的 Sobol 敏感性。

    采用 Saltelli 式两矩阵（A、B 与混合矩阵）的 Jansen 估计器：
        S_i ≈ (1/(2N)) Σ (f(B) - f(Bⁱ))² / Var(f)
    其中 Bⁱ 是 B 的第 i 列换成 A 的第 i 列。返回 (一阶指数, 各变量"主效应曲线"的方差)。
    """
    rng = np.random.default_rng(seed)
    bounds = np.asarray(bounds, float)
    d = bounds.shape[0]
    lo, span = bounds[:, 0], bounds[:, 1] - bounds[:, 0]
    A = lo + rng.random((n_mc, d)) * span
    B = lo + rng.random((n_mc, d)) * span
    fA = np.asarray(model(A), float).ravel()
    fB = np.asarray(model(B), float).ravel()

    tot = float(np.var(np.concatenate([fA, fB])))
    if tot <= _TINY:
        return np.zeros(d), np.zeros(d)

    s1 = np.zeros(d)
    eff_var = np.zeros(d)
    for i in range(d):
        Bi = B.copy()
        Bi[:, i] = A[:, i]
        fBi = np.asarray(model(Bi), float).ravel()
        s1[i] = float(np.mean((fB - fBi) ** 2)) / (2.0 * tot)
        # 主效应：沿第 i 维把其它维固定在 A 上扫一遍，取响应的方差
        grid = np.tile(A, (1, 1))
        sweep = np.linspace(0.0, 1.0, 21)
        curve = []
        for t in sweep:
            g = grid.copy()
            g[:, i] = lo[i] + t * span[i]
            curve.append(float(np.mean(model(g))))
        eff_var[i] = float(np.var(curve))
    return np.clip(s1, 0.0, 1.0), eff_var


def anova_variance_shares(model: Callable[[np.ndarray], np.ndarray],
                          bounds: Sequence[Tuple[float, float]],
                          n_mc: int = 4096,
                          seed: int = 0) -> np.ndarray:
    """把一阶指数归一化为"方差贡献占比（%）"，便于与论文 04/05 的 ANOVA 结论对照。"""
    s1, _ = first_order_effects(model, bounds, n_mc=n_mc, seed=seed)
    s = float(np.sum(s1))
    if s <= _TINY:
        return np.zeros_like(s1)
    return 100.0 * s1 / s


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(20240905)

    # 用一个 2 维解析函数做真值
    def camel6(x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, float))
        x1, x2 = x[:, 0], x[:, 1]
        return (4.0 - 2.1 * x1 ** 2 + x1 ** 4 / 3.0) * x1 ** 2 + x1 * x2 + (-4.0 + 4.0 * x2 ** 2) * x2 ** 2

    bounds = [(-3.0, 3.0), (-2.0, 2.0)]
    lo = np.array([b[0] for b in bounds])
    span = np.array([b[1] - b[0] for b in bounds])

    # 1) 采样拟合
    n = 40
    X = lo + rng.random((n, 2)) * span
    y = camel6(X)
    gp = Kriging(nugget=1e-8, n_restarts=2, seed=1).fit(X, y)

    # 2) 插值性质：训练点处预测应几乎等于观测值（用响应量程做相对容差）
    mu_tr, sd_tr = gp.predict(X)
    rel_err = float(np.max(np.abs(mu_tr - y)) / (np.max(y) - np.min(y)))
    assert rel_err < 1e-3, f"Kriging 未通过训练点（插值性质失效，相对误差 {rel_err:.2e}）"
    assert np.all(sd_tr >= 0), "预测方差出现负值"

    # 3) 泛化：独立测试集 R² 应明显为正
    Xt = lo + rng.random((500, 2)) * span
    yt = camel6(Xt)
    r2 = gp.r2(Xt, yt)
    assert r2 > 0.8, f"测试集 R² 过低：{r2:.3f}"

    # 4) 远离训练数据的地方，预测方差应大于近邻处
    _, sd_far = gp.predict(np.array([[2.9, 1.9]]))
    _, sd_near = gp.predict(X[:1])
    assert sd_far[0] > sd_near[0], "外推区不确定性未增大"

    # 5) 留一误差应小于响应量级
    loo = gp.leave_one_out_rmse()
    assert loo < 0.5 * (yt.max() - yt.min()), f"留一 RMSE 过大：{loo}"

    # 6) EI：在当前最优处为 0，且非负；GEI(g=1) 应与 EI 一致
    fbest = float(np.min(y))
    mu_t, sd_t = gp.predict(Xt)
    ei = expected_improvement(mu_t, sd_t, fbest)
    assert np.all(ei >= -1e-12), "EI 出现负值"
    ei_at_best = expected_improvement(np.array([fbest]), np.array([1e-6]), fbest)[0]
    assert abs(ei_at_best) < 1e-6, "EI 在当前最优处应为 0"
    gei1 = generalized_expected_improvement(mu_t, sd_t, fbest, g=1)
    assert np.allclose(ei, gei1, atol=1e-8), "GEI(g=1) 与 EI 不一致"
    gei2 = generalized_expected_improvement(mu_t, sd_t, fbest, g=2)
    assert np.all(gei2 >= -1e-12), "GEI(g=2) 出现负值"

    # 7) 一阶效应：camel6 对 x1 更敏感（x1 的项量级更大）
    s1, _ = first_order_effects(lambda Z: gp.predict(Z)[0], bounds, n_mc=512, seed=3)
    assert s1[0] > s1[1], f"一阶效应排序不符：{s1}"
    shares = anova_variance_shares(lambda Z: gp.predict(Z)[0], bounds, n_mc=512, seed=3)
    assert abs(float(np.sum(shares)) - 100.0) < 1e-6, "占比未归一化到 100%"

    # 8) 异常输入
    try:
        Kriging().fit(np.zeros((5, 2)), np.zeros(3))
    except ValueError:
        pass
    else:
        raise AssertionError("样本数不匹配未报错")

    print(f"[gp.py] 自检通过：插值性 R²={r2:.3f} / 留一RMSE={loo:.3f} / "
          f"EI-GEI 一致 / 一阶效应 S1={np.round(s1, 3)}")


if __name__ == "__main__":
    _self_test()

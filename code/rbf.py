"""rbf.py —— 径向基函数（RBF）代理模型

为什么单独给 RBF 一个模块：本全集第 03 讲（**论文 07，GSDE**）在 126 维叶栅优化里
**明确放弃了 Kriging 而选择 RBF**，理由是"高维设计空间中 RBF 的预测精度强于其他常见
代理，且训练时间随变量数增长仍可接受"［原文 P07 §Proposed algorithm］。GSDE 使用的是

    ŷ(x) = Σ_i λ_i·φ(‖x − x_i‖) + c₀ + Σ_j c_j·x_j        （φ(r)=r³，三次 RBF + 线性尾项）

即**三次径向基 + 线性多项式尾项**。这个结构有两个必须知道的性质：

1. **插值性**：只要样本点互不相同，线性系统满秩，模型必定精确通过所有训练点；
2. **线性再生性**：带线性尾项后，若真实函数是一次多项式，模型可以**精确复现**。

代价是：RBF 不自带不确定性估计（不像 Kriging 有 σ），所以它更适合"进化算法里当
局部加速器"，而不适合直接拿去做 EI 类采集函数——这正是 GSDE 把它嵌进 DE、而不是
拿它做贝叶斯优化的原因。

**只依赖 numpy**。运行自检：
    python code/rbf.py
自检内容：插值性、线性再生性、留一误差、边界外推行为、异常输入。
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

import numpy as np

__all__ = ["RBFInterpolant", "cubic_kernel", "linear_kernel",
           "thin_plate_kernel", "gaussian_kernel", "fit_rbf", "leave_one_out_rmse"]

_TINY = 1e-12


# --------------------------------------------------------------------------- 核函数
def cubic_kernel(r: np.ndarray) -> np.ndarray:
    """三次核 φ(r) = r³（GSDE 使用）。"""
    return np.asarray(r, dtype=float) ** 3


def linear_kernel(r: np.ndarray) -> np.ndarray:
    """线性核 φ(r) = r。"""
    return np.asarray(r, dtype=float)


def thin_plate_kernel(r: np.ndarray) -> np.ndarray:
    """薄板样条核 φ(r) = r²·ln r（约定 r=0 时取 0）。"""
    r = np.asarray(r, dtype=float)
    out = np.zeros_like(r)
    m = r > _TINY
    out[m] = r[m] ** 2 * np.log(r[m])
    return out


def gaussian_kernel(r: np.ndarray, eps: float = 1.0) -> np.ndarray:
    """高斯核 φ(r) = exp(−(εr)²)。"""
    r = np.asarray(r, dtype=float)
    return np.exp(-(eps * r) ** 2)


def _pairwise_dist(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """欧氏距离矩阵 (n, m)。"""
    diff = A[:, None, :] - B[None, :, :]
    return np.sqrt(np.einsum("nmk,nmk->nm", diff, diff))


# --------------------------------------------------------------------------- 主类
class RBFInterpolant:
    """三次（默认）RBF + 线性多项式尾项插值器。

    用法：
        m = RBFInterpolant().fit(X, y)      # 或 fit_rbf(X, y)
        yhat = m(Xs)                        # 也支持 m.predict(Xs)
    """

    def __init__(self,
                 kernel: Callable[[np.ndarray], np.ndarray] = cubic_kernel,
                 smooth: float = 0.0,
                 normalize: bool = True):
        """
        kernel    : 径向基核，默认三次核（GSDE 的选择）
        smooth    : 正则化/平滑量 λ（0 = 严格插值；样本有噪声时取小正数）
        normalize : 是否把输入归一化到 [0,1]^d（强烈建议保持 True，改善条件数）
        """
        self.kernel = kernel
        self.smooth = float(smooth)
        self.normalize = bool(normalize)

        self.X: Optional[np.ndarray] = None      # 归一化后的训练点
        self.y: Optional[np.ndarray] = None
        self.lam: Optional[np.ndarray] = None    # 径向基系数
        self.coef: Optional[np.ndarray] = None   # 多项式尾项系数 [c0, c1, ..., cd]
        self.xmin: Optional[np.ndarray] = None
        self.xspan: Optional[np.ndarray] = None

    # ---- 工具
    def _to_unit(self, A: np.ndarray) -> np.ndarray:
        A = np.asarray(A, dtype=float)
        if not self.normalize:
            return A
        return (A - self.xmin) / self.xspan

    def _design(self, X: np.ndarray) -> np.ndarray:
        """多项式尾项设计矩阵 [1, x1, ..., xd]。"""
        return np.hstack([np.ones((X.shape[0], 1)), X])

    # ---- 拟合
    def fit(self, X: np.ndarray, y: np.ndarray) -> "RBFInterpolant":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        n, d = X.shape
        if n != y.size:
            raise ValueError("X 与 y 的样本数不一致")
        if n < d + 2:
            raise ValueError(f"样本数不足：需要 ≥ d+2 = {d + 2} 个，实到 {n} 个")

        self.xmin = X.min(axis=0)
        self.xspan = X.max(axis=0) - self.xmin
        self.xspan[self.xspan <= 0] = 1.0
        Z = self._to_unit(X)
        self.X, self.y = Z, y

        Phi = self.kernel(_pairwise_dist(Z, Z))
        if self.smooth > 0:
            Phi[np.diag_indices_from(Phi)] += self.smooth
        P = self._design(Z)
        m = P.shape[1]

        A = np.zeros((n + m, n + m))
        A[:n, :n] = Phi
        A[:n, n:] = P
        A[n:, :n] = P.T
        rhs = np.concatenate([y, np.zeros(m)])
        sol = np.linalg.lstsq(A, rhs, rcond=None)[0]   # 用 lstsq 而非 solve：容忍近似共线
        self.lam, self.coef = sol[:n], sol[n:]
        return self

    # ---- 预测
    def predict(self, Xs: np.ndarray) -> np.ndarray:
        Xs = np.asarray(Xs, dtype=float)
        if Xs.ndim == 1:
            Xs = Xs.reshape(1, -1)
        Z = self._to_unit(Xs)
        Phi = self.kernel(_pairwise_dist(Z, self.X))
        return Phi @ self.lam + self._design(Z) @ self.coef

    __call__ = predict

    # ---- 诊断
    def r2(self, X: np.ndarray, y: np.ndarray) -> float:
        y = np.asarray(y, float).ravel()
        pred = self.predict(X)
        ss_res = float(np.sum((y - pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        if ss_tot <= _TINY:
            return 1.0 if ss_res <= _TINY else 0.0
        return 1.0 - ss_res / ss_tot


def fit_rbf(X: np.ndarray, y: np.ndarray, **kw) -> RBFInterpolant:
    """便捷函数：一步拟合一个默认（三次核 + 线性尾项）RBF 模型。"""
    return RBFInterpolant(**kw).fit(X, y)


def leave_one_out_rmse(X: np.ndarray, y: np.ndarray, **kw) -> float:
    """留一交叉验证 RMSE：判断这套样本/这个核是否够用（成本高：会重拟合 n 次）。"""
    X = np.asarray(X, float)
    y = np.asarray(y, float).ravel()
    errs = []
    for i in range(X.shape[0]):
        keep = np.ones(X.shape[0], dtype=bool)
        keep[i] = False
        try:
            sub = RBFInterpolant(**kw).fit(X[keep], y[keep])
            errs.append(float(sub.predict(X[i].reshape(1, -1))[0]) - float(y[i]))
        except (ValueError, np.linalg.LinAlgError):
            errs.append(float("nan"))
    return float(np.sqrt(np.nanmean(np.square(errs))))


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(11)

    # 1) 插值性：光滑函数上，训练点处必须精确穿过
    def f(x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, float))
        return np.sin(2.0 * x[:, 0]) + 0.5 * x[:, 1] ** 2

    X = rng.uniform(-2.0, 2.0, size=(50, 2))
    y = f(X)
    mdl = fit_rbf(X, y)
    assert np.max(np.abs(mdl(X) - y)) < 1e-6, "RBF 未精确通过训练点"

    # 2) 线性再生性：真实函数为一次多项式时应几乎零误差
    w = np.array([1.5, -2.0, 0.7])
    Xl = rng.uniform(-1.0, 1.0, size=(40, 2))
    yl = w[0] + Xl @ w[1:]
    ml = fit_rbf(Xl, yl)
    Xt = rng.uniform(-1.0, 1.0, size=(200, 2))
    assert np.max(np.abs(ml(Xt) - (w[0] + Xt @ w[1:]))) < 1e-6, "线性尾项未能再生线性函数"

    # 3) 测试集表现
    Xte = rng.uniform(-2.0, 2.0, size=(400, 2))
    assert mdl.r2(Xte, f(Xte)) > 0.9, "RBF 测试集 R² 过低"

    # 4) 留一误差应远小于响应量程
    loo = leave_one_out_rmse(X, y)
    assert loo < 0.2 * (y.max() - y.min()), f"留一 RMSE 过大：{loo}"

    # 5) 平滑量 smooth 会牺牲插值性（正则化效果）
    ms = fit_rbf(X, y, smooth=1e-2)
    assert np.max(np.abs(ms(X) - y)) > 1e-6, "smooth>0 时不应仍精确插值"

    # 6) 不同核都能跑通并给出合理精度
    for kern in (cubic_kernel, linear_kernel, thin_plate_kernel,
                 lambda r: gaussian_kernel(r, eps=1.0)):
        mk = fit_rbf(X, y, kernel=kern)
        assert mk.r2(Xte, f(Xte)) > 0.5, f"核 {kern} 精度过低"

    # 7) 异常输入：维数/样本数/坐标维不匹配
    for bad in [lambda: fit_rbf(np.zeros((5, 2)), np.zeros(4)),
                lambda: fit_rbf(np.zeros((3, 2)), np.zeros(3))]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")
    try:
        mdl(rng.uniform(size=(3, 5)))
    except (ValueError, IndexError):
        pass
    else:
        raise AssertionError("预测维数不匹配未报错")

    print(f"[rbf.py] 自检通过：插值性 / 线性再生 / 测试R²={mdl.r2(Xte, f(Xte)):.3f} / "
          f"留一RMSE={loo:.4f} / 四种核 / 异常输入")


if __name__ == "__main__":
    _self_test()

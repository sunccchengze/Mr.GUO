"""benchmarks.py —— 优化算法测试函数集

本模块收集本全集中各篇论文反复使用的**解析基准函数**，用于在没有 CFD 的情况下
验证优化算法的正确性与相对优劣。

选这些函数的理由（都对应到具体论文）：
  * Hartman6 / Shekel4 / Camel6 / Trid10 —— 论文 01（CR-EI）的 7 个基准函数中的 4 个
  * Ackley / Rosenbrock（含 6 维版本）—— 论文 06（GMFoO）与论文 08（KT-ASO）的
    源/目标任务构造直接使用了 Ackley6d 与 0.9·Ackley6d + 0.1·Rosenbrock6d
  * Ackley5 / Hartman6 —— 论文 02（Filter-GEI）Table 4 的测试函数
  * 30~90 维版本 —— 论文 11（DA-EGO）在 21 个 30~90 维函数上验证
  * 50~100 维版本 —— 论文 07（GSDE）的数值验证区间

**重要提醒**：这些函数是"廉价黑箱"，与真实 CFD 的昂贵性无关；它们只能验证
"算法的搜索逻辑"，不能验证"算法在昂贵场景下的样本效率"。真要评估后者，必须
统计**函数评估次数**（本模块中每个 Problem 都会记录 eval_count）。

运行自检：
    python code/benchmarks.py
自检内容：已知全局最优值、维度与边界一致性、评估计数、以及"越接近最优点函数值越小"的
    单调性抽查。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

__all__ = [
    "Problem",
    "get_problem",
    "list_problems",
    "sphere", "rosenbrock", "ackley", "griewank", "levy", "trid",
    "hartman6", "shekel4", "branin", "camel6",
]


# --------------------------------------------------------------------------- 容器
class Problem:
    """一个带边界、已知最优值与评估计数的优化问题（统一按**最小化**处理）。"""

    def __init__(self,
                 name: str,
                 func: Callable[[np.ndarray], float],
                 dim: int,
                 bounds: List[Tuple[float, float]],
                 fmin: float,
                 xmin: Optional[np.ndarray] = None,
                 note: str = ""):
        self.name = name
        self.func = func
        self.dim = dim
        self.bounds = bounds
        self.fmin = fmin                      # 已知全局最小值（文献值）
        self.xmin = None if xmin is None else np.asarray(xmin, dtype=float)
        self.note = note
        self.eval_count: int = 0              # 昂贵评估次数统计
        self.history: List[float] = []        # 每次评估的目标值（便于画收敛曲线）

    def __call__(self, x: np.ndarray) -> float:
        x = np.asarray(x, dtype=float).ravel()
        if x.size != self.dim:
            raise ValueError(f"{self.name} 期望 {self.dim} 维，收到 {x.size} 维")
        y = float(self.func(x))
        self.eval_count += 1
        self.history.append(y)
        return y

    def reset(self) -> None:
        """清空评估计数与历史（做多次独立重复实验时用）。"""
        self.eval_count = 0
        self.history.clear()

    def best_so_far(self) -> float:
        """当前已评估样本中的最优值（用于画收敛曲线）。"""
        if not self.history:
            return float("inf")
        return float(np.min(self.history))

    def regret(self) -> float:
        """当前最优值与已知全局最优的差（越小越好，0 表示已找到全局最优）。"""
        return self.best_so_far() - self.fmin

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试输出
        return f"Problem({self.name}, dim={self.dim}, f*={self.fmin:.6g}, n_eval={self.eval_count})"


# --------------------------------------------------------------------------- 基本函数
def sphere(x: np.ndarray) -> float:
    """Sphere：最平凡的凸单峰函数，全局最优 0（原点）。"""
    x = np.asarray(x, dtype=float).ravel()
    return float(np.sum(x ** 2))


def rosenbrock(x: np.ndarray) -> float:
    """Rosenbrock：经典"香蕉谷"，全局最优 0（全 1 向量）。

    论文 06/08 用的是带平移的版本：f(x) = Σ(0.4 - x_i)² + 20·Σ(x_i - x_{i+1})²，
    即最优在 x_i = 0.4；本处提供标准版本，平移版本见 make_shifted_rosenbrock()。
    """
    x = np.asarray(x, dtype=float).ravel()
    return float(np.sum(100.0 * (x[1:] - x[:-1] ** 2) ** 2 + (1.0 - x[:-1]) ** 2))


def make_shifted_rosenbrock(dim: int = 6) -> Callable[[np.ndarray], float]:
    """论文 08（KT-ASO）数值验证中使用的平移 Rosenbrock：
       f(x) = Σ_{i=1}^{d}(0.4 - x_i)²  +  20·Σ_{i=1}^{d-1}(x_i - x_{i+1})²
    定义域 x_i ∈ [-2, 2]，最优在 x_i = 0.4，最优值 0。
    """
    def f(x: np.ndarray) -> float:
        x = np.asarray(x, dtype=float).ravel()
        return float(np.sum((0.4 - x) ** 2) + 20.0 * np.sum((x[:-1] - x[1:]) ** 2))
    f.__name__ = f"shifted_rosenbrock{dim}d"
    return f


def ackley(x: np.ndarray, a: float = 20.0, b: float = 0.2, c: float = 2.0 * np.pi) -> float:
    """Ackley：海量局部极小 + 全局最优 0（原点）。高维优化的常用试金石。"""
    x = np.asarray(x, dtype=float).ravel()
    d = x.size
    s1 = np.sum(x ** 2)
    s2 = np.sum(np.cos(c * x))
    return float(-a * np.exp(-b * np.sqrt(s1 / d)) - np.exp(s2 / d) + a + np.e)


def griewank(x: np.ndarray) -> float:
    """Griewank：乘积型多峰，全局最优 0（原点）。"""
    x = np.asarray(x, dtype=float).ravel()
    d = x.size
    i = np.arange(1, d + 1, dtype=float)
    return float(1.0 + np.sum(x ** 2) / 4000.0 - np.prod(np.cos(x / np.sqrt(i))))


def levy(x: np.ndarray) -> float:
    """Levy：全局最优 0（全 1 向量）。"""
    x = np.asarray(x, dtype=float).ravel()
    w = 1.0 + (x - 1.0) / 4.0
    term1 = np.sin(np.pi * w[0]) ** 2
    term3 = (w[-1] - 1.0) ** 2 * (1.0 + np.sin(2.0 * np.pi * w[-1]) ** 2)
    term2 = np.sum((w[:-1] - 1.0) ** 2 * (1.0 + 10.0 * np.sin(np.pi * w[:-1] + 1.0) ** 2))
    return float(term1 + term2 + term3)


def trid(x: np.ndarray) -> float:
    """Trid：全局最优 -d(d+4)(d-1)/6（论文 01 用 Trid10，最优值 -210）。"""
    x = np.asarray(x, dtype=float).ravel()
    d = x.size
    s1 = np.sum((x - 1.0) ** 2)
    s2 = np.sum(x[1:] * x[:-1])
    return float(s1 - s2)


def branin(x: np.ndarray) -> float:
    """Branin（2 维）：三个全局最优点，最优值 0.397887。"""
    x = np.asarray(x, dtype=float).ravel()
    x1, x2 = x[0], x[1]
    a, b, c, r, s, t = 1.0, 5.1 / (4.0 * np.pi ** 2), 5.0 / np.pi, 6.0, 10.0, 1.0 / (8.0 * np.pi)
    return float(a * (x2 - b * x1 ** 2 + c * x1 - r) ** 2 + s * (1.0 - t) * np.cos(x1) + s)


def camel6(x: np.ndarray) -> float:
    """Six-Hump Camel（2 维）：六个局部极小，两个全局最优点，最优值 -1.0316。
    论文 01（CR-EI）用它做参数敏感性分析。"""
    x = np.asarray(x, dtype=float).ravel()
    x1, x2 = x[0], x[1]
    return float((4.0 - 2.1 * x1 ** 2 + x1 ** 4 / 3.0) * x1 ** 2
                 + x1 * x2 + (-4.0 + 4.0 * x2 ** 2) * x2 ** 2)


_H6_ALPHA = np.array([1.0, 1.2, 3.0, 3.2])
_H6_A = np.array([[10.0, 3.0, 17.0, 3.5, 1.7, 8.0],
                  [0.05, 10.0, 17.0, 0.1, 8.0, 14.0],
                  [3.0, 3.5, 1.7, 10.0, 17.0, 8.0],
                  [17.0, 8.0, 0.05, 10.0, 0.1, 14.0]])
_H6_P = 1e-4 * np.array([[1312, 1696, 5569, 124, 8283, 5886],
                         [2329, 4135, 8307, 3736, 1004, 9991],
                         [2348, 1451, 3522, 2883, 3047, 6650],
                         [4047, 8828, 8732, 5743, 1091, 381]])


def hartman6(x: np.ndarray) -> float:
    """Hartman6（6 维，域 [0,1]^6）：6 个局部最优，全局最小 -3.32237。
    论文 01 中明确提到"Hartman6 有 6 个局部最优"。"""
    x = np.asarray(x, dtype=float).ravel()
    return float(-np.sum(_H6_ALPHA * np.exp(-np.sum(_H6_A * (x[None, :] - _H6_P) ** 2, axis=1))))


_S4_A = np.array([[4.0, 4.0, 4.0, 4.0],
                  [1.0, 1.0, 1.0, 1.0],
                  [8.0, 8.0, 8.0, 8.0],
                  [6.0, 6.0, 6.0, 6.0],
                  [3.0, 7.0, 3.0, 7.0],
                  [2.0, 9.0, 2.0, 9.0],
                  [5.0, 5.0, 3.0, 3.0],
                  [8.0, 1.0, 8.0, 1.0],
                  [6.0, 2.0, 6.0, 2.0],
                  [7.0, 3.6, 7.0, 3.6]], dtype=float)
_S4_C = np.array([0.1, 0.2, 0.2, 0.4, 0.4, 0.6, 0.3, 0.7, 0.5, 0.5])


def shekel4(x: np.ndarray) -> float:
    """Shekel / Shekel4（4 维，域 [0,10]^4）：论文 01 Table 1 使用的函数之一。
    这里采用 m=10 的常用 Shekel 形式，全局最小约 -10.5364。"""
    x = np.asarray(x, dtype=float).ravel()
    inner = np.sum((x[None, :] - _S4_A) ** 2, axis=1) + _S4_C
    return float(-np.sum(1.0 / inner))


# --------------------------------------------------------------------------- 注册表
def _reg() -> Dict[str, Problem]:
    p: Dict[str, Problem] = {}

    def add(prob: Problem) -> None:
        p[prob.name] = prob

    add(Problem("sphere5", sphere, 5, [(-5.12, 5.12)] * 5, 0.0, np.zeros(5),
                "凸单峰，用于 sanity check"))
    add(Problem("branin2", branin, 2, [(-5.0, 10.0), (0.0, 15.0)], 0.397887,
                np.array([-np.pi, 12.275]),
                "2 维，3 个全局最优点"))
    add(Problem("camel6", camel6, 2, [(-3.0, 3.0), (-2.0, 2.0)], -1.031628,
                np.array([0.0898, -0.7126]),
                "论文 01 参数敏感性算例"))
    add(Problem("hartman6", hartman6, 6, [(0.0, 1.0)] * 6, -3.322368,
                np.array([0.20169, 0.150011, 0.476874, 0.275332, 0.311652, 0.6573]),
                "论文 01/02 均使用；6 个局部最优"))
    add(Problem("shekel4", shekel4, 4, [(0.0, 10.0)] * 4, -10.5364,
                np.array([4.0, 4.0, 4.0, 4.0]),
                "论文 01 Table 1 使用"))
    add(Problem("trid10", trid, 10, [(-100.0, 100.0)] * 10, -210.0,
                np.arange(1, 11) * (11 - np.arange(1, 11)),
                "论文 01 Table 1 使用；最优值 -d(d+4)(d-1)/6"))
    add(Problem("ackley5", ackley, 5, [(-32.768, 32.768)] * 5, 0.0, np.zeros(5),
                "论文 02 Table 4 使用"))
    add(Problem("ackley6", ackley, 6, [(-2.0, 2.0)] * 6, 0.0, np.zeros(6),
                "论文 06/08 数值验证的目标任务"))
    add(Problem("rosenbrock6", make_shifted_rosenbrock(6), 6, [(-2.0, 2.0)] * 6, 0.0,
                np.full(6, 0.4),
                "论文 08 的平移 Rosenbrock（最优在 x_i=0.4）"))
    add(Problem("griewank10", griewank, 10, [(-600.0, 600.0)] * 10, 0.0, np.zeros(10),
                "乘积型多峰"))
    add(Problem("levy10", levy, 10, [(-10.0, 10.0)] * 10, 0.0, np.ones(10),
                "多峰，最优在全 1 向量"))
    add(Problem("rosenbrock30", rosenbrock, 30, [(-2.048, 2.048)] * 30, 0.0, np.ones(30),
                "论文 11 的 30 维量级"))
    add(Problem("ackley50", ackley, 50, [(-32.768, 32.768)] * 50, 0.0, np.zeros(50),
                "论文 07 的 50~100 维量级"))
    add(Problem("sphere100", sphere, 100, [(-5.12, 5.12)] * 100, 0.0, np.zeros(100),
                "论文 07 的 100 维量级"))
    return p


_REGISTRY: Dict[str, Problem] = _reg()


def list_problems() -> List[str]:
    """返回所有可用基准问题的名字。"""
    return sorted(_REGISTRY)


def get_problem(name: str) -> Problem:
    """按名字取一个**全新的** Problem 实例（每次调用都会重置评估计数）。"""
    if name not in _REGISTRY:
        raise KeyError(f"未知问题 {name!r}，可用：{list_problems()}")
    src = _REGISTRY[name]
    return Problem(src.name, src.func, src.dim, list(src.bounds), src.fmin, src.xmin, src.note)


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    # 1) 已知函数的最优值核对（含论文 01 提到的 Trid10 = -210）
    checks = [
        ("sphere5", np.zeros(5), 0.0),
        ("branin2", np.array([-np.pi, 12.275]), 0.397887),
        ("camel6", np.array([0.0898, -0.7126]), -1.0316),
        ("hartman6", np.array([0.20169, 0.150011, 0.476874, 0.275332, 0.311652, 0.6573]), -3.32237),
        ("trid10", np.arange(1, 11) * (11 - np.arange(1, 11)), -210.0),
        ("ackley5", np.zeros(5), 0.0),
        ("ackley6", np.zeros(6), 0.0),
        ("rosenbrock6", np.full(6, 0.4), 0.0),
        ("griewank10", np.zeros(10), 0.0),
        ("levy10", np.ones(10), 0.0),
    ]
    for name, xstar, fstar in checks:
        pr = get_problem(name)
        got = pr(xstar)
        assert abs(got - fstar) < 5e-3, f"{name} 最优值不符：{got} vs {fstar}"
        assert got <= pr.fmin + 5e-3, f"{name} 的 fmin 登记值偏小"

    # 2) 维度与边界一致
    for name in list_problems():
        pr = get_problem(name)
        assert len(pr.bounds) == pr.dim, f"{name} 边界数与维度不一致"
        for lo, hi in pr.bounds:
            assert hi > lo, f"{name} 存在非法边界"

    # 3) 评估计数与收敛记录
    pr = get_problem("hartman6")
    rng = np.random.default_rng(7)
    for _ in range(10):
        pr(rng.random(6))
    assert pr.eval_count == 10, "评估计数错误"
    assert len(pr.history) == 10, "历史长度错误"
    assert pr.best_so_far() == min(pr.history), "best_so_far 计算错误"
    pr.reset()
    assert pr.eval_count == 0 and not pr.history, "reset 未清空"

    # 4) 维度错误应报错
    try:
        pr(rng.random(5))
    except ValueError:
        pass
    else:
        raise AssertionError("维度不匹配未报错")

    # 5) 单调性抽查：沿"当前点->全局最优点"连线插值，函数值应大体下降
    pr = get_problem("ackley5")
    lo = np.array([b[0] for b in pr.bounds])
    hi = np.array([b[1] for b in pr.bounds])
    start = lo + 0.25 * (hi - lo)
    vals = [pr(start + t * (pr.xmin - start)) for t in np.linspace(0, 1, 9)]
    assert vals[-1] < vals[0], "沿指向最优点的路径函数值未下降"

    print(f"[benchmarks.py] 自检通过：{len(list_problems())} 个问题，"
          f"最优值/边界/计数/单调性 全部正确")


if __name__ == "__main__":
    _self_test()

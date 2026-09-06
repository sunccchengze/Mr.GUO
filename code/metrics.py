"""metrics.py —— 叶轮机械气动与传热评价指标

本全集所有"优化目标"最终都落在几个物理量上。要读懂各篇论文的表格，必须先把这些
指标的定义钉死。本模块给出**行业内通行的教科书定义**（不是某篇论文独创的公式），
并统一处理"面平均 / 质量平均""相对变化量""不确定度汇总"这三件最容易出错的事。

覆盖的指标与出处对照：
  * **总压损失系数** ω —— 第 17 讲（论文 09）报告"出口马赫数 0.8 时面积平均总压
    损失系数下降 14.0%"；第 03 讲（论文 07）用等熵效率评价 126 维叶栅优化
  * **面积平均气膜冷却有效度** η_aw、**面积平均努塞尔数** Nu —— 第 19 讲（论文 04）
    UQ 的两个热学输出："面积平均气膜冷却效率最大偏差 45%，面积平均 Nu 最大偏差 5.0%"
  * **面积平均综合冷却效率** φ 及其**标准差** —— 第 20 讲（论文 05）三个评价指标中的
    前两个（第三个是总压降系数）
  * **级等熵效率** —— 第 18 讲（论文 10）叶尖优化的目标函数

> ⚠️ **关于"面平均"的诚实提醒**：论文里说"面积平均"，实务中有按**几何面积**加权和
> 按**质量流量**加权两种做法，二者在强三维流场里差异可观。本模块两者都提供
> （`area_average` / `mass_average`），请在使用时明确用的是哪一种——这是本全集
> 第 19 讲反复强调的"可复现性"底线。

**只依赖 numpy**。运行自检：
    python code/metrics.py
"""

from __future__ import annotations

from typing import Dict, Sequence

import numpy as np

__all__ = [
    "area_average", "mass_average", "area_average_with_std",
    "total_pressure_loss_coefficient", "static_pressure_coefficient",
    "adiabatic_film_effectiveness", "overall_cooling_effectiveness",
    "nusselt_number", "heat_transfer_coefficient",
    "isentropic_efficiency", "compressor_efficiency",
    "relative_change", "percentage_point_change",
    "describe", "deviation_band",
]

_TINY = 1e-12


# --------------------------------------------------------------------------- 平均方式
def area_average(values: np.ndarray, areas: np.ndarray) -> float:
    """面积（或任意权重）平均：Σ w_i·v_i / Σ w_i。"""
    v = np.asarray(values, float).ravel()
    w = np.asarray(areas, float).ravel()
    if v.size != w.size:
        raise ValueError("values 与 areas 的长度不一致")
    if np.any(w < 0):
        raise ValueError("权重（面积）不能为负")
    s = float(np.sum(w))
    if s <= _TINY:
        raise ValueError("权重（面积）之和为 0")
    return float(np.sum(w * v) / s)


def mass_average(values: np.ndarray, mass_flows: np.ndarray) -> float:
    """质量流量加权平均：Σ ṁ_i·v_i / Σ ṁ_i。

    与 `area_average` 的区别只在权重的物理含义；接口分开是为了避免混用。
    """
    v = np.asarray(values, float).ravel()
    m = np.asarray(mass_flows, float).ravel()
    if v.size != m.size:
        raise ValueError("values 与 mass_flows 的长度不一致")
    if np.any(m < 0):
        raise ValueError("质量流量不能为负")
    s = float(np.sum(m))
    if s <= _TINY:
        raise ValueError("质量流量之和为 0")
    return float(np.sum(m * v) / s)


def area_average_with_std(values: np.ndarray, areas: np.ndarray) -> tuple:
    """面积平均及其（面积加权的）标准差——对应论文 05 的"综合冷却效率 + 其标准差"
    这对指标。返回 (均值, 标准差)。"""
    v = np.asarray(values, float).ravel()
    w = np.asarray(areas, float).ravel()
    mean = area_average(v, w)
    var = area_average((v - mean) ** 2, w)
    return mean, float(np.sqrt(max(var, 0.0)))


# --------------------------------------------------------------------------- 气动指标
def total_pressure_loss_coefficient(pt_in: float, pt_out: float,
                                    ps_in: float) -> float:
    """总压损失系数 ω = (p_t,in − p_t,out) / (p_t,in − p_s,in)。

    分母用**进口动压头**，所以 ω 越接近 0 越好；若出口总压高于进口（有做功或数值
    异常），ω 为负，此时应回头检查而不是直接采信。
    """
    denom = float(pt_in) - float(ps_in)
    if abs(denom) <= _TINY:
        raise ValueError("进口动压头为 0，无法定义总压损失系数")
    return (float(pt_in) - float(pt_out)) / denom


def static_pressure_coefficient(p: float, p_ref: float, q_ref: float) -> float:
    """静压系数 Cp = (p − p_ref) / q_ref（q_ref 为参考动压）。

    第 17 讲（论文 09）用它刻画非轴对称端壁对端壁静压的改变。
    """
    if abs(float(q_ref)) <= _TINY:
        raise ValueError("参考动压不能为 0")
    return (float(p) - float(p_ref)) / float(q_ref)


def isentropic_efficiency(pt_in: float, pt_out: float,
                          Tt_in: float, Tt_out: float,
                          gamma: float = 1.4) -> float:
    """涡轮等熵效率 η = (1 − T_t,out/T_t,in) / (1 − (p_t,out/p_t,in)^((γ−1)/γ))。

    分子是**实际焓降**，分母是**等熵焓降**，故 η ∈ (0,1)。
    """
    Tt_in = float(Tt_in)
    if Tt_in <= _TINY:
        raise ValueError("进口总温必须为正")
    pr = float(pt_out) / float(pt_in)
    if pr <= 0 or pr > 1.0:
        raise ValueError("涡轮的出口总压应低于进口总压（压比 ≤ 1）")
    actual = 1.0 - float(Tt_out) / Tt_in
    ideal = 1.0 - pr ** ((gamma - 1.0) / gamma)
    if abs(ideal) <= _TINY:
        raise ValueError("等熵焓降趋近 0，效率无定义")
    return actual / ideal


def compressor_efficiency(pt_in: float, pt_out: float,
                          Tt_in: float, Tt_out: float,
                          gamma: float = 1.4) -> float:
    """压气机等熵效率 η = (PR^((γ−1)/γ) − 1) / (T_t,out/T_t,in − 1)。"""
    pr = float(pt_out) / float(pt_in)
    if pr < 1.0:
        raise ValueError("压气机的压比应 ≥ 1")
    ideal = pr ** ((gamma - 1.0) / gamma) - 1.0
    actual = float(Tt_out) / float(Tt_in) - 1.0
    if abs(actual) <= _TINY:
        raise ValueError("实际温升趋近 0，效率无定义")
    return ideal / actual


# --------------------------------------------------------------------------- 传热指标
def adiabatic_film_effectiveness(T_inf: float, T_aw: float, T_c: float) -> float:
    """绝热气膜冷却有效度 η_aw = (T_∞ − T_aw) / (T_∞ − T_c)。

    T_∞ 主流温度、T_aw 绝热壁温、T_c 冷气温度。
    η=0 表示气膜完全没起作用（壁温等于主流温度），η=1 表示壁温被压到冷气温度。
    """
    denom = float(T_inf) - float(T_c)
    if abs(denom) <= _TINY:
        raise ValueError("主流与冷气温差为 0，气膜有效度无定义")
    return (float(T_inf) - float(T_aw)) / denom


def overall_cooling_effectiveness(T_inf: float, T_w: float, T_c: float) -> float:
    """综合冷却效率 φ = (T_∞ − T_w) / (T_∞ − T_c)。

    与 η_aw 的区别：φ 用的是**真实壁温**（含内部冷却），η_aw 用的是**绝热壁温**
    （只含外部气膜）。第 20 讲（论文 05）的三个指标之一就是"面积平均综合冷却效率"。
    """
    denom = float(T_inf) - float(T_c)
    if abs(denom) <= _TINY:
        raise ValueError("主流与冷气温差为 0，综合冷却效率无定义")
    return (float(T_inf) - float(T_w)) / denom


def nusselt_number(h: float, L: float, k: float) -> float:
    """努塞尔数 Nu = h·L / k（h 对流换热系数、L 特征长度、k 流体导热系数）。"""
    if abs(float(k)) <= _TINY:
        raise ValueError("导热系数不能为 0")
    return float(h) * float(L) / float(k)


def heat_transfer_coefficient(nu: float, L: float, k: float) -> float:
    """由 Nu 反算对流换热系数 h = Nu·k / L（`nusselt_number` 的逆运算）。"""
    if abs(float(L)) <= _TINY:
        raise ValueError("特征长度不能为 0")
    return float(nu) * float(k) / float(L)


# --------------------------------------------------------------------------- 变化量
def relative_change(new: float, base: float) -> float:
    """相对变化量（%）：(new − base)/|base| × 100。

    > 强烈建议统一用这个函数，而不是随手写 `a/b - 1`。第 03 讲（论文 07）里
    > "GSDE 拿到 DE 约 99% 的效率增益"就是 1.104/1.115 这种**比值**口径，而
    > "总压损失下降 14.0%"是**相对变化**口径，两者不能混为一谈。
    """
    if abs(float(base)) <= _TINY:
        raise ValueError("基准值为 0，相对变化量无定义")
    return 100.0 * (float(new) - float(base)) / abs(float(base))


def percentage_point_change(new: float, base: float) -> float:
    """百分点变化：直接相减（用于本身就是百分比的量，如效率 91.2% → 91.6%）。"""
    return float(new) - float(base)


def deviation_band(mu: float, sigma: float, k: float = 2.0) -> tuple:
    """不确定度区间 [μ − kσ, μ + kσ]（k=2 约对应 95% 置信度）。

    第 19 讲（论文 04）的 UQ 输出需要这种"均值 ± 偏差"的表述。
    """
    mu = float(mu)
    s = abs(float(sigma)) * abs(float(k))
    return (mu - s, mu + s)


def describe(values: np.ndarray, weights: np.ndarray = None) -> Dict[str, float]:
    """对一组样本给出统一的统计摘要（可选按面积加权）。

    返回 dict：n / mean / std / min / max / rsd（相对标准差 %）/ p05 / p95。
    """
    v = np.asarray(values, float).ravel()
    if v.size == 0:
        raise ValueError("输入为空")
    if weights is None:
        mean = float(np.mean(v))
        std = float(np.std(v))
    else:
        mean, std = area_average_with_std(v, weights)
    p05, p95 = np.percentile(v, [5, 95])
    return {
        "n": int(v.size),
        "mean": mean,
        "std": std,
        "min": float(np.min(v)),
        "max": float(np.max(v)),
        "rsd": (100.0 * std / abs(mean)) if abs(mean) > _TINY else float("nan"),
        "p05": float(p05),
        "p95": float(p95),
    }


# --------------------------------------------------------------------------- 自检
def _self_test() -> None:
    rng = np.random.default_rng(5)

    # 1) 面积平均：常数场 → 均值等于该常数；两块不同面积 → 手算核对
    assert abs(area_average(np.full(10, 3.0), np.ones(10)) - 3.0) < 1e-12
    assert abs(area_average(np.array([1.0, 2.0]), np.array([3.0, 1.0])) - 1.25) < 1e-12
    assert abs(mass_average(np.array([1.0, 2.0]), np.array([3.0, 1.0])) - 1.25) < 1e-12
    mu, sd = area_average_with_std(np.array([1.0, 3.0]), np.array([1.0, 1.0]))
    assert abs(mu - 2.0) < 1e-12 and abs(sd - 1.0) < 1e-12, "面积加权均值/标准差错误"
    assert area_average_with_std(np.full(5, 2.0), np.ones(5))[1] == 0.0, "常数场标准差应为 0"

    # 2) 总压损失系数：无损失为 0，全损失为 1
    assert abs(total_pressure_loss_coefficient(100.0, 100.0, 90.0)) < 1e-12
    assert abs(total_pressure_loss_coefficient(100.0, 90.0, 90.0) - 1.0) < 1e-12
    # 第 17 讲论文 09 的 -14.0%：损失系数下降 14% 是"相对变化"口径
    w_ref, w_new = 0.0500, 0.0500 * 0.86
    assert abs(relative_change(w_new, w_ref) + 14.0) < 1e-9, "相对变化口径错误"

    # 3) 静压系数
    assert abs(static_pressure_coefficient(101325.0, 100000.0, 5000.0) - 0.265) < 1e-3

    # 4) 气膜有效度：上下界与中点
    Tinf, Tc = 1500.0, 600.0
    assert abs(adiabatic_film_effectiveness(Tinf, Tinf, Tc)) < 1e-12, "无气膜时应为 0"
    assert abs(adiabatic_film_effectiveness(Tinf, Tc, Tc) - 1.0) < 1e-12, "完美气膜时应为 1"
    assert abs(adiabatic_film_effectiveness(Tinf, 1050.0, Tc) - 0.5) < 1e-12
    # 综合冷却效率用真实壁温：内部冷却把壁温压到 900K → φ=0.667
    assert abs(overall_cooling_effectiveness(Tinf, 900.0, Tc) - 2.0 / 3.0) < 1e-12
    # 同一壁温下，φ 一定 ≥ η_aw（绝热壁温不低于真实壁温）
    assert overall_cooling_effectiveness(Tinf, 900.0, Tc) >= \
        adiabatic_film_effectiveness(Tinf, 1000.0, Tc)

    # 5) Nu 与 h 互为逆运算
    h, L, k = 850.0, 0.02, 0.06
    nu = nusselt_number(h, L, k)
    assert abs(nu - 283.3333333) < 1e-4, f"Nu 计算错误：{nu}"
    assert abs(heat_transfer_coefficient(nu, L, k) - h) < 1e-9, "h 反算不一致"

    # 6) 等熵效率：用一组自洽的数据，η 必须落在 (0,1)
    # 自洽算例：p_t 1000→550 kPa、T_t,in = 1600 K、γ=1.33 时等熵温降约 124 K，
    # 取实际温降 200 K（对应出口总温 1400 K）→ η ≈ 0.90
    eta = isentropic_efficiency(1000.0, 550.0, 1600.0, 1400.0, gamma=1.33)
    assert 0.0 < eta < 1.0, f"等熵效率超出 (0,1)：{eta}"
    # 等熵过程（实际温降 = 理想温降）时效率应为 1
    Tout_ideal = 1600.0 * (550.0 / 1000.0) ** ((1.33 - 1.0) / 1.33)
    assert abs(isentropic_efficiency(1000.0, 550.0, 1600.0, Tout_ideal, 1.33) - 1.0) < 1e-9
    # 压气机
    eta_c = compressor_efficiency(100.0, 300.0, 288.0, 480.0, 1.4)
    assert 0.0 < eta_c < 1.0, f"压气机效率超出 (0,1)：{eta_c}"

    # 7) 百分点 vs 相对变化（第 18 讲论文 10 的 +0.42% 是"效率增量"，属百分点口径）
    assert abs(percentage_point_change(91.62, 91.20) - 0.42) < 1e-9
    assert abs(relative_change(91.62, 91.20) - 0.4605) < 1e-3

    # 8) 不确定度区间与 describe
    lo_b, hi_b = deviation_band(0.35, 0.05, k=2.0)
    assert abs(lo_b - 0.25) < 1e-12 and abs(hi_b - 0.45) < 1e-12
    x = rng.normal(10.0, 2.0, size=5000)
    s = describe(x)
    assert s["n"] == 5000 and abs(s["mean"] - 10.0) < 0.2 and abs(s["std"] - 2.0) < 0.2
    assert s["min"] <= s["p05"] <= s["p95"] <= s["max"]
    sw = describe(x, weights=np.ones_like(x))
    assert abs(sw["mean"] - s["mean"]) < 1e-9, "等权重的加权均值应等于算术均值"

    # 9) 异常输入
    for bad in [lambda: area_average(np.ones(3), np.ones(4)),
                lambda: area_average(np.ones(3), np.zeros(3)),
                lambda: total_pressure_loss_coefficient(100.0, 90.0, 100.0),
                lambda: adiabatic_film_effectiveness(600.0, 800.0, 600.0),
                lambda: isentropic_efficiency(550.0, 1000.0, 1600.0, 1250.0),
                lambda: compressor_efficiency(300.0, 100.0, 288.0, 480.0),
                lambda: relative_change(1.0, 0.0),
                lambda: describe(np.zeros(0))]:
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法输入未报错")

    print(f"[metrics.py] 自检通过：平均/损失系数/气膜有效度/Nu/等熵效率"
          f"(η_t={eta:.4f}, η_c={eta_c:.4f})/变化量口径/统计摘要/异常输入")


if __name__ == "__main__":
    _self_test()

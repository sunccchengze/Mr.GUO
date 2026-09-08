# P1：2 维翼型优化（入门级）

> **难度**：⭐
> **前置知识**：第 01、02 讲
> **预计时间**：3–4 小时
> **目标**：用 CR-EI + Filter-GEI 的思想，在一个 2 维测试函数上做优化，体会"自适应调度"和"多保真分配"的实际效果。

---

## 1. 项目目标

用 `code/optimizer.py` 和 `code/multifidelity.py` 中的函数，完成以下实验：

1. 在 2 维 Branin 函数上，对比 **随机搜索** vs **EGO** vs **CR-EI** 的收敛速度
2. 观察 CR-EI 的三种调度模式（EI / EI+REI / CEI+REI）各自被触发了几次
3. 思考：如果把维度从 2 提高到 10，结果会怎样变化？

## 2. 验收标准

| 标准 | 说明 |
|:---|:---|
| 代码能运行 | `python your_projects/P1/main.py` 不报错 |
| 有对比结果 | 三种方法的最优值收敛曲线图（或表格） |
| 有分析 | 你能回答"CR-EI 比 EGO 好在哪？在什么情况下不好？" |
| 有报告 | `your_projects/P1/report.md`，用 [项目报告模板](../../templates/project_report_template.md) |

## 3. 分步教程

### Step 1：环境准备（10 分钟）

```bash
# 确认 code/optimizer.py 能正常运行
cd /home/user/Mr.GUO
python code/optimizer.py
```

如果看到 `[optimizer.py] 自检通过`，说明环境没问题。

### Step 2：写优化脚本（30 分钟）

创建 `your_projects/P1/main.py`：

```python
"""P1：2 维翼型优化实验"""
import sys
sys.path.insert(0, "/home/user/Mr.GUO/code")

from optimizer import (
    differential_evolution, ego, cr_ei_step, expected_improvement
)
import numpy as np

# 目标函数：2 维 Branin（全局最优 ≈ 0.397887）
def branin(x):
    x1, x2 = x[0], x[1]
    a, b, c, r, s, t = 1.0, 5.1/(4*np.pi**2), 5/np.pi, 6.0, 10.0, 1/(8*np.pi)
    return a*(x2 - b*x1**2 + c*x1 - r)**2 + s*(1-t)*np.cos(x1) + s

bounds = [(-5.0, 10.0), (0.0, 15.0)]

# 方法 1：随机搜索（基线）
rng = np.random.default_rng(42)
rand_results = []
for _ in range(100):
    X = np.array([rng.uniform(b[0], b[1]) for b in bounds])
    rand_results.append(branin(X))
rand_best = min(rand_results)
print(f"随机搜索（100次）最优值: {rand_best:.4f}")

# 方法 2：DE（进化算法）
x_de, f_de = differential_evolution(branin, bounds, pop_size=20, max_nfe=100, seed=42)
print(f"DE（100次评估）最优值: {f_de:.4f}")

# 方法 3：EGO（贝叶斯优化）
# 注意：需要一个代理模型。用 optimizer.py 内置的 _DemoSurrogate
from optimizer import _DemoSurrogate
x_ego, f_ego, hist_ego = ego(branin, bounds, _DemoSurrogate, 
                              n_init=10, n_iter=20, n_candidates=500, 
                              seed=42, return_history=True)
print(f"EGO（30次迭代）最优值: {f_ego:.4f}")

# 输出对比
print("\n=== 对比结果 ===")
print(f"随机搜索: {rand_best:.4f}")
print(f"DE:       {f_de:.4f}")
print(f"EGO:      {f_ego:.4f}")
```

### Step 3：运行并观察（30 分钟）

```bash
mkdir -p your_projects/P1
python your_projects/P1/main.py
```

**观察点：**
- EGO 是否比随机搜索好？
- DE 和 EGO 哪个更好？为什么？（提示：评估次数相同吗？）

### Step 4：加入 CR-EI 调度观察（1 小时）

在 `main.py` 中加入 CR-EI 的调度模式观察：

```python
# 观察 CR-EI 的调度模式
# 用一个简化的模拟：假设我们有一些候选点的代理预测
rng = np.random.default_rng(42)
n_candidates = 50
X_cand = rng.random((n_candidates, 2)) * [15, 15] + [-5, 0]
mean = rng.normal(0, 1, n_candidates)
sd = rng.uniform(0.1, 2.0, n_candidates)
y = rng.normal(0, 1, n_candidates)
x_pbs = np.array([0.0, 0.0])

# 模拟 10 轮 CR-EI 调度
print("\n=== CR-EI 调度模式观察 ===")
for round_num in range(10):
    n_breakthrough = rng.integers(0, 3)  # 随机模拟突破计数
    result = cr_ei_step(mean, sd, X_cand, y, x_pbs, 
                        d_T=3.0, beta=0.1, n_breakthrough=n_breakthrough)
    print(f"轮 {round_num+1}: 模式={result['mode']}, 建议点数={len(result['indices'])}")
```

### Step 5：写报告（30 分钟）

用 [项目报告模板](../../templates/project_report_template.md) 写 `your_projects/P1/report.md`。

**必须回答的问题：**
1. 三种方法的最优值分别是多少？
2. CR-EI 的三种调度模式分别在什么情况下触发？
3. 如果把维度从 2 提高到 10，你预期结果会怎样变化？为什么？

## 4. 常见问题

| 问题 | 解决方案 |
|:---|:---|
| `ModuleNotFoundError: No module named 'optimizer'` | 确认 `sys.path.insert(0, "/home/user/Mr.GUO/code")` |
| EGO 结果不稳定 | 多跑几次取平均，或增加 `n_candidates` |
| 不知道怎么画收敛曲线 | 用 `matplotlib`，或直接看 `hist_ego` 数组 |

## 5. 进阶挑战

完成后如果还有时间：
- 把 Branin 换成 6 维 Hartman 函数，观察 EGO 性能是否下降
- 对比 EGO 和 DE 在不同维度下的表现
- 尝试用 `code/rbf.py` 的 RBF 替代 `_DemoSurrogate`

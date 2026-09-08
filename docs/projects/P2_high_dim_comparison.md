# P2：高维代理对比实验（进阶级）

> **难度**：⭐⭐
> **前置知识**：第 03、04 讲
> **预计时间**：4–6 小时
> **目标**：在 30 维测试函数上对比 GSDE vs DA-EGO 的思想，体会"换队伍"vs"换场地"的取舍。

---

## 1. 项目目标

1. 在 30 维 Ackley 函数上，对比 **DE** vs **代理辅助 DE** 的收敛速度
2. 用 `code/sampling.py` 的敏感性分析，找出最重要的 5 个变量
3. 思考：如果只优化这 5 个最重要的变量（"换场地"思想），结果会怎样？

## 2. 验收标准

| 标准 | 说明 |
|:---|:---|
| 代码能运行 | `python your_projects/P2/main.py` 不报错 |
| 有对比结果 | DE vs 代理辅助 DE 的收敛曲线 |
| 有敏感性分析 | 30 维中最重要的 5 个变量排序 |
| 有分析 | 你能回答"GSDE 和 DA-EGO 的核心区别是什么？" |
| 有报告 | `your_projects/P2/report.md` |

## 3. 分步教程

### Step 1：定义 30 维 Ackley 函数（15 分钟）

```python
"""P2：高维代理对比实验"""
import sys
sys.path.insert(0, "/home/user/Mr.GUO/code")
import numpy as np
from optimizer import differential_evolution, surrogate_assisted_de, _DemoSurrogate
from sampling import sobol_first_order_indices

def ackley(x):
    x = np.asarray(x, float)
    n = len(x)
    return -20*np.exp(-0.2*np.sqrt(np.sum(x**2)/n)) - np.exp(np.sum(np.cos(2*np.pi*x))/n) + 20 + np.e

d = 30
bounds = [(-5.0, 5.0)] * d
```

### Step 2：运行 DE 和代理辅助 DE（1 小时）

```python
# DE（基线）
x_de, f_de, hist_de = differential_evolution(
    ackley, bounds, pop_size=50, max_nfe=500, seed=42, return_history=True)
print(f"DE 最优值: {f_de:.4f}")

# 代理辅助 DE（GSDE 思想）
x_sde, f_sde, hist_sde = surrogate_assisted_de(
    ackley, bounds, _DemoSurrogate, 
    pop_size=30, top_T=5, max_nfe=500, seed=42, return_history=True)
print(f"代理辅助 DE 最优值: {f_sde:.4f}")
```

### Step 3：敏感性分析（30 分钟）

```python
# 用 LHS 采样，做敏感性分析
from sampling import latin_hypercube
X = latin_hypercube(200, d, rng=np.random.default_rng(42))
X_phys = np.array([bounds[j][0] + X[:, j]*(bounds[j][1]-bounds[j][0]) for j in range(d)]).T
y = np.array([ackley(x) for x in X_phys])

# 一阶敏感性
sobol_idx = sobol_first_order_indices(X_phys, y)
top5 = np.argsort(sobol_idx)[-5:][::-1]
print(f"\n最重要的 5 个变量: {top5}")
print(f"它们的敏感性指数: {sobol_idx[top5]}")
```

### Step 4：子空间优化实验（1 小时）

```python
# 只优化最重要的 5 个变量（DA-EGO 思想）
top5_bounds = [bounds[i] for i in top5]

def ackley_sub(x_sub):
    """只优化 5 个变量，其余固定为 0"""
    x_full = np.zeros(d)
    for i, idx in enumerate(top5):
        x_full[idx] = x_sub[i]
    return ackley(x_full)

x_sub, f_sub = differential_evolution(
    ackley_sub, top5_bounds, pop_size=30, max_nfe=200, seed=42)
print(f"\n子空间优化（5维）最优值: {f_sub:.4f}")
```

### Step 5：写报告（30 分钟）

**必须回答的问题：**
1. DE 和代理辅助 DE 在 30 维上的表现差异有多大？
2. 敏感性分析的结果是否符合 Ackley 函数的特性？（提示：Ackley 函数是各向同性的）
3. 子空间优化（5 维）的结果和全空间优化（30 维）相比如何？这说明了什么？

## 4. 进阶挑战

- 把 Ackley 换成一个**非各向同性**的函数（如 Rosenbrock），观察敏感性分析的结果是否更明显
- 尝试用 `code/multifidelity.py` 的 CoKriging 替代 `_DemoSurrogate`
- 思考：在真实叶栅优化中，哪些变量可能是"最重要的"？

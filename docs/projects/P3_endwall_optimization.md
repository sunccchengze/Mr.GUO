# P3：端壁优化全流程（实战级）

> **难度**：⭐⭐⭐
> **前置知识**：第 06–09、16–17 讲
> **预计时间**：8–12 小时
> **目标**：用生成式参数化 + 优化 + SHAP 归因，完成一个端壁设计的端到端流程（简化版）。

---

## 1. 项目目标

本项目是一个**简化版**的端壁优化流程，目的是让你体验从"参数化→优化→归因"的完整链条。由于真实 CFD 成本太高，我们用测试函数代替。

1. 用 `code/rbf.py` 构造一个"伪端壁几何生成器"（把设计变量映射为几何形状）
2. 用 `code/optimizer.py` 做优化
3. 用 `code/sampling.py` 做敏感性归因
4. 写一份完整的项目报告

## 2. 验收标准

| 标准 | 说明 |
|:---|:---|
| 代码能运行 | `python your_projects/P3/main.py` 不报错 |
| 有完整流程 | 参数化→优化→归因三个环节都有 |
| 有分析 | 你能回答"哪些变量对性能影响最大？" |
| 有报告 | `your_projects/P3/report.md` |

## 3. 分步教程

### Step 1：构造简化端壁问题（1 小时）

```python
"""P3：端壁优化全流程（简化版）"""
import sys
sys.path.insert(0, "/home/user/Mr.GUO/code")
import numpy as np
from rbf import RBFInterpolant, cubic_kernel
from sampling import latin_hypercube, sobol_first_order_indices
from optimizer import differential_evolution
from moo import nsga2, pareto_front

# 模拟端壁几何：10 个设计变量 → 端壁高度分布
# 真实情况：VAE-NURBS 把 200+ 控制点压到 9 个潜变量
# 这里简化为 10 个变量 → 50 个端壁高度点
n_vars = 10
n_points = 50  # 端壁上的高度采样点数

def generate_endwall(x):
    """设计变量 → 端壁高度分布（简化模型）"""
    x = np.asarray(x, float)
    # 用 RBF 插值：设计变量控制少数控制点，插值出完整形状
    ctrl_idx = np.linspace(0, 1, n_vars)
    target_idx = np.linspace(0, 1, n_points)
    mdl = RBFInterpolant(kernel=cubic_kernel)
    mdl.fit(ctrl_idx.reshape(-1, 1), x)
    return mdl.predict(target_idx.reshape(-1, 1))

def endwall_performance(x):
    """端壁性能评估（简化模型）
    
    真实情况：CFD 模拟
    这里：用一个数学函数模拟"总压损失"和"气膜效率"
    """
    h = generate_endwall(x)
    # 总压损失：高度变化越剧烈，损失越大（模拟二次流）
    loss = np.sum(np.diff(h)**2) + 0.1*np.sum(h**2)
    # 气膜效率：高度越高，冷却越差（模拟覆盖不足）
    cooling = np.mean(np.maximum(0, h - 0.5)**2)
    return loss, cooling
```

### Step 2：生成样本并做敏感性分析（2 小时）

```python
# 生成 100 个样本
X = latin_hypercube(100, n_vars, rng=np.random.default_rng(42))
X_phys = -1.0 + 2.0 * X  # 映射到 [-1, 1]

# 评估两个目标
losses = []
coolings = []
for x in X_phys:
    l, c = endwall_performance(x)
    losses.append(l)
    coolings.append(c)
losses = np.array(losses)
coolings = np.array(coolings)

# 敏感性分析（对总压损失）
sobol_loss = sobol_first_order_indices(X_phys, losses)
top5_loss = np.argsort(sobol_loss)[-5:][::-1]
print("对总压损失最重要的 5 个变量:")
for i, idx in enumerate(top5_loss):
    print(f"  变量 {idx}: 敏感性 = {sobol_loss[idx]:.4f}")

# 敏感性分析（对气膜效率）
sobol_cool = sobol_first_order_indices(X_phys, coolings)
top5_cool = np.argsort(sobol_cool)[-5:][::-1]
print("\n对气膜效率最重要的 5 个变量:")
for i, idx in enumerate(top5_cool):
    print(f"  变量 {idx}: 敏感性 = {sobol_cool[idx]:.4f}")
```

### Step 3：单目标优化（2 小时）

```python
# 优化总压损失
x_opt_loss, f_opt_loss = differential_evolution(
    lambda x: endwall_performance(x)[0],
    [(-1.0, 1.0)] * n_vars,
    pop_size=30, max_nfe=300, seed=42
)
print(f"\n最小总压损失: {f_opt_loss:.4f}")
print(f"对应气膜效率: {endwall_performance(x_opt_loss)[1]:.4f}")

# 优化气膜效率
x_opt_cool, f_opt_cool = differential_evolution(
    lambda x: endwall_performance(x)[1],
    [(-1.0, 1.0)] * n_vars,
    pop_size=30, max_nfe=300, seed=42
)
print(f"\n最小气膜效率: {f_opt_cool:.4f}")
print(f"对应总压损失: {endwall_performance(x_opt_cool)[0]:.4f}")
```

### Step 4：多目标优化（2 小时）

```python
# NSGA-II 多目标优化
def bi_obj(P):
    P = np.atleast_2d(P)
    results = []
    for x in P:
        l, c = endwall_performance(x)
        results.append([l, c])
    return np.array(results)

X_pareto, F_pareto = nsga2(
    bi_obj, [(-1.0, 1.0)] * n_vars,
    pop_size=50, n_gen=80, seed=42
)
pf_idx = pareto_front(F_pareto)
print(f"\nPareto 前沿上有 {len(pf_idx)} 个解")
print("前 5 个解:")
for i in pf_idx[:5]:
    print(f"  损失={F_pareto[i,0]:.4f}, 冷却={F_pareto[i,1]:.4f}")
```

### Step 5：写报告（1 小时）

用 [项目报告模板](../../templates/project_report_template.md) 写 `your_projects/P3/report.md`。

**必须回答的问题：**
1. 对"总压损失"和"气膜效率"最重要的变量是否相同？这说明了什么？
2. 单目标优化得到的两个解（最小损失 vs 最小冷却）有什么矛盾？
3. Pareto 前沿上的解如何帮助工程师做决策？
4. 如果这是一个真实的端壁优化，你下一步会做什么？

## 4. 进阶挑战

- 尝试用 `code/transfer.py` 的知识迁移：把一组设计变量的优化结果迁移到另一组
- 尝试用 `code/multifidelity.py` 的多保真方法：用"粗网格"（少采样点）做初筛，"细网格"（多采样点）做精修
- 思考：在真实工程中，"总压损失"和"气膜效率"的权衡应该如何处理？

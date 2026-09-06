# 代码库 `code/`

本目录是本白皮书各讲所涉算法的**可运行实现**。旧版白皮书声称拥有"完整代码库"，
实际上 `code/` 一个文件都没有——本目录就是把这个缺口补上。

## 设计约定（请先读这三条）

1. **只依赖 numpy 与标准库**。不引入 scipy / scikit-learn / PyTorch / matplotlib。
   理由是：这套代码要能在任何一台装了 Python + numpy 的机器上直接跑，包括没有
   外网的算力节点。因此超参数搜索、正态 CDF、Cholesky 求解等都在这里手写实现。
2. **模块之间零耦合**：`code/` 下的模块**互不 import**，每个文件都能单独拷走使用。
   需要代理模型的地方一律用**鸭子接口**注入（见下）。
3. **每个模块都自带自检**：`python code/xxx.py` 直接运行即可，会打印自检结论。

### 鸭子接口（代理模型）

需要代理模型的函数（如 `optimizer.ego`、`multifidelity.CoKriging`）接受一个
`surrogate_factory` 工厂函数，返回的对象需满足：

```python
obj = factory()
obj.fit(X, y)                  # X: (n, d) 原始尺度；y: (n,)
obj.predict(Xs) -> (mean, sd)  # 两个数组，形状均为 (m,)
```

`code/gp.py` 的 `Kriging` 完全符合；`code/rbf.py` 的 RBF 只给均值，需要包一层：

```python
class RbfWithSd:
    def __init__(self): self.m = None
    def fit(self, X, y):
        self.m = rbf.fit_rbf(X, y); self.X, self.y = X, y; return self
    def predict(self, Xs):
        return self.m(Xs), np.full(len(np.atleast_2d(Xs)), np.std(self.y))
```

## 模块清单

| 模块 | 内容 | 主要对应论文 |
| :--- | :--- | :--- |
| `sampling.py` | 拉丁超立方（LHS）、均匀随机、尺度变换、粗粒度敏感性排序 | 论文 04（LHS+UQ）、论文 05（均匀设计）、论文 11 |
| `benchmarks.py` | 14 个基准测试函数（含论文 01 的 Camel6/Hartman6/Shekel4/Trid10、论文 06/08 的 Ackley6d 与平移 Rosenbrock6d） | 论文 01/06/07/08/11 |
| `gp.py` | 普通 Kriging（ARD 高斯相关、集中似然、留一诊断）+ EI / GEI + 一阶效应分解 | 论文 01/02/03/04/06/08/17（Kriging/GP 为核心或基础组件；16 仅作对比基线） |
| `rbf.py` | 径向基函数代理（三次 RBF + 线性尾项，GSDE 的选择） | 论文 07 |
| `optimizer.py` | DE（best/1、rand/1；二项/指数交叉）、PSO、EGO、**CR-EI**（CEI/REI 互补分区 + 调度）、GSDE 骨架 | 论文 01、论文 07 |
| `multifidelity.py` | AR1 Co-Kriging、**Filter-GEI 的 ω 与 T 原文公式**、层次聚类去重叠、DBSCAN、EMFS 集成 | 论文 02（Co-Kriging + Filter-GEI）、论文 13（DBSCAN/EMFS，据摘要）、论文 17（co-kriging 基线）、论文 08（多保真迁移） |
| `moo.py` | 非支配排序、拥挤距离、NSGA-II、超体积、IGD、分布均匀性 | 论文 15、论文 16 |
| `metrics.py` | 总压损失系数、气膜有效度、综合冷却效率、Nu、等熵效率、面积/质量平均、变化量口径 | 论文 09/10/04/05/07 |
| `decomposition.py` | 变量交互检测（蒙特卡洛 ANOVA）、P_C/P_S 三类划分、并查集分组、精英点聚合、边界收缩 | 论文 11（DA-EGO） |
| `transfer.py` | MMD² 分布差异、源任务排序、负迁移判定、SW-VAE 加权批次采样、尾缘正则项 L_P、FFD 网格 | 论文 08（SW-VAE / KT-ASO） |

## 运行

```bash
# 单个模块自检
python code/gp.py

# 全部模块自检 + 全部单元测试
python tools/run_checks.py
```

单元测试在 `tests/` 下（标准库 `unittest`，无需 pytest）：

```bash
python tests/test_gp.py
for f in tests/test_*.py; do python "$f"; done
```

## 关于"忠实于原文"的说明

凡是原文**给出了明确公式**的部分（Filter-GEI 的 ω 与 T、SW-VAE 的 L_P、CR-EI 的
调度规则、Co-Kriging 的 AR1 结构等），本代码库按原文实现，并在 docstring 里标注出处。

凡是原文**没有给出细节**的部分（例如论文 13 的 DBSCAN 参数与 EMFS 权重公式、论文 11
的 PCE 灵敏度系数、GSDE 的局部邻域规模），本代码库采用合理的工程替代方案，并**在
docstring 与函数内部注释中明确标注"这是我们的选择，不是论文数值"**。请勿把这些部分
当作论文方法引用。

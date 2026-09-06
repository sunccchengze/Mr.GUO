# 单元测试 `tests/`

标准库 `unittest` 编写，**不需要 pytest**（验证脚本 `tools/verify_all.py` 的 B3 检查
禁止 `code/` 引入重量级依赖，测试侧同样保持"零额外依赖"）。

## 运行

```bash
# 单个测试文件
python tests/test_gp.py

# 全部（等价于 `python -m unittest discover -s tests`，但保持文件级可单独运行）
for f in tests/test_*.py; do python "$f"; done

# 连同 code/ 的模块自检一起跑
python tools/run_checks.py
```

`tests/_path.py` 负责把 `code/` 加入 `sys.path`，因此每个测试文件都可以直接
`import sampling`、`import gp` 等。

## 文件与覆盖

| 测试文件 | 覆盖模块 | 用例数 |
| :--- | :--- | :---: |
| `test_sampling.py` | `code/sampling.py` | 11 |
| `test_benchmarks.py` | `code/benchmarks.py` | 10 |
| `test_gp.py` | `code/gp.py` | 12 |
| `test_rbf.py` | `code/rbf.py` | 9 |
| `test_optimizer.py` | `code/optimizer.py` | 12 |
| `test_moo.py` | `code/moo.py` | 14 |
| `test_metrics.py` | `code/metrics.py` | 15 |
| `test_multifidelity.py` | `code/multifidelity.py` | 18 |
| `test_decomposition_transfer.py` | `code/decomposition.py` + `code/transfer.py` | 28 |
| **合计** | | **129** |

## 测试设计原则

1. **先测理论性质，再测数值表现**。例如 Kriging 先验证"训练点处精确插值"这一
   插值性，再验证测试集 R²；RBF 先验证插值性与线性再生性，再验证预测精度。
2. **论文里出现的数字要能被复算**。例如 `test_benchmarks.py` 明确验证 Trid10 的
   最优值 −d(d+4)(d−1)/6 = **−210**（论文 01 使用的算例）。
3. **口径差异要被钉死**。例如 `test_metrics.py` 同时验证"相对变化"与"百分点"两种
   口径，防止把论文 09 的 −14.0%（相对）与论文 10 的 +0.42%（百分点）混为一谈。
4. **随机性必须可控**：所有测试都显式传入 `seed`，保证结果可复现。

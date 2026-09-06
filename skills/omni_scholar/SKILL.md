# 🔎 omni_scholar：文献检索与核验技能包（真实实现版）

> **Skill ID:** `omni-scholar-core`
> **适用环境:** 任意可执行 Python 的 Agent（Claude Code / Cursor / Codex / 自研 Agent）
> **版本:** v3.0（真实实现；v2.0 及以前为占位壳子，见下方「旧版问题」）
> **依赖:** 仅 Python 标准库（复用 `tools/extract_corpus.py`，不需要额外安装包）

---

## 一、这个技能到底是什么

它是一个**基于本仓库 `corpus/` 语料的文献检索与核验工具**，不是"论文解读生成器"。

遵守与白皮书完全相同的铁律：

> **没有出处的话不输出。**
> 每一条论断都附带 `(语料文件, 字符区间, 原文片段)`，可以直接回溯到
> `corpus/txt/` 里的原文字符。**检索不到就明确说"未检索到"，绝不代以模板套话。**

### 旧版问题（v2.0 及以前）

旧版 `core.py` 每个方法都返回一段写死的漂亮话（例如"从数学收敛性、计算复杂度和隐空间
流形保形性进行审查"），`generate_reproducible_code_blueprint()` 返回一段写死的占位字符串。
它**不读取任何语料、不输出任何可回溯证据**——看着像在深度分析，实际什么都没做。
本版已彻底重写，并移除了"代码蓝图生成"这一能力：**生成没有语料支撑的代码不属于本技能的职责**，
真正可运行的代码在 `code/` 目录下（见 `code/README.md`）。

---

## 二、五项能力

| 能力 | 方法 | 输出 |
| :--- | :--- | :--- |
| ① 元数据与 DOI 核验 | `verify_doi(pid)` | 声明值 / 核验值 / 正文嗅探值三方比对，状态为 `一致` / `冲突` / `未核验` / `仅核验值` |
| ② 四维骨架抽取 | `extract_skeleton(pid)` | 痛点 / 前人失效 / 本文方法 / 量化验证，每维最多 3 条带字符区间的原文证据 |
| ③ 跨文献演进拓扑 | `build_evolution_topology()` | 按真实年份排代、方法关键词共现矩阵（Top 15） |
| ④ 跨文献互证与批评 | `detect_cross_paper_links()` | 在 A 篇正文中命中 B 篇方法名的位置，并判断是否含批评性措辞 |
| ⑤ 事实卡生成 | `generate_fact_card(pid)` | Markdown 事实卡：元数据 + DOI 核验 + 量化断言池 + 四维骨架 |

辅助：`grep(keyword)` 在全部语料中检索关键词，返回带字符位置的命中。

### 与 `tools/extract_corpus.py` 的关系

本技能**直接复用**抽取器的 `normalize` / `DOI_RE` / `mine_numeric_claims` /
`sniff_metadata`，不另写一套正则，避免两处口径漂移。

---

## 三、命令行用法（仓库根目录执行）

```bash
python skills/omni_scholar/core.py --demo              # 端到端演示
python skills/omni_scholar/core.py --verify-doi 06     # 核验单篇 DOI
python skills/omni_scholar/core.py --skeleton 07       # 抽取四维骨架
python skills/omni_scholar/core.py --topology          # 跨文献演进拓扑
python skills/omni_scholar/core.py --links             # 跨文献互证 / 批评关系
python skills/omni_scholar/core.py --fact-card 09      # 生成事实卡
python skills/omni_scholar/core.py --grep "negative transfer"
python skills/omni_scholar/core.py --skeleton 07 --json   # 任意命令可加 --json
```

---

## 四、真实输出节选（`--demo`，2026 年重建后实测）

```
【1】语料概览
  - 论文数：20；编号：01, 02, ..., 20
  - 有全文：13 篇

【2】DOI 核验（逐篇三方比对）
  OK P06 [一致]: 声明=10.1109/TCYB.2022.3165044 | 核验=10.1109/TCYB.2022.3165044 | 正文=...3165044
  ?! P04 [未核验]: 声明=10.1115/1.4051416 | 核验=None | 正文=None
  !! P15 [仅核验值]: 声明=None | 核验=10.1109/CEC65147.2025.11043110 | 正文=...
  → 真正冲突的篇目：无（标 ?! 者为无本地原文、无法核验，不等于错误）

【3】四维骨架抽取示例
**核心痛点与研究动机**：语料中检索到以下直接表述（按出现顺序）：
  - `corpus/txt/P01_s00158-021-03038-3.txt` 字符 [698:800]：
    「However, the EI-based BO can get stuck in sub-optimal solutions even with a large number of samples.」
  - `corpus/txt/P01_s00158-021-03038-3.txt` 字符 [17202:17248]：
    「However, it drops exponentially when z ≤ 0 .」

【4】跨文献演进拓扑
  - 年份分布：{"2021": ["P01","P03"], "2023": ["P06","P07"], "2024": ["P08","P09","P10","P12"],
               "2025": ["P11","P15","P16"], "2026": ["P17","P18","P19"]}
  - 方法共现（前 5 对）：P06 ↔ P08 共享 7 个方法关键词；P06 ↔ P17 共享 7 个；……

【5】跨文献互证 / 批评关系
  - P08 → P06｜引用/互证｜命中「multiform」
      `corpus/txt/P08_1-s2.0-S1270963824001317-main.txt` [59068:59877]
  - P17 → P13｜批评/局限｜命中「EMFS」
      `corpus/txt/P17_1-s2.0-S1270963826007042-main.txt` [21791:22595]
```

> 注意【4】是**统计结果**而非人工归类：年份取 `corpus/index.json` 的 `year_hint`，
> 方法命中取正文正则匹配，未做任何人工判断。

---

## 五、作为 Python 库调用

```python
from skills.omni_scholar.core import OmniScholarEngine

eng = OmniScholarEngine()

# ① DOI 核验
print(eng.verify_doi("18")["status"])          # '一致'

# ② 四维骨架（逐条可回溯）
sk = eng.extract_skeleton("07")
print(sk.validation_and_empirical_gains.render())

# ③ 演进拓扑
topo = eng.build_evolution_topology()
print(topo["timeline_by_year"])

# ④ 在语料里找证据
for hit in eng.grep("negative transfer", limit=5):
    print(hit["paper"], hit["start"], hit["snippet"][:120])
```

---

## 六、使用边界（请务必遵守）

1. **输出是"候选证据"，不是结论。** 骨架抽取靠正则命中句子，可能命中噪声
   （例如表格里的数字行）。引用前请打开对应字符区间人工核对。
2. **无全文的篇目不生成骨架。** 论文 04、05、13、14、20 在本地没有正文，
   `extract_skeleton()` 会直接报错并提示查阅 `corpus/web_evidence/` 与 `corpus/facts/`。
3. **演进拓扑只反映"关键词共现"与"年份顺序"**，不等于真实的引用关系；
   真实的引用关系请用 `--links`（基于方法名在正文中的实际命中）。
4. **不生成代码。** 可运行算法实现在 `code/` 下，且全部通过自检
   （`python tools/run_checks.py`）。

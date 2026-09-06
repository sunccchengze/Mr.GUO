# omni_scholar — 文献核验与抽取技能包

> **一句话**：把"这篇论文到底说了什么、数字有没有出处、DOI 对不对"变成**一条命令可复现**的事。
> 本技能包**不生成任何无语料支撑的内容**：检索不到就明说检索不到。

完整能力说明与约束见 [`SKILL.md`](./SKILL.md)。本 README 只回答三件事：**怎么装、跑什么、跑出来长什么样**。

---

## 一、一次性准备（新克隆的仓库必须做一次）

`corpus/txt/`（论文正文抽取产物）被 `.gitignore` 排除——因为原文 PDF 有版权，不入库。
所有依赖全文的命令都要求先生成它：

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt   # 需要 pypdf
.venv/bin/python tools/extract_corpus.py                                    # 13 PDF + 2 HTML，约 20 秒
```

> **不需要这一步也能跑**的命令：`--verify-doi`、`--topology`、`--fact-card`
> （它们只读已入库的 `corpus/index.json` 与 `corpus/facts/`）。
> 未抽取语料时，全文类命令会打印上面的准备说明并返回退出码 **2**，不会抛 traceback。

## 二、端到端演示（可直接复制）

```bash
python3 skills/omni_scholar/core.py --demo
```

实测输出 106 行，退出码 0。节选：

```
【2】DOI 核验（逐篇三方比对）
  OK P01 [一致]: 声明=10.1007/s00158-021-03038-3 | 核验=10.1007/s00158-021-03038-3 | 正文=None
  ...
  !! P15 [仅核验值]: 声明=None | 核验=10.1109/CEC65147.2025.11043110 | 正文=None
  → 真正冲突的篇目：无（标 ?! 者为无本地原文、无法核验，不等于错误）

【3】四维骨架抽取示例（取一篇正文已抽取的论文）
## 论文 P01 四维骨架（证据等级 A（本地有全文，可逐句回溯））
**核心痛点与研究动机**：语料中检索到以下直接表述（按出现顺序）：
  - `corpus/txt/P01_s00158-021-03038-3.txt` 字符 [698:800]：「However, the EI-based BO can get stuck in
    sub-optimal solutions even with a large number of samples.」
```

**每一条证据都带 `(文件, 字符区间)`**，可直接复核：

```bash
.venv/bin/python - <<'PY'
t=open("corpus/txt/P01_s00158-021-03038-3.txt",encoding="utf-8").read()
print(repr(t[698:800]))   # 应与上面引用的句子逐字一致
PY
```

## 三、命令一览

| 命令 | 是否需要 corpus/txt | 退出码 |
| :--- | :---: | :--- |
| `--demo` | 否（缺则跳过相应小节） | 0 |
| `--verify-doi 06` | 否 | 0 |
| `--topology` | 否 | 0 |
| `--fact-card 09` | 否 | 0 |
| `--skeleton 07` | **是** | 0；缺语料 → 2 |
| `--links` | **是** | 0；缺语料 → 2 |
| `--grep "negative transfer"` | **是** | 0；缺语料 → 2 |

任意命令追加 `--json` 可得到机器可读输出。

## 四、它刻意"不做"的事

1. **不做无出处的摘要转述**——语料里没有的句子，本技能不会生成（旧版正是栽在这里）。
2. **不把"无法核验"当作"错误"**——P13/P14/P20 无本地原文，输出标 `?!`，而非 `!!`。
3. **不覆盖人工事实卡**——`corpus/facts/` 中不含 `TODO` 的文件视为人工成果，生成器一律跳过。

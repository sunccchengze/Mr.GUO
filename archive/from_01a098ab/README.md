# 从分支 `arena/01a098ab-mr-guo` 吸收的材料（第零章 B 方案）

> **吸收日期：** 2026-09-17
> **来源 tip：** `eaf1116`（*验收跑绿 44/44 + 分篇 PDF 重建（含第零章 B 与全部可读性修复）*）
> **合并方式：** `git merge -s ours`（历史经 merge 父永久可达，正文树不受扰动）
> **原则：** 该分支与主链同期解决了**同一个问题**（owner 要求模拟大二生通读白皮书）。主链
> 01a09a93 的 T01–T22「先教再用、就地整改」路线最终被采纳（verify 48/48 > 本支 44/44，
> 且急救包直接长在正文里，无需另开一册）。本分支独有的两样东西有长期价值，入档留存：
> **第零章 B 四张补丁卡的成稿**（内容已分散并入 chapter0/bridges，但整册形态是好的教学备份）
> 与**审计器 audit_reader_sim.py + 自动测量数据**（可对任何后续改版复跑）。

---

## 一、分支评估结论

| 本分支独有产物 | 规模 | 处置 | 主链对应物 |
| :--- | :---: | :--- | :--- |
| `docs/chapter0b.md`（第零章 B·四张补丁卡：概率统计/神经网络/叶轮机几何/风洞实验与 UQ） | 359 行 | **入档** | 内容拆并：0.4/0.5 急救包（chapter0，T02/T03）＋ 过桥 A–D 各一节急救包（T04–T07）＋ 附录 G 术语表（T19） |
| `images/CH0B_b1_normal_curve_zh.png` 等 4 图（正态曲线 / 神经网络 / 叶栅几何 / 心智图） | 4 × 约 1.7 MB | **入档**（不入 `images/`，避免 C2 孤儿图红灯） | 其中正态曲线的新版为 `images/ch0_normal_phi_Phi_zh.png`（已入库、被 chapter0 引用） |
| `docs/模拟读者验收_大二基础.md`（人读报告）＋`（自动测量）.md/.json`（机器数据） | 3 件 | **入档** | 同类结论落在 `docs/大二生审读报告与整改清单.md`（T01，已入库） |
| `tools/audit_reader_sim.py`（「大二模拟读者」扫描器：已修/未修课程显式建模，逐讲找第一个读不下去的位置） | 447 行 | **入档** | 思路收编为验收器 R1–R4 可读性守卫（T20，verify 43→48 项）＋ selftest 反身用例 |
| 分篇 PDF 重建（第零章 B 版式） | — | **不取** | 主链 T 系列之后 8 篇 md 全部翻新，PDF 以 `make pdf` 或 `tools/pdf_build/` 重跑为准 |

**不并入正文的理由：** 两套方案若同时装配，白皮书会出现重复急救内容且 `F4`（源/派生一致）
与 `C2`（孤儿图）双双红灯；主链方案已通过 48 项验收与 30 项反身测试，为准绳。

---

## 二、目录映射（原路径 → 档案路径）

| 原路径 | 档案路径 |
| :--- | :--- |
| `docs/chapter0b.md` | `archive/from_01a098ab/docs/chapter0b.md` |
| `docs/模拟读者验收_大二基础.md` | `archive/from_01a098ab/docs/模拟读者验收_大二基础.md` |
| `docs/模拟读者验收_大二基础（自动测量）.md` / `.json` | `archive/from_01a098ab/docs/` 同名 |
| `images/CH0B_*.png` | `archive/from_01a098ab/images/` |
| `tools/audit_reader_sim.py` | `archive/from_01a098ab/tools/audit_reader_sim.py` |

> 档案内 md 中的相对链接（如 `./images/CH0B_*.png`、`tools/audit_reader_sim.py`）保持原样未改，
> 本目录不在验收器 C1 扫描范围（仅扫根 `*.md` 与 `docs/*.md`），故不构成死链。

## 三、复跑方法

脚本按「仓库根/tools/」解析路径，复跑时先临时拷回 `tools/`（**不要**提交，避免 C5/D7 之外的
验收面扩大）：

```bash
cp archive/from_01a098ab/tools/audit_reader_sim.py tools/_tmp_reader_sim.py
python3 tools/_tmp_reader_sim.py        # 对当前 docs/ 重新扫描，输出可读性缺口表
rm tools/_tmp_reader_sim.py
```

## 四、该分支的历史链

`eaf1116` ← `610bcef`（Merge，含当时 main `e9c5764`）← `b8c8ef9`（路线 A 收编）← `d229262` ← `960e805` ← `1946bb8` ← `d560f0f`（检测题二三批）← ……
其中 `b8c8ef9` 及更早提交同时是 01a09a93 主链的祖先，正文已随主链并入 `main`。

# DOI 与元数据核查对照表

> **生成方式：** 由 `tools/extract_corpus.py` 从本地 PDF/HTML **原文第一页**机械抽取 DOI，
> 与仓库文档（README / 全集汇总 / 公开论文整理 / 付费论文五篇整理 / 论文链接整理）中**声称的 DOI** 自动比对，
> 冲突项再经网络检索（Crossref 收录方页面、出版商页面、引用该文的第三方文献）人工裁定。
> **核查日期：** 2026-09-05
> **原则：** 以「原文印刷的 DOI」为一审证据，以「出版商页面」为二审证据；两者冲突时以出版商页面为准并在备注中说明。

## 一、总表

| 编号 | 论文简称 | 文档声称 DOI | 原文实测 DOI | 裁定 | 处置 |
| :---: | :--- | :--- | :--- | :--- | :--- |
| 01 | CR-EI | `10.1007/s00158-021-03038-3` | 同左 | ✅ 一致 | — |
| 02 | Filter-GEI | `10.1007/s00158-021-02931-1` | 同左 | ✅ 一致 | — |
| 03 | NAE-Purge | `10.1016/j.ijheatmasstransfer.2021.121626` | 同左 | ✅ 一致 | — |
| 04 | Slot-UQ | `10.1115/1.4051416` | 无本地原文 | ✅ 外部确认 | 见 `web_evidence/P04.md` |
| 05 | Impingement-Film | `10.1115/1.4050358` | 无本地原文 | ✅ 外部确认 | 见 `web_evidence/P05.md` |
| 06 | GMFoO | `10.1109/TCYB.2022.3168744` | `10.1109/TCYB.2022.3165044` | ❌ **文档错** | 全文替换 |
| 07 | GSDE | `10.1016/j.ast.2023.108675` | 同左 | ✅ 一致 | — |
| 08 | SW-VAE | `10.1016/j.ast.2024.108998` | 同左 | ✅ 一致 | — |
| 09 | NAE-Exp | `10.1016/j.ast.2024.109015` | 同左（HTML meta） | ✅ 一致 | — |
| 10 | FFD-Tip | `10.1016/j.ijheatfluidflow.2024.109644` | 同左（HTML meta） | ✅ 一致 | — |
| 11 | DA-EGO | `10.1080/0305215X.2024.2325651` | 同左 | ✅ 一致 | 但**年份/讲次标注有误**，见下 |
| 12 | SDNO | `10.2139/ssrn.4869789` | 未检出（PDF 无 DOI 行） | ⚠️ 沿用文档 | 标注为 SSRN 预印本 |
| 13 | EMFS / MSFO | `10.1115/1.4064228` | 无本地原文 | ✅ 外部确认 | 见 `web_evidence/P13.md` |
| 14 | GAN-Endwall | 无 | 无本地原文 | ⚠️ 未获 DOI | 见 `web_evidence/P14.md` |
| 15 | AI-PJP | 无（仅写 "IEEE 检索"） | `10.1109/CEC65147.2025.11043110` | ❌ **文档年份错** | IEEE CEC **2025**，非 2024 |
| 16 | TNO | `10.1016/j.cja.2025.103473` | 同左 | ✅ 一致 | — |
| 17 | GTO | `10.1016/j.ast.2026.112324` | 同左 | ✅ 一致 | — |
| 18 | ResUNet-Sim | `10.1016/j.ast.2026.112440` | `10.1016/j.ast.2026.112351` | ❌ **文档 DOI 指向无关论文** | 全文替换 |
| 19 | SHAP-Turbine | `10.1016/j.cja.2026.104374` | 同左 | ✅ 一致 | — |
| 20 | SPIE-AI | 无 | 无本地原文 | ⚠️ 未获 DOI | 见 `web_evidence/P20.md` |

**统计：20 篇中 3 篇存在实质性错误（15%），1 篇待补 DOI，2 篇仅有公开线索。**

## 二、三处硬伤详述

### 硬伤 1｜P06 GMFoO 的 DOI 尾号错误
- 文档写：`10.1109/TCYB.2022.3168744`
- 原文（IEEE TCYB 首页页眉）印：`10.1109/TCYB.2022.3165044`
- 第三方交叉印证：Wiley *Scandinavian Journal of Statistics* 某文参考文献著录为
  `Guo, Z., Liu, H., Ong, Y.-S., Qu, X., Zhang, Y., & Zheng, J. (2023). Generative multiform bayesian optimization. IEEE Transactions on Cybernetics, 53(7), 4347–4360. 10.1109/TCYB.2022.3165044` [1](https://onlinelibrary.wiley.com/doi/10.1111/sjos.12786)
- 完整著录：**IEEE Trans. Cybernetics, 2023, 53(7): 4347–4360**（14 页），IEEE 文献号 9775011 [1](https://ieeexplore.ieee.org/document/9775011/)。

### 硬伤 2｜P18 ResUNet-Sim 的 DOI 指向一篇完全无关的论文
- 文档写：`10.1016/j.ast.2026.112440`
- 实测该 DOI 解析到：*Accelerating Tandem-Airfoil simulations using curriculum-based graph convolutional network for initialization*，
  Aerospace Science and Technology, Vol. 178 Part B, Article 112440，**作者与郭老师团队毫无关系** [1](https://www.sciencedirect.com/science/article/abs/pii/S1270963826008205)。
- 正确条目：*Physics-enhanced performance prediction and intelligent design for wide-operating-range turbine blades*，
  AST Vol. 177 Part B, Article **112351**, 2026 年 10 月，DOI `10.1016/j.ast.2026.112351`，
  作者 Hui Cheng, Liming Song, Yuqing Ouyang, Fei Zeng, Zhendong Guo [1](https://www.sciencedirect.com/science/article/abs/pii/S1270963826007315)。
- **顺带纠正白皮书里的虚构数字**：白皮书 6.1 矩阵称"宽工况马赫数预测精度达 98%"，
  原文摘要给的是：流场平均相对误差 **MRE 1.16%**、总压损失系数 **MAE 0.26%**。

### 硬伤 3｜P15 AI-PJP 的发表年份与会议错误
- README 全景表写 "IEEE Conference **2024**"，白皮书第 14 讲标 `(*IEEE 2024*)`。
- 原文 DOI：`10.1109/CEC65147.2025.11043110` —— 会议号 CEC**65147**/2025，即 **IEEE Congress on Evolutionary Computation (CEC) 2025**。
- ResearchGate 学者主页亦将该文列为 "Conference Paper, **Jun 2025**" [1](https://www.researchgate.net/profile/Zhendong-Guo-3)。

## 三、附带发现：口径与命名不一致（非 DOI 问题，但同属"忽略"）

| 问题 | 现状 | 处置 |
| :--- | :--- | :--- |
| 论文编号三套并行 | README/全集用 01–20；白皮书按主题重排，其"第10讲"实为 16 号 TNO | 统一 01–20 为唯一编号，讲次与之并列标注 |
| 篇数口径混乱 | 同一文档内同时出现"15 篇""20 篇""15+5 篇" | 统一为「本地有原文 15 篇 / 全集 20 篇」 |
| P13 算法命名 | 白皮书第 05 讲标题称"**EMFS 算法**" | 原文：代理模型叫 **EMFS**（ensemble weighted multi-fidelity surrogate），配套优化算法叫 **MSFO**（multi- and single-fidelity surrogate fused optimization）。二者不可混用 |
| P12 SDNO 状态 | 文档标 "SSRN / Elsevier 2024" | 实际为 SSRN 预印本（2024-01），作者序 Wang, Song, Liu, Guo（郭老师为通讯作者） |
| DA-EGO 年份 | 白皮书第 04 讲标 `(*Eng Opt 2025*)`，README 表标 2024 | 以 Taylor & Francis 页面为准：2024 年在线发表 |

## 四、复现方法

```bash
python3 -m venv .venv && .venv/bin/pip install pypdf
.venv/bin/python tools/extract_corpus.py                    # 抽取语料 + 生成 corpus/index.json
.venv/bin/python tools/extract_corpus.py --grep "112351"    # 在语料中定位任意数字的出处
```

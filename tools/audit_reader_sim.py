#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_reader_sim.py —— 「大二模拟读者」可读性审计器
==================================================

模拟读者画像（本次审计设定）
--------------------------
* 身份：工科大二学生，读完秋季/春季学期
* 已修：**高等数学（微积分+多元微分+级数+常微分方程）**、**线性代数（矩阵/行列式/特征值/二次型）**
* 未修：概率论与数理统计、数值分析、最优化方法、偏微分方程、机器学习、
        流体力学、工程热力学、传热学、叶轮机原理、CFD

审计问题
--------
这个人按目录顺序通读《燃气轮机智能设计与前沿算法自学白皮书》，能读懂吗？
把「读不懂」拆成可测量、可定位、可复查的三件事：

1. **超纲概念密度**：每千字出现多少个他课上没学过的专业概念（按 6 大类分）
2. **裸奔首现**：概念第一次出现时，附近 ±240 字内有没有「人话批注」（这就是/定义为/换句话说/符号卡/…）
3. **知识债**：第零章（前置铺垫）到底替他还掉了多少债，哪些债完全没还

产物
----
* stdout：人读的审计摘要
* docs/模拟读者验收_大二基础.md
* docs/模拟读者验收_大二基础.json（机器可读，供回归对比）

用法：python3 tools/audit_reader_sim.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WP = os.path.join(ROOT, "燃气轮机智能设计与前沿算法自学白皮书.md")
OUT_MD = os.path.join(ROOT, "docs", "模拟读者验收_大二基础（自动测量）.md")
OUT_JSON = os.path.join(ROOT, "docs", "模拟读者验收_大二基础（自动测量）.json")

# --------------------------------------------------------------------------
# 一、概念词典：一个大二（仅高数+线代）学生课上学不到的东西
#     { 类别: { 概念名: 正则 } }
# --------------------------------------------------------------------------
PRE = OrderedDict([
    ("P 概率统计与随机", OrderedDict([
        ("数学期望",        r"期望(?!改善)(?!改进)"),
        ("方差",            r"方差(?!分析)"),
        ("标准差",          r"标准差"),
        ("概率分布",        r"概率分布|正态分布|高斯分布|后验分布|先验分布|分布函数|钟形"),
        ("条件概率",        r"条件概率"),
        ("贝叶斯/后验/先验", r"后验|先验|贝叶斯"),
        ("似然",            r"似然"),
        ("协方差",          r"协方差"),
        ("相关系数",        r"相关系数|Pearson"),
        ("中位数/分位数",   r"中位数|分位数|四分位"),
        ("置信区间/置信带", r"置信"),
        ("假设检验/显著性", r"假设检验|显著性|p\s*值"),
        ("蒙特卡洛/采样",   r"蒙特卡[洛罗]|拉丁超方|LHS|随机采样|重采样"),
        ("随机过程",        r"随机过程"),
        ("ANOVA 方差分析",  r"ANOVA|方差分析"),
        ("不确定性量化 UQ", r"不确定性量化|不确定度量化|\bUQ\b"),
        ("概率代理/高斯过程", r"高斯过程|\bGP\b|克里金|Kriging|代理模型"),
    ])),
    ("M 机器学习与深度学习", OrderedDict([
        ("神经网络",        r"神经网络|\bMLP\b|多层感知|图神经网络|全连接层|激活函数|前向传播"),
        ("反向传播",        r"反向传播|梯度回传|链式法则求导"),
        ("损失函数",        r"损失函数|目标函数(?!值)|loss"),
        ("优化器/学习率",   r"学习率|Adam|梯度下降|SGD"),
        ("过拟合/泛化",     r"过拟合|欠拟合|泛化能力|泛化性"),
        ("正则化",          r"正则化|正则项|权重衰减|Dropout"),
        ("训练/验证/测试集", r"训练集|验证集|测试集|训练样本|批大小|batch"),
        ("超参数",          r"超参数"),
        ("自编码器/潜空间", r"自编码器|\bVAE\b|编码器|解码器|潜空间|隐空间|隐变量|潜在变量"),
        ("生成对抗网络",    r"生成对抗|\bGAN\b|判别器|生成器"),
        ("Transformer/注意力", r"Transformer|自注意力|注意力机制|多头|位置编码"),
        ("卷积/池化",       r"卷积|池化|\bCNN\b|ResUNet|U-Net"),
        ("神经算子",        r"神经算子|傅里叶神经算子|\bFNO\b|DeepONet|算子学习"),
        ("迁移/微调",       r"迁移学习|知识迁移|微调|fine-?tune|域适应"),
        ("可解释性 SHAP",   r"SHAP|可解释性|特征归因|归因分析"),
        ("聚类",            r"聚类|DBSCAN|K-?means"),
    ])),
    ("O 最优化与数值方法", OrderedDict([
        ("最优化/寻优",     r"最优化|寻优|优化问题|收敛曲线|收敛速度"),
        ("局部/全局最优",   r"局部最优|全局最优|早熟收敛"),
        ("约束处理",        r"约束条件|罚函数|可行域|约束优化"),
        ("梯度/导数信息",   r"梯度信息|一阶导数|二阶导数|海塞|Hessian"),
        ("无导数优化/进化", r"差分进化|粒子群|遗传算法|进化算法|变异算子|交叉算子|精英"),
        ("多目标/帕累托",   r"多目标|帕累托|Pareto|支配关系|非支配|超体积|\bHV\b|\bIGD\b"),
        ("代理辅助优化",    r"贝叶斯优化|\bEGO\b|采集函数|加点准则|序列采样"),
        ("插值/拟合",        r"插值|径向基|\bRBF\b|响应面|多项式拟合"),
        ("数值离散/CFD求解", r"离散化|网格划分|迭代求解|残差收敛|时间步|湍流模型|壁面函数"),
        ("多保真",          r"多保真|低保真|高保真|变保真|co-?Kriging|尺度因子"),
    ])),
    ("T 数学工具（超纲）", OrderedDict([
        ("偏微分方程",      r"偏微分方程|\bPDE\b|Navier-?Stokes|N-?S 方程|守恒方程"),
        ("雅可比/海塞矩阵", r"雅可比|Jacobian"),
        ("范数/内积/距离",   r"范数|欧氏距离|内积|相似度度量"),
        ("KL 散度/熵",      r"KL 散度|KL\(|相对熵|交叉熵|信息熵"),
        ("变分推断",        r"变分推断|变分下界|ELBO|重参数化技巧"),
        ("傅里叶/谱",       r"傅里叶变换|快速傅里叶|\bFFT\b|谱方法|频域"),
        ("矩阵分解",        r"奇异值分解|\bSVD\b|本征正交分解|\bPOD\b|主成分分析|\bPCA\b|特征值分解"),
        ("流形",            r"流形|降维到|嵌入空间"),
        ("张量",            r"张量"),
        ("蒙特卡洛积分",    r"蒙特卡洛积分|拟蒙特卡洛|QMC"),
        ("梯度反演/可微",   r"梯度反演|可微渲染|可微求解"),
    ])),
    ("F 流体力学与叶轮机", OrderedDict([
        ("雷诺数",          r"雷诺数|Re\s*=|Reynolds"),
        ("马赫数",          r"马赫数|Ma\s*=|Mach|MA\s*="),
        ("总压/静压",       r"总压|静压|总温"),
        ("总压损失系数",    r"总压损失|损失系数|损失降低"),
        ("熵/等熵",         r"等熵|熵增|熵产"),
        ("边界层/分离",     r"边界层|流动分离|分离泡|转捩"),
        ("二次流/涡系",     r"二次流|通道涡|马蹄涡|泄漏涡|角涡|涡系|涡量"),
        ("激波/跨声速",     r"激波|跨声速|超声速|亚声速"),
        ("湍流/层流",       r"湍流|层流|涡粘|大涡模拟|\bLES\b|\bRANS\b|\bDNS\b"),
        ("无量纲化/相似",   r"无量纲|相似原理|相似准则|流动相似"),
        ("叶栅/端壁/轮缘",  r"叶栅|端壁|轮缘|叶尖间隙|叶片排|级\b|静子|转子"),
        ("叶型气动术语",    r"反动度|攻角|落后角|安装角|稠度|展弦比|中弧线|前缘|尾缘|子午面|栅距|叶型"),
        ("气动热/冷却",     r"气膜冷却|冲击冷却|冷却效率|努塞尔数|\bNu\b|换热系数|热流密度|绝热|吹风比"),
        ("流固耦合",        r"流固耦合|\bFSI\b|颤振|气动弹性"),
        ("非轴对称端壁",    r"非轴对称|端壁造型|\bNAE\b"),
        ("参数化/FFD",      r"自由变形|\bFFD\b|NURBS|贝塞尔|控制体网格"),
    ])),
    ("E 实验与工程测量", OrderedDict([
        ("风洞实验",        r"风洞|试验台|实验台|叶栅试验"),
        ("测量技术",        r"压力敏感漆|\bPSP\b|纹影|热线|五孔探针|\bPIV\b|热电偶"),
        ("误差/不确定度评定", r"测量误差|系统误差|随机误差|不确定度评定|误差棒"),
        ("标定/校准",       r"标定|校准曲线|重复性"),
    ])),
])

# 高数 + 线代 的「已知地基」：用来判断书中是否借用了他能懂的脚手架
BASE = OrderedDict([
    ("导数/偏导", r"偏导|偏导数|导数"),
    ("梯度",      r"梯度"),
    ("泰勒展开",  r"泰勒"),
    ("积分",      r"积分"),
    ("矩阵/向量", r"矩阵|向量|线性变换"),
    ("特征值",    r"特征值|特征向量|二次型"),
    ("极值/驻点", r"极值|驻点|最值"),
    ("级数",      r"级数|收敛半径"),
])

# 「人话批注」标记：概念首次出现处附近若命中，视为有脚手架
SCAFFOLD = [
    r"就是", r"指的是", r"定义为", r"所谓", r"意思是", r"换句话说", r"也?就是?说",
    r"符号卡", r"人话", r"比喻", r"假设你", r"可以想成", r"可以理解", r"记作",
    r"称为", r"叫作", r"叫做", r"相当于", r"类比", r"想象", r"把它当", r"请先当",
    r"先混个眼熟", r"不必先", r"可跳过", r"先不用管", r"回译", r"指读", r"先只记住",
]
SCAFFOLD_RE = re.compile("|".join(SCAFFOLD))

WINDOW = 240  # 首次出现处前后各取多少字做「有没有脚手架」判断


# --------------------------------------------------------------------------
# 二、切分白皮书
# --------------------------------------------------------------------------
def split_sections(text: str) -> "OrderedDict[str, str]":
    """按 第零章 / 第NN讲 / 过桥 / 第六篇 / 代码篇 / 附录 切块。"""
    marks = [(0, "前言与导读")]
    for m in re.finditer(r"^# 第零章.*$", text, re.M):
        name = "第零章B · 补丁包" if re.match(r"^# 第零章\s*B\b", m.group(0)) else "第零章"
        marks.append((m.start(), name))
    for m in re.finditer(r"^### 【第(\d+)讲】", text, re.M):
        marks.append((m.start(), "第%s讲" % m.group(1)))
    for m in re.finditer(r"^## 过桥\s*([A-D])", text, re.M):
        marks.append((m.start(), "过桥%s" % m.group(1)))
    for m in re.finditer(r"^# 第五篇.*$", text, re.M):
        marks.append((m.start(), "第五篇·代码"))
    for m in re.finditer(r"^# 第六篇.*$", text, re.M):
        marks.append((m.start(), "第六篇·对比批判"))
    for m in re.finditer(r"^# 附录.*$", text, re.M):
        marks.append((m.start(), "附录"))
    marks = sorted(set(marks), key=lambda t: t[0])

    secs = OrderedDict()
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        secs[name] = text[pos:end]
    return secs


def cjk_count(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def formula_count(s: str) -> int:
    """〔式〕核心式 + 独立公式块 + 行内 $...$ """
    n = len(re.findall(r"〔式〕", s))
    n += len(re.findall(r"^\s*\$\$.*?\$\$\s*$", s, re.M | re.S))
    n += len(re.findall(r"(?<!\$)\$(?!\$)[^$\n]{2,}\$(?!\$)", s))
    return n


def deep_box_ratio(s: str) -> float:
    """深潜（可跳过）框里的中文字占比。"""
    lines = s.split("\n")
    total = cjk_count(s)
    box = 0
    in_box = False
    for ln in lines:
        if re.match(r"^\s*>\s*【深潜", ln):
            in_box = True
        elif in_box and not ln.strip().startswith(">"):
            in_box = False
        if in_box:
            box += cjk_count(ln)
    return (box / total) if total else 0.0


def scaffold_metrics(s: str):
    """（回译数, 模板回译数, 深潜框数, 配图数）"""
    n_huiyi = len(re.findall(r"\*\*回译[:：]", s))
    n_tpl = len(re.findall(r"上式是主路径构件", s))
    # 只数「真正起一个框」的深潜标记（行首为 > 【深潜），不数正文里对它的引用
    n_box = len(re.findall(r"^\s*>\s*【深潜", s, re.M))
    n_img = len(re.findall(r"!\[", s))
    return n_huiyi, n_tpl, n_box, n_img


def para_stats(s: str):
    paras = [p for p in re.split(r"\n\s*\n", s) if cjk_count(p) >= 20]
    if not paras:
        return 0, 0
    lengths = [cjk_count(p) for p in paras]
    return len(paras), sum(lengths) / len(lengths)


# --------------------------------------------------------------------------
# 三、主审计
# --------------------------------------------------------------------------
def main() -> int:
    if not os.path.exists(WP):
        print("找不到白皮书：%s" % WP, file=sys.stderr)
        return 2
    text = open(WP, encoding="utf-8").read()
    secs = split_sections(text)

    # 正文讲次（不含代码篇/附录/前言）
    lect_names = [k for k in secs if re.fullmatch(r"第\d{2}讲", k)]
    read_order = ["第零章", "第零章B · 补丁包"] + lect_names  # 通读顺序

    # 全局首现位置（按通读顺序累积）
    all_terms = [(cat, name, pat) for cat, d in PRE.items() for name, pat in d.items()]
    first_seen = {}          # (cat,name) -> 章节名
    first_ctx = {}           # (cat,name) -> 首次出现的上下文片段
    per_sec_hits = {}        # 章节 -> {术语: 次数}
    per_sec_naked = {}       # 章节 -> [裸奔术语]

    for sec in read_order:
        body = secs.get(sec, "")
        hits = {}
        for cat, name, pat in all_terms:
            n = len(re.findall(pat, body))
            if n:
                hits[(cat, name)] = n
                key = (cat, name)
                if key not in first_seen:
                    first_seen[key] = sec
                    m = re.search(pat, body)
                    a = max(0, m.start() - WINDOW)
                    b = min(len(body), m.end() + WINDOW)
                    first_ctx[key] = re.sub(r"\s+", " ", body[a:b]).strip()
        per_sec_hits[sec] = hits

    # 裸奔首现判断
    for key, sec in first_seen.items():
        ctx = first_ctx[key]
        if not SCAFFOLD_RE.search(ctx):
            per_sec_naked.setdefault(sec, []).append(key)

    # 第零章还债情况
    ch0 = secs.get("第零章", "")
    ch0_covered = {k for k, v in first_seen.items() if v == "第零章"}
    ch0_terms = {k for k in first_seen if len(re.findall(dict(((a, b), c) for a, b, c in
                 [(cat, name, pat) for cat, d in PRE.items() for name, pat in d.items()])[k], ch0))}

    # 逐讲指标
    rows = []
    for sec in read_order:
        body = secs.get(sec, "")
        cjk = cjk_count(body)
        hits = per_sec_hits.get(sec, {})
        n_types = len(hits)
        n_occ = sum(hits.values())
        naked = per_sec_naked.get(sec, [])
        npara, avgpara = para_stats(body)
        q = len(re.findall(r"[？?]", body))
        base_hits = {k: len(re.findall(p, body)) for k, p in BASE.items()}
        hy, tpl, box, img = scaffold_metrics(body)
        rows.append(OrderedDict([
            ("章节", sec),
            ("中文字数", cjk),
            ("超纲概念种数", n_types),
            ("超纲概念出现次数", n_occ),
            ("每千字概念种数", round(n_types / (cjk / 1000), 2) if cjk else 0),
            ("每千字概念次数", round(n_occ / (cjk / 1000), 2) if cjk else 0),
            ("首次出现且无脚手架", len(naked)),
            ("裸奔概念", "、".join(n for _, n in naked)),
            ("公式条数", formula_count(body)),
            ("每千字公式", round(formula_count(body) / (cjk / 1000), 2) if cjk else 0),
            ("深潜框占比", round(deep_box_ratio(body), 3)),
            ("段落数", npara),
            ("平均段长(字)", round(avgpara, 1)),
            ("问号数", q),
            ("高数线代脚手架命中", sum(base_hits.values())),
            ("回译条数", hy), ("其中模板回译", tpl), ("深潜框", box), ("配图", img),
        ]))

    # 全文（正文部分）
    body_all = "".join(secs.get(s, "") for s in read_order)
    cjk_all = cjk_count(body_all)

    # 概念总表：首现章节 + 是否有脚手架 + 后续出现总次数
    term_rows = []
    for (cat, name), sec in first_seen.items():
        pat = dict(((a, b), c) for a, b, c in
                   [(c2, n2, p2) for c2, d in PRE.items() for n2, p2 in d.items()])[(cat, name)]
        total = len(re.findall(pat, body_all))
        term_rows.append(OrderedDict([
            ("类别", cat), ("概念", name), ("首现章节", sec),
            ("有脚手架", "否" if (cat, name) in
             {k for s, lst in per_sec_naked.items() for k in lst} else "是"),
            ("全书出现次数", total),
        ]))
    term_rows.sort(key=lambda r: (-r["全书出现次数"], r["首现章节"]))

    # ---------------- 报告 ----------------
    naked_total = sum(len(v) for v in per_sec_naked.values())
    first_lect_naked = per_sec_naked.get("第01讲", [])
    ch0_naked = per_sec_naked.get("第零章", [])
    lect_only = [r for r in rows if r["章节"] != "第零章"]
    avg_density = sum(r["每千字概念次数"] for r in lect_only) / max(1, len(lect_only))
    max_row = max(lect_only, key=lambda r: r["每千字概念次数"])

    md = []
    md.append("# 模拟读者验收：一个只学过「高数 + 线代」的大二学生，通读白皮书会怎样\n")
    md.append("> 生成脚本：`tools/audit_reader_sim.py`（可复跑，数值随白皮书自动更新）  ")
    md.append("> 审计对象：`燃气轮机智能设计与前沿算法自学白皮书.md`  ")
    md.append("> 模拟读者画像：工科大二，已修 **高等数学**、**线性代数**；未修 概率统计 / 数值分析 / 最优化 / 偏微分方程 / 机器学习 / 流体力学 / 工程热力学 / 传热学 / 叶轮机原理 / CFD\n")
    md.append("---\n")
    md.append("## 一、一句话结论\n")
    verdict = ("**读不完，但第 01 讲能读进去。**" if avg_density < 60 else
               "**读不动。**")
    md.append("先给结论，再给证据：%s\n" % verdict)
    md.append("| 指标 | 数值 | 读法 |\n| :--- | ---: | :--- |")
    md.append("| 正文（第零章+20 讲）中文字数 | %d | 约合 %.1f 本中文小册子 |" % (cjk_all, cjk_all / 80000))
    md.append("| 超纲概念（课上没学过的）种数 | %d | 全书要他边读边认的生词 |" % len(first_seen))
    md.append("| 首次出现且附近无「人话批注」的概念 | %d | **裸奔首现**，读者的第一个坑 |" % naked_total)
    md.append("| 第零章引入的超纲概念种数 | %d | 第零章替他还掉的债 |" % len(ch0_covered))
    md.append("| 第零章裸奔概念 | %d | 连前置章都在裸奔 |" % len(ch0_naked))
    md.append("| 第01讲裸奔概念 | %d（%s） | 进门第一讲就踩坑 |" % (
        len(first_lect_naked), "、".join(n for _, n in first_lect_naked) or "无"))
    md.append("| 20 讲平均概念密度 | %.1f 次/千字 | 每千字撞上 %.0f 个陌生词 |" % (avg_density, avg_density))
    md.append("| 密度最高讲次 | %s（%.1f 次/千字） | 最劝退的一讲 |" % (max_row["章节"], max_row["每千字概念次数"]))
    n_tpl = sum(r["其中模板回译"] for r in rows)
    n_hy = sum(r["回译条数"] for r in rows)
    n_box = sum(r["深潜框"] for r in rows)
    md.append("| 全书「回译」条数 / 其中模板套话 | %d / %d | 宣称的翻译机制 %.0f%% 是空转 |" % (
        n_hy, n_tpl, 100.0 * n_tpl / max(1, n_hy)))
    md.append("| 全书「深潜（可跳过）」框总数 | %d | 前言承诺的避风港，实际只存在于 %s |" % (
        n_box, "、".join(r["章节"] for r in rows if r["深潜框"] > 0) or "（无）"))
    md.append("")
    md.append("---\n")
    md.append("## 二、逐讲体检表（按通读顺序，裸奔=首次出现且周围没人话批注）\n")
    cols = list(rows[0].keys())
    cols.remove("裸奔概念")
    md.append("| " + " | ".join(cols) + " |")
    md.append("| " + " | ".join(["---:"] * (len(cols) - 1) + [":---"]) + " |")
    for r in rows:
        md.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    md.append("")
    md.append("### 裸奔概念明细（按讲次）\n")
    for sec in read_order:
        lst = per_sec_naked.get(sec, [])
        if lst:
            md.append("- **%s**（%d 个）：%s" % (sec, len(lst), "、".join(n for _, n in lst)))
        else:
            md.append("- **%s**：无（首次出现的概念都带批注）" % sec)
    md.append("")
    md.append("---\n")
    md.append("## 三、知识债清单：他没学过的概念，全书首现在哪、有没有人接住他\n")
    md.append("| 类别 | 概念 | 首现章节 | 首次出现有脚手架 | 全书出现次数 |")
    md.append("| :--- | :--- | :---: | :---: | ---: |")
    for r in term_rows:
        md.append("| %s | %s | %s | %s | %d |" % (r["类别"], r["概念"], r["首现章节"], r["有脚手架"], r["全书出现次数"]))
    md.append("")
    md.append("---\n")
    md.append("## 四、第零章还债审计（前置章到底垫了什么）\n")
    md.append("第零章中文字数：**%d**。它引入并带批注的概念：\n" % cjk_count(ch0))
    if ch0_covered:
        md.append("| 概念 | 首次出现有脚手架 |")
        md.append("| :--- | :---: |")
        for k in sorted(ch0_covered, key=lambda k: k[1]):
            ok = "否" if k in {x for lst in per_sec_naked.values() for x in lst} else "是"
            md.append("| %s | %s |" % (k[1], ok))
    else:
        md.append("（无）")
    md.append("")
    md.append("**没还的债（全书首现落在第 01 讲及以后，且第零章完全没提）**：共 %d 项，见 §三 表格中「首现章节 ≠ 第零章」的行。\n"
              % sum(1 for r in term_rows if r["首现章节"] != "第零章"))
    md.append("---\n")
    md.append("## 五、怎么用这张表\n")
    md.append("1. **裸奔概念**是最高优先级：这是读者第一次见到这个词的地方，没接住就是「读了下句忘上句」的起点。")
    md.append("2. **每千字概念次数 > 45** 的讲次需要拆讲或加缓坡（对照第零章的密度做基准）。")
    md.append("3. 修完再跑一次 `python3 tools/audit_reader_sim.py`，看裸奔数量是否归零——这是可回归的硬指标。")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    open(OUT_MD, "w", encoding="utf-8").write("\n".join(md) + "\n")

    payload = {
        "读者画像": "大二 / 仅高数+线代",
        "正文中文字数": cjk_all,
        "超纲概念种数": len(first_seen),
        "裸奔首现总数": naked_total,
        "第零章引入概念数": len(ch0_covered),
        "第01讲裸奔": [n for _, n in first_lect_naked],
        "平均概念密度_每千字": round(avg_density, 2),
        "逐讲指标": rows,
        "裸奔明细": {s: [n for _, n in lst] for s, lst in per_sec_naked.items()},
        "概念表": term_rows,
    }
    open(OUT_JSON, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2))

    # stdout 摘要
    print("正文（第零章 + 20 讲）中文字数：%d" % cjk_all)
    print("超纲概念种数：%d；裸奔首现：%d" % (len(first_seen), naked_total))
    print("第零章引入概念：%d；第01讲裸奔：%s" % (len(ch0_covered), [n for _, n in first_lect_naked]))
    print("平均概念密度：%.1f 次/千字；最高：%s %.1f" % (avg_density, max_row["章节"], max_row["每千字概念次数"]))
    print("\n逐讲：章节 字数 概念种数 每千字次数 裸奔 公式/千字 深潜占比")
    for r in rows:
        print("  %-10s %6d %4d %8.1f %4d %8.1f %6.2f" % (
            r["章节"], r["中文字数"], r["超纲概念种数"], r["每千字概念次数"],
            r["首次出现且无脚手架"], r["每千字公式"], r["深潜框占比"]))
    print("\n→ 报告：%s" % OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())

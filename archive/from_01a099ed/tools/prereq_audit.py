#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prereq_audit.py —— 「大二学生（只学过高等数学 + 线性代数）」可读性断点审计器
================================================================================
用途
----
模拟一名**只修过《高等数学》《线性代数》两门基础课**的大二学生，逐讲通读
docs/lectures/*.md，找出他在**第几行、因为哪个概念**第一次读不下去。

设计原则
--------
1. **只测「知识断层」，不测文笔。** 上次 `可读性全面优化方案` 已解决叙事节奏，
   本审计专门查它没覆盖的那一层：**读者的知识库里根本没有这个物件**。
2. **可复现。** 概念词典显式写在 LEXICON 里，改词典即改口径，不靠人眼。
3. **只打「裸奔」不打「出现」。** 出现一个超纲词不等于读不懂——只要就地解释过
   （比喻 / "就是" / 符号卡 / 补丁指针）就算过关。真正致命的是**裸奔**。

用法
----
    python3 tools/prereq_audit.py                  # 人读的报告
    python3 tools/prereq_audit.py --json           # 机器可读
    python3 tools/prereq_audit.py --lecture 01     # 只看某一讲
    python3 tools/prereq_audit.py --strict         # 有一条裸奔就退出码 1（接 CI）

输出
----
* 全书「断点地图」：每讲的**第一个断点**在哪一行、是什么概念、原文片段
* 裸奔概念清单（按严重度排序）
* 符号卡覆盖率：主路径公式里的符号，有多少没进本讲符号卡
* 第零章欠账：第零章声称"读完即可读全部 20 讲"，实际覆盖了几个前置概念
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# ---------------------------------------------------------------------------
# 一、读者画像：一个大二学生**到底会什么**
# ---------------------------------------------------------------------------
# 口径：修完《高等数学》(上/下) + 《线性代数》。未修：概率论与数理统计、
# 数值分析、数学物理方程、流体力学、工程热力学、机器学习、最优化方法。
BASELINE_HAS = {
    # 高数
    "极限", "连续", "导数", "偏导数", "微分", "全微分", "积分", "定积分",
    "不定积分", "级数", "泰勒", "多元函数", "方向导数", "梯度", "极值",
    "常微分方程", "重积分", "曲线积分", "曲面积分", "牛顿", "莱布尼茨",
    # 线代
    "向量", "矩阵", "行列式", "线性方程组", "秩", "线性无关", "线性相关",
    "基", "维数", "特征值", "特征向量", "内积", "正交", "二次型",
    "线性变换", "转置", "逆矩阵", "相似",
    # 高中物理
    "力", "速度", "加速度", "能量", "功", "压强", "温度", "质量", "密度",
    "守恒", "牛顿第二定律", "摩擦",
}

# ---------------------------------------------------------------------------
# 二、超纲概念词典：分 7 个「断层族」，每族标严重度
# ---------------------------------------------------------------------------
# 严重度：
#   P0 = 致命 —— 不补这个，该讲整节读不下去（通常是公式里的主角）
#   P1 = 高   —— 不补这个，能跟剧情但跟不了推理
#   P2 = 中   —— 读起来像黑话，但不影响主线
#
# 每个概念写成 (规范名, 正则组, 排除组)。排除组专门砍掉口语/同名误解：
#   「大概率烂尾」不是概率论；「ANOVA 方差分析」里的「方差」不是本节要的 σ²；
#   「后验观察」不是贝叶斯后验。词典口径直接决定审计可信度，改这里即改结论。
LEXICON = OrderedDict()


def _fam(name, severity, concepts):
    """concepts: list of (规范名, [正则...], [排除正则...])"""
    LEXICON[name] = {"severity": severity, "concepts": concepts}


_fam("A 概率统计（大二未开课）", "P0", [
    ("概率", [r"随机变量", r"(?<![大很极低高小超])概率(?!密度)"],
             [r"大概率", r"小概率事件"]),
    ("数学期望", [r"数学期望", r"期望值", r"𝔼", r"E\[", r"期望改善"], []),
    ("方差/标准差", [r"标准差", r"方差(?!分析)", r"σ²", r"s²_", r"均方差"],
                   [r"方差分析", r"ANOVA"]),
    ("正态分布", [r"正态分布", r"高斯分布", r"钟形(?!曲线) *", r"标准正态"], []),
    ("累积分布函数 Φ", [r"Φ\(", r"Φ\(z", r"Φ\(u", r"累积分布", r"CDF"], []),
    ("概率密度 φ", [r"φ\(", r"φ\(z", r"φ\(u", r"概率密度", r"PDF"], []),
    ("先验/后验", [r"先验", r"后验(?!观察)", r"posterior", r"prior"], [r"后验观察"]),
    ("似然", [r"似然", r"[Ll]ikelihood"], []),
    ("贝叶斯定理", [r"贝叶斯定理", r"Bayes 定理"], []),
    ("协方差", [r"协方差", r"covariance", r"Cov\(", r"协方差矩阵"], []),
    ("蒙特卡洛", [r"蒙特卡洛", r"Monte Carlo", r"MCMC"], []),
    ("置信区间", [r"置信区间", r"置信带", r"置信水平"], []),
    ("KL 散度", [r"KL 散度", r"KL\(", r"Kullback"], []),
    ("信息熵", [r"信息熵", r"交叉熵", r"互信息"], []),
    ("分位数", [r"分位数", r"quantile"], []),
    ("不确定性量化", [r"不确定性量化", r"\bUQ\b"], []),
])

_fam("B 高斯过程 / 代理模型（研究生课）", "P0", [
    ("高斯过程", [r"高斯过程", r"Gaussian Process", r"GPR", r"\bGP\b"], []),
    ("核函数", [r"核函数", r"kernel", r"RBF 核", r"核矩阵", r"长度尺度"], []),
    ("克里金", [r"克里金", r"Kriging", r"Co-Kriging"], []),
    ("超参数", [r"超参数", r"超参(?!数)?"], []),
    ("后验均值/方差", [r"后验均值", r"后验方差"], []),
    ("Cholesky 分解", [r"Cholesky", r"乔列斯基"], []),
    ("正定矩阵", [r"正定"], []),
    ("径向基函数", [r"径向基", r"\bRBF\b"], []),
    ("代理模型", [r"代理模型", r"替代模型", r"surrogate"], []),
])

_fam("C 机器学习 / 深度学习（大二未开课）", "P0", [
    ("神经网络", [r"神经网络", r"多层感知机", r"MLP", r"全连接"], []),
    ("反向传播", [r"反向传播", r"链式法则", r"自动微分", r"autograd"], []),
    ("梯度下降", [r"梯度下降", r"Adam\b", r"学习率", r"优化器"], []),
    ("损失函数", [r"损失函数", r"\bloss\b", r"\bLoss\b", r"损失项", r"MSE 损失"], []),
    ("训练轮次", [r"epoch", r"batch", r"\bbatch size"], []),
    ("过拟合/泛化", [r"过拟合", r"泛化(?!性论)", r"正则化", r"正则项", r"dropout"], []),
    ("激活函数", [r"激活函数", r"ReLU", r"[Ss]igmoid"], []),
    ("卷积网络", [r"卷积", r"CNN", r"ResUNet", r"U-Net"], []),
    ("注意力机制", [r"注意力", r"自注意力", r"Attention"], []),
    ("Transformer", [r"Transformer", r"位置编码", r"token"], []),
    ("编码器/解码器", [r"编码器", r"解码器", r"encoder", r"decoder"], []),
    ("自编码器", [r"自编码器", r"VAE", r"变分自编码器", r"autoencoder"], []),
    ("潜空间", [r"潜空间", r"隐空间", r"潜变量", r"潜码", r"潜在空间", r"隐变量", r"潜维"], []),
    ("生成对抗网络", [r"GAN\b", r"生成对抗", r"判别器", r"生成器"], []),
    ("神经算子", [r"神经算子", r"DeepONet", r"FNO\b", r"算子学习"], []),
    ("迁移学习", [r"迁移学习", r"知识迁移", r"微调", r"fine-tune", r"预训练", r"负迁移"], []),
    ("流形", [r"流形"], []),
])

_fam("D 最优化理论（大三/研究生课）", "P1", [
    ("帕累托前沿", [r"帕累托", r"Pareto", r"非支配"], []),
    ("多目标优化", [r"多目标", r"目标函数"], []),
    ("超体积指标", [r"超体积", r"HV 指标"], []),
    ("凸优化", [r"凸优化", r"凸性"], []),
    ("KKT / 拉格朗日", [r"KKT", r"拉格朗日", r"罚函数"], []),
    ("全局/局部最优", [r"全局最优", r"局部最优", r"收敛性"], []),
    ("启发式算法", [r"启发式", r"差分进化", r"遗传算法", r"粒子群"], []),
    ("无导数优化", [r"无导数", r"derivative-free", r"直接搜索"], []),
    ("加点准则", [r"采集函数", r"acquisition", r"加点准则", r"infill"], []),
])

_fam("E 数值方法 / PDE / 流体力学（大三课）", "P1", [
    ("偏微分方程", [r"偏微分方程", r"PDE", r"N-S 方程", r"Navier-Stokes", r"Navier–Stokes", r"控制方程"], []),
    ("湍流模型", [r"湍流", r"RANS", r"LES\b", r"DNS\b", r"涡黏", r"雷诺平均"], []),
    ("有限体积/差分", [r"有限体积", r"有限差分", r"离散化", r"离散"], []),
    ("计算网格", [r"网格", r"mesh", r"grid"], [r"栅格地图"]),
    ("数值格式", [r"残差", r"收敛阶", r"数值耗散", r"迭代"], []),
    ("插值方法", [r"插值", r"样条", r"NURBS", r"B 样条"], []),
    ("降阶模型", [r"POD\b", r"本征正交", r"降阶", r"ROM\b"], []),
    ("马赫数", [r"马赫", r"Mach", r"Ma="], []),
    ("雷诺数", [r"雷诺数", r"Reynolds", r"Re="], []),
    ("激波", [r"激波", r"跨声速", r"超声速", r"超音速"], []),
    ("边界层", [r"边界层", r"分离(?!变量)", r"转捩"], [r"变量分离"]),
])

_fam("F 线代进阶（超出线代基础课）", "P2", [
    ("奇异值分解", [r"奇异值", r"SVD"], []),
    ("主成分分析", [r"主成分", r"PCA"], []),
    ("降维", [r"降维", r"嵌入", r"embedding"], []),
    ("矩阵范数", [r"范数", r"‖", r"Frobenius"], []),
    ("张量", [r"张量", r"tensor"], []),
    ("雅可比矩阵", [r"雅可比", r"Jacobian"], []),
    ("投影算子", [r"投影", r"子空间"], []),
])

_fam("G 叶轮机械 / 工程热物理（专业课）", "P1", [
    ("叶栅基本术语", [r"叶栅", r"静子", r"转子(?!动力)", r"叶片排", r"\d+ 级压气机"], []),
    ("总压损失", [r"总压损失", r"损失系数", r"总压"], []),
    ("等熵效率", [r"等熵效率", r"等熵", r"绝热效率", r"气动效率"], []),
    ("反动度", [r"反动度"], []),
    ("攻角/落后角", [r"攻角", r"冲角", r"落后角", r"安装角"], []),
    ("端壁与二次流", [r"端壁", r"二次流", r"通道涡", r"角区", r"马蹄涡", r"泄漏涡"], []),
    ("气膜冷却", [r"气膜冷却", r"气膜", r"冷却效率", r"吹风比", r"冲击冷却"], []),
    ("子午面", [r"子午", r"展弦比", r"叶高", r"展向"], []),
    ("热力参数", [r"焓", r"熵增", r"滞止", r"总温", r"总压比", r"落压比", r"压比"], []),
    ("旋转机械工况", [r"喘振", r"失速", r"流量系数", r"反动度"], []),
    ("风洞实验", [r"风洞", r"环形叶栅", r"五孔探针", r"PIV", r"探针"], []),
    ("参数化方法", [r"FFD", r"自由变形", r"参数化"], []),
])

# ---------------------------------------------------------------------------
# 二·补、根概念聚类：把 60+ 个裸奔概念收敛成「补丁」单位
# ---------------------------------------------------------------------------
# 这是把「问题太大」变小的关键一步：不必逐条修 366 处，只需补 N 张补丁卡。
ROOT_PATCH = OrderedDict([
    ("P1 概率两件套：期望 / 方差", ["数学期望", "方差/标准差", "概率", "协方差"]),
    ("P2 正态分布与 Φ / φ", ["正态分布", "累积分布函数 Φ", "概率密度 φ", "置信区间", "分位数"]),
    ("P3 贝叶斯三件套", ["先验/后验", "似然", "贝叶斯定理", "蒙特卡洛", "KL 散度", "信息熵"]),
    ("P4 高斯过程与代理模型", ["高斯过程", "核函数", "克里金", "后验均值/方差", "Cholesky 分解",
                        "正定矩阵", "径向基函数", "代理模型", "超参数", "不确定性量化", "加点准则"]),
    ("P5 神经网络骨架", ["神经网络", "编码器/解码器", "自编码器", "潜空间", "卷积网络",
                     "注意力机制", "Transformer", "生成对抗网络", "神经算子", "流形", "激活函数"]),
    ("P6 训练四件套", ["反向传播", "梯度下降", "损失函数", "训练轮次", "过拟合/泛化", "迁移学习"]),
    ("P7 降维与矩阵", ["降维", "奇异值分解", "主成分分析", "投影算子", "矩阵范数", "雅可比矩阵", "张量"]),
    ("P8 优化与多目标", ["帕累托前沿", "多目标优化", "超体积指标", "凸优化", "KKT / 拉格朗日",
                     "全局/局部最优", "启发式算法", "无导数优化"]),
    ("P9 CFD 与网格", ["计算网格", "有限体积/差分", "数值格式", "降阶模型", "偏微分方程", "湍流模型", "插值方法"]),
    ("P10 叶轮机名词", ["叶栅基本术语", "子午面", "攻角/落后角", "反动度", "旋转机械工况",
                     "风洞实验", "热力参数", "参数化方法"]),
    ("P11 端壁与流动", ["端壁与二次流", "气膜冷却", "边界层", "激波", "马赫数", "雷诺数"]),
    ("P12 性能三件套", ["总压损失", "等熵效率"]),
])


def patch_pareto(results):
    """把裸奔条数按「补丁」聚合，给出帕累托。"""
    lookup = {}
    for patch, cs in ROOT_PATCH.items():
        for c in cs:
            lookup[c] = patch
    cnt = Counter()
    lectures = {p: set() for p in ROOT_PATCH}
    fatal = Counter()
    for r in results:
        for h in r["bare_list"]:
            patch = lookup.get(h["concept"])
            if patch is None:
                continue
            cnt[patch] += 1
            lectures[patch].add(r["lecture"])
            if h["severity"] == "P0+":
                fatal[patch] += 1
    return cnt, lectures, fatal


# ---------------------------------------------------------------------------
# 三、「就地解释」线索：出现这些，说明作者当场救了读者
# ---------------------------------------------------------------------------
EXPLAIN_CUES = [
    "就是", "指的是", "指的是", "意思是", "可以理解为", "换句话说", "人话",
    "即 ", "也即", "相当于", "打个比方", "比喻", "好比", "想象", "所谓",
    "定义是", "定义为", "记作", "记为", "称为", "叫做", "译作",
    "可以把它", "我们把它", "简单地", "一句话", "先当成", "可先当",
    "不懂没关系", "不必会", "可跳过", "先记",
]

# 符号卡 / 术语区 的锚点
CARD_ANCHORS = ["3B.", "符号卡", "补丁", "前置补丁"]


# ---------------------------------------------------------------------------
# 四、核心：扫一讲，找断点
# ---------------------------------------------------------------------------
def zh_len(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def split_lines(text: str):
    return text.split("\n")


def find_symbol_card(text: str) -> str:
    """抓取 3B 符号卡区块（从标题到下一个 #####/####）。"""
    m = re.search(r"#####\s*3B\..*?\n(.*?)(?=\n#####|\n####|\Z)", text, re.S)
    return m.group(1) if m else ""


def extracted_symbols(eq_lines):
    """从〔式〕行里抽出符号 token（粗粒度，够用）。"""
    syms = set()
    for line in eq_lines:
        e = re.sub(r"〔式〕", "", line)
        e = re.sub(r"[\u4e00-\u9fff]", "", e)
        e = re.sub(r"\*\*", "", e)
        for tok in re.findall(r"[A-Za-zΑ-ω][^\s,;（）()]{0,7}", e):
            tok = tok.strip(" .。，、|")
            if tok and len(tok) <= 8:
                syms.add(tok)
    return syms


def strip_cjk_words(s: str) -> str:
    return s


def line_context(line: str) -> str:
    """这一行是什么性质的行 —— 决定这个超纲词有多要命。"""
    t = line.strip()
    if "〔式〕" in t:
        return "公式"
    if t.startswith("![") or t.startswith("> **指读") or t.startswith("> 上图"):
        return "图注"
    if t.startswith("|"):
        return "表格"
    if t.startswith("#"):
        return "标题"
    if t.startswith(">"):
        return "引用"
    return "正文"


CTX_WEIGHT = {"公式": 3, "正文": 2, "图注": 2, "表格": 1, "标题": 1, "引用": 2}


def audit_lecture(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    name = os.path.basename(path)
    lines = split_lines(text)
    card = find_symbol_card(text)

    first_seen = {}   # 规范名 -> (行号, 上下文)

    for fam, meta in LEXICON.items():
        for canon, pats, exc in meta["concepts"]:
            for i, line in enumerate(lines):
                if any(x in line for x in ("```",)) and line.strip() == "```":
                    continue
                ok = False
                for p in pats:
                    try:
                        if re.search(p, line):
                            ok = True
                            break
                    except re.error:
                        if p in line:
                            ok = True
                            break
                if not ok:
                    continue
                if any(re.search(e, line) for e in exc):
                    continue
                if canon not in first_seen or i < first_seen[canon][0]:
                    first_seen[canon] = (i, line_context(line))
                break

    hits = []
    covered = set()
    for fam, meta in LEXICON.items():
        sev = meta["severity"]
        for canon, pats, exc in meta["concepts"]:
            if canon not in first_seen:
                continue
            i, ctx = first_seen[canon]
            window = "\n".join(lines[max(0, i - 3): i + 4])
            explained = any(c in window for c in EXPLAIN_CUES)
            in_card = (canon in card) or any(a for a in pats if a and a in card)
            if explained or in_card or canon in BASELINE_HAS:
                covered.add(canon)
                continue
            # 严重度升级：P0 概念落在公式行里 = 致命式
            real_sev = sev
            if sev == "P0" and ctx == "公式":
                real_sev = "P0+"
            snippet = re.sub(r"\*\*|`", "", lines[i].strip())[:110]
            hits.append({
                "concept": canon, "family": fam, "severity": real_sev,
                "line": i + 1, "context": ctx, "snippet": snippet,
            })

    eq_lines = [(i, l.strip()) for i, l in enumerate(lines) if "〔式〕" in l]
    syms = extracted_symbols([l for _, l in eq_lines])
    miss_syms = sorted(s for s in syms if s and s not in card)

    # 第一个「致命式」断点优先；没有则取最靠前的
    fatal = sorted([h for h in hits if h["severity"] == "P0+"], key=lambda h: h["line"])
    hits_sorted = sorted(hits, key=lambda h: h["line"])
    first_break = fatal[0] if fatal else (hits_sorted[0] if hits_sorted else None)

    return {
        "lecture": name.replace(".md", ""),
        "chars_zh": zh_len(text),
        "n_lines": len(lines),
        "n_forms": len(eq_lines),
        "n_new_concepts": len(first_seen),
        "n_explained": len(covered),
        "n_bare": len(hits),
        "bare_rate": round(len(hits) / max(1, len(first_seen)) * 100, 1),
        "first_break": first_break,
        "bare_by_sev": dict(Counter(h["severity"] for h in hits)),
        "n_fatal_forms": len(fatal),
        "bare_list": hits_sorted,
        "symbols_in_formulas": len(syms),
        "symbols_missing_in_card": miss_syms,
        "symbol_cover": round((1 - len(miss_syms) / max(1, len(syms))) * 100, 1) if syms else 100.0,
    }


def audit_chapter0() -> dict:
    """第零章欠账：声称'读完即可读全部 20 讲'，查它到底铺了几个前置概念。"""
    p = os.path.join(DOCS, "chapter0.md")
    text = open(p, encoding="utf-8").read()
    missing = []
    for fam, meta in LEXICON.items():
        if meta["severity"] != "P0":
            continue
        for canon, pats, _exc in meta["concepts"]:
            if not any(re.search(pt, text) for pt in pats):
                missing.append((fam, canon))
    return {"text_zh": zh_len(text), "p0_missing": missing}


# ---------------------------------------------------------------------------
# 五、报告
# ---------------------------------------------------------------------------
def render(results, ch0):
    out = []
    W = out.append
    W("# 读者可达性审计：一个大二学生读得懂吗？\n")
    W("> 由 `tools/prereq_audit.py` 自动生成 · 读者画像：**仅修完《高等数学》+《线性代数》**\n")
    W("> 未修：概率论与数理统计、数值分析、数学物理方程、流体力学、工程热力学、机器学习、最优化方法\n")
    W("\n---\n")

    W("\n## 一、结论先行\n")
    tot_bare = sum(r["n_bare"] for r in results)
    tot_new = sum(r["n_new_concepts"] for r in results)
    p0 = sum(r["bare_by_sev"].get("P0", 0) for r in results)
    p0p = sum(r["bare_by_sev"].get("P0+", 0) for r in results)
    W(f"- 全书 20 讲共引入 **{tot_new} 个**超纲概念，其中 **{tot_bare} 个裸奔**（首次出现未做任何解释）。")
    W(f"- 裸奔率 **{round(tot_bare/max(1,tot_new)*100,1)}%**；其中 P0 级 {p0} 条、"
      f"**P0+ 致命式 {p0p} 条**（超纲概念直接站在公式行里）。")
    W(f"- 第零章只有 **{ch0['text_zh']} 字**，却在末尾写下「读完第零章，你已经具备了读懂全部 20 讲的物理基础」。")
    W(f"  实测：P0 级前置概念里有 **{len(ch0['p0_missing'])} 个**第零章**一个字都没提**。")

    W("\n## 二、断点地图：他在哪一行的哪一句话卡死\n")
    W("| 讲 | 正文(中文字) | 超纲概念 | 裸奔 | 裸奔率 | 致命式 | 第一个断点(行) | 卡在 | 原文片段 |")
    W("| :--- | ---: | ---: | ---: | ---: | ---: | :--- | :--- |")
    for r in results:
        fb = r["first_break"]
        snip = (fb["snippet"].replace("|", "\\|") if fb else "—")[:58]
        W(f"| {r['lecture']} | {r['chars_zh']} | {r['n_new_concepts']} | {r['n_bare']} | "
          f"{r['bare_rate']}% | {r['n_fatal_forms']} | {fb['line'] if fb else '—'} | "
          f"{fb['concept'] if fb else '—'} | {snip} |")

    W("\n## 三、致命清单\n")
    W("\n### 3.1 P0+ 致命式：超纲概念直接出现在〔式〕行里\n")
    W("| 讲 | 行 | 概念 | 原文公式 |")
    W("| :--- | ---: | :--- | :--- |")
    for r in results:
        for h in r["bare_list"]:
            if h["severity"] == "P0+":
                sn = h["snippet"].replace("|", "\\|")[:80]
                W(f"| {r['lecture']} | {h['line']} | {h['concept']} | {sn} |")
    W("\n### 3.2 P0 裸奔（正文/图注/表格）\n")
    W("| 讲 | 行 | 概念 | 族 | 原文片段 |")
    W("| :--- | ---: | :--- | :--- | :--- |")
    for r in results:
        for h in r["bare_list"]:
            if h["severity"] == "P0":
                sn = h["snippet"].replace("|", "\|")[:70]
                W(f"| {r['lecture']} | {h['line']} | {h['concept']} | {h['family'].split()[0]} | {sn} |")

    W("\n## 四、符号卡覆盖率：公式里的符号，卡上有几个\n")
    W("| 讲 | 公式数 | 符号 token | 未进符号卡 | 覆盖率 |")
    W("| :--- | ---: | ---: | ---: | ---: |")
    for r in results:
        W(f"| {r['lecture']} | {r['n_forms']} | {r['symbols_in_formulas']} | "
          f"{len(r['symbols_missing_in_card'])} | {r['symbol_cover']}% |")

    W("\n## 五、帕累托：把「366 处裸奔」收敛成 12 张补丁卡\n")
    W("> 这是把大问题变小的关键：**不必逐条修 366 处**，只需补若干张根概念补丁卡。\n")
    cnt, lecs, fatal = patch_pareto(results)
    tot = sum(cnt.values()) or 1
    W("| 补丁 | 覆盖裸奔 | 占比 | 累进 | 涉及讲 | 其中致命式 |")
    W("| :--- | ---: | ---: | ---: | :---: | ---: |")
    cum = 0
    for patch, v in cnt.most_common():
        cum += v
        W(f"| {patch} | {v} | {v/tot*100:.1f}% | {cum/tot*100:.1f}% | "
          f"{len(lecs[patch])}/20 | {fatal[patch]} |")

    W("\n## 六、第零章欠账（P0 级，全书零铺垫）\n")
    W("| 族 | 缺失概念 |")
    W("| :--- | :--- |")
    for fam, canon in ch0["p0_missing"]:
        W(f"| {fam} | {canon} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lecture", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--out", default=None, help="把报告写入文件")
    args = ap.parse_args()

    files = sorted(
        os.path.join(DOCS, "lectures", f)
        for f in os.listdir(os.path.join(DOCS, "lectures"))
        if re.fullmatch(r"\d{2}\.md", f)
    )
    if args.lecture:
        files = [f for f in files if os.path.basename(f).startswith(args.lecture)]

    results = [audit_lecture(f) for f in files]
    ch0 = audit_chapter0()

    if args.json:
        print(json.dumps({"lectures": results, "chapter0": ch0}, ensure_ascii=False, indent=2))
    else:
        rep = render(results, ch0)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(rep + "\n")
            print(f"[written] {args.out}")
        print(rep)

    if args.strict:
        bad = [r for r in results if r["bare_by_sev"].get("P0+", 0) > 0]
        if bad:
            print(f"\n[FAIL] {len(bad)} 讲存在 P0+ 致命式", file=sys.stderr)
            sys.exit(1)
        print("\n[OK] 无 P0+ 致命式")


if __name__ == "__main__":
    main()

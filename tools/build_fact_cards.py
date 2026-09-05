#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_fact_cards.py —— 由语料自动生成「事实卡」草稿
=============================================================================
输入：corpus/index.json + corpus/txt/*.txt
输出：corpus/facts/PXX.md

生成的事实卡包含：
  1. 权威著录（优先用原文实测值，缺则用文档声称值并标注）
  2. 摘要原文（英文逐字，从 PDF 首页机械截取，不作改写）
  3. 候选量化断言（从全文机械抽取含 %/倍/维数 的句子，供人工逐条裁定）
  4. 待人工填写的骨架小节（机理 / 验证 / 局限 / 承前启后）

设计红线：脚本**绝不生成**任何事实性文字，只做搬运与定位；
         所有需要"判断"的内容一律留空并打上 TODO，防止再次出现编造。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "corpus")
TXT = os.path.join(CORPUS, "txt")
FACTS = os.path.join(CORPUS, "facts")

# 讲次 ↔ 规范编号 对照（白皮书重建版：讲次按主题编排，编号用 01-20 全集口径）
LECTURE_OF = {
    "01": "第01讲", "02": "第02讲", "03": "第03讲", "04": "第05讲",
    "05": "第20讲", "06": "第06讲", "07": "第03讲", "08": "第07讲",
    "09": "第17讲", "10": "第18讲", "11": "第04讲", "12": "第11讲",
    "13": "第05讲", "14": "第09讲", "15": "第14讲", "16": "第10讲",
    "17": "第08讲", "18": "第12讲", "19": "第13讲", "20": "第15讲",
}

SHORT_NAME = {
    "01": "CR-EI", "02": "Filter-GEI", "03": "NAE-Purge", "04": "Slot-UQ",
    "05": "Impingement-Film", "06": "GMFoO", "07": "GSDE", "08": "SW-VAE",
    "09": "NAE-Exp", "10": "FFD-Tip", "11": "DA-EGO", "12": "SDNO",
    "13": "EMFS / MSFO", "14": "GAN-Endwall", "15": "AI-PJP", "16": "TNO",
    "17": "GTO", "18": "ResUNet-Sim", "19": "SHAP-Turbine", "20": "SPIE-AI",
}


def find_abstract(text: str, limit: int = 2200) -> str:
    """从首页文本中机械截取摘要：定位 Abstract 关键词，遇到 Keywords/Introduction 收尾。"""
    for kw in ("A B S T R A C T", "ABSTRACT", "Abstract", "A b s t r a c t", "Abstract—"):
        idx = text.find(kw)
        if idx > 0 and idx < 12000:
            seg = text[idx + len(kw): idx + len(kw) + limit]
            break
    else:
        return ""
    # 截断：摘要之后通常紧跟 Keywords / Nomenclature / 1. Introduction / 版权行
    cuts = []
    for pat in (r"\bKeywords?\b", r"\bKEYWORDS\b", r"\bNomenclature\b",
                r"\b1\.\s*Introduction\b", r"\bIntroduction\b", r"\bIndex Terms\b",
                r"©\s*20\d\d", r"\bArticle history\b"):
        m = re.search(pat, seg)
        if m and m.start() > 300:
            cuts.append(m.start())
    if cuts:
        seg = seg[:min(cuts)]
    seg = seg[:1800]
    # 丢弃尾部被截断的残句
    tail = seg.rfind(". ")
    if tail > 400:
        seg = seg[: tail + 1]
    return re.sub(r"\s+", " ", seg).strip()


CLAIM_PATTERNS = [
    r"[^\n.]{0,150}\b\d+(?:\.\d+)?\s?%[^\n.]{0,150}\.",
    r"[^\n.]{0,150}\b\d+(?:\.\d+)?\s?(?:dimensional|-D|dimensions|variables)\b[^\n.]{0,150}\.",
    r"[^\n.]{0,150}\b(?:reduced|improved|increased|decreased|saving|saved|speedup|faster)\b[^\n.]{0,150}\.",
]


def mine_claims(text: str, per_pattern: int = 12) -> list[str]:
    out: list[str] = []
    for pat in CLAIM_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE | re.DOTALL):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            s = s.lstrip(" .,;:")
            if len(s) < 25 or len(s) > 320:
                continue
            if s not in out:
                out.append(s)
            if len(out) >= per_pattern * len(CLAIM_PATTERNS):
                break
    return out[:40]


def main() -> None:
    os.makedirs(FACTS, exist_ok=True)
    index = json.load(open(os.path.join(CORPUS, "index.json"), encoding="utf-8"))["papers"]

    for p in index:
        pid = p["id"]
        text = ""
        if p.get("txt"):
            text = open(os.path.join(ROOT, p["txt"]), encoding="utf-8").read()

        abstract = find_abstract(text) if text else ""
        claims = mine_claims(text) if text else []
        level = "A（本地原文可查）" if p.get("has_fulltext") else (
            "B（出版商页面/摘要）" if p.get("txt") else "C（仅公开线索）")

        doi = p.get("doi") or p.get("declared_doi") or "未获取"
        doi_note = ""
        if p.get("doi") and p.get("declared_doi") and p["doi"] != p["declared_doi"]:
            doi_note = f"\n> ⚠️ **原文实测 DOI 与旧文档声称值冲突**：旧文档 `{p['declared_doi']}` → 以原文 `{p['doi']}` 为准（详见 `../doi_verification.md`）"
        elif not p.get("doi") and p.get("declared_doi"):
            doi_note = f"\n> ℹ️ 原文未检出 DOI，沿用文档声称值（证据等级低）"

        lines = []
        lines.append(f"# P{pid} · {SHORT_NAME.get(pid, '')}")
        lines.append("")
        lines.append(f"> 规范编号 **{pid}** ｜ 白皮书讲次 **{LECTURE_OF.get(pid, '待定')}** ｜ 证据等级 **{level}**")
        lines.append(f"> 生成时间 {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ｜ 生成器 `tools/build_fact_cards.py`")
        lines.append("")
        lines.append("## 一、权威著录")
        lines.append("")
        lines.append("| 字段 | 值 |")
        lines.append("| :--- | :--- |")
        lines.append(f"| 本地原文 | `{p.get('file') or '无'}` |")
        lines.append(f"| DOI | `{doi}` |")
        lines.append(f"| 原文页数 | {p.get('pages') or '—'} |")
        lines.append(f"| 抽取字符数 | {p.get('chars') or 0} |")
        lines.append(f"| 期刊线索 | {p.get('journal_hint') or 'TODO'} |")
        lines.append(f"| 年份线索 | {p.get('year_hint') or 'TODO'} |")
        lines.append(f"| 卷期页码 | TODO（从原文首页或出版商页面补全） |")
        lines.append(f"| 作者 | TODO（按原文顺序，标注通讯） |")
        if doi_note:
            lines.append(doi_note.strip().replace("\n> ", "\n> "))
        lines.append("")
        lines.append("## 二、摘要原文（English，逐字摘录，未改写）")
        lines.append("")
        lines.append(f"> {abstract if abstract else 'TODO：本地无原文，见 `../web_evidence/P%s.md`' % pid}")
        lines.append("")
        lines.append("**摘要中译**：TODO（人工翻译，须与英文逐句对应）")
        lines.append("")
        lines.append("## 三、关键量化指标（逐条裁定后填入）")
        lines.append("")
        lines.append("| 指标 | 数值 | 原文位置 | 证据等级 | 是否采信 |")
        lines.append("| :--- | :--- | :--- | :---: | :---: |")
        lines.append("| TODO | TODO | §TODO | A/B/C | ⬜ |")
        lines.append("")
        lines.append("## 四、候选量化断言（机器抽取，**待人工逐条裁定**）")
        lines.append("")
        if claims:
            for i, c in enumerate(claims, 1):
                lines.append(f"{i}. {c}")
        else:
            lines.append("（本地无全文，无法抽取）")
        lines.append("")
        lines.append("## 五、方法机理")
        lines.append("")
        lines.append("- **核心痛点**：TODO")
        lines.append("- **传统方法为何失效**：TODO")
        lines.append("- **本文方法的数学表达**：TODO（关键公式，逐步推导）")
        lines.append("- **算法控制流 / 网络架构**：TODO")
        lines.append("")
        lines.append("## 六、验证与基线")
        lines.append("")
        lines.append("- **验证算例 / 实验台**：TODO")
        lines.append("- **对比基线**：TODO")
        lines.append("- **量化结果**：TODO（必须与第三节表格一致）")
        lines.append("")
        lines.append("## 七、局限与可攻击点（供「审稿人批判」小节使用）")
        lines.append("")
        lines.append("- TODO：隐蔽假设、极端工况失效边界、计算开销、数据依赖…")
        lines.append("")
        lines.append("## 八、承前启后")
        lines.append("")
        lines.append("- **继承于**：TODO（编号 + 一句）")
        lines.append("- **启发了**：TODO（编号 + 一句）")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("> 本文件由脚本生成骨架，**第三节及之后的所有判断性内容均需人工依据原文填写**。")
        lines.append("> 填入任何数字前，请先用 `python3 tools/extract_corpus.py --grep \"<数字>\"` 定位原文出处。")

        path = os.path.join(FACTS, f"P{pid}.md")
        open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"[OK] {os.path.relpath(path, ROOT)}  abstract={len(abstract)}  claims={len(claims)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_corpus.py —— Mr.GUO 本地文献语料抽取管线
=============================================================================
用途：把 `郭老师论文/` 下的 13 篇 PDF + 2 篇 ScienceDirect HTML 全文/元数据，
      抽取为可检索的纯文本语料与结构化元数据，作为白皮书重建的唯一事实底座。

设计原则（针对上一版"凭空编造数字"的问题）：
  1. 一切结论必须能追溯到 corpus/txt/ 下的原文字符；
  2. 抽取不到的字段一律写 None，并在校验报告中列出，绝不猜；
  3. 数值型断言（如 1.104%、14.0%）单独抽取为候选证据，供人工逐条核对。

用法：
    python3 tools/extract_corpus.py            # 全量抽取
    python3 tools/extract_corpus.py --grep "126"   # 在语料中检索关键词
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_DIR = os.path.join(ROOT, "郭老师论文")
CORPUS_DIR = os.path.join(ROOT, "corpus")
TXT_DIR = os.path.join(CORPUS_DIR, "txt")

# ---------------------------------------------------------------------------
# 规范论文编号：统一采用 README / 全集汇总「论文全景索引表」的 01~20 编号。
# 注意：白皮书旧版按主题自行重排过编号（其"第10讲"其实是本表的 16 号），
#      这是造成全书口径混乱的根因之一，本表为唯一权威口径。
#
# 字段：(规范编号, 本地文件名, 类型, 文档声称的 DOI 或 None)
# ---------------------------------------------------------------------------
PAPER_MAP = [
    ("01", "s00158-021-03038-3.pdf",                        "pdf",  "10.1007/s00158-021-03038-3"),
    ("02", "s00158-021-02931-1.pdf",                        "pdf",  "10.1007/s00158-021-02931-1"),
    ("03", "1-s2.0-S0017931021007298-main.pdf",             "pdf",  "10.1016/j.ijheatmasstransfer.2021.121626"),
    ("04", None,                                            "none", "10.1115/1.4051416"),
    ("05", None,                                            "none", "10.1115/1.4050358"),
    ("06", "Generative_Multiform_Bayesian_Optimization.pdf", "pdf",  "10.1109/TCYB.2022.3168744"),
    ("07", "1-s2.0-S1270963823005710-main.pdf",             "pdf",  "10.1016/j.ast.2023.108675"),
    ("08", "1-s2.0-S1270963824001317-main.pdf",             "pdf",  "10.1016/j.ast.2024.108998"),
    ("09", "S1270963824001482.htm",                         "html", "10.1016/j.ast.2024.109015"),
    ("10", "S0142727X24003692.htm",                         "html", "10.1016/j.ijheatfluidflow.2024.109644"),
    ("11", "A dynamic aggregation strategy enhanced efficient global optimization algorithm for solving high-dimensional turbomachinery design problems.pdf", "pdf", "10.1080/0305215X.2024.2325651"),
    ("12", "ssrn-4869789.pdf",                              "pdf",  "10.2139/ssrn.4869789"),
    ("13", None,                                            "none", "10.1115/1.4064228"),
    ("14", None,                                            "none", None),
    ("15", "AI-Assisted_Fluid-Structure_Modeling_and_Optimization_of_Pump-Jet_Propulsor.pdf", "pdf", None),
    ("16", "1-s2.0-S1000936125000792-main.pdf",             "pdf",  "10.1016/j.cja.2025.103473"),
    ("17", "1-s2.0-S1270963826007042-main.pdf",             "pdf",  "10.1016/j.ast.2026.112324"),
    ("18", "1-s2.0-S1270963826007315-main.pdf",             "pdf",  "10.1016/j.ast.2026.112440"),
    ("19", "1-s2.0-S1000936126003122-main.pdf",             "pdf",  "10.1016/j.cja.2026.104374"),
    ("20", None,                                            "none", None),
]

# 按文件名唯一化（防御性：同一文件被误配两次时只抽一次）
_SEEN = set()
UNIQUE_MAP = []
for rec in PAPER_MAP:
    if rec[1] is None:
        UNIQUE_MAP.append(rec)
        continue
    if rec[1] in _SEEN:
        continue
    _SEEN.add(rec[1])
    UNIQUE_MAP.append(rec)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def normalize(text: str) -> str:
    """统一全角/半角与空白，便于后续正则检索。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")           # 软连字符
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def read_pdf(path: str) -> tuple[str, int]:
    from pypdf import PdfReader  # 延迟导入，仅抽取阶段需要

    reader = PdfReader(path)
    chunks = []
    for i, page in enumerate(reader.pages, 1):
        try:
            txt = page.extract_text() or ""
        except Exception as exc:  # 单页失败不应中断整篇
            txt = f"[PAGE {i} EXTRACTION FAILED: {exc}]"
        chunks.append(f"\n===== [PAGE {i}] =====\n{txt}")
    return normalize("".join(chunks)), len(reader.pages)


def read_html(path: str) -> tuple[str, dict]:
    raw = open(path, encoding="utf-8", errors="replace").read()

    meta = {}
    for key in ("citation_title", "citation_journal_title", "citation_doi",
                "citation_volume", "citation_issue", "citation_firstpage",
                "citation_lastpage", "citation_publication_date", "citation_pii",
                "citation_issn", "citation_publisher", "dc.identifier"):
        m = re.search(r'<meta[^>]*name=["\']%s["\'][^>]*content=["\']([^"\']*)["\']' % key, raw)
        if not m:  # content 在 name 之前的情况
            m = re.search(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']%s["\']' % key, raw)
        if m:
            meta[key] = html_mod.unescape(m.group(1)).strip()

    authors = re.findall(r'<meta[^>]*name=["\']citation_author["\'][^>]*content=["\']([^"\']*)["\']', raw)
    if not authors:
        authors = re.findall(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']citation_author["\']', raw)
    meta["authors"] = [html_mod.unescape(a).strip() for a in authors]

    desc = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']*)["\']', raw)
    if desc:
        meta["abstract"] = html_mod.unescape(desc.group(1)).strip()

    # 正文：优先抓 ScienceDirect 的摘要段落，其余标签一律剥掉
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    abstract_blocks = re.findall(r'(?is)<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>', body)
    text_parts = []
    for blk in abstract_blocks:
        text_parts.append(re.sub(r"(?s)<[^>]+>", " ", blk))
    meta["has_fulltext"] = False
    if not text_parts:
        text_parts.append(re.sub(r"(?s)<[^>]+>", " ", body))
    return normalize(html_mod.unescape(" ".join(text_parts))), meta


DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def sniff_metadata(text: str, fallback_doi: str | None) -> dict:
    """从首页文本中尽力嗅探元数据；嗅探不到的字段保持 None。"""
    head = text[:6000]
    out = {"doi": None, "journal_hint": None, "year_hint": None, "title_hint": None}

    m = DOI_RE.search(head)
    if m:
        out["doi"] = m.group(0).rstrip(".,;")
    elif fallback_doi:
        out["doi"] = fallback_doi

    years = re.findall(r"\b(20[0-2]\d)\b", head)
    if years:
        out["year_hint"] = years[0]

    # 期刊线索：常见刊名
    for name in ("Aerospace Science and Technology", "Chinese Journal of Aeronautics",
                 "Structural and Multidisciplinary Optimization",
                 "International Journal of Heat and Mass Transfer",
                 "International Journal of Heat and Fluid Flow",
                 "Engineering Optimization", "IEEE Transactions on Cybernetics",
                 "Applied Thermal Engineering", "Journal of Turbomachinery"):
        if name.lower() in text[:20000].lower():
            out["journal_hint"] = name
            break

    # 标题线索：取首页中最长的、以大写字母开头的一行
    lines = [ln.strip() for ln in head.split("\n") if 25 < len(ln.strip()) < 160]
    if lines:
        out["title_hint"] = max(lines, key=len)
    return out


NUM_CLAIM_RE = re.compile(
    r"[^\n]{0,120}?\b\d+(?:\.\d+)?\s?%[^\n]{0,120}", re.IGNORECASE
)


def mine_numeric_claims(text: str, limit: int = 60) -> list[str]:
    """抽取含百分号的量化断言，作为人工核对的候选证据池。"""
    hits = []
    for m in NUM_CLAIM_RE.finditer(text):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if len(s) < 12:
            continue
        if s not in hits:
            hits.append(s)
        if len(hits) >= limit:
            break
    return hits


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", default=None, help="在已抽取语料中检索关键词")
    ap.add_argument("--context", type=int, default=180, help="grep 上下文字符数")
    args = ap.parse_args()

    os.makedirs(TXT_DIR, exist_ok=True)

    if args.grep:
        return do_grep(args.grep, args.context)

    index = []
    for pid, fname, kind, doi in UNIQUE_MAP:
        if kind == "none":
            index.append({
                "id": pid, "file": None, "kind": "none", "pages": None,
                "doi": None, "declared_doi": doi, "journal_hint": None,
                "year_hint": None, "title_hint": None, "has_fulltext": False,
                "chars": 0, "numeric_claims": [],
                "note": "无本地原文，需网络检索补全（见 corpus/web_evidence/）",
            })
            log(f"[NO-LOCAL] P{pid} 无本地文件，标记为待网络补全")
            continue
        path = os.path.join(PAPER_DIR, fname)
        if not os.path.exists(path):
            log(f"[MISSING] {pid} {fname}")
            continue

        if kind == "pdf":
            text, npages = read_pdf(path)
            meta = sniff_metadata(text, doi)
            record = {
                "id": pid, "file": fname, "kind": "pdf", "pages": npages,
                "doi": meta["doi"], "declared_doi": doi,
                "journal_hint": meta["journal_hint"],
                "year_hint": meta["year_hint"], "title_hint": meta["title_hint"],
                "has_fulltext": len(text) > 20000,
            }
        else:
            text, hmeta = read_html(path)
            record = {
                "id": pid, "file": fname, "kind": "html", "pages": None,
                "doi": hmeta.get("citation_doi"), "declared_doi": doi,
                "journal_hint": hmeta.get("citation_journal_title"),
                "year_hint": (hmeta.get("citation_publication_date") or "")[:4] or None,
                "title_hint": hmeta.get("citation_title"),
                "authors_hint": hmeta.get("authors"),
                "abstract_hint": hmeta.get("abstract"),
                "has_fulltext": False,
            }

        record["chars"] = len(text)
        slug = f"P{pid}_{os.path.splitext(fname)[0][:40]}"
        txt_path = os.path.join(TXT_DIR, slug + ".txt")
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        record["txt"] = os.path.relpath(txt_path, ROOT)
        record["numeric_claims"] = mine_numeric_claims(text)
        index.append(record)
        log(f"[OK] P{pid:<2} {fname[:52]:<54} chars={len(text):>7} pages={record['pages']} "
            f"fulltext={record['has_fulltext']}")

    index.sort(key=lambda r: r["id"])
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "tools/extract_corpus.py",
        "papers": index,
    }
    with open(os.path.join(CORPUS_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    log("\n" + "=" * 92)
    log(f"{'ID':<4}{'本地文件':<56}{'字符数':>9}{'页数':>6}  {'全文':<5}{'DOI'}")
    log("-" * 92)
    for r in index:
        log(f"P{r['id']:<3}{r['file'][:54]:<56}{r['chars']:>9}{str(r['pages'] or '-'):>6}  "
            f"{str(r['has_fulltext']):<5}{r['doi'] or 'None'}")
    log("=" * 92)
    log(f"共 {len(index)} 篇，语料已写入 {TXT_DIR}/ ，索引已写入 corpus/index.json")
    return 0


def do_grep(keyword: str, context: int) -> int:
    idx_path = os.path.join(CORPUS_DIR, "index.json")
    if not os.path.exists(idx_path):
        log("先运行抽取：python3 tools/extract_corpus.py")
        return 1
    index = json.load(open(idx_path, encoding="utf-8"))["papers"]
    pat = re.compile(re.escape(keyword), re.IGNORECASE)
    total = 0
    for r in index:
        text = open(os.path.join(ROOT, r["txt"]), encoding="utf-8").read()
        for m in pat.finditer(text):
            total += 1
            s = max(0, m.start() - context)
            e = min(len(text), m.end() + context)
            snippet = re.sub(r"\s+", " ", text[s:e])
            page = text[:m.start()].count("===== [PAGE")
            log(f"--- P{r['id']} {r['file'][:40]} (约第 {page} 页) ---\n...{snippet}...\n")
    log(f"命中 {total} 处。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

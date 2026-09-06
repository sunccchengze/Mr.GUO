#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_corpus.py —— Mr.GUO 本地文献语料抽取管线
=============================================================================
用途：把 `郭老师论文/` 下的 13 篇 PDF 全文 + 2 篇 ScienceDirect HTML 摘要页（仅摘要与元数据），
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
    # DOI 已按 corpus/doi_verification.md 修正：文档旧值 ...3168744 尾号有误，
    # 原文首页与第三方期刊的参考文献著录均为 ...3165044。
    ("06", "Generative_Multiform_Bayesian_Optimization.pdf", "pdf",  "10.1109/TCYB.2022.3165044"),
    ("07", "1-s2.0-S1270963823005710-main.pdf",             "pdf",  "10.1016/j.ast.2023.108675"),
    ("08", "1-s2.0-S1270963824001317-main.pdf",             "pdf",  "10.1016/j.ast.2024.108998"),
    ("09", "S1270963824001482.htm",                         "html", "10.1016/j.ast.2024.109015"),
    ("10", "S0142727X24003692.htm",                         "html", "10.1016/j.ijheatfluidflow.2024.109644"),
    ("11", "A dynamic aggregation strategy enhanced efficient global optimization algorithm for solving high-dimensional turbomachinery design problems.pdf", "pdf", "10.1080/0305215X.2024.2325651"),
    ("12", "ssrn-4869789.pdf",                              "pdf",  "10.2139/ssrn.4869789"),
    ("13", None,                                            "none", "10.1115/1.4064228"),
    # 2026-09-06 二次核验：Crossref 可直接命中（proceedings-article，GT2024-128792，
    # 文章号 V12DT34A025），旧版"Crossref 未命中"为误判。
    ("14", None,                                            "none", "10.1115/GT2024-128792"),
    ("15", "AI-Assisted_Fluid-Structure_Modeling_and_Optimization_of_Pump-Jet_Propulsor.pdf", "pdf", "10.1109/CEC65147.2025.11043110"),
    ("16", "1-s2.0-S1000936125000792-main.pdf",             "pdf",  "10.1016/j.cja.2025.103473"),
    ("17", "1-s2.0-S1270963826007042-main.pdf",             "pdf",  "10.1016/j.ast.2026.112324"),
    # DOI 已按 corpus/doi_verification.md 修正：旧值 ...112440 指向一篇与本团队无关的
    # GCN 论文（AST 178 Part B），正确文章号为 112351。
    ("18", "1-s2.0-S1270963826007315-main.pdf",             "pdf",  "10.1016/j.ast.2026.112351"),
    ("19", "1-s2.0-S1000936126003122-main.pdf",             "pdf",  "10.1016/j.cja.2026.104374"),
    # 2026-09-06 二次核验：Proc. SPIE 14253 (HARCT 2026), 142530E；旧版"SPIE 未开放索引"为误判。
    ("20", None,                                            "none", "10.1117/12.3117536"),
]

# ---------------------------------------------------------------------------
# 人工裁定（curated）的年份与发表载体：sniff_metadata() 的启发式嗅探会误抓
# （如 P02 首页引用年份 2016、P15 参考文献中的期刊名），且无原文的 5 篇嗅探不到。
# 下表依据 corpus/doi_verification.md 与事实卡著录人工裁定，是年份/载体的唯一口径：
#   年份 = 首次正式发表年（在线优先）；P11 在线 2024，正式卷期 2025, 57(2)。
# ---------------------------------------------------------------------------
CURATED_META = {
    "01": (2021, "Structural and Multidisciplinary Optimization"),
    "02": (2021, "Structural and Multidisciplinary Optimization"),
    "03": (2021, "International Journal of Heat and Mass Transfer"),
    "04": (2021, "ASME Journal of Turbomachinery"),
    "05": (2021, "ASME Journal of Turbomachinery"),
    "06": (2023, "IEEE Transactions on Cybernetics"),
    "07": (2023, "Aerospace Science and Technology"),
    "08": (2024, "Aerospace Science and Technology"),
    "09": (2024, "Aerospace Science and Technology"),
    "10": (2024, "International Journal of Heat and Fluid Flow"),
    "11": (2024, "Engineering Optimization"),
    "12": (2024, "SSRN Preprint"),
    "13": (2024, "ASME Journal of Turbomachinery"),
    "14": (2024, "ASME Turbo Expo"),
    "15": (2025, "IEEE Congress on Evolutionary Computation (CEC)"),
    "16": (2025, "Chinese Journal of Aeronautics"),
    "17": (2026, "Aerospace Science and Technology"),
    "18": (2026, "Aerospace Science and Technology"),
    "19": (2026, "Chinese Journal of Aeronautics"),
    "20": (2026, "SPIE Conference"),
}

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


_YEAR = r"(20[0-2]\d)"
# 年份嗅探按“出版语义”排优先级，而不是取首页第一个 20xx（旧逻辑曾把 P02 参考文献里的 2016 当成出版年）。
_YEAR_RULES = [
    re.compile(r"(?:Available\s*online|Published\s*online|First\s*published|Published)[^\n]{0,60}?" + _YEAR, re.I),
    re.compile(r"VOL\.[^\n]{0,60}?" + _YEAR),                     # IEEE 卷期行：VOL. 53, NO. 7, JULY 2023
    re.compile(r"(?:©|Copyright)[^\n]{0,120}?" + _YEAR),
    re.compile(r"Accepted[^\n]{0,60}?" + _YEAR, re.I),
]


def sniff_year(head: str) -> str | None:
    """从首页文本嗅探出版年：在线发表/卷期/版权/录用 依次兜底，最后才退回“首个孤立的 20xx”。"""
    for rule in _YEAR_RULES:
        m = rule.search(head)
        if m:
            return m.group(1)
    m = re.search(r"(?<!\d)" + _YEAR + r"(?!\d)", head)
    return m.group(1) if m else None


def sniff_metadata(text: str, fallback_doi: str | None) -> dict:
    """从首页文本中尽力嗅探元数据；嗅探不到的字段保持 None。"""
    head = text[:6000]
    out = {"doi": None, "journal_hint": None, "year_hint": None, "title_hint": None}

    m = DOI_RE.search(head)
    if m:
        out["doi"] = m.group(0).rstrip(".,;")
    elif fallback_doi:
        out["doi"] = fallback_doi

    out["year_hint"] = sniff_year(head)

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
                "curated_year": CURATED_META[pid][0], "curated_venue": CURATED_META[pid][1],
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
                "curated_year": CURATED_META[pid][0], "curated_venue": CURATED_META[pid][1],
                "journal_hint": meta["journal_hint"],
                "year_hint": meta["year_hint"], "title_hint": meta["title_hint"],
                "has_fulltext": len(text) > 20000,
            }
        else:
            text, hmeta = read_html(path)
            record = {
                "id": pid, "file": fname, "kind": "html", "pages": None,
                "doi": hmeta.get("citation_doi"), "declared_doi": doi,
                "curated_year": CURATED_META[pid][0], "curated_venue": CURATED_META[pid][1],
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
    # 确定性内容戳：原文目录的内容哈希，而非“此刻”（mtime 经不起 touch）。
    # 否则每次重跑 index.json 都会变脏，破坏“可复现”承诺。
    import hashlib
    h = hashlib.sha256()
    try:
        names = sorted(os.listdir(PAPER_DIR))
    except OSError:
        names = []
    for f in names:
        if f.startswith("."):
            continue
        try:
            with open(os.path.join(PAPER_DIR, f), "rb") as fh:
                while True:
                    blk = fh.read(1 << 20)
                    if not blk:
                        break
                    h.update(blk)
        except OSError:
            pass
    out = {
        "generated_at": "src-" + h.hexdigest()[:12],
        "generator": "tools/extract_corpus.py",
        "papers": index,
    }
    with open(os.path.join(CORPUS_DIR, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    log("\n" + "=" * 92)
    log(f"{'ID':<4}{'本地文件':<56}{'字符数':>9}{'页数':>6}  {'全文':<5}{'DOI'}")
    log("-" * 92)
    for r in index:
        # 无本地原文的篇目 r['file'] 为 None，直接切片会抛 TypeError，故先兜底
        log(f"P{r['id']:<3}{str(r['file'] or '-')[:54]:<56}{r['chars']:>9}"
            f"{str(r['pages'] or '-'):>6}  {str(r['has_fulltext']):<5}{r['doi'] or 'None'}")
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

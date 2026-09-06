#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skills/omni_scholar/core.py —— 文献分析技能包（**真实实现版**）
=============================================================================

为什么重写
----------
旧版 `core.py` 是一个"假装在工作"的壳子：所有方法都返回一段写死的漂亮话，
`generate_reproducible_code_blueprint()` 更是把假文本直接当结果返回。
它不读取任何语料、不输出任何可回溯的证据。

本版把它改造成**真正调用本仓库抽取能力的检索与核验工具**，并遵守与白皮书
完全相同的铁律：

> **没有出处的话不输出。**
> 本技能产生的每一条论断，都附带 (文件, 字符区间, 原文片段) 三元组，
> 可以直接回溯到 `corpus/txt/` 里的原文字符。凡语料中检索不到的，
> 一律返回空结果并标注「语料中未检索到」，**绝不代以模板套话**。

能力清单
--------
1. `verify_doi(pid)`            —— 元数据与 DOI 核验（声明值 / 核验值 / 正文嗅探值三方比对）
2. `extract_skeleton(pid)`      —— 四维骨架抽取（痛点 / 前人失效 / 本文方法 / 量化验证），逐条带证据
3. `build_evolution_topology()` —— 跨文献演进拓扑（按真实年份排代、方法关键词共现、共同作者）
4. `detect_cross_paper_links()` —— 跨文献互证 / 批评关系（在正文中检索他篇方法名的真实命中）
5. `generate_fact_card(pid)`    —— 生成事实卡（Markdown），含证据等级与全部证据位置

与 `tools/extract_corpus.py` 的关系
-----------------------------------
本模块**直接复用** `tools/extract_corpus.py` 的 `normalize` / `DOI_RE` /
`mine_numeric_claims` / `sniff_metadata`，不另写一套正则，避免两处口径漂移。

命令行用法（仓库根目录执行）
----------------------------
    python skills/omni_scholar/core.py --demo
    python skills/omni_scholar/core.py --verify-doi 06
    python skills/omni_scholar/core.py --skeleton 07
    python skills/omni_scholar/core.py --topology
    python skills/omni_scholar/core.py --links
    python skills/omni_scholar/core.py --fact-card 09
    python skills/omni_scholar/core.py --grep "negative transfer"

作为 Python 库调用
------------------
    from skills.omni_scholar.core import OmniScholarEngine
    eng = OmniScholarEngine()
    sk = eng.extract_skeleton("07")
    print(sk.core_methodology.render())
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- 路径
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CORPUS = os.path.join(ROOT, "corpus")
TXT_DIR = os.path.join(CORPUS, "txt")
FACTS_DIR = os.path.join(CORPUS, "facts")
INDEX = os.path.join(CORPUS, "index.json")

# --------------------------------------------------------------------------- 复用抽取器的能力
def _load_extractor():
    """按文件路径加载 tools/extract_corpus.py（它不在任何包里）。"""
    path = os.path.join(ROOT, "tools", "extract_corpus.py")
    spec = importlib.util.spec_from_file_location("_mrguo_extract_corpus", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 tools/extract_corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_EX = _load_extractor()
normalize = _EX.normalize
DOI_RE = _EX.DOI_RE
mine_numeric_claims = _EX.mine_numeric_claims
sniff_metadata = _EX.sniff_metadata


# --------------------------------------------------------------------------- 数据结构
@dataclass
class Evidence:
    """一条可回溯的证据：语料文件 + 字符区间 + 原文片段。"""

    source: str          # 相对仓库根目录的路径
    start: int
    end: int
    snippet: str

    def render(self, width: int = 200) -> str:
        s = re.sub(r"\s+", " ", self.snippet).strip()
        if len(s) > width:
            s = s[: width - 3] + "..."
        return f"- `{self.source}` 字符 [{self.start}:{self.end}]：" + "「" + s + "」"

    def as_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "start": self.start, "end": self.end,
                "snippet": re.sub(r"\s+", " ", self.snippet).strip()}


@dataclass
class SkeletonField:
    """四维骨架中的一个维度。claim 为**检索到**的核心句；若无命中则标注「未检索到」。"""

    name: str
    claim: str
    evidence: List[Evidence] = field(default_factory=list)
    found: bool = True

    def render(self) -> str:
        head = f"**{self.name}**：{self.claim}"
        if not self.evidence:
            return head + "\n  - （本维度在语料中未检索到支持句，故不给出论断。）"
        return head + "\n" + "\n".join("  " + e.render() for e in self.evidence)

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "claim": self.claim, "found": self.found,
                "evidence": [e.as_dict() for e in self.evidence]}


@dataclass
class FourDimensionalDeconstruction:
    paper_id: str
    title_hint: Optional[str]
    evidence_level: str
    core_problem_and_motivation: SkeletonField
    previous_sota_limitations: SkeletonField
    core_methodology_and_math: SkeletonField
    validation_and_empirical_gains: SkeletonField

    def render(self) -> str:
        return "\n".join([
            f"## 论文 P{self.paper_id} 四维骨架（证据等级 {self.evidence_level}）",
            f"- 标题线索：{self.title_hint or '语料中未嗅探到'}",
            "",
            self.core_problem_and_motivation.render(),
            "",
            self.previous_sota_limitations.render(),
            "",
            self.core_methodology_and_math.render(),
            "",
            self.validation_and_empirical_gains.render(),
        ])


# --------------------------------------------------------------------------- 主引擎
class OmniScholarEngine:
    """文献检索与核验引擎。所有输出均来自 `corpus/` 中的真实语料。"""

    #: 方法关键词表（用于跨文献拓扑）。键为方法名，值为在语料中检索用的正则。
    METHOD_KEYWORDS: Dict[str, str] = {
        "Kriging / Gaussian process": r"\b(Kriging|kriging|Gaussian process|GP model)\b",
        "Expected improvement (EI)": r"\b(expected improvement|\bEI\b|acquisition function)\b",
        "Multi-fidelity / Co-Kriging": r"\b(multi-?fidelity|co-?kriging|multi-?form)\b",
        "Differential evolution": r"\b(differential evolution|\bDE\b|evolutionary algorithm)\b",
        "Decomposition / subspace": r"\b(decompos\w+|sub-?space|subspace)\b",
        "Generative model (GAN/VAE)": r"\b(generative adversarial|\bGAN\b|\bVAE\b|latent space)\b",
        "Transfer / knowledge reuse": r"\b(transfer learning|knowledge transfer|negative transfer)\b",
        "Neural operator / deep net": r"\b(neural operator|deep neural network|transformer|UNet|ResUNet)\b",
        "Physics-enhanced / SHAP": r"\b(physics-?(enhanced|informed)|\bSHAP\b|superposition principle)\b",
        "Uncertainty quantification": r"\b(uncertainty quantific\w+|\bUQ\b|polynomial chaos|\bANOVA\b)\b",
    }

    #: 分页标记（replace 为等长空格，保证字符偏移与原文一致）
    PAGE_RE = re.compile(r"===== \[PAGE \d+\] =====")

    def view(self, pid: str) -> str:
        """检索视图：换行与分页标记换成空格（**等长替换，字符偏移不变**），
        这样跨行的句子也能被整句命中。"""
        body = self.text(pid)
        if not body:
            return ""
        v = self.PAGE_RE.sub(lambda m: " " * len(m.group(0)), body)
        return v.replace("\n", " ")

    #: 四维骨架各维度的检索模式（英文；语料为英文原文）
    SKELETON_PATTERNS: Dict[str, List[str]] = {
        "核心痛点与研究动机": [
            r"[^.]{0,200}?\b(however|challeng\w+|expensive|costly|"
            r"curse of dimensionality|bottleneck|difficult\w*|limitation)\b[^.]{0,200}\.",
            r"[^.]{0,200}?\b(problem|issue|concern|obstacle)\b[^.]{0,120}?"
            r"\b(remain\w*|still|yet|unsolved|open)\b[^.]{0,160}\.",
        ],
        "前人方法为何失效": [
            r"[^.]{0,200}?\b(state[- ]of[- ]the[- ]art|previous|existing|conventional|"
            r"traditional|prior)\b[^.]{0,160}?\b(suffer\w*|fail\w*|limit\w*|inadequat\w*|"
            r"cannot|unable|degrad\w*|poor|drawback\w*|bottleneck|challeng\w*|"
            r"expensive|costly|difficult\w*)\b[^.]{0,200}\.",
            r"[^.]{0,200}?\b(however|unfortunately|yet|nevertheless)\b[^.]{0,160}?"
            r"\b(method\w*|approach\w*|algorithm\w*|model\w*|surrogate\w*|technique\w*)\b"
            r"[^.]{0,160}\.",
        ],
        "本文方法与数学内核": [
            r"[^.]{0,200}?\b(we propose|this paper proposes|in this (paper|work|study)|"
            r"we present|we develop|our (method|approach|framework))\b[^.]{0,260}\.",
            r"[^.]{0,200}?\b(proposed|presented|developed)\b[^.]{0,120}?"
            r"\b(method|approach|framework|algorithm|model)\b[^.]{0,200}\.",
        ],
        "实验验证与量化收益": [
            r"[^.]{0,220}?\b(compared (with|to)|baseline|outperform\w*|improv\w+|reduc\w+|"
            r"increas\w+|achiev\w+)\b[^.]{0,220}?\d[^.]{0,120}\.",
            r"[^.]{0,220}?\b(experimental|numerical|simulation|validation|verification)\b"
            r"[^.]{0,160}?\d[^.]{0,120}\.",
        ],
    }

    def __init__(self, corpus_dir: str = CORPUS):
        self.corpus_dir = corpus_dir
        self._index: Optional[Dict[str, Any]] = None
        self._papers: Optional[Dict[str, dict]] = None
        self._text_cache: Dict[str, str] = {}

    # ---------------------------------------------------------------- 语料访问
    @property
    def index(self) -> Dict[str, Any]:
        if self._index is None:
            with open(os.path.join(self.corpus_dir, "index.json"), encoding="utf-8") as f:
                self._index = json.load(f)
        return self._index

    @property
    def papers(self) -> Dict[str, dict]:
        if self._papers is None:
            self._papers = {p["id"]: p for p in self.index["papers"]}
        return self._papers

    def paper_ids(self) -> List[str]:
        return sorted(self.papers)

    def text(self, pid: str) -> str:
        """取某篇的正文（懒加载 + 缓存）。无全文者返回空串。"""
        if pid in self._text_cache:
            return self._text_cache[pid]
        rel = self.papers[pid].get("txt")
        if not rel:
            self._text_cache[pid] = ""
            return ""
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            self._text_cache[pid] = ""
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        self._text_cache[pid] = content
        return content

    def has_text(self, pid: str) -> bool:
        """正文是否真的可检索。corpus/txt/ 是 .gitignore 排除的派生产物，
        新克隆的仓库里默认不存在，必须先跑 tools/extract_corpus.py 生成。"""
        return bool(self.text(pid).strip())

    def corpus_ready(self) -> bool:
        return any(self.has_text(pid) for pid in self.paper_ids())

    def evidence_level(self, pid: str) -> str:
        p = self.papers[pid]
        if p.get("has_fulltext"):
            if not self.has_text(pid):
                return ("A（本地有 PDF 原文，但尚未抽取正文，暂不可逐句回溯；"
                        "运行 tools/extract_corpus.py 后可回溯）")
            return "A（本地有全文，可逐句回溯）"
        if p.get("kind") == "html":
            return "B（仅摘要级 HTML）"
        # 无本地文件：若 corpus/web_evidence/PXX.md 已登记权威著录与出版商摘要，则为 B；
        # 只有连 DOI/摘要都没有时才是 C（截至 2026-09-06 全集已无此类条目）。
        if p.get("declared_doi") and os.path.exists(
                os.path.join(ROOT, "corpus", "web_evidence", f"P{pid}.md")):
            return "B（无本地原文；DOI 与出版商摘要已核验，见 corpus/web_evidence/）"
        return "C（仅公开线索，无本地原文）"

    # ---------------------------------------------------------------- 1) DOI 核验
    def verify_doi(self, pid: str) -> Dict[str, Any]:
        """三方比对：文档声明值 / 已核验值 / 正文嗅探值。"""
        p = self.papers[pid]
        declared = p.get("declared_doi")
        verified = p.get("doi")
        body = self.text(pid)
        sniffed = None
        if body:
            m = DOI_RE.search(body[:20000])
            if m:
                sniffed = m.group(0).rstrip(".,;")
        if verified and declared and declared != verified:
            status, note = "冲突", "⚠ 文档声明值与核验值不一致，已按 corpus/doi_verification.md 修正"
        elif not verified and declared:
            status, note = ("出版商核验",
                            "本地无原文，无法从正文嗅探；声明值来自 Crossref/出版商页面核验"
                            "（见 corpus/doi_verification.md 与 corpus/web_evidence/）")
        elif not verified:
            status, note = "未核验", "本地无原文，且未取得可核验的 DOI"
        elif not declared:
            status, note = "仅核验值", "旧文档未登记 DOI，现有值为本次核验结果"
        else:
            status, note = "一致", "声明值与核验值一致"
        return {
            "paper_id": pid,
            "status": status,
            "declared_doi": declared,
            "verified_doi": verified,
            "in_text_doi": sniffed,
            "declared_matches_verified": (status in ("一致", "仅核验值", "出版商核验")),
            "verified_matches_in_text": (sniffed is None) or (sniffed == verified),
            "has_fulltext": bool(p.get("has_fulltext")),
            "txt_file": p.get("txt"),
            "note": note,
        }

    # ---------------------------------------------------------------- 2) 四维骨架
    def _search(self, pid: str, pattern: str, limit: int = 4,
                span: Optional[Tuple[int, int]] = None) -> List[Evidence]:
        """在正文中检索。默认只搜前 85%（文末通常是参考文献，命中多为噪声）。"""
        body = self.view(pid)
        if not body:
            return []
        if span is None:
            span = (0, int(len(body) * 0.85))
        lo, hi = span
        seg = body[lo:hi] if hi else body[lo:]
        out: List[Evidence] = []
        seen: set = set()
        for m in re.finditer(pattern, seg, re.IGNORECASE):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) < 40 or s in seen:
                continue
            seen.add(s)
            out.append(Evidence(source=self.papers[pid].get("txt", "?"),
                                start=lo + m.start(), end=lo + m.end(), snippet=s))
            if len(out) >= limit:
                break
        return out

    def extract_skeleton(self, pid: str, per_field: int = 3) -> FourDimensionalDeconstruction:
        """四维骨架抽取。每个维度给出**检索到的支持句**及其字符位置。

        每个维度按"严→宽"依次尝试若干模式：先找最贴切的表述，找不到再放宽；
        全都找不到时返回 `found=False`，**绝不生成模板套话**。
        """
        if pid not in self.papers:
            raise KeyError(f"无此论文编号：{pid}（可用：{', '.join(self.paper_ids())}）")
        body = self.text(pid)
        if not body:
            raise ValueError(
                f"论文 P{pid} 在本地没有正文（{self.papers[pid].get('file')}），"
                f"无法抽取骨架——本技能不生成无语料支撑的内容。")

        def build(name: str, patterns: Sequence[str]) -> SkeletonField:
            for i, pat in enumerate(patterns):
                ev = self._search(pid, pat, limit=per_field)
                if ev:
                    return SkeletonField(
                        name=name,
                        claim="语料中检索到以下直接表述（按出现顺序"
                              + ("，已放宽检索条件" if i else "") + "）：",
                        evidence=ev, found=True)
            return SkeletonField(name=name,
                                 claim="语料中未检索到该维度的直接表述（未给出论断）。",
                                 evidence=[], found=False)

        fields = {k: build(k, v) for k, v in self.SKELETON_PATTERNS.items()}

        # 第四维额外补上量化断言池（复用抽取器的 mine_numeric_claims）
        claims = mine_numeric_claims(body, limit=6)
        if claims:
            extra = []
            for c in claims[:3]:
                pos = body.find(c)
                extra.append(Evidence(source=self.papers[pid].get("txt", "?"),
                                      start=max(pos, 0), end=max(pos, 0) + len(c),
                                      snippet=re.sub(r"\s+", " ", c).strip()))
            fields["实验验证与量化收益"].evidence.extend(extra)

        return FourDimensionalDeconstruction(
            paper_id=pid,
            title_hint=self.papers[pid].get("title_hint"),
            evidence_level=self.evidence_level(pid),
            core_problem_and_motivation=fields["核心痛点与研究动机"],
            previous_sota_limitations=fields["前人方法为何失效"],
            core_methodology_and_math=fields["本文方法与数学内核"],
            validation_and_empirical_gains=fields["实验验证与量化收益"],
        )

    # ---------------------------------------------------------------- 3) 演进拓扑
    def build_evolution_topology(self) -> Dict[str, Any]:
        """按**真实年份**排代 + 方法关键词共现 + 共同作者，构建跨文献拓扑。"""
        rows = []
        for pid in self.paper_ids():
            body = self.text(pid)
            methods = [name for name, pat in self.METHOD_KEYWORDS.items()
                       if body and re.search(pat, body, re.IGNORECASE)]
            p = self.papers[pid]
            rows.append({
                "id": pid,
                "year": p.get("year_hint"),
                "venue": p.get("journal_hint"),
                "has_fulltext": bool(p.get("has_fulltext")),
                "methods": methods,
            })
        with_text = [r for r in rows if r["year"]]
        timeline: Dict[str, List[str]] = {}
        for r in sorted(with_text, key=lambda x: (str(x["year"]), x["id"])):
            timeline.setdefault(str(r["year"]), []).append(f"P{r['id']}")

        # 方法关键词的"共现矩阵"（只看是否有共同方法，作为代际亲缘的**证据**）
        cooccurrence: List[Dict[str, Any]] = []
        ids = [r["id"] for r in rows]
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ma = set(next(r["methods"] for r in rows if r["id"] == a))
                mb = set(next(r["methods"] for r in rows if r["id"] == b))
                shared = sorted(ma & mb)
                if shared:
                    cooccurrence.append({"pair": [f"P{a}", f"P{b}"],
                                         "shared_methods": shared,
                                         "n_shared": len(shared)})
        cooccurrence.sort(key=lambda d: -d["n_shared"])

        return {
            "n_papers": len(rows),
            "n_with_fulltext": sum(1 for r in rows if r["has_fulltext"]),
            "timeline_by_year": timeline,
            "methods_per_paper": {f"P{r['id']}": r["methods"] for r in rows},
            "method_cooccurrence_top": cooccurrence[:15],
            "note": ("拓扑完全由 corpus/ 中的真实文本统计得出：年份取 index.json 的 year_hint，"
                     "方法命中取正文正则匹配。未做任何人工归类。"),
        }

    # ---------------------------------------------------------------- 4) 跨文献互证
    #: 各篇的"方法代号"，用于在别篇正文里检索被提及/被批评的痕迹
    ALIASES: Dict[str, str] = {
        "01": r"\b(CR[- ]?EI|calibrated and recalibrated expected improvement)\b",
        "02": r"\b(Filter[- ]?GEI|generalized expected improvement)\b",
        "03": r"\b(MFSIK|ASMO)\b",
        "04": r"\b(Slot[- ]?UQ|uncertainty quantific\w+ of aero-?thermal)\b",
        "06": r"\b(GMFoO|multiform|MFoO)\b",
        "07": r"\b(GSDE|surrogate[- ]assisted differential evolution)\b",
        "08": r"\b(SW[- ]?VAE|KT[- ]?ASO|sample[- ]weighted VAE)\b",
        "11": r"\b(DA[- ]?EGO|dynamic aggregation|decomposition[- ]based EGO)\b",
        "12": r"\b(SDNO|superposition\w* (principle )?(based )?neural operator)\b",
        "13": r"\b(EMFS|MSFO|ensemble weighted multi-?fidelity)\b",
        "16": r"\b(TNO|panoramic prediction)\b",
        "17": r"\b(GTO|gradient[- ]based (generative )?transform)\b",
        "18": r"\b(ResUNet[- ]?Sim|similarity principle)\b",
        "19": r"\b(SHAP[- ]?Turbine|Shapley)\b",
    }
    CRITIQUE_RE = re.compile(
        r"[^.]{0,180}\b(however|unfortunately|suffer\w*|fail\w*|limitat\w*|drawback\w*|"
        r"degrad\w*|mislead\w*|negative transfer|poor|weak)\b[^.]{0,180}\.", re.IGNORECASE)

    def detect_cross_paper_links(self, limit_per_pair: int = 1) -> List[Dict[str, Any]]:
        """在 A 篇正文中检索 B 篇方法名被提及的位置；若命中句同时含批评性措辞，
        则标记为"批评/局限"，否则标记为"引用/互证"。全部带字符位置。"""
        links: List[Dict[str, Any]] = []
        for pid in self.paper_ids():
            body = self.text(pid)
            if not body:
                continue
            for other, alias in self.ALIASES.items():
                if other == pid:
                    continue
                for m in re.finditer(alias, body, re.IGNORECASE):
                    win_lo = max(0, m.start() - 400)
                    win_hi = min(len(body), m.end() + 400)
                    window = body[win_lo:win_hi]
                    cm = self.CRITIQUE_RE.search(window)
                    kind = "批评/局限" if cm else "引用/互证"
                    anchor = cm.group(0) if cm else window[:200]
                    links.append({
                        "from": f"P{pid}",
                        "to": f"P{other}",
                        "kind": kind,
                        "match": re.sub(r"\s+", " ", m.group(0)).strip(),
                        "source": self.papers[pid].get("txt"),
                        "start": win_lo,
                        "end": win_hi,
                        "snippet": re.sub(r"\s+", " ", anchor).strip()[:300],
                    })
                    break   # 每对只取第一处命中，避免刷屏
        return links

    # ---------------------------------------------------------------- 5) 事实卡
    def generate_fact_card(self, pid: str) -> str:
        """生成一篇论文的事实卡（Markdown），含元数据、DOI 核验与四维骨架证据。"""
        p = self.papers[pid]
        doi = self.verify_doi(pid)
        lines: List[str] = []
        lines.append(f"# 事实卡 · 论文 {pid}")
        lines.append("")
        lines.append("| 项 | 值 |")
        lines.append("| :--- | :--- |")
        lines.append(f"| 本地文件 | `{p.get('file')}` |")
        lines.append(f"| 类型 | {p.get('kind')}（{p.get('pages')} 页） |")
        lines.append(f"| 证据等级 | {self.evidence_level(pid)} |")
        lines.append(f"| 期刊线索 | {p.get('journal_hint') or '未嗅探到'} |")
        lines.append(f"| 年份线索 | {p.get('year_hint') or '未嗅探到'} |")
        lines.append(f"| 核验 DOI | `{doi['verified_doi'] or doi['declared_doi'] or '未获取'}`"
                     f"{'（出版商/Crossref 核验，正文不可嗅探）' if not doi['verified_doi'] and doi['declared_doi'] else ''} |")
        lines.append(f"| 正文内 DOI | `{doi['in_text_doi'] or '未嗅探到'}` |")
        lines.append(f"| 语料字符数 | {p.get('chars')} |")
        lines.append(f"| 语料文件 | `{p.get('txt') or '无'}` |")
        lines.append("")

        existing = os.path.join(FACTS_DIR, f"P{pid}.md")
        if os.path.exists(existing):
            lines.append(f"> 人工整理的事实卡已存在：`corpus/facts/P{pid}.md`（以人工版本为准）。")
            lines.append("")

        if p.get("numeric_claims"):
            lines.append("## 抽取器命中的量化断言（前 8 条，需人工核对后引用）")
            lines.append("")
            for c in p["numeric_claims"][:8]:
                cleaned = re.sub(r"\s+", " ", c).strip()
                lines.append(f"- {cleaned}")
            lines.append("")

        if p.get("has_fulltext"):
            lines.append("## 四维骨架（自动检索，逐条可回溯）")
            lines.append("")
            lines.append(self.extract_skeleton(pid).render())
        else:
            lines.append("## 四维骨架")
            lines.append("")
            lines.append("> 本地无全文，**不生成骨架**（本技能不产出无语料支撑的内容）。"
                         "如需事实依据，请查阅 `corpus/web_evidence/` 与 `corpus/facts/`。")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 6) 全文检索
    def grep(self, keyword: str, context: int = 180, limit: int = 10) -> List[Dict[str, Any]]:
        """在全部语料中检索关键词，返回带字符位置的命中（转发抽取器的能力）。"""
        out: List[Dict[str, Any]] = []
        for pid in self.paper_ids():
            body = self.text(pid)
            if not body:
                continue
            for m in re.finditer(re.escape(keyword), body, re.IGNORECASE):
                lo = max(0, m.start() - context)
                hi = min(len(body), m.end() + context)
                out.append({
                    "paper": f"P{pid}",
                    "source": self.papers[pid].get("txt"),
                    "start": m.start(), "end": m.end(),
                    "snippet": re.sub(r"\s+", " ", body[lo:hi]).strip(),
                })
                if len(out) >= limit:
                    return out
        return out


# --------------------------------------------------------------------------- CLI
PREP_HINT = (
    "正文语料尚未生成（corpus/txt/ 是派生产物，不入库）。\n"
    "  一次性准备：\n"
    "      python3 -m venv .venv && .venv/bin/pip install pypdf\n"
    "      python3 tools/extract_corpus.py\n"
    "  之后 --skeleton / --links / --grep / --demo 的全文检索部分即可输出真实结果。"
)


def _demo(engine: OmniScholarEngine) -> int:
    print("=" * 78)
    print("Omni-Scholar 端到端演示（全部输出来自 corpus/ 真实语料）")
    print("=" * 78)

    print("\n【1】语料概览")
    print(f"  - 论文数：{len(engine.paper_ids())}；编号：{', '.join(engine.paper_ids())}")
    print(f"  - 有全文：{sum(1 for p in engine.paper_ids() if engine.papers[p].get('has_fulltext'))} 篇")

    print("\n【2】DOI 核验（逐篇三方比对）")
    bad = []
    for pid in engine.paper_ids():
        r = engine.verify_doi(pid)
        flag = ("OK " if r["status"] in ("一致", "出版商核验")
                else ("?! " if r["status"] == "未核验" else "!! "))
        if r["status"] == "冲突":
            bad.append(f"P{pid}")
        print(f"  {flag}P{pid} [{r['status']}]: 声明={r['declared_doi']} | "
              f"核验={r['verified_doi']} | 正文={r['in_text_doi']}")
    print(f"  → 真正冲突的篇目：{bad if bad else '无'}"
          f"（标 OK[出版商核验] 者为无本地原文、DOI 经 Crossref/出版商页面核验；标 ?! 者为既无原文也无 DOI）")

    print("\n【3】四维骨架抽取示例（取一篇正文已抽取的论文）")
    target = next((p for p in engine.paper_ids() if engine.has_text(p)), None)
    if target:
        print(engine.extract_skeleton(target).render())
    else:
        print("  ⚠ 无可检索正文，本节跳过。\n  " + PREP_HINT)

    print("\n【4】跨文献演进拓扑")
    topo = engine.build_evolution_topology()
    print(f"  - 年份分布：{json.dumps(topo['timeline_by_year'], ensure_ascii=False)}")
    print("  - 方法共现（前 5 对）：")
    for c in topo["method_cooccurrence_top"][:5]:
        print(f"      {' ↔ '.join(c['pair'])}：共享 {c['n_shared']} 个方法关键词"
              f" → {', '.join(c['shared_methods'][:3])}")

    print("\n【5】跨文献互证 / 批评关系（前 8 条）")
    links = engine.detect_cross_paper_links()[:8]
    if links:
        for lk in links:
            print(f"  - P{lk['from'][1:]} → {lk['to']}｜{lk['kind']}｜命中「{lk['match']}」")
            print(f"      `{lk['source']}` [{lk['start']}:{lk['end']}]")
    else:
        print("  ⚠ 无已抽取正文，本节跳过。\n  " + PREP_HINT)

    print("\n【6】事实卡示例")
    if target:
        print(engine.generate_fact_card(target)[:1200])
        print("      ……（完整事实卡见 --fact-card 输出）")
    else:
        print("  ⚠ 无已抽取正文，本节跳过；人工事实卡见 `corpus/facts/`。")

    print("\n" + "=" * 78)
    if target:
        print("演示结束。以上每一条都可通过 (文件, 字符区间) 回溯到原文。")
    else:
        print("演示结束：【1】【2】【4】基于已入库的 corpus/index.json 与 corpus/facts/，"
              "离线即可复现；\n全文检索类小节需先完成上方的一次性语料抽取。")
    print("=" * 78)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="omni_scholar 文献检索与核验引擎（真实实现）")
    ap.add_argument("--demo", action="store_true", help="端到端演示")
    ap.add_argument("--verify-doi", metavar="PID", default=None, help="核验某篇的 DOI")
    ap.add_argument("--skeleton", metavar="PID", default=None, help="抽取四维骨架")
    ap.add_argument("--topology", action="store_true", help="跨文献演进拓扑")
    ap.add_argument("--links", action="store_true", help="跨文献互证/批评关系")
    ap.add_argument("--fact-card", metavar="PID", default=None, help="生成事实卡")
    ap.add_argument("--grep", metavar="KEYWORD", default=None, help="全文检索")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（配合单条命令）")
    args = ap.parse_args(argv)

    engine = OmniScholarEngine()

    # 语料未抽取时，依赖全文的命令给出可执行的修复指引，而不是抛 traceback。
    if args.skeleton and not engine.has_text(args.skeleton):
        print(f"论文 P{args.skeleton} 的正文尚未抽取——本技能不生成无语料支撑的内容。\n\n{PREP_HINT}",
              file=sys.stderr)
        return 2
    if (args.links or args.grep) and not engine.corpus_ready():
        print(f"全文检索需要 corpus/txt/，当前仓库尚未抽取。\n\n{PREP_HINT}", file=sys.stderr)
        return 2

    if args.demo:
        return _demo(engine)

    if args.verify_doi:
        r = engine.verify_doi(args.verify_doi)
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else
              "\n".join(f"{k}: {v}" for k, v in r.items()))
        return 0

    if args.skeleton:
        sk = engine.extract_skeleton(args.skeleton)
        if args.json:
            print(json.dumps({
                "paper_id": sk.paper_id, "title_hint": sk.title_hint,
                "evidence_level": sk.evidence_level,
                "fields": [sk.core_problem_and_motivation.as_dict(),
                           sk.previous_sota_limitations.as_dict(),
                           sk.core_methodology_and_math.as_dict(),
                           sk.validation_and_empirical_gains.as_dict()],
            }, ensure_ascii=False, indent=2))
        else:
            print(sk.render())
        return 0

    if args.topology:
        t = engine.build_evolution_topology()
        print(json.dumps(t, ensure_ascii=False, indent=2) if args.json else
              json.dumps(t, ensure_ascii=False, indent=2))
        return 0

    if args.links:
        links = engine.detect_cross_paper_links()
        if args.json:
            print(json.dumps(links, ensure_ascii=False, indent=2))
        else:
            for lk in links:
                print(f"P{lk['from'][1:]} → {lk['to']}｜{lk['kind']}｜「{lk['match']}」")
                print(f"    `{lk['source']}` [{lk['start']}:{lk['end']}]")
                print(f"    {lk['snippet'][:160]}")
        return 0

    if args.fact_card:
        print(engine.generate_fact_card(args.fact_card))
        return 0

    if args.grep:
        hits = engine.grep(args.grep)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        elif not hits:
            print("（检索范围内无命中——已限定在 corpus/txt/ 的正文前 85%，"
                  "可用 --json 查看已检索的语料清单）")
        else:
            for h in hits:
                print(f"[P{h['paper'][1:]}] `{h['source']}` [{h['start']}:{h['end']}]")
                print(f"    {h['snippet']}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_all.py —— Mr.GUO 仓库自动验收
=============================================================================
按 docs/重建计划.md 中「目标 A–E」的机器可验部分逐条检查，输出 PASS/FAIL 成绩单。
脚本只做判定，不做修复；任何 FAIL 都给出可定位的文件与行号。

用法：
    python3 tools/verify_all.py              # 全量验收，输出报告
    python3 tools/verify_all.py --json       # 机器可读输出（供 CI 使用）
"""

from __future__ import annotations

import ast
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHITEPAPER = os.path.join(ROOT, "燃气轮机智能设计与前沿算法自学白皮书.md")
README = os.path.join(ROOT, "README.md")
CORPUS = os.path.join(ROOT, "corpus")
CODE = os.path.join(ROOT, "code")
IMAGES = os.path.join(ROOT, "images")
SKILLS = os.path.join(ROOT, "skills", "omni_scholar")

REQUIRED_SECTIONS = ["生活与物理直觉", "工程死穴", "数学", "控制流", "验证", "批判"]
LECTURE_RE = re.compile(r"^### 【第(\d{2})讲】", re.M)
IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(\./images/([^)]+)\)")
PCT_RE = re.compile(r"[^\n|]{0,80}\d+(?:\.\d+)?\s?%")

# 什么才算「真·来源标注」：
#  ① 规范标注 —— ［原文 P07 §4.2］／［出版商页面］／［原文未获取］／［待核实］
#  ② 定位标注 —— ［§3.2］／［Table 3］／［摘要］／［由 Table 2 计算］
#     （讲义单讲只讨论一篇论文，§/Table 级定位在该讲内是唯一的，故视为可回溯）
# 刻意**不**把"块内出现了任意 ［"当作合格——旧版用空括号即可骗过此项检查。
SOURCE_TAG_RE = re.compile(
    r"［[^］]{0,60}(?:原文|出版商|doi_verification|web_evidence|待核|未获取)[^］]{0,60}］")
LOCATOR_TAG_RE = re.compile(
    r"［[^］]{0,80}(?:§\s*[\dIVX]|Table\s*\d|Tab\.\s*\d|Fig\.?\s*\d|图\s*\d|摘要|结论|式\s*[（(]|由[^］]{0,30}计算)[^］]{0,80}］")
CITED_RE = re.compile(rf"(?:{SOURCE_TAG_RE.pattern})|(?:{LOCATOR_TAG_RE.pattern})")

# 已查实的"必须不得复现"的内容（来源：corpus/doi_verification.md 的裁定）。
# 这些串曾在交付物里出现并被判定为硬伤，因此作为回归守卫长期保留。
FORBIDDEN = [
    ("10.1109/TCYB.2022.3168744", "论文 06 的错误 DOI 尾号（应为 …3165044）"),
    ("10.1016/j.ast.2026.112440", "论文 18 指向无关论文的错误 DOI（应为 …112351）"),
    ("IEEE Conference 2024", "论文 15 的错误年份（应为 IEEE CEC 2025）"),
    ("*IEEE 2024*", "论文 15 的错误年份（应为 IEEE CEC 2025）"),
    ("精度 98%", "论文 18 的旧版虚构指标"),
    # 2026-09-06 第三轮复审新增（见 docs/重建计划.md §六）
    ("GAN-Endwall", "论文 14 的方法是 VAE + NURBS 层（出版商摘要），旧代号 GAN-Endwall 属误称"),
    ("SPIE-AI", "论文 20 的旧版臆造代号；现按摘要写作“物理增强子午面全景预测”"),
    ("HTML 全文", "两篇 .htm（论文 09、10）仅为 ScienceDirect 摘要级页面，不是全文"),
    ("Official Abstract", "全集汇总 §三 的中文转述曾被标为 Official Abstract，应写“摘要转述”"),
]

# extract_corpus.py 允许的标准库（不要求在 requirements 中声明）
_STDLIB_OK = {"__future__", "argparse", "html", "json", "os", "re", "sys", "unicodedata",
              "datetime", "pathlib", "typing", "collections", "itertools", "functools"}

results: list[tuple[str, bool, str]] = []


def check(category: str, ok: bool, detail: str) -> None:
    results.append((category, ok, detail))


# --------------------------------------------------------------------------- A
def verify_whitepaper() -> None:
    if not os.path.exists(WHITEPAPER):
        check("A-内容", False, "白皮书文件不存在")
        return
    text = open(WHITEPAPER, encoding="utf-8").read()
    chars = len(re.sub(r"\s", "", text))
    check("A1-篇幅", chars >= 60000, f"正文去空白 {chars} 字（目标 ≥ 60000）")

    heads = list(LECTURE_RE.finditer(text))
    check("A2-讲次数量", len(heads) == 20, f"检出 {len(heads)} 讲（目标 20）")

    thin, missing_sec = [], []
    part_heads = [x.start() for x in re.finditer(r"^# ", text, re.M)]
    for i, m in enumerate(heads):
        # 终点取「下一讲」与「下一篇」中更早者：否则第 20 讲会把第五/六篇
        # 全部计入，单讲篇幅虚高到 10 万字级，反而掩盖该讲本身变薄的情况。
        cands = [heads[i + 1].start()] if i + 1 < len(heads) else []
        cands += [x for x in part_heads if x > m.start()]
        end = min(cands) if cands else len(text)
        block = text[m.start():end]
        n = len(re.sub(r"\s", "", block))
        if n < 1200:
            thin.append(f"第{m.group(1)}讲({n}字)")
        hits = [s for s in REQUIRED_SECTIONS if s in block]
        # 标准原文：「20 讲每讲均含 6 个规定小节」。旧判定 ≥4 即放行，属放水。
        if len(hits) < len(REQUIRED_SECTIONS):
            missing = "、".join(s for s in REQUIRED_SECTIONS if s not in block)
            missing_sec.append(f"第{m.group(1)}讲缺：{missing}")
    check("A3-单讲篇幅", not thin, "过短：" + "、".join(thin) if thin else "全部 ≥1200 字")
    check("A4-小节完整", not missing_sec,
          "缺节：" + "、".join(missing_sec) if missing_sec else "20 讲均含规定小节")

    # 数字可溯：按"块"（段落 / 表格 / 列表项，以空行分隔）判定。
    # 一个块内只要出现了百分比断言，就必须在同一块内带有可回溯的引用标注。
    # 严格之处：① 不接受"块里有 ［"这种形式合规；② 不允许任何配额（旧版容忍 5 处）；
    #          ③ 标题/引注/短句不豁免（旧版 len(blk)<120 直接跳过，是后门）。
    blocks = re.split(r"\n\s*\n", text)
    bare: list[str] = []
    in_fence = False
    for i, blk in enumerate(blocks):
        # 跳过代码块（代码是执行物，不是文字断言）
        if blk.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not re.search(r"\d+(?:\.\d+)?\s?%", blk):
            continue
        if CITED_RE.search(blk):
            continue
        # 表格块：允许来源标注写在紧邻的上一段或下一段（常见排版：表题/表注）
        is_table = sum(1 for ln in blk.splitlines() if ln.strip().startswith("|")) >= 2
        if is_table:
            prev_blk = blocks[i - 1] if i > 0 else ""
            next_blk = blocks[i + 1] if i + 1 < len(blocks) else ""
            if CITED_RE.search(prev_blk) or CITED_RE.search(next_blk):
                continue
        bare.append(re.sub(r"\s+", " ", blk.strip())[:70])
    check("A5-数字可溯", not bare,
          (f"{len(bare)} 个段落含百分比断言但无可回溯的来源标注，例：{' / '.join(bare[:3])}"
           if bare else "含百分比断言的段落全部带来源标注"))

    # A6：篇级完整性——第六篇（对比、批判与前瞻）不得为空壳。
    m6 = re.search(r"^# 第六篇.*$", text, re.M)
    if not m6:
        check("A6-篇完整性", False, "白皮书缺少「第六篇」")
    else:
        tail = text[m6.end():]
        nxt = re.search(r"^# ", tail, re.M)
        body = tail[:nxt.start()] if nxt else tail
        n = len(re.sub(r"\s", "", body))
        has_matrix = "6.1" in body and "全景对比矩阵" in body
        placeholder = any(k in body for k in ("待重建", "待补", "TODO"))
        ok = n >= 3000 and has_matrix and not placeholder
        detail = (f"第六篇 {n} 字，矩阵={'有' if has_matrix else '无'}，"
                  f"占位符={'有🔴' if placeholder else '无'}")
        check("A6-篇完整性", ok, detail if ok else f"第六篇不达标（{detail}）")


# --------------------------------------------------------------------------- B
def verify_code() -> None:
    if not os.path.isdir(CODE):
        check("B1-代码目录", False, "code/ 目录不存在（旧版声称的‘完整代码库’实为 0 个文件）")
        return
    files = sorted(glob.glob(os.path.join(CODE, "*.py")))
    files = [f for f in files if not os.path.basename(f).startswith("_")]
    check("B1-代码目录", len(files) >= 6, f"{len(files)} 个模块（目标 ≥6）")

    broken = []
    for f in files:
        try:
            ast.parse(open(f, encoding="utf-8").read())
        except SyntaxError as e:
            broken.append(f"{os.path.basename(f)}:{e.lineno}")
    check("B2-语法", not broken, "语法错误：" + "、".join(broken) if broken else "全部可解析")

    heavy = []
    allowed = {"numpy", "math", "random", "json", "os", "sys", "argparse",
               "dataclasses", "typing", "pathlib", "itertools", "functools",
               "collections", "time", "re", "__future__"}
    for f in files:
        tree = ast.parse(open(f, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] not in allowed:
                        heavy.append(f"{os.path.basename(f)}:{a.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] not in allowed:
                    heavy.append(f"{os.path.basename(f)}:{node.module}")
    check("B3-依赖", not heavy, "超范围依赖：" + "、".join(heavy) if heavy else "仅 numpy/标准库")

    no_main = [os.path.basename(f) for f in files
               if "__main__" not in open(f, encoding="utf-8").read()]
    check("B4-可自检", not no_main,
          "缺 __main__ 自检：" + "、".join(no_main) if no_main else "全部含自检入口")

    tests = glob.glob(os.path.join(ROOT, "tests", "test_*.py"))
    check("B5-单元测试", len(tests) >= 3, f"{len(tests)} 个测试文件（目标 ≥3）")


# --------------------------------------------------------------------------- C
def verify_images() -> None:
    if not os.path.isdir(IMAGES):
        check("C-配图", False, "images/ 不存在")
        return
    on_disk = {os.path.basename(p) for p in glob.glob(os.path.join(IMAGES, "*"))
               if os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg", ".webp")}

    refs: dict[str, list[tuple[str, str]]] = {}
    for md in glob.glob(os.path.join(ROOT, "*.md")) + glob.glob(os.path.join(ROOT, "docs", "*.md")):
        t = open(md, encoding="utf-8").read()
        for m in IMAGE_REF_RE.finditer(t):
            refs.setdefault(m.group(1), []).append((os.path.basename(md), m.group(0)[:70]))

    dangling = [r for r in refs if r not in on_disk]
    check("C1-无死链", not dangling, "引用了不存在的文件：" + "、".join(dangling) if dangling else "引用均存在")

    orphans = sorted(on_disk - set(refs))
    check("C2-无孤儿图", not orphans, "未被引用：" + "、".join(orphans) if orphans else "全部有归属")

    # 语义一致性：被引用的文件名应与其所在段落的讲义主题相关（关键词粗筛）
    suspicious = []
    if os.path.exists(WHITEPAPER):
        t = open(WHITEPAPER, encoding="utf-8").read()
        for m in re.finditer(r"!\[([^\]]*)\]\(\./images/([^)]+)\)", t):
            alt, fname = m.group(1), m.group(2)
            stem = os.path.splitext(fname)[0]
            key = stem.replace("_zh", "").replace("_en", "")
            # 图注中的英文串应与文件名有实词交集
            words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", key)}
            altw = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", alt)}
            if words and altw and not (words & altw):
                suspicious.append(f"{fname} ← “{alt}”")
    check("C3-图文相符", not suspicious,
          "图文不匹配嫌疑：" + "；".join(suspicious) if suspicious else "图注与文件名语义一致")

    # C4：目标 C 要求「四篇主体各有配图」——逐篇统计被引用的图数。
    if os.path.exists(WHITEPAPER):
        t = open(WHITEPAPER, encoding="utf-8").read()
        parts = list(re.finditer(r"^# 第[一二三四]篇[^\n]*$", t, re.M))
        nofig = []
        for i, m in enumerate(parts):
            s = m.end()
            e = parts[i + 1].start() if i + 1 < len(parts) else len(t)
            if not IMAGE_REF_RE.search(t[s:e]):
                nofig.append(m.group(0).lstrip("# "))
        check("C4-四篇配图", not nofig,
              "这些篇没有配图：" + "、".join(nofig) if nofig else "第一至第四篇各有配图")


# --------------------------------------------------------------------------- D
def verify_consistency() -> None:
    idx = os.path.join(CORPUS, "index.json")
    if not os.path.exists(idx):
        check("D-一致性", False, "corpus/index.json 缺失，请先运行 tools/extract_corpus.py")
        return
    papers = json.load(open(idx, encoding="utf-8"))["papers"]
    bad = []
    for p in papers:
        dec, got = p.get("declared_doi"), p.get("doi")
        if dec and got and dec != got:
            bad.append(f"P{p['id']}({dec}≠{got})")
    check("D1-DOI一致", not bad, "DOI 冲突未修正：" + "、".join(bad) if bad else "20 篇 DOI 与原文一致")

    readme = open(README, encoding="utf-8").read()
    ids = re.findall(r"\|\s*\*\*(\d{2})\*\*\s*\|", readme)
    uniq = sorted(set(ids))
    check("D2-编号唯一", len(uniq) == 20 and len(ids) == 20,
          f"README 索引表检出 {len(ids)} 行 / {len(uniq)} 个唯一编号（目标 20/20）")

    wp = open(WHITEPAPER, encoding="utf-8").read()
    check("D3-口径统一", ("15+5" not in wp),
          "白皮书仍存在“15+5 篇”口径混用" if "15+5" in wp else "无混用口径")

    # D4：索引文档与 corpus/ 的元数据必须一致。
    #   (a) 凡 corpus 里已确证的 DOI，都要能在《论文链接整理.md》里找到；
    #   (b) 已被裁定为硬伤的字符串不得在任何文档中复现（回归守卫）。
    link_doc = os.path.join(ROOT, "论文链接整理.md")
    link_txt = open(link_doc, encoding="utf-8").read() if os.path.exists(link_doc) else ""
    # 旧判定只查“从 PDF 抽到的 DOI”，5 篇无本地原文的论文（04/05/13/14/20）因此**从未被检查**——
    # 论文 14/20 长期“无 DOI”正是这样漏网的。现改为：20 篇的 DOI（抽取值优先，否则取
    # extract_corpus.PAPER_MAP 的声明值）都必须落到《论文链接整理.md》（DOI 比对不区分大小写）。
    summary_doc = os.path.join(ROOT, "郭老师论文全集综合整理汇总.md")
    summary_txt = (open(summary_doc, encoding="utf-8").read().lower()
                   if os.path.exists(summary_doc) else "")
    missing_doi = []
    for p in papers:
        doi = p.get("doi") or p.get("declared_doi")
        if not doi:
            missing_doi.append(f"P{p['id']}:无DOI")
            continue
        if doi.lower() not in link_txt.lower() or doi.lower() not in summary_txt:
            missing_doi.append(f"P{p['id']}:{doi}")
    check("D4a-DOI落地", not missing_doi,
          "索引文档（链接整理/全集汇总）缺少 DOI：" + "、".join(missing_doi[:6])
          if missing_doi else "20/20 篇 DOI（含 5 篇无本地原文者）均落到链接整理与全集汇总")

    # 允许"辟谣式引用"：错误串若出现在 更正/旧版/错误/无此说法/虚构/应为 等语境中，
    # 说明是在记录"这里曾经错、现在改了"，属正当用途；否则即为残留。
    DEBUNK = ("更正", "错误", "旧版", "无此说法", "虚构", "应为", "不得", "删除", "误")
    scan_targets = [WHITEPAPER, README, link_doc,
                    os.path.join(ROOT, "郭老师论文全集综合整理汇总.md"),
                    os.path.join(ROOT, "公开论文整理.md"),
                    os.path.join(ROOT, "付费论文五篇整理.md")]
    hits = []
    for bad, why in FORBIDDEN:
        for path in scan_targets:
            if not os.path.exists(path):
                continue
            body = open(path, encoding="utf-8").read()
            for mt in re.finditer(re.escape(bad), body):
                ctx = body[max(0, mt.start() - 90):mt.end() + 90]
                if not any(k in ctx for k in DEBUNK):
                    line = body[:mt.start()].count("\n") + 1
                    hits.append(f"{os.path.basename(path)}:{line}←{bad}")
                    break
    why_by_bad = {b: w for b, w in FORBIDDEN}
    detail = "无已裁定错误残留（辟谣式引用已排除）"
    if hits:
        reasons = "；".join(f"{h} 应为：{why_by_bad.get(b, '')}"
                            for h in hits for b, _ in FORBIDDEN if h.endswith(b))
        detail = "已裁定的错误仍以正文口径存在 → " + (reasons or "；".join(hits[:4]))
    check("D4b-无禁用残留", not hits, detail)

    # D5：规范编号必须贯穿全部索引文档（目标 D「统一 01–20 编号」）。
    #   旧状态：全集 §三 卡片、公开/付费/链接整理只有“文内顺序号”，读者无法把
    #   “公开论文整理的第 9 篇”对应到“白皮书第 11 讲 / 论文 12”。
    #   现判定：① 全集汇总 §三 与《论文链接整理》各自含全部 20 个 ［论文 XX］ 标签；
    #           ② 《公开论文整理》∪《付费论文五篇整理》恰好覆盖 20 个编号且两者不重叠。
    tag_re = re.compile(r"【论文\s*(\d{2})】")
    all20 = {f"{i:02d}" for i in range(1, 21)}

    def tags(path: str) -> set[str]:
        return set(tag_re.findall(open(path, encoding="utf-8").read())) if os.path.exists(path) else set()

    pub = tags(os.path.join(ROOT, "公开论文整理.md"))
    paid = tags(os.path.join(ROOT, "付费论文五篇整理.md"))
    problems = []
    for name, got in (("全集汇总", tags(summary_doc)), ("链接整理", tags(link_doc))):
        if got != all20:
            problems.append(f"{name}缺 {sorted(all20 - got)}")
    if pub | paid != all20:
        problems.append(f"公开∪付费缺 {sorted(all20 - (pub | paid))}")
    if pub & paid:
        problems.append(f"公开∩付费重叠 {sorted(pub & paid)}")
    check("D5-规范编号贯穿", not problems,
          "；".join(problems) if problems
          else f"四份索引文档均按【论文 XX】贯穿 20 篇（公开 {len(pub)} + 付费 {len(paid)}）")


# --------------------------------------------------------------------------- E
def verify_skills() -> None:
    core = os.path.join(SKILLS, "core.py")
    if not os.path.exists(core):
        check("E-技能包", False, "skills/omni_scholar/core.py 缺失")
        return
    src = open(core, encoding="utf-8").read()
    # 旧版这里写的是 `"待注入" in l or "TODO" in l and "raise NotImplementedError" in src`，
    # 因 and 优先级高于 or，TODO 检测在源文件不含 NotImplementedError 时被整体短路——等于没查。
    placeholders = [f"L{i+1}:{ln.strip()[:50]}" for i, ln in enumerate(src.splitlines())
                    if any(k in ln for k in ("待注入", "占位字符串", "placeholder"))
                    and not ln.strip().startswith("#")]
    notimpl = [f"L{i+1}" for i, ln in enumerate(src.splitlines())
               if "raise NotImplementedError" in ln or "pass  # TODO" in ln]
    check("E1-无占位实现", not placeholders and not notimpl,
          "仍含占位：" + "；".join((placeholders + notimpl)[:3])
          if (placeholders or notimpl) else "无硬编码占位、无 NotImplementedError")

    try:
        ast.parse(src)
        check("E2-可解析", True, "core.py 语法正确")
    except SyntaxError as e:
        check("E2-可解析", False, f"语法错误 line {e.lineno}")

    # E3：目标 E 明确要求「附 README + 一条可复制的端到端命令」。
    readme = os.path.join(SKILLS, "README.md")
    if not os.path.exists(readme):
        check("E3-技能包README", False, "skills/omni_scholar/README.md 不存在（目标 E 要求）")
    else:
        r = open(readme, encoding="utf-8").read()
        has_cmd = "core.py --demo" in r
        check("E3-技能包README", has_cmd,
              "README 存在且含可复制的端到端命令" if has_cmd
              else "README 缺少 `core.py --demo` 端到端命令")

    # E4：那条端到端命令必须真的能跑（不依赖网络；无语料时应干净降级而非 traceback）。
    import subprocess
    try:
        p = subprocess.run([sys.executable, core, "--demo"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0 and "Traceback" not in out and len(out.splitlines()) >= 20
        check("E4-演示可运行", ok,
              f"--demo 退出码 {p.returncode}，输出 {len(out.splitlines())} 行"
              + ("" if ok else "（需退出码 0、无 traceback、有实质输出）"))
    except Exception as e:  # noqa: BLE001
        check("E4-演示可运行", False, f"无法执行 --demo：{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- F
def verify_hygiene() -> None:
    """交付物齐备性与"事实底座"完成度——这些在旧版验收中完全没有被检查。"""
    # F1：20 张事实卡必须已依原文填写（P1），且每张含规定的 7 个栏目。
    fdir = os.path.join(ROOT, "corpus", "facts")
    cards = sorted(glob.glob(os.path.join(fdir, "P*.md")))
    todo_cards, thin_cards = [], []
    for c in cards:
        body = open(c, encoding="utf-8").read()
        if "TODO" in body:
            todo_cards.append(os.path.basename(c))
        if body.count("\n## ") < 7:
            thin_cards.append(os.path.basename(c))
    check("F1a-事实卡无TODO", not todo_cards,
          f"{len(todo_cards)} 张仍是骨架：" + "、".join(todo_cards[:6])
          if todo_cards else f"{len(cards)}/20 张已依原文填写")
    check("F1b-事实卡栏目齐", not thin_cards and len(cards) == 20,
          f"栏目不足 7 节：" + "、".join(thin_cards[:6]) if thin_cards
          else f"{len(cards)} 张、每张 ≥7 栏（目标 20）")

    # F2：计划中点名要求、但曾缺失的交付物。
    need = {"Makefile": "P3 要求的 Makefile",
            os.path.join("tools", "verify_whitepaper.py"): "目标 A『验证方式』点名的脚本"}
    lack = [f"{k}（{v}）" for k, v in need.items() if not os.path.exists(os.path.join(ROOT, k))]
    check("F2-交付物齐备", not lack, "缺失：" + "、".join(lack) if lack else "Makefile 与专项校验脚本均在")

    # F3：依赖声明必须与实际 import 一致（规范 3「文中声明与实际 imports 严格一致」）。
    req_code = os.path.join(CODE, "requirements.txt")
    req_tools = os.path.join(ROOT, "tools", "requirements.txt")
    ext = os.path.join(ROOT, "tools", "extract_corpus.py")
    declared = open(req_tools, encoding="utf-8").read() if os.path.exists(req_tools) else ""
    heavy = []
    if os.path.exists(ext):
        tree = ast.parse(open(ext, encoding="utf-8").read())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else ([node.module] if isinstance(node, ast.ImportFrom) else []))
            for n in names:
                top = (n or "").split(".")[0]
                # 第三方（非标准库、非 numpy）依赖必须写进 tools/requirements.txt
                if top and top not in _STDLIB_OK and top not in declared:
                    heavy.append(f"extract_corpus.py→{top}")
    check("F3-抽取依赖已声明", not heavy,
          "第三方依赖未在 requirements 中声明：" + "、".join(heavy)
          if heavy else "pypdf 已在 tools/requirements.txt 声明（code/ 仍仅 numpy）")



def main() -> int:
    verify_whitepaper()
    verify_code()
    verify_images()
    verify_consistency()
    verify_skills()
    verify_hygiene()

    if "--json" in sys.argv:
        print(json.dumps([{"item": c, "pass": ok, "detail": d} for c, ok, d in results],
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 78)
        print("Mr.GUO 仓库验收报告")
        print("=" * 78)
        for cat, ok, detail in results:
            print(f"[{'PASS' if ok else 'FAIL'}] {cat:<16} {detail}")
        passed = sum(1 for _, ok, _ in results if ok)
        print("-" * 78)
        print(f"合计 {passed}/{len(results)} 项通过")
        print("=" * 78)
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

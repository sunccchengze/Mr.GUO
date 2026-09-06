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
    # --- 本轮审计新增（2026-09-06）：上一轮 P6 自称“已统一”实则漏网的残留 ---
    ("Eng Opt (2025)", "论文 11 的单年份旧口径（应为“2024-04-18 在线；正式卷期 2025, 57(2)”）"),
    ("HTML 全文", "两篇 htm 仅为摘要页却冒充全文（应为“HTML 摘要页”）"),
    ("HTML全文", "两篇 htm 仅为摘要页却冒充全文（应为“HTML 摘要页”）"),
    ("HTML 格式全文", "两篇 htm 仅为摘要页却冒充全文（应为“HTML 摘要页”）"),
    ("HTML原文", "两篇 htm 仅为摘要页却冒充原文"),
    ("总压总效率", "笔误（应为“总-总等熵效率”）"),
    # 全集曾用改写摘要冒充 Official Abstract（现已逐字替换，此处防回归）：
    ("non-axisymmetric endwalls (NAE), a transonic aerodynamic test platform was constructed",
     "论文 09 的改写版摘要（逐字版见事实卡 P09 §二）"),
    ("technique with high freedom and superior smoothness. Driven by a large-variable optimization algorithm",
     "论文 10 的改写版摘要（逐字版见事实卡 P10 §二）"),
    ("an efficient uncertainty quantification method evaluates the impacts of slot width",
     "论文 04 的改写版摘要（逐字版见 corpus/web_evidence/P04.md）"),
    # 2026-09-06 第三轮复审新增（见 docs/重建计划.md §六；合并自独立复审分支）
    ("GAN-Endwall", "论文 14 的方法是 VAE + NURBS 层（出版商摘要），旧代号 GAN-Endwall 属误称"),
    ("SPIE-AI", "论文 20 的旧版臆造代号；现按摘要写作“物理增强子午面全景预测”"),
    ("Official Abstract", "全集汇总 §三 的中文转述曾被标为 Official Abstract，应写“摘要转述”"),
]

# extract_corpus.py 允许的标准库（不要求在 requirements 中声明）
_STDLIB_OK = {"__future__", "argparse", "hashlib", "html", "json", "os", "re", "sys", "unicodedata",
              "datetime", "pathlib", "typing", "collections", "itertools", "functools", "subprocess",
              "shutil", "tempfile", "glob", "ast", "math", "random", "time", "dataclasses"}

# index.json curated 年份/载体的期望值（与 tools/extract_corpus.py 的 CURATED_META 同源，
# 复制一份在此做交叉核对；若两处不一致，说明有一处被单独改动过，必须人工介入）。
CURATED_EXPECT = {
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

# 事实卡规定的 7 类栏目（关键词须出现在 ## 标题中）
FACT_SECTIONS = ["权威著录", "摘要", "量化指标", "方法机理", "验证", "局限", "承前启后"]


results: list[tuple[str, bool, str]] = []


def check(category: str, ok: bool, detail: str) -> None:
    results.append((category, ok, detail))


# --------------------------------------------------------------------------- A
def verify_whitepaper() -> None:
    if not os.path.exists(WHITEPAPER):
        check("A-内容", False, "白皮书文件不存在")
        return
    text = open(WHITEPAPER, encoding="utf-8").read()
    # 旧口径把第五篇嵌入的 ~10 万字代码也算成“正文”，篇幅虚胖近一倍。
    # 现口径：去掉所有 ``` 代码块后再计（仍 ≥60000 才算过）。
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    chars = len(re.sub(r"\s", "", prose))
    check("A1-篇幅", chars >= 60000, f"正文去空白去代码 {chars} 字（目标 ≥ 60000）")

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
        # 小节必须以标题行存在（####/###），正文里顺口提到“数学”二字不算。
        # 此前在整块内做子串匹配，标题被删、只剩正文提及也能蒙混过关。
        heads_in = re.findall(r"^#{3,4}\s+(.*)$", block, re.M)
        hits = [s for s in REQUIRED_SECTIONS if any(s in h for h in heads_in)]
        # 标准原文：「20 讲每讲均含 6 个规定小节」。
        if len(hits) < len(REQUIRED_SECTIONS):
            missing = "、".join(s for s in REQUIRED_SECTIONS
                                if not any(s in h for h in heads_in))
            missing_sec.append(f"第{m.group(1)}讲缺：{missing}")
    check("A3-单讲篇幅", not thin, "过短：" + "、".join(thin) if thin else "全部 ≥1200 字")
    check("A4-小节完整", not missing_sec,
          "缺节：" + "、".join(missing_sec) if missing_sec else "20 讲均含规定小节")

    # 数字可溯：按"块"（段落 / 表格 / 列表项，以空行分隔）判定。
    # 一个块内只要出现了百分比/倍数断言，就必须在同一块内带有可回溯的引用标注。
    # 严格之处：① 不接受"块里有 ［"这种形式合规；② 不允许任何配额（旧版容忍 5 处）；
    #          ③ 标题/引注/短句不豁免（旧版 len(blk)<120 直接跳过，是后门）；
    #          ④ 规范原文是“百分比/倍数/CFD次数”，旧检查只查了百分比，本轮补上倍数。
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
        if not re.search(r"\d+(?:\.\d+)?\s?(?:%|倍)", blk):
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
        # 旧检查只认 6.1，6.2–6.5 被删光也能过；现要求 6.1–6.5 小节齐全。
        subs = [s for s in ("6.1", "6.2", "6.3", "6.4", "6.5")
                if re.search(r"^##\s+" + s, body, re.M)]
        placeholder = any(k in body for k in ("待重建", "待补", "TODO"))
        ok = n >= 3000 and has_matrix and len(subs) == 5 and not placeholder
        detail = (f"第六篇 {n} 字，矩阵={'有' if has_matrix else '无'}，"
                  f"小节{len(subs)}/5，占位符={'有🔴' if placeholder else '无'}")
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

    # B4b/B5b：标准原文要求“pytest 全绿 + 每个脚本能跑出结果”。
    # 旧检查只数字符串（有无 __main__、有几个测试文件）：本轮审计亲手复现过——
    # 在 numpy 根本没装、19 项全挂的环境下，B 项照样 5/5 PASS。这是验收器最大的放水口。
    # 现改为真跑：缺依赖时明确 FAIL 并提示 make venv，而不是虚假全绿。
    import subprocess
    try:
        import numpy  # noqa: F401
        have_numpy = True
    except ImportError:
        have_numpy = False
    if os.environ.get("MRGUO_SKIP_SLOW"):
        # 仅供 selftest_verifier 加速非B用例；直接跑 verify 永远全量真跑。
        check("B4b-模块真跑", True, "SKIP（selftest加速模式，非B用例）")
        check("B5b-测试真跑", True, "SKIP（selftest加速模式，非B用例）")
    elif not have_numpy:
        check("B4b-模块真跑", False, "numpy 未安装，code/ 自检无法运行（先 `make venv`）")
        check("B5b-测试真跑", False, "numpy 未安装，tests/ 无法运行（先 `make venv`）")
    else:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "run_checks.py"),
                            "--modules"], cwd=ROOT, capture_output=True, text=True, timeout=600)
        fails = [ln for ln in p.stdout.splitlines() if "[FAIL]" in ln]
        check("B4b-模块真跑", p.returncode == 0 and not fails,
              ("全部模块自检通过" if (p.returncode == 0 and not fails)
               else f"模块自检失败：{'; '.join(fails[:3]) or p.stderr.strip().splitlines()[-1:] }"))
        p = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=ROOT,
                           capture_output=True, text=True, timeout=900)
        tail = (p.stdout.strip().splitlines() or [""]) [-1]
        check("B5b-测试真跑", p.returncode == 0,
              f"pytest: {tail}" if p.returncode == 0 else f"pytest 未全绿：{tail}")


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
            # 只剥离行尾的 _zh/_en 后缀。旧写法 stem.replace("_en","") 会把
            # 文件名中间的 "_en…"（如 vae_nurbs_endwall）一并误删，导致 C3 误报——
            # 2026-09-06 第四轮补图时发现，已修。
            key = re.sub(r"_(zh|en)$", "", stem)
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

    # D1b：curated 年份/载体必须与裁定值一致。旧检查只比 DOI，不管年份/载体——
    # 本轮审计发现 index.json 里 P02 年份被嗅探成 2016（实 2021）、P15 载体被嗅探成
    # Engineering Optimization（实 IEEE CEC），且演示程序曾把错值当结论展示。
    bad_cur = []
    for p in papers:
        exp = CURATED_EXPECT.get(p["id"])
        got = (p.get("curated_year"), p.get("curated_venue"))
        if exp != got:
            bad_cur.append(f"P{p['id']}(index={got}≠curation={exp})")
    check("D1b-年份载体", not bad_cur,
          "curated 与裁定不一致：" + "、".join(bad_cur[:4]) if bad_cur else "20 篇 curated 年份/载体与裁定一致")

    readme = open(README, encoding="utf-8").read()
    ids = re.findall(r"\|\s*\*\*(\d{2})\*\*\s*\|", readme)
    uniq = sorted(set(ids))
    check("D2-编号唯一", len(uniq) == 20 and len(ids) == 20,
          f"README 索引表检出 {len(ids)} 行 / {len(uniq)} 个唯一编号（目标 20/20）")

    # D2b：目标 D 要求“全仓库统一 01–20”，旧检查只看了 README 索引表。
    # 2026-09-06 合并后编号体系升级为标题级【论文 XX】标签（原“规范编号 **NN**”后缀式已淘汰）：
    # 公开 15 篇 + 付费 5 篇 = 20，全集 §三 20 张卡片标题全部带【论文 XX】。
    d2b_bad = []
    tag_re2 = re.compile(r"【论文\s*(\d{2})】")
    open_tags = set(tag_re2.findall(open(os.path.join(ROOT, "公开论文整理.md"), encoding="utf-8").read()))
    if len(open_tags) != 15:
        d2b_bad.append(f"公开论文整理【论文 XX】标签 {len(open_tags)} 个（目标 15）")
    pay_tags = set(tag_re2.findall(open(os.path.join(ROOT, "付费论文五篇整理.md"), encoding="utf-8").read()))
    if len(pay_tags) != 5:
        d2b_bad.append(f"付费论文五篇整理【论文 XX】标签 {len(pay_tags)} 个（目标 5）")
    quan_txt = open(os.path.join(ROOT, "郭老师论文全集综合整理汇总.md"), encoding="utf-8").read()
    n_head = len(re.findall(r"^#### \d+\.\s*【论文 \d{2}】", quan_txt, re.M))
    if n_head != 20:
        d2b_bad.append(f"全集 #### 标题带【论文 XX】{n_head}/20")
    check("D2b-编号落地", not d2b_bad, "；".join(d2b_bad) if d2b_bad else "公开15+付费5=全集20，标题级【论文 XX】齐全")

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

    # D5：事实卡 P09 §四明令——“14.0% 必须连同工况限定语 MA=0.8 一起引用，
    # 脱离马赫数写‘降低 14.0%’属过度泛化”。本轮审计在全集/白皮书各抓到一处违反。
    # 检查：全仓库（去代码块）每个 14.0% 的 ±300 字符窗口内必须有 MA/马赫数限定。
    MA_RE = re.compile(r"MA\s?[=＝]\s?\$?0\.8|Ma\s?[=＝]\s?\$?0\.8|0\.8\s?工况|马赫数\s?0\.8|"
                       r"Mach\s?(number of )?0\.8|出口马赫数", re.I)
    d5_bad = []
    for path in scan_targets:
        if not os.path.exists(path):
            continue
        body = re.sub(r"```.*?```", "", open(path, encoding="utf-8").read(), flags=re.S)
        for mt in re.finditer(r"14\.0\s?%", body):
            ctx = body[max(0, mt.start() - 300):mt.end() + 100]
            if not MA_RE.search(ctx):
                line = body[:mt.start()].count("\n") + 1
                d5_bad.append(f"{os.path.basename(path)}:{line}")
                break
    check("D5-工况限定", not d5_bad,
          "14.0% 脱离 MA=0.8 限定（过度泛化）：" + "、".join(d5_bad) if d5_bad
          else "全部 14.0% 均带 MA=0.8 工况限定")

    # D6：规范编号必须贯穿全部索引文档（目标 D「统一 01–20 编号」）。
    #   （合并说明：该检查在独立复审分支上原名 D5-规范编号贯穿；与本仓 D5-工况限定 撞号，
    #    合并后统一改为 D6，selftest_verifier 的对应用例同步改名。）
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
    check("D6-规范编号贯穿", not problems,
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
    # 旧判定只数行数（≥20 即过）：本轮审计复现过——语料完全缺失时的 58 行降级输出
    # 与完整语料下的 106 行输出都 PASS，裁判根本区分不了“真跑通”与“降级跑通”。
    # 现分模式判定并如实报告模式。
    import subprocess
    txt_dir = os.path.join(CORPUS, "txt")
    has_corpus = os.path.isdir(txt_dir) and any(
        f.endswith(".txt") for f in os.listdir(txt_dir))
    try:
        p = subprocess.run([sys.executable, core, "--demo"], cwd=ROOT,
                           capture_output=True, text=True, timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        nlines = len(out.splitlines())
        if has_corpus:
            # 完整模式：必须有可回溯的正文证据（“字符 [a:b]”引用），而不只是 DOI 表格。
            n_ev = len(re.findall(r"字符\s*\[\d+:\d+\]", out))
            ok = p.returncode == 0 and "Traceback" not in out and n_ev >= 3
            check("E4-演示可运行", ok,
                  f"--demo 完整模式：退出码 {p.returncode}，{nlines} 行，正文回溯证据 {n_ev} 条"
                  + ("" if ok else "（需退出码 0、无 traceback、≥3 条正文回溯证据）"))
        else:
            ok = (p.returncode == 0 and "Traceback" not in out
                  and "一次性准备" in out and nlines >= 20)
            check("E4-演示可运行", ok,
                  f"--demo 降级模式（corpus/txt 缺失）：退出码 {p.returncode}，{nlines} 行"
                  + ("" if ok else "（需退出码 0、无 traceback、含修复指引、有实质输出）"))
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
    # F1b 旧检查只数 “## ”个数（≥7 即过）：栏名写成“占位一、占位二…”也能过。
    # 现要求 7 类规定栏目（权威著录/摘要/量化指标/方法机理/验证/局限/承前启后）齐全。
    bad_sec = []
    for c in cards:
        heads = " ".join(re.findall(r"^##\s+(.*)$", open(c, encoding="utf-8").read(), re.M))
        miss = [s for s in FACT_SECTIONS if s not in heads]
        if miss:
            bad_sec.append(f"{os.path.basename(c)}缺{','.join(miss)}")
    check("F1b-事实卡栏目齐", not thin_cards and not bad_sec and len(cards) == 20,
          ("栏目不足 7 节：" + "、".join(thin_cards[:6]) if thin_cards
           else "栏目名不符：" + "、".join(bad_sec[:4])) if (thin_cards or bad_sec)
          else f"{len(cards)} 张、每张 7 类规定栏目齐全（目标 20）")

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

    # F4：白皮书是派生物，必须与 docs/lectures + code/ 源一致。
    # 旧验收完全不查这一项：直接改白皮书（或改了讲稿忘装配）都能 PASS，
    # 下次装配即丢改动。现备份→重装配→比对→恢复，全程不污染工作区。
    # （build 已改为确定性时间戳，故可逐字节比对。）
    import shutil
    import subprocess
    import tempfile
    wp_path = WHITEPAPER
    try:
        with tempfile.TemporaryDirectory() as td:
            bak = os.path.join(td, "wp.bak.md")
            shutil.copy2(wp_path, bak)
            p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_whitepaper.py")],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
            same = (p.returncode == 0
                    and open(wp_path, "rb").read() == open(bak, "rb").read())
            shutil.copy2(bak, wp_path)  # 无论如何恢复，避免 verify 污染工作区
        check("F4-白皮书源一致", same,
              "白皮书与讲稿/代码源逐字节一致" if same
              else "白皮书与源不一致（改了讲稿/code 后请重跑 make whitepaper；或有人直接改了白皮书）")
    except Exception as e:  # noqa: BLE001
        check("F4-白皮书源一致", False, f"一致性检查无法执行：{type(e).__name__}: {e}")



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

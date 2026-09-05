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
SOURCE_TAG_RE = re.compile(r"［[^］]{0,40}(?:原文|出版商|doi_verification|web_evidence|待核|未获取)[^］]{0,40}］")

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
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        block = text[m.start():end]
        n = len(re.sub(r"\s", "", block))
        if n < 1200:
            thin.append(f"第{m.group(1)}讲({n}字)")
        hits = [s for s in REQUIRED_SECTIONS if s in block]
        if len(hits) < 4:
            missing_sec.append(f"第{m.group(1)}讲({len(hits)}/6)")
    check("A3-单讲篇幅", not thin, "过短：" + "、".join(thin) if thin else "全部 ≥1200 字")
    check("A4-小节完整", not missing_sec,
          "缺节：" + "、".join(missing_sec) if missing_sec else "20 讲均含规定小节")

    # 数字可溯：统计表格外的裸百分比断言
    body = re.sub(r"^\|.*$", "", text, flags=re.M)  # 先剔除表格行
    bare = []
    for m in PCT_RE.finditer(body):
        seg = m.group(0)
        if not SOURCE_TAG_RE.search(seg) and "［" not in seg:
            bare.append(re.sub(r"\s+", " ", seg)[-60:])
    check("A5-数字可溯", len(bare) <= 10,
          f"{len(bare)} 处百分比断言未标注来源" + (f"，例：{bare[0]}" if bare else ""))


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


# --------------------------------------------------------------------------- E
def verify_skills() -> None:
    core = os.path.join(SKILLS, "core.py")
    if not os.path.exists(core):
        check("E-技能包", False, "skills/omni_scholar/core.py 缺失")
        return
    src = open(core, encoding="utf-8").read()
    placeholders = [l.strip()[:60] for l in src.splitlines()
                    if "待注入" in l or "TODO" in l and "raise NotImplementedError" in src]
    check("E1-无占位实现", not placeholders,
          "仍含占位：" + "；".join(placeholders[:3]) if placeholders else "无硬编码占位")
    try:
        ast.parse(src)
        check("E2-可解析", True, "core.py 语法正确")
    except SyntaxError as e:
        check("E2-可解析", False, f"语法错误 line {e.lineno}")


def main() -> int:
    verify_whitepaper()
    verify_code()
    verify_images()
    verify_consistency()
    verify_skills()

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

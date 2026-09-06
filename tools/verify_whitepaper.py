#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_whitepaper.py —— 白皮书"内容达标"专项校验（目标 A 的逐条明细）
=============================================================================
`tools/verify_all.py` 只给一行 PASS/FAIL；本脚本给出**逐讲**的达成情况，
用于定位"到底哪一讲的哪一节不达标"。

判定口径**直接复用** verify_all.py 的正则常量，避免两个脚本各说各话
（这正是上一版"验收器比标准宽松"的问题根源）。

用法：
    python3 tools/verify_whitepaper.py            # 逐讲报告
    python3 tools/verify_whitepaper.py --strict    # 有任一不达标即退出码 1
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import verify_all as V  # noqa: E402  复用同一套常量与判定逻辑

WHITEPAPER = V.WHITEPAPER
MIN_CHARS = 1200
N_REQUIRED = len(V.REQUIRED_SECTIONS)


def lecture_blocks(text: str):
    """逐讲切块：终点取「下一讲」与「下一篇（^# ）」中更早者。"""
    heads = list(V.LECTURE_RE.finditer(text))
    parts = [x.start() for x in re.finditer(r"^# ", text, re.M)]
    for i, m in enumerate(heads):
        cands = [heads[i + 1].start()] if i + 1 < len(heads) else []
        cands += [x for x in parts if x > m.start()]
        yield m.group(1), text[m.start():min(cands) if cands else len(text)]


def percent_blocks_unsourced(block: str):
    """返回该讲内含百分比但无可回溯标注的段落数（与 A5 同口径）。"""
    out = []
    blocks = re.split(r"\n\s*\n", block)
    in_fence = False
    for i, blk in enumerate(blocks):
        if blk.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not re.search(r"\d+(?:\.\d+)?\s?(?:%|倍)", blk):
            continue
        if V.CITED_RE.search(blk):
            continue
        is_table = sum(1 for l in blk.splitlines() if l.strip().startswith("|")) >= 2
        if is_table:
            prev = blocks[i - 1] if i > 0 else ""
            nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
            if V.CITED_RE.search(prev) or V.CITED_RE.search(nxt):
                continue
        out.append(re.sub(r"\s+", " ", blk.strip())[:64])
    return out


def main() -> int:
    if not os.path.exists(WHITEPAPER):
        print(f"✗ 白皮书不存在：{WHITEPAPER}")
        return 1
    text = open(WHITEPAPER, encoding="utf-8").read()
    blocks = list(lecture_blocks(text))
    total = len(re.sub(r"\s", "", text))

    print("=" * 96)
    print("白皮书内容达标明细（口径与 verify_all.py 完全一致）")
    print("=" * 96)
    print(f"{'讲次':<6}{'字数':>8}  {'6 小节':<10}{'缺节':<26}{'无源百分比段':>12}")
    print("-" * 96)
    bad = 0
    for lid, blk in blocks:
        n = len(re.sub(r"\s", "", blk))
        heads_in = re.findall(r"^#{3,4}\s+(.*)$", blk, re.M)
        hits = [s for s in V.REQUIRED_SECTIONS if any(s in h for h in heads_in)]
        miss = "、".join(s for s in V.REQUIRED_SECTIONS
                         if not any(s in h for h in heads_in)) or "—"
        unsourced = percent_blocks_unsourced(blk)
        ok = n >= MIN_CHARS and len(hits) == N_REQUIRED and not unsourced
        bad += 0 if ok else 1
        mark = "✅" if ok else "❌"
        print(f"第{lid}讲 {mark:<4}{n:>8,}  {len(hits)}/6 {'  ':<4}{miss:<26}{len(unsourced):>10}")
        for s in unsourced[:2]:
            print(f"        └─ 无源：{s}")
    print("-" * 96)
    print(f"合计 {len(blocks)} 讲，全书 {total:,} 字；不达标 {bad} 讲")
    if len(blocks) != 20:
        print(f"✗ 讲次数量应为 20，实为 {len(blocks)}")
    if bad == 0 and len(blocks) == 20 and total >= 60000:
        print("✅ 目标 A 的机器可验部分全部达成")
        return 0
    print("❌ 存在不达标项（详见上表 ❌ 行）")
    return 1 if "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())

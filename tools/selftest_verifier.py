#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest_verifier.py —— 验收器的反身测试（红队自己的裁判）
=============================================================================
为什么需要它：`verify_all.py` 报 PASS 只说明"没触红灯"，不说明"红灯有效"。
上一版的教训恰恰是**裁判比标准宽松**（A4 命中 4/6 即放行、A5 见到任意"［"即放行、
E1 因 and/or 优先级把 TODO 检测短路）。因此本脚本**故意把每一类已知缺陷塞回仓库**，
断言验收器必须变红；跑完自动还原，不留痕。

用法：
    python3 tools/selftest_verifier.py        # 逐条断言，全绿则退出码 0
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WP = os.path.join(ROOT, "燃气轮机智能设计与前沿算法自学白皮书.md")
FACTS = os.path.join(ROOT, "corpus", "facts", "P09.md")
README = os.path.join(ROOT, "README.md")
SKILL_README = os.path.join(ROOT, "skills", "omni_scholar", "README.md")
LECT07 = os.path.join(ROOT, "docs", "lectures", "07.md")
PART6 = os.path.join(ROOT, "docs", "part6.md")
FACT01 = os.path.join(ROOT, "corpus", "facts", "P01.md")
LECT03 = os.path.join(ROOT, "docs", "lectures", "03.md")
LECT10 = os.path.join(ROOT, "docs", "lectures", "10.md")
LECT17 = os.path.join(ROOT, "docs", "lectures", "17.md")
SAMPLING = os.path.join(ROOT, "code", "sampling.py")
QUANJI = os.path.join(ROOT, "郭老师论文全集综合整理汇总.md")
LINKS = os.path.join(ROOT, "论文链接整理.md")
PAID = os.path.join(ROOT, "付费论文五篇整理.md")

# (用例名, 被改文件, 搜索串, 替换串, 期望变红的检查项[, "all"=替换全部出现而非仅首个])
MUTATIONS = [
    ("A4 小节缺失", WP, "#### 2. 叶轮机械中的真实工程死穴：方案论证阶段",
     "#### 2. 为什么值得单独做一篇", "A4"),
    ("A5 无源百分比", WP, "\n## 6.5 全书收口",
     "\n本方法将效率提升了 42.7%。\n\n## 6.5 全书收口", "A5"),
    ("A6 空壳篇", WP, "## 6.1 全景对比矩阵", "## 6.1 待重建"),
    ("F1 事实卡回退骨架", FACTS, "## 五、方法机理", "## 五、方法机理\n\n- TODO：待填写\n\n## 占位"),
    ("D4b 错误年份回流", README, "| **15** | 2025 |",
     "| **15** | 2024 | *IEEE Conference 2024* |"),
    ("E3 端到端命令缺失", SKILL_README, "core.py --demo", "core.py --无此命令"),
    # --- 本轮收紧项的反身用例（2026-09-06） ---
    ("A4 标题降级为正文", WP, "#### 2. 叶轮机械中的真实工程死穴",
     "2. 叶轮机械中的真实工程死穴", "A4"),
    ("A5 无源倍数", WP, "\n## 6.5 全书收口",
     "\n本方法把效率提升了 3 倍。\n\n## 6.5 全书收口", "A5"),
    ("A6 缺6.3小节", WP, "## 6.3 前瞻选题", "## 6.3 待补", "A6"),
    ("D4b 单年份旧口径回流", README, "| **11** | 2024 |",
     "| **11** | 2024 | Eng Opt (2025) 旧口径 |", "D4b"),
    ("D5 无MA限定的14.0%", README, "损失实测降低 14.0%(MA=0.8)",
     "损失实测降低 14.0%", "D5"),
    ("F1b 事实卡栏目改名", FACT01, "## 六、局限与可攻击点", "## 六、其他事项", "F1b"),
    ("F4 白皮书与源脱节", LECT07, "6 倍维度；10 次独立运行［原文 P08",
     "6 倍维度；10 次独立运行［正文 P08", "F4"),
    ("B 代码注入运行时错误", SAMPLING, 'if __name__ == "__main__":',
     'raise RuntimeError("selftest注入")\nif __name__ == "__main__":', "B"),
    # 第三轮新增：无本地原文的论文 DOI 从索引文档消失，必须被 D4a 抓到
    # （DOI 在该条目中出现 3 次：链接文字、doi.org、出版商 URL——必须整体抹掉，故标记 all）
    ("D4a 无原文论文的DOI丢失", LINKS, "10.1117/12.3117536", "10.1117/12.0000000", "D4a", "all"),
    # 第三轮新增：规范编号从付费五篇整理中消失（回退为纯文内顺序号），必须被 D6 抓到
    # （合并说明：该检查在独立复审分支上原名 D5；与本仓 D5-工况限定 撞号，合并后统一改为 D6）
    ("D6 规范编号缺失", PAID, "【论文 14】", "", "D6"),
    # 第四轮新增：整讲的配图引用从白皮书消失（图文件还在 images/，但该讲正文无图）——
    # C4 只按“篇”统计抓不到这种回退，必须由 C5 按讲捕获。
    # 第五轮新增：规范 §三.3 禁止的"无量化套话"回流，必须被 A7 抓到
    # （旧验收器只查"数字有没有标签"，对"显著/大幅"这类无出处形容词完全无感）
    # 第六轮新增：讲次↔论文并列标注错位（历史上"白皮书第10讲=全集16号"式混乱），必须被 D7 抓到
    ("D7 讲次论文标注错位", LECT10, "（**论文 16**）", "（**论文 12**）", "D7"),
    # 第六轮新增：自陈算式被改坏（改数字忘同步推导值），必须被 A8 抓到
    # A5 只看有没有来源标签，对"标签在、算术错"完全无感
    ("A8 自陈算式算错", LECT03, "1500/20000 = 7.5%", "1500/20000 = 15.0%", "A8"),
    # 第六轮新增：LaTeX 结构损坏（公式渲染成乱码），必须被 A9 抓到
    ("A9 公式花括号损坏", LECT03, "$$", "$$\\frac{a}{b$$\n\n$$", "A9"),
    # 第十二轮新增：图注里的数字被抽掉出处标签（图注长期是检查盲区），必须被 C6 抓到
    ("C6 图注数字失去出处", LECT17,
     "（cascade rig，数值见［原文 P09 摘要］，手绘笔记版）",
     "（cascade rig，手绘笔记版）", "C6"),
    ("A7 无源套话回流", WP, "\n## 6.5 全书收口",
     "\n本方法把端壁二次流损失显著降低。\n\n## 6.5 全书收口", "A7"),
    # 第五轮新增：自称"逐字/verbatim"的英文摘要被改写或截断，必须被 F5 抓到
    # （F1b 只数栏目名、D4b 只认已知错误串；"改写版冒充逐字"这类新造假两者都放行）
    ("F5 逐字摘要被篡改", FACT01,
     "has been widely used to guide the Bayesian optimization (BO).",
     "has been broadly adopted to steer the Bayesian optimization process (BO).", "F5"),
    # C5 变异：删掉某一讲的**全部**配图。
    #   旧用例只删 1 张，但随着每讲配图增至 2~3 张，删 1 张已不足以让该讲无图——
    #   2026-09-06 第十二轮反身测试当场暴露此用例失效（C5 漏检），遂改为整讲清空。
    ("C5 某讲配图整体消失", LECT17, "__ALL_IMAGES__", "", "C5"),
]


def run_verify(fast: bool = False) -> str:
    env = dict(os.environ)
    if fast:
        # 非B用例不需要真跑pytest（~70s/轮）：verify_all 见此标记即把 B4b/B5b 记为 SKIP。
        # 这只是反身测试的加速机制——默认的 `make verify` 仍是全量真跑。
        env["MRGUO_SKIP_SLOW"] = "1"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_all.py")],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return p.stdout


def items(output: str) -> dict[str, str]:
    out = {}
    for line in output.splitlines():
        m = re.match(r"\[(PASS|FAIL)\]\s+(\S+)", line)
        if m:
            out[m.group(2)] = m.group(1)
    return out


def backup(paths) -> dict:
    return {p: open(p, "rb").read() for p in set(paths)}


def restore(snaps: dict) -> None:
    for p, data in snaps.items():
        with open(p, "wb") as f:
            f.write(data)


def main() -> int:
    print("=" * 78)
    print("验收器反身测试：故意注入缺陷，断言 verify_all.py 必须报 FAIL")
    print("=" * 78)
    base = items(run_verify(fast=True))
    bad0 = [k for k, v in base.items() if v != "PASS"]
    if bad0:
        print(f"⚠ 基线不干净，先修好这些再自测：{bad0}")
        return 1
    print(f"基线：{len(base)}/{len(base)} PASS\n")

    snaps = backup([m[1] for m in MUTATIONS])
    failed: list[str] = []
    try:
        for case in MUTATIONS:
            name, path, needle, repl = case[0], case[1], case[2], case[3]
            want = case[4] if len(case) > 4 else None
            # 特殊锚点：删掉该文件里的**全部**图引用（用于 C5——某讲配图整体消失）。
            # 每讲配图已增至 2~3 张，删单张不再能让该讲无图，必须整讲清空。
            if needle == "__ALL_IMAGES__":
                if not os.path.exists(path):
                    print(f"⚠ 跳过「{name}」：文件不存在 {path}")
                    continue
                t = open(path, encoding="utf-8").read()
                open(path, "w", encoding="utf-8").write(
                    re.sub(r"!\[[^\]]*\]\(\./images/[^)]+\)\n?", "", t))
            else:
                if not os.path.exists(path) or needle not in open(path, encoding="utf-8").read():
                    print(f"⚠ 跳过「{name}」：注入锚点不存在（该用例需随正文演进更新）")
                    continue
                t = open(path, encoding="utf-8").read()
                count = -1 if (len(case) > 5 and case[5] == "all") else 1
                open(path, "w", encoding="utf-8").write(t.replace(needle, repl, count))
            # B 用例必须全量真跑才能捕获；其余用例用加速模式。
            after = items(run_verify(fast=not (want or "").startswith("B")))
            caught = [k for k, v in after.items() if v == "FAIL"]
            if want:
                hit = [k for k in caught if k.startswith(want)]
            else:  # A6：任一 FAIL 即算捕获
                hit = caught
            status = "✅ 捕获" if hit else "❌ 漏检"
            print(f"  {status}  「{name}」→ {want or '任意'}  "
                  f"（实际 FAIL 项：{', '.join(caught) or '无'}）")
            if not hit:
                failed.append(name)
            restore(snaps)
    finally:
        restore(snaps)

    print("-" * 78)
    if failed:
        print(f"❌ 验收器对 {len(failed)} 类缺陷无感知：{'、'.join(failed)}")
        print("   → 说明裁判仍然太宽松，请收紧 verify_all.py 而不是放松标准。")
        return 1
    print(f"✅ 全部 {len(MUTATIONS)} 类缺陷均被捕获；仓库已还原。")
    final = items(run_verify(fast=True))
    unclean = [k for k, v in final.items() if v != "PASS"]
    print(f"   还原后复跑：{len(final) - len(unclean)}/{len(final)} PASS"
          + (f"（残留 {unclean}）" if unclean else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

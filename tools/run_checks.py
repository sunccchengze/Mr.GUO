#!/usr/bin/env python3
"""run_checks.py —— 一站式自检：先跑 code/ 的模块自检，再跑 tests/ 的单元测试。

用法（仓库根目录）：
    python tools/run_checks.py            # 全部
    python tools/run_checks.py --modules  # 只跑 code/ 模块自检
    python tools/run_checks.py --tests    # 只跑 tests/ 单元测试

退出码：全部通过为 0，任一失败为 1。
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = os.path.join(ROOT, "code")
TESTS = os.path.join(ROOT, "tests")


def run_one(script: str) -> tuple:
    """运行一个脚本，返回 (是否成功, 耗时秒, 输出摘要)。"""
    t0 = time.time()
    proc = subprocess.run([sys.executable, script],
                          cwd=ROOT, capture_output=True, text=True)
    dt = time.time() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    summary = ""
    ran = ""
    for line in out.strip().splitlines():
        if line.startswith("Ran "):
            ran = line.strip()
        elif line.startswith(("[", "OK", "FAILED")):
            summary = line.strip()
    # 单元测试优先显示 "Ran N tests" 这条（用例数信息）
    if ran:
        summary = ran + ((" — " + summary) if summary else "")
    if proc.returncode != 0:
        summary = (out.strip().splitlines() or ["<无输出>"])[-1]
    return proc.returncode == 0, dt, summary


def main() -> int:
    ap = argparse.ArgumentParser(description="运行 code/ 模块自检与 tests/ 单元测试")
    ap.add_argument("--modules", action="store_true", help="只跑 code/ 模块自检")
    ap.add_argument("--tests", action="store_true", help="只跑 tests/ 单元测试")
    args = ap.parse_args()
    do_modules = args.modules or not (args.modules or args.tests)
    do_tests = args.tests or not (args.modules or args.tests)

    failures = 0

    if do_modules:
        mods = sorted(glob.glob(os.path.join(CODE, "*.py")))
        mods = [m for m in mods if not os.path.basename(m).startswith("_")]
        print(f"=== code/ 模块自检（{len(mods)} 个）===")
        for m in mods:
            ok, dt, summary = run_one(m)
            flag = "PASS" if ok else "FAIL"
            print(f"  [{flag}] {os.path.basename(m):<24s} {dt:6.2f}s  {summary}")
            failures += 0 if ok else 1

    if do_tests:
        tfiles = sorted(glob.glob(os.path.join(TESTS, "test_*.py")))
        print(f"=== tests/ 单元测试（{len(tfiles)} 个文件）===")
        total = 0
        for t in tfiles:
            ok, dt, summary = run_one(t)
            flag = "PASS" if ok else "FAIL"
            if summary.startswith("Ran "):
                try:
                    total += int(summary.split()[1])
                except (IndexError, ValueError):
                    pass
            print(f"  [{flag}] {os.path.basename(t):<34s} {dt:6.2f}s  {summary}")
            failures += 0 if ok else 1
        print(f"  单元测试用例合计：{total}")

    print("=" * 60)
    if failures:
        print(f"存在 {failures} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

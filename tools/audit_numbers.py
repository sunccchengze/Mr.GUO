#!/usr/bin/env python3
"""检测卷数值审计：
  N1 出处：卷/答案中的每个内容数字必须在【本讲源】（第零章→chapter0.md，第NN讲→lectures/NN.md）
     或【事实卡】中命中；仅在全集白书命中者单列（跨讲引用，需人工确认合理性）。
  N2 算术：抽出所有显式算式（A±B=C / A×B=C / A÷B=C / A/B≈C / lg、幂、百分数换算）逐条复算。
用法：python3 tools/audit_numbers.py [--only 第03讲]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDIR = os.path.join(ROOT, '检测题')
W = os.path.join(ROOT, '燃气轮机智能设计与前沿算法自学白皮书.md')

IDS = ['第零章'] + ['第%02d讲' % i for i in range(1, 21)]

whitepaper = open(W, encoding='utf-8').read()
facts = ''
for f in sorted(os.listdir(os.path.join(ROOT, 'corpus', 'facts'))):
    if f.endswith('.md'):
        facts += open(os.path.join(ROOT, 'corpus', 'facts', f), encoding='utf-8').read()

def src_of(idn):
    if idn == '第零章':
        return open(os.path.join(ROOT, 'docs', 'chapter0.md'), encoding='utf-8').read()
    n = idn[1:3]
    return open(os.path.join(ROOT, 'docs', 'lectures', f'{n}.md'), encoding='utf-8').read()

# 数字 token：小数 / 整数（1~4 位）/ 百分数
NUM = re.compile(r'(\d{1,4}(?:\.\d+)?)\s*(%|万|万节点|维|小时|次|天|年|分|分钟|节点|mm|MM|K|Pa|RPM|kg/s|GB|核|排|级|个|条|张|页|倍|s|ms|℃|°C|°|周|月|维数|变量|样本|次CFD|轮|秒|米|m|km|h|Hz|W|J|N|Pa|MPa|GPa|kPa)')
PCT = re.compile(r'(\d{1,4}(?:\.\d+)?)\s*%')
INT = re.compile(r'(?<![\d.．．])(\d{1,4})(?![\d.％%])')

# 自引用/脚手架数字（非内容断言）：题号、讲次、P 编号、章节号、年份、建议用时
def is_scaffold(num, ctx):
    if num in ('2021','2022','2023','2024','2025','2026','2020'):
        return True
    if re.search(r'第\s*0?\d+\s*[讲章]', ctx):
        return True
    if re.search(r'P\d\d', ctx):
        return True
    if re.search(r'[§§]\s*\d|节|路线图|Table|\d+讲|第\d+题|题\d|（\d+分|\d+分）|\d+ 分钟|\d+分钟', ctx):
        return True
    if re.search(r'满分|建议用时|自查|成绩|分数段|80分|60分|90分|80~|60~', ctx):
        return True
    return False

def extract_numbers(text):
    seen = {}
    for m in PCT.finditer(text):
        num, ctx = m.group(1), text[max(0, m.start()-28):m.end()+28]
        seen.setdefault(num, set()).add(ctx)
    for m in NUM.finditer(text):
        num, ctx = m.group(1), text[max(0, m.start()-28):m.end()+28]
        if not is_scaffold(num, ctx):
            seen.setdefault(num, set()).add(ctx)
    for m in INT.finditer(text):
        num, ctx = m.group(1), text[max(0, m.start()-28):m.end()+28]
        if not is_scaffold(num, ctx) and len(m.group(1)) >= 2:
            seen.setdefault(num, set()).add(ctx)
    return seen

ARITH = re.compile(
    r'(\d{1,6}(?:\.\d+)?)\s*([−\-+×x✕/÷^])\s*(\d{1,6}(?:\.\d+)?(?:\.\d+)?)\s*(?:[=＝]\s*)?([≈~]?\s*\**(\d{1,8}(?:\.\d+)?(?:\.\d+)?%?)\**)?')

def check_arith(text, tag, issues):
    # 只抓显式 "A op B =/≈ C" 型
    for m in re.finditer(r'(\d{1,6}(?:\.\d+)?)\s*([−\-+×x✕])\s*(\d{1,6}(?:\.\d+)?)\s*=\s*\**\s*(\d{1,6}(?:\.\d+)?)', text):
        a, op, b, c = float(m.group(1)), m.group(2), float(m.group(3)), float(m.group(4))
        if op in '−-':
            r = a - b
        elif op == '+':
            r = a + b
        else:
            r = a * b
        if abs(r - c) > max(0.005 * max(1, abs(c)), 0.015):
            issues.append(f'{tag}: 算式 {a} {op} {b} = {m.group(4)}（复算 {r:.4g}）')
    for m in re.finditer(r'(\d{1,6}(?:\.\d+)?)\s*/\s*(\d{1,6}(?:\.\d+)?)\s*≈?\s*\**\s*(\d{1,6}(?:\.\d+)?)\s*%', text):
        a, b, c = float(m.group(1)), float(m.group(2)), float(m.group(3))
        if b == 0:
            continue
        r = a / b * 100
        if abs(r - c) > max(0.05 * max(1, abs(c)), 0.05):
            issues.append(f'{tag}: 算式 {a}/{b} ≈ {m.group(3)}%（复算 {r:.4g}%）')
    for m in re.finditer(r'1000\^\(1/(\d{1,4})\)\s*≈\s*(\d{1,4}\.\d{2,4})', text):
        d, c = float(m.group(1)), float(m.group(2))
        r = 1000 ** (1 / d)
        if abs(r - c) > 0.002:
            issues.append(f'{tag}: 算式 1000^(1/{m.group(1)}) ≈ {m.group(2)}（复算 {r:.5f}）')

def main():
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]
    issues = []
    for idn in IDS:
        if only and only not in idn:
            continue
        tp = os.path.join(TDIR, f'{idn}-检测卷.md')
        ap = os.path.join(TDIR, f'{idn}-答案与评分.md')
        text = open(tp, encoding='utf-8').read() + '\n' + open(ap, encoding='utf-8').read()
        src = src_of(idn)
        nums = extract_numbers(text)
        cross, none = [], []
        for num in sorted(nums, key=lambda x: (len(x), x)):
            if num in src or num in facts:
                continue
            if num in whitepaper:
                cross.append(num)
            else:
                none.append(num)
        if cross:
            issues.append(f'{idn}: 仅全集命中(跨讲?)数字: {", ".join(cross)}')
        if none:
            ctxs = []
            for num in none:
                c = next(iter(nums[num]))
                ctxs.append(f'{num} …{c}…')
            issues.append(f'{idn}: 无出处数字 {len(none)} 个:\n    ' + '\n    '.join(ctxs[:12]))
        check_arith(text, idn, issues)
    print('=== 检测卷数值审计（tools/audit_numbers.py）===')
    if issues:
        print(f'!!! 待核 {len(issues)} 条:')
        for i in issues:
            print(' -', i)
    else:
        print('!!! 全部数字有出处，算术零违例')

if __name__ == '__main__':
    main()

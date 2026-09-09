#!/usr/bin/env python3
"""把检测题按"篇"合并：每篇产出 {篇名}-检测卷合集.md 与 {篇名}-答案与评分合集.md。

合并规则：各讲内容一字不改，仅标题降一级（# -> ##），并加来源注记。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTDIR = os.path.join(ROOT, '检测题')
OUT = os.path.join(ROOT, '分篇学习版')
BASE = '燃气轮机智能设计与前沿算法自学白皮书'

TESTS = {
    '00-第零章': ['第零章'],
    '01-第一篇': ['第01讲', '第02讲', '第03讲', '第04讲', '第05讲'],
    '02-第二篇': ['第06讲', '第07讲', '第08讲', '第09讲'],
    '03-第三篇': ['第10讲', '第11讲', '第12讲', '第13讲', '第14讲', '第15讲'],
    '04-第四篇': ['第16讲', '第17讲', '第18讲', '第19讲', '第20讲'],
}
NAMES = {'检测卷': '检测卷合集', '答案与评分': '答案与评分合集'}
P_NAMES = {'00-第零章': '第零章', '01-第一篇': '第一篇', '02-第二篇': '第二篇',
           '03-第三篇': '第三篇', '04-第四篇': '第四篇'}


def demote(text):
    out, fence = [], False
    for ln in text.split('\n'):
        if ln.strip().startswith('```'):
            fence = not fence
            out.append(ln)
            continue
        if not fence and re.match(r'^#{1,5} ', ln):
            out.append('#' + ln)
        else:
            out.append(ln)
    return '\n'.join(out)


def build(folder, kind):
    lec = TESTS[folder]
    cname = NAMES[kind]
    parts = ['# %s%s（共%d套）\n' % (P_NAMES[folder], cname, len(lec))]
    parts.append('> 合并说明：以下%d套卷原样合并，内容一字未改，仅标题降一级；' % len(lec)
                 + '来源见每套卷首注记。\n')
    for t in lec:
        src = os.path.join(TESTDIR, f'{t}-{kind}.md')
        assert os.path.exists(src), f'缺源文件：{src}'
        body = open(src, encoding='utf-8').read()
        parts.append('---\n\n> 📌 来源：`检测题/%s-%s.md`\n' % (t, kind))
        parts.append(demote(body).rstrip() + '\n')
    d = os.path.join(OUT, folder)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f'{BASE}-{P_NAMES[folder]}-{cname}.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(parts))
    print(f'{folder} {kind}: {len(lec)}套 -> {os.path.basename(out)}')


def main():
    for folder in TESTS:
        build(folder, '检测卷')
        build(folder, '答案与评分')


if __name__ == '__main__':
    main()

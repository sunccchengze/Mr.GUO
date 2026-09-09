#!/usr/bin/env python3
"""把白皮书按"篇"切成 8 个 md（图片路径改写为相对新位置，其余一字不动）。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, '燃气轮机智能设计与前沿算法自学白皮书.md')
OUT = os.path.join(ROOT, '分篇学习版')
BASE = '燃气轮机智能设计与前沿算法自学白皮书'

# 命名规则：{BASE}-{篇名}-{类型}.md；篇名与文件夹名一致（07-附录 的篇名为「附录」）
P_NAMES = {'00-第零章': '第零章', '01-第一篇': '第一篇', '02-第二篇': '第二篇',
           '03-第三篇': '第三篇', '04-第四篇': '第四篇', '05-第五篇': '第五篇',
           '06-第六篇': '第六篇', '07-附录': '附录'}

# (文件夹, 起始行, 结束行) —— 1-based闭区间；第零章含卷首(1-166)
PARTS = [
    ('00-第零章', 1, 321),
    ('01-第一篇', 322, 2467),
    ('02-第二篇', 2468, 4138),
    ('03-第三篇', 4139, 6753),
    ('04-第四篇', 6754, 9101),
    ('05-第五篇', 9102, 12787),
    ('06-第六篇', 12788, 12954),
    ('07-附录', 12955, 12995),
]
EXPECT_HEAD = {
    '00-第零章': '# 燃气轮机智能设计与前沿算法自学白皮书',
    '01-第一篇': '# 第一篇', '02-第二篇': '<a id="part-2"',
    '03-第三篇': '<a id="part-3"', '04-第四篇': '<a id="part-4"',
    '05-第五篇': '<a id="part-5"', '06-第六篇': '<a id="part-6"',
    '07-附录': '<a id="appendix"',
}
EXPECT_TAIL = {
    '00-第零章': None, '01-第一篇': None, '02-第二篇': None, '03-第三篇': None,
    '04-第四篇': None, '05-第五篇': None, '06-第六篇': None,
    '07-附录': 'vae_nurbs_endwall.png',
}


def main():
    lines = open(SRC, encoding='utf-8').read().split('\n')
    assert len(lines) == 12996, f'全文行数变化：{len(lines)}'  # 末尾空串
    # 连续性校验
    for (f1, s1, e1), (f2, s2, e2) in zip(PARTS, PARTS[1:]):
        assert s2 == e1 + 1, f'{f1}/{f2} 不连续'
    for folder, s, e in PARTS:
        head = lines[s - 1]
        assert head.startswith(EXPECT_HEAD[folder]), f'{folder} 头不对：{head[:40]}'
        tail = lines[e - 1]
        if EXPECT_TAIL[folder]:
            assert EXPECT_TAIL[folder] in tail, f'{folder} 尾不对：{tail[:60]}'
        body = '\n'.join(lines[s - 1:e])
        # 图片路径：./images/ -> ../../images/（新位置深 2 层）
        n_img = body.count('./images/')
        body = body.replace('./images/', '../../images/')
        d = os.path.join(OUT, folder)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f'{BASE}-{P_NAMES[folder]}-白皮书.md')
        open(out, 'w', encoding='utf-8').write(body)
        print(f'{folder}: 行{s}-{e}（{e - s + 1}行，{n_img}处图片）-> {os.path.basename(out)}')


if __name__ == '__main__':
    main()

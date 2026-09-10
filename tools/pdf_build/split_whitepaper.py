#!/usr/bin/env python3
"""把白皮书按"篇"切成 8 个 md（其余一字不动，仅两类相对路径改写）：

1. 图片：./images/ -> ../../images/（分篇位置深 2 层）
2. 学习回路链接：](prompts/ 、](templates/（白皮书在仓库根，根相对）
   -> ](../../prompts/ 、](../../templates/

边界定位：2026-09-10 起改用**语义标记动态定位**（各篇标题行/锚点行），
不再硬编码行号——白皮书内容增长（学习回路块收编等）会使行号锁必然腐烂
（旧锁 12996 即因此断裂，见 docs/重建计划.md §18.5）。标记语义唯一性由
装配期目录锚点自检保证（id 不重复）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, '燃气轮机智能设计与前沿算法自学白皮书.md')
OUT = os.path.join(ROOT, '分篇学习版')
BASE = '燃气轮机智能设计与前沿算法自学白皮书'

# 命名规则：{BASE}-{篇名}-{类型}.md；篇名与文件夹名一致（07-附录 的篇名为「附录」）
P_NAMES = {'00-第零章': '第零章', '01-第一篇': '第一篇', '02-第二篇': '第二篇',
           '03-第三篇': '第三篇', '04-第四篇': '第四篇', '05-第五篇': '第五篇',
           '06-第六篇': '第六篇', '07-附录': '附录'}

# (文件夹, 起始行语义标记) —— 第零章以白皮书主标题为界（第 1 行起），无标记
MARKERS = [
    ('01-第一篇', '# 第一篇'),
    ('02-第二篇', '<a id="part-2"'),
    ('03-第三篇', '<a id="part-3"'),
    ('04-第四篇', '<a id="part-4"'),
    ('05-第五篇', '<a id="part-5"'),
    ('06-第六篇', '<a id="part-6"'),
    ('07-附录', '<a id="appendix"'),
]

EXPECT_TITLE = '# 燃气轮机智能设计与前沿算法自学白皮书'  # 主标题前缀（其后为副标题）
APPENDIX_TAIL = 'vae_nurbs_endwall.png'  # 附录末行应含的图（图册收尾）


def find_part_starts(lines):
    starts = {}
    for i, ln in enumerate(lines, 1):
        for folder, marker in MARKERS:
            if folder not in starts and ln.startswith(marker):
                starts[folder] = i
    missing = [f for f, _ in MARKERS if f not in starts]
    if missing:
        raise SystemExit('[FAIL] 篇起始标记未命中：' + '、'.join(missing))
    return starts


def main():
    lines = open(SRC, encoding='utf-8').read().split('\n')
    # 结构性校验（取代旧硬编码行数锁）
    assert lines[0].startswith(EXPECT_TITLE), f'首行非主标题：{lines[0][:40]}'
    assert lines[-1] == '', '末行应为结尾空串'
    starts = find_part_starts(lines)

    # 全部分片（第零章 = 1 .. 第一篇起始-1；其余 = 本段起始 .. 下一段起始-1）
    seq_folders = ['00-第零章'] + [f for f, _ in MARKERS]
    seq_starts = {f: starts[f] for f in seq_folders if f != '00-第零章'}
    seq_starts['00-第零章'] = 1
    boundaries = []
    for i, folder in enumerate(seq_folders):
        s = seq_starts[folder]
        e = (seq_starts[seq_folders[i + 1]] - 1) if i + 1 < len(seq_folders) else len(lines) - 1
        assert e - s + 1 >= 5, f'{folder} 分片异常短：行 {s}-{e}'
        boundaries.append((folder, s, e))
    assert [s for _, s, _ in boundaries] == sorted(s for _, s, _ in boundaries)
    assert boundaries[-1][2] == len(lines) - 1, '末篇未收到文末'

    for folder, s, e in boundaries:
        body = '\n'.join(lines[s - 1:e])
        if folder == '07-附录':
            assert APPENDIX_TAIL in lines[e - 1], f'附录末行异常：{lines[e - 1][:60]}'
        # 图片路径：./images/ -> ../../images/（新位置深 2 层）
        n_img = body.count('./images/')
        body = body.replace('./images/', '../../images/')
        # 学习回路链接：](prompts/ 、](templates/ -> ](../../...（深 2 层）
        n_pr = body.count('](prompts/') + body.count('](templates/')
        body = body.replace('](prompts/', '](../../prompts/')
        body = body.replace('](templates/', '](../../templates/')
        d = os.path.join(OUT, folder)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f'{BASE}-{P_NAMES[folder]}-白皮书.md')
        open(out, 'w', encoding='utf-8').write(body)
        print(f'{folder}: 行{s}-{e}（{e - s + 1}行，{n_img}处图片，{n_pr}处回路链接）-> {os.path.basename(out)}')


if __name__ == '__main__':
    main()

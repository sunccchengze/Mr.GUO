#!/usr/bin/env python3
"""一键构建：图片压缩缓存 -> 18 个 PDF -> pypdf 校验 -> 预览图。

前置（同会话 /tmp，不进 git）：
    /tmp/pdffont/NotoSansSC-{Regular,Bold}.ttf   # 见 tools/pdf_build/README
    pip: markdown reportlab pillow fonttools pymupdf pypdf
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, '分篇学习版')
BASE = '燃气轮机智能设计与前沿算法自学白皮书'
IMG_CACHE = '/tmp/pdfbuild/img'
FONTDIR = '/tmp/pdffont'
PREVIEW = '/tmp/pdfbuild/preview'

# 命名规则：{BASE}-{篇名}-{类型}.md（与 split/merge 脚本一致）
P_NAMES = {'00-第零章': '第零章', '01-第一篇': '第一篇', '02-第二篇': '第二篇',
           '03-第三篇': '第三篇', '04-第四篇': '第四篇', '05-第五篇': '第五篇',
           '06-第六篇': '第六篇', '07-附录': '附录'}


def md_name(folder, kind):
    return f'{BASE}-{P_NAMES[folder]}-{kind}.md'


# (文件夹, md 文件名, 栏数)
JOBS = []
for folder in ['00-第零章', '01-第一篇', '02-第二篇', '03-第三篇', '04-第四篇']:
    for kind in ('白皮书', '检测卷合集', '答案与评分合集'):
        JOBS.append((folder, md_name(folder, kind), 2))
JOBS.append(('05-第五篇', md_name('05-第五篇', '白皮书'), 1))   # 代码密集，单栏
JOBS.append(('06-第六篇', md_name('06-第六篇', '白皮书'), 2))
JOBS.append(('07-附录', md_name('07-附录', '白皮书'), 1))       # 图册，单栏大图


def build_cache():
    from PIL import Image
    os.makedirs(IMG_CACHE, exist_ok=True)
    have = {os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(IMG_CACHE, '*.jpg'))}
    n, tot = 0, 0
    for p in sorted(glob.glob(os.path.join(ROOT, 'images', '*.png'))):
        stem = os.path.splitext(os.path.basename(p))[0]
        out = os.path.join(IMG_CACHE, stem + '.jpg')
        if stem in have:
            tot += os.path.getsize(out)
            continue
        im = Image.open(p).convert('RGB')
        if im.width > 1000:
            im = im.resize((1000, int(im.height * 1000 / im.width)), Image.LANCZOS)
        im.save(out, quality=80)
        n += 1
        tot += os.path.getsize(out)
    print(f'图片缓存：{len(glob.glob(os.path.join(IMG_CACHE, "*.jpg")))}张（新转{n}张），{tot / 1048576:.1f} MB')


def render():
    md2pdf = os.path.join(ROOT, 'tools', 'pdf_build', 'md2pdf.py')
    for folder, md, cols in JOBS:
        mdpath = os.path.join(OUT, folder, md)
        pdf = mdpath[:-3] + '.pdf'
        assert os.path.exists(mdpath), f'缺 md：{mdpath}'
        r = subprocess.run([sys.executable, md2pdf, mdpath, pdf, '--columns', str(cols),
                            '--img-cache', IMG_CACHE, '--fontdir', FONTDIR],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            print(f'FAIL {folder}/{md}:\n{r.stderr[-3000:]}')
            sys.exit(1)
        print(f'{folder} {md} -> {cols}栏 OK')


def verify():
    import fitz
    from pypdf import PdfReader
    os.makedirs(PREVIEW, exist_ok=True)
    print('\n%-10s %-28s %4s %8s %4s  %s' % ('文件夹', '文件', '页数', '大小', '图数', '字体'))
    total_pages, total_size = 0, 0
    for folder, md, _ in JOBS:
        pdf = os.path.join(OUT, folder, md)[:-3] + '.pdf'
        r = PdfReader(pdf)
        fonts, nimgs = set(), 0
        for pg in r.pages:
            nimgs += len(pg.images)
            for f in (pg.get('/Resources') or {}).get('/Font', {}).values():
                fonts.add(str(f.get_object().get('/BaseFont')))
        size = os.path.getsize(pdf)
        total_pages += len(r.pages)
        total_size += size
        # 完整性：首尾文本标记
        t0 = (r.pages[0].extract_text() or '')
        tN = (r.pages[-1].extract_text() or '')
        assert len(t0) > 50, f'{pdf} 首页无文本？'
        assert len(tN) > 20, f'{pdf} 末页无文本？'
        assert '[缺图' not in t0 and '[缺图' not in tN, f'{pdf} 有缺图！'
        kind = os.path.splitext(md)[0][len(BASE) + 1:].rsplit('-', 1)[-1]
        fnames = ','.join(sorted(f.split('+')[-1] for f in fonts))
        print('%-10s %-28s %4d %7.1fM %4d  %s' % (
            folder, kind, len(r.pages), size / 1048576, nimgs, fnames))
        # 预览图：每个 PDF 的第 1 页 + 大文档追加中间页
        d = fitz.open(pdf)
        picks = [0] if len(d) <= 6 else [0, len(d) // 2]
        for p in picks:
            tag = f'{folder}_{kind}_p{p + 1}'
            d[p].get_pixmap(dpi=100).save(os.path.join(PREVIEW, tag + '.png'))
    print(f'\n合计：{total_pages}页，{total_size / 1048576:.1f} MB；预览图见 {PREVIEW}/')


if __name__ == '__main__':
    assert os.path.exists(os.path.join(FONTDIR, 'NotoSansSC-Regular.ttf')), '缺字体 /tmp/pdffont'
    build_cache()
    render()
    verify()

#!/usr/bin/env python3
"""md2pdf.py —— Markdown 转高密度双栏 PDF（reportlab 直驱）。

用法：
    python3 md2pdf.py 输入.md 输出.pdf --columns 2 --imgdir images --fontdir /tmp/pdffont

设计目标（用户要求）：页边距很窄、两栏、高图文密度、图片嵌入、中日韩无 tofu。
防 tofu 机制：正文每字符必落入 NotoSansSC ∪ DejaVuSans，否则构建前直接报错；
emoji 等装饰符映射为 CJK 语义 token（仅影响 PDF，md 原文不动）。
页内链接：目标锚点在本篇内的保留为可点击内链（如本篇目录），跨篇的退化为纯文本。
"""
import argparse
import html as htmlmod
import os
import re
import sys
from html.parser import HTMLParser

import markdown
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, Image as RLImage,
                                HRFlowable, KeepTogether, PageBreak)

# ---------------------------------------------------------------- 字符映射
# 1) 两字体都没有的字符 -> 语义等价替换（PDF 渲染层，md 不动）
CHARMAP = {
    '✅': '✓', '❌': '✗', '❗': '！', '⭐': '★',
    '𝒢': '<b>G</b>', '𝒫': '<b>P</b>', '𝒳': '<b>X</b>', '𝒵': '<b>Z</b>', '𝔼': '<b>E</b>',
    '🎓': '【毕】', '👑': '【冠】', '💡': '【要】', '📌': '【钉】', '📎': '【附】',
    '📖': '【读】', '🗑': '【删】', '🚫': '【禁】', '🧭': '【引】',
    '\uFE0F': '', '\uFE0E': '', '\u200D': '',  # 变体选择符 / ZWJ：直接去
}
# 2) Noto 缺、DejaVu 有 -> 用 DejaVu 渲染（构建前会校验覆盖）
DEJAVU_ONLY = set(
    'ĈŜŝŷṁẋẍẏˢ̂̃ᵀᵀᵢᵣ⁰ⁱ⁵⁶⁷⁺⁻⁽⁾ⁿ₀₁₂₃₄ₐₑₓₖₘₚₛₜ'
    'ℒℝℳ∖∘∼⊤✗☐☑ⱼ'
)
NOTO = 'NotoSC'
NOTO_B = 'NotoSC-Bold'
DJV = 'DejaVu'

FONTS = {}  # name -> cmap set


def register_fonts(fontdir):
    def reg(name, path):
        pdfmetrics.registerFont(TTFont(name, path))
        from fontTools.ttLib import TTFont as FT
        FONTS[name] = set(FT(path).getBestCmap().keys())
    reg(NOTO, os.path.join(fontdir, 'NotoSansSC-Regular.ttf'))
    reg(NOTO_B, os.path.join(fontdir, 'NotoSansSC-Bold.ttf'))
    reg(DJV, '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')


def wrap_dejavu(markup):
    """把 DEJAVU_ONLY 字符用 DejaVu 包起来（跳过 tag 区）。"""
    out, i, buf = [], 0, []
    while i < len(markup):
        ch = markup[i]
        if ch == '<':
            if buf:
                out.append(f'<font name="{DJV}">' + ''.join(buf) + '</font>')
                buf = []
            j = markup.find('>', i)
            out.append(markup[i:j + 1])
            i = j + 1
            continue
        if ch in DEJAVU_ONLY:
            buf.append(ch)
        else:
            if buf:
                out.append(f'<font name="{DJV}">' + ''.join(buf) + '</font>')
                buf = []
            out.append(ch)
        i += 1
    if buf:
        out.append(f'<font name="{DJV}">' + ''.join(buf) + '</font>')
    return ''.join(out)


def tx(text):
    """text 节点 -> reportlab 安全串。"""
    text = (' ' if text[:1].isspace() else '') + ' '.join(text.split()) + (' ' if text[-1:].isspace() and text.strip() else '')  # HTML 语义：空白折叠
    if text.lstrip().startswith('[ ] '):
        text = text.replace('[ ] ', '☐ ', 1)  # 自查清单复选框（全库仅此一处形态）
    for k, v in CHARMAP.items():
        if k in text:
            text = text.replace(k, v)
    text = htmlmod.escape(text, quote=False)
    # CHARMAP 引入的 <b> 标签被 escape 了，还原回来
    text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    return wrap_dejavu(text)


# ---------------------------------------------------------------- HTML->story
class Walker(HTMLParser):
    def __init__(self, ctx, anchors):
        super().__init__(convert_charrefs=True)
        self.c = ctx
        self.anchors = anchors        # 本文档内存在的 <a id> 集合
        self.emitted_names = set()    # 已写出的 name 目标（去重）
        self.stack = []               # 块栈
        self.inline = []              # 当前段落的 inline 累积
        self.list_stack = []          # (type, counter, indent)
        self.table = None             # 当前表格累积
        self.cell_is_head = False
        self.pre = False
        self.pre_buf = []

    def para_text(self):
        return ''.join(self.inline)

    def emit_para(self, style):
        t = self.para_text().strip()
        self.inline = []
        if t:
            self.c.emit(Paragraph(t, style))

    def handle_starttag(self, tag, attrs):
        A = dict(attrs)
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.stack.append(('h', tag))
        elif tag == 'p':
            self.stack.append(('p', None))
        elif tag in ('strong', 'b'):
            self.inline.append('<b>')
            self.stack.append(('b', None))
        elif tag in ('em', 'i'):
            self.inline.append('<b>')
            self.stack.append(('b', None))
        elif tag == 'code' and not self.pre:
            self.inline.append('<font color="#555555">')
            self.stack.append(('code', None))
        elif tag == 'a':
            href = A.get('href', '')
            if not href and (A.get('id') or A.get('name')):
                # 锚点定义 -> PDF 内链目标（去重）
                nm = A.get('id') or A.get('name')
                if nm in self.anchors and nm not in self.emitted_names:
                    self.emitted_names.add(nm)
                    self.inline.append('<a name="%s"/>' % htmlmod.escape(nm, quote=True))
                self.stack.append(('a', None))
            elif href.startswith('#') and href[1:] in self.anchors:
                self.inline.append('<a color="blue" href="%s">' % htmlmod.escape(href, quote=True))
                self.stack.append(('a', True))
            else:
                self.stack.append(('a', False))  # 跨篇/外部/畸形 href：纯文本
        elif tag == 'br':
            self.inline.append('<br/>')
        elif tag in ('ul', 'ol'):
            self.list_stack.append([tag, 0, len(self.list_stack)])
        elif tag == 'li':
            self.stack.append(('li', None))
        elif tag == 'blockquote':
            self.c.indent += 1
            self.stack.append(('q', None))
        elif tag == 'pre':
            self.pre = True
            self.pre_buf = []
        elif tag == 'table':
            self.table = {'rows': [], 'cur': []}
        elif tag == 'tr':
            self.table['cur'] = []
        elif tag in ('th', 'td'):
            self.cell_is_head = (tag == 'th')
            self.saved_inline = self.inline
            self.inline = []
        elif tag == 'hr':
            self.c.emit(HRFlowable(width='100%', thickness=0.4, color=colors.HexColor('#999999'),
                                   spaceBefore=3, spaceAfter=3))
        elif tag == 'img':
            self.c.emit_image(A.get('src', ''), A.get('alt', ''))
        elif tag == 'summary':
            self.stack.append(('summary', None))
        # 其他 tag（details / div）忽略

    def handle_endtag(self, tag):
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            lvl = int(tag[1])
            style = self.c.style('h%d' % min(lvl, 4))
            t = self.para_text().strip()
            self.inline = []
            if t:
                self.c.emit(Paragraph(t, style))
                if lvl == 1:
                    self.c.emit(HRFlowable(width='100%', thickness=0.8,
                                           color=colors.HexColor('#333333'),
                                           spaceBefore=1, spaceAfter=4))
            self.stack.pop()
        elif tag == 'p':
            self.emit_para(self.c.cur_text_style())
            self.stack.pop()
        elif tag in ('strong', 'b', 'em', 'i'):
            self.inline.append('</b>')
            self.stack.pop()
        elif tag == 'code' and not self.pre:
            self.inline.append('</font>')
            self.stack.pop()
        elif tag == 'a':
            opened = self.stack.pop()[1]
            if opened:
                self.inline.append('</a>')
        elif tag in ('ul', 'ol'):
            self.list_stack.pop()
        elif tag == 'li':
            t = self.para_text().strip()
            self.inline = []
            if t:
                ltype, cnt, depth = self.list_stack[-1]
                if ltype == 'ol':
                    self.list_stack[-1][1] += 1
                    bullet = '%d.' % self.list_stack[-1][1]
                else:
                    bullet = '•'
                st = self.c.list_style(depth)
                self.c.emit(Paragraph(t, st, bulletText=bullet))
            self.stack.pop()
        elif tag == 'blockquote':
            self.c.indent -= 1
            self.stack.pop()
        elif tag == 'pre':
            self.pre = False
            code = ''.join(self.pre_buf).replace('\r', '')
            # 逐行发（可跨页/跨栏断开；空行发小 spacer 保持行距）
            for ln in code.split('\n'):
                if ln.strip() == '':
                    self.c.emit(Spacer(1, 2))
                else:
                    self.c.emit(Paragraph(tx(ln.expandtabs(4)), self.c.style('code')))
            self.pre_buf = []
        elif tag == 'code' and self.pre:
            pass
        elif tag in ('th', 'td'):
            t = ''.join(self.inline).strip() or ' '
            self.inline = self.saved_inline
            if self.cell_is_head:
                t = '<b>%s</b>' % t
            self.table['cur'].append(t)
        elif tag == 'tr':
            self.table['rows'].append(self.table['cur'])
        elif tag == 'table':
            self.c.emit_table(self.table['rows'])
            self.table = None
        elif tag == 'summary':
            t = self.para_text().strip()
            self.inline = []
            self.stack.pop()
            if t:
                self.c.emit(Paragraph('<b>▼ %s</b>' % t, self.c.style('summary')))

    def handle_data(self, data):
        if self.pre:
            self.pre_buf.append(data)
            return
        if not data.strip():
            # 纯空白：段落内折成一个空格
            if self.inline is not None and (self.stack and self.stack[-1][0] in ('p', 'li', 'h', 'a', 'summary')):
                self.inline.append(' ')
            return
        self.inline.append(tx(data))


class Ctx:
    def __init__(self, md_path, img_cache, col_width, frame_h):
        self.story = []
        self.indent = 0
        self.md_dir = os.path.dirname(os.path.abspath(md_path))
        self.img_cache = img_cache
        self.col_width = col_width
        self.max_img_h = frame_h * 0.44  # 单图限高，保证图册页能排下 2 张
        self.styles = self.make_styles()

    def make_styles(self):
        S = {}
        base = dict(fontName=NOTO, fontSize=8.2, leading=11.5, spaceBefore=0,
                    spaceAfter=3, alignment=0)
        S['body'] = ParagraphStyle('body', **base)
        S['h1'] = ParagraphStyle('h1', parent=S['body'], fontName=NOTO_B, fontSize=12.5,
                                 leading=15, spaceBefore=8, spaceAfter=2, keepWithNext=1)
        S['h2'] = ParagraphStyle('h2', parent=S['body'], fontName=NOTO_B, fontSize=10.2,
                                 leading=13, spaceBefore=6, spaceAfter=2, keepWithNext=1)
        S['h3'] = ParagraphStyle('h3', parent=S['body'], fontName=NOTO_B, fontSize=9.2,
                                 leading=12, spaceBefore=4, spaceAfter=2, keepWithNext=1)
        S['h4'] = ParagraphStyle('h4', parent=S['body'], fontName=NOTO_B, fontSize=8.6,
                                 leading=11.5, spaceBefore=3, spaceAfter=2, keepWithNext=1)
        S['quote'] = ParagraphStyle('quote', parent=S['body'], fontSize=7.8, leading=11,
                                    leftIndent=8, textColor=colors.HexColor('#333333'),
                                    spaceAfter=2)
        S['code'] = ParagraphStyle('code', parent=S['body'], fontName=NOTO, fontSize=6.6,
                                   leading=8, leftIndent=4, backColor=colors.HexColor('#F2F2F2'),
                                   borderPadding=(1, 4, 1), spaceAfter=0, spaceBefore=0)
        S['caption'] = ParagraphStyle('caption', parent=S['body'], fontSize=6.8, leading=8.5,
                                      textColor=colors.HexColor('#555555'), spaceAfter=5,
                                      alignment=1)
        S['summary'] = ParagraphStyle('summary', parent=S['body'], fontName=NOTO_B,
                                      fontSize=8.2, backColor=colors.HexColor('#EFEFEF'),
                                      borderPadding=(2, 4, 2), spaceAfter=2)
        S['cell'] = ParagraphStyle('cell', parent=S['body'], fontSize=7, leading=9,
                                   spaceAfter=1)
        S['cellH'] = ParagraphStyle('cellH', parent=S['cell'], fontName=NOTO_B)
        return S

    def style(self, n):
        return self.styles[n]

    def cur_text_style(self):
        return self.styles['quote'] if self.indent else self.styles['body']

    def list_style(self, depth):
        return ParagraphStyle('li%d' % depth, parent=self.cur_text_style(),
                              leftIndent=12 + depth * 8, firstLineIndent=0,
                              bulletIndent=4 + depth * 8, spaceAfter=1)

    def emit(self, fl):
        self.story.append(fl)

    # -- 图片（优先用压缩缓存；限高保证密度） --
    def emit_image(self, src, alt):
        if not src:
            return
        p = None
        base = os.path.basename(src)
        stem = os.path.splitext(base)[0]
        for cand in (os.path.join(self.img_cache, stem + '.jpg'),
                     os.path.join(self.img_cache, base),
                     os.path.normpath(os.path.join(self.md_dir, src))):
            if os.path.exists(cand):
                p = cand
                break
        if p is None:
            self.emit(Paragraph('<font color="red">[缺图 %s]</font>' % htmlmod.escape(src),
                                self.style('body')))
            return
        try:
            iw, ih = PILImage.open(p).size
        except Exception:
            return
        w = min(self.col_width, self.max_img_h * iw / ih)
        h = w * ih / iw
        img = RLImage(p, width=w, height=h)
        img.hAlign = 'CENTER'
        if alt and alt.strip():
            cap = Paragraph(tx(alt.strip()), self.style('caption'))
            self.emit(KeepTogether([img, cap]))
        else:
            self.emit(img)

    # -- 表格 --
    def emit_table(self, rows):
        if not rows:
            return
        ncol = max(len(r) for r in rows)
        rows = [r + [' '] * (ncol - len(r)) for r in rows]
        data = [[Paragraph(c, self.styles['cellH'] if i == 0 else self.styles['cell'])
                 for c in r] for i, r in enumerate(rows)]
        widths = self.col_widths(rows, ncol)
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#999999')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E3E3E3')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]))
        self.emit(t)
        self.emit(Spacer(1, 3))

    @staticmethod
    def cell_units(cell):
        txt = re.sub(r'<[^>]+>', '', htmlmod.unescape(cell))
        n = 0
        for ch in txt:
            n += 2 if ord(ch) > 0x2E7F else 1
        return max(n, 2)

    def col_widths(self, rows, ncol):
        mx = [0] * ncol
        for r in rows:
            for j, c in enumerate(r):
                mx[j] = max(mx[j], self.cell_units(c))
        tot = sum(mx) or 1
        W = self.col_width
        widths = []
        for m in mx:
            w = W * m / tot
            w = max(w, W * 0.07)
            widths.append(w)
        s = sum(widths)
        return [w * W / s for w in widths]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(NOTO, 7)
    canvas.setFillColor(colors.HexColor('#888888'))
    canvas.drawCentredString(A4[0] / 2, 8 * mm, '%d' % doc.page)
    canvas.restoreState()


def build(md_path, pdf_path, columns, img_cache, fontdir):
    register_fonts(fontdir)
    md = open(md_path, encoding='utf-8').read()
    html = markdown.markdown(md, extensions=['tables', 'fenced_code'])
    anchors = set(re.findall(r'<a\s+[^>]*?\bid="([^"]+)"', html))
    anchors |= set(re.findall(r'<a\s+[^>]*?\bname="([^"]+)"', html))
    ML = MR = 9 * mm
    MT, MB = 10 * mm, 14 * mm
    W, H = A4
    FH = H - MT - MB
    if columns == 2:
        gut = 5 * mm
        cw = (W - ML - MR - gut) / 2
        frames = [Frame(ML, MB, cw, FH, id='L'),
                  Frame(ML + cw + gut, MB, cw, FH, id='R')]
    else:
        cw = W - ML - MR
        frames = [Frame(ML, MB, cw, FH, id='full')]
    ctx = Ctx(md_path, img_cache, cw, FH)
    Walker(ctx, anchors).feed(html)
    n_flow = len(ctx.story)
    # ---- 覆盖校验：防 tofu ----
    nodig = set()
    for para in ctx.story:
        if isinstance(para, Paragraph):
            txt = re.sub(r'<[^>]+>', '', para.text)
            txt = htmlmod.unescape(txt)
            for ch in txt:
                o = ord(ch)
                if o in FONTS[NOTO] or o in FONTS[NOTO_B]:
                    continue
                if ch in DEJAVU_ONLY and o in FONTS[DJV]:
                    continue
                nodig.add(ch)
    if nodig:
        raise SystemExit('缺字（会 tofu）：' + repr(''.join(sorted(nodig))))
    doc = BaseDocTemplate(pdf_path, pagesize=A4, leftMargin=ML, rightMargin=MR,
                          topMargin=MT, bottomMargin=MB, title=os.path.basename(md_path))
    doc.addPageTemplates([PageTemplate(id='p', frames=frames, onPage=footer)])
    doc.build(ctx.story)
    print('OK %s (%d flowables)' % (pdf_path, n_flow))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('md')
    ap.add_argument('pdf')
    ap.add_argument('--columns', type=int, default=2)
    ap.add_argument('--img-cache', default='/tmp/pdfbuild/img')
    ap.add_argument('--fontdir', default='/tmp/pdffont')
    a = ap.parse_args()
    build(a.md, a.pdf, a.columns, a.img_cache, a.fontdir)

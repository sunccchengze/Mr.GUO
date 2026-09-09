# PDF 构建工具链（md → 高密度双栏 PDF）

`分篇学习版/` 下全部 18 个 PDF 由本工具链生成。渲染器为 reportlab 直驱
（沙箱无 pango，WeasyPrint/LaTeX 路线不可行），A4 窄边距（9mm），正文双栏。

## 文件

| 脚本 | 作用 |
|---|---|
| `md2pdf.py` | 核心渲染器：markdown → HTML → reportlab 双栏/单栏 PDF |
| `split_whitepaper.py` | 白皮书按"篇"切 8 个 `{篇名}-白皮书.md`（图片路径改写，其余一字不动） |
| `merge_tests.py` | 检测题按"篇"合并 `{篇名}-检测卷合集.md` / `{篇名}-答案与评分合集.md`（标题降一级 + 来源注记） |
| `build_all.py` | 一键：图片压缩缓存 → 18 个 PDF → pypdf 校验 → 预览图 |

## 文件命名口径（2026-09-09 起）

`燃气轮机智能设计与前沿算法自学白皮书-{篇名}-{类型}.md`（PDF 同名）：

- 篇名：`第零章 / 第一～六篇 / 附录`（与文件夹 `00-第零章`…`07-附录` 对应）
- 类型：`白皮书 / 检测卷合集 / 答案与评分合集`
- 第五/六篇与附录目前仅有白皮书（检测卷尚未命制，见各篇 README）

## 复现步骤（字体与缓存不进 git，需重建）

```bash
pip install --break-system-packages markdown reportlab pillow fonttools brotli pypdf pymupdf
mkdir -p /tmp/pdffont
# Noto Sans SC 可变字体（GitHub API 直链，约18MB）
curl -sL -o /tmp/pdffont/NotoSansSC-var.ttf \
  https://api.github.com/repos/google/fonts/contents/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf?ref=main \
  -H "Accept: application/vnd.github.raw"
# 实例化 Regular(400)/Bold(700)并修正命名表
python3 -c "
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.ttLib import TTFont
for fn, fam, sub, full, ps, wght in [
    ('NotoSansSC-Regular.ttf', 'Noto Sans SC', 'Regular', 'Noto Sans SC', 'NotoSansSC-Regular', 400),
    ('NotoSansSC-Bold.ttf', 'Noto Sans SC', 'Bold', 'Noto Sans SC Bold', 'NotoSansSC-Bold', 700)]:
    f = TTFont('/tmp/pdffont/NotoSansSC-var.ttf')
    instantiateVariableFont(f, {'wght': wght}, updateFontNames=True)
    for nid, val in [(1,fam),(2,sub),(4,full),(6,ps),(16,fam),(17,sub)]:
        f['name'].setName(val, nid, 3, 1, 0x409)
    for nid, val in [(1,fam),(2,sub),(4,full),(6,ps)]:
        f['name'].setName(val, nid, 1, 0, 0)
    f.save('/tmp/pdffont/' + fn)
"
# DejaVu 由系统提供：/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
python3 tools/pdf_build/split_whitepaper.py
python3 tools/pdf_build/merge_tests.py
python3 tools/pdf_build/build_all.py
```

## 设计要点

- **防 tofu 门禁**：每字符必落入 NotoSansSC ∪ DejaVuSans，否则构建失败；
  emoji/特殊符号映射为 CJK 语义 token（✅→✓、📌→【钉】等，仅 PDF 层）。
- **图片**：构建时转 JPEG 缓存（最长边 1000px，q80），PDF 内嵌。
- **内链**：目标锚点在本篇内的目录链接保留可点击，跨篇退化为纯文本。
- **栏数**：第五篇（代码密集）与附录（图册）单栏，其余双栏。

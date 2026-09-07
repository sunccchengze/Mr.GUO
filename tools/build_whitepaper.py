#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_whitepaper.py —— 由讲稿源文件装配白皮书
=============================================================================
设计目的（针对旧版"文档与内容脱节"的问题）：
  1. 白皮书正文的每一讲都来自独立源文件 docs/lectures/NN.md，便于逐篇修订与评审；
  2. 目录、篇标题、讲次与论文编号的对应关系由本脚本统一生成，杜绝手抄导致的不一致；
  3. 第五篇代码篇由 code/ 目录下的**真实文件**自动嵌入，杜绝"文档里的代码跑不通"；
  4. 缺失的讲次显式标记为"待重建"，而不是悄悄略写；
  5. 目录跳转使用**显式稳定锚点**（`<a id="…">`），不再依赖各渲染器对中文
     标题 slug 的各自实现——旧版 `anchor()` 与正文标题、与 GitHub GFM 三者
     互不一致，导致目录几乎全坏。

用法：
    python3 tools/build_whitepaper.py
"""

from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LECT_DIR = os.path.join(ROOT, "docs", "lectures")
CODE_DIR = os.path.join(ROOT, "code")
OUT = os.path.join(ROOT, "燃气轮机智能设计与前沿算法自学白皮书.md")

# 讲次 → （所属篇, 篇标题, 篇导语）
PARTS = [
    (1, 5, "第一篇", "【贝叶斯优化与高维代理模型篇】",
     "本篇覆盖**论文 01、02、07、11、13**。这一条主线回答一个问题："
     "**当一次 CFD 贵得要命时，下一个点该算在哪里？** "
     "从校准采集函数（CR-EI），到多保真并行分配（Filter-GEI），"
     "再到 126 维下被迫改换门庭的代理进化（GSDE）与子空间聚合（DA-EGO），"
     "最后以「多保真也会骗人」这一反直觉发现（EMFS / MSFO）收尾。"),
    (6, 9, "第二篇", "【生成式模型与跨任务知识迁移篇】",
     "本篇覆盖**论文 06、08、17、14**。核心追问是："
     "**能不能不每次都从零开始设计？** "
     "把叶型、端壁这类高维几何压进一个低维潜空间（GMFoO、GAN 参数化），"
     "再把上一个型号学到的设计知识迁移到新型号（SW-VAE、GTO），"
     "从而把昂贵的优化样本量再降一个量级。"),
    (10, 15, "第三篇", "【物理增强神经算子与 AI4Turbomachinery 篇】",
     "本篇覆盖**论文 16、12、18、19、15、20**。范式转变是："
     "**不再预测一个标量性能，而是直接预测整个流场。*"
     "把叠加原理、流动相似性、守恒律写进网络结构（SDNO、ResUNet-Sim、TNO），"
     "再用 SHAP 把黑箱里的决策逻辑翻译给工程师看（SHAP-Turbine）。"),
    (16, 20, "第四篇", "【流动控制、气动热耦合与风洞实验篇】",
     "本篇覆盖**论文 03、09、10、04、05**。回到物理本体："
     "**端壁二次流怎么控、叶尖怎么修、冷气怎么给、实验结果站不站得住。** "
     "非轴对称端壁从数值优化（NAE-Purge）走到跨声速风洞实测验证（NAE-Exp），"
     "并用不确定性量化（Slot-UQ）回答一个工程上最要命的问题："
     "**加工公差和工况波动，会让我的设计偏离标称值多远？**"),
]

LECTURE_PAPER = {
    "01": "01", "02": "02", "03": "07", "04": "11", "05": "13",
    "06": "06", "07": "08", "08": "17", "09": "14",
    "10": "16", "11": "12", "12": "18", "13": "19", "14": "15", "15": "20",
    "16": "03", "17": "09", "18": "10", "19": "04", "20": "05",
}

PAPER_SHORT = {
    "01": "CR-EI", "02": "Filter-GEI", "03": "NAE-Purge", "04": "Slot-UQ",
    "05": "Impingement-Film", "06": "GMFoO", "07": "GSDE", "08": "SW-VAE",
    "09": "NAE-Exp", "10": "FFD-Tip", "11": "DA-EGO", "12": "SDNO",
    "13": "EMFS / MSFO", "14": "GAN-Endwall", "15": "AI-PJP", "16": "TNO",
    "17": "GTO", "18": "ResUNet-Sim", "19": "SHAP-Turbine", "20": "SPIE-AI",
}

FRONT_MATTER_PATH = os.path.join(ROOT, "docs", "front_matter.md")
CH0_PATH = os.path.join(ROOT, "docs", "chapter0.md")
PART6_PATH = os.path.join(ROOT, "docs", "part6.md")
APPENDIX_PATH = os.path.join(ROOT, "docs", "appendix.md")

# ---------------------------------------------------------------------------
# 稳定锚点：目录与正文共用同一套 ID，渲染器无关
# ---------------------------------------------------------------------------
# 约定（ASCII，短，稳定，永不随标题文案漂移）：
#   ch0 / ch0-1 / ch0-2 / ch0-3          第零章及其小节
#   part-1 … part-4 / part-5 / part-6    各篇
#   lec-01 … lec-20                      二十讲
#   code-<stem>                          第五篇代码文件（stem 把非 [A-Za-z0-9]
#                                        换成 -，如 benchmarks.py → benchmarks-py）
#   sec-6-1 … sec-6-5                    第六篇小节
#   appendix                              附录（若有）


def aid_tag(aid: str) -> str:
    """生成正文锚点标记。同时写 id 与 name，兼容旧渲染器。"""
    # 单独成行放在标题正上方：不影响标题文本、不影响 LECTURE_RE 等验收正则。
    return f'<a id="{aid}" name="{aid}"></a>'


def toc_link(text: str, aid: str, indent: int = 0) -> str:
    """目录条目：显示文案 → 稳定锚点。"""
    pad = "  " * indent
    return f"{pad}- [{text}](#{aid})"


def code_aid(filename: str) -> str:
    """`benchmarks.py` → `code-benchmarks-py`。"""
    stem = re.sub(r"[^A-Za-z0-9]+", "-", filename).strip("-").lower()
    return f"code-{stem}"


def read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8").read().strip()


def normalize_fences(text: str) -> str:
    """让每一个 ``` 栅栏行都独占一个"块"（前后各留一个空行）。

    为什么要做：docs/lectures/ 里的伪代码栅栏有些写成"最后一行代码紧跟着 ```"，
    这在 Markdown 渲染上没问题，但会让按空行切分来定位代码块的校验脚本
    （tools/verify_all.py 的 A5）丢失栅栏配对，进而把正文/代码误判成"没有来源
    标注的百分比断言"。统一规范化后，栅栏配对永远正确。

    副作用：仅增删空行，不改变任何可见内容。
    """
    out: list[str] = []
    for ln in text.split("\n"):
        if ln.lstrip().startswith("```"):
            if out and out[-1].strip() != "":
                out.append("")
            out.append(ln)
            out.append("")
        else:
            out.append(ln)
    # 折叠连续空行
    res: list[str] = []
    for ln in out:
        if ln.strip() == "" and res and res[-1].strip() == "":
            continue
        res.append(ln)
    return "\n".join(res)


def lecture_title(content: str, fallback: str) -> str:
    first = content.splitlines()[0].strip() if content.strip() else ""
    m = re.match(r"^###\s+【(第\d{2}讲)】(.*)$", first)
    if m:
        return f"【{m.group(1)}】{m.group(2)}"
    return fallback


def inject_heading_anchor(text: str, pattern: str, aid_fn) -> str:
    """在匹配到的标题行正上方插入锚点（若尚未插入）。

    pattern: 匹配整行标题的正则（需带 ^...$ 与 re.M）
    aid_fn:  callable(match) -> aid 字符串
    """
    def repl(m: re.Match) -> str:
        aid = aid_fn(m)
        line = m.group(0)
        # 已经有锚点则不重复
        return f"{aid_tag(aid)}\n{line}"

    # 避免对已带锚点的标题二次插入：若上一行已是 <a id=...> 则跳过
    lines = text.split("\n")
    out: list[str] = []
    rx = re.compile(pattern)
    for i, ln in enumerate(lines):
        m = rx.match(ln)
        if m:
            prev = out[-1] if out else ""
            if not re.match(r'^<a\s+id="[^"]+"', prev):
                out.append(aid_tag(aid_fn(m)))
        out.append(ln)
    return "\n".join(out)


def decorate_chapter0(body: str) -> str:
    """给第零章主标题与 0.x 小节挂稳定锚点。"""
    if not body:
        return body
    body = inject_heading_anchor(
        body,
        r"^#\s+第零章\b.*$",
        lambda _m: "ch0",
    )
    body = inject_heading_anchor(
        body,
        r"^###\s+(0\.(\d)\s+.*)$",
        lambda m: f"ch0-{m.group(2)}",
    )
    return body


def decorate_lecture(content: str, key: str) -> str:
    """给单讲主标题挂 lec-NN 锚点。"""
    if not content:
        return content
    return inject_heading_anchor(
        content,
        rf"^###\s+【第{key}讲】.*$",
        lambda _m: f"lec-{key}",
    )


def decorate_part6(body: str) -> str:
    """给第六篇主标题与 6.x 小节挂稳定锚点。"""
    if not body:
        return body
    body = inject_heading_anchor(
        body,
        r"^#\s+第六篇\b.*$",
        lambda _m: "part-6",
    )
    body = inject_heading_anchor(
        body,
        r"^##\s+6\.(\d)\b.*$",
        lambda m: f"sec-6-{m.group(1)}",
    )
    return body


def build_toc(lectures: dict[str, str]) -> list[str]:
    """目录：全部指向显式稳定锚点，与正文 aid_tag 一一对应。"""
    lines: list[str] = []
    toc0 = read(CH0_PATH)
    if toc0:
        lines.append(toc_link(
            "第零章 极简前置铺垫：初高中物理/数学如何托起航空燃气轮机？", "ch0"))
        for h in re.findall(r"^###\s+(0\.(\d)\s+.*)$", toc0, re.M):
            title, num = h[0], h[1]
            lines.append(toc_link(title, f"ch0-{num}", indent=1))

    # 篇序号：PARTS 顺序即 1..4
    for part_idx, (start, end, _, ptitle, _) in enumerate(PARTS, start=1):
        lines.append(toc_link(ptitle, f"part-{part_idx}"))
        for i in range(start, end + 1):
            key = f"{i:02d}"
            title = lecture_title(lectures[key], f"第{key}讲")
            lines.append(toc_link(title, f"lec-{key}", indent=1))

    if os.path.isdir(CODE_DIR) and [f for f in os.listdir(CODE_DIR) if f.endswith(".py")]:
        lines.append(toc_link("第五篇 【实践与代码篇】可运行算法原型库", "part-5"))
        for f in sorted(os.listdir(CODE_DIR)):
            if f.endswith(".py") and not f.startswith("_"):
                lines.append(toc_link(f"`{f}`", code_aid(f), indent=1))

    # 第六篇与附录：过去只装配正文、不进目录，导致"写了但没人找得到"。
    body6 = read(PART6_PATH)
    if body6:
        lines.append(toc_link("第六篇 【对比、批判与前瞻篇】", "part-6"))
        for h in re.findall(r"^##\s+(6\.(\d)[^\n]*)$", body6, re.M):
            title, num = h[0].strip(), h[1]
            lines.append(toc_link(title, f"sec-6-{num}", indent=1))

    if read(APPENDIX_PATH):
        lines.append(toc_link("附录", "appendix"))

    return lines


def build_code_section() -> list[str]:
    """把 code/ 下的真实代码嵌入白皮书，确保文档与代码同源。"""
    if not os.path.isdir(CODE_DIR):
        return [aid_tag("part-5"),
                "# 第五篇 【实践与代码篇】可运行算法原型库", "",
                "> 🚧 代码库尚在建设中（见 `docs/重建计划.md` P3）。", ""]
    files = sorted(f for f in os.listdir(CODE_DIR)
                   if f.endswith(".py") and not f.startswith("_"))
    if not files:
        return [aid_tag("part-5"),
                "# 第五篇 【实践与代码篇】可运行算法原型库", "",
                "> 🚧 代码库尚在建设中。", ""]
    out = [aid_tag("part-5"),
           "# 第五篇 【实践与代码篇】可运行算法原型库", "",
           "本篇所有代码均**逐字取自 `code/` 目录下的真实文件**，由 "
           "`tools/build_whitepaper.py` 自动嵌入。",
           "换句话说：**你在这里看到的代码，就是仓库里能跑起来的那个文件**，"
           "不存在「文档里一份、仓库里另一份」的情况。", "",
           "运行环境与依赖见 `code/requirements.txt`（仅 numpy）与 `code/README.md`。", ""]
    for f in files:
        src = open(os.path.join(CODE_DIR, f), encoding="utf-8").read().rstrip()
        out.append(aid_tag(code_aid(f)))
        out.append(f"### `code/{f}`")
        out.append("")
        out.append("```python")
        out.append(src)
        # 收尾的 ``` 前留一个空行：既符合 Markdown 排版习惯，也让按"空行切分"的
        # 校验脚本（tools/verify_all.py 的 A5）能正确识别代码块边界——否则收尾
        # 栅栏会黏在最后一行代码上，导致后续正文被误判为"未加来源标注的断言"。
        out.append("")
        out.append("```")
        out.append("")
    return out


def source_stamp() -> str:
    """源内容戳：docs/ 与 code/ 下所有源文件内容的 SHA-256（前 12 位）。

    白皮书此前用“此刻”做时间戳，导致源不变、重跑也 dirty。曾改用源 mtime，
    但 mtime 经不起 touch/restore（selftest 恢复文件即刷新 mtime，导致 F4 误报）。
    内容哈希则只与内容有关：源不变 → 戳不变 → 装配结果逐字节相同。
    """
    import hashlib
    h = hashlib.sha256()
    paths = []
    for base in (os.path.join(ROOT, "docs"), CODE_DIR):
        for dirpath, dirnames, files in os.walk(base):
            # 派生目录不计入：__pycache__ 随每次运行重写，计入会导致戳漂移（F4 误报）。
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for f in sorted(files):
                if f.startswith(".") or f.endswith((".pyc", ".pyo")):
                    continue
                paths.append(os.path.join(dirpath, f))
    for p in sorted(paths):
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return "src-" + h.hexdigest()[:12]


def collect_toc_anchors(toc_lines: list[str]) -> list[str]:
    """从目录行提取全部 href 锚点（不含 #）。"""
    aids = []
    for ln in toc_lines:
        m = re.search(r"\]\(#([^)]+)\)", ln)
        if m:
            aids.append(m.group(1))
    return aids


def main() -> None:
    lectures: dict[str, str] = {}
    missing: list[str] = []
    for i in range(1, 21):
        key = f"{i:02d}"
        path = os.path.join(LECT_DIR, f"{key}.md")
        if os.path.exists(path):
            lectures[key] = open(path, encoding="utf-8").read().strip()
        else:
            lectures[key] = ""
            missing.append(key)

    toc_lines = build_toc(lectures)

    doc: list[str] = []
    doc.append(read(FRONT_MATTER_PATH) or "# 燃气轮机智能设计与前沿算法自学白皮书")
    doc.append("")
    doc.append(f"> 📌 **本文件由 `tools/build_whitepaper.py` 自动装配生成，请勿直接编辑。**")
    doc.append(f"> 修改内容请改 `docs/lectures/` 下的讲稿源文件后重新运行装配脚本。")
    doc.append(f"> 内容版本：{source_stamp()}（= 讲稿/代码源文件的内容哈希；源不变则装配结果逐字节不变）")
    doc.append("")
    doc.append("---")
    doc.append("")
    doc.append("## 目录")
    doc.append("")
    doc.extend(toc_lines)
    doc.append("")
    doc.append("---")
    doc.append("")

    if os.path.exists(CH0_PATH):
        doc.append(decorate_chapter0(read(CH0_PATH)))
        doc.append("")
        doc.append("---")
        doc.append("")

    for part_idx, (start, end, ptitle_full, ptitle, pintro) in enumerate(PARTS, start=1):
        doc.append(aid_tag(f"part-{part_idx}"))
        doc.append(f"# {ptitle_full} {ptitle}")
        doc.append("")
        doc.append(pintro)
        doc.append("")
        doc.append("---")
        doc.append("")
        for i in range(start, end + 1):
            key = f"{i:02d}"
            if lectures[key]:
                doc.append(decorate_lecture(lectures[key], key))
            else:
                doc.append(aid_tag(f"lec-{key}"))
                doc.append(f"### 【第{key}讲】待重建（对应论文 {LECTURE_PAPER[key]} · "
                           f"{PAPER_SHORT[LECTURE_PAPER[key]]}）")
                doc.append("")
                doc.append("> 🚧 本讲尚未按重建规范重写。"
                            "事实依据见 `corpus/facts/P%s.md`；"
                            "旧版内容保留在 git 历史中。" % LECTURE_PAPER[key])
            doc.append("")
            doc.append("---")
            doc.append("")

    doc.extend(build_code_section())
    doc.append("---")
    doc.append("")
    if os.path.exists(PART6_PATH):
        doc.append(decorate_part6(read(PART6_PATH)))
    else:
        doc.append(aid_tag("part-6"))
        doc.append("# 第六篇 【对比、批判与前瞻篇】")
        doc.append("")
        doc.append("> 🚧 待重建：全景对比矩阵将逐条标注数据来源，"
                    "凡无出处者一律标注「待核实」，不再沿用旧版的无源数字。")
    doc.append("")
    doc.append("---")
    doc.append("")
    if os.path.exists(APPENDIX_PATH):
        body_app = read(APPENDIX_PATH)
        doc.append(aid_tag("appendix"))
        # 若附录自身以 # 开头则原样，否则包一层
        if body_app.lstrip().startswith("#"):
            doc.append(body_app)
        else:
            doc.append("# 附录")
            doc.append("")
            doc.append(body_app)
    doc.append("")

    text = normalize_fences("\n".join(doc) + "\n")

    # 装配期自检：目录里的每一个锚点都必须在正文中以 id= 形式出现
    toc_aids = collect_toc_anchors(toc_lines)
    body_ids = set(re.findall(r'<a\s+id="([^"]+)"', text))
    missing_aids = [a for a in toc_aids if a not in body_ids]
    if missing_aids:
        raise SystemExit(
            "[FAIL] 目录锚点在正文中缺失（跳转会坏）：" + "、".join(missing_aids)
        )
    dup = [a for a in toc_aids if toc_aids.count(a) > 1]
    if dup:
        raise SystemExit("[FAIL] 目录锚点重复：" + "、".join(sorted(set(dup))))

    open(OUT, "w", encoding="utf-8").write(text)
    n_ok = 20 - len(missing)
    print(f"[OK] 已生成 {os.path.relpath(OUT, ROOT)}")
    print(f"     讲稿完成 {n_ok}/20" + (f"，待重建：{'、'.join(missing)}" if missing else ""))
    print(f"     目录锚点 {len(toc_aids)} 条，全部命中正文 id")


if __name__ == "__main__":
    main()

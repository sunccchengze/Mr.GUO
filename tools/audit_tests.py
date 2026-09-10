#!/usr/bin/env python3
"""检测卷系统性审计：结构 / 分值配平 / 答案覆盖 / 得分点配平（层级感知）。

用法：python3 tools/audit_tests.py
覆盖：检测题/ 全部 21 套（第零章 + 第01~20讲，每套 = 检测卷 + 答案与评分）。

检查项：
  S1 卷头必含「满分 100 分」「建议用时 30 分钟」
  S2 卷·客观节：每题分 × 题数 == 节标注「共 X 分」
  S3 卷·主观节：单题分之和 == 节标注「共 X 分」（仅 1 题且题面未标分时由节总分推得）
  S4 全卷合计 == 100
  S5 题号 1..N 连续无跳号
  S6 答案题号集合 == 卷题号集合（不缺不多）
  S7 答案主观题标注分（或配给合计）== 卷面该题分值
  S8 得分点层级配平：每个子标题(X分)下属带分值列表项之和 == X；顶层配给之和 == 题分
退出码：0 = 全过；1 = 有问题。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDIR = os.path.join(ROOT, '检测题')
IDS = ['第零章'] + ['第%02d讲' % i for i in range(1, 21)]

SEC_HDR = re.compile(r'^## ([一二三四五六])、(.+?)（(.*?)）\s*$')
QRE = re.compile(r'^\*\*(\d+)[.．](?:（(\d+)分）)?\*\*')
SUBJ_HDR = re.compile(r'^### 第(\d+)题(?:（(\d+)分）)?')
ALLOC = re.compile(r'（(\d+)分(?=[，,）)])')


def parse_test(path):
    text = open(path, encoding='utf-8').read()
    secs, cur = [], None
    for ln in text.split('\n'):
        s = ln.strip()
        m = SEC_HDR.match(s)
        if m and '自查' not in s and '成绩评定' not in s:
            cur = {'name': m.group(1), 'title': m.group(2), 'info': m.group(3), 'qs': []}
            secs.append(cur)
            continue
        if s.startswith('## ') and not SEC_HDR.match(s):
            cur = None
            continue
        if cur is not None:
            m2 = QRE.match(s)
            if m2:
                cur['qs'].append((int(m2.group(1)), int(m2.group(2)) if m2.group(2) else None))
    has100 = bool(re.search(r'满分\s*100\s*分', text))
    has30 = bool(re.search(r'建议用时\s*30\s*分钟', text))
    return text, secs, has100, has30


def section_pts(info):
    m = re.search(r'每题\s*(\d+)\s*分', info)
    per = int(m.group(1)) if m else None
    m = re.search(r'共\s*(\d+)\s*分', info)
    total = int(m.group(1)) if m else None
    return per, total


def parse_answer(path):
    text = open(path, encoding='utf-8').read()
    secs, cur = [], None
    for ln in text.split('\n'):
        s = ln.strip()
        m = re.match(r'^## ([一二三四五六])、(.+?)（(.*?)）\s*$', s)
        if m:
            cur = {'name': m.group(1), 'title': m.group(2), 'info': m.group(3), 'obj': [], 'subj': []}
            secs.append(cur)
            continue
        if s.startswith('## '):
            cur = None
            continue
        if cur is None:
            continue
        m2 = re.match(r'^\|\s*题号\s*\|(.+)\|', s)
        if m2:
            cur['obj'].extend([int(x) for x in re.findall(r'(\d+)', m2.group(1))])
            continue
        m4 = SUBJ_HDR.match(s)
        if m4:
            cur['subj'].append((int(m4.group(1)), int(m4.group(2)) if m4.group(2) else None))
            continue
        m3 = re.match(r'^\|\s*(\d+)\s*\|', s)
        if m3:
            cur['obj'].append(int(m3.group(1)))
    return text, secs


def subj_block(atext, qnum):
    """截取答案中第 qnum 题的完整评分块。"""
    pat = re.compile(rf'^### 第{qnum}题.*?(?=^### |^## |\Z)', re.M | re.S)
    mm = pat.search(atext)
    return mm.group(0) if mm else None


def check_allocations(block, qpts):
    """层级配平。

    规则（避免误伤"按文字给分"的条目）：
      叶子层：子标题(X分)下属带分值项之和 ≤ X；若下属项全部带分值则必须 == X。
      顶层：  顶层显式配给（子标题分值 + 顶层带分值列表项）之和 ≤ 题分；
              若顶层所有段均带分值，则必须 == 题分。
    返回 (问题列表, 顶层配给列表)
    """
    problems = []
    lines = block.split('\n')
    top_alloc = []          # 顶层显式配给（子标题分值 + 顶层带分值列表项）
    top_segments = 0        # 顶层段数（子标题 + 顶层列表项，含按文字给分者）
    subheads = []           # [pts, [tagged items], n_untagged]
    cur_sub = None
    for ln in lines[1:]:    # 跳过块首行（### 题头）
        s = ln.strip()
        if s.startswith('**') and ALLOC.search(s):
            pts = sum(int(x) for x in ALLOC.findall(s))
            cur_sub = [pts, [], 0]
            subheads.append(cur_sub)
            top_alloc.append(pts)
            top_segments += 1
            continue
        if s.startswith('- ') or s.startswith('* '):
            tags = [int(x) for x in ALLOC.findall(s)]
            body = s[2:].lstrip()
            lead = ALLOC.search(body)
            if lead:
                rest = body[lead.end():].lstrip('）)')
                is_lead = lead.start() == 0 or rest[:1] in '：:'
            else:
                is_lead = False
            if is_lead and len(tags) > 1:
                # 行首/冒号式 (X分) = 该条配给；行内其余为子分解（和不得超出行首分值）
                alloc = int(lead.group(1))
                subs = tags[1:]
                if sum(subs) > alloc:
                    problems.append(f'行内子分解{subs}合计{sum(subs)} 超出行首({alloc}分)：{s[:24]}…')
                tags = [alloc]
            if cur_sub is not None:
                if tags:
                    cur_sub[1].extend(tags)
                else:
                    cur_sub[2] += 1
            else:
                top_segments += 1
                if tags:
                    top_alloc.extend(tags)
    for (sp, items, n_un) in subheads:
        tagged_sum = sum(items)
        if tagged_sum > sp:
            problems.append(f'子标题({sp}分)下属配给{items}合计{tagged_sum} 超额')
        elif items and n_un == 0 and tagged_sum != sp:
            # 下属项全部带分值时才断言相等；无下属项 = 自足子标题（分值在标题行）
            problems.append(f'子标题({sp}分)下属配给{items}合计{tagged_sum} ≠ {sp}')
    top_sum = sum(top_alloc)
    n_tagged_top = len(top_alloc)
    if top_sum > qpts:
        problems.append(f'顶层配给{top_alloc}合计{top_sum} 超出题分{qpts}')
    elif n_tagged_top == top_segments and top_sum != qpts:
        problems.append(f'顶层配给{top_alloc}合计{top_sum} ≠ 题分{qpts}（顶层{top_segments}段均带分值）')
    return problems, top_alloc


def main():
    issues, ok, grand = [], [], 0
    for idn in IDS:
        tp = os.path.join(TDIR, f'{idn}-检测卷.md')
        ap = os.path.join(TDIR, f'{idn}-答案与评分.md')
        if not (os.path.exists(tp) and os.path.exists(ap)):
            issues.append(f'{idn}: 缺文件')
            continue
        ttext, tsecs, has100, has30 = parse_test(tp)
        atext, asecs = parse_answer(ap)
        tag = idn
        if not has100:
            issues.append(f'{tag}: S1 卷头缺「满分 100 分」')
        if not has30:
            issues.append(f'{tag}: S1 卷头缺「建议用时 30 分钟」')

        total, all_q, tp_map = 0, [], {}
        for s in tsecs:
            per, st = section_pts(s['info'])
            n = len(s['qs'])
            all_q += [q for q, _ in s['qs']]
            if st is None:
                issues.append(f'{tag}: S2/S3 节{s["name"]}《{s["title"]}》未标注总分')
                for (q, p) in s['qs']:
                    tp_map[q] = p
                continue
            if per is not None:
                calc = per * n
                if calc != st:
                    issues.append(f'{tag}: S2 节{s["name"]} 每题{per}×{n}题={calc} ≠ 标注{st}')
                for (q, p) in s['qs']:
                    tp_map[q] = p
                total += st
            else:
                known = sum(p for _, p in s['qs'] if p is not None)
                unknown = [q for q, p in s['qs'] if p is None]
                if len(unknown) == 1:
                    rest = st - known
                    if rest <= 0:
                        issues.append(f'{tag}: S3 节{s["name"]} 题{unknown} 推得分值非正（{rest}）')
                    else:
                        tp_map[unknown[0]] = rest
                elif len(unknown) == 0:
                    if known != st:
                        issues.append(f'{tag}: S3 节{s["name"]} 单题分合计{known} ≠ 标注{st}')
                else:
                    issues.append(f'{tag}: S3 节{s["name"]} 题{unknown} 均缺单题分值且无法唯一推得')
                for (q, p) in s['qs']:
                    if p is not None:
                        tp_map[q] = p
                total += st
        if total != 100:
            issues.append(f'{tag}: S4 全卷分值合计 = {total} ≠ 100')
        grand += total
        if all_q != list(range(1, len(all_q) + 1)):
            issues.append(f'{tag}: S5 题号不连续: {all_q}')

        obj_ans, subj_ans = [], []
        for s in asecs:
            obj_ans += s['obj']
            subj_ans += [q for q, _ in s['subj']]
            for (qnum, qpts) in s['subj']:
                if qnum not in tp_map:
                    continue
                if qpts is None:
                    # 答案题头未标分：用卷面分值做 S8 校验基准
                    qpts = tp_map[qnum]
                elif tp_map[qnum] is not None and tp_map[qnum] != qpts:
                    issues.append(f'{tag}: S7 答案第{qnum}题标注{qpts}分 ≠ 卷面{tp_map[qnum]}分')
                if qpts is None:
                    issues.append(f'{tag}: S7/S8 第{qnum}题卷面与答案均无法确定分值')
                    continue
                block = subj_block(atext, qnum)
                if not block:
                    issues.append(f'{tag}: S8 未找到第{qnum}题评分块')
                    continue
                probs, _ = check_allocations(block, qpts)
                for pb in probs:
                    issues.append(f'{tag}: S8 第{qnum}题 {pb}')
        test_set, ans_set = set(all_q), set(obj_ans) | set(subj_ans)
        if test_set - ans_set:
            issues.append(f'{tag}: S6 答案缺题: {sorted(test_set - ans_set)}')
        if ans_set - test_set:
            issues.append(f'{tag}: S6 答案多出: {sorted(ans_set - test_set)}')
        ok.append(f'{tag}: 卷面{total}分 题{len(all_q)}道 客观{len(set(obj_ans))} 主观{len(set(subj_ans))}')

    print('=== 检测卷结构与分值审计（tools/audit_tests.py）===')
    for l in ok:
        print('OK  ' + l)
    print()
    if issues:
        print(f'!!! 发现问题 {len(issues)} 处:')
        for i in issues:
            print(' -', i)
        sys.exit(1)
    print('!!! 全部通过：S1–S8 零违例')
    print('全卷合计（应=2100）:', grand)


if __name__ == '__main__':
    main()

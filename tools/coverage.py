"""逐字稿覆盖检查：确认 transcript.md 的每一段都已写进文章，或明确排除并写明原因。

用法：python -P coverage.py <transcript.md> <覆盖表.csv> [--article 成稿.md]

覆盖表.csv（UTF-8，表头固定）：
  时间戳,章节,处理,说明
  00:00:02,一、纽曼追问公平,写入,
  00:12:40,三、平均差异很小,合并,与 00:11:50 同一论点，并入同一段
  01:58:10,,排除,广告口播
处理只能是：写入 / 合并 / 排除。合并、排除必须写说明。

检查项：
  ERROR  逐字稿段落没有出现在覆盖表中；覆盖表里有逐字稿中不存在的时间戳；处理值非法；合并或排除缺少说明；
         --article 时，"写入/合并"的章节在成稿中找不到对应标题
  WARN   排除时长超过全片的 8%；单条排除超过 3 分钟（长段排除最容易藏着"嫌它太尖锐"的遗漏）
退出码：有 ERROR 时为 1。
"""
import argparse
import csv
import re
import sys
from pathlib import Path

TS = re.compile(r'^\[(\d{2}:\d{2}:\d{2})\]\s')
VALID = {'写入', '合并', '排除'}


def sec(t):
    h, m, s = (int(x) for x in t.split(':'))
    return h * 3600 + m * 60 + s


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('transcript', type=Path)
    ap.add_argument('table', type=Path)
    ap.add_argument('--article', type=Path)
    a = ap.parse_args()

    stamps = [m.group(1) for line in a.transcript.read_text(encoding='utf-8-sig').splitlines() if (m := TS.match(line))]
    if not stamps:
        sys.exit('逐字稿中没有 [HH:MM:SS] 段落')
    with a.table.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))

    errors, warns = [], []
    table = {}
    for i, r in enumerate(rows, 2):
        t = (r.get('时间戳') or '').strip()
        act = (r.get('处理') or '').strip()
        note = (r.get('说明') or '').strip()
        if t in table:
            errors.append(f'第 {i} 行：时间戳 {t} 重复')
        table[t] = (r.get('章节') or '').strip(), act, note
        if act not in VALID:
            errors.append(f'第 {i} 行：处理"{act}"不是 写入/合并/排除')
        elif act != '写入' and not note:
            errors.append(f'第 {i} 行：{t} {act}，但没有写说明')

    stamp_set = set(stamps)
    missing = [t for t in stamps if t not in table]
    extra = [t for t in table if t not in stamp_set]
    if missing:
        errors.append(f'{len(missing)} 段逐字稿未登记：{", ".join(missing[:15])}{" …" if len(missing) > 15 else ""}')
    if extra:
        errors.append(f'覆盖表中有 {len(extra)} 个逐字稿里不存在的时间戳：{", ".join(extra[:10])}')

    # 每段时长 = 到下一段开始；最后一段按 30 秒估计
    dur = {t: (sec(stamps[k + 1]) if k + 1 < len(stamps) else sec(t) + 30) - sec(t) for k, t in enumerate(stamps)}
    total = sum(dur.values())
    excluded = [(t, dur[t], table[t][2]) for t in stamps if t in table and table[t][1] == '排除']
    ex_total = sum(d for _, d, _ in excluded)
    if total and ex_total / total > 0.08:
        warns.append(f'排除内容占全片 {ex_total / total:.1%}（{ex_total // 60} 分钟），超过 8%：逐条复核是否真的与主题无关')
    run_start, run_len = None, 0
    for t in stamps + ['']:
        if t and t in table and table[t][1] == '排除':
            run_start = run_start or t
            run_len += dur[t]
            continue
        if run_start and run_len > 180:
            warns.append(f'从 {run_start} 起连续排除 {run_len // 60} 分 {run_len % 60} 秒：长段排除需要逐句复核')
        run_start, run_len = None, 0

    if a.article:
        heads = [l.lstrip('#').strip() for l in a.article.read_text(encoding='utf-8-sig').splitlines() if l.startswith('#')]
        chapters = {table[t][0] for t in table if table[t][1] in ('写入', '合并') and table[t][0]}
        for ch in sorted(chapters):
            if not any(ch in h or h in ch for h in heads):
                errors.append(f'覆盖表中的章节"{ch}"在成稿标题中找不到')

    print(f'逐字稿 {len(stamps)} 段；已登记 {len(stamps) - len(missing)} 段；排除 {len(excluded)} 段，约 {ex_total // 60} 分钟（占 {ex_total / max(total, 1):.1%}）')
    for t, d, note in excluded:
        print(f'  排除 [{t}] {d} 秒：{note}')
    for w in warns:
        print(f'[WARN] {w}')
    for e in errors:
        print(f'[ERROR] {e}')
    print(f'ERROR {len(errors)}，WARN {len(warns)}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())

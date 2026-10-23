"""逐字稿覆盖检查：确认 transcript.md 的每一段都已写进文章，或明确排除并写明原因。

用法：python -P coverage.py <transcript.md> <覆盖表.csv ...> [--article 成稿.md]
  覆盖表可以给多个（或用通配符，如 "核对\覆盖表_*.csv"）：每章的核对各写一份，最后一起检查。
  章与章交界处同一段可以登记两次；只要有一行是"写入/合并"就算写进了文章。

覆盖表.csv（UTF-8，表头固定）：
  时间戳,章节,处理,说明
  00:00:02,一、纽曼追问公平,写入,
  00:12:40,三、平均差异很小,合并,与 00:11:50 同一论点，并入同一段
  01:58:10,,排除,广告口播
处理只能是：写入 / 合并 / 排除。合并、排除必须写说明。

检查项：
  ERROR  逐字稿段落没有出现在覆盖表中；覆盖表里有逐字稿中不存在的时间戳；处理值非法；合并或排除缺少说明；
         同一份表里同一时间戳出现两次；
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
    ap.add_argument('tables', nargs='+')
    ap.add_argument('--article', type=Path)
    a = ap.parse_args()

    stamps = [m.group(1) for line in a.transcript.read_text(encoding='utf-8-sig').splitlines() if (m := TS.match(line))]
    if not stamps:
        sys.exit('逐字稿中没有 [HH:MM:SS] 段落')
    paths = []
    for pat in a.tables:
        p = Path(pat)
        hits = sorted(p.parent.glob(p.name)) if any(c in p.name for c in '*?[') else [p]
        paths += [h for h in hits if h.is_file()]
    if not paths:
        sys.exit(f'找不到覆盖表：{a.tables}')

    errors, warns = [], []
    table = {}
    for path in paths:
        seen = set()
        with path.open(encoding='utf-8-sig', newline='') as f:
            for i, r in enumerate(csv.DictReader(f), 2):
                t = (r.get('时间戳') or '').strip()
                act = (r.get('处理') or '').strip()
                note = (r.get('说明') or '').strip()
                where = f'{path.name} 第 {i} 行'
                if t in seen:
                    errors.append(f'{where}：时间戳 {t} 在同一份表里重复')
                seen.add(t)
                if act not in VALID:
                    errors.append(f'{where}：处理"{act}"不是 写入/合并/排除')
                elif act != '写入' and not note:
                    errors.append(f'{where}：{t} {act}，但没有写说明')
                # 跨表重复（章节交界）：有任何一行写入/合并，就以它为准
                if t not in table or (table[t][1] == '排除' and act in ('写入', '合并')):
                    table[t] = (r.get('章节') or '').strip(), act, note

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
        lines = a.article.read_text(encoding='utf-8-sig').splitlines()
        heads = [(i, len(l) - len(l.lstrip('#')), l.lstrip('#').strip()) for i, l in enumerate(lines) if l.startswith('#')]
        ch_secs = {}
        for t in stamps:
            if t in table and table[t][1] in ('写入', '合并') and table[t][0]:
                ch_secs[table[t][0]] = ch_secs.get(table[t][0], 0) + dur[t]
        density = {}
        for ch, secs in ch_secs.items():
            hit = next((h for h in heads if ch in h[2] or h[2] in ch), None)
            if not hit:
                errors.append(f'覆盖表中的章节"{ch}"在成稿标题中找不到')
                continue
            i, level, _ = hit
            end = next((j for j, lv, _ in heads if j > i and lv <= level), len(lines))
            chars = len(re.findall(r'[一-鿿]', '\n'.join(lines[i + 1:end])))
            density[ch] = (chars / max(secs / 60, 0.5), chars, secs)
        # 章节密度：每分钟访谈写成多少字。明显低于中位数的章节，多半有整段被概括掉
        if len(density) >= 3:
            med = sorted(v[0] for v in density.values())[len(density) // 2]
            print(f'章节密度中位数：每分钟访谈 {med:.0f} 字')
            for ch, (d, chars, secs) in density.items():
                if d < med * 0.5 and secs >= 120:
                    warns.append(f'"{ch}"偏薄：{secs // 60} 分钟访谈只写了 {chars} 字（每分钟 {d:.0f} 字，不到中位数一半），逐段对照逐字稿查遗漏')

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

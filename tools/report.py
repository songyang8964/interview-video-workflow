"""汇总一期的润色、盲读和配图记录，给主会话写最终报告用。主会话只读这份摘要，不必逐个打开记录文件。

用法：python -P report.py <素材目录> [--top 5]
  读取：润色记录*.json、盲读挑刺*.json、盲读/*.json、配图计划.json
  输出：润色改动数、盲读挑出数、配图核对情况，以及改动最大的几处（改前 → 改后）
"""
import argparse
import difflib
import json
import sys
from pathlib import Path


def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', type=Path)
    ap.add_argument('--top', type=int, default=5)
    a = ap.parse_args()
    f = a.folder

    edits = []
    for p in sorted(f.glob('润色记录*.json')):
        data = load(p) or []
        edits += [e for e in data if isinstance(e, dict) and 'before' in e and 'after' in e]
    blind = 0
    for p in sorted(f.glob('盲读挑刺*.json')) + sorted((f / '盲读').glob('*.json')):
        if p.name.endswith('_判定.json'):
            continue
        data = load(p)
        if isinstance(data, dict):
            blind += sum(len(v) for v in data.values() if isinstance(v, list))
        elif isinstance(data, list):
            blind += len(data)
    plan = load(f / '配图计划.json') or []

    print(f'润色改动：{len(edits)} 处')
    by_step = {}
    for e in edits:
        by_step[e.get('step', '未标步骤')] = by_step.get(e.get('step', '未标步骤'), 0) + 1
    if by_step:
        print('  按步骤：' + '，'.join(f'{k} {v} 处' for k, v in by_step.items()))
    print(f'盲读挑出：{blind} 处')
    unchecked = [x.get('file') for x in plan if not x.get('visual_check')]
    print(f'配图：{len(plan)} 张，未核对 {len(unchecked)} 张' + (f'：{unchecked}' if unchecked else ''))

    # 改动大小 = 1 - 相似度，再乘以长度，优先挑出既长又改得多的
    scored = sorted(edits, key=lambda e: (1 - difflib.SequenceMatcher(None, e['before'], e['after']).ratio()) * max(len(e['before']), len(e['after'])), reverse=True)
    if scored:
        print(f'\n改动最大的 {min(a.top, len(scored))} 处：')
        for i, e in enumerate(scored[:a.top], 1):
            print(f'\n{i}. [{e.get("chapter", "")}] {e.get("reason", "")}')
            print(f'   改前：{e["before"]}')
            print(f'   改后：{e["after"]}')


if __name__ == '__main__':
    main()

"""把 yt-dlp 下载的 json3 字幕整理成带时间戳、分段的逐字稿 transcript.md。

用法：python -P transcript.py <素材目录> [--lang en]
  读取 <素材目录>/source.info.json 和 source.<lang>*.json3，写出 <素材目录>/transcript.md。
  人工字幕优先于自动字幕；自动字幕中优先 <lang>-orig（原始语音识别，未经机翻）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

PARA_MIN_MS = 30_000   # 段落至少 30 秒，遇到停顿才换段
PARA_MAX_MS = 60_000   # 段落最长 60 秒，超过后在下一个词处强制换段
GAP_MS = 1_200         # 两个词之间超过这个间隔视为停顿


def ts(ms):
    s = int(ms // 1000)
    return f'{s // 3600:02}:{s % 3600 // 60:02}:{s % 60:02}'


def pick_subtitle(folder: Path, info: dict, lang: str):
    manual = [k for k in (info.get('subtitles') or {}) if k == lang or k.startswith(lang + '-')]
    candidates = []
    if manual:
        candidates += [folder / f'source.{k}.json3' for k in sorted(manual, key=len)]
    candidates += [folder / f'source.{lang}-orig.json3', folder / f'source.{lang}.json3']
    candidates += sorted(folder.glob(f'source.{lang}*.json3'))
    for path in candidates:
        if path.is_file():
            return path, bool(manual) and path.stem.split('.', 1)[1] in manual
    raise SystemExit(f'在 {folder} 中找不到 source.{lang}*.json3 字幕文件')


def words_from_json3(path: Path):
    """返回 [(绝对毫秒, 文本)]。自动字幕按词带偏移；人工字幕按行，去掉滚动重复。"""
    events = json.loads(path.read_text(encoding='utf-8')).get('events', [])
    words, last_line = [], ''
    for ev in events:
        segs = ev.get('segs')
        if not segs or ev.get('aAppend'):
            continue
        start = ev.get('tStartMs', 0)
        if len(segs) == 1 and 'tOffsetMs' not in segs[0]:
            line = segs[0].get('utf8', '').replace('\n', ' ').strip()
            if not line:
                continue
            if last_line and line.startswith(last_line):   # 滚动字幕：只保留新增部分
                line = line[len(last_line):].strip()
            last_line = segs[0].get('utf8', '').replace('\n', ' ').strip()
            if line:
                words.append((start, line))
            continue
        for seg in segs:
            text = seg.get('utf8', '').replace('\n', ' ').strip()
            if text:
                words.append((start + seg.get('tOffsetMs', 0), text))
    return words


def paragraphs(words):
    paras, cur, cur_start, prev_ms = [], [], None, None
    for ms, text in words:
        if cur:
            span = ms - cur_start
            pause = prev_ms is not None and ms - prev_ms >= GAP_MS
            if (span >= PARA_MIN_MS and pause) or span >= PARA_MAX_MS:
                paras.append((cur_start, ' '.join(cur)))
                cur, cur_start = [], None
        if not cur:
            cur_start = ms
        cur.append(text)
        prev_ms = ms
    if cur:
        paras.append((cur_start, ' '.join(cur)))
    return [(ms, re.sub(r'\s+', ' ', t).strip()) for ms, t in paras]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', type=Path)
    ap.add_argument('--lang', default='en')
    args = ap.parse_args()
    folder = args.folder
    info_path = folder / 'source.info.json'
    info = json.loads(info_path.read_text(encoding='utf-8-sig')) if info_path.is_file() else {}
    sub, is_manual = pick_subtitle(folder, info, args.lang)
    paras = paragraphs(words_from_json3(sub))
    chapters = info.get('chapters') or []

    out = [f"# {info.get('title', folder.name)}", '']
    meta = [('频道', info.get('channel') or info.get('uploader')),
            ('发布日期', info.get('upload_date') and f"{info['upload_date'][:4]}-{info['upload_date'][4:6]}-{info['upload_date'][6:]}"),
            ('时长', info.get('duration') and ts(info['duration'] * 1000)),
            ('链接', info.get('webpage_url')),
            ('字幕来源', f"{sub.name}（{'人工字幕' if is_manual else '自动字幕，无说话人标注'}）")]
    out += [f'- {k}：{v}' for k, v in meta if v] + ['']
    if chapters:
        out += ['## 视频章节', ''] + [f"- [{ts(c['start_time'] * 1000)}] {c['title']}" for c in chapters] + ['']
    if info.get('description'):
        out += ['## 视频简介', '', info['description'].strip(), '']
    out += ['## 逐字稿', '']
    ch_iter = iter(sorted(chapters, key=lambda c: c['start_time']))
    next_ch = next(ch_iter, None)
    for ms, text in paras:
        while next_ch and next_ch['start_time'] * 1000 <= ms:
            out += [f"### [{ts(next_ch['start_time'] * 1000)}] {next_ch['title']}", '']
            next_ch = next(ch_iter, None)
        out += [f'[{ts(ms)}] {text}', '']
    target = folder / 'transcript.md'
    target.write_text('\n'.join(out), encoding='utf-8')
    words = sum(len(t.split()) for _, t in paras)
    print(f'已写出 {target}：{len(paras)} 段，约 {words} 词，字幕 {sub.name}')


if __name__ == '__main__':
    sys.exit(main())

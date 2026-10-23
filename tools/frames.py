"""访谈配图：联系表粗筛 → 按时间点取原图并过画质 → 按锚点插入文章。

只依赖 FFmpeg（含 ffprobe）、pillow 和 numpy。取原帧和画质检查的代码移植自 video-notes
（https://github.com/songyang8964/video-notes 的 media.extract_frame 与 vision.quality.score）。

  python -P frames.py sheet  <video> <输出目录> --start 00:10:00 --end 00:30:00 [--step 10]
      每 step 秒取一张缩略图，拼成带时间戳的联系表（每张 40 格），供模型一次看一大段。
  python -P frames.py grab   <video> <配图计划.json> <assets目录>
      计划为列表，每项至少有 seconds、file；画质不合格时在 ±0.5/1/2/3 秒内找替代帧。
      结果写回计划文件：load_source_frame、quality、path、sha256。
  python -P frames.py insert <文章.md> <配图计划.json>
      每项按 anchor（正文中的一段原文）定位段落，默认插在段后（before: true 时插在段前）。
      图片块：![alt](<assets目录名>/file) + 空行 + *caption*。已插入过的图片不会重复插入。
"""
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw


# —— 以下移植自 video-notes：取原分辨率帧并记录真实时间戳、画质评分 ——

def _run(args, timeout=None):
    result = subprocess.run([str(a) for a in args], capture_output=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} exit {result.returncode}: {result.stderr[-1200:]}')
    return result


def _probe(path):
    data = json.loads(_run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', path]).stdout)
    return dict(duration_ms=round(float(data['format']['duration']) * 1000))


def _extract_frame(video, ms, target, duration_ms):
    """在 ms 处取一帧原分辨率 JPEG，返回 {'actual_ms', 'requested_ms', 'pts_ticks'}。"""
    meta = Path(target).with_suffix('.frame.json')
    if not (meta.is_file() and Path(target).is_file()):
        result = _run(['ffmpeg', '-hide_banner', '-ss', f'{ms / 1000:.3f}', '-copyts', '-i', video, '-an',
                       '-frames:v', '1', '-vf', 'showinfo', '-fps_mode', 'vfr', '-q:v', '2', '-update', '1', '-y',
                       target], timeout=120)
        first = re.search(r'\bn:\s*0\s+pts:\s*(\d+)\s+pts_time:([\d.]+)', result.stderr)
        if not first or not Path(target).is_file():
            raise RuntimeError(f'frame extraction failed at {ms} ms')
        meta.write_text(json.dumps(dict(actual_ms=round(float(first[2]) * 1000), pts_ticks=int(first[1]),
                                        requested_ms=int(ms))), encoding='utf-8')
    data = json.loads(meta.read_text(encoding='utf-8'))
    if not 0 <= data['actual_ms'] < duration_ms:
        raise RuntimeError('frame PTS outside the source')
    return data


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _score(path, width=640):
    """{'quality','blur','brightness','reject','reason'}：过暗、过亮、模糊（拉普拉斯方差过低）判为不合格。"""
    with Image.open(path) as img:
        img = img.convert('L')
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)))
        gray = np.asarray(img).astype(np.float64)
    brightness = float(gray.mean())
    lap = -4 * gray[1:-1, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1]
    blur = float(lap.var()) if lap.size else 0.0
    for bad, reason in ((brightness < 12.0, 'too_dark'), (brightness > 243.0, 'too_bright'), (blur < 8.0, 'blurry')):
        if bad:
            return dict(quality=0.0, blur=blur, brightness=brightness, reject=True, reason=reason)
    return dict(quality=min(1.0, math.log10(1 + blur) / 3), blur=blur, brightness=brightness, reject=False, reason='')


media = SimpleNamespace(probe=_probe, extract_frame=_extract_frame, sha256=_sha256)
quality = SimpleNamespace(score=_score)


def parse_ts(s):
    if re.fullmatch(r'[\d.]+', str(s)):
        return float(s)
    parts = [float(p) for p in str(s).split(':')]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt(sec):
    sec = int(sec)
    return f'{sec // 3600:02}:{sec % 3600 // 60:02}:{sec % 60:02}'


def cmd_sheet(a):
    start, end, step = parse_ts(a.start), parse_ts(a.end), a.step
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(start), '-to', str(end),
                        '-i', str(a.video), '-vf', f'fps=1/{step},scale=320:-2', '-q:v', '4',
                        str(Path(tmp) / '%05d.jpg')], check=True)
        thumbs = sorted(Path(tmp).glob('*.jpg'))
        per, cols = 40, 5
        for page in range(0, len(thumbs), per):
            batch = thumbs[page:page + per]
            w, h = Image.open(batch[0]).size
            rows = (len(batch) + cols - 1) // cols
            sheet = Image.new('RGB', (cols * w, rows * (h + 22)), 'white')
            draw = ImageDraw.Draw(sheet)
            for k, p in enumerate(batch):
                x, y = (k % cols) * w, (k // cols) * (h + 22)
                sheet.paste(Image.open(p), (x, y))
                draw.text((x + 4, y + h + 4), fmt(start + (page + k) * step), fill='black')
            name = out / f'sheet_{fmt(start + page * step).replace(":", "")}.jpg'
            sheet.save(name, quality=80)
            print(name)


def cmd_grab(a):
    video, plan_path, assets = Path(a.video), Path(a.plan), Path(a.assets)
    assets.mkdir(parents=True, exist_ok=True)
    duration = media.probe(video)['duration_ms']
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    work = Path(tempfile.mkdtemp(prefix='frames_'))
    for item in plan:
        base = parse_ts(item['seconds'])
        best = None
        for off in (0, 0.5, -0.5, 1, -1, 2, -2, 3, -3):
            ms = int((base + off) * 1000)
            if not 0 <= ms < duration:
                continue
            tmp = work / f'{ms}.jpg'
            frame = media.extract_frame(video, ms, tmp, duration)
            q = quality.score(tmp)
            if best is None or q['quality'] > best[2]['quality']:
                best = (tmp, frame, q)
            # 只有画质不合格时才找替代帧。不能"挑最清晰的"：访谈画面普遍偏暗、得分低，
            # 那样会漂到片尾字幕卡这类明亮但无关的画面（斯诺登篇 00:24:04 曾漂到 00:24:07 的订阅卡）
            if not q['reject']:
                best = (tmp, frame, q)
                break
        tmp, frame, q = best
        target = assets / item['file']
        Image.open(tmp).convert('RGB').save(target, quality=90)
        item.update(load_source_frame=frame, quality=q, path=str(target), sha256=media.sha256(target))
        flag = f"  ⚠ {q['reason']}" if q['reject'] else ''
        print(f"{item['file']}: {fmt(frame['actual_ms'] / 1000)} quality={q['quality']:.2f}{flag}")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')


def cmd_insert(a):
    md, plan = Path(a.md), json.loads(Path(a.plan).read_text(encoding='utf-8-sig'))
    text = md.read_text(encoding='utf-8-sig')
    paras = text.split('\n\n')
    missing = []
    for item in plan:
        rel = f"{Path(item['path']).parent.name}/{item['file']}"
        if rel in text:
            continue
        anchor = (item.get('anchor') or '').strip()
        # 空锚点会匹配任意段落，把图插到开头；按"找不到锚点"处理，等定稿后补上
        idx = next((i for i, p in enumerate(paras) if anchor in p), None) if anchor else None
        if idx is None:
            missing.append(item['file'])
            continue
        block = f"![{item.get('alt', '')}]({rel})\n\n*{item['caption']}*"
        paras.insert(idx if item.get('before') else idx + 1, block)
        text = '\n\n'.join(paras)
    md.write_text('\n\n'.join(paras), encoding='utf-8')
    print(f'已插入 {len(plan) - len(missing)} 张' + (f'；找不到锚点：{missing}' if missing else ''))
    return 1 if missing else 0


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sheet')
    s.add_argument('video'); s.add_argument('out')
    s.add_argument('--start', default='0'); s.add_argument('--end', required=True)
    s.add_argument('--step', type=float, default=10)
    g = sub.add_parser('grab')
    g.add_argument('video'); g.add_argument('plan'); g.add_argument('assets')
    i = sub.add_parser('insert')
    i.add_argument('md'); i.add_argument('plan')
    a = ap.parse_args()
    return {'sheet': cmd_sheet, 'grab': cmd_grab, 'insert': cmd_insert}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())

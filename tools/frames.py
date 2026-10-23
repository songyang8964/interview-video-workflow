"""访谈配图：联系表粗筛 → 按时间点取原图并过画质 → 按锚点插入文章。

依赖已安装的 video_notes（只用它的 media.extract_frame 和 vision.quality.score）。

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
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from video_notes import media
from video_notes.vision import quality


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
        idx = next((i for i, p in enumerate(paras) if item['anchor'] in p), None)
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

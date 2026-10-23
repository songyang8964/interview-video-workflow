"""把一章的写作材料预先拼成一个文件，写作者读一次就够，不用分几次去查。

用法：python -P pack_chapter.py <素材目录> [章号 ...]
  不写章号就打包全部章节。每章输出 <素材目录>/chapters/NN.brief.md，内容依次是：
    1. 本章提纲（从 分析素材包.md 中截取），附候选金句原文
    2. 本章时间范围内的逐字稿段落
    3. 上一章正文的最后一段（上一章还没写时省略）
    4. 译名表全文

提纲格式约定（interview-analysis 产出时遵守）：
  每章以一行加粗标题开头，后跟时间范围，例如
  **一、手机关着屏，也一直在喊"我在这里"** [00:00:00–00:07:59]
  到下一章标题或下一个 ## 标题为止，都算本章提纲。
"""
import re
import sys
from pathlib import Path

HEAD = re.compile(r'^\*\*(.+?)\*\*\s*\[(\d{1,2}:\d{2}:\d{2})\s*[–—\-~]\s*(\d{1,2}:\d{2}:\d{2})\]')
PARA = re.compile(r'^\[(\d{2}:\d{2}:\d{2})\]\s')


def sec(t):
    h, m, s = (int(x) for x in t.split(':'))
    return h * 3600 + m * 60 + s


def outline(pack_text):
    """返回 [(标题, 起, 止, 提纲文本)]，按出现顺序。"""
    lines = pack_text.splitlines()
    chapters, cur = [], None
    for line in lines:
        m = HEAD.match(line.strip())
        if m:
            if cur:
                chapters.append(cur)
            cur = [m.group(1), m.group(2), m.group(3), [line]]
            continue
        if cur and line.startswith('## '):
            chapters.append(cur)
            cur = None
            continue
        if cur:
            cur[3].append(line)
    if cur:
        chapters.append(cur)
    return [(t, a, b, '\n'.join(body).strip()) for t, a, b, body in chapters]


def quotes_section(pack_text):
    """素材包里标题含"金句"的那一节（提纲常按编号引用金句，要把原文一起带上）。"""
    m = re.search(r'^##[^\n]*金句[^\n]*\n(.*?)(?=^## |\Z)', pack_text, flags=re.S | re.M)
    return m.group(1).strip() if m else ''


def transcript_slice(text, start, end):
    """起止时间内的逐字稿段落；起点前最近的一段也带上，免得切掉句子开头。"""
    paras = [(m.group(1), line) for line in text.splitlines() if (m := PARA.match(line))]
    s, e = sec(start), sec(end)
    keep = [line for t, line in paras if s <= sec(t) <= e]
    before = [line for t, line in paras if sec(t) < s]
    if before:
        keep.insert(0, before[-1])
    return '\n\n'.join(keep)


def last_paragraph(path):
    if not path.is_file():
        return ''
    text = re.sub(r'<!--.*?-->', '', path.read_text(encoding='utf-8'), flags=re.S)
    paras = [p.strip() for p in text.split('\n\n') if p.strip() and not p.strip().startswith(('#', '>', '!', '*', '---'))]
    return paras[-1] if paras else ''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    wanted = {int(x) for x in sys.argv[2:]}
    pack = (folder / '分析素材包.md').read_text(encoding='utf-8-sig')
    transcript = (folder / 'transcript.md').read_text(encoding='utf-8-sig')
    glossary_path = folder / '译名表.md'
    glossary = glossary_path.read_text(encoding='utf-8-sig') if glossary_path.is_file() else '（尚无译名表）'
    chapters = outline(pack)
    quotes = quotes_section(pack)
    if not chapters:
        sys.exit('分析素材包.md 里没有找到章节标题。格式应为：**一、标题** [00:00:00–00:07:59]')
    out_dir = folder / 'chapters'
    out_dir.mkdir(exist_ok=True)
    for n, (title, start, end, body) in enumerate(chapters, 1):
        if wanted and n not in wanted:
            continue
        prev = last_paragraph(out_dir / f'{n - 1:02}.md') if n > 1 else ''
        parts = [f'# 第 {n:02} 章写作材料：{title}', f'时间范围：[{start}–{end}]', '',
                 '## 1. 本章提纲', '', body, '']
        if quotes:
            parts += ['### 候选金句（提纲里的编号对应这里）', '', quotes, '']
        parts += ['## 2. 本章逐字稿（只用来核对数字、人名和细节，不要逐句翻译）', '', transcript_slice(transcript, start, end), '']
        if prev:
            parts += ['## 3. 上一章结尾（用于衔接）', '', prev, '']
        parts += ['## 4. 译名表（人名、术语一律照此翻译）', '', glossary.strip(), '']
        target = out_dir / f'{n:02}.brief.md'
        target.write_text('\n'.join(parts), encoding='utf-8')
        print(f'{target.name}：{title}  [{start}–{end}]  {len(target.read_text(encoding="utf-8"))} 字符')


if __name__ == '__main__':
    main()

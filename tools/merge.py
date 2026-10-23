"""把各章合并成成稿：chapters/01.md、02.md…… 依次拼接，去掉写作者留下的 HTML 注释，末尾接上 文末附注.md。

用法：python -P merge.py <素材目录> <成稿.md>
  文末附注.md（可选）放在素材目录里，内容是"文末附注"和"复核说明"两节。
  只合并文件名是纯数字的章节文件（01.md），不会把 01.brief.md 这类材料混进来。
"""
import re
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    folder, target = Path(sys.argv[1]), Path(sys.argv[2])
    chapters = sorted(p for p in (folder / 'chapters').glob('*.md') if re.fullmatch(r'\d+', p.stem))
    if not chapters:
        sys.exit(f'{folder / "chapters"} 下没有 01.md 这样的章节文件')
    parts = [re.sub(r'<!--.*?-->', '', p.read_text(encoding='utf-8-sig'), flags=re.S).strip() for p in chapters]
    appendix = folder / '文末附注.md'
    if appendix.is_file():
        parts.append('---\n\n' + appendix.read_text(encoding='utf-8-sig').strip())
    if target.exists():
        # 已有成稿（可能插过图、人工改过），另存一份，不覆盖
        backup = target.with_name(target.stem + '.上一版.md')
        backup.write_text(target.read_text(encoding='utf-8-sig'), encoding='utf-8')
        print(f'原成稿已备份为 {backup.name}')
    text = '\n\n'.join(parts) + '\n'
    target.write_text(text, encoding='utf-8')
    zh = len(re.findall(r'[一-鿿]', text))
    print(f'已合并 {len(chapters)} 章{"和文末附注" if appendix.is_file() else ""} → {target}（中文 {zh} 字）')


if __name__ == '__main__':
    main()

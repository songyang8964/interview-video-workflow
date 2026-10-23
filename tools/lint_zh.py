"""访谈长文中文质量检查：翻译腔、AI 味、评判性措辞、英文残留、长句等。

用法：python -P lint_zh.py <文章.md> [--json 输出.json] [--max 30] [--full]
  --full 用于合并后的成稿：另查开头和结尾的原始链接、文末"复核说明"。
  ERROR = 违反硬规则（禁用词、评判性措辞、每章双语金句超过 2 条），必须改到 0。
  WARN  = 可疑写法，润色时逐条判断：改，或说明保留理由。
退出码：有 ERROR 时为 1。
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# (等级, 规则名, 正则, 提示)
PATTERNS = [
    # —— writing-style 禁止清单 ——
    ('ERROR', '禁用词', r'众所周知|值得注意的是|值得一提的是|不得不说|综上所述|让我们拭目以待|在当今.{0,10}时代|随着.{1,12}的(?:发展|到来|兴起)|赋能|闭环|抓手|底层逻辑|颗粒度',
     '删除或换成普通说法'),
    ('ERROR', '禁用词', r'(?:^|[。！？\n])\s*总之|(?:^|[。！？\n])\s*总而言之', '公式化结尾，删除'),
    # —— 偏向：评判性措辞（docs/项目规则.md） ——
    ('ERROR', '评判性措辞', r'不十分清晰|不太清晰|逻辑关联不(?:太)?紧密|逻辑(?:并)?不严密|站不住脚|缺乏(?:证据|依据)|夸大其词|危言耸听|阴谋论',
     '编辑在替读者下判断；删掉，或移到文末附注并注明依据'),
    ('WARN', '不对等动词', r'声称|辩称|宣称|鼓吹|妄称|所谓的',
     '核对：另一方是否用的是"指出/表示"？受访者自己用过这个词吗？'),
    # —— 翻译腔 ——
    ('WARN', '翻译腔', r'进行了?(?:讨论|分析|研究|评估|调查|解释|描述|比较|反思|回应|沟通|交流|批评|辩论|说明|阐述)',
     '"进行+动词"：直接用动词，如"进行了讨论"→"讨论了"'),
    ('WARN', '翻译腔', r'对.{1,15}进行', '"对……进行……"：改成动宾结构'),
    ('WARN', '翻译腔', r'被.{1,20}所(?:[一-鿿])', '"被……所……"：改主动句或去掉"所"'),
    ('WARN', '翻译腔', r'作为一(?:个|名|位)', '"as a ..."直译：多数可删，或改"身为""他是……"'),
    ('WARN', '翻译腔', r'一种.{1,15}的(?:方式|方法|感觉|状态|过程)', '"a ... way"直译：改成动词说法'),
    ('WARN', '翻译腔', r'在.{1,15}(?:方面|层面|意义上|程度上)', '"in terms of"直译：多数可删'),
    ('WARN', '翻译腔', r'在.{1,20}的情况下', '"in the case of"：改"如果……""……时"'),
    ('WARN', '翻译腔', r'当.{1,20}的时候', '"when"从句直译：改"……时"或直接并列'),
    ('WARN', '翻译腔', r'这是一个.{1,15}的(?:问题|事情|过程|观点|话题|东西)', '"this is a ... thing"：直接说判断'),
    ('WARN', '翻译腔', r'使得|从而|基于此|由此可见|与此同时|换句话说|某种程度上|本质上|事实上|毫无疑问|显而易见',
     '书面连接词堆砌：口语访谈里大多可删'),
    ('WARN', '翻译腔', r'他(?:们)?(?:的)?(?:观点|看法|立场)是', '"his view is"：改"他认为"'),
    ('WARN', '翻译腔', r'(?:非常|十分|极其|相当)地', '副词+"地"多余'),
    ('WARN', '翻译腔', r'(?:我|你|他|她|我们|他们)(?:必须|需要)要', '"必须要/需要要"重复'),
    ('WARN', '翻译腔', r'(?:这|那)(?:就)?是为什么', '"that\'s why"直译：改"所以""难怪"'),
    ('WARN', '翻译腔', r'(?:让|使)(?:他|她|我|我们|他们|人们)?(?:感到|觉得)', '"make sb feel"直译：直接写感受'),
    ('WARN', 'AI 味', r'不仅仅是.{1,20}更是|不是.{1,12}而是.{1,12}更是|这不仅.{1,15}更', '排比式拔高，访谈实录里少用'),
    ('WARN', 'AI 味', r'深刻(?:地)?(?:揭示|反映|体现)|发人深省|引人深思|耐人寻味|令人动容', '替读者抒情，删掉'),
    # —— 以下规则来自历次返工记录（见 interview-video/references/历史错误清单.md） ——
    ('ERROR', '评判性措辞', r'万能钥匙|利用了?(?:这个)?平台|个人化(?:的)?诠释|嘴硬|黑子|老生常谈|陈词滥调|偷换概念|自相矛盾',
     '暗中贬低受访者（Rupert、DHH 两篇都因此返工）：改成中性陈述'),
    ('ERROR', '元叙述', r'字幕|逐字稿|自动转录|转录稿|整理成文|整理者|笔者|本文(?:将|会|试图)|(?:本|原|这段|该)(?:视频|节目)中',
     '正文不写整理过程（泽连斯基一篇因"字幕中不完整"被要求删）：直接写内容；需要说明的放文末附注'),
    ('WARN', '编造细节', r'笑着说|笑了笑|顿了顿|停顿了?一下|停了一下|叹了口气|沉默(?:了)?片刻|眼眶|哽咽|声音(?:低|颤)|语气(?:变得|逐渐)|让人停顿|第一次公开',
     '神态、动作和"首次披露"最容易编造（泽连斯基一篇删过"笑着说""他停了一下"）：逐字稿或画面没有依据就删'),
    ('WARN', 'AI 味', r'(?:构成|带来)了.{0,10}(?:重量|分量)|值得(?:关注|留意)的(?:信号|是)|有几个.{0,6}值得|定海神针|一锤定音|振聋发聩|掷地有声',
     '总结腔和用力过猛的词：改成平实的叙述'),
    ('WARN', '口语填充', r'我是说|你知道(?:吗|[，,])|对吧|说实话|(?:^|[，。“"])就是这样[。，！”"]|老实说|嗯|好吧|你懂的|怎么说呢',
     '英文口头禅逐字带进中文（泽连斯基一篇"就是这样"出现 11 次）：大多删掉'),
    ('WARN', '自问自答', r'为什么[？?]\s*因为', '"Why? Because…"句式，一章最多留一处'),
]
# 文末附注、复核说明里允许谈整理过程和字幕
APPENDIX_ONLY_OK = {'元叙述', '编造细节'}
APPENDIX_HEAD = re.compile(r'附注|复核|资料说明|核查|来源说明|参考资料')

ENGLISH_RUN = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:[\s,]+[A-Za-z][A-Za-z'’\-]*){5,}")
QUOTE = re.compile(r'[“"]([^”"]{1,400})[”"]')
SENT_SPLIT = re.compile(r'(?<=[。！？；])')
EDITOR_NOTE = re.compile(r'^\s*[\[【（(]?\s*编者注')


def strip_inline(text):
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'`[^`]*`', '', text)
    return re.sub(r'https?://\S+', '', text)


def cjk_len(s):
    return len(re.findall(r'[一-鿿]', s))


def lint(path: Path, full=False):
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    # 章节标题层级：出现至少 3 次的最浅标题层级（有的文章用 ##，有的用 ###）
    levels = Counter(len(m.group(1)) for l in lines if (m := re.match(r'^(#{2,4})\s', l)))
    ch_level = min((lv for lv, n in levels.items() if n >= 3), default=2)
    issues, chapter, in_code, in_appendix = [], '（开头）', False, False
    bilingual = Counter()
    zh_chars = 0
    dashes = 0
    feichang = 0
    seen_paren_en = defaultdict(list)

    def add(level, rule, lineno, snippet, hint):
        issues.append(dict(level=level, rule=rule, line=lineno, chapter=chapter, snippet=snippet.strip()[:90], hint=hint))

    for i, raw in enumerate(lines, 1):
        if raw.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code or not raw.strip():
            continue
        if raw.startswith('#'):
            if APPENDIX_HEAD.search(raw):
                in_appendix = True
            if raw.startswith('#' * ch_level + ' '):
                chapter = raw[ch_level + 1:].strip()
            continue
        line = strip_inline(raw)
        is_quote_block = raw.lstrip().startswith('>')
        is_caption = raw.strip().startswith('*') and raw.strip().endswith('*') and '原视频' in raw
        zh_chars += cjk_len(line)
        dashes += line.count('——')
        feichang += line.count('非常')

        # 英文金句块：中文行 + 英文行；英文行计数，不算残留
        if is_quote_block:
            if ENGLISH_RUN.search(line) and cjk_len(line) < 5:
                bilingual[chapter] += 1
                continue
        else:
            for m in ENGLISH_RUN.finditer(line):
                add('WARN', '英文残留', i, m.group(0), '正文对话应改为中文；只有金句块保留英文')

        quoted = [m.span() for m in QUOTE.finditer(line)]
        for level, rule, pat, hint in PATTERNS:
            if rule in APPENDIX_ONLY_OK and (in_appendix or is_caption or 'http' in raw):
                continue  # 文末附注、图注、来源行可以谈字幕和整理过程
            for m in re.finditer(pat, line):
                ctx = line[max(0, m.start() - 15): m.end() + 15]
                # 受访者原话里的口头禅不算编辑违规，降为提醒
                in_quote = any(a <= m.start() < b for a, b in quoted)
                add('WARN' if in_quote else level, rule + ('（引语内）' if in_quote else ''), i, ctx, hint)

        if line.count('——') >= 3:
            add('WARN', '破折号过多', i, line[:60], '一段 3 个以上破折号：改用逗号、句号或拆句')

        for sent in SENT_SPLIT.split(line):
            n = cjk_len(sent)
            if n > 90 and not is_caption:
                add('WARN', '长句', i, sent[:60] + '…', f'一句 {n} 字：拆成两三句')
            for clause in re.split(r'[，、：,]', sent):
                if clause.count('的') >= 4:
                    add('WARN', '"的"字堆叠', i, clause[:60], '长定语：拆出去单独成句')

        for m in QUOTE.finditer(line):
            if cjk_len(m.group(1)) > 100:
                add('WARN', '长引语', i, m.group(1)[:60] + '…', '引号里的长句最容易直译：改成转述，或只引最关键的半句')

        if EDITOR_NOTE.match(line) and cjk_len(line) > 160:
            add('WARN', '编者注过长', i, line[:60] + '…', f'编者注 {cjk_len(line)} 字：压到一两句，背景放文末附注')

        if line.count('他说') + line.count('她说') >= 3:
            add('WARN', '"他说"重复', i, line[:60], '同段三次以上"他说"：合并转述或换说法')

        for m in re.finditer(r'[（(]([A-Z][A-Za-z .\'’\-]{2,40})[）)]', line):
            seen_paren_en[m.group(1).strip()].append(i)

    for term, where in seen_paren_en.items():
        if len(where) > 1:
            issues.append(dict(level='WARN', rule='英文注释重复', line=where[1], chapter='', snippet=f'（{term}）出现 {len(where)} 次，行 {where[:6]}',
                               hint='英文原名只在首次出现时标注'))

    for ch, n in bilingual.items():
        if n > 2:
            issues.append(dict(level='ERROR', rule='双语金句超额', line=0, chapter=ch, snippet=f'本章 {n} 条双语金句', hint='每章最多 2 条，其余改为中文转述'))

    # 结构（interview-writing 的硬性结构要求）
    heads = [(i, l[ch_level + 1:].strip()) for i, l in enumerate(lines, 1) if l.startswith('#' * ch_level + ' ')]
    for i, h in heads:
        bare = re.sub(r'^[一二三四五六七八九十百\d]+[、.．]\s*', '', h)
        if cjk_len(bare) < 8 and not re.search(r'结尾|附注|复核|核查|写在最后', bare):
            issues.append(dict(level='WARN', rule='小标题过泛', line=i, chapter=h, snippet=h,
                               hint='小标题 = 讨论了什么 + 核心结论，如"Google 的技术被别人先商业化了"'))
    if full:
        body = '\n'.join(lines)
        first_head = heads[0][0] if heads else len(lines)
        if not any(re.search(r'youtube\.com|youtu\.be', l) for l in lines[:first_head]):
            issues.append(dict(level='ERROR', rule='缺来源', line=1, chapter='（开头）', snippet='开头没有原始视频链接',
                               hint='开头三件事：受访者是谁、聊了什么、访谈来源（节目、日期、链接）'))
        if not any(re.search(r'youtube\.com|youtu\.be', l) for l in lines[-40:]):
            issues.append(dict(level='ERROR', rule='缺来源', line=len(lines), chapter='（结尾）', snippet='结尾没有原始视频链接',
                               hint='结尾附上原始链接'))
        if not re.search(r'复核说明', body):
            issues.append(dict(level='ERROR', rule='缺复核说明', line=len(lines), chapter='（结尾）', snippet='文末没有"复核说明"',
                               hint='文末写明润色、审查各改了多少处，以及未解决项'))

    per_k = dashes / max(zh_chars, 1) * 1000
    fc_k = feichang / max(zh_chars, 1) * 1000
    stats = dict(zh_chars=zh_chars, dashes=dashes, dashes_per_1000=round(per_k, 2), feichang_per_1000=round(fc_k, 2),
                 bilingual_quotes=dict(bilingual))
    if per_k > 4:
        # 成稿时为硬错误：用户多次因破折号过多要求返工，不接受"系列一贯风格"之类的理由
        issues.append(dict(level='ERROR' if full else 'WARN', rule='破折号密度', line=0, chapter='', snippet=f'每千字 {per_k:.1f} 个"——"',
                           hint='每千字 ≤ 4 个；破折号插入语是英文句法，改逗号、冒号、括号或拆句'))
    if fc_k > 1.0:
        issues.append(dict(level='WARN', rule='"非常"过多', line=0, chapter='', snippet=f'"非常" {feichang} 次（每千字 {fc_k:.1f}）',
                           hint='删掉一半，或换成具体说法'))
    body_heads = [h for _, h in heads if not APPENDIX_HEAD.search(h)]
    if full and len(body_heads) >= 4 and sum(bilingual.values()) < len(body_heads) // 2:
        issues.append(dict(level='WARN', rule='金句太少', line=0, chapter='', snippet=f'{len(body_heads)} 章只有 {sum(bilingual.values())} 条双语金句',
                           hint='每章 1–2 条：挑有画面感、能独立传播的原话（Rupert 一篇被指出金句太少）'))
    return issues, stats


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('file', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--max', type=int, default=30, help='每条规则最多打印几处')
    ap.add_argument('--full', action='store_true', help='成稿模式：另查开头/结尾来源链接、复核说明')
    args = ap.parse_args()
    issues, stats = lint(args.file, args.full)

    by_rule = Counter((x['level'], x['rule']) for x in issues)
    print(f"{args.file.name}：中文 {stats['zh_chars']} 字，破折号每千字 {stats['dashes_per_1000']}")
    print('汇总：' + '；'.join(f'{lv} {r} {n}' for (lv, r), n in sorted(by_rule.items())) or '无问题')
    printed = Counter()
    for x in sorted(issues, key=lambda x: (x['level'] != 'ERROR', x['rule'], x['line'])):
        key = (x['level'], x['rule'])
        printed[key] += 1
        if printed[key] > args.max:
            continue
        print(f"[{x['level']}] {x['rule']} L{x['line']} 「{x['snippet']}」 → {x['hint']}")
    if args.json:
        args.json.write_text(json.dumps(dict(stats=stats, issues=issues), ensure_ascii=False, indent=1), encoding='utf-8')
    errors = sum(1 for x in issues if x['level'] == 'ERROR')
    print(f'ERROR {errors}，WARN {len(issues) - errors}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())

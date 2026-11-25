# -*- coding: utf-8 -*-
"""md_prep.py — محاضرة markdown ← أسطر مصدر مرقّمة [L001] (SPEC §8). دوال نقية."""
from __future__ import annotations

import json
import re
from typing import Dict, List

import markers as M

MAX_LINE = 600
_ABBR = {'dr', 'mr', 'mrs', 'ms', 'prof', 'e.g', 'i.e', 'vs', 'fig', 'approx', 'cf', 'al', 'st', 'no', 'etc'}
_IMG = re.compile(r'!\[([^\]]*)\]\([^)]*\)')
_LINK = re.compile(r'\[([^\]]+)\]\([^)]*\)')
_AUTOLINK = re.compile(r'<(?:https?://|mailto:)[^>]+>')
_LIST = re.compile(r'^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$')
_HEAD = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
_SEP = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')
_FENCE = re.compile(r'^\s*(```|~~~)')


def _inline(s: str) -> str:
    s = _IMG.sub(lambda m: m.group(1), s)
    s = _LINK.sub(lambda m: m.group(1), s)
    s = _AUTOLINK.sub('', s)
    s = re.sub(r'<br\s*/?>', ' ', s, flags=re.I)
    s = re.sub(r'<!--.*?-->', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def split_sentences(text: str, limit: int = MAX_LINE) -> List[str]:
    """يقسّم عند حدود الجُمل فقط (R-63)؛ الجملة الواحدة الأطول من الحد بتفضل سطر واحد."""
    if len(text) <= limit:
        return [text]
    parts, last = [], 0
    for m in re.finditer(r'[.!?؟…۔]+["”’)\]]*\s+', text):
        toks = text[last:m.start()].split()
        w = (toks[-1] if toks else '').lower().strip('.')
        if w in _ABBR or re.fullmatch(r'[a-z]', w):
            continue
        parts.append(text[last:m.end()].strip())
        last = m.end()
    if text[last:].strip():
        parts.append(text[last:].strip())
    lines, cur = [], ''
    for s in parts:
        if cur and len(cur) + 1 + len(s) > limit:
            lines.append(cur)
            cur = s
        else:
            cur = (cur + ' ' + s).strip()
    if cur:
        lines.append(cur)
    return lines or [text]


def prepare(md_text: str) -> Dict:
    md_text = (md_text or '').replace('\r\n', '\n').replace('\r', '\n')
    if md_text.startswith('\ufeff'):
        md_text = md_text[1:]
    raw: List[dict] = []
    para: List[str] = []
    quote: List[str] = []
    in_code = False

    def flush_para():
        if para:
            t = _inline(' '.join(para))
            if t:
                raw.append(dict(kind='para', text=t))
            para.clear()

    def flush_quote():
        if quote:
            t = _inline(' '.join(quote))
            if t:
                raw.append(dict(kind='quote', text=t))
            quote.clear()

    last_list = None
    for ln in md_text.split('\n'):
        if _FENCE.match(ln):
            flush_para(); flush_quote()
            in_code = not in_code
            last_list = None
            continue
        if in_code:
            if ln.strip():
                raw.append(dict(kind='code', text=ln.rstrip()))
            continue
        s = ln.rstrip()
        if not s.strip():
            flush_para(); flush_quote()
            last_list = None
            continue
        m = _HEAD.match(s.strip())
        if m:
            flush_para(); flush_quote()
            raw.append(dict(kind='heading', text=_inline(m.group(2)), level=len(m.group(1))))
            last_list = None
            continue
        if s.lstrip().startswith('>'):
            flush_para()
            body = re.sub(r'^\s*(>\s?)+', '', s)
            if body.strip():
                quote.append(body.strip())
            else:
                flush_quote()
            last_list = None
            continue
        flush_quote()
        if s.strip().startswith('|') or (s.count('|') >= 2 and not _LIST.match(s)):
            flush_para()
            if not _SEP.match(s):
                cells = [_inline(c) for c in s.strip().strip('|').split('|')]
                t = ' | '.join(c for c in cells)
                if t.strip(' |'):
                    raw.append(dict(kind='table', text=t))
            last_list = None
            continue
        lm = _LIST.match(s)
        if lm:
            flush_para()
            t = _inline(lm.group(2))
            if t:
                raw.append(dict(kind='list', text=t))
                last_list = raw[-1]
            continue
        if last_list is not None and s.startswith((' ', '\t')):      # استكمال عنصر قايمة
            last_list['text'] = (last_list['text'] + ' ' + _inline(s)).strip()
            continue
        last_list = None
        para.append(s.strip())
    flush_para(); flush_quote()

    # تقسيم الأسطر الطويلة بين الجمل
    expanded: List[dict] = []
    for r in raw:
        if r['kind'] in ('para', 'list', 'quote') and len(r['text']) > MAX_LINE:
            for piece in split_sentences(r['text']):
                expanded.append(dict(r, text=piece))
        else:
            expanded.append(r)
    total = len(expanded)
    width = max(3, len(str(total)))
    lines = []
    for i, r in enumerate(expanded, 1):
        d = dict(n=i, kind=r['kind'], text=r['text'])
        if 'level' in r:
            d['level'] = r['level']
        lines.append(d)
    rendered = '\n'.join('[%s] %s' % (M.fmt_src(l['n'], width), l['text']) for l in lines)
    return dict(lines=lines, total=total, rendered=rendered, width=width)


def build_meta(a: Dict) -> str:
    """بلوك META: من إجابات البوت (R-64). القيم الناقصة = غير محدد."""
    def g(k):
        v = str(a.get(k) or '').replace('|', '/').strip()
        return v or 'غير محدد'
    warm = 'on' if a.get('warmup', True) not in (False, 'off', 0, '0') else 'off'
    return 'META:\n%s | warmup=%s' % (' | '.join(g(k) for k in
                                                 ('number', 'title', 'doctor', 'course', 'level', 'goal', 'focus')), warm)


def build_user_message(meta_text: str, rendered: str) -> str:
    return '%s\n\nLECTURE_START\n%s\nLECTURE_END' % (meta_text.strip(), rendered)


def _ranges(nums: List[int]):
    out, st, prev = [], None, None
    for n in nums:
        if st is None:
            st = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((st, prev)); st = prev = n
    if st is not None:
        out.append((st, prev))
    return out


def coverage_report(pr: 'M.ParseResult', total: int, lines: List[dict] = None) -> Dict:
    """لكل موضوع الأسطر اللي بيدّعيها + الأسطر الناقصة كمدى مع معاينة 60 حرف (R-65)."""
    cov = M.coverage(pr, total)
    byn = {l['n']: l['text'] for l in (lines or [])}
    unc = []
    for a, b in cov['uncovered']:
        prev = byn.get(a, '')
        unc.append(dict(start=a, end=b, preview=(prev[:60] + ('…' if len(prev) > 60 else ''))))
    per = {tid: ', '.join('%s-%s' % (M.fmt_src(a), M.fmt_src(b)) for a, b in rg) for tid, rg in cov['claims'].items()}
    txt = []
    for u in unc:
        r = M.fmt_src(u['start']) if u['start'] == u['end'] else '%s-%s' % (M.fmt_src(u['start']), M.fmt_src(u['end']))
        txt.append('• %s%s' % (r, (' — ' + u['preview']) if u['preview'] else ''))
    return dict(per_topic=per, uncovered=unc, overlaps=cov['overlaps'], text='\n'.join(txt))


def dumps_lines(lines: List[dict]) -> str:
    return json.dumps(lines, ensure_ascii=False)

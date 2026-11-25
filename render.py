# -*- coding: utf-8 -*-
"""المواضيع والتوقيتات: schema لـ Gemini + تنضيف/تصحيح التوقيتات + تنسيق رسائل تليجرام (HTML)."""
import bisect, html, json, re
from subs import hms, hms_to_sec

SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'lecture_title': {'type': 'STRING'},
        'sections': {'type': 'ARRAY', 'items': {
            'type': 'OBJECT',
            'properties': {
                'title': {'type': 'STRING'},
                'emoji': {'type': 'STRING'},
                'items': {'type': 'ARRAY', 'items': {
                    'type': 'OBJECT',
                    'properties': {'time': {'type': 'STRING'}, 'label': {'type': 'STRING'}, 'key': {'type': 'BOOLEAN'}},
                    'required': ['time', 'label', 'key']}},
            },
            'required': ['title', 'emoji', 'items']}},
    },
    'required': ['lecture_title', 'sections'],
}

_KEYCAPS = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'}
_BANNED = re.compile(r'\b(axis|axes|section|part|chapter)\b\s*\d*\s*[:\-–—.]?\s*', re.I)


def keycap(n):
    return ''.join(_KEYCAPS[c] for c in str(n))


def parse_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r'\{.*\}', text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _clean_title(t):
    t = _BANNED.sub('', (t or '').strip())
    t = re.sub(r'^\s*[\d]+\s*[.):\-–]\s*', '', t)
    return t.strip(' -–—:') or 'Topic'


def _first_emoji(e):
    e = (e or '').strip()
    m = re.match(r'(?:[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF][\uFE0F\u200D]?)+', e)
    return (m.group(0) if m else '📌')[:8]


def normalize(js, cue_starts, duration):
    """يصلّح التوقيتات (snap لأقرب سطر في التفريغ)، يرتب، يشيل المكرر. يرجّع (title, sections)."""
    starts = sorted(set(cue_starts))
    secs_out = []
    for sec in js.get('sections', []):
        items = []
        for it in sec.get('items', []):
            t = hms_to_sec(it.get('time', ''))
            label = re.sub(r'\s+', ' ', str(it.get('label', ''))).strip(' -–—•▸')
            if t is None or not label:
                continue
            if duration and t > duration + 5:
                continue
            if starts:
                i = bisect.bisect_left(starts, t)
                near = [starts[j] for j in (i - 1, i) if 0 <= j < len(starts)]
                best = min(near, key=lambda s: abs(s - t))
                if abs(best - t) <= 60:
                    t = best
            items.append((t, label, bool(it.get('key'))))
        if not items:
            continue
        items.sort(key=lambda x: x[0])
        secs_out.append(dict(title=_clean_title(sec.get('title')), emoji=_first_emoji(sec.get('emoji')), items=items))
    secs_out.sort(key=lambda s: s['items'][0][0])
    seen, final = set(), []
    for s in secs_out:
        its = []
        for t, label, key in s['items']:
            k = (round(t), label.lower())
            if k in seen:
                continue
            seen.add(k)
            its.append((t, label, key))
        if its:
            s['items'] = its
            final.append(s)
    title = re.sub(r'\s+', ' ', str(js.get('lecture_title', '') or '')).strip()
    return title, final


def stats(sections):
    return len(sections), sum(len(s['items']) for s in sections)


def _block(n, sec, items=None, cont=False, k0=0):
    items = sec['items'] if items is None else items
    head = '%s <b>%s. %s</b>%s' % (sec['emoji'], n, html.escape(sec['title']), ' …' if cont else '')
    lines = ['<blockquote>%s</blockquote>' % head]
    for k, (t, label, key) in enumerate(items, k0 + 1):
        lab = html.escape(label)
        lines.append('<b>%d.%d</b>  <code>%s</code> ▸ %s' % (n, k, hms(t), ('⭐ <b>%s</b>' % lab) if key else lab))
    return '\n'.join(lines)


def render_messages(title, sections, duration, limit=3500):
    n_sec, n_items = stats(sections)
    head = '<b>🕒 Topics &amp; Timestamps</b>'
    if title:
        head += '\n<i>%s</i>' % html.escape(title)
    head += '\n<i>⏱ %s  ·  %d topics  ·  %d timestamps</i>' % (hms(duration), n_sec, n_items)
    blocks = []
    for i, sec in enumerate(sections, 1):
        b = _block(i, sec)
        if len(b) <= limit - 200:
            blocks.append(b)
            continue
        # قسم ضخم: قسّمه لأجزاء
        part, size, first, k0 = [], 0, True, 0
        for it in sec['items']:
            line_len = len(it[1]) + 70
            if part and size + line_len > limit - 400:
                blocks.append(_block(i, sec, part, cont=not first, k0=k0))
                k0 += len(part)
                part, size, first = [], 0, False
            part.append(it)
            size += line_len
        if part:
            blocks.append(_block(i, sec, part, cont=not first, k0=k0))
    msgs, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > limit:
            msgs.append(cur)
            cur = b
        else:
            cur += '\n\n' + b
    if cur:
        msgs.append(cur)
    return msgs

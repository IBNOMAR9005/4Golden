# -*- coding: utf-8 -*-
"""
markers.py  —  لغة الـ markers (SPEC §4-§7): lexer + parser + validator + unit ledger.

دوال نقية: مفيش I/O ومفيش ReportLab. `parse()` عمره ما بيرمي استثناء على ناتج موديل بايظ (R-30).
المفاتيح القياسية للوحدات: topic:7 / wrap:2 / case:2.1  (§4.5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PLAN_SENTENCE = 'الخطة جاهزة. هبدأ الكتابة.'

MARKER_RE = re.compile(r'^\s*@@([A-Z][A-Z0-9_]*)\s*(\|.*)?$')               # R-11
END_DONE_RE = re.compile(r'^@@(TOPIC_END|WRAP_END|CASEQ_END)\b.*\bDONE\b', re.I)  # R-20
FENCE_RE = re.compile(r'^\s*```[\w+\-]*\s*$')
_KEYED_RE = re.compile(r'^([A-Za-z_]+)\s*=(.*)$', re.S)                      # R-13

W_EMOJI = 'شلت رموز'          # بادئة التنبيهات المجمّعة (build_pdf بيدمجها)
W_BOLD = 'علامات ** غير متوازنة'

UNIT_START = {'TOPIC_START': 'topic', 'WRAP_START': 'wrap', 'CASEQ_START': 'case'}
UNIT_END = {'TOPIC_END': 'topic', 'WRAP_END': 'wrap', 'CASEQ_END': 'case'}
TABLE_TYPES = ('compare', 'classify', 'values', 'ddx')

# بلوكات نصية: سطر عادي بعدها = استكمال (R-15). الزيادة عن الـ spec: BUL/NUM/CASE_PEARL (توثيق في CHANGELOG)
CONT_KINDS = {'P', 'KEY', 'EMPH', 'WARN', 'RED', 'PEARL', 'CLIN', 'NOTE', 'EXTRA', 'ANALOGY',
              'CASE_STEM', 'CASE_A', 'CASE_Q', 'BUL', 'NUM', 'CASE_PEARL'}

# ════════════════════════════════════════════════════════════════════
#  1) تطبيع النص (R-10) + الإيموجي (R-17)
# ════════════════════════════════════════════════════════════════════
_ZW = '\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
_EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2B1B\u2B1C\u2B05-\u2B07\u2934\u2935'
                       '\u231A\u231B\u23E9-\u23F3\u23F8-\u23FA\u25B6\u25C0\u24C2\U000E0020-\U000E007F]')
_VS = re.compile('[\uFE0E\uFE0F\u20E3]')


def _is_ar(ch: str) -> bool:
    return '\u0621' <= ch <= '\u064A' or '\u0671' <= ch <= '\u06D3'


def _strip_zw(s: str) -> str:
    if not any(ch in s for ch in _ZW):
        return s
    out, n = [], len(s)
    for i, ch in enumerate(s):
        if ch not in _ZW:
            out.append(ch)
        elif ch in '\u200c\u200d' and 0 < i < n - 1 and _is_ar(s[i - 1]) and _is_ar(s[i + 1]):
            out.append(ch)          # ZWJ/ZWNJ جوه كلمة عربي بس
    return ''.join(out)


def normalize_lines(text: str) -> List[Tuple[int, str]]:
    """[(رقم السطر الأصلي، النص)] بعد التطبيع. أسطر الـ code-fence بتتشال (الترقيم الأصلي بيفضل)."""
    if text.startswith('\ufeff'):
        text = text[1:]
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for i, ln in enumerate(text.split('\n'), 1):
        ln = _strip_zw(ln).rstrip(' \t\u00a0')
        if FENCE_RE.match(ln):
            continue
        out.append((i, ln))
    return out


def normalize(text: str) -> str:
    return '\n'.join(l for _, l in normalize_lines(text))


def strip_emoji(s: str) -> Tuple[str, int]:
    n = len(_EMOJI_RE.findall(s))
    if not n and not _VS.search(s):
        return s, 0
    s2 = _VS.sub('', _EMOJI_RE.sub('', s))
    s2 = re.sub(r'[ \t]{2,}', ' ', s2).strip()
    return s2, n


# ════════════════════════════════════════════════════════════════════
#  2) جدول الـ markers (§4.3)
# ════════════════════════════════════════════════════════════════════
ANY = None   # أي مفاتيح keyed


def _spec(pos=(), keys=frozenset(), req=(), unl=False, flags=False):
    return dict(pos=tuple(pos), keys=keys, req=tuple(req), unl=unl, flags=flags)


_T = lambda *req: _spec(pos=('text',), req=req or ('text',))   # noqa: E731

SPECS: Dict[str, dict] = {
    'PLAN_START': _spec(), 'PLAN_END': _spec(),
    'LECTURE': _spec(keys=ANY, req=('title',)),
    'ABOUT': _T(), 'LOGIC': _T(),
    'DICT': _spec(pos=('pair',), req=('pair',)),
    'AXIS_PLAN': _spec(keys=ANY, req=('id', 'title', 'src')),
    'TOPIC_PLAN': _spec(keys=ANY, req=('axis', 'id', 'title', 'src')),
    'LINK_PLAN': _spec(keys=ANY, req=('from', 'to')),
    'STRUCT': _spec(keys=ANY, req=('topic', 'block')),
    'AXIS_START': _spec(keys=ANY, req=('id', 'title')),
    'AXIS_INTRO': _T(),
    'WARMUP': _spec(pos=('question', 'answer'), req=('question',)),
    'TOPIC_START': _spec(keys=ANY, req=('id', 'title')),
    'TOPIC_END': _spec(keys=ANY, flags=True),
    'CHECKPOINT': _spec(keys=ANY),
    'SUMMARY': _spec(),
    'WRAP_START': _spec(keys=ANY, req=('axis',)), 'WRAP_END': _spec(keys=ANY, flags=True),
    'AXIS_SUMMARY': _T(), 'BIGPIC': _T(), 'HY': _T(),
    'CASEQ_START': _spec(keys=ANY, req=('id',)), 'CASEQ_END': _spec(keys=ANY, flags=True),
    'CASE_STEM': _T(), 'CASE_Q': _T(), 'CASE_A': _T(), 'CASE_PEARL': _T(),
    'H2': _T(), 'P': _T(), 'BUL': _T(), 'NUM': _T(),
    'DEF': _spec(pos=('term_en', 'term_ar', 'definition', 'analogy'), req=('term_en', 'definition')),
    'KEY': _T(), 'EMPH': _T(),
    'WHY': _spec(pos=('question', 'chain'), req=('question', 'chain')),
    'LINK': _spec(pos=('topic_id', 'text'), req=('topic_id',)),
    'WARN': _T(), 'RED': _T(), 'PEARL': _T(), 'CLIN': _T(), 'NOTE': _T(),
    'MNEMO': _spec(pos=('abbreviation', 'expansion'), req=('abbreviation', 'expansion')),
    'FLOW': _T(),
    'DRUG': _spec(pos=('name_en', 'class', 'indication', 'dose', 'mechanism', 'contraindications',
                       'adverse_interactions'), req=('name_en',)),
    'EXTRA': _T(), 'ANALOGY': _T(),
    'UNCLEAR': _spec(pos=('line_ref', 'text'), req=('text',)),
    'AUDIO': _spec(pos=('line_ref', 'text'), req=('text',)),           # legacy → UNCLEAR
    'TABLE_START': _spec(pos=('title',), keys=frozenset({'type'})),
    'TR': _spec(unl=True), 'TABLE_END': _spec(),
    'HIGHYIELD_START': _spec(), 'HIGHYIELD_END': _spec(),
    'BIGPICTURE': _T(),
    'FINAL': _spec(keys=ANY), 'CONTINUE': _spec(keys=ANY), 'COVERAGE': _spec(keys=ANY),
}

TOPIC_BLOCKS = {'H2', 'P', 'BUL', 'NUM', 'DEF', 'KEY', 'EMPH', 'WHY', 'LINK', 'WARN', 'RED', 'PEARL', 'CLIN',
                'NOTE', 'MNEMO', 'FLOW', 'DRUG', 'EXTRA', 'ANALOGY', 'UNCLEAR', 'AUDIO', 'TABLE_START', 'TR', 'TABLE_END',
                'SUMMARY'}
SHARED_BLOCKS = {'H2', 'P', 'BUL', 'NUM', 'KEY', 'NOTE', 'WARN', 'UNCLEAR', 'AUDIO'}
WRAP_ONLY = {'AXIS_SUMMARY', 'BIGPIC', 'HY'}
CASE_ONLY = {'CASE_STEM', 'CASE_Q', 'CASE_A', 'CASE_PEARL'}
PLAN_MARKERS = {'LECTURE', 'ABOUT', 'LOGIC', 'DICT', 'AXIS_PLAN', 'TOPIC_PLAN', 'LINK_PLAN', 'STRUCT'}
_ARROW_SPLIT = re.compile(r'\s*(?:[←→⟵⟶]|<-|->)\s*')


# ════════════════════════════════════════════════════════════════════
#  3) الموديل (§5)
# ════════════════════════════════════════════════════════════════════
@dataclass
class Block:
    kind: str
    fields: Any = None          # dict | list (قايمة عناصر في BUL/NUM بعد الدمج)
    text: str = ''
    line: int = 0


@dataclass
class Topic:
    id: int
    axis: Optional[int] = None
    title: str = ''
    en: str = ''
    src: str = ''
    blocks: List[Block] = field(default_factory=list)
    summary: List[str] = field(default_factory=list)
    done: bool = False
    line: int = 0
    end_line: int = 0
    extra: Dict[str, str] = field(default_factory=lambda: {})
    frame: Optional[int] = None
    kind: str = 'topic'

    @property
    def key(self) -> str:
        return 'topic:%d' % self.id


@dataclass
class Wrap:
    axis: int
    summary: List[str] = field(default_factory=list)
    bigpic: str = ''
    hy: List[str] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    done: bool = False
    line: int = 0
    end_line: int = 0
    kind: str = 'wrap'

    @property
    def key(self) -> str:
        return 'wrap:%d' % self.axis


@dataclass
class Case:
    axis: int
    id: int
    level: str = ''
    tests: str = ''
    stem: str = ''
    qa: List[Tuple[str, str]] = field(default_factory=list)
    pearl: str = ''
    blocks: List[Block] = field(default_factory=list)
    done: bool = False
    line: int = 0
    end_line: int = 0
    kind: str = 'case'

    @property
    def key(self) -> str:
        return 'case:%d.%d' % (self.axis, self.id)


@dataclass
class Axis:
    id: int
    title: str = ''
    en: str = ''
    kind: str = ''
    src: str = ''
    intro: str = ''
    warmups: List[Tuple[str, str]] = field(default_factory=list)
    units: List[Any] = field(default_factory=list)       # بترتيب العرض
    implicit: bool = False


@dataclass
class Lecture:
    meta: Dict[str, str] = field(default_factory=lambda: {})
    about: str = ''
    logic: str = ''
    axes_plan: List[dict] = field(default_factory=list)
    topics_plan: List[dict] = field(default_factory=list)
    links_plan: List[dict] = field(default_factory=list)
    structs: List[dict] = field(default_factory=list)
    dict: List[Tuple[str, str]] = field(default_factory=list)   # آخر حقل (عشان ما نظللش builtin dict)


@dataclass
class Tail:
    hy: List[str] = field(default_factory=list)
    bigpicture: str = ''
    final: Dict[str, str] = field(default_factory=lambda: {})
    unclear: List[Tuple[str, str]] = field(default_factory=list)
    final_seen: bool = False
    highyield_seen: bool = False


@dataclass
class Ledger:
    done: List[str] = field(default_factory=list)
    partial: Optional[str] = None
    expected: List[str] = field(default_factory=list)
    next_unit: Optional[str] = None
    last_src: int = 0
    finished: bool = False
    incomplete: List[str] = field(default_factory=list)   # وحدات اتقفلت ناقصة (derail) وملهاش نسخة كاملة
    plan_present: bool = False
    final_seen: bool = False

    @property
    def last_done(self) -> Optional[str]:
        return self.done[-1] if self.done else None


@dataclass
class ParseResult:
    lecture: Lecture
    axes: List[Axis]
    tail: Tail
    ledger: Ledger
    warnings: List[str]
    units: List[Any] = field(default_factory=list)         # كل النسخ بترتيب الظهور (كاملة وناقصة)
    stats: Dict[str, int] = field(default_factory=lambda: {})
    checkpoints: List[dict] = field(default_factory=list)
    coverage_lines: List[dict] = field(default_factory=list)
    continue_info: Dict[str, str] = field(default_factory=lambda: {})
    plan_complete: bool = False
    legacy: bool = False       # مفيش AXIS_PLAN/AXIS_START: محور ضمني id=0

    def complete_units(self) -> List[Any]:
        return [u for ax in self.axes for u in ax.units]

    def topics(self) -> List[Topic]:
        return [u for u in self.complete_units() if u.kind == 'topic']

    def unit(self, key: str):
        for u in self.complete_units():
            if u.key == key:
                return u
        return None

    def unclear(self) -> List[Tuple[str, str]]:
        out = []
        for u in self.complete_units():
            for b in getattr(u, 'blocks', []):
                if b.kind == 'UNCLEAR':
                    out.append((b.fields.get('line_ref') or '', b.text))
        return out + list(self.tail.unclear)


# ════════════════════════════════════════════════════════════════════
#  4) أدوات صغيرة
# ════════════════════════════════════════════════════════════════════
def _int(v) -> Optional[int]:
    if v is None:
        return None
    m = re.search(r'-?\d+', str(v))
    return int(m.group()) if m else None


_SRC_PART = re.compile(r'\s*L?\s*(\d+)\s*(?:[-–—~]\s*L?\s*(\d+))?\s*$', re.I)


def parse_src(s: Optional[str]) -> List[Tuple[int, int]]:
    """L10-L25 | 10-25 | L7 | 'L1-L5, L9-L12'  ←  [(a,b),...] (R legacy: A-B رقمي بس مقبول)."""
    out = []
    for part in re.split(r'[,;،]', s or ''):
        m = _SRC_PART.match(part)
        if m:
            a = int(m.group(1)); b = int(m.group(2) or a)
            out.append((min(a, b), max(a, b)))
    return out


def fmt_src(n: int, width: int = 3) -> str:
    return 'L%0*d' % (width, n)


def unit_key(kind: str, **kw) -> str:
    if kind == 'topic':
        return 'topic:%d' % kw['id']
    if kind == 'wrap':
        return 'wrap:%d' % kw['axis']
    return 'case:%d.%d' % (kw['axis'], kw['id'])


def _split_fields(rest: Optional[str]) -> List[str]:
    if not rest:
        return []
    rest = rest.strip()
    if rest.startswith('|'):
        rest = rest[1:]
    fl = [x.strip() for x in rest.split('|')]
    return [] if all(not x for x in fl) else fl


def _is_plan_sentence(s: str) -> bool:
    t = re.sub(r'\s+', ' ', s).strip().rstrip('.،') 
    return t == PLAN_SENTENCE.rstrip('.')


def _nz(v):
    return None if v in (None, '', '-') else v


# ════════════════════════════════════════════════════════════════════
#  5) الـ Parser
# ════════════════════════════════════════════════════════════════════
class _Parser:
    def __init__(self):
        self.warnings: List[str] = []
        self.stats = dict(emoji=0, bold=0, pipes=0, unknown=0, dropped_lines=0)
        self.lec = Lecture()
        self.units: List[Any] = []
        self.cur = None
        self.frames: Dict[int, dict] = {}
        self.axis_cur: Optional[int] = None
        self.tail = Tail()
        self.mode: Optional[str] = None            # 'hy' | None
        self.summary_mode = False
        self.table: Optional[dict] = None
        self._cont = None                          # (get, set) لاستكمال آخر بلوك نصي
        self._cont_warned = set()
        self.plan_state = 0                        # 0 لا، 1 جوه، 2 خلصت
        self.skip_plan = False
        self.checkpoints: List[dict] = []
        self.coverage_lines: List[dict] = []
        self.continue_info: Dict[str, str] = {}
        self.has_axis_plan = False
        self.legacy_axis_missing = 0
        self.last_line = 0
        self.eof_open: Optional[str] = None
        self.dup_plan = False

    # ── تحذيرات ──
    def w(self, ln: int, msg: str):
        self.warnings.append('سطر %d: %s' % (ln, msg) if ln else msg)

    # ── ربط الحقول ──
    def bind(self, name: str, raw_fields: List[str], ln: int):
        spec = SPECS[name]
        pos, keys = spec['pos'], spec['keys']
        vals: Dict[str, Optional[str]] = {}
        flags: List[str] = []
        last: Optional[str] = None
        pi, npos = 0, 0
        keyed_used = False
        for f in raw_fields:
            m = _KEYED_RE.match(f) if f else None
            if m and (keys is ANY or m.group(1).lower() in keys):
                k = m.group(1).lower()
                vals[k] = _nz(m.group(2).strip())
                last = k
                keyed_used = True
                continue
            if not pos:   # ماركر keyed بالكامل: الحقل العاري يا flag يا بقية قيمة فيها pipe
                if spec['flags'] and f and re.fullmatch(r'[A-Za-z_]+', f):
                    flags.append(f.upper())
                    continue
                if f and last is not None:
                    vals[last] = ((vals.get(last) or '') + ' / ' + f).strip(' /')
                    self.stats['pipes'] += 1
                    self.w(ln, 'حقول زيادة في @@%s اتدمجت (| جوه المحتوى)' % name)
                elif f:
                    self.w(ln, 'حقل من غير مفتاح اتشال في @@%s: %s' % (name, f[:30]))
                continue
            v = _nz(f)
            npos += 1
            if pi < len(pos):
                vals[pos[pi]] = v
                last = pos[pi]
                pi += 1
            else:
                tgt = pos[-1]
                vals[tgt] = ((vals.get(tgt) or '') + ' / ' + f).strip(' /') if f else vals.get(tgt)
                self.stats['pipes'] += 1
                self.w(ln, 'حقول زيادة في @@%s اتدمجت في آخر حقل (| جوه المحتوى)' % name)
        if vals.get('src') is None and vals.get('srt') is not None:      # legacy: srt=A-B هو src
            vals['src'] = vals['srt']
        for k, v in list(vals.items()):
            if v is not None:
                v2, n = strip_emoji(v)
                self.stats['emoji'] += n
                vals[k] = v2 or None
        miss = [r for r in spec['req'] if vals.get(r) is None]
        return vals, flags, npos, miss

    # ── dispatch ──
    def feed(self, ln: int, line: str):
        self.last_line = ln
        s = line.strip()
        if not s:
            return
        m = MARKER_RE.match(line)
        if not m:
            return self._nonmarker(ln, s)
        name, rest = m.group(1), m.group(2)
        if self.table is not None and name not in ('TR', 'TABLE_END'):
            self._finish_table()
        raw_fields = _split_fields(rest)
        if name not in SPECS:
            return self._unknown(name, raw_fields, ln)
        if name == 'TR':
            return self._m_tr(raw_fields, ln)
        vals, flags, npos, miss = self.bind(name, raw_fields, ln)
        if name == 'DEF' and npos == 2:
            miss = [x for x in miss if x != 'definition']    # شكل legacy: DEF | مصطلح | تعريف
        if name == 'TOPIC_PLAN':
            miss = [x for x in miss if x != 'axis']          # legacy من غير axis: بنتحقق منه مجمّعاً في الآخر
        if miss:
            self.w(ln, 'حقل ناقص في @@%s: %s' % (name, '، '.join(miss)))
        h = getattr(self, '_m_' + name.lower(), None)
        if h is None:
            return
        self._cont = None
        h(vals, ln, flags=flags, npos=npos, miss=miss, line=s)

    # ── سطور مش markers (R-15) ──
    def _nonmarker(self, ln: int, s: str):
        if _is_plan_sentence(s):
            return
        cur = self.cur
        if self.table is not None and self.table['rows'] and self.table['rows'][-1]:
            row = self.table['rows'][-1]
            row[-1] = (row[-1] + ' ' + s).strip()
            self._warn_cont(ln, 'table')
            return
        if isinstance(cur, Topic) and self.summary_mode:
            bullet = re.match(r'^[-•*\u2022]\s*(.*)$', s)
            if bullet:
                cur.summary.append(self.se(bullet.group(1)))
                self._set_summary_cont(cur)
                return
            if self._cont is None or getattr(self, '_cont_is_marker_bul', False) is False:
                cur.summary.append(self.se(s))
                self._set_summary_cont(cur)
                return
        if self._cont is not None:
            g, st = self._cont
            st((g() + ' ' + self.se(s)).strip())
            self._warn_cont(ln, getattr(cur, 'key', 'out') if cur is not None else 'out')
            return
        self.stats['dropped_lines'] += 1
        self.w(ln, 'سطر مش marker اتشال: %s' % s[:40])

    def se(self, s: str) -> str:
        s2, n = strip_emoji(s)
        self.stats['emoji'] += n
        return s2

    def _warn_cont(self, ln, key):
        if key not in self._cont_warned:
            self._cont_warned.add(key)
            self.w(ln, 'سطر عادي اتضاف كاستكمال للبلوك اللي قبله (مرة واحدة لكل وحدة)')

    def _set_summary_cont(self, cur, marker_bul=False):
        idx = len(cur.summary) - 1
        self._cont = (lambda: cur.summary[idx], lambda v: cur.summary.__setitem__(idx, v))
        self._cont_is_marker_bul = marker_bul

    def _unknown(self, name, raw_fields, ln):
        self.stats['unknown'] += 1
        if self.cur is not None and self.table is None:
            txt = ' / '.join(strip_emoji(f)[0] for f in raw_fields if f and f != '-')
            self.w(ln, 'marker مش معروف @@%s اتعرض كفقرة' % name)
            if txt:
                self._append_block(Block('P', {}, txt, ln))
        else:
            self.w(ln, 'marker مش معروف @@%s اتشال' % name)
        self._cont = None

    # ── وحدات ──
    def _close(self, done: bool, ln: int, reason: str = ''):
        cur = self.cur
        if cur is None:
            return
        self._finish_table()
        cur.done = done
        cur.end_line = ln
        self._post_unit(cur)
        self.units.append(cur)
        self.cur, self.summary_mode, self._cont = None, False, None

    def _boundary(self, ln: int, what: str):
        if self.plan_state == 1:
            self.plan_state = 2
            self.w(ln, '@@PLAN_END مفقود؛ الخطة اتقفلت ضمنياً')
        if self.cur is not None:
            self.w(ln, 'الوحدة %s ما اتقفلتش بـ DONE وجه %s (الموديل خرج عن الخط) — اتعتبرت ناقصة' % (self.cur.key, what))
            self._close(False, max(self.cur.line, ln - 1), 'derail')

    def _post_unit(self, u):
        if isinstance(u, Topic):
            u.blocks = self._merge_lists(u.blocks)
            if u.done and not u.blocks and not u.summary:
                self.w(u.end_line, 'الموضوع %d فاضي' % u.id)
        elif isinstance(u, (Wrap, Case)):
            u.blocks = self._merge_lists(u.blocks)

    def _merge_lists(self, blocks: List[Block]) -> List[Block]:
        out: List[Block] = []
        for b in blocks:
            if b.kind in ('BUL', 'NUM') and not isinstance(b.fields, list):
                if out and out[-1].kind == b.kind and isinstance(out[-1].fields, list):
                    out[-1].fields.append(b.text)
                    continue
                out.append(Block(b.kind, [b.text], '', b.line))
            else:
                out.append(b)
        res: List[Block] = []
        for i, b in enumerate(out):                       # H2 فاضي (R-34)
            if b.kind == 'H2' and (i + 1 >= len(out) or out[i + 1].kind == 'H2'):
                self.w(b.line, 'عنوان فرعي H2 من غير محتوى اتشال')
                continue
            res.append(b)
        return res

    def _m_plan_start(self, v, ln, **k):
        if self.cur is not None:
            self._boundary(ln, '@@PLAN_START')
        if self.plan_state == 2:
            self.skip_plan = True
            if not self.dup_plan:
                self.dup_plan = True
                self.w(ln, 'الخطة اتعادت؛ الأولى هي المعتمدة والتانية اتجاهلت')
        else:
            self.plan_state = 1

    def _m_plan_end(self, v, ln, **k):
        if self.skip_plan:
            self.skip_plan = False
            return
        self.plan_state = 2

    # ── الخطة ──
    def _plan_guard(self, name, ln) -> bool:
        if self.skip_plan:
            return False
        if self.cur is not None:
            self.w(ln, '@@%s جوه وحدة (مكانه الخطة) — اتشال' % name)
            return False
        return True

    def _m_lecture(self, v, ln, **k):
        if self._plan_guard('LECTURE', ln):
            for kk, vv in v.items():
                if vv is not None:
                    self.lec.meta[kk] = vv

    def _text_plan(self, attr, v, ln, name):
        if not self._plan_guard(name, ln):
            return
        setattr(self.lec, attr, v.get('text') or '')
        self._cont = (lambda: getattr(self.lec, attr), lambda s: setattr(self.lec, attr, s))

    def _m_about(self, v, ln, **k):
        self._text_plan('about', v, ln, 'ABOUT')

    def _m_logic(self, v, ln, **k):
        self._text_plan('logic', v, ln, 'LOGIC')

    def _m_dict(self, v, ln, **k):
        if not self._plan_guard('DICT', ln):
            return
        parts = [x.strip() for x in _ARROW_SPLIT.split(v.get('pair') or '', maxsplit=1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            self.lec.dict.append((parts[0], parts[1]))
        else:
            self.w(ln, 'سطر DICT لازم يكون "الغلط ← الصح": %s' % (v.get('pair') or '')[:40])

    def _m_axis_plan(self, v, ln, **k):
        if not self._plan_guard('AXIS_PLAN', ln):
            return
        i = _int(v.get('id'))
        if i is None:
            return self.w(ln, 'AXIS_PLAN من غير id اتشال')
        self.has_axis_plan = True
        if any(a['id'] == i for a in self.lec.axes_plan):
            return self.w(ln, 'AXIS_PLAN مكرر للمحور %d اتجاهل' % i)
        e = dict(v)
        e['id'] = i
        e['src'] = v.get('src') or v.get('srt')
        self.lec.axes_plan.append(e)

    def _m_topic_plan(self, v, ln, miss=(), **k):
        if not self._plan_guard('TOPIC_PLAN', ln):
            return
        i = _int(v.get('id'))
        if i is None:
            return self.w(ln, 'TOPIC_PLAN من غير id اتشال')
        e = dict(v)
        e['id'], e['axis'] = i, _int(v.get('axis'))
        e['src'] = v.get('src') or v.get('srt')
        if e['axis'] is None:
            self.legacy_axis_missing += 1
        if any(t['id'] == i for t in self.lec.topics_plan):
            return self.w(ln, 'TOPIC_PLAN مكرر للموضوع %d اتجاهل' % i)
        self.lec.topics_plan.append(e)

    def _m_link_plan(self, v, ln, **k):
        if self._plan_guard('LINK_PLAN', ln):
            self.lec.links_plan.append(dict(v))

    def _m_struct(self, v, ln, **k):
        if self._plan_guard('STRUCT', ln):
            self.lec.structs.append(dict(v))

    # ── محور ──
    def _m_axis_start(self, v, ln, **k):
        self._boundary(ln, '@@AXIS_START')
        i = _int(v.get('id'))
        if i is None:
            return self.w(ln, 'AXIS_START من غير id اتشال')
        self.axis_cur = i
        self.frames[i] = dict(title=v.get('title') or '', en=v.get('en') or '', kind=v.get('kind') or '',
                              src=v.get('src') or v.get('srt') or '', intro='', warmups=[])

    def _m_axis_intro(self, v, ln, **k):
        if self.cur is not None or self.axis_cur is None:
            return self.w(ln, '@@AXIS_INTRO في مكان غلط اتشال')
        fr = self.frames[self.axis_cur]
        fr['intro'] = v.get('text') or ''
        self._cont = (lambda: fr['intro'], lambda s: fr.__setitem__('intro', s))

    def _m_warmup(self, v, ln, **k):
        if self.cur is not None or self.axis_cur is None:
            return self.w(ln, '@@WARMUP في مكان غلط اتشال')
        if v.get('question'):
            self.frames[self.axis_cur]['warmups'].append((v['question'], v.get('answer') or ''))

    # ── بداية ونهاية الوحدات ──
    def _m_topic_start(self, v, ln, **k):
        self._boundary(ln, '@@TOPIC_START')
        tid = _int(v.get('id'))
        if tid is None:
            seen = [u.id for u in self.units if isinstance(u, Topic)] + [t['id'] for t in self.lec.topics_plan]
            tid = max(seen + [0]) + 1
            self.w(ln, 'TOPIC_START من غير id؛ اتدّى رقم %d' % tid)
        known = ('id', 'axis', 'title', 'en', 'src', 'srt')
        t = Topic(id=tid, axis=_int(v.get('axis')), title=v.get('title') or '', en=v.get('en') or '',
                  src=v.get('src') or v.get('srt') or '', line=ln, frame=self.axis_cur,
                  extra={kk: vv for kk, vv in v.items() if kk not in known and vv is not None})
        self.cur = t
        self.summary_mode = False

    def _m_wrap_start(self, v, ln, **k):
        self._boundary(ln, '@@WRAP_START')
        ax = _int(v.get('axis'))
        if ax is None:
            ax = self.axis_cur if self.axis_cur is not None else 0
            self.w(ln, 'WRAP_START من غير axis؛ اتاخد المحور %d' % ax)
        self.cur = Wrap(axis=ax, line=ln)

    def _m_caseq_start(self, v, ln, **k):
        self._boundary(ln, '@@CASEQ_START')
        ax = _int(v.get('axis'))
        if ax is None:
            ax = self.axis_cur if self.axis_cur is not None else 0
        cid = _int(v.get('id'))
        if cid is None:
            cid = 1 + sum(1 for u in self.units if isinstance(u, Case) and u.axis == ax)
            self.w(ln, 'CASEQ_START من غير id؛ اتدّى رقم %d' % cid)
        lv = (v.get('level') or '').lower()
        self.cur = Case(axis=ax, id=cid, level=lv, tests=v.get('tests') or '', line=ln)

    def _end(self, kind, v, ln, flags, line):
        done = bool(END_DONE_RE.match(line))
        if self.cur is None:
            return self.w(ln, 'نهاية وحدة من غير بداية اتجاهلت')
        if self.cur.kind != kind:
            self.w(ln, 'نهاية %s جت والوحدة المفتوحة %s — اتعتبرت ناقصة' % (kind, self.cur.key))
            return self._close(False, ln - 1)
        if kind == 'topic' and _int(v.get('id')) not in (None, self.cur.id):
            self.w(ln, 'TOPIC_END id=%s مش بتاع الموضوع المفتوح %d' % (v.get('id'), self.cur.id))
        if not done:
            self.w(ln, 'الوحدة %s اتقفلت من غير DONE — ناقصة' % self.cur.key)
        self._close(done, ln)

    def _m_topic_end(self, v, ln, flags=(), line='', **k):
        self._end('topic', v, ln, flags, line)

    def _m_wrap_end(self, v, ln, flags=(), line='', **k):
        self._end('wrap', v, ln, flags, line)

    def _m_caseq_end(self, v, ln, flags=(), line='', **k):
        self._end('case', v, ln, flags, line)

    # ── متابعة ──
    def _m_checkpoint(self, v, ln, **k):
        if self.cur is not None:
            return self.w(ln, '@@CHECKPOINT جوه وحدة مفتوحة اتجاهل')
        self.checkpoints.append(dict(v))

    def _m_continue(self, v, ln, **k):
        if self.cur is not None:
            self._boundary(ln, '@@CONTINUE')
        self.continue_info = {kk: vv for kk, vv in v.items() if vv is not None}

    def _m_coverage(self, v, ln, **k):
        self.coverage_lines.append(dict(v))

    # ── البلوكات ──
    def _append_block(self, b: Block):
        cur = self.cur
        if isinstance(cur, (Topic, Wrap, Case)):
            cur.blocks.append(b)

    def _gate(self, name, ln) -> bool:
        cur = self.cur
        if cur is None:
            self.w(ln, '@@%s برّه أي وحدة اتشال' % name)
            return False
        if isinstance(cur, Topic):
            ok = name in TOPIC_BLOCKS
        elif isinstance(cur, Wrap):
            ok = name in SHARED_BLOCKS or name in WRAP_ONLY
        else:
            ok = name in SHARED_BLOCKS or name in CASE_ONLY
        if not ok:
            self.w(ln, '@@%s مش مسموح جوه %s — اتشال' % (name, cur.key))
        return ok

    def _text_block(self, kind, v, ln):
        txt = v.get('text')
        if not txt:
            return None
        b = Block(kind, {}, txt, ln)
        self._append_block(b)
        if kind in CONT_KINDS:
            self._cont = (lambda: b.text, lambda s: setattr(b, 'text', s))
        return b

    def _simple(self, name):
        def h(v, ln, **k):
            if self._gate(name, ln):
                self._text_block(name, v, ln)
        return h

    def __getattr__(self, attr):
        if attr.startswith('_m_'):
            nm = attr[3:].upper()
            if nm in ('P', 'KEY', 'EMPH', 'WARN', 'RED', 'PEARL', 'CLIN', 'NOTE', 'EXTRA', 'ANALOGY', 'H2'):
                return self._simple(nm)
        raise AttributeError(attr)

    def _m_bul(self, v, ln, **k):
        self._list_item('BUL', v, ln)

    def _m_num(self, v, ln, **k):
        self._list_item('NUM', v, ln)

    def _list_item(self, kind, v, ln):
        if not self._gate(kind, ln):
            return
        txt = v.get('text')
        if not txt:
            return
        cur = self.cur
        if isinstance(cur, Topic) and self.summary_mode:
            cur.summary.append(txt)
            self._set_summary_cont(cur, marker_bul=True)
            return
        self._text_block(kind, v, ln)

    def _m_summary(self, v, ln, **k):
        if isinstance(self.cur, Topic):
            self.summary_mode = True
        else:
            self.w(ln, '@@SUMMARY برّه موضوع اتشال')

    def _m_def(self, v, ln, npos=0, **k):
        if not self._gate('DEF', ln):
            return
        f = dict(v)
        if npos == 2 and f.get('definition') is None and f.get('term_ar'):   # شكل legacy: DEF | مصطلح | تعريف
            f['definition'], f['term_ar'] = f['term_ar'], None
        if not f.get('term_en') or not f.get('definition'):
            return self.w(ln, 'DEF من غير term_en أو definition اتشال')
        b = Block('DEF', {x: f.get(x) for x in ('term_en', 'term_ar', 'definition', 'analogy')}, f['definition'], ln)
        self._append_block(b)
        self._cont = (lambda: b.fields['definition'], lambda s: b.fields.__setitem__('definition', s))

    def _m_why(self, v, ln, **k):
        if not self._gate('WHY', ln):
            return
        q, chain = v.get('question'), v.get('chain')
        if not q:
            return
        steps = [x for x in _ARROW_SPLIT.split(chain or '') if x.strip()]
        if len(steps) < 2:
            self.w(ln, 'WHY فيها أقل من خطوتين اتحولت لفقرة')
            return self._append_block(Block('P', {}, ('%s: %s' % (q, chain)) if chain else q, ln))
        self._append_block(Block('WHY', {'question': q, 'chain': [s.strip() for s in steps]}, q, ln))

    def _m_flow(self, v, ln, **k):
        if not self._gate('FLOW', ln):
            return
        txt = v.get('text')
        if not txt:
            return
        steps = [x.strip() for x in _ARROW_SPLIT.split(txt) if x.strip()]
        if len(steps) < 2:
            self.w(ln, 'FLOW فيها أقل من خطوتين اتحولت لفقرة')
            return self._append_block(Block('P', {}, txt, ln))
        self._append_block(Block('FLOW', {'steps': steps}, txt, ln))

    def _m_link(self, v, ln, **k):
        if not self._gate('LINK', ln):
            return
        tid = _int(v.get('topic_id'))
        if tid is None:
            self.w(ln, 'LINK من غير رقم موضوع صالح — اتعرض كنص')
        self._append_block(Block('LINK', {'topic_id': tid, 'ok': None}, v.get('text') or '', ln))

    def _m_mnemo(self, v, ln, **k):
        if self._gate('MNEMO', ln) and v.get('abbreviation') and v.get('expansion'):
            self._append_block(Block('MNEMO', {'abbreviation': v['abbreviation'], 'expansion': v['expansion']}, '', ln))

    def _m_drug(self, v, ln, **k):
        if self._gate('DRUG', ln) and v.get('name_en'):
            self._append_block(Block('DRUG', dict(v), '', ln))

    def _m_unclear(self, v, ln, **k):
        if not v.get('text'):
            return
        if self.cur is not None and self._gate('UNCLEAR', ln):
            self._append_block(Block('UNCLEAR', {'line_ref': v.get('line_ref') or ''}, v['text'], ln))
        elif self.cur is None:
            self.tail.unclear.append((v.get('line_ref') or '', v['text']))

    def _m_audio(self, v, ln, **k):
        self._m_unclear(v, ln)

    # ── جداول ──
    def _m_table_start(self, v, ln, **k):
        if not self._gate('TABLE_START', ln):
            self.table = None
            return
        typ = (v.get('type') or 'compare').lower()
        if typ not in TABLE_TYPES:
            self.w(ln, 'نوع جدول غير معروف "%s" → compare' % typ)
            typ = 'compare'
        self.table = dict(title=v.get('title') or '', type=typ, rows=[], line=ln)

    def _m_tr(self, raw_fields, ln):
        if self.table is None:
            return self.w(ln, '@@TR من غير TABLE_START اتشال')
        row = []
        for f in raw_fields:
            f, n = strip_emoji('' if f == '-' else f)
            self.stats['emoji'] += n
            row.append(f)
        self.table['rows'].append(row)

    def _m_table_end(self, v, ln, **k):
        if self.table is None:
            return self.w(ln, '@@TABLE_END من غير جدول مفتوح اتجاهل')
        self._finish_table()

    @staticmethod
    def _rstrip_empty(r):
        r = list(r)
        while r and not r[-1]:
            r.pop()
        return r

    def _finish_table(self):
        t, self.table = self.table, None
        if t is None or self.cur is None:
            return
        rows = [self._rstrip_empty(r) for r in t['rows']]
        rows = [r for r in rows if r]
        ln = t['line']
        if not rows:
            return self.w(ln, 'جدول فاضي اتشال')
        nc = len(rows[0])
        if nc < 2 or len(rows) < 2:
            items = [' — '.join(c for c in r if c) for r in rows]
            self.w(ln, 'جدول بعمود واحد أو من غير صفوف بيانات اتحول لقايمة')
            return self._append_block(Block('BUL', [i for i in items if i], '', ln))
        if any(len(r) != nc for r in rows[1:]):
            self.w(ln, 'جدول "%s" أعمدته مش متساوية؛ اتظبط على عدد أعمدة العنوان (%d)' % (t['title'][:30], nc))
        rows = [(r + [''] * nc)[:nc] for r in rows]
        self._append_block(Block('TABLE', dict(title=t['title'], type=t['type'], rows=rows, ragged=False), '', ln))

    # ── الذيل ──
    def _m_highyield_start(self, v, ln, **k):
        self._boundary(ln, '@@HIGHYIELD_START')
        self.mode = 'hy'
        self.tail.highyield_seen = True

    def _m_highyield_end(self, v, ln, **k):
        self._boundary(ln, '@@HIGHYIELD_END')
        self.mode = None

    def _m_hy(self, v, ln, **k):
        txt = v.get('text')
        if not txt:
            return
        if isinstance(self.cur, Wrap):
            self.cur.hy.append(txt)
            lst, idx = self.cur.hy, len(self.cur.hy) - 1
        else:
            if self.cur is not None:
                return self.w(ln, '@@HY جوه %s مش مسموح — اتشال' % self.cur.key)
            if self.mode != 'hy':
                self.w(ln, '@@HY برّه HIGHYIELD اتحط في قايمة المراجعة')
            self.tail.hy.append(txt)
            lst, idx = self.tail.hy, len(self.tail.hy) - 1
        self._cont = (lambda: lst[idx], lambda s: lst.__setitem__(idx, s))

    def _m_bigpicture(self, v, ln, **k):
        self._boundary(ln, '@@BIGPICTURE')
        self.tail.bigpicture = v.get('text') or ''
        self._cont = (lambda: self.tail.bigpicture, lambda s: setattr(self.tail, 'bigpicture', s))

    def _m_final(self, v, ln, **k):
        self._boundary(ln, '@@FINAL')
        self.tail.final = {kk: vv for kk, vv in v.items() if vv is not None}
        self.tail.final_seen = True

    # ── Wrap / Case ──
    def _m_axis_summary(self, v, ln, **k):
        if self._gate('AXIS_SUMMARY', ln) and v.get('text'):
            cur = self.cur
            cur.summary.append(v['text'])
            idx = len(cur.summary) - 1
            self._cont = (lambda: cur.summary[idx], lambda s: cur.summary.__setitem__(idx, s))

    def _m_bigpic(self, v, ln, **k):
        if self._gate('BIGPIC', ln) and v.get('text'):
            cur = self.cur
            cur.bigpic = v['text']
            self._cont = (lambda: cur.bigpic, lambda s: setattr(cur, 'bigpic', s))

    def _m_case_stem(self, v, ln, **k):
        if self._gate('CASE_STEM', ln) and v.get('text'):
            cur = self.cur
            if cur.stem:
                self.w(ln, 'CASE_STEM مكرر في %s' % cur.key)
                cur.stem += ' ' + v['text']
            else:
                cur.stem = v['text']
            self._cont = (lambda: cur.stem, lambda s: setattr(cur, 'stem', s))

    def _m_case_q(self, v, ln, **k):
        if self._gate('CASE_Q', ln) and v.get('text'):
            cur = self.cur
            cur.qa.append((v['text'], ''))
            idx = len(cur.qa) - 1
            self._cont = (lambda: cur.qa[idx][0], lambda s: cur.qa.__setitem__(idx, (s, cur.qa[idx][1])))

    def _m_case_a(self, v, ln, **k):
        if not (self._gate('CASE_A', ln) and v.get('text')):
            return
        cur = self.cur
        if not cur.qa or cur.qa[-1][1]:
            self.w(ln, 'CASE_A من غير CASE_Q قبله في %s' % cur.key)
            cur.qa.append(('', v['text']))
        else:
            cur.qa[-1] = (cur.qa[-1][0], v['text'])
        idx = len(cur.qa) - 1
        self._cont = (lambda: cur.qa[idx][1], lambda s: cur.qa.__setitem__(idx, (cur.qa[idx][0], s)))

    def _m_case_pearl(self, v, ln, **k):
        if self._gate('CASE_PEARL', ln) and v.get('text'):
            cur = self.cur
            cur.pearl = v['text']
            self._cont = (lambda: cur.pearl, lambda s: setattr(cur, 'pearl', s))

    # ── ختام ──
    def finish(self, text_lines: int) -> ParseResult:
        if self.table is not None:
            self._finish_table()
        if self.cur is not None:
            self.eof_open = self.cur.key
            self._close(False, self.last_line)
        if self.plan_state == 1:
            self.plan_state = 1
        return _assemble(self)


# ════════════════════════════════════════════════════════════════════
#  6) تجميع النتيجة: المحاور، الترتيب، الـ ledger
# ════════════════════════════════════════════════════════════════════
def plan_expected(lec: Lecture) -> List[str]:
    """المفاتيح المتوقعة بترتيب الخطة (R-40). مع AXIS_PLAN: مواضيع المحور ثم wrap ثم الحالات.
    الحالات: عددها من حقل cases (مفقود = 1، "-" = صفر)."""
    def eff(t):
        return t['axis'] if t['axis'] is not None else 0
    ids = sorted({a['id'] for a in lec.axes_plan} | {eff(t) for t in lec.topics_plan})
    keys: List[str] = []
    for ax in ids:
        keys += ['topic:%d' % t['id'] for t in lec.topics_plan if eff(t) == ax]
        ap = next((a for a in lec.axes_plan if a['id'] == ax), None)
        if ap is not None:
            keys.append('wrap:%d' % ax)
            n = 1 if 'cases' not in ap else (_int(ap.get('cases')) or 0)
            keys += ['case:%d.%d' % (ax, i) for i in range(1, n + 1)]
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _assemble(p: _Parser) -> ParseResult:
    lec, warns = p.lec, p.warnings
    # أول نسخة كاملة/ناقصة لكل key
    first_idx: Dict[str, int] = {}
    win: Dict[str, Tuple[int, Any]] = {}
    inc_only: Dict[str, Any] = {}
    for i, u in enumerate(p.units):
        first_idx.setdefault(u.key, i)
        if u.done:
            win[u.key] = (i, u)                 # R-23: آخر نسخة كاملة تكسب
    for u in p.units:
        if u.key not in win:
            inc_only[u.key] = u                 # نسخة ناقصة ملهاش نسخة كاملة
    plan_topic_axis = {t['id']: t['axis'] for t in lec.topics_plan if t['axis'] is not None}
    # تحديد محور كل موضوع: صريح ← الخطة ← الإطار ← 0
    for k, (_, u) in win.items():
        if isinstance(u, Topic) and u.axis is None:
            u.axis = plan_topic_axis.get(u.id, u.frame if u.frame is not None else 0)
    explicit_axes = bool(lec.axes_plan or p.frames)
    plan_complete = p.plan_state == 2
    expected = plan_expected(lec) if plan_complete else []
    plan_present = plan_complete and bool(expected)

    # ── المحاور بترتيب العرض (R-24) ──
    complete_units = [u for _, (i, u) in sorted(win.items(), key=lambda kv: first_idx[kv[0]])]
    axis_ids = {a['id'] for a in lec.axes_plan} | set(p.frames) | {u.axis for u in complete_units}
    axis_ids |= {t['axis'] for t in lec.topics_plan if t['axis'] is not None}
    if not axis_ids:
        axis_ids = set()
    axes: List[Axis] = []
    plan_order = {t['id']: n for n, t in enumerate(lec.topics_plan)}
    for aid in sorted(axis_ids):
        ap = next((a for a in lec.axes_plan if a['id'] == aid), {})
        fr = p.frames.get(aid, {})
        implicit = (aid == 0 and not ap and not fr)
        ax = Axis(id=aid,
                  title=fr.get('title') or ap.get('title') or (lec.meta.get('title', '') if implicit else ''),
                  en=fr.get('en') or ap.get('en') or '', kind=fr.get('kind') or ap.get('kind') or '',
                  src=fr.get('src') or ap.get('src') or '', intro=fr.get('intro', ''),
                  warmups=list(fr.get('warmups', [])), implicit=implicit)
        topics = [u for u in complete_units if isinstance(u, Topic) and u.axis == aid]
        topics.sort(key=lambda t: (0, plan_order[t.id]) if t.id in plan_order else (1, first_idx[t.key]))
        wrap = [u for u in complete_units if isinstance(u, Wrap) and u.axis == aid]
        cases = sorted([u for u in complete_units if isinstance(u, Case) and u.axis == aid], key=lambda c: c.id)
        ax.units = topics + wrap + cases
        axes.append(ax)
    axes = [a for a in axes if a.units or not a.implicit]

    # ── LINK: حل الأهداف (R-33) ──
    tids = {u.id for u in complete_units if isinstance(u, Topic)}
    for u in complete_units:
        for b in getattr(u, 'blocks', []):
            if b.kind == 'LINK':
                ok = b.fields.get('topic_id') in tids
                b.fields['ok'] = ok
                if not ok:
                    warns.append('سطر %d: LINK لموضوع مش موجود (%s) — اتعرض كنص' % (b.line, b.fields.get('topic_id')))

    # ── ** غير متوازنة (تنبيه مجمّع) ──
    def chk(s):
        if isinstance(s, str) and s.count('**') % 2:
            p.stats['bold'] += 1
    for u in complete_units:
        for b in getattr(u, 'blocks', []):
            if isinstance(b.fields, list):
                for it in b.fields:
                    chk(it)
            elif b.kind == 'TABLE':
                for r in b.fields['rows']:
                    for c in r:
                        chk(c)
            else:
                chk(b.text)
                if isinstance(b.fields, dict):
                    for vv in b.fields.values():
                        chk(vv)
        if isinstance(u, Topic):
            for s in u.summary:
                chk(s)
    if p.stats['emoji']:
        warns.append('%s (إيموجي/رموز): %d' % (W_EMOJI, p.stats['emoji']))
    if p.stats['bold']:
        warns.append('%s في %d نص — اتعرضت كما هي' % (W_BOLD, p.stats['bold']))
    if p.legacy_axis_missing and lec.axes_plan:
        warns.append('TOPIC_PLAN من غير axis في %d سطر' % p.legacy_axis_missing)

    # ── tail: unclear من وحدات كاملة بس ──
    # ── Ledger (R-40) ──
    ordered = [k for k, _ in sorted(win.items(), key=lambda kv: kv[1][0])]
    done_set = set(ordered)
    last_src = 0
    for k in ordered:
        u = win[k][1]
        if isinstance(u, Topic):
            for _, b in parse_src(u.src):
                last_src = max(last_src, b)
    nxt = next((k for k in expected if k not in done_set), None)
    led = Ledger(done=ordered, partial=p.eof_open, expected=expected, next_unit=nxt, last_src=last_src,
                 finished=bool(plan_present and nxt is None), incomplete=sorted(inc_only),
                 plan_present=plan_present, final_seen=p.tail.final_seen)
    res = ParseResult(lecture=lec, axes=axes, tail=p.tail, ledger=led, warnings=warns, units=p.units,
                      stats=p.stats, checkpoints=p.checkpoints, coverage_lines=p.coverage_lines,
                      continue_info=p.continue_info, plan_complete=plan_complete, legacy=not explicit_axes)
    return res


def parse(text: str) -> ParseResult:
    """ما بيرميش أبداً (R-30)."""
    p = _Parser()
    try:
        lines = normalize_lines(text or '')
        for ln, line in lines:
            try:
                p.feed(ln, line)
            except Exception as e:          # حماية أخيرة: سطر واحد ما يوقعش الباقي
                p.warnings.append('سطر %d: خطأ داخلي في المعالجة (%s)' % (ln, type(e).__name__))
        return p.finish(len(lines))
    except Exception as e:                 # pragma: no cover
        r = ParseResult(Lecture(), [], Tail(), Ledger(), ['فشل التحليل: %s' % type(e).__name__])
        return r


# ════════════════════════════════════════════════════════════════════
#  7) التغطية والتحقق (§6)
# ════════════════════════════════════════════════════════════════════
def coverage(pr: ParseResult, total: int = 0) -> dict:
    claims: Dict[int, List[Tuple[int, int]]] = {}
    plan_src = {t['id']: t.get('src') for t in pr.lecture.topics_plan}
    for t in pr.topics():
        rg = parse_src(t.src) or parse_src(plan_src.get(t.id))
        claims[t.id] = rg
    pts = sorted({x for rg in claims.values() for a, b in rg for x in (a, b + 1)})
    overlaps, uncovered, out_of_range = [], [], []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1] - 1
        who = [tid for tid, rg in claims.items() if any(x <= a and b <= y for x, y in rg)]
        if len(who) > 1:
            overlaps.append((a, b, sorted(who)))
    hi = total or max([b for rg in claims.values() for _, b in rg] + [0])
    covered = sorted({(a, b) for rg in claims.values() for a, b in rg})
    cur = 1
    for a, b in covered:
        if a > cur:
            uncovered.append((cur, a - 1))
        cur = max(cur, b + 1)
    if hi and cur <= hi:
        uncovered.append((cur, hi))
    if total:
        for tid, rg in claims.items():
            if any(a < 1 or b > total for a, b in rg):
                out_of_range.append(tid)
    return dict(claims=claims, overlaps=overlaps, uncovered=uncovered, out_of_range=sorted(out_of_range))


def _rng(a, b):
    return fmt_src(a) if a == b else '%s-%s' % (fmt_src(a), fmt_src(b))


def structural_issues(pr: ParseResult) -> List[Tuple[str, str]]:
    """وحدات كاملة بس بنيتها ناقصة (مرشحة لـ REPAIR) — مثال: حالة من غير pearl."""
    out = []
    for u in pr.complete_units():
        if isinstance(u, Case):
            if not u.stem:
                out.append((u.key, 'missing CASE_STEM'))
            if not any(q and a for q, a in u.qa):
                out.append((u.key, 'missing CASE_Q/CASE_A pair'))
            if not u.pearl:
                out.append((u.key, 'missing CASE_PEARL'))
        elif isinstance(u, Topic) and not u.blocks:
            out.append((u.key, 'empty topic'))
        elif isinstance(u, Wrap) and not (u.summary or u.bigpic or u.hy):
            out.append((u.key, 'empty wrap'))
    return out


def validate(pr: ParseResult, total_lines: int = 0, mode: str = 'lenient') -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warns: List[str] = []
    led = pr.ledger
    if not pr.complete_units():
        errors.append('مفيش أي وحدة مكتملة (محتاج على الأقل موضوع واحد مقفول بـ DONE)')
    missing = [k for k in led.expected if k not in set(led.done)]
    if led.plan_present and missing:
        msg = 'وحدات مخططة ناقصة/غير مكتملة: %s' % '، '.join(missing[:12]) + (' …' if len(missing) > 12 else '')
        (errors if mode == 'strict' else warns).append(msg)
        if pr.tail.final_seen:
            warns.append('الموديل قفل بدري: FINAL موجود لكن في %d وحدة ناقصة' % len(missing))
    if led.incomplete:
        warns.append('وحدات اتقطعت ومالهاش نسخة كاملة: %s' % '، '.join(led.incomplete[:10]))
    cov = coverage(pr, total_lines)
    for a, b, who in cov['overlaps']:
        warns.append('تداخل في المصدر %s بين المواضيع %s' % (_rng(a, b), '، '.join(map(str, who))))
    for a, b in cov['uncovered']:
        warns.append('فجوة: أسطر المصدر %s مش متغطية' % _rng(a, b))
    for tid in cov['out_of_range']:
        warns.append('src الموضوع %d خارج النطاق [L1..L%d]' % (tid, total_lines))
    plan_axes = {a['id'] for a in pr.lecture.axes_plan}
    if plan_axes:
        for u in pr.topics():
            if u.axis not in plan_axes:
                warns.append('الموضوع %d تابع لمحور %s مش في الخطة' % (u.id, u.axis))
    for ax in pr.axes:
        if ax.implicit:
            continue
        nt = sum(1 for u in ax.units if isinstance(u, Topic))
        if nt and not 2 <= nt <= 15:
            warns.append('المحور %d فيه %d موضوع (المتوقع 2..15) — للعلم' % (ax.id, nt))
        if not any(isinstance(u, Wrap) for u in ax.units):
            warns.append('المحور %d من غير ملخص (WRAP)' % ax.id)
        if not any(isinstance(u, Case) for u in ax.units):
            warns.append('المحور %d من غير حالة واحدة على الأقل' % ax.id)
    for k, issue in structural_issues(pr):
        warns.append('%s: %s' % (k, issue))
    return errors, warns


def repair_targets(pr: ParseResult) -> List[Tuple[str, str]]:
    """(key, issue) لكل وحدة متوقعة ناقصة، ثم الوحدات الكاملة اللي بنيتها مكسورة."""
    led = pr.ledger
    done = set(led.done)
    out = []
    for k in led.expected:
        if k not in done:
            out.append((k, 'incomplete' if (k in led.incomplete or k == led.partial) else 'missing'))
    out.extend(structural_issues(pr))
    seen, res = set(), []
    for k, i in out:
        if k not in seen:
            seen.add(k)
            res.append((k, i))
    return res


# ════════════════════════════════════════════════════════════════════
#  8) قص/دمج النص (R-42/R-43) + أدوات الـ compact context
# ════════════════════════════════════════════════════════════════════
def _line_marker(s: str) -> Optional[str]:
    m = MARKER_RE.match(s)
    return m.group(1) if m else None


def _end_positions(text: str):
    """[(رقم سطر النهاية، done)] لكل وحدة + سطور الأصل."""
    lines = normalize_lines(text)
    p = _Parser()
    for ln, l in lines:
        try:
            p.feed(ln, l)
        except Exception:
            pass
    p.finish(len(lines))
    return lines, p


def trim_to_complete(text: str) -> str:
    """يقص عند آخر وحدة مقفولة بـ DONE (+ CHECKPOINT/CONTINUE/إطار محور بعدها مباشرة). R-42."""
    lines, p = _end_positions(text)
    ends = [u.end_line for u in p.units if u.done]
    if not ends:
        for ln, l in lines:
            if _line_marker(l) == 'PLAN_END':
                return '\n'.join(x for n, x in lines if n <= ln).rstrip() + '\n'
        return ''
    cut = max(ends)
    keep_after = {'CHECKPOINT', 'CONTINUE', 'AXIS_START', 'AXIS_INTRO', 'WARMUP'}
    last_kept = cut
    for ln, l in lines:
        if ln <= cut or not l.strip():
            continue
        mk = _line_marker(l)
        if mk in keep_after:
            last_kept = ln
        else:
            break
    return '\n'.join(x for n, x in lines if n <= last_kept).rstrip() + '\n'


def extract_tail(text: str) -> str:
    """بعد آخر وحدة كاملة: يرجّع HIGHYIELD كاملة + BIGPICTURE + FINAL بس (باقي الكلام بيتشال)."""
    lines, p = _end_positions(text)
    ends = [u.end_line for u in p.units if u.done]
    cut = max(ends) if ends else 0
    out, in_hy, hy_buf = [], False, []
    for ln, l in lines:
        if ln <= cut:
            continue
        mk = _line_marker(l)
        if mk == 'HIGHYIELD_START':
            in_hy, hy_buf = True, [l]
        elif in_hy and mk == 'HIGHYIELD_END':
            out.extend(hy_buf + [l])
            in_hy, hy_buf = False, []
        elif in_hy:
            hy_buf.append(l)
        elif mk in ('BIGPICTURE', 'FINAL'):
            out.append(l)
    return '\n'.join(out)


def strip_preamble(text: str) -> str:
    """يشيل أي كلام قبل أول سطر @@ (R-43)."""
    lines = text.replace('\r', '').split('\n')
    for i, ln in enumerate(lines):
        if ln.strip().startswith('@@'):
            return '\n'.join(lines[i:])
    return ''


def remove_plan(text: str) -> str:
    """يشيل أي كتلة PLAN_START…PLAN_END اتعادت (R-43)."""
    out, skip = [], False
    for l in text.replace('\r', '').split('\n'):
        mk = _line_marker(l)
        if mk == 'PLAN_START':
            skip = True
            continue
        if skip:
            if mk == 'PLAN_END':
                skip = False
            elif mk in UNIT_START or mk in ('AXIS_START', 'HIGHYIELD_START'):
                skip = False
                out.append(l)
            continue
        out.append(l)
    return '\n'.join(out)


def plan_block(text: str) -> str:
    lines = normalize_lines(text)
    st = en = None
    for ln, l in lines:
        mk = _line_marker(l)
        if mk == 'PLAN_START' and st is None:
            st = ln
        elif mk == 'PLAN_END' and st is not None:
            en = ln
            break
    if st is None or en is None:
        return ''
    return '\n'.join(x for n, x in lines if st <= n <= en)


def unit_texts(text: str) -> Dict[str, str]:
    """key ← النص الخام لآخر نسخة كاملة من الوحدة (من START لـ END + CHECKPOINT اللي بعدها)."""
    lines, p = _end_positions(text)
    res: Dict[str, str] = {}
    for u in p.units:
        if u.done:
            res[u.key] = '\n'.join(x for n, x in lines if u.line <= n <= u.end_line)
    return res


def synth_final(pr: ParseResult, total: int = 0) -> str:
    """سطر @@FINAL مصنّع (R-41)."""
    axes = sum(1 for a in pr.axes if not a.implicit) or len(pr.axes)
    topics = len(pr.topics())
    cases = sum(1 for u in pr.complete_units() if isinstance(u, Case))
    cov = coverage(pr, total)
    cnt = total or max([b for rg in cov['claims'].values() for _, b in rg] + [0])
    unc = sum(b - a + 1 for a, b in cov['uncovered'])
    covered = max(0, cnt - unc) if cnt else 0
    return '@@FINAL | axes=%d | topics=%d | cases=%d | src_covered=%d/%d | unclear=%d' % (
        axes, topics, cases, covered, cnt, len(pr.unclear()))

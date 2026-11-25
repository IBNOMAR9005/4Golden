#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lecture_to_pdf.py
=================
يحوّل ناتج الـ AI (صيغة @@ markers) إلى ملزمة مذاكرة PDF بصفحات A4.

الاستخدام:
    python lecture_to_pdf.py notes.txt -o lecture.pdf
    python lecture_to_pdf.py part1.txt part2.txt -o lecture.pdf --srt lecture.srt --fonts ./fonts

المتطلبات: reportlab فقط  (pip install reportlab)
    - الكود فيه محرك عربي خاص (تشكيل الحروف + ترتيب عربي/إنجليزي لكل سطر)
      فمش محتاج arabic-reshaper ولا python-bidi.
    - أفضل خطوط: حط في فولدر fonts/ جنب السكريبت أي زوج من:
      Amiri-Regular/Amiri-Bold  أو  Cairo-Regular/Cairo-Bold  أو  NotoNaskhArabic-Regular/Bold
      (لازم TTF ثابت مش variable). لو مفيش، بياخد Arial/Tahoma/DejaVu من السيستم.

لو الناتج جه على أكتر من رد (انقطاع API): الصق الملفات ورا بعض أو مرّرها كلها
للسكريبت. لو موضوع اتكرر، بياخد النسخة المكتملة (DONE) وبيتجاهل الناقصة.
"""
import os, re, sys, copy, math, argparse, unicodedata
from collections import Counter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Flowable, PageBreak,
                                Table, TableStyle, Spacer, CondPageBreak, KeepTogether)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import markers as M

# ════════════════════════════════════════════════════════════════════
#  1) الخطوط
# ════════════════════════════════════════════════════════════════════
# الأولوية: عائلات حديثة بـ Bold حقيقي (كلها OFL). Amiri وباقي القايمة القديمة fallback.
PREFERRED_AR = ('cairo', 'tajawal', 'ibmplexsansarabic')
FONT_PAIRS = {
    'ar': [('Cairo-Regular', 'Cairo-Bold'), ('IBMPlexSansArabic-Regular', 'IBMPlexSansArabic-Bold'),
           ('Tajawal-Regular', 'Tajawal-Bold'), ('NotoNaskhArabic-Regular', 'NotoNaskhArabic-Bold'),
           ('Amiri-Regular', 'Amiri-Bold'),
           ('NotoSansArabic-Regular', 'NotoSansArabic-Bold'), ('arial', 'arialbd'),
           ('tahoma', 'tahomabd'), ('segoeui', 'segoeuib'), ('DejaVuSans', 'DejaVuSans-Bold')],
    'la': [('IBMPlexSans-Regular', 'IBMPlexSans-Bold'), ('Inter-Regular', 'Inter-Bold'),
           ('SourceSans3-Regular', 'SourceSans3-Bold'),
           ('Carlito-Regular', 'Carlito-Bold'), ('calibri', 'calibrib'), ('segoeui', 'segoeuib'),
           ('LiberationSans-Regular', 'LiberationSans-Bold'), ('arial', 'arialbd'),
           ('DejaVuSans', 'DejaVuSans-Bold')],
    'sym': [('DejaVuSans', 'DejaVuSans-Bold'), ('seguisym', 'seguisym'), ('arial', 'arialbd')],
}
VARIABLE_SKIPPED = []
F = {}     # 'AR' -> (regular, bold)
COV = {}   # 'AR' -> set of covered codepoints


def _is_variable(path):
    """TTFont بتاع ReportLab ما بيدعمش variable (بياخد الـ default بس) فبنتجاهلها."""
    try:
        import struct
        with open(path, 'rb') as f:
            head = f.read(12)
            n = struct.unpack('>H', head[4:6])[0]
            tags = f.read(16 * n)
        return any(tags[i:i + 4] == b'fvar' for i in range(0, len(tags), 16))
    except Exception:
        return False


def _index_fonts(extra):
    dirs = [extra, os.path.join(HERE, 'fonts'), HERE, os.path.expanduser('~/.fonts'),
            os.path.expanduser('~/Library/Fonts'), '/usr/share/fonts', '/usr/local/share/fonts',
            '/Library/Fonts', '/System/Library/Fonts/Supplemental', 'C:\\Windows\\Fonts', '/content']
    idx = {}
    for d in dirs:
        if d and os.path.isdir(d):
            for root, _, files in os.walk(d):
                for fn in files:
                    if fn.lower().endswith('.ttf'):
                        full = os.path.join(root, fn)
                        if _is_variable(full):
                            if fn not in VARIABLE_SKIPPED:
                                VARIABLE_SKIPPED.append(fn)
                            continue
                        idx.setdefault(fn[:-4].lower(), full)
    return idx


def _covers(path, cps):
    try:
        face = TTFont('_probe', path).face.charToGlyph
        return all(cp in face for cp in cps)
    except Exception:
        return False


def setup_fonts(extra=None):
    del VARIABLE_SKIPPED[:]
    F.clear(); COV.clear()
    idx = _index_fonts(extra)
    need_ar = [0xFE8D, 0xFEDF, 0xFEFB, 0x0640, 0x061F, 0x060C]
    chosen = {}
    for fam, key, need in (('ar', 'AR', need_ar), ('la', 'LA', [0x41, 0x61, 0x30]), ('sym', 'SYM', [0x2190, 0x2192])):
        got = None
        for reg, bold in FONT_PAIRS[fam]:
            r = idx.get(reg.lower())
            b = idx.get(bold.lower()) or r
            if r and _covers(r, need):
                got = (reg, r, b)
                break
        if not got:
            if key == 'AR':
                sys.exit('✗ مفيش خط عربي مناسب. حط Cairo أو IBMPlexSansArabic (TTF ثابت) في فولدر fonts/ (شوف fonts/README.md).')
            F[key] = F['LA']
            COV[key] = COV['LA']
            continue
        pdfmetrics.registerFont(TTFont(key, got[1]))
        pdfmetrics.registerFont(TTFont(key + '-B', got[2]))
        F[key] = (key, key + '-B')
        COV[key] = set(pdfmetrics.getFont(key).face.charToGlyph.keys())
        chosen[key] = got[0]
    print('الخطوط:', ', '.join('%s=%s' % kv for kv in chosen.items()))
    ar = chosen.get('AR', '').lower()
    if not any(ar.startswith(p) for p in PREFERRED_AR):          # تنبيه واحد بس باسم الملف الناقص (R-70)
        extra_msg = (' | variable متجاهَل: %s (اعمل static، شوف fonts/README.md)' % ', '.join(VARIABLE_SKIPPED)) \
            if VARIABLE_SKIPPED else ''
        print('⚠ الخط العربي المفضل (Cairo-Regular.ttf أو IBMPlexSansArabic-Regular.ttf) مش موجود؛ استخدمت %s%s'
              % (chosen.get('AR', '?'), extra_msg))


def neutral_family(t):
    for fam in ('AR', 'LA', 'SYM'):
        cov = COV[fam]
        if all(ord(ch) in cov for ch in t):
            return fam
    return 'AR'


# ════════════════════════════════════════════════════════════════════
#  2) محرك العربي: تشكيل الحروف
# ════════════════════════════════════════════════════════════════════
DUAL = set('بتثجحخسشصضطظعغفقكلمنهيىئ\u0640')
RIGHT = set('اأإآٱدذرزوؤة')
NONJOIN = set('ء')
_FORMS, _LIG = {}, {}
for _cp in range(0xFE70, 0xFEFF):
    _d = unicodedata.decomposition(chr(_cp))
    if not _d.startswith('<'):
        continue
    _tag, _rest = _d.split(' ', 1)
    _tag = _tag.strip('<>')
    _parts = _rest.split()
    if _tag not in ('isolated', 'final', 'initial', 'medial'):
        continue
    if len(_parts) == 1:
        _FORMS.setdefault(chr(int(_parts[0], 16)), {}).setdefault(_tag, chr(_cp))
    elif len(_parts) == 2 and _parts[0] == '0644':
        _LIG.setdefault((chr(0x644), chr(int(_parts[1], 16))), {})[_tag] = chr(_cp)

_MARKS = re.compile('[\u064B-\u065F\u0670\u06D6-\u06ED]')


def shape(s):
    s = _MARKS.sub('', s)
    out, n, i, prev_dual = [], len(s), 0, False
    while i < n:
        c = s[i]
        if c not in DUAL and c not in RIGHT and c not in NONJOIN:
            out.append(c); prev_dual = False; i += 1
            continue
        if c == 'ل' and i + 1 < n and s[i + 1] in 'آأإا':
            lig = _LIG.get(('ل', s[i + 1]), {}).get('final' if prev_dual else 'isolated')
            if lig:
                out.append(lig); prev_dual = False; i += 2
                continue
        nxt = i + 1 < n and (s[i + 1] in DUAL or s[i + 1] in RIGHT)
        if c in DUAL:
            f = 'medial' if (prev_dual and nxt) else 'final' if prev_dual else 'initial' if nxt else 'isolated'
            prev_dual = True
        elif c in RIGHT:
            f = 'final' if prev_dual else 'isolated'; prev_dual = False
        else:
            f = 'isolated'; prev_dual = False
        out.append(c if c == '\u0640' else _FORMS.get(c, {}).get(f, c))
        i += 1
    return ''.join(out)


# ════════════════════════════════════════════════════════════════════
#  3) محرك النص: chunks + ترتيب ثنائي الاتجاه لكل سطر + قصّ السطور
# ════════════════════════════════════════════════════════════════════
AR = '\u0621-\u064A\u0640\u0671-\u06D3'
LA = 'A-Za-z0-9\u00C0-\u024F\u0370-\u03FF'
TOKEN_RE = re.compile(
    r'(?P<sp>[ \t\n\r\xa0]+)'
    rf'|(?P<ar>[{AR}]+)'
    rf"|(?P<la>[<>=~≥≤±×]?[{LA}]+(?:[-'’./:+#&_]+[{LA}]+)*%?)"
    rf'|(?P<ne>[^ \t\n\r\xa0{AR}{LA}]+)')
_ADIG = str.maketrans('٠١٢٣٤٥٦٧٨٩٪٫', '0123456789%.')
_MIRROR = str.maketrans('()[]{}«»', ')(][}{»«')


def H(x):
    return HexColor(x)


INK, MUTED, LINE = H('#1F2937'), H('#6B7280'), H('#D7DDE8')
LATIN, NUMC, QCOL, BOLDC = H('#0B5FA5'), H('#B45309'), H('#E67E22'), H('#0F2A4A')


def PS(size=9.7, lead=None, color=INK, bold=False, align='auto', justify=False,
       la=LATIN, num=NUMC, boldc=BOLDC, sb=0, sa=0, lascale=1.0):
    return dict(size=size, lead=lead or size * 1.5, color=color, bold=bold, align=align,
                justify=justify, la=la, num=num, boldc=boldc, sb=sb, sa=sa, lascale=lascale)


class Chunk:
    __slots__ = ('t', 'kind', 'bold', 'special', 'font', 'size', 'color', 'w', 'vis', 'shaped', 'bg', 'hsize')

    def __init__(self, t, kind, bold=False, special=None):
        self.t, self.kind, self.bold, self.special = t, kind, bold, special
        self.vis = t


# شارات الـ inline tags (§4.2): نص، لون الخلفية، لون الحرف (تباين ≥ 4.5)
BADGES = {'[إضافة]': ('إضافة', '#DBEAFE', '#1E3A8A'), '[راجع المرجع]': ('راجع المرجع', '#FEF3C7', '#78350F'),
          '[؟]': ('؟', '#FFE4D1', '#7C2D12'), '[?]': ('؟', '#FFE4D1', '#7C2D12')}


def style_chunk(ch, st):
    b = ch.bold or st['bold']
    if ch.kind == 'B':                       # شارة: بتتصمم كحروف عربي بترتيب مرئي جاهز
        label, bg, fg = BADGES[ch.special]
        ch.size, ch.hsize = st['size'] * 0.76, st['size']
        ch.font = F['AR'][1]
        ch.shaped = ch.vis = shape(label)[::-1]
        ch.color, ch.bg = H(fg), H(bg)
        ch.w = pdfmetrics.stringWidth(ch.shaped, ch.font, ch.size) + 7
        return
    if ch.kind == 'R':
        ch.shaped, fam = shape(ch.t), 'AR'
    elif ch.kind in ('L', 'D'):
        ch.shaped, fam = ch.t, 'LA'
    else:
        ch.shaped, fam = ch.t, neutral_family(ch.t)
    ch.font = F[fam][1 if b else 0]
    ch.size = st['size'] * (st['lascale'] if fam == 'LA' else 1.0)
    if ch.kind == 'L':
        ch.color = st['la'] or st['color']
    elif ch.kind == 'D':
        ch.color = st['num'] or st['color']
    elif ch.kind == 'R' and ch.bold and st['boldc'] is not None:
        ch.color = st['boldc'] if st['color'] is INK else st['color']
    else:
        ch.color = st['color']
    ch.w = pdfmetrics.stringWidth(ch.shaped, ch.font, ch.size)
    ch.vis = ch.shaped


_INLINE_SPLIT = re.compile(r'(\*\*|\[إضافة\]|\[راجع المرجع\]|\[؟\]|\[\?\])')


def parse_inline(text):
    """[(نص، bold، special)] — special = مفتاح الشارة. لو عدد ** فردي بتتعرض حرفياً (R: §4.2)."""
    parts, bold = [], False
    literal = text.count('**') % 2 == 1
    for tok in _INLINE_SPLIT.split(text):
        if tok == '**':
            if literal:
                parts.append((tok, bold, None))
            else:
                bold = not bold
        elif tok in BADGES:
            parts.append((tok, bold, tok))
        elif tok:
            parts.append((tok, bold, None))
    return parts


DROPPED = Counter()        # حروف اتشالت لأنها مش في أي خط (تنبيه مجمّع واحد في الآخر)
_ARR_RTL = str.maketrans('→⟶', '←⟵')
_ARR_LTR = str.maketrans('←⟵', '→⟶')


def _keep(ch):
    if ch.isspace():
        return True
    cp = ord(ch)
    if cp < 0x20 or ch in '\u200c\u200d':
        return False
    if ch in DUAL or ch in RIGHT or ch in NONJOIN or _MARKS.match(ch):
        return True
    return any(cp in COV.get(f, ()) for f in ('AR', 'LA', 'SYM'))


def sanitize(txt):
    """يشيل أي حرف مش مغطى بالخطوط عشان مايظهرش tofu (R-17)، وبيعدّه."""
    if all(_keep(c) for c in txt):
        return txt
    out = []
    for c in txt:
        if _keep(c):
            out.append(c)
        elif ord(c) >= 0x20 and c not in '\u200c\u200d':
            DROPPED[c] += 1
    return ''.join(out)


def make_chunks(text, st):
    chunks, has_ar = [], False
    # اتجاه الأسهم العادية في النص = اتجاه القراءة بتاع الفقرة (R-72)
    arrows = _ARR_RTL if re.search('[%s]' % AR, text) else _ARR_LTR
    for txt, bold, special in parse_inline(text):
        if special:
            ch = Chunk(special, 'B', bold, special)
            style_chunk(ch, st)
            chunks.append(ch)
            continue
        txt = sanitize(txt.translate(_ADIG).translate(arrows))
        for m in TOKEN_RE.finditer(txt):
            g, s = m.lastgroup, m.group()
            if g == 'sp':
                if chunks and chunks[-1].kind == 'S':
                    continue
                ch = Chunk(' ', 'S')
            elif g == 'ar':
                ch = Chunk(s, 'R', bold); has_ar = True
            elif g == 'la':
                first = re.search(f'[{LA}]', s).group()
                ch = Chunk(s, 'D' if first.isdigit() else 'L', bold)
            else:
                ch = Chunk(s, 'N', bold, special)
            style_chunk(ch, st)
            chunks.append(ch)
    while chunks and chunks[0].kind == 'S':
        chunks.pop(0)
    while chunks and chunks[-1].kind == 'S':
        chunks.pop()
    return chunks, has_ar


def reorder(line, rtl):
    """ترتيب مرئي لسطر واحد (UBA مبسّط على مستوى الـ chunks)."""
    n = len(line)
    if n == 0:
        return []
    e = 1 if rtl else 0
    sos = 'R' if rtl else 'L'
    t, last = [], sos
    for ch in line:
        k = ch.kind
        if k in ('R', 'L'):
            last = k; t.append(k)
        elif k == 'D':
            t.append('L' if last == 'L' else 'D')
        else:
            t.append('N')
    # علامة لاصقة بالرقم (4+ ، 40% ، 37°) بتفضل بعده في الـ run مش بتتعكس
    for i in range(n - 1):
        if t[i] == 'D' and line[i + 1].kind == 'N' and line[i + 1].t and all(c in '+%\u2030\u00b0' for c in line[i + 1].t):
            t[i + 1] = 'D'
    # رقم + مسافة + كلمة لاتينية (3.5 g/day، 20-80 mg) = LTR run واحد حتى جوه جملة عربي
    for i in range(n - 2):
        if t[i] == 'D' and line[i + 1].kind == 'S' and t[i + 2] == 'L':
            t[i], t[i + 1] = 'L', 'L'

    def sd(k):
        return 'L' if k == 'L' else 'R'
    res, i = t[:], 0
    while i < n:
        if t[i] == 'N':
            j = i
            while j < n and t[j] == 'N':
                j += 1
            left = sd(t[i - 1]) if i > 0 else sos
            right = sd(t[j]) if j < n else sos
            d = left if left == right else sos
            for k in range(i, j):
                res[k] = d
            i = j
        else:
            i += 1
    levels = []
    for k in res:
        if k == 'L':
            levels.append(e if e % 2 == 0 else e + 1)
        elif k == 'R':
            levels.append(e if e % 2 == 1 else e + 1)
        else:
            levels.append(e + 2 if e % 2 == 0 else e + 1)
    order = list(range(n))
    odds = [l for l in levels if l % 2 == 1]
    if odds:
        for lvl in range(max(levels), min(odds) - 1, -1):
            i = 0
            while i < n:
                if levels[order[i]] >= lvl:
                    j = i
                    while j < n and levels[order[j]] >= lvl:
                        j += 1
                    order[i:j] = reversed(order[i:j])
                    i = j
                else:
                    i += 1
    out = []
    for idx in order:
        ch = line[idx]
        if levels[idx] % 2 == 1:
            if ch.kind == 'R':
                ch.vis = ch.shaped[::-1]
            elif ch.kind == 'N':
                ch.vis = ch.shaped[::-1].translate(_MIRROR)
            else:
                ch.vis = ch.shaped
        else:
            ch.vis = ch.shaped
        out.append(ch)
    return out


def _space(spw):
    s = Chunk(' ', 'S')
    s.w, s.shaped, s.vis, s.font, s.size, s.color = spw, ' ', ' ', F['AR'][0], 0, INK
    return s


def break_lines(chunks, width, first_indent, spw):
    words, cur = [], []
    for ch in chunks:
        if ch.kind == 'S':
            if cur:
                words.append(cur); cur = []
        else:
            cur.append(ch)
    if cur:
        words.append(cur)
    lines, line, lw, avail = [], [], 0.0, width - first_indent
    for w in words:
        ww = sum(c.w for c in w)
        if line and lw + spw + ww > avail + 0.5:
            lines.append(line); line = list(w); lw = ww; avail = width
        else:
            if line:
                line.append(_space(spw)); lw += spw
            line.extend(w); lw += ww
    if line:
        lines.append(line)
    return lines


def _draw_visual(c, vis, x, y, extra=0.0):
    for ch in vis:
        if ch.kind == 'B':
            c.setFillColor(ch.bg)
            c.roundRect(x + .5, y - ch.hsize * .22, ch.w - 1, ch.hsize * .98, 2.6, stroke=0, fill=1)
            c.setFont(ch.font, ch.size)
            c.setFillColor(ch.color)
            c.drawString(x + 3.5, y + ch.hsize * .04, ch.vis)
            x += ch.w
        elif ch.kind != 'S':
            c.setFont(ch.font, ch.size)
            c.setFillColor(ch.color)
            c.drawString(x, y, ch.vis)
            x += ch.w
        else:
            x += ch.w + extra


def text_width(text, st):
    chunks, _ = make_chunks(text, st)
    return sum(ch.w for ch in chunks)


def draw_text(c, text, x, y, st, align='R', maxw=None):
    """يرسم سطر واحد. align: R (x = الحافة اليمنى) / L / C. بيصغّر الخط لو زاد عن maxw."""
    cur = st
    for sc in (1, .93, .86, .8, .74, .68):
        cur = dict(st, size=st['size'] * sc)
        chunks, rtl = make_chunks(text, cur)
        w = sum(ch.w for ch in chunks)
        if maxw is None or w <= maxw:
            break
    if maxw is not None and w > maxw:
        while len(text) > 4 and w > maxw:
            text = text[:-2]
            chunks, rtl = make_chunks(text + '…', cur)
            w = sum(ch.w for ch in chunks)
    vis = reorder(chunks, rtl)
    x0 = x - w if align == 'R' else x - w / 2 if align == 'C' else x
    _draw_visual(c, vis, x0, y)
    return w


# ════════════════════════════════════════════════════════════════════
#  4) RichPara: فقرة عربي/إنجليزي قابلة للتقسيم بين الصفحات
# ════════════════════════════════════════════════════════════════════
class RichPara(Flowable):
    def __init__(self, text, st, deco=None):
        Flowable.__init__(self)
        self.text, self.st, self.deco = text, st, deco or {}
        self.chunks, self.rtl = make_chunks(text, st)
        self.spw = pdfmetrics.stringWidth(' ', F['AR'][0], st['size'])
        self._lines, self._sliced = None, False
        self.is_first = self.is_last = True
        self.spaceBefore, self.spaceAfter = st['sb'], st['sa']
        k = self.deco.get('kind')
        self.pl = self.pr = self.pt = self.pb = self.gut = 0
        if k == 'box':
            self.pl, self.pr, self.pt, self.pb = 7, 11.5, 5, 5
        elif k == 'bullet':
            self.gut = 12
        elif k == 'num':
            self.gut = 18
        elif k == 'link':
            self.gut = 18
        elif k == 'h2':
            self.pr, self.pt, self.pb = 9, 3, 3.5
        self.chip_w = 0
        if k == 'box' and self.deco.get('label'):
            self.chip_st = PS(7.3, bold=True, color=white, la=white, num=white, boldc=None)
            self.chip_w = text_width(self.deco['label'], self.chip_st) + 12

    def getSpaceBefore(self):
        return self.spaceBefore

    def getSpaceAfter(self):
        return self.spaceAfter

    def natural(self):
        return sum(c.w for c in self.chunks)

    def minw(self):
        best = cur = 0
        for ch in self.chunks:
            if ch.kind == 'S':
                best = max(best, cur); cur = 0
            else:
                cur += ch.w
        return max(best, cur)

    def wrap(self, aw, ah):
        self.aw = aw
        self.tw = aw - self.pl - self.pr - self.gut
        if not self._sliced:
            fi = self.chip_w + 6 if self.chip_w else 0
            self._lines = break_lines(self.chunks, self.tw, fi, self.spw)
        self.width = aw
        self.height = self.pt + self.pb + len(self._lines) * self.st['lead']
        return aw, self.height

    def split(self, aw, ah):
        if self._lines is None or self.aw != aw:
            self.wrap(aw, ah)
        n, lead = len(self._lines), self.st['lead']
        fit = int((ah - self.pt - self.pb) // lead)
        if fit >= n or n < 3 or fit < 2:
            return []
        if n - fit < 2:
            fit = n - 2
        if fit < 2:
            return []
        a, b = copy.copy(self), copy.copy(self)
        a._lines, b._lines = self._lines[:fit], self._lines[fit:]
        a._sliced = b._sliced = True
        a.is_last, b.is_first = False, False
        a.spaceAfter, b.spaceBefore = 0, 0
        return [a, b]

    def draw(self):
        c, st, d = self.canv, self.st, self.deco
        W, Hh, k = self.width, self.height, d.get('kind')
        size, lead = st['size'], st['lead']
        if k == 'box':
            c.setFillColor(d['bg']); c.setStrokeColor(d['bd']); c.setLineWidth(d.get('lw', .6))
            if d.get('dash'):
                c.setDash(3, 2.2)
            c.roundRect(0, 0, W, Hh, 3.2, stroke=1, fill=1)
            c.setDash()
            bw = d.get('bar', 4.4)
            c.setFillColor(d['bd'])
            c.roundRect(W - bw, 0, bw, Hh, min(2.2, bw / 2), stroke=0, fill=1)
        elif k == 'h2':
            c.setFillColor(d['bd']); c.rect(W - 3.4, 2, 3.4, Hh - 4, stroke=0, fill=1)
            c.setStrokeColor(d['line']); c.setLineWidth(.7); c.line(0, .6, W - 9, .6)
        if d.get('dest'):
            c.linkRect('', d['dest'], (0, 0, W, Hh), relative=1, thickness=0)
        x_l, x_r = self.pl, W - self.pr - self.gut
        align = st['align'] if st['align'] != 'auto' else ('R' if self.rtl else 'L')
        for i, line in enumerate(self._lines):
            base = Hh - self.pt - i * lead - (lead - size) / 2 - size * .82
            first = (i == 0 and self.is_first)
            fi = (self.chip_w + 6) if (first and self.chip_w) else 0
            avail = self.tw - fi
            vis = reorder(line, self.rtl)
            lw = sum(ch.w for ch in vis)
            nsp = sum(1 for ch in vis if ch.kind == 'S')
            extra = 0.0
            last = (i == len(self._lines) - 1) and self.is_last
            if st['justify'] and not last and nsp and avail * .72 < lw < avail:
                extra = (avail - lw) / nsp
                lw = avail
            if align == 'R':
                x = x_r - fi - lw
            elif align == 'L':
                x = x_l
            else:
                x = x_l + (self.tw - lw) / 2
            _draw_visual(c, vis, x, base, extra)
            if first:
                yc = base + size * .32
                if self.chip_w:
                    c.setFillColor(d['bd'])
                    c.roundRect(x_r - self.chip_w, yc - 6.2, self.chip_w, 12.4, 3.4, stroke=0, fill=1)
                    draw_text(c, d['label'], x_r - self.chip_w / 2, yc - 2.5, self.chip_st, 'C')
                if k == 'bullet':
                    bx = W - self.pr - 5
                    c.setFillColor(d['bd']); c.setStrokeColor(d['bd'])
                    if d.get('mk') == 'tick':
                        c.setLineWidth(1.5)
                        c.line(bx - 3.4, yc, bx - 1, yc - 2.4); c.line(bx - 1, yc - 2.4, bx + 3.4, yc + 2.6)
                    else:
                        c.circle(bx, yc, 2.2, stroke=0, fill=1)
                elif k == 'link':                 # سهم فيكتور بيشاور شمال (اتجاه القراءة RTL)
                    bx = W - self.pr - 8
                    c.setStrokeColor(d['bd']); c.setFillColor(d['bd']); c.setLineWidth(1.3)
                    c.line(bx + 5, yc, bx - 5, yc)
                    p = c.beginPath(); p.moveTo(bx - 6.5, yc); p.lineTo(bx - 2, yc + 3.2); p.lineTo(bx - 2, yc - 3.2); p.close()
                    c.drawPath(p, stroke=0, fill=1)
                elif k == 'num':
                    bx = W - self.pr - 8
                    c.setFillColor(d['bd']); c.circle(bx, yc, 6.2, stroke=0, fill=1)
                    nst = PS(7.6, bold=True, color=white, la=white, num=white, boldc=None)
                    draw_text(c, str(d.get('n', '')), bx, yc - 2.6, nst, 'C')


# ════════════════════════════════════════════════════════════════════
#  5) ألوان وأنواع البلوكات
# ════════════════════════════════════════════════════════════════════
ACCENTS = [('#1E3A5F', '#E9F0F9', '#7FA2CC'), ('#0F766E', '#E5F4F2', '#6DBDB5'),
           ('#6D28D9', '#F0EAFB', '#A58BE0'), ('#B45309', '#FDF1E3', '#E2A66B'),
           ('#BE185D', '#FCE9F1', '#E58DB3'), ('#15803D', '#E8F5EC', '#7CC293'),
           ('#3730A3', '#ECECFA', '#8E8AE0'), ('#4D7C0F', '#F0F6E4', '#A6C46A')]
# ألوان دلالية ثابتة (ما بتتغيرش بلون المحور): label, border, bg, extras
BLOCKS = {
    'KEY': ('نقطة أساسية', '#1D4ED8', '#EAF1FF', {}),
    'EMPH': ('الدكتور شدد عليها', '#B94E0A', '#FFF3E8', {}),
    'WARN': ('تحذير', '#B42318', '#FEF3F2', {}),
    'RED': ('علامة خطر', '#7A1020', '#FCE7EA', {'lw': 1.6, 'bar': 8}),
    'PEARL': ('لؤلؤة إكلينيكية', '#A16207', '#FFF8DB', {}),
    'CLIN': ('حالة إكلينيكية', '#047857', '#E6F6EF', {}),
    'NOTE': ('ملحوظة', '#475569', '#F0F3F7', {}),
    'EXTRA': ('من خارج المحاضرة', '#6B7280', '#F7F7F8', {'dash': True}),
}


def box_deco(kind):
    label, bd, bg, ex = BLOCKS[kind]
    return dict(kind='box', bg=H(bg), bd=H(bd), label=label, **ex)


# ════════════════════════════════════════════════════════════════════
#  6) فلوابلز مخصّصة
# ════════════════════════════════════════════════════════════════════
class TitleBlock(Flowable):
    def __init__(self, meta, acc):
        Flowable.__init__(self)
        self.meta, self.acc = meta, acc

    def wrap(self, aw, ah):
        self.width, self.height = aw, 84
        return aw, 84

    def draw(self):
        c, W, h, m = self.canv, self.width, self.height, self.meta
        dark, mid = H(self.acc[0]), H(self.acc[2])
        c.setFillColor(dark); c.roundRect(0, 0, W, h, 7, stroke=0, fill=1)
        c.saveState(); c.setFillAlpha(.07); c.setFillColor(white)
        c.circle(W * .52, h + 6, 58, stroke=0, fill=1); c.circle(W * .40, -14, 44, stroke=0, fill=1)
        c.restoreState()
        c.setFillColor(H('#FFD66B')); c.roundRect(0, 0, 96, h, 7, stroke=0, fill=1)
        c.rect(60, 0, 40, h, stroke=0, fill=1)
        c.setFillColor(dark); c.rect(96, 0, 3, h, stroke=0, fill=1)
        num = str(m.get('number', '')).strip() or '--'
        draw_text(c, 'LECTURE', 48, h - 20, PS(8, color=dark, bold=True, la=dark, num=dark, boldc=None), 'C')
        draw_text(c, num, 48, h / 2 - 15, PS(38, color=dark, bold=True, la=dark, num=dark, boldc=None), 'C', maxw=84)
        draw_text(c, 'محاضرة', 48, 10, PS(8.5, color=dark, bold=True, la=dark, num=dark, boldc=None), 'C')
        draw_text(c, 'ملزمة مذاكرة  ·  STUDY NOTES', W - 16, h - 20,
                  PS(8, color=H('#FFD66B'), bold=True, la=H('#FFD66B'), num=H('#FFD66B'), boldc=None), 'R')
        draw_text(c, m.get('title', ''), W - 16, h / 2 - 7,
                  PS(21, color=white, bold=True, la=white, num=white, boldc=None), 'R', maxw=W - 140)
        sub = '  ·  '.join(x for x in (m.get('doctor', ''), m.get('course', '')) if x)
        if sub:
            draw_text(c, sub, W - 16, 11, PS(9.2, color=H('#D5E3F5'), la=H('#D5E3F5'), num=H('#D5E3F5'), boldc=None),
                      'R', maxw=W - 140)


class TopicBanner(Flowable):
    is_banner = True

    def __init__(self, t, acc, level=0):
        Flowable.__init__(self)
        self.tid, self.title, self.en = t['id'], t['title'], t['en']
        self.time, self.srt, self.accent, self.level = t['time'], t['srt'], acc, level

    def wrap(self, aw, ah):
        self.width, self.height = aw, 38
        return aw, 38

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        dark, mid = H(self.accent[0]), H(self.accent[2])
        c.setFillColor(dark); c.roundRect(0, 0, W, h, 5, stroke=0, fill=1)
        c.setFillColor(mid); c.rect(0, 0, 6, h, stroke=0, fill=1)
        c.roundRect(0, 0, 8, h, 3, stroke=0, fill=1)
        c.setFillColor(dark); c.rect(5, 0, 6, h, stroke=0, fill=1)
        c.setFillColor(white); c.circle(W - 21, h / 2, 12.6, stroke=0, fill=1)
        draw_text(c, str(self.tid), W - 21, h / 2 - 4.6, PS(13.5, color=dark, bold=True, la=dark, num=dark, boldc=None), 'C')
        light = H('#D5E3F5')
        ty = h - 17 if self.en else h / 2 - 5
        draw_text(c, self.title, W - 42, ty, PS(14.2, color=white, bold=True, la=white, num=white, boldc=None),
                  'R', maxw=W - 42 - 150)
        if self.en:
            draw_text(c, self.en, W - 42, 7.5, PS(8.4, color=light, la=light, num=light, boldc=None), 'R', maxw=W - 200)
        sm = PS(7.8, color=light, la=light, num=light, boldc=None)
        if self.time:
            draw_text(c, self.time, 18, h - 15, sm, 'L')
        if self.srt:
            draw_text(c, ('SRT ' + self.srt) if re.match(r'^\d', self.srt) else self.srt, 18, 7.5, sm, 'L')
        key = 'topic%s' % self.tid
        c.bookmarkPage(key)
        try:
            c.addOutlineEntry('%s. %s' % (self.tid, self.title), key, self.level)
        except Exception:
            pass


class TocBlock(Flowable):
    """فهرس (محور واحد أو الفهرس العام): entries = [(علامة|None, عنوان, صفحة, accent, dest?)]."""
    def __init__(self, entries, acc, links, head=None):
        Flowable.__init__(self)
        self.entries, self.acc, self.links = entries, acc, links
        self.head = head or 'الفهرس  ·  Contents'

    def wrap(self, aw, ah):
        n = len(self.entries)
        self.cols = 2 if n > 5 else 1
        self.rows = max(1, math.ceil(n / self.cols))
        self.rh = 15.2
        self.width, self.height = aw, 26 + self.rows * self.rh + 5
        return aw, self.height

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        dark, light, mid = [H(x) for x in self.acc]
        c.setFillColor(light); c.setStrokeColor(mid); c.setLineWidth(.6)
        c.roundRect(0, 0, W, h, 5, stroke=1, fill=1)
        c.setFillColor(dark); c.rect(W - 4, 6, 4, h - 12, stroke=0, fill=1)
        draw_text(c, self.head, W - 14, h - 17, PS(10, color=dark, bold=True, la=dark, num=dark, boldc=None), 'R')
        c.setStrokeColor(mid); c.setLineWidth(.5); c.line(10, h - 22, W - 12, h - 22)
        pad, gap = 12, 16
        colw = (W - 2 * pad - gap * (self.cols - 1)) / self.cols
        for i, e in enumerate(self.entries):
            mk, title, page, acc = e[:4]
            dest = e[4] if len(e) > 4 else 'topic%s' % mk
            col, row = divmod(i, self.rows)
            xr = W - pad - col * (colw + gap)
            y = h - 26 - (row + 1) * self.rh + 4.6
            c.setFillColor(H(acc[0]))
            if mk is None:                                     # علامة فيكتور للعناصر اللي من غير رقم
                p = c.beginPath(); p.moveTo(xr - 6, y + 8.4); p.lineTo(xr - .6, y + 3.1)
                p.lineTo(xr - 6, y - 2.2); p.lineTo(xr - 11.4, y + 3.1); p.close()
                c.drawPath(p, stroke=0, fill=1)
            else:
                c.circle(xr - 6, y + 3.1, 5.6, stroke=0, fill=1)
                draw_text(c, str(mk), xr - 6, y + .6, PS(7.2, color=white, bold=True, la=white, num=white, boldc=None), 'C')
            draw_text(c, title, xr - 17, y, PS(8.8, color=INK, boldc=None), 'R', maxw=colw - 17 - 26)
            draw_text(c, str(page), xr - colw, y, PS(8.6, color=dark, bold=True, la=dark, num=dark, boldc=None), 'L')
            c.setStrokeColor(LINE); c.setLineWidth(.4); c.setDash(1, 2)
            c.line(xr - colw + 20, y - 2.6, xr - 17, y - 2.6)
            c.setDash()
            if self.links:
                c.linkRect('', dest, (xr - colw, y - 4, xr, y + 9), relative=1, thickness=0)


class FlowChart(Flowable):
    def __init__(self, steps, acc):
        Flowable.__init__(self)
        self.steps, self.acc = steps, acc
        self.paras = [RichPara(s, PS(8.8, 12.2, align='C', boldc=None)) for s in steps]

    def wrap(self, aw, ah):
        n = len(self.steps)
        per = n if n <= 4 else (3 if n in (5, 6, 9) else 4)
        self.per, self.gap = per, 17
        self.bw = (aw - (per - 1) * self.gap) / per
        for p in self.paras:
            p.wrap(self.bw - 14, 999)
        self.rows = [list(range(i, min(i + per, n))) for i in range(0, n, per)]
        self.rowh = [max(30, max(self.paras[i].height for i in r) + 12) for r in self.rows]
        self.vgap = 15
        self.width = aw
        self.height = sum(self.rowh) + self.vgap * (len(self.rows) - 1) + 8
        self.spaceBefore, self.spaceAfter = 1, 6
        return aw, self.height

    def _arrow(self, c, x1, y1, x2, y2):
        ang = math.atan2(y2 - y1, x2 - x1)
        c.line(x1, y1, x2, y2)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - 5 * math.cos(ang - .45), y2 - 5 * math.sin(ang - .45))
        p.lineTo(x2 - 5 * math.cos(ang + .45), y2 - 5 * math.sin(ang + .45))
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    def layout(self):
        """هندسة الرسم: boxes[i] = (x, y, h) والأسهم segments. الصف الأول بيبدأ من اليمين (RTL)
        فالسهم بيمشي من الخطوة i لـ i+1 ناحية الشمال."""
        geo, y_top = {}, self.height - 4
        for r, idxs in enumerate(self.rows):
            rh = self.rowh[r]
            y0 = y_top - rh
            for k, i in enumerate(idxs):
                geo[i] = (self.width - (k + 1) * self.bw - k * self.gap, y0, rh)
            y_top = y0 - self.vgap
        arrows = []
        for i in range(len(self.steps) - 1):
            x, y, rh = geo[i]
            if geo[i + 1][1] == y:
                arrows.append(('h', (x - 2, y + rh / 2, x - self.gap + 2.5, y + rh / 2)))
            else:
                nx, ny, nrh = geo[i + 1]
                xm, mid_y = x + self.bw / 2, y - self.vgap / 2
                arrows.append(('v', (xm, y, xm, mid_y), (xm, mid_y, nx + self.bw / 2, mid_y),
                               (nx + self.bw / 2, mid_y, nx + self.bw / 2, ny + nrh + 1.5)))
        return geo, arrows

    def draw(self):
        c = self.canv
        dark, light, mid = [H(x) for x in self.acc]
        geo, arrows = self.layout()
        for i, (x, y0, rh) in geo.items():
            c.setFillColor(light); c.setStrokeColor(mid); c.setLineWidth(.9)
            c.roundRect(x, y0, self.bw, rh, 4, stroke=1, fill=1)
            p = self.paras[i]
            p.canv = c
            c.saveState(); c.translate(x + 7, y0 + (rh - p.height) / 2); p.draw(); c.restoreState()
            c.setFillColor(dark); c.circle(x + self.bw - 1, y0 + rh - 1, 7, stroke=0, fill=1)
            draw_text(c, str(i + 1), x + self.bw - 1, y0 + rh - 3.7,
                      PS(8, color=white, bold=True, la=white, num=white, boldc=None), 'C')
        c.setStrokeColor(dark); c.setFillColor(dark); c.setLineWidth(1.3)
        for a in arrows:
            if a[0] == 'h':
                self._arrow(c, *a[1])
            else:
                c.line(*a[1]); c.line(*a[2]); self._arrow(c, *a[3])


class MnemoBox(Flowable):
    def __init__(self, word, meaning):
        Flowable.__init__(self)
        self.word = word
        items = [x.strip() for x in re.split(r'[;؛]', meaning) if x.strip()]
        self.rtl = bool(re.search(f'[{AR}]', word))
        self.tiles = []
        letters = [ch for ch in word if ch.isalnum()]
        for i, it in enumerate(items):
            m = re.match(r'^\s*(\S)\s*[=:：\-–]\s*(.+)$', it)
            if m:
                lt, tx = m.group(1), m.group(2)
            else:
                lt, tx = (letters[i] if i < len(letters) else ''), it
            self.tiles.append((lt, RichPara(tx, PS(8.4, 11.6, align='C', boldc=None))))

    def wrap(self, aw, ah):
        n = max(1, len(self.tiles))
        per = min(n, 6)
        self.per, self.g = per, 6
        self.tw = (aw - 16 - (per - 1) * self.g) / per
        for _, p in self.tiles:
            p.wrap(self.tw - 8, 999)
        self.rows = [self.tiles[i:i + per] for i in range(0, n, per)]
        self.rowh = [26 + max(p.height for _, p in r) + 6 for r in self.rows]
        self.width = aw
        self.height = 24 + sum(self.rowh) + 6
        self.spaceBefore, self.spaceAfter = 1, 6
        return aw, self.height

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        gold, bg = H('#A16207'), H('#FFF8DB')
        c.setFillColor(bg); c.setStrokeColor(H('#D9B400')); c.setLineWidth(.7)
        c.roundRect(0, 0, W, h, 4, stroke=1, fill=1)
        c.setFillColor(H('#D9B400')); c.roundRect(W - 4.4, 0, 4.4, h, 2.2, stroke=0, fill=1)
        chip = PS(7.6, bold=True, color=white, la=white, num=white, boldc=None)
        label = 'Mnemonic  ·  ' + self.word
        cw = text_width(label, chip) + 14
        c.setFillColor(gold); c.roundRect(W - 12 - cw, h - 19, cw, 13, 3.5, stroke=0, fill=1)
        draw_text(c, label, W - 12 - cw / 2, h - 15.3, chip, 'C')
        y_top = h - 24
        for r, row in enumerate(self.rows):
            rh = self.rowh[r]
            for k, (lt, p) in enumerate(row):
                x = (W - 8 - (k + 1) * self.tw - k * self.g) if self.rtl else (8 + k * (self.tw + self.g))
                c.setFillColor(white); c.setStrokeColor(H('#E4C94A')); c.setLineWidth(.6)
                c.roundRect(x, y_top - rh, self.tw, rh, 3, stroke=1, fill=1)
                draw_text(c, lt, x + self.tw / 2, y_top - 20, PS(17, color=gold, bold=True, la=gold, num=gold, boldc=None), 'C')
                p.canv = c
                c.saveState(); c.translate(x + 4, y_top - rh + 4); p.draw(); c.restoreState()
            y_top -= rh


# ════════════════════════════════════════════════════════════════════
#  7) فلوابلز إضافية: محور، خريطة، تعريف، دواء، جداول، صناديق
# ════════════════════════════════════════════════════════════════════
BUILD_WARNS = []          # تنبيهات البناء (بتتطبع بـ ⚠ في build_pdf)
GOLD = ('#7A4B00', '#FFF6DA', '#E4C94A')
GREY = ('#475569', '#F1F4F8', '#94A3B8')
LEVELS_AR = {'easy': 'سهل', 'medium': 'متوسط', 'hard': 'صعب'}


def _w(st_color, bold=False, size=9, lead=None, **kw):
    return PS(size, lead, color=st_color, la=st_color, num=st_color, boldc=None, bold=bold, **kw)


def _placeholder(kind):
    BUILD_WARNS.append('تعذّر عرض بلوك %s فاتحوّل لمكان رمادي' % kind)
    return RichPara('تعذّر عرض هذا الجزء', PS(8.6, 12, color=MUTED, boldc=None, sa=4),
                    deco=dict(kind='box', bg=H('#EEF0F3'), bd=H('#9CA3AF'), label='⚠', dash=True))


def safe(kind, fn):
    """R-76: بلوك واحد بايظ ما يوقعش الـ PDF."""
    try:
        return fn()
    except Exception as e:                       # noqa: BLE001
        BUILD_WARNS.append('(%s: %s)' % (kind, type(e).__name__))
        return [_placeholder(kind)]


class SectionMark(Flowable):
    """مفيش ارتفاع: بيسجّل بداية قسم (bookmark + outline) وبيصفّر المحور الحالي للفوتر."""
    is_section = True

    def __init__(self, name, title=None, level=0, reset=True):
        Flowable.__init__(self)
        self.name, self.title, self.level, self.reset = name, title, level, reset

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        c = self.canv
        c.bookmarkPage('sec_' + self.name)
        if self.title:
            try:
                c.addOutlineEntry(self.title, 'sec_' + self.name, self.level)
            except Exception:
                pass


class AxisBanner(Flowable):
    is_axis = True

    def __init__(self, aid, title, en, acc, n_topics=0, explicit=True):
        Flowable.__init__(self)
        self.aid, self.title, self.en, self.accent, self.n, self.explicit = aid, title, en, acc, n_topics, explicit

    def wrap(self, aw, ah):
        self.width, self.height = aw, 66
        return aw, 66

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        dark, mid = H(self.accent[0]), H(self.accent[2])
        light = H('#E3ECF8')
        c.setFillColor(dark); c.roundRect(0, 0, W, h, 7, stroke=0, fill=1)
        c.saveState(); c.setFillAlpha(.08); c.setFillColor(white)
        c.circle(W * .35, h + 8, 56, stroke=0, fill=1); c.circle(W * .15, -16, 40, stroke=0, fill=1)
        c.restoreState()
        c.setFillColor(mid); c.roundRect(0, 0, 9, h, 4, stroke=0, fill=1); c.rect(5, 0, 6, h, stroke=0, fill=1)
        c.setFillColor(dark); c.rect(9, 0, 3, h, stroke=0, fill=1)
        c.setFillColor(white); c.circle(W - 32, h / 2, 21, stroke=0, fill=1)
        draw_text(c, str(self.aid), W - 32, h / 2 - 8, _w(dark, True, 22), 'C')
        draw_text(c, 'AXIS %s  ·  محور' % self.aid, W - 64, h - 18, _w(light, True, 8), 'R')
        draw_text(c, self.title, W - 64, h / 2 - 8, _w(white, True, 18), 'R', maxw=W - 64 - 90)
        if self.en:
            draw_text(c, self.en, W - 64, 9, _w(light, False, 9), 'R', maxw=W - 64 - 90)
        if self.n:
            draw_text(c, '%d موضوع' % self.n, 20, h / 2 - 3, _w(light, True, 9), 'L')
        key = 'axis%s' % self.aid
        c.bookmarkPage(key)
        try:
            c.addOutlineEntry('المحور %s: %s' % (self.aid, self.title), key, 0)
        except Exception:
            pass


class UnitBanner(Flowable):
    """شريط أصغر للـ wrap / الحالات / صفحة الإجابات."""
    def __init__(self, title, sub, acc, bookmark, outline=None, level=1, flag=None, ident=None, chip=''):
        Flowable.__init__(self)
        self.title, self.sub, self.accent, self.bookmark = title, sub, acc, bookmark
        self.outline, self.level, self.chip = outline, level, chip
        if flag:
            setattr(self, flag, True)
        self.ident = ident

    def wrap(self, aw, ah):
        self.width, self.height = aw, 30
        return aw, 30

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        dark, mid = H(self.accent[0]), H(self.accent[2])
        c.setFillColor(mid); c.roundRect(0, 0, W, h, 5, stroke=0, fill=1)
        c.setFillColor(dark); c.roundRect(0, 0, W - 5, h, 5, stroke=0, fill=1)
        if self.chip:
            cw = text_width(self.chip, _w(dark, True, 8.4)) + 16
            c.setFillColor(white); c.roundRect(W - 12 - cw, h / 2 - 8.5, cw, 17, 8, stroke=0, fill=1)
            draw_text(c, self.chip, W - 12 - cw / 2, h / 2 - 3, _w(dark, True, 8.4), 'C')
            xr = W - 20 - cw
        else:
            xr = W - 14
        draw_text(c, self.title, xr, h / 2 - 4.5, _w(white, True, 12.2), 'R', maxw=xr - 150)
        if self.sub:
            draw_text(c, self.sub, 16, h / 2 - 3.6, _w(H('#D5E3F5'), False, 8.4), 'L', maxw=140)
        c.bookmarkPage(self.bookmark)
        if self.outline:
            try:
                c.addOutlineEntry(self.outline, self.bookmark, self.level)
            except Exception:
                pass


class AxesMap(Flowable):
    """خريطة المحاور: chips بألوان المحاور مع عدد المواضيع."""
    def __init__(self, items):
        Flowable.__init__(self)
        self.items = items          # [(num, title, n_topics, acc)]

    def wrap(self, aw, ah):
        self.width = aw
        self.rows, row, used = [], [], 0.0
        for it in self.items:
            lab = '%s · %s (%d)' % (it[0], it[1], it[2])
            cw = min(aw - 12, text_width(lab, _w(white, True, 8.6)) + 26)
            if row and used + cw + 6 > aw - 16:
                self.rows.append(row); row, used = [], 0.0
            row.append((lab, cw, it[3])); used += cw + 6
        if row:
            self.rows.append(row)
        self.height = 24 + len(self.rows) * 21 + 4
        return aw, self.height

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        c.setFillColor(H('#F8FAFC')); c.setStrokeColor(LINE); c.setLineWidth(.6)
        c.roundRect(0, 0, W, h, 5, stroke=1, fill=1)
        draw_text(c, 'خريطة المحاور  ·  Axes map', W - 12, h - 16, _w(BOLDC, True, 9.4), 'R')
        y = h - 24
        for row in self.rows:
            x = W - 10
            for lab, cw, acc in row:
                c.setFillColor(H(acc[0])); c.roundRect(x - cw, y - 17, cw, 17, 8.5, stroke=0, fill=1)
                draw_text(c, lab, x - cw / 2, y - 12, _w(white, True, 8.6), 'C', maxw=cw - 12)
                x -= cw + 6
            y -= 21


class DefCard(Flowable):
    """كارت تعريف: سطر المصطلح (EN ثم عربي) + التعريف + التشبيه."""
    is_def = True

    def __init__(self, f):
        Flowable.__init__(self)
        self.f = f
        self.term = f['term_en']
        self.defp = RichPara(f['definition'], PS(9.4, 14, justify=True, boldc=None))
        self.anap = RichPara('تشبيه: ' + f['analogy'], PS(9, 13.2, color=H('#334E7A'), boldc=None)) if f.get('analogy') else None
        self.spaceBefore, self.spaceAfter = 1, 6

    def wrap(self, aw, ah):
        self.width = aw
        iw = aw - 24
        self.defp.wrap(iw, 999)
        h = 7 + 17 + self.defp.height + 5
        if self.anap:
            self.anap.wrap(iw - 8, 999)
            h += self.anap.height + 5
        self.height = h
        return aw, h

    def draw(self):
        c, W, h = self.canv, self.width, self.height
        bd, bg = H('#1D4ED8'), H('#EAF1FF')
        c.setFillColor(bg); c.setStrokeColor(bd); c.setLineWidth(.6)
        c.roundRect(0, 0, W, h, 3.2, stroke=1, fill=1)
        c.setFillColor(bd); c.roundRect(W - 4.4, 0, 4.4, h, 2.2, stroke=0, fill=1)
        x = W - 14
        w1 = draw_text(c, self.f['term_en'], x, h - 16, _w(H('#0B3FA8'), True, 10.6), 'R', maxw=W * .5)
        if self.f.get('term_ar'):
            c.setFillColor(bd); c.circle(x - w1 - 8, h - 12.6, 1.6, stroke=0, fill=1)
            draw_text(c, self.f['term_ar'], x - w1 - 15, h - 16, _w(INK, True, 10.2), 'R', maxw=W * .45)
        self.defp.canv = c
        c.saveState(); c.translate(10, h - 21 - self.defp.height); self.defp.draw(); c.restoreState()
        if self.anap:
            y = h - 21 - self.defp.height - 5 - self.anap.height
            c.setStrokeColor(H('#9DB8E8')); c.setDash(2, 2); c.setLineWidth(.6)
            c.line(10, y + self.anap.height + 3, W - 16, y + self.anap.height + 3); c.setDash()
            self.anap.canv = c
            c.saveState(); c.translate(14, y); self.anap.draw(); c.restoreState()


def _ctx_rows_table(rows, W, head_color, label_w=88, head=None, lab_bg='#F1F4F8'):
    data = []
    ts = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 6),
          ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 3.4),
          ('BOTTOMPADDING', (0, 0), (-1, -1), 3.4), ('INNERGRID', (0, 0), (-1, -1), .4, LINE),
          ('BOX', (0, 0), (-1, -1), .9, head_color)]
    r0 = 0
    if head is not None:
        data.append([head, ''])
        ts += [('SPAN', (0, 0), (1, 0)), ('BACKGROUND', (0, 0), (1, 0), head_color)]
        r0 = 1
    for i, (lab, val) in enumerate(rows):
        data.append([val, lab])                    # RTL: العنوان على اليمين
        ts.append(('BACKGROUND', (1, r0 + i), (1, r0 + i), H(lab_bg)))
    t = Table(data, colWidths=[W - label_w, label_w])
    t.setStyle(TableStyle(ts))
    return t


DRUG_ROWS = (('indication', 'الاستخدام'), ('dose', 'الجرعة'), ('mechanism', 'آلية العمل'),
             ('contraindications', 'موانع الاستعمال'), ('adverse_interactions', 'أعراض جانبية وتداخلات'))


def drug_card(f, W):
    hd = PS(10.4, 14, color=white, la=white, num=white, boldc=None, bold=True, align='R')
    head_txt = '**%s**' % f['name_en'] + (('  ·  ' + f['class']) if f.get('class') else '')
    head = RichPara(head_txt, hd)
    rows = [(RichPara(lab, PS(8.6, 12, bold=True, color=H('#334155'), boldc=None)),
             RichPara(f[k], PS(8.9, 13, justify=True, boldc=None))) for k, lab in DRUG_ROWS if f.get(k)]
    if not rows:
        return [KeepTogether([head])]
    t = _ctx_rows_table(rows, W, H('#334155'), head=head)
    t.spaceBefore, t.spaceAfter = 2, 8
    return [KeepTogether([t])]


def build_table(t, W, acc):
    dark, light, mid = [H(x) for x in acc]
    kind = t['kind']
    rows = [r for r in t['rows'] if r]
    if not rows:
        return []
    nc = max(len(r) for r in rows)
    rows = [r + [''] * (nc - len(r)) for r in rows]
    hdr = dark
    paras = []
    for ri, r in enumerate(rows):
        pr = []
        for ci, cell in enumerate(r):
            if ri == 0:
                st = PS(8.8, 12, color=white, bold=True, la=white, num=white, boldc=None, align='C')
            else:
                bold = ci == 0 and kind in ('compare', 'classify', 'ddx')
                st = PS(8.7, 12.4, bold=bold, align='C' if kind == 'values' and ci > 0 else 'auto')
            pr.append(RichPara(cell, st))
        paras.append(pr)
    pad = 11
    cols = list(zip(*paras))
    mins = [max(p.minw() for p in col) + pad + 2 for col in cols]
    prefs = [max(p.natural() for p in col) + pad + 2 for col in cols]
    if sum(prefs) <= W:
        widths = [p * W / sum(prefs) for p in prefs]
    elif sum(mins) >= W:
        widths = [m * W / sum(mins) for m in mins]
    else:
        spare, need = W - sum(mins), [p - m for p, m in zip(prefs, mins)]
        tot = sum(need) or 1
        widths = [m + spare * nd / tot for m, nd in zip(mins, need)]
    lo, hi = 34.0, W * .6                                   # clamps: لا ضيق قوي ولا عمود واحد ياكل الجدول
    widths = [min(max(w, lo), hi) for w in widths]
    k = W / sum(widths)
    widths = [w * k for w in widths]
    data = [list(reversed(r)) for r in paras]               # RTL: العمود 1 على اليمين
    widths = widths[::-1]
    ts = [('BACKGROUND', (0, 0), (-1, 0), hdr), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
          ('TOPPADDING', (0, 0), (-1, -1), 3.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.6),
          ('INNERGRID', (0, 0), (-1, -1), .4, LINE), ('BOX', (0, 0), (-1, -1), .9, hdr)]
    for r in range(1, len(rows)):
        if r % 2 == 0:
            ts.append(('BACKGROUND', (0, r), (-1, r), light))     # zebra بلون المحور الفاتح
    if kind in ('compare', 'classify', 'ddx'):
        ts.append(('BACKGROUND', (nc - 1, 1), (nc - 1, -1), H(acc[2]) if kind == 'ddx' else light))
    if kind == 'ddx':
        ts += [('BOX', (0, 0), (-1, -1), 1.4, dark), ('LINEAFTER', (nc - 2, 0), (nc - 2, -1), .9, dark)]
    tbl = Table(data, colWidths=widths, repeatRows=1)
    tbl.setStyle(TableStyle(ts))
    tbl.spaceAfter = 6
    label = {'compare': 'جدول مقارنة', 'classify': 'جدول تصنيف', 'values': 'جدول قيم',
             'ddx': 'تشخيص تفريقي'}.get(kind, 'جدول')
    tdeco = dict(kind='box', bg=light, bd=hdr, label=label)
    title = RichPara(t['title'] or label, PS(9.4, 13, bold=True, color=dark, boldc=None, sa=2), deco=tdeco)
    approx = 18 + 17 * len(rows)
    if approx < 260:
        return [CondPageBreak(60), KeepTogether([title, tbl])]
    return [CondPageBreak(90), title, tbl]


def list_box(items, title, W, acc, numbered=False, head=None):
    """قايمة مؤطرة. title=None → من غير شريط عنوان (BUL/NUM جوه المتن)."""
    dark, light, mid = [H(x) for x in acc]
    head = head or dark
    rows = []
    if title:
        rows.append([RichPara(title, PS(9.8, 13.6, color=white, bold=True, la=white, num=white, boldc=None))])
    for i, it in enumerate(items):
        deco = dict(kind='num' if numbered else 'bullet', bd=dark, mk='tick', n=i + 1)
        rows.append([RichPara(it, PS(9.2, 13.6, justify=True), deco=deco)])
    tbl = Table(rows, colWidths=[W])
    st = [('BACKGROUND', (0, 1 if title else 0), (0, -1), light),
          ('BOX', (0, 0), (-1, -1), .9, head), ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
          ('TOPPADDING', (0, 0), (-1, -1), 2.2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.2),
          ('LINEAFTER', (-1, 0), (-1, -1), 4, head)]
    if title:
        st += [('BACKGROUND', (0, 0), (0, 0), head), ('TOPPADDING', (0, 0), (0, 0), 5), ('BOTTOMPADDING', (0, 0), (0, 0), 4.5)]
    tbl.setStyle(TableStyle(st))
    tbl.spaceBefore, tbl.spaceAfter = 3, 9
    return tbl


# ════════════════════════════════════════════════════════════════════
#  8) الـ Parser (غلاف فوق markers.py — الـ API القديم شغال)
# ════════════════════════════════════════════════════════════════════
class Notes:
    """نتيجة parse(): .meta/.topics (المكتملة بس)/.hy/.audio/.final/.plan + .result (ParseResult كامل)."""
    def __init__(self, pr):
        self.result = pr
        self.meta = dict(pr.lecture.meta)
        self.topics = pr.topics()
        self.hy = list(pr.tail.hy)
        self.audio = pr.unclear()
        self.final = dict(pr.tail.final)
        self.plan = list(pr.lecture.topics_plan)


def parse(text):
    return Notes(M.parse(text))


def srt_total(path):
    t = open(path, encoding='utf-8-sig').read().replace('\r', '')
    idx = [int(m.group(1)) for m in re.finditer(r'(?m)^\s*(\d+)\s*\n\s*\d\d:\d\d:\d\d[,.]\d{3}\s*-->', t)]
    return max(idx) if idx else 0


def validate(N, total=0, mode='lenient'):
    """قايمة نصوص (أخطاء ثم تحذيرات) — نفس شكل الـ API القديم."""
    errs, warns = M.validate(N.result, total, mode)
    return errs + warns


# ════════════════════════════════════════════════════════════════════
#  9) تجميع الـ story
# ════════════════════════════════════════════════════════════════════
def accent_of(tid):
    return ACCENTS[(tid - 1) % len(ACCENTS)] if tid > 0 else ACCENTS[0]


def axis_accent(ax, topic=None):
    """محور صريح: لون المحور (دوري). محور ضمني (legacy): لون كل موضوع زي ما كان."""
    if ax.implicit:
        return accent_of(topic.id) if topic is not None else ACCENTS[0]
    return ACCENTS[(ax.id - 1) % len(ACCENTS)] if ax.id >= 1 else ACCENTS[0]


class Pages:
    """أرقام الصفحات المجمّعة في المرور الأول (للـ TOC والروابط والمسرد)."""
    def __init__(self):
        self.topic, self.axis, self.wrap, self.case, self.ans, self.sec = {}, {}, {}, {}, {}, {}
        self.defs = {}

    def snapshot(self):
        return (dict(self.topic), dict(self.axis), dict(self.wrap), dict(self.case), dict(self.ans), dict(self.sec),
                {k: list(v) for k, v in self.defs.items()})


def _pg(d, k):
    return d.get(k, '·')


def render_block(b, W, acc, pages, titles, links):
    k, f = b.kind, b.fields
    dark = H(acc[0])
    if k == 'H2':
        return [CondPageBreak(62), RichPara(b.text, PS(11.4, 16, color=dark, bold=True, boldc=None, sb=5, sa=3),
                                            deco=dict(kind='h2', bd=dark, line=H(acc[2])))]
    if k == 'P':
        return [RichPara(b.text, PS(sa=4.5, justify=True))]
    if k in ('BUL', 'NUM'):
        return [list_box(f, None, W, acc, numbered=(k == 'NUM'))]
    if k == 'DEF':
        return [DefCard(f)]
    if k in BLOCKS:
        return [RichPara(b.text, PS(9.5, 14, sa=5.5, justify=True), deco=box_deco(k))]
    if k == 'WHY':
        strip = RichPara(f['question'], PS(9.6, 14, bold=True, color=white, la=white, num=white, boldc=None, sa=0),
                         deco=dict(kind='box', bg=dark, bd=dark, label='ليه؟'))
        return [KeepTogether([strip, Spacer(1, 4), FlowChart(f['chain'], acc)])]
    if k == 'FLOW':
        return [FlowChart(f['steps'], acc)]
    if k == 'MNEMO':
        return [MnemoBox(f['abbreviation'], f['expansion'])]
    if k == 'DRUG':
        return drug_card(f, W)
    if k == 'TABLE':
        return build_table(dict(title=f['title'], kind=f['type'], rows=f['rows']), W, acc)
    if k == 'LINK':
        tid = f.get('topic_id')
        if not f.get('ok'):
            return [RichPara(b.text or ('راجع الموضوع %s' % tid), PS(9, 13, sa=4, color=MUTED, boldc=None))]
        lab = '**راجع الموضوع %s: %s (صفحة %s)**' % (tid, titles.get(tid, ''), _pg(pages.topic, tid))
        txt = lab + ((' — ' + b.text) if b.text else '')
        return [RichPara(txt, PS(9, 13, sa=5, color=INK, boldc=None),
                         deco=dict(kind='link', bd=dark, dest='topic%s' % tid if links else None))]
    return []                                                # UNCLEAR وغيره: مش بيتعرض جوه المتن


def blocks_story(blocks, W, acc, pages, titles, links):
    s = []
    for b in blocks:
        if b.kind == 'UNCLEAR':
            continue
        s.extend(safe(b.kind, lambda b=b: render_block(b, W, acc, pages, titles, links)))
    return s


def topic_story(t, W, acc, pages, titles, links, level, H_quarter):
    td = dict(id=t.id, title=t.title, en=t.en, time=t.extra.get('time', ''), srt=t.src)
    s = [CondPageBreak(H_quarter), TopicBanner(td, acc, level), Spacer(1, 6)]
    s.extend(blocks_story(t.blocks, W, acc, pages, titles, links))
    if t.summary:
        s += [CondPageBreak(78), list_box(t.summary, 'ملخص الموضوع  ·  Topic summary', W, acc)]
    else:
        s.append(Spacer(1, 6))
    return s


def axis_story(ax, W, acc, first):
    s = [] if first else [PageBreak()]
    s.append(AxisBanner(ax.id, ax.title, ax.en, acc, sum(1 for u in ax.units if u.kind == 'topic')))
    s.append(Spacer(1, 8))
    dark, light, mid = [H(x) for x in acc]
    if ax.intro:
        s.append(RichPara(ax.intro, PS(10, 15, justify=True, sa=6),
                          deco=dict(kind='box', bg=light, bd=dark, label='عن المحور')))
    for q, a in ax.warmups:
        parts = [RichPara(q, PS(9.4, 13.6, sa=0), deco=dict(kind='box', bg=H('#FFFFFF'), bd=dark, label='سؤال تسخين'))]
        if a:
            parts += [Spacer(1, 2), RichPara(a, PS(8.8, 12.8, color=MUTED, la=MUTED, num=MUTED, boldc=None, sa=5),
                                              deco=dict(kind='box', bg=H('#F6F7F9'), bd=H(acc[2]), label='الإجابة', lw=.4))]
        s.append(KeepTogether(parts))
    s.append(Spacer(1, 8))
    return s


def wrap_story(w, ax, W, acc, pages, titles, links):
    dark, light, mid = [H(x) for x in acc]
    s = [CondPageBreak(170), UnitBanner('ملخص المحور %s' % ax.id if not ax.implicit else 'الملخص', ax.title if not ax.implicit else '',
                                        acc, 'wrap%s' % w.axis, 'ملخص المحور %s' % w.axis, 1, 'is_wrap', w.axis, 'WRAP'),
         Spacer(1, 6)]
    for t in w.summary:
        s.append(RichPara(t, PS(9.6, 14.2, justify=True, sa=4.5), deco=dict(kind='box', bg=light, bd=dark, label='ملخص المحور')))
    if w.bigpic:
        s.append(RichPara(w.bigpic, PS(10.3, 15.5, justify=True, sa=6, boldc=None),
                          deco=dict(kind='box', bg=H('#FFFFFF'), bd=dark, label='الصورة الكبيرة', lw=1.3, bar=6)))
    s.extend(blocks_story(w.blocks, W, acc, pages, titles, links))
    if w.hy:
        s.append(list_box(w.hy, 'High-Yield  ·  أهم النقاط', W, acc, numbered=True))
    return s


def case_story(c, ax, W, acc, pages, ans_at_end, links):
    dark, light, mid = [H(x) for x in acc]
    label = '%s.%s' % (c.axis, c.id)
    sub = c.tests and ('يختبر: ' + c.tests)
    s = [CondPageBreak(150), UnitBanner('حالة %s' % label + (' · ' + LEVELS_AR.get(c.level, c.level) if c.level else ''),
                                        sub or '', acc, 'case%s' % label, 'حالة %s' % label, 1, 'is_case', label,
                                        'CASE')]
    s.append(Spacer(1, 5))
    if c.stem:
        s.append(RichPara(c.stem, PS(9.6, 14.2, justify=True, sa=5), deco=dict(kind='box', bg=light, bd=dark, label='الحالة')))
    ans_bd, ans_bg = H('#334155'), H('#F8FAFC')
    for i, (q, a) in enumerate(c.qa, 1):
        qp = RichPara(q, PS(9.5, 14, bold=False, sa=2, justify=True), deco=dict(kind='num', bd=dark, n=i)) if q else None
        parts = [qp] if qp else []
        if ans_at_end:
            if a:
                parts.append(RichPara('الإجابة في صفحة %s' % _pg(pages.ans, c.axis),
                                      PS(8.2, 11.5, color=MUTED, la=MUTED, num=MUTED, boldc=None, sa=4),
                                      deco=dict(kind='link', bd=H(acc[2]), dest=('ans%s' % c.axis) if links else None)))
        elif a:
            parts.append(RichPara(a, PS(9.2, 13.6, justify=True, sa=5),
                                  deco=dict(kind='box', bg=ans_bg, bd=ans_bd, label='الإجابة', lw=.4)))
        if parts:
            s.append(KeepTogether(parts))
    if c.pearl:
        s.append(RichPara(c.pearl, PS(9.5, 14, sa=5.5, justify=True), deco=box_deco('PEARL')))
    s.extend(blocks_story(c.blocks, W, acc, pages, {}, links))
    s.append(Spacer(1, 6))
    return s


def answers_story(ax, cases, W, acc, pages, links):
    dark, light, mid = [H(x) for x in acc]
    s = [PageBreak(), UnitBanner('إجابات حالات المحور %s' % ax.id, ax.title, acc, 'ans%s' % ax.id,
                                 'إجابات المحور %s' % ax.id, 1, 'is_ans', ax.id, 'ANSWERS'), Spacer(1, 6)]
    for c in cases:
        label = '%s.%s' % (c.axis, c.id)
        s.append(RichPara('**حالة %s** — راجع الحالة (صفحة %s)' % (label, _pg(pages.case, label)),
                          PS(9.4, 13.4, sa=3, color=dark, la=dark, num=dark, boldc=None),
                          deco=dict(kind='link', bd=dark, dest=('case%s' % label) if links else None)))
        for i, (q, a) in enumerate(c.qa, 1):
            if q:
                s.append(RichPara(q, PS(9.2, 13.4, sa=1.5, justify=True), deco=dict(kind='num', bd=dark, n=i)))
            if a:
                s.append(RichPara(a, PS(9.2, 13.6, justify=True, sa=5),
                                  deco=dict(kind='box', bg=H('#F8FAFC'), bd=H('#334155'), label='الإجابة', lw=.4)))
    return s


def glossary_story(pr, W, pages):
    defs = {}
    for u in pr.complete_units():
        for b in getattr(u, 'blocks', []):
            if b.kind == 'DEF':
                key = b.fields['term_en'].casefold()
                defs.setdefault(key, b.fields)
    if not defs:
        return []
    acc = ACCENTS[0]
    dark, light, mid = [H(x) for x in acc]
    hdr = PS(8.8, 12, color=white, bold=True, la=white, num=white, boldc=None, align='C')
    rows = [[RichPara('صفحة', hdr), RichPara('التعريف', hdr), RichPara('المصطلح', hdr)]]
    for key in sorted(defs):
        f = defs[key]
        pgs = sorted(set(pages.defs.get(f['term_en'], [])))
        term = [RichPara('**%s**' % f['term_en'], PS(8.8, 12, align='L', boldc=None))]
        if f.get('term_ar'):
            term.append(RichPara(f['term_ar'], PS(8.8, 12, boldc=None)))
        rows.append([RichPara('، '.join(str(p) for p in pgs) or '·', PS(8.4, 12, align='C', boldc=None)),
                     RichPara(f['definition'], PS(8.5, 12.4, justify=True, boldc=None)), term])
    tbl = Table(rows, colWidths=[44, W - 44 - 120, 120], repeatRows=1)
    ts = [('BACKGROUND', (0, 0), (-1, 0), dark), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('INNERGRID', (0, 0), (-1, -1), .4, LINE), ('BOX', (0, 0), (-1, -1), .9, dark),
          ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
    for r in range(2, len(rows), 2):
        ts.append(('BACKGROUND', (0, r), (-1, r), light))
    tbl.setStyle(TableStyle(ts))
    title = RichPara('المسرد  ·  Glossary', PS(12, 17, bold=True, color=dark, boldc=None, sb=2, sa=5),
                     deco=dict(kind='h2', bd=dark, line=mid))
    return [PageBreak(), SectionMark('glossary', 'المسرد · Glossary', 0), title, tbl]


def unclear_story(items, W):
    if not items:
        return []
    grey, light = H(GREY[0]), H(GREY[1])
    hdr = PS(8.8, 12, color=white, bold=True, la=white, num=white, boldc=None, align='C')
    rows = [[RichPara('مرجع السطر', hdr), RichPara('الجملة / المشكلة (محتاجة مراجعة من المصدر)', hdr)]]
    for ref, txt in items:
        rows.append([RichPara(ref or '·', PS(8.4, 12, align='C', boldc=None)), RichPara(txt, PS(8.4, 12, boldc=None))])
    tbl = Table([[r[1], r[0]] for r in rows], colWidths=[W - 62, 62], repeatRows=1)
    ts = [('BACKGROUND', (0, 0), (-1, 0), grey), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('INNERGRID', (0, 0), (-1, -1), .4, LINE), ('BOX', (0, 0), (-1, -1), .8, grey),
          ('TOPPADDING', (0, 0), (-1, -1), 2.6), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.6)]
    for r in range(2, len(rows), 2):
        ts.append(('BACKGROUND', (0, r), (-1, r), light))
    tbl.setStyle(TableStyle(ts))
    title = RichPara('نقاط متراجعة من المصدر  ·  Unclear', PS(10.4, 14.5, bold=True, color=grey, boldc=None, sb=4, sa=3),
                     deco=dict(kind='h2', bd=grey, line=LINE))
    return [CondPageBreak(110), SectionMark('unclear', 'نقاط متراجعة', 0, reset=False), title, tbl]


def extras_story(pr, W):
    items = []
    for u in pr.complete_units():
        for b in getattr(u, 'blocks', []):
            if b.kind == 'EXTRA' and b.text:
                items.append(b.text)
    if not items:
        return []
    return [CondPageBreak(110), SectionMark('extra', 'من خارج المحاضرة', 0, reset=False),
            list_box(items, 'اللي الموديل ضافه من برّه  ·  Added by the model', W, GREY, head=H(GREY[0]))]


def toc_story(pr, W, pages, links, tail_sections):
    s = []
    for ax in pr.axes:
        acc = axis_accent(ax)
        entries = []
        for u in ax.units:
            a2 = axis_accent(ax, u if u.kind == 'topic' else None)
            if u.kind == 'topic':
                entries.append((u.id, u.title, _pg(pages.topic, u.id), a2, 'topic%s' % u.id))
            elif u.kind == 'wrap':
                entries.append((None, 'ملخص المحور', _pg(pages.wrap, u.axis), a2, 'wrap%s' % u.axis))
            else:
                lab = '%s.%s' % (u.axis, u.id)
                entries.append((None, 'حالة %s' % lab, _pg(pages.case, lab), a2, 'case%s' % lab))
        if not entries:
            continue
        head = ('المحور %s  ·  %s' % (ax.id, ax.title)) if not ax.implicit else None
        s += [TocBlock(entries, acc, links, head), Spacer(1, 7)]
    ents = [(None, t, _pg(pages.sec, n), ACCENTS[0], 'sec_' + n) for n, t in tail_sections]
    if ents:
        s += [TocBlock(ents, ACCENTS[0], links, 'ملحقات  ·  Appendices'), Spacer(1, 7)]
    return s


def full_story(pr, W, pages, links, answers_at_end=False, H_quarter=190):
    s = []
    meta = pr.lecture.meta
    first_acc = axis_accent(pr.axes[0]) if pr.axes else ACCENTS[0]
    s.append(TitleBlock(meta, first_acc))
    s.append(Spacer(1, 7))
    if pr.lecture.about:
        s.append(RichPara(pr.lecture.about, PS(10, 15, justify=True, sa=6),
                          deco=dict(kind='box', bg=H(first_acc[1]), bd=H(first_acc[0]), label='عن المحاضرة')))
    explicit = [a for a in pr.axes if not a.implicit]
    if explicit:
        s.append(AxesMap([(a.id, a.title, sum(1 for u in a.units if u.kind == 'topic'), axis_accent(a)) for a in explicit]))
        s.append(Spacer(1, 8))
    tails = []
    glossary = glossary_story(pr, W, pages) if True else []
    hy = pr.tail.hy
    if hy:
        tails.append(('hy', 'أهم النقاط للمراجعة'))
    if pr.tail.bigpicture:
        tails.append(('bigpicture', 'الصورة الكبيرة'))
    if glossary:
        tails.append(('glossary', 'المسرد'))
    if pr.unclear():
        tails.append(('unclear', 'نقاط متراجعة'))
    s.extend(toc_story(pr, W, pages, links, tails))
    titles = {t.id: t.title for t in pr.topics()}
    for n, ax in enumerate(pr.axes):
        acc = axis_accent(ax)
        if not ax.implicit:
            s.extend(axis_story(ax, W, acc, first=False))
        cases = [u for u in ax.units if u.kind == 'case']
        for u in ax.units:
            a2 = axis_accent(ax, u if u.kind == 'topic' else None)
            if u.kind == 'topic':
                s.extend(safe('topic %d' % u.id, lambda u=u, a2=a2: topic_story(
                    u, W, a2, pages, titles, links, 0 if ax.implicit else 1, H_quarter)))
            elif u.kind == 'wrap':
                s.extend(safe(u.key, lambda u=u, a2=a2: wrap_story(u, ax, W, a2, pages, titles, links)))
            else:
                s.extend(safe(u.key, lambda u=u, a2=a2: case_story(u, ax, W, a2, pages, answers_at_end, links)))
        if answers_at_end and cases and any(a for c in cases for _, a in c.qa):
            s.extend(safe('answers %d' % ax.id, lambda: answers_story(ax, cases, W, acc, pages, links)))
    if hy:
        s += [PageBreak(), SectionMark('hy', 'أهم النقاط للمراجعة', 0),
              list_box(hy, 'High-Yield Review  ·  أهم النقاط للمراجعة السريعة', W, GOLD, numbered=True, head=H(GOLD[0]))]
    if pr.tail.bigpicture:
        s += [CondPageBreak(140), SectionMark('bigpicture', 'الصورة الكبيرة', 0, reset=not hy),
              RichPara(pr.tail.bigpicture, PS(10.8, 16.4, justify=True, sa=6, boldc=None),
                       deco=dict(kind='box', bg=H(first_acc[1]), bd=H(first_acc[0]), label='الصورة الكبيرة', lw=1.3, bar=6))]
    s.extend(glossary)
    s.extend(unclear_story(pr.unclear(), W))
    s.extend(extras_story(pr, W))
    return s


# ════════════════════════════════════════════════════════════════════
#  10) الصفحة: header / footer / "page n / total"
# ════════════════════════════════════════════════════════════════════
class Ctx:
    def __init__(self, meta):
        self.meta, self.pages = meta, Pages()
        self.page_info, self.cur_axis, self.cur_topic = {}, None, None


class NotesDoc(BaseDocTemplate):
    def __init__(self, path, ctx, **kw):
        BaseDocTemplate.__init__(self, path, **kw)
        self.ctx = ctx

    def afterFlowable(self, f):
        x, pg = self.ctx, self.ctx.pages
        if getattr(f, 'is_axis', False):
            pg.axis[f.aid] = self.page
            x.cur_axis, x.cur_topic = (f.aid, f.title, f.accent), None
        elif getattr(f, 'is_banner', False):
            pg.topic[f.tid] = self.page
            x.cur_topic = (f.tid, f.title, f.accent)
        elif getattr(f, 'is_wrap', False):
            pg.wrap[f.ident] = self.page
            x.cur_topic = None
        elif getattr(f, 'is_case', False):
            pg.case[f.ident] = self.page
            x.cur_topic = None
        elif getattr(f, 'is_ans', False):
            pg.ans[f.ident] = self.page
        elif getattr(f, 'is_def', False):
            pg.defs.setdefault(f.term, []).append(self.page)
        elif getattr(f, 'is_section', False):
            pg.sec[f.name] = self.page
            if f.reset:
                x.cur_axis = x.cur_topic = None
        if getattr(f, 'is_axis', False) or (getattr(f, 'is_section', False) and f.reset):
            x.page_info[self.page] = (x.cur_axis, x.cur_topic)       # بداية محور/قسم: بتغلب أي تسجيل سابق للصفحة
        else:
            x.page_info.setdefault(self.page, (x.cur_axis, x.cur_topic))


def make_canvas_class(ctx):
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            rl_canvas.Canvas.__init__(self, *a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                chrome(self, self._pageNumber, total, ctx)
                rl_canvas.Canvas.showPage(self)
            rl_canvas.Canvas.save(self)
    return NumberedCanvas


def chrome(c, pn, total, ctx):
    PW, PH = A4
    ML = 14 * mm
    m = ctx.meta
    axis, topic = ctx.page_info.get(pn, (None, None))
    acc = topic[2] if topic else (axis[2] if axis else ACCENTS[0])
    dark, mid = H(acc[0]), H(acc[2])
    c.saveState()
    c.setFillColor(dark); c.rect(0, PH - 3.4 * mm, PW, 3.4 * mm, stroke=0, fill=1)
    c.setFillColor(mid); c.rect(0, PH - 3.4 * mm, PW * .18, 1 * mm, stroke=0, fill=1)
    small = PS(8, color=MUTED, boldc=None, la=MUTED, num=MUTED)
    if pn > 1:
        yh = PH - 9.6 * mm
        left = PS(8.4, color=dark, bold=True, boldc=None, la=dark, num=dark)
        if topic:
            c.setFillColor(dark); c.circle(ML + 3, yh + 2.6, 2.6, stroke=0, fill=1)
            draw_text(c, topic[1], ML + 10, yh, left, 'L', maxw=PW * .5)
        sub = '  ·  '.join(x for x in (m.get('doctor', ''), m.get('course', '')) if x)
        if sub:
            draw_text(c, sub, PW - ML, yh, small, 'R', maxw=PW * .42)
        c.setStrokeColor(dark); c.setLineWidth(.7); c.line(ML, yh - 5, PW - ML, yh - 5)
    yf = 8.6 * mm
    c.setStrokeColor(dark); c.setLineWidth(.7); c.line(ML, yf + 12, PW - ML, yf + 12)
    c.setStrokeColor(mid); c.setLineWidth(.7); c.line(ML, yf + 10.5, PW - ML, yf + 10.5)
    pill = 'page %d / %d' % (pn, total)
    pst = PS(8.4, color=white, bold=True, boldc=None, la=white, num=white)
    pw = text_width(pill, pst) + 20
    c.setFillColor(dark); c.roundRect(PW / 2 - pw / 2, yf - 3.4, pw, 14.6, 7, stroke=0, fill=1)
    draw_text(c, pill, PW / 2, yf + .8, pst, 'C')
    right_txt = m.get('title', '')
    if m.get('number'):
        right_txt = 'Lecture %s  ·  %s' % (m['number'], right_txt)
    draw_text(c, right_txt, PW - ML, yf + .8, small, 'R', maxw=PW * .30)
    if axis:                                                   # اسم المحور الحالي بلونه
        adark = H(axis[2][0])
        c.setFillColor(adark); c.circle(ML + 3, yf + 3.4, 2.6, stroke=0, fill=1)
        draw_text(c, axis[1], ML + 10, yf + .8, PS(8.4, color=adark, bold=True, boldc=None, la=adark, num=adark),
                  'L', maxw=PW * .30)
    c.restoreState()


def _symbols_warning(emoji, dropped):
    parts = []
    if emoji:
        parts.append('إيموجي/رموز: %d' % emoji)
    if dropped:
        parts.append('حروف مش في الخط: %s' % ' '.join('U+%04X' % ord(ch) for ch in sorted(dropped)[:8]))
    return ('%s — %s (اتشالت من الـ PDF)' % (M.W_EMOJI, '، '.join(parts))) if parts else None


def build_pdf(text, out, srt=None, fonts=None, total=0, validate_mode='lenient', answers_at_end=False):
    """بيرمي SystemExit برسالة عربي لو مفيش حاجة تتعرض. كل التنبيهات بتتطبع سطر بيبدأ بـ ⚠ (R-07)."""
    del BUILD_WARNS[:]
    DROPPED.clear()
    setup_fonts(fonts)
    N = parse(text)
    pr = N.result
    total = total or (srt_total(srt) if srt else 0)
    errs, warns = M.validate(pr, total, validate_mode)
    if errs:
        sys.exit('✗ ' + ' | '.join(errs))
    seen = set()
    for w in pr.warnings + warns:
        if w.startswith(M.W_EMOJI) or w.startswith(M.W_BOLD) or w in seen:
            continue
        seen.add(w)
        print('⚠', w)
    ML, MR, MT, MB = 16 * mm, 16 * mm, 17 * mm, 17.5 * mm
    PW, PH = A4
    W = PW - ML - MR
    meta = pr.lecture.meta

    def run(path, pages, links):
        DROPPED.clear()
        del BUILD_WARNS[:]
        ctx = Ctx(meta)
        doc = NotesDoc(path, ctx, pagesize=A4, leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB,
                       title='%s - Lecture %s' % (meta.get('title', ''), meta.get('number', '')),
                       author=meta.get('doctor', '') or 'Study notes')
        doc.addPageTemplates([PageTemplate(id='main', frames=[Frame(ML, MB, W, PH - MT - MB, 0, 0, 0, 0, id='f')])])
        doc.build(full_story(pr, W, pages, links, answers_at_end, .25 * (PH - MT - MB)),
                  canvasmaker=make_canvas_class(ctx))
        return ctx

    tmp = out + '.pass1.pdf'
    ctx = run(tmp, Pages(), False)
    for _ in range(3):                                         # لحد ما أرقام الصفحات تثبت
        prev = ctx.pages.snapshot()
        ctx = run(out, ctx.pages, True)
        if ctx.pages.snapshot() == prev:
            break
    try:
        os.remove(tmp)
    except OSError:
        pass
    sym = _symbols_warning(pr.stats.get('emoji', 0), DROPPED)
    if sym:
        print('⚠', sym)
    if pr.stats.get('bold'):
        print('⚠ %s في %d نص — اتعرضت كما هي' % (M.W_BOLD, pr.stats['bold']))
    for w in dict.fromkeys(BUILD_WARNS):
        print('⚠', w)
    npages = max(ctx.page_info) if ctx.page_info else 0
    print('✓ %s  |  %d محور  |  %d مواضيع  |  %d صفحة  |  %d نقطة للمراجعة' % (
        out, len([a for a in pr.axes if not a.implicit]), len(pr.topics()), npages, len(pr.unclear())))


def main():
    ap = argparse.ArgumentParser(description='@@markers → PDF')
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--out', default='lecture_notes.pdf')
    ap.add_argument('--srt', help='ملف الـ SRT الأصلي للتحقق من التغطية (اختياري)')
    ap.add_argument('--total', type=int, default=0, help='عدد أسطر المصدر (لوضع lecture)')
    ap.add_argument('--fonts', help='فولدر فيه خطوط TTF (اختياري)')
    ap.add_argument('--strict', action='store_true', help='VALIDATE_MODE=strict')
    ap.add_argument('--answers-at-end', action='store_true')
    a = ap.parse_args()
    text = '\n'.join(open(p, encoding='utf-8-sig').read() for p in a.inputs)
    build_pdf(text, a.out, a.srt, a.fonts, total=a.total, validate_mode='strict' if a.strict else 'lenient',
              answers_at_end=a.answers_at_end)


if __name__ == '__main__':
    main()

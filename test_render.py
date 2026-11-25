# -*- coding: utf-8 -*-
import io, os, re, sys, contextlib
import pytest
import markers as M
import lecture_to_pdf as L
import notes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(os.path.dirname(__file__), 'fixtures')
FULL = open(os.path.join(FIX, 'sample_full.txt'), encoding='utf-8').read()
LEGACY = open(os.path.join(FIX, 'legacy_srt.txt'), encoding='utf-8').read()
FONTS = os.path.join(HERE, 'fonts')


def build(text, tmp_path, **kw):
    out = str(tmp_path / 'o.pdf')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            L.build_pdf(text, out, None, FONTS, **kw)
        except SystemExit as e:
            if 'مفيش خط عربي' in str(e):
                pytest.skip('مفيش خط عربي في fonts/')
            raise
    lines = [l for l in buf.getvalue().split('\n') if l]
    return out, lines


def pdf_info(path):
    b = open(path, 'rb').read()
    return dict(pages=len(re.findall(rb'/Type\s*/Page\b', b)), outlines=b'/Outlines' in b, size=len(b), raw=b)


def test_legacy_srt_document_still_builds_pdf(tmp_path):
    N = L.parse(LEGACY)
    assert N.meta['title'] == 'Heart Failure' and len(N.topics) == 2 and N.result.legacy
    out, lines = build(LEGACY, tmp_path)
    info = pdf_info(out)
    assert info['pages'] >= 2 and info['outlines']
    assert not any('خط' in l and l.startswith('⚠') for l in lines)
    assert any(l.startswith('✓') and '2 مواضيع' in l for l in lines)
    # API القديم لـ notes.build_pdf_sync بيرجّع نفس الشكل
    warns, meta, n_topics, o = notes.build_pdf_sync(HERE, LEGACY, str(tmp_path / 'b.pdf'), None, FONTS)
    assert n_topics == 2 and meta['title'] == 'Heart Failure' and os.path.exists(str(tmp_path / 'b.pdf'))
    assert not [w for w in warns if 'حقل ناقص' in w]


def test_arrow_direction_normalized_for_flow_and_why():
    L.setup_fonts(FONTS)
    st = L.PS()
    ch, rtl = L.make_chunks('الغلط → الصح ⟶ تاني', st)
    glyphs = ''.join(c.t for c in ch if c.kind == 'N')
    assert rtl and '←' in glyphs and '→' not in glyphs and '⟶' not in glyphs
    ch, rtl = L.make_chunks('Cause ← effect', st)
    assert not rtl and '→' in ''.join(c.t for c in ch) and '←' not in ''.join(c.t for c in ch)
    fc = L.FlowChart(['أ', 'ب', 'ج', 'د'], L.ACCENTS[0])
    fc.wrap(480, 800)
    geo, arrows = fc.layout()
    xs = [geo[i][0] for i in range(4) if geo[i][1] == geo[0][1]]
    assert xs == sorted(xs, reverse=True) and len(xs) >= 2          # الخطوة 1 على اليمين
    kind, (x1, y1, x2, y2) = arrows[0]
    assert kind == 'h' and x2 < x1 and y1 == y2                      # السهم ناحية الشمال
    narrow = L.FlowChart(['خطوة واحدة طويلة شوية', 'خطوة تانية طويلة', 'تالتة طويلة', 'رابعة طويلة', 'خامسة'], L.ACCENTS[1])
    narrow.wrap(300, 800)
    geo, arrows = narrow.layout()
    assert any(a[0] == 'v' for a in arrows)                          # الصف الجديد بينزل ومش بيرجع لورا
    why = M.parse('@@TOPIC_START | id=1 | title=T\n@@WHY | ليه؟ | أ ← ب → ج\n@@TOPIC_END | id=1 | DONE\n').topics()[0].blocks[0]
    kt = L.render_block(why, 480, L.ACCENTS[0], L.Pages(), {}, False)[0]
    fcs = [f for f in kt._content if isinstance(f, L.FlowChart)]
    assert fcs and fcs[0].steps == ['أ', 'ب', 'ج']


def test_emoji_and_uncovered_glyphs_removed_with_single_warning(tmp_path):
    t = ('@@TOPIC_START | id=1 | title=T\n@@P | نص 🚨 فيه إيموجي ⚠️ و 中 حرف صيني و 文 كمان\n'
         '@@KEY | 🔥 نقطة\n@@TOPIC_END | id=1 | DONE\n')
    out, lines = build(t, tmp_path)
    sym = [l for l in lines if l.startswith('⚠') and M.W_EMOJI in l]
    assert len(sym) == 1 and 'U+4E2D' in sym[0] and 'إيموجي' in sym[0]
    assert pdf_info(out)['pages'] >= 1
    # الإيموجي اتشال من الموديل نفسه كمان
    assert '🚨' not in M.parse(t).topics()[0].blocks[0].text


def test_inline_badges_and_unbalanced_bold():
    L.setup_fonts(FONTS)
    ch, _ = L.make_chunks('جرعة [راجع المرجع] و[إضافة] و[؟] و **bold** عادي', L.PS())
    assert [c.special for c in ch if c.kind == 'B'] == ['[راجع المرجع]', '[إضافة]', '[؟]']
    assert all(c.w > 10 for c in ch if c.kind == 'B')
    ch, _ = L.make_chunks('نص **من غير قفل', L.PS())
    assert any('**' in c.t for c in ch) and not any(c.bold for c in ch)


MIXED = ['الـ proteinuria أكتر من 3.5 g/day عند الكبار', 'الـ ACE inhibitors (ACEi) بتقلّل الـ albumin/creatinine',
         'non-ST elevation myocardial infarction نادر', 'الـ albumin ← oncotic pressure → edema', 'Na/K pump و β-blocker و pH 7.4',
         'السعر 12.5 mg/kg/day ثلاث مرات']


def test_mixed_arabic_english_regressions():
    L.setup_fonts(FONTS)
    L.DROPPED.clear()
    for s in MIXED:
        p = L.RichPara(s, L.PS())
        p.wrap(300, 999)
        assert p.height > 0
    assert not L.DROPPED
    # الجزء اللاتيني بيفضل متتالي ومقروء بصرياً (LTR run سليم) جوه السطر العربي
    ch, rtl = L.make_chunks(MIXED[0], L.PS())
    line = L.reorder(ch, rtl)
    vis = ''.join(c.vis for c in line)
    assert '3.5' in vis and 'g/day' in vis and 'proteinuria' in vis
    assert vis.index('3.5') < vis.index('g/day')


def test_build_pdf_smoke(tmp_path):
    out, lines = build(FULL, tmp_path, total=60)
    info = pdf_info(out)
    assert info['pages'] > 3 and info['outlines']
    assert not any(l.startswith('⚠') and 'الخط' in l for l in lines)
    assert all(l.startswith(('⚠', '✓', 'الخطوط')) for l in lines)       # كل سطر تنبيه بيبدأ بـ ⚠ (R-07)
    assert sum(1 for l in lines if l.startswith('⚠') and M.W_EMOJI in l) == 1
    # استقرار: نفس الإدخال ← نفس عدد الصفحات
    out2, _ = build(FULL, tmp_path, total=60)
    assert pdf_info(out2)['pages'] == info['pages']


def test_answers_at_end_and_strict_mode(tmp_path):
    out, lines = build(FULL, tmp_path, total=60, answers_at_end=True)
    assert pdf_info(out)['pages'] >= 9
    broken = FULL.replace(M.unit_texts(FULL)['topic:5'], '')
    with pytest.raises(SystemExit):
        build(broken, tmp_path, total=60, validate_mode='strict')
    out, lines = build(broken, tmp_path, total=60)                 # lenient: بيبني اللي مكتمل ويحذّر
    assert any('ناقصة' in l for l in lines) and pdf_info(out)['pages'] > 3


def test_nothing_renderable_exits_with_arabic_message(tmp_path):
    with pytest.raises(SystemExit) as e:
        build('@@TOPIC_START | id=1 | title=T\n@@P | x\n', tmp_path)
    assert 'مفيش أي وحدة مكتملة' in str(e.value)


def test_block_failure_becomes_placeholder(tmp_path, monkeypatch):
    real = L.drug_card
    monkeypatch.setattr(L, 'drug_card', lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
    out, lines = build(FULL, tmp_path, total=60)
    assert pdf_info(out)['pages'] > 3 and any('DRUG' in l and l.startswith('⚠') for l in lines)


def test_semantic_colour_contrast():
    def lum(h):
        h = h.lstrip('#'); r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
        return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)

    def cr(a, b):
        x, y = sorted((lum(a), lum(b)), reverse=True)
        return (x + .05) / (y + .05)
    for k, (label, bd, bg, ex) in L.BLOCKS.items():
        assert cr('#FFFFFF', bd) >= 4.5, k
        assert cr('#1F2937', bg) >= 4.5, k
    for acc in L.ACCENTS:
        assert cr('#FFFFFF', acc[0]) >= 4.5
    for _, bg, fg in L.BADGES.values():
        assert cr(bg, fg) >= 4.5
    assert L.ACCENTS[0][0] == '#1E3A5F' and L.ACCENTS[1][0] == '#0F766E' and len(L.ACCENTS) == 8


def test_percent_and_sign_stay_attached_to_number():
    L.setup_fonts(FONTS)
    for s, want in (('الـ EF أقل من 40% عادة', '40%'), ('فيه 4+ protein كتير', '4+ protein'), ('درجة 37° ثابتة', '37°'),
                    ('الجرعة 20-80 mg يومياً', '20-80 mg')):
        ch, rtl = L.make_chunks(s, L.PS())
        vis = ''.join(c.vis for c in L.reorder(ch, rtl))
        assert want in vis, (s, vis)

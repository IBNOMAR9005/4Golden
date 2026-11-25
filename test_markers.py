# -*- coding: utf-8 -*-
import os
import markers as M

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')


def full():
    return open(os.path.join(FIX, 'sample_full.txt'), encoding='utf-8').read()


def test_parse_full_fixture_no_warnings_except_expected():
    r = M.parse(full())
    allowed = ('حقول زيادة', 'أعمدته مش متساوية', 'LINK لموضوع مش موجود', M.W_EMOJI)
    bad = [w for w in r.warnings if not any(a in w for a in allowed)]
    assert bad == []
    assert r.ledger.finished and r.ledger.partial is None
    assert len(r.topics()) == 6 and [a.id for a in r.axes] == [1, 2]
    errs, warns = M.validate(r, 60)
    assert errs == []
    assert all('للعلم' in w for w in warns)          # المعلوماتي بس (3 مواضيع لكل محور)
    # كل الـ markers المعروفة في الجدول ظاهرة في الـ fixture
    import re
    used = set(re.findall(r'^@@([A-Z0-9_]+)', full(), re.M))
    missing = set(M.SPECS) - used - {'AUDIO'}
    assert missing == set(), missing


def test_pipe_surplus_absorbed_last_field():
    r = M.parse('@@TOPIC_START | id=1 | title=T\n@@P | a | b | c\n@@TOPIC_END | id=1 | DONE\n')
    b = r.topics()[0].blocks[0]
    assert b.text == 'a / b / c'
    assert any('حقول زيادة' in w for w in r.warnings)
    r = M.parse('@@TOPIC_START | id=1 | title=A | B\n@@P | x\n@@TOPIC_END | id=1 | DONE\n')
    assert r.topics()[0].title == 'A / B'


def test_crlf_bom_codefence_normalization():
    t = '\ufeff```text\r\n@@TOPIC_START | id=1 | title=T   \r\n@@P | ك\u200bلمة   \r\n@@TOPIC_END | id=1 | DONE\r\n```\r\n'
    r = M.parse(t)
    assert r.warnings == []
    assert r.topics()[0].blocks[0].text == 'كلمة'
    assert '\r' not in M.normalize(t) and '```' not in M.normalize(t)
    # ZWNJ جوه كلمة عربي بيفضل
    assert M.normalize('بـ\u200cـب') == M.normalize('بـ\u200cـب')
    assert '\u200c' in M.normalize('من\u200cها') and '\u200c' not in M.normalize('a\u200cb')


def test_unknown_marker_does_not_crash():
    r = M.parse('@@FOO | x\n@@TOPIC_START | id=1 | title=T\n@@WEIRD | نص | تاني\n@@TOPIC_END | id=1 | DONE\n@@BAR\n')
    assert r.topics()[0].blocks[0].kind == 'P' and 'نص' in r.topics()[0].blocks[0].text
    assert sum('مش معروف' in w for w in r.warnings) == 3
    assert M.parse('').axes == [] and M.parse('@@@@ ||| \x00 junk').units == []


def test_ragged_table_padded():
    t = ('@@TOPIC_START | id=1 | title=T\n@@TABLE_START | x | type=compare\n@@TR | a | b | c\n@@TR | 1 | 2\n'
         '@@TR | 3 | 4 | 5 | 6\n@@P | بعد الجدول من غير TABLE_END\n@@TOPIC_END | id=1 | DONE\n')
    r = M.parse(t)
    blocks = r.topics()[0].blocks
    assert blocks[0].kind == 'TABLE' and blocks[1].kind == 'P'      # اتقفل عند أول marker مش TR (R-31)
    assert blocks[0].fields['rows'] == [['a', 'b', 'c'], ['1', '2', ''], ['3', '4', '5']]
    assert any('مش متساوية' in w for w in r.warnings)
    # عمود واحد → قايمة
    r = M.parse('@@TOPIC_START | id=1 | title=T\n@@TABLE_START | x\n@@TR | a\n@@TR | b\n@@TABLE_END\n@@TOPIC_END | id=1 | DONE\n')
    assert r.topics()[0].blocks[0].kind == 'BUL'


def test_incomplete_unit_never_rendered():
    t = ('@@TOPIC_START | id=1 | title=A\n@@P | x\n@@TOPIC_END | id=1 | DONE\n'
         '@@TOPIC_START | id=2 | title=B\n@@P | y\n'
         '@@TOPIC_START | id=3 | title=C\n@@P | z\n@@TOPIC_END | id=3\n'          # من غير DONE
         '@@TOPIC_START | id=4 | title=D\n@@P | w\n')
    r = M.parse(t)
    assert [u.key for u in r.complete_units()] == ['topic:1']
    assert r.ledger.partial == 'topic:4'
    assert set(r.ledger.incomplete) == {'topic:2', 'topic:3', 'topic:4'}


def test_truncation_property():
    text = full()
    lines = text.split('\n')
    cuts = ['\n'.join(lines[:i]) for i in range(len(lines) + 1)]
    for i in range(1, len(text), 37):
        cuts.append(text[:i])                                   # قص في نص السطر
    for c in cuts:
        r = M.parse(c)                                          # ما يرميش
        L = r.ledger
        assert set(L.done) <= {u.key for u in r.units}
        assert L.next_unit not in L.done
        assert L.finished == (L.plan_present and L.next_unit is None)
        assert len(set(L.done)) == len(L.done)
        t = M.trim_to_complete(c)
        r2 = M.parse(t)
        assert r2.ledger.partial is None
        assert set(r2.ledger.done) == set(L.done)


def test_duplicate_unit_last_complete_wins_repair():
    t = ('@@TOPIC_START | id=1 | title=A\n@@P | قديم\n@@TOPIC_END | id=1 | DONE\n'
         '@@TOPIC_START | id=2 | title=B\n@@P | y\n@@TOPIC_END | id=2 | DONE\n'
         '@@TOPIC_START | id=1 | title=A\n@@P | جديد\n@@TOPIC_END | id=1 | DONE\n')
    r = M.parse(t)
    ts = r.topics()
    assert [x.id for x in ts] == [1, 2]                          # الترتيب بأول ظهور، المحتوى آخر نسخة
    assert ts[0].blocks[0].text == 'جديد'
    assert r.ledger.done == ['topic:2', 'topic:1']


def test_incomplete_duplicate_does_not_override_complete():
    t = ('@@TOPIC_START | id=1 | title=A\n@@P | كامل\n@@TOPIC_END | id=1 | DONE\n'
         '@@TOPIC_START | id=1 | title=A\n@@P | ناقص\n')
    r = M.parse(t)
    assert r.topics()[0].blocks[0].text == 'كامل'
    assert 'topic:1' in r.ledger.done and 'topic:1' not in r.ledger.incomplete


def test_finished_requires_all_units_even_if_final_present():
    t = full()
    cut = t.index('@@TOPIC_START | id=5')                       # نشيل من الموضوع 5 لقدام ونحط FINAL
    r = M.parse(t[:cut] + '@@FINAL | axes=2 | topics=6\n')
    assert r.tail.final_seen and not r.ledger.finished
    assert r.ledger.next_unit == 'topic:5'
    errs, warns = M.validate(r, 60)
    assert any('قفل بدري' in w for w in warns)
    _, _ = M.validate(r, 60, mode='strict')
    assert M.validate(r, 60, mode='strict')[0] != []


def test_final_synthesized_when_all_units_done():
    t = full().replace([l for l in full().split('\n') if l.startswith('@@FINAL')][0], '')
    r = M.parse(t)
    assert r.ledger.finished and not r.tail.final_seen
    line = M.synth_final(r, 60)
    assert line.startswith('@@FINAL | axes=2 | topics=6 | cases=2')
    assert M.parse(t + '\n' + line).tail.final_seen


def test_src_parsing_and_legacy():
    assert M.parse_src('L10-L25') == [(10, 25)] and M.parse_src('10-25') == [(10, 25)]
    assert M.parse_src('L7') == [(7, 7)] and M.parse_src('L1-L5, L9') == [(1, 5), (9, 9)]
    r = M.parse('@@TOPIC_START | id=1 | title=T | srt=1-48 | time=00:00:00-00:02:10\n@@P | x\n@@TOPIC_END | id=1 | DONE\n'
                '@@AUDIO | 00:01:02 | جملة | فيها pipe\n')
    assert r.legacy and r.axes[0].implicit and r.topics()[0].src == '1-48'
    assert r.unclear()[0][0] == '00:01:02' and r.ledger.last_src == 48


def test_coverage_gap_and_overlap_detection():
    t = ('@@TOPIC_START | id=1 | title=A | src=L1-L10\n@@P | x\n@@TOPIC_END | id=1 | DONE\n'
         '@@TOPIC_START | id=2 | title=B | src=L8-L15\n@@P | x\n@@TOPIC_END | id=2 | DONE\n'
         '@@TOPIC_START | id=3 | title=C | src=L20-L25\n@@P | x\n@@TOPIC_END | id=3 | DONE\n')
    r = M.parse(t)
    cov = M.coverage(r, 30)
    assert cov['overlaps'] == [(8, 10, [1, 2])]
    assert cov['uncovered'] == [(16, 19), (26, 30)]
    _, w = M.validate(r, 30)
    assert any('تداخل' in x and 'L008-L010' in x for x in w)
    assert any('فجوة' in x and 'L016-L019' in x for x in w)
    assert any('خارج النطاق' in x for x in M.validate(r, 22)[1])


def test_why_flow_degrade_and_arrows():
    t = ('@@TOPIC_START | id=1 | title=T\n@@WHY | ليه؟ | خطوة واحدة\n@@FLOW | بس واحدة\n'
         '@@WHY | ليه؟ | أ ← ب → ج\n@@FLOW | أ → ب ← ج\n@@TOPIC_END | id=1 | DONE\n')
    b = M.parse(t).topics()[0].blocks
    assert [x.kind for x in b] == ['P', 'P', 'WHY', 'FLOW']
    assert b[2].fields['chain'] == ['أ', 'ب', 'ج'] and b[3].fields['steps'] == ['أ', 'ب', 'ج']


def test_misc_rules():
    # LINK لموضوع غير موجود، DEF ناقص، H2 يتيم، bullets بتتدمج
    t = ('@@TOPIC_START | id=1 | title=T\n@@H2 | عنوان يتيم\n@@H2 | عنوان\n@@BUL | a\n@@BUL | b\n@@DEF | X\n'
         '@@LINK | 9 | x\n@@TOPIC_END | id=1 | DONE\n')
    r = M.parse(t)
    kinds = [b.kind for b in r.topics()[0].blocks]
    assert kinds == ['H2', 'BUL', 'LINK']
    assert r.topics()[0].blocks[1].fields == ['a', 'b']
    # الجملة المسموحة بتتجاهل بصمت، وسطر غريب بيتحذّر
    r = M.parse('الخطة جاهزة. هبدأ الكتابة.\nكلام برّه\n')
    assert len(r.warnings) == 1 and 'كلام برّه' in r.warnings[0]
    # مفتاح axis: صريح ← خطة ← إطار ← 0
    assert M.parse('@@TOPIC_START | id=1 | title=T\n@@TOPIC_END | id=1 | DONE\n').topics()[0].axis == 0

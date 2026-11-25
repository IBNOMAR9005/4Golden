# -*- coding: utf-8 -*-
import asyncio, json, os
import markers as M, notes, md_prep
from store import Store

FIX = os.path.join(os.path.dirname(__file__), 'fixtures')
FULL = open(os.path.join(FIX, 'sample_full.txt'), encoding='utf-8').read()


class FakePool:
    """بديل GeminiPool: بيرد من سكريبت (نص أو دالة على contents) ويسجّل الطلبات. من غير شبكة."""
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def generate(self, session, system, contents, temperature=0.3, on_wait=None, **kw):
        self.calls.append([(r, t) for r, t in contents])
        r = self.script.pop(0) if self.script else ''
        r = r(contents) if callable(r) else r
        return r, 'STOP', 'fake-model'


def run(coro):
    return asyncio.run(coro)


def cut_before(text, marker_line):
    return text[:text.index(marker_line)]


def unit_slice(text, key):
    return M.unit_texts(text)[key]


def test_resume_message_format_exact():
    pr = M.parse(cut_before(FULL, '@@TOPIC_START | id=4'))
    msg = notes.resume_message(pr.ledger, 3)
    l1, l2 = msg.split('\n')
    assert l1 == 'RESUME | last_done=case:1.1 | last_src=L030 | next=topic:4'
    assert l2 == 'Continue per the resume protocol. Output markers only. Do not repeat the plan or any written unit.'
    assert notes.resume_message(pr.ledger, 4).split('\n')[0].endswith('| next=topic:4') and 'L0030' in notes.resume_message(pr.ledger, 4)
    hint = notes.resume_message(pr.ledger, 3, hint=True).split('\n')
    assert hint[0] == l1 and hint[-1] == 'Write shorter topics (≤350 words).'
    assert notes.repair_message('case:2.1', 'missing CASE_PEARL').split('\n')[0] == 'REPAIR | unit=case:2.1 | issue=missing CASE_PEARL'
    assert notes.coverage_message().split('\n')[0] == 'CHECK_COVERAGE'


def test_continuation_merge_strips_preamble_and_repeated_plan():
    part1 = 'مقدمة غريبة قبل الخطة\n' + cut_before(FULL, '@@TOPIC_START | id=4')
    rest = FULL[FULL.index('@@TOPIC_START | id=4'):]
    plan = M.plan_block(FULL)
    part2 = 'هكمل من الموضوع 4\n' + plan + '\n@@AXIS_START | id=2 | title=التشخيص والعلاج\n' + rest
    pool = FakePool([part1, part2])
    res = run(notes.generate_units(None, pool, 'sys', 'U1', max_calls=5, total_lines=60))
    assert res.ledger.finished and not res.stopped and res.calls == 2
    assert res.text.count('@@PLAN_START') == 1 and 'مقدمة غريبة' not in res.text and 'هكمل' not in res.text
    assert '@@FINAL' in res.text and M.parse(res.text).ledger.finished


def test_finished_requires_all_units_even_if_final_present():
    t5 = unit_slice(FULL, 'topic:5')
    broken = FULL.replace(t5, '')
    assert '@@FINAL' in broken and not M.parse(broken).ledger.finished
    pool = FakePool([broken, t5 + '\n@@TOPIC_START'])        # الرد التاني فيه ذيل ناقص بيتقص
    res = run(notes.generate_units(None, pool, 'sys', 'U1', max_calls=5, total_lines=60))
    assert res.ledger.finished and res.calls == 2
    assert pool.calls[1][-1][1].startswith('RESUME | last_done=')
    assert 'next=topic:5' in pool.calls[1][-1][1]


def test_final_synthesized_when_all_units_done():
    no_final = '\n'.join(l for l in FULL.split('\n') if not l.startswith('@@FINAL'))
    res = run(notes.generate_units(None, FakePool([no_final]), 's', 'U', max_calls=3, total_lines=60))
    assert res.ledger.finished and res.text.rstrip().split('\n')[-1].startswith('@@FINAL | axes=2 | topics=6')


def test_stall_escalation_and_hard_stop():
    pool = FakePool(['كلام من غير markers'] * 10)
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=40))
    assert res.stopped and res.reason == 'stalled' and res.calls == 4 == len(pool.calls)
    # أول استدعاء من غير resume؛ التلات الباقيين: التلميح بيظهر من بعد ثاني stall
    last_msgs = [c[-1][1] if len(c) > 1 else '' for c in pool.calls]
    assert 'shorter' not in last_msgs[1]
    # بعد plan موجودة الاستئناف بيبقى فيه RESUME والتلميح بعد stall التاني
    part1 = cut_before(FULL, '@@TOPIC_START | id=3')
    pool = FakePool([part1] + ['x'] * 10)
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=40, total_lines=60))
    assert res.stopped and res.reason == 'stalled' and res.calls == 1 + 4 + 2     # + محاولتين REPAIR لأول وحدة ناقصة بس
    msgs = [c[-1][1] for c in pool.calls[1:5]]
    assert ['shorter' in m for m in msgs] == [False, False, True, True]
    assert all(m.startswith('RESUME |') for m in msgs)
    assert all(c[-1][1].startswith('REPAIR | unit=topic:3') for c in pool.calls[5:])
    # max_calls
    pool = FakePool([cut_before(FULL, '@@TOPIC_START | id=2')] + [cut_before(FULL, '@@TOPIC_START | id=3')])
    res = run(notes.generate_units(None, FakePool([part1]), 's', 'U', max_calls=1))
    assert res.stopped and res.reason == 'max_calls' and res.calls == 1


def test_repair_replaces_unit_without_duplication():
    broken = FULL.replace('@@CASE_PEARL | في مريض السكري المتورّم والبروتين عالي، فكّر في diabetic nephropathy بس استبعد الأسباب التانية.\n', '')
    assert any(k == 'case:2.1' for k, _ in M.structural_issues(M.parse(broken)))
    fixed = unit_slice(FULL, 'case:2.1')
    pool = FakePool([broken, fixed])
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=5, total_lines=60))
    assert pool.calls[1][-1][1].startswith('REPAIR | unit=case:2.1 | issue=missing CASE_PEARL')
    pr = M.parse(res.text)
    assert M.structural_issues(pr) == [] and sum(1 for u in pr.units if u.key == 'case:2.1' and u.done) == 2
    assert len([u for u in pr.complete_units() if u.key == 'case:2.1']) == 1
    assert res.warnings == []
    # محاولتين بس لكل وحدة
    pool = FakePool([broken, 'x', 'y', 'z'])
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=5, total_lines=60))
    assert len(pool.calls) == 3 and any('ما قدرتش أصلّح case:2.1' in w for w in res.warnings)


def test_compact_vs_full_context():
    part1 = cut_before(FULL, '@@TOPIC_START | id=4')
    rest = FULL[FULL.index('@@TOPIC_START | id=4'):]
    for ctx in ('compact', 'full'):
        pool = FakePool([part1, rest])
        run(notes.generate_units(None, pool, 's', 'U1', max_calls=4, context=ctx, total_lines=60))
        c = pool.calls[1]
        assert [r for r, _ in c] == ['user', 'model', 'user'] and c[0][1] == 'U1'
        model = c[1][1]
        if ctx == 'full':
            assert '@@TOPIC_START | id=1' in model and '@@WARMUP' in model and 'RESUME' not in model
        else:
            assert '@@PLAN_START' in model and '@@DICT | نيفروتك' in model and 'LEDGER | done=5/10' in model
            assert '@@TOPIC_START | id=1' not in model and '@@CASEQ_START | id=1 | axis=1' in model
            assert '@@WRAP_START | axis=1' in model and len(model) < len(part1)


def test_tail_pass_and_coverage_pass():
    core = FULL[:FULL.index('@@HIGHYIELD_START')]
    tail = FULL[FULL.index('@@HIGHYIELD_START'):FULL.index('@@COVERAGE')]
    pool = FakePool([core, 'كلام\n' + tail + '\n@@TOPIC_START | id=9'])
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=5, total_lines=60))
    pr = M.parse(res.text)
    assert pr.tail.highyield_seen and len(pr.tail.hy) == 4 and pr.tail.bigpicture and res.calls == 2
    assert pool.calls[1][-1][1].split('\n')[0].endswith('next=tail')
    cov = '@@COVERAGE | topic=2 | src=L11-L20 | status=partial | missing=مثال الدكتور عن الكبد\n@@COVERAGE | topic=1 | status=ok'
    fixed = unit_slice(FULL, 'topic:2')
    pool = FakePool([FULL, cov, fixed])
    res = run(notes.generate_units(None, pool, 's', 'U', max_calls=5, coverage_pass=True, total_lines=60))
    assert pool.calls[1][-1][1].startswith('CHECK_COVERAGE')
    assert pool.calls[2][-1][1].startswith('REPAIR | unit=topic:2 | issue=missing: مثال الدكتور عن الكبد')
    assert '@@COVERAGE' not in res.text and 'موضوع 2' in res.coverage_summary


def test_error_after_progress_returns_stopped_and_first_error_raises():
    class Boom(FakePool):
        async def generate(self, *a, **k):
            if self.script:
                return await FakePool.generate(self, *a, **k)
            raise RuntimeError('quota key=AIzaSECRETSECRETSECRETSECRET123')
    res = run(notes.generate_units(None, Boom([cut_before(FULL, '@@TOPIC_START | id=3')]), 's', 'U', max_calls=5))
    assert res.stopped and res.reason.startswith('error:') and 'AIza' not in res.reason and len(res.ledger.done) == 2
    try:
        run(notes.generate_units(None, Boom([]), 's', 'U'))
        assert False
    except RuntimeError:
        pass


def test_status_text_and_resume_from_state(tmp_path):
    pr = M.parse(cut_before(FULL, '@@TOPIC_START | id=5'))
    txt = notes.progress_text(pr)
    assert 'محور 2/2' in txt and 'موضوع 4/6' in txt and 'topic:5' in txt
    st = Store(str(tmp_path / 'store.json'))
    saved = []

    async def ck(acc, led):
        saved.append(acc)
        st.save_job('j1', {'acc': acc, 'done': led.done}, [{'n': 1, 'kind': 'para', 'text': 'x'}])
    pool = FakePool([cut_before(FULL, '@@TOPIC_START | id=4')])
    run(notes.generate_units(None, pool, 's', 'U', max_calls=1, checkpoint=ck, total_lines=60))
    state, lines = st.load_job('j1')
    assert lines[0]['n'] == 1 and state['done'][-1] == 'case:1.1'
    rest = FULL[FULL.index('@@TOPIC_START | id=4'):]
    pool2 = FakePool([rest])
    res = run(notes.generate_units(None, pool2, 's', 'U', max_calls=3, resume_text=state['acc'], total_lines=60))
    assert res.ledger.finished and res.calls == 1                # كمّل من غير إعادة الوحدات المخلصة
    assert 'next=topic:4' in pool2.calls[0][-1][1]


def test_md_prep_numbering_and_long_paragraph_split():
    long_para = ' '.join('هذه الجملة رقم %d فيها كلام كتير بما يكفي لتطويل الفقرة شوية صغيرة.' % i for i in range(40))
    md = '# عنوان\n\nفقرة قصيرة.\n\n- بند 1\n- بند 2\n\n> اقتباس\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode1\ncode2\n```\n\n' \
         '![alt text](http://x/y.png) و[رابط](http://z.com)\n\n' + long_para + '\n'
    r = md_prep.prepare(md)
    kinds = [l['kind'] for l in r['lines']]
    assert kinds[:9] == ['heading', 'para', 'list', 'list', 'quote', 'table', 'table', 'code', 'code']
    assert r['lines'][0]['level'] == 1 and [l['n'] for l in r['lines']] == list(range(1, r['total'] + 1))
    assert r['rendered'].split('\n')[0] == '[L001] عنوان' and r['width'] == 3
    assert 'http' not in r['rendered'] and 'alt text ورابط' in r['rendered']
    parts = [l['text'] for l in r['lines'] if l['kind'] == 'para' and 'الجملة رقم' in l['text']]
    assert len(parts) >= 4 and all(len(p) <= 600 for p in parts) and all(p.endswith('.') for p in parts)
    assert ' '.join(parts).count('الجملة رقم') == 40
    big = md_prep.prepare('\n\n'.join('سطر %d' % i for i in range(1200)))
    assert big['rendered'].startswith('[L0001] ') and big['width'] == 4
    meta = md_prep.build_meta({'number': 7, 'title': 'T | x', 'doctor': '', 'warmup': True})
    assert meta == 'META:\n7 | T / x | غير محدد | غير محدد | غير محدد | غير محدد | غير محدد | warmup=on'


def test_coverage_report_text():
    pr = M.parse('@@TOPIC_START | id=1 | title=A | src=L1-L2\n@@P | x\n@@TOPIC_END | id=1 | DONE\n')
    lines = [{'n': i, 'kind': 'para', 'text': 'سطر رقم %d ' % i + 'ي' * 80} for i in range(1, 6)]
    rep = md_prep.coverage_report(pr, 5, lines)
    assert rep['uncovered'] == [dict(start=3, end=5, preview=lines[2]['text'][:60] + '…')]
    assert rep['text'].startswith('• L003-L005 — ') and rep['per_topic'] == {1: 'L001-L002'}

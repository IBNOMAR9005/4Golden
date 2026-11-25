# -*- coding: utf-8 -*-
"""الملزمة: Gemini بالبرومبت بتاعك (+ بروتوكول الاستكمال) ثم lecture_to_pdf.py.

مساران:
  • generate_notes()  — مسار الـ SRT القديم (بيرجّع (text, calls)) من غير تغيير في السلوك.
  • generate_units()  — مسار المحاضرات: محرك وحدات مبني على الـ ledger (SPEC §7).
"""
import asyncio, contextlib, importlib.util, io, os, re, sys
from dataclasses import dataclass, field

import markers as M
from store import redact

_DONE_RE = re.compile(r'^@@(TOPIC_END|WRAP_END|CASEQ_END)\b.*\bDONE\b', re.I)


def load_pdf_module(here, filename='lecture_to_pdf.py'):
    if here not in sys.path:
        sys.path.insert(0, here)
    spec = importlib.util.spec_from_file_location(os.path.splitext(filename)[0], os.path.join(here, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip_preamble(text):
    """يشيل أي كلام قبل أول @@ (زي 'هكمل من الموضوع..')."""
    return M.strip_preamble(text)


def trim_to_complete(text):
    """يقص الناتج عند آخر وحدة (موضوع/wrap/حالة) مقفولة بـ DONE (+ CHECKPOINT/CONTINUE بعدها)."""
    return M.trim_to_complete(text)


def progress_of(text):
    """(آخر id موضوع مكتمل، آخر سطر SRT اتغطى، توقيته) — مسار الـ SRT."""
    tid, last_srt, tm = 0, 0, ''
    cur = None
    for ln in text.split('\n'):
        s = ln.strip()
        if s.startswith('@@TOPIC_START'):
            cur = s
        elif re.match(r'^@@TOPIC_END\b.*\bDONE\b', s, re.I) and cur:
            m = re.search(r'id=(\d+)', cur)
            if m:
                tid = max(tid, int(m.group(1)))
            m = re.search(r'(?:srt|src)=L?(\d+)\s*[-–—]\s*L?(\d+)', cur)
            if m:
                last_srt = max(last_srt, int(m.group(2)))
            m = re.search(r'time=[\d:]+\s*[-–—]\s*([\d:]+)', cur)
            if m:
                tm = m.group(1)
    return tid, last_srt, tm


def is_finished(text):
    return '@@FINAL' in text


def count_done(text):
    """عدد الوحدات المقفولة (كل الأنواع التلاتة)."""
    return sum(1 for ln in text.split('\n') if _DONE_RE.match(ln.strip()))


def first_user_message(meta_text, srt_text):
    return ('إجابات المرحلة 0 (من المستخدم):\n%s\n\n'
            'ملف الـ SRT الكامل للمحاضرة:\n=====SRT_START=====\n%s\n=====SRT_END=====\n\n'
            'ابدأ المرحلة 1 فوراً ثم المرحلة 2 ثم المرحلة 3 حسب التعليمات، بدون أسئلة وبدون أي كلام خارج الـ markers.'
            % (meta_text.strip() or 'غير محدد', srt_text))


def continuation_message(tid, last_srt, tm):
    return ('كمّل حسب بروتوكول الاستكمال. آخر موضوع مكتمل هو %d (آخر سطر SRT مغطى: %s%s). '
            'ابدأ من أول الموضوع %d من غير ما تعيد الخطة أو أي موضوع اتكتب، وطبّق نفس القاموس والأسلوب. '
            'اكتب بس الـ markers. لو خلصت كل الـ SRT اكتب المرحلة 3 (@@HIGHYIELD_START ... @@HIGHYIELD_END ثم @@FINAL).'
            % (tid, last_srt or '؟', (' · ' + tm) if tm else '', tid + 1))


async def generate_notes(session, pool, system, srt_text, meta_text, status=None, max_calls=16):
    """يرجّع (نص الـ markers الكامل، عدد الاستدعاءات)."""
    u1 = first_user_message(meta_text, srt_text)
    acc, calls, stalls = '', 0, 0

    async def on_wait(sec):
        if status:
            await status('⏳ كوتة Gemini مشغولة، هستنى حوالي %d دقيقة…' % (sec // 60 + 1))

    while calls < max_calls:
        calls += 1
        contents = [('user', u1)]
        if acc:
            tid, ls, tm = progress_of(acc)
            contents += [('model', acc), ('user', continuation_message(tid, ls, tm))]
        text, fin, model = await pool.generate(session, system, contents, temperature=0.3, on_wait=on_wait)
        before = count_done(acc)
        if not acc:
            new = text
        else:
            new = _strip_preamble(text)
        merged = (acc + '\n' + new) if acc else new
        finished = is_finished(merged)
        # لو لسه ما خلصش: قص عند آخر موضوع كامل
        acc = merged if finished else (trim_to_complete(merged) or merged)
        done_now = count_done(acc)
        if status:
            tid, ls, tm = progress_of(acc)
            await status('✍️ بكتب الملزمة… (%d موضوع%s)' % (done_now, (' · وصلت لـ ' + tm) if tm else ''))
        if finished:
            break
        if done_now <= before:
            stalls += 1
            if stalls >= 2:
                break
        else:
            stalls = 0
    return acc, calls


def build_pdf_sync(here, text, out_pdf, srt_path, fonts_dir, module='lecture_to_pdf.py', **kw):
    """يشغّل مولّد الـ PDF (blocking) ويرجّع (warnings, meta, n_topics, pages_info).
    module: lecture_to_pdf_legacy.py = مولّد النسخة القديمة (مسار الصوت/SRT)، lecture_to_pdf.py = مسار الشرح."""
    mod = load_pdf_module(here, module)
    buf = io.StringIO()
    meta, n_topics = {}, 0
    with contextlib.redirect_stdout(buf):
        try:
            N = mod.parse(text)
            meta, n_topics = dict(N.meta), len(N.topics)
            mod.build_pdf(text, out_pdf, srt_path, fonts_dir, **kw)
        except SystemExit as e:
            raise RuntimeError(str(e.code) if e.code else 'lecture_to_pdf أنهى التنفيذ')
    out = buf.getvalue()
    warns = [ln[1:].strip() for ln in out.splitlines() if ln.startswith('⚠')]
    return warns, meta, n_topics, out



# ════════════════════════════════════════════════════════════════════
#  مسار المحاضرات: محرك الوحدات (SPEC §7)
# ════════════════════════════════════════════════════════════════════
RESUME_TEXT = 'Continue per the resume protocol. Output markers only. Do not repeat the plan or any written unit.'
SHORT_HINT = 'Write shorter topics (\u2264350 words).'
COVERAGE_TEXT = 'Reply with @@COVERAGE lines only: one per topic with status=ok|partial|missing and missing=<what>.'
STALL_HINT_AT, STALL_STOP_AT = 2, 4


@dataclass
class UnitsResult:
    text: str
    ledger: M.Ledger
    calls: int
    stopped: bool = False
    reason: str = ''
    warnings: list = field(default_factory=list)
    coverage: list = field(default_factory=list)
    coverage_summary: str = ''


def resume_message(ledger, width=3, hint=False):
    """R-44: السطر الأول آلي وحرفي."""
    first = 'RESUME | last_done=%s | last_src=%s | next=%s' % (
        ledger.last_done or 'none', M.fmt_src(ledger.last_src, width), ledger.next_unit or 'tail')
    msg = first + '\n' + RESUME_TEXT
    return msg + '\n' + SHORT_HINT if hint else msg


def repair_message(key, issue):
    """R-47: السطر الأول حرفي."""
    return 'REPAIR | unit=%s | issue=%s\nOutput only the corrected unit as markers. Do not repeat the plan or other units.' % (
        key, issue)


def coverage_message():
    return 'CHECK_COVERAGE\n' + COVERAGE_TEXT


def progress_text(pr):
    """R-51: ✍️ محور 2/4 · موضوع 9/31 (+ عنوان المحور والمفتاح الحالي)."""
    led, lec = pr.ledger, pr.lecture
    if not led.expected:
        return '✍️ بكتب الملزمة… (%d وحدة)' % len(led.done)
    done = set(led.done)
    topics = [k for k in led.expected if k.startswith('topic:')]
    td = sum(1 for k in topics if k in done)
    key = led.next_unit or led.last_done or ''
    ax_ids = sorted({a['id'] for a in lec.axes_plan} | {t['axis'] for t in lec.topics_plan if t['axis'] is not None})
    cur = None
    m = re.match(r'(topic|wrap|case):(\d+)', key)
    if m and m.group(1) == 'topic':
        cur = next((t['axis'] for t in lec.topics_plan if t['id'] == int(m.group(2))), None)
    elif m:
        cur = int(m.group(2))
    title = next((a.get('title') for a in lec.axes_plan if a['id'] == cur), '') or ''
    out = '✍️ '
    if ax_ids and cur in ax_ids:
        out += 'محور %d/%d%s · ' % (ax_ids.index(cur) + 1, len(ax_ids), (' «%s»' % title) if title else '')
    out += 'موضوع %d/%d · وحدات %d/%d' % (td, len(topics), len(done & set(led.expected)), len(led.expected))
    return out + ((' · ' + key) if key else '')


def _ledger_line(led):
    return 'LEDGER | done=%d/%d | last_done=%s | next=%s' % (
        len(led.done), len(led.expected), led.last_done or 'none', led.next_unit or 'tail')


def build_contents(u1, acc, tail_msg, context, led, extra_unit_key=None):
    """R-46: full = كل اللي اتكتب كـ model turn. compact = الخطة + DICT + آخر وحدتين + سطر ledger."""
    if not acc:
        return [('user', u1)]
    if context == 'full':
        return [('user', u1), ('model', acc), ('user', tail_msg)]
    texts = M.unit_texts(acc)
    keep = list(led.done[-2:])
    if extra_unit_key and extra_unit_key in texts and extra_unit_key not in keep:
        keep.insert(0, extra_unit_key)
    parts = [M.plan_block(acc)] + [texts[k] for k in keep if k in texts] + [_ledger_line(led)]
    return [('user', u1), ('model', '\n'.join(p for p in parts if p)), ('user', tail_msg)]


async def generate_units(session, pool, system, user_message, status=None, max_calls=40, context='compact',
                         resume_text='', coverage_pass=False, checkpoint=None, total_lines=0,
                         temperature=0.3, finalize=True):
    """يرجّع UnitsResult. الإنهاء بقرار الكود مش الموديل (R-41). ما بيرميش غير لو مفيش أي ناتج."""
    width = max(3, len(str(total_lines or 0)))
    acc = M.trim_to_complete(resume_text) if resume_text else ''
    pr = M.parse(acc)
    calls, stalls, stopped, reason = 0, 0, False, 'finished'
    warns = []
    stash = ''          # ذيل (HIGHYIELD/BIGPICTURE/FINAL) الموديل كتبه بدري واتقص؛ بنرجّعه لما الوحدات تخلص

    async def on_wait(sec):
        if status:
            await status('⏳ كوتة Gemini مشغولة، هستنى حوالي %d دقيقة…' % (sec // 60 + 1))

    async def call(contents):
        nonlocal calls
        text, fin, model = await pool.generate(session, system, contents, temperature=temperature, on_wait=on_wait)
        calls += 1
        return text

    # ── الحلقة الرئيسية ──
    while True:
        led = pr.ledger
        if acc and led.finished:
            break
        if calls >= max_calls:
            stopped, reason = True, 'max_calls'
            break
        msg = resume_message(led, width, hint=stalls >= STALL_HINT_AT)
        try:
            text = await call(build_contents(user_message, acc, msg, context, led))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not acc:
                raise
            stopped, reason = True, 'error: %s %s' % (type(e).__name__, redact(str(e))[:200])
            break
        new = redact(M.strip_preamble(text))      # أي سر يهلوسه الموديل ما يدخلش الملزمة
        if acc:
            new = M.remove_plan(new)
        merged = (acc + '\n' + new) if acc else new
        trimmed = M.trim_to_complete(merged)
        pr2 = M.parse(trimmed)
        added = set(pr2.ledger.done) - set(led.done)
        final_in_new = any(M._line_marker(l) == 'FINAL' for l in new.split('\n'))
        stash = M.extract_tail(merged) or stash
        if pr2.ledger.finished or (not pr2.ledger.plan_present and final_in_new and pr2.ledger.done):
            tail = stash
            if tail:
                trimmed = trimmed.rstrip() + '\n' + tail + '\n'
                pr2 = M.parse(trimmed)
        acc, pr = trimmed, pr2
        if status:
            await status(progress_text(pr))
        if checkpoint:
            await checkpoint(acc, pr.ledger)
        if not pr.ledger.plan_present and final_in_new and pr.ledger.done:
            reason = 'no_plan_final'
            warns.append('الموديل ما كتبش خطة؛ اتوقفنا عند FINAL')
            break
        stalls = 0 if added else stalls + 1
        if stalls >= STALL_STOP_AT:
            stopped, reason = True, 'stalled'
            break

    # ── ذيل المستند (HIGHYIELD/BIGPICTURE/FINAL) لو الوحدات خلصت والذيل ناقص: محاولة واحدة ──
    if finalize and pr.ledger.finished and not (pr.tail.highyield_seen or pr.tail.final_seen or pr.tail.bigpicture) \
            and calls < max_calls and not stopped:
        try:
            text = await call(build_contents(user_message, acc, resume_message(pr.ledger, width), context, pr.ledger))
            tail = M.extract_tail(M.strip_preamble(text))
            if tail:
                acc = acc.rstrip() + '\n' + tail + '\n'
                pr = M.parse(acc)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            warns.append('طلب الذيل فشل: %s' % type(e).__name__)

    # ── الإصلاح (R-47): بس لو مش مقطوعين بسبب كوتة/خطأ/سقف ──
    async def repair(key, issue):
        nonlocal acc, pr
        for _ in range(2):
            try:
                text = await call(build_contents(user_message, acc, repair_message(key, issue), context, pr.ledger,
                                                 extra_unit_key=key))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                warns.append('إصلاح %s فشل: %s %s' % (key, type(e).__name__, redact(str(e))[:100]))
                return False
            cand = M.unit_texts(M.remove_plan(M.strip_preamble(text))).get(key)
            if not cand:
                continue
            trial = M.parse(acc.rstrip() + '\n' + cand + '\n')
            if key in trial.ledger.done and not any(k == key for k, _ in M.structural_issues(trial)):
                acc, pr = acc.rstrip() + '\n' + cand + '\n', trial
                return True
        return False

    if (not stopped or reason == 'stalled') and pr.ledger.plan_present:
        targets = M.repair_targets(pr)
        if stopped:                         # بعد stall: البنيوي + أول وحدة ناقصة بس (مش استنزاف كوتة)
            miss = [t for t in targets if t[1] in ('missing', 'incomplete')]
            targets = [t for t in targets if t not in miss] + miss[:1]
        budget = 2 * len(targets)
        for key, issue in targets:
            if budget <= 0:
                break
            budget -= 2
            if not await repair(key, issue):
                warns.append('ما قدرتش أصلّح %s (%s) بعد محاولتين' % (key, issue))
            if checkpoint:
                await checkpoint(acc, pr.ledger)
            if status:
                await status(progress_text(pr))

    # ── فحص التغطية الاختياري (R-48) ──
    cov_lines, cov_sum = [], ''
    if finalize and coverage_pass and acc and not stopped:
        try:
            text = await call(build_contents(user_message, acc, coverage_message(), context, pr.ledger))
            cov_lines = M.parse(M.strip_preamble(text)).coverage_lines
        except asyncio.CancelledError:
            raise
        except Exception as e:
            warns.append('فحص التغطية فشل: %s' % type(e).__name__)
        bad = [c for c in cov_lines if (c.get('status') or '').lower() in ('partial', 'missing')]
        for c in bad:
            tid = M._int(c.get('topic'))
            if tid is None:
                continue
            await repair('topic:%d' % tid, 'missing: %s' % (c.get('missing') or 'unspecified'))
        cov_sum = '\n'.join('• موضوع %s [%s]: %s' % (c.get('topic'), c.get('status'), c.get('missing') or '')
                            for c in bad)

    # ── FINAL مصنّع لو الوحدات كلها خلصت (R-41) ──
    if finalize and pr.ledger.finished and not pr.tail.final_seen:
        acc = acc.rstrip() + '\n' + M.synth_final(pr, total_lines) + '\n'
        pr = M.parse(acc)
    return UnitsResult(text=acc, ledger=pr.ledger, calls=calls, stopped=stopped, reason=reason, warnings=warns,
                       coverage=cov_lines, coverage_summary=cov_sum)


# ════════════════════════════════════════════════════════════════════
#  التقسيم على المفاتيح: خطة واحدة ← كل محور يتكتب لوحده بالتوازي (مفتاح لكل محور) ← دمج ← ذيل
#  مفتاح واحد مش بيستحمل محاضرة كاملة، فكل مهمة بتاخد بس أسطر محورها (سياق أصغر + طلبات أقل لكل مفتاح).
# ════════════════════════════════════════════════════════════════════
PLAN_ONLY_TEXT = ('PLAN_ONLY | Output only the plan block (@@PLAN_START ... @@PLAN_END) and then the single line: %s '
                  'Do not write any unit.' % M.PLAN_SENTENCE)


def _plan_for_axis(plan, axis):
    """كتلة الخطة متفلترة لمحور واحد: AXIS_PLAN/TOPIC_PLAN/STRUCT بتاعته + باقي السطور العامة."""
    topic_ids = set()
    for ln in plan.split('\n'):
        if M._line_marker(ln) == 'TOPIC_PLAN':
            a, i = re.search(r'\baxis=(\d+)', ln), re.search(r'\bid=(\d+)', ln)
            if a and i and int(a.group(1)) == axis:
                topic_ids.add(int(i.group(1)))
    out = []
    for ln in plan.split('\n'):
        mk = M._line_marker(ln)
        if mk == 'AXIS_PLAN':
            m = re.search(r'\bid=(\d+)', ln)
            if not (m and int(m.group(1)) == axis):
                continue
        elif mk == 'TOPIC_PLAN':
            m = re.search(r'\bid=(\d+)', ln)
            if not (m and int(m.group(1)) in topic_ids):
                continue
        elif mk == 'STRUCT':
            m = re.search(r'\btopic=(\d+)', ln)
            if m and int(m.group(1)) not in topic_ids:
                continue
        out.append(ln)
    return '\n'.join(out)


def _axis_chunk(text, axis):
    """نص المحور k من ناتج مدموج (من @@AXIS_START id=k لحد بداية المحور اللي بعده أو الذيل)."""
    out, on = [], False
    for ln in text.split('\n'):
        mk = M._line_marker(ln)
        if mk == 'AXIS_START':
            m = re.search(r'\bid=(\d+)', ln)
            on = bool(m and int(m.group(1)) == axis)
        elif mk == 'HIGHYIELD_START':
            on = False
        if on:
            out.append(ln)
    return '\n'.join(out)


def _axis_lines(lec, axis, lines, width):
    """أسطر المصدر المرقّمة بتاعة المحور (اتحاد src المواضيع، وإلا src المحور)."""
    rng = []
    for t in lec.topics_plan:
        if (t['axis'] if t['axis'] is not None else 0) == axis:
            rng += M.parse_src(t.get('src'))
    if not rng:
        ap = next((a for a in lec.axes_plan if a['id'] == axis), {})
        rng = M.parse_src(ap.get('src'))
    want = set()
    for a, b in rng:
        want.update(range(a, b + 1))
    return '\n'.join('[%s] %s' % (M.fmt_src(l['n'], width), l['text']) for l in lines if l['n'] in want)


async def generate_parallel(session, pool, system, meta_text, lines, total_lines, status=None, max_calls=40,
                            context='compact', resume_text='', coverage_pass=False, checkpoint=None,
                            concurrency=3, temperature=0.3, full_message=None):
    """يرجّع UnitsResult. لو الخطة ما طلعتش/مفيش محاور: بيرجع للمحرك المتسلسل generate_units."""
    import md_prep
    width = max(3, len(str(total_lines or 0)))
    full_message = full_message or md_prep.build_user_message(
        meta_text, '\n'.join('[%s] %s' % (M.fmt_src(l['n'], width), l['text']) for l in lines))

    async def on_wait(sec):
        if status:
            await status('⏳ كوتة Gemini مشغولة، هستنى حوالي %d دقيقة…' % (sec // 60 + 1))

    async def sequential(reason):
        r = await generate_units(session, pool, system, full_message, status=status, max_calls=max_calls,
                                 context=context, resume_text=resume_text, coverage_pass=coverage_pass,
                                 checkpoint=checkpoint, total_lines=total_lines, temperature=temperature)
        r.warnings.insert(0, 'اتشرحت بالتتابع (%s)' % reason)
        return r

    # ── 1) الخطة (مرة واحدة) ──
    plan = M.plan_block(resume_text) if resume_text else ''
    plan_calls = 0
    if not plan:
        if status:
            await status('🧭 بقسّم المحاضرة لمحاور ومواضيع…')
        for _ in range(2):
            text, _f, _m = await pool.generate(session, system, [('user', full_message + '\n\n' + PLAN_ONLY_TEXT)],
                                               temperature=temperature, on_wait=on_wait)
            plan_calls += 1
            cand = M.plan_block(redact(M.strip_preamble(text)))
            lec = M.parse(cand).lecture
            if cand and lec.topics_plan and lec.axes_plan:
                plan = cand
                break
        if not plan:
            return await sequential('الخطة ما طلعتش بمحاور')
    lec = M.parse(plan).lecture
    axes = sorted({a['id'] for a in lec.axes_plan})
    if not axes:
        return await sequential('مفيش محاور في الخطة')

    # ── 2) كل محور في مهمة مستقلة (مفتاح لكل مهمة) ──
    seed_all = resume_text or ''
    axis_acc = {}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(max(1, min(concurrency, len(axes))))
    stats = {'calls': 0, 'axes_done': 0}
    expected_n = {}

    def merged():
        parts = [plan, M.PLAN_SENTENCE]
        for k in axes:
            if axis_acc.get(k):
                parts.append(M.remove_plan(axis_acc[k]).strip())
        return '\n'.join(p for p in parts if p).rstrip() + '\n'

    async def report():
        if status:
            done = sum(len(M.parse(axis_acc.get(k, '')).ledger.done) for k in axes)
            tot = sum(expected_n.values())
            await status('✍️ بكتب الملزمة بالتوازي · محور %d/%d خلص · وحدات %d/%d · %d محور شغال' % (
                stats['axes_done'], len(axes), done, tot, min(concurrency, len(axes))))

    async def worker(k):
        async with sem:
            fplan = _plan_for_axis(plan, k)
            ex = M.plan_expected(M.parse(fplan).lecture)
            expected_n[k] = len(ex)
            seed = fplan
            chunk = _axis_chunk(seed_all, k) if seed_all else ''
            if chunk:
                seed = fplan + '\n' + M.PLAN_SENTENCE + '\n' + chunk
            body = _axis_lines(lec, k, lines, width)
            header = ('AXIS_TASK | axis=%d | units=%s\nWrite ONLY the units of this axis (listed in units=). The plan below is final; '
                      'do not write any other axis, HIGHYIELD, BIGPICTURE or FINAL.' % (k, ','.join(ex)))
            msg = '%s\n\n%s\n\n%s\n\nLECTURE_START\n%s\nLECTURE_END' % (
                meta_text.strip(), header, fplan, body)

            async def ckpt(acc, led):
                async with lock:
                    axis_acc[k] = acc
                    await report()
                    if checkpoint:
                        text = merged()
                        await checkpoint(text, M.parse(text).ledger)

            r = await generate_units(session, pool, system, msg, status=None, max_calls=max_calls, context=context,
                                     resume_text=seed, coverage_pass=False, checkpoint=ckpt,
                                     total_lines=total_lines, temperature=temperature, finalize=False)
            axis_acc[k] = M.trim_to_complete(r.text) or axis_acc.get(k, '')
            stats['calls'] += r.calls
            if r.ledger.finished:
                stats['axes_done'] += 1
            await report()
            return k, r

    results = await asyncio.gather(*(worker(k) for k in axes), return_exceptions=True)
    warns = []
    for k, res in zip(axes, results):
        if isinstance(res, asyncio.CancelledError):
            raise res
        if isinstance(res, Exception):
            warns.append('محور %d فشل: %s %s' % (k, type(res).__name__, redact(str(res))[:120]))
        elif res[1].stopped:
            warns.append('محور %d وقف: %s' % (k, res[1].reason[:100]))
    text = merged()

    # ── 3) الدمج + الذيل + أي وحدة ناقصة (بالمحرك المتسلسل على الخطة الكاملة) ──
    if status:
        await status('🧩 بدمج المحاور وبكتب الخلاصة النهائية…')
    final = await generate_units(session, pool, system, full_message, status=status, max_calls=max_calls,
                                 context=context, resume_text=text, coverage_pass=coverage_pass,
                                 checkpoint=checkpoint, total_lines=total_lines, temperature=temperature)
    final.calls += stats['calls'] + plan_calls
    final.warnings = warns + final.warnings
    return final

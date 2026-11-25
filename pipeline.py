# -*- coding: utf-8 -*-
"""خطوات الشغل (من غير أي كود تليجرام عشان تتجرب لوحدها): تفريغ ← مواضيع ← ملزمة."""
import asyncio, json, os, re, shutil, time
import aiohttp

import media, subs, render, notes, md_prep, markers
from groq_stt import GroqPool, GroqError
from gemini_client import GeminiPool, GeminiError

HERE = os.path.dirname(os.path.abspath(__file__))


def read_prompt(name):
    with open(os.path.join(HERE, 'prompts', name), encoding='utf-8') as f:
        return f.read()


class App:
    def __init__(self, cfg, store, log=print):
        self.cfg, self.store, self.log = cfg, store, log
        self.session = None
        self.groq = GroqPool(cfg, store, log)
        self.gem_t = GeminiPool(cfg.gemini_keys, cfg.gemini_models, cfg.gemini_base, cfg.gemini_max_out, 'topics', log)
        self.gem_n = GeminiPool(cfg.gemini_keys_pdf or cfg.gemini_keys, cfg.gemini_models_pdf, cfg.gemini_base,
                                cfg.gemini_max_out, 'notes', log)
        # مجمّع شرح المحاضرات: مفاتيح الملزمة (tier 0) ثم مفاتيح المواضيع (tier 1) بعد حذف المكرر
        lk, lt, seen = [], [], set()
        for tier, keys in ((0, cfg.gemini_keys_pdf), (1, cfg.gemini_keys)):
            for k in keys:
                if k not in seen:
                    seen.add(k)
                    lk.append(k)
                    lt.append(tier)
        self.gem_l = GeminiPool(lk, cfg.gemini_models_lecture, cfg.gemini_base, cfg.gemini_max_out, 'lecture', log, tiers=lt)
        self.lecture_tiers = (sum(1 for t in lt if t == 0), sum(1 for t in lt if t == 1))

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()


LANG_PROMPTS = {
    'en': 'A medical lecture. Terms: pathophysiology, diagnosis, differential diagnosis, treatment, ECG, myocardial infarction.',
}


def lang_args(app, lang):
    if lang == 'auto':
        return None, app.cfg.whisper_prompt
    if lang == 'ar':
        return 'ar', app.cfg.whisper_prompt
    return lang, LANG_PROMPTS.get(lang)


async def transcribe(app, job_id, uniq, src_path, lang, status):
    """يرجّع dict(segs, cues, duration, info). status: async fn(text)"""
    cfg = app.cfg
    workdir = os.path.join(cfg.work_dir, job_id)
    shutil.rmtree(workdir, ignore_errors=True)

    async def stage(name):
        await status({'convert': '🎛 بحوّل الصوت (mono 16kHz + تطبيع)…', 'split': '✂️ بقسّم عند أقرب سكون…'}[name])

    prep = await media.prepare(src_path, workdir, cfg.chunk_seconds, cfg.chunk_mp3_kbps, cfg.normalize_audio, stage)
    duration, chunks = prep['duration'], prep['chunks']
    language, prompt = lang_args(app, lang)

    cache_dir = os.path.join(cfg.data_dir, 'cache', '%s_%s_%d' % (re.sub(r'\W', '', uniq or job_id), lang, cfg.chunk_seconds))
    os.makedirs(cache_dir, exist_ok=True)

    keys, cap, wait = app.groq.plan_keys(duration, cfg.max_keys_per_job)
    note = None
    if not keys:
        raise GroqError('مفيش مفاتيح Groq شغالة.')
    if cap < duration and wait > 60:
        note = '⏳ الكوتة المتاحة أقل من مدة الملف؛ هكمل بالمتاح وأستنى تجديدها (~%d دقيقة).' % (wait // 60 + 1)

    done, results, lock = 0, {}, asyncio.Lock()
    queue = asyncio.Queue()
    for c in chunks:
        queue.put_nowait(c)
    total = len(chunks)

    async def report(extra=''):
        txt = '🎙 تفريغ Groq… %d/%d  ·  مفاتيح: %s%s' % (done, total, ' + '.join(keys), ('\n' + extra) if extra else '')
        await status(txt)

    async def on_wait(w):
        await report('⏳ مستني تجديد كوتة Groq (~%d دقيقة)' % (w // 60 + 1))

    async def worker():
        nonlocal done
        while True:
            try:
                c = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            cf = os.path.join(cache_dir, 'c%03d_%d.json' % (c['index'], int(c['start'])))
            segs = None
            if os.path.exists(cf):
                try:
                    segs = json.load(open(cf, encoding='utf-8'))
                except ValueError:
                    segs = None
            if segs is None:
                r = await app.groq.transcribe(app.session, c['path'], c['dur'], keys, language, prompt, on_wait)
                segs = []
                for s in r['segments']:
                    segs.append(dict(start=float(s['start']) + c['start'], end=float(s['end']) + c['start'],
                                     text=s.get('text', ''), no_speech_prob=s.get('no_speech_prob'),
                                     avg_logprob=s.get('avg_logprob'), compression_ratio=s.get('compression_ratio')))
                if not segs and (r.get('text') or '').strip():
                    segs = [dict(start=c['start'], end=c['end'], text=r['text'])]
                json.dump(segs, open(cf, 'w', encoding='utf-8'), ensure_ascii=False)
            async with lock:
                results[c['index']] = segs
                done += 1
            await report()

    await report(note or '')
    ws = [asyncio.create_task(worker()) for _ in range(max(1, len(keys)))]
    try:
        await asyncio.gather(*ws)
    except BaseException:
        for w in ws:
            w.cancel()
        await asyncio.gather(*ws, return_exceptions=True)
        raise
    allsegs = [s for i in sorted(results) for s in results[i]]
    cleaned = subs.clean_segments(allsegs)
    if not cleaned:
        raise media.MediaError('مفيش كلام مسموع في الملف (التفريغ طلع فاضي).')
    cues = subs.to_cues(cleaned)
    shutil.rmtree(workdir, ignore_errors=True)
    return dict(segs=cleaned, cues=cues, duration=duration, tracks=prep['audio_tracks'], has_video=prep['has_video'],
                keys=keys)


async def make_topics(app, cues, duration, status):
    """يرجّع (قايمة رسايل HTML، (n_sections, n_items)). لو مفاتيح المواضيع فشلت يجرّب مفاتيح الملزمة."""
    pools = [app.gem_t]
    if app.gem_n is not app.gem_t and set(app.gem_n.labels.values()) - set(app.gem_t.labels.values()):
        pools.append(app.gem_n)
    transcript = subs.compact_transcript(cues)
    head = 'Lecture duration: %s\nNumber of transcript lines: %d\n\nTRANSCRIPT:\n' % (subs.hms(duration), len(cues))
    sysm = read_prompt('topics.txt')

    async def on_wait(sec):
        await status('⏳ كوتة Gemini مشغولة (~%d دقيقة)…' % (sec // 60 + 1))

    async def gen(system, user, max_wait):
        errs = []
        for pool in pools:
            for use_schema in (True, False):
                try:
                    u = user if use_schema else user + '\n\nReturn ONLY valid JSON: {"lecture_title": str, "sections": [{"title": str, "emoji": str, "items": [{"time": "HH:MM:SS", "label": str, "key": bool}]}]}'
                    text, fin, model = await pool.generate(app.session, system, [('user', u)],
                                                           schema=render.SCHEMA if use_schema else None,
                                                           want_json=not use_schema, temperature=0.2,
                                                           max_wait=max_wait, on_wait=on_wait)
                    return text, fin
                except GeminiError as e:
                    errs.append(str(e))
                    if 'HTTP 400' not in str(e):
                        break
        raise GeminiError(' || '.join(errs)[:600])

    async def call(system, user, max_wait=420):
        for attempt in range(3):
            text, fin = await gen(system, user, max_wait)
            try:
                return render.parse_json(text)
            except ValueError:
                app.log('topics: JSON parse failed (%s, attempt %d)' % (fin, attempt + 1))
        raise GeminiError('Gemini رجّع JSON مش سليم 3 مرات.')

    await status('🧠 Gemini بيقرا التفريغ كله ويطلّع المحاور…')
    draft = await call(sysm, head + transcript)
    final = draft
    if app.cfg.topics_review:
        await status('🔎 مراجعة تانية للتغطية والتوقيتات…')
        try:
            rv = read_prompt('topics_review.txt')
            user = head + transcript + '\n\nDRAFT INDEX (JSON):\n' + json.dumps(draft, ensure_ascii=False)
            reviewed = await call(rv, user, max_wait=90)
            if len(reviewed.get('sections', [])) and sum(len(s.get('items', [])) for s in reviewed['sections']) >= \
                    0.8 * sum(len(s.get('items', [])) for s in draft.get('sections', [])):
                final = reviewed
        except (GeminiError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            app.log('topics review skipped: %r' % e)
    title, sections = render.normalize(final, [c[0] for c in cues], duration)
    if not sections:
        raise GeminiError('مفيش مواضيع طلعت من Gemini.')
    return render.render_messages(title, sections, duration), render.stats(sections)


def safe_name(s, default='lecture'):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', s or '').strip(' .')
    s = re.sub(r'\s+', ' ', s)
    return (s[:80] or default)


async def make_pdf(app, srt_text, meta_text, outdir, status, mode=None, job_id=None, resume=False):
    """يرجّع dict(pdf, md, warnings, meta, topics, calls). mode: srt (افتراضي legacy) | lecture."""
    if (mode or app.cfg.notes_mode) == 'lecture':
        return await make_pdf_lecture(app, srt_text, meta_text, outdir, status, job_id=job_id, resume=resume)
    os.makedirs(outdir, exist_ok=True)
    system = read_prompt('notes.txt') + read_prompt('notes_auto.txt')
    text, calls = await notes.generate_notes(app.session, app.gem_n, system, srt_text, meta_text, status)
    if '@@TOPIC_START' not in text:
        raise GeminiError('Gemini ما كتبش مواضيع بالصيغة المطلوبة.')
    await status('📄 بحوّل الملزمة لـ PDF…')
    srt_path = os.path.join(outdir, 'lecture.srt')
    open(srt_path, 'w', encoding='utf-8').write(srt_text)
    tmp_pdf = os.path.join(outdir, 'notes.pdf')
    warns, meta, n_topics, _ = await asyncio.to_thread(notes.build_pdf_sync, HERE, text, tmp_pdf, srt_path, app.cfg.fonts_dir,
                                          module='lecture_to_pdf_legacy.py')
    base = safe_name(('Lecture %s - %s' % (meta.get('number', ''), meta.get('title', ''))).replace('Lecture  - ', 'Lecture - ')
                     if meta.get('title') else 'Lecture notes')
    pdf = os.path.join(outdir, base + '.pdf')
    os.replace(tmp_pdf, pdf)
    md = os.path.join(outdir, base + '.md.txt')
    open(md, 'w', encoding='utf-8').write(text)
    return dict(pdf=pdf, md=md, warnings=warns, meta=meta, topics=n_topics, calls=calls)


LECTURE_PROMPT = 'lecture_explainer_prompt.md'


def _snapshot(cfg, total, ledger):
    """حالة الـ job بتتحفظ من غير أي مفاتيح أو توكنز (R-49)."""
    return dict(version=1, mode='lecture', total_lines=total, context=cfg.notes_context, max_calls=cfg.notes_max_calls,
                validate_mode=cfg.validate_mode, models=list(cfg.gemini_models_lecture),
                done=list(ledger.done), expected=list(ledger.expected), next_unit=ledger.next_unit)


async def make_pdf_lecture(app, md_text, meta_text, outdir, status, job_id=None, resume=False):
    """lecture .md ← أسطر مرقّمة ← Gemini (وحدات + استكمال + إصلاح) ← PDF."""
    cfg = app.cfg
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(HERE, 'prompts', LECTURE_PROMPT)
    if not os.path.exists(path):
        raise GeminiError('برومبت المنتج prompts/%s مش موجود؛ ضيفه وبعدين جرّب تاني.' % LECTURE_PROMPT)
    system = read_prompt(LECTURE_PROMPT)
    state, saved_lines = (app.store.load_job(job_id) if (resume and job_id) else (None, None))
    if state and saved_lines:                      # R-66: نفس الترقيم بعد الاستئناف
        lines, total = saved_lines, len(saved_lines)
        width = max(3, len(str(total)))
        rendered = '\n'.join('[%s] %s' % (markers.fmt_src(l['n'], width), l['text']) for l in lines)
        resume_text = state.get('acc', '')
    else:
        prep = md_prep.prepare(md_text)
        lines, total, rendered, resume_text = prep['lines'], prep['total'], prep['rendered'], ''
    if total == 0:
        raise RuntimeError('ملف المحاضرة فاضي.')
    user_message = md_prep.build_user_message(meta_text or 'META:\nغير محدد', rendered)

    async def checkpoint(acc, ledger):
        if job_id:
            st = _snapshot(cfg, total, ledger)
            st['acc'] = acc
            await asyncio.to_thread(app.store.save_job, job_id, st, lines)

    if cfg.lecture_split:
        par = cfg.lecture_parallel or max(1, min(6, app.lecture_tiers[0] or app.lecture_tiers[1]))
        res = await notes.generate_parallel(app.session, app.gem_l, system, meta_text or 'META:\nغير محدد', lines, total,
                                            status=status, max_calls=cfg.notes_max_calls, context=cfg.notes_context,
                                            resume_text=resume_text, coverage_pass=cfg.coverage_pass,
                                            checkpoint=checkpoint, concurrency=par, full_message=user_message)
    else:
        res = await notes.generate_units(app.session, app.gem_l, system, user_message, status=status,
                                         max_calls=cfg.notes_max_calls, context=cfg.notes_context,
                                         resume_text=resume_text, coverage_pass=cfg.coverage_pass,
                                         checkpoint=checkpoint, total_lines=total)
    pr = markers.parse(res.text)
    errors, vwarns = markers.validate(pr, total, cfg.validate_mode)
    if errors:
        raise RuntimeError('الملزمة ما اتبنتش: ' + ' | '.join(errors))
    await status('📄 بحوّل الملزمة لـ PDF…')
    tmp_pdf = os.path.join(outdir, 'notes.pdf')
    warns, meta, n_topics, _ = await asyncio.to_thread(
        notes.build_pdf_sync, HERE, res.text, tmp_pdf, None, cfg.fonts_dir,
        total=total, validate_mode=cfg.validate_mode, answers_at_end=cfg.answers_at_end)
    base = safe_name(('Lecture %s - %s' % (meta.get('number', ''), meta.get('title', ''))).replace('Lecture  - ', 'Lecture - ')
                     if meta.get('title') else 'Lecture notes')
    pdf = os.path.join(outdir, base + '.pdf')
    os.replace(tmp_pdf, pdf)
    mdp = os.path.join(outdir, base + '.md.txt')
    open(mdp, 'w', encoding='utf-8').write(res.text)
    rep = md_prep.coverage_report(pr, total, lines)
    return dict(pdf=pdf, md=mdp, warnings=list(dict.fromkeys(warns + res.warnings)), meta=meta, topics=n_topics,
                calls=res.calls, stopped=res.stopped, reason=res.reason, ledger=res.ledger,
                coverage_summary=res.coverage_summary, coverage_text=rep['text'], total_lines=total)

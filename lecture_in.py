# -*- coding: utf-8 -*-
"""مدخلات شرح المحاضرات: ملف md/txt/pdf ← نص markdown جاهز لـ md_prep.prepare().

PDF: نحاول استخراج النص محلياً (pdftotext ثم pypdf)؛ لو طلع قليل (ملزمة مصورة) أو العربي مقلوب/مفكك،
بنطلب من Gemini ينسخ المحتوى كـ markdown (الملف بيتبعت inline، حد أقصى ~18MB).
"""
import asyncio, base64, os, re, shutil, subprocess

TEXT_EXT = {'.md', '.markdown', '.txt'}
PDF_EXT = {'.pdf'}
MAX_INLINE = 18 * 1024 * 1024
MIN_CHARS_PER_PAGE = 80

EXTRACT_SYSTEM = ('You are a precise document transcriber. Transcribe the attached lecture document completely and '
                  'faithfully into Markdown. Rules: do not summarize, do not translate, do not add commentary; keep every '
                  'sentence, number, unit and term exactly; keep the original language(s); use # headings for titles, '
                  '- for bullets, and | rows for tables; for slides, write each slide as its own section in order; for '
                  'figures/diagrams write a one-line description in square brackets. Output only the Markdown.')


def kind_of(name, mime=''):
    ext = os.path.splitext(name or '')[1].lower()
    mime = (mime or '').lower()
    if ext in PDF_EXT or mime == 'application/pdf':
        return 'pdf'
    if ext in TEXT_EXT or mime in ('text/markdown', 'text/plain', 'text/x-markdown'):
        return 'text'
    return None


def read_text_file(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'utf-16', 'cp1256', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode('utf-8', 'replace')


def _pdf_pages(path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return 0


def _pdf_local_text(path):
    if shutil.which('pdftotext'):
        r = subprocess.run(['pdftotext', '-enc', 'UTF-8', path, '-'], capture_output=True, timeout=300)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode('utf-8', 'replace')
    try:
        from pypdf import PdfReader
        return '\n'.join((p.extract_text() or '') for p in PdfReader(path).pages)
    except Exception:
        return ''


def _arabic_looks_broken(text):
    """عربي بصيغ العرض (FE70-FEFF) أو أحرف مفككة = غالباً ترتيب بصري مقلوب → الأفضل نسخ Gemini."""
    ar = [c for c in text if '\u0600' <= c <= '\u06FF' or '\uFB50' <= c <= '\uFDFF' or '\uFE70' <= c <= '\uFEFF']
    if len(ar) < 50:
        return False
    pres = sum(1 for c in ar if c >= '\uFB50')
    return pres / len(ar) > 0.05


def _clean_pdf_text(t):
    t = t.replace('\r\n', '\n').replace('\r', '\n').replace('\f', '\n\n')
    t = re.sub(r'(?<=\w)-\n(?=\w)', '', t)               # كلمات مقطوعة بشرطة آخر السطر
    t = re.sub(r'[ \t]+\n', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


async def load(path, name, mime, pool, session, status):
    """يرجّع (markdown_text, source) حيث source = text|pdf-local|pdf-gemini."""
    k = kind_of(name, mime)
    if k == 'text':
        return read_text_file(path), 'text'
    if k != 'pdf':
        raise RuntimeError('الصيغة دي مش مدعومة. ابعت PDF أو MD أو TXT.')
    await status('📖 باقرا الـ PDF…')
    pages = await asyncio.to_thread(_pdf_pages, path)
    local = _clean_pdf_text(await asyncio.to_thread(_pdf_local_text, path))
    weak = len(local) < MIN_CHARS_PER_PAGE * max(1, pages or 1)
    if local and not weak and not _arabic_looks_broken(local):
        return local, 'pdf-local'
    size = os.path.getsize(path)
    if size > MAX_INLINE:
        if local:
            return local, 'pdf-local'
        raise RuntimeError('الـ PDF مصوّر/مفيهوش نص قابل للنسخ وحجمه أكبر من 18MB. صغّره أو ابعته كـ MD.')
    await status('🔎 الـ PDF محتاج قراءة بالذكاء الاصطناعي (مصوّر أو عربي مش مقروء)… ممكن ياخد كام دقيقة')
    b64 = base64.b64encode(open(path, 'rb').read()).decode()

    async def on_wait(sec):
        await status('⏳ كوتة Gemini مشغولة، هستنى حوالي %d دقيقة…' % (sec // 60 + 1))

    text, fin, model = await pool.generate(
        session, EXTRACT_SYSTEM,
        [('user', 'Transcribe this document to Markdown now.', [('application/pdf', b64)])],
        temperature=0.0, on_wait=on_wait)
    text = re.sub(r'^```(?:markdown|md)?\s*\n|\n```\s*$', '', text.strip())
    if len(text) < 200 and local:
        return local, 'pdf-local'
    if len(text) < 50:
        raise RuntimeError('ما قدرتش أطلّع نص من الـ PDF.')
    return text, 'pdf-gemini'

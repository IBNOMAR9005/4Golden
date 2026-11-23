# بوت تفريغ + شرح المحاضرات

- **صوت/فيديو** ← تفريغ SRT/TXT + مواضيع + ملزمة (زي النسخة القديمة بالظبط، بمولّد PDF القديم `lecture_to_pdf_legacy.py`).
- **PDF / MD / TXT للمحاضرة** ← زرار "📖 اشرح المحاضرة" ← أسئلة سريعة (تتخطّى) ← تقسيم لمحاور ومواضيع ← شرح ← ملزمة PDF.

## مفاتيح شرح المحاضرات
أولوية: `GEMINI_KEYS_PDF` (الملزمة) الأول، ولو كلها اتستهلكت/اتحجبت مؤقتاً بيكمّل بـ `GEMINI_KEYS` (المواضيع) تلقائياً.
الموديلات (بالترتيب، غير المتاح بيتشال عند الفحص): `GEMINI_MODELS_LECTURE` (افتراضي `gemini-3.8-flash, gemini-3.5-flash, gemini-2.5-pro, gemini-2.5-flash`).

## متغيرات اختيارية
`NOTES_CONTEXT=compact|full` `NOTES_MAX_CALLS=40` `VALIDATE_MODE=lenient|strict` `COVERAGE_PASS=0|1` `ANSWERS_AT_END=0|1`

## اختبار
    pip install reportlab aiohttp aiogram pypdf pytest
    python -m pytest tests -q

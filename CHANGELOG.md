# CHANGELOG — مسار الملزمة بالـ markers (SPEC_markers_to_pdf.md)

المراحل 1–3 اتنفذت واتختبرت. **المرحلة 4 (واجهة البوت §10) ما اتنفذتش** — اختيارية في الـ spec، و`bot.py` ما اتلمسش.

## اللي اتضاف / اتغيّر
- `markers.py` (جديد): lexer + parser + dataclasses + validator + ledger + trim/merge helpers. دوال نقية، `parse()` ما بيرميش.
- `md_prep.py` (جديد): md ← أسطر `[Lnnn]`، `coverage_report`, `build_meta`.
- `notes.py`: `generate_units()` (محرك وحدات بالـ ledger) + دوال الـ SRT القديمة محفوظة (`generate_notes` بنفس السلوك).
- `pipeline.py`: `make_pdf(..., mode=)` + `make_pdf_lecture()`؛ مسار SRT القديم هو الافتراضي (`NOTES_MODE=srt`).
- `config.py`: `NOTES_MODE, NOTES_CONTEXT, NOTES_MAX_CALLS, VALIDATE_MODE, COVERAGE_PASS, ANSWERS_AT_END, ENABLE_WARMUP`.
- `store.py`: `save_job/load_job/delete_job` + `redact()` (بيشيل أي سر معروف من أي حالة بتتحفظ).
- `lecture_to_pdf.py`: parser بقى غلاف فوق `markers.py` (API القديم `parse/validate/build_pdf/main` شغال)، وعناصر §9 كلها.
- `gemini_client.py`: **تعديل أمني صغير** — `labels` كانت بتحط آخر 4 حروف من كل مفتاح في الـ logs؛ بقت `G1, G2…` (R-01).
- `fonts/README.md` + `IBMPlexSansArabic-{Regular,Bold}.ttf` + `OFL.txt` (OFL 1.1، إعادة التوزيع مسموحة).
- `tests/` (39 اختبار)، `sample_out/sample.pdf`.

## قرارات على نقاط غامضة (الأشد صرامة غالباً)
1. **برومبت المنتج `lecture_explainer_prompt.md` ما كانش في الملفات.** عقد `RESUME/REPAIR/CHECK_COVERAGE` منفّذ من ناحية الكود حرفياً، لكن سلوك الموديل غير مجرَّب. المسار بيفشل برسالة عربي واضحة لو `prompts/lecture_explainer_prompt.md` مش موجود.
2. **ترتيب العرض لو الخطة ناقصة:** المحتوى = آخر نسخة كاملة، والترتيب = أول ظهور للمفتاح (عشان REPAIR يستبدل في مكانه).
3. **`cases` مفقود في AXIS_PLAN = حالة واحدة متوقعة؛ `cases=-` = صفر.** الـ wrap دايماً متوقع للمحور المخطط.
4. **امتدادات في الاستكمال (R-15):** سطر عادي بعد `BUL/NUM/CASE_PEARL` وبعد `ABOUT/LOGIC/AXIS_INTRO/BIGPICTURE/HY` بيتضاف كاستكمال (مرة تحذير لكل وحدة) بدل ما يتشال، عشان "مفيش حاجة كتبها الموديل تضيع".
5. **DEF بحقلين (legacy)** = `term_en | definition` (مش `term_ar`).
6. **تداخل/فجوات المصدر (§6):** محسوبة على اتحاد الـ ranges (مش "المتتالية" فقط)، وبتطلع مدى دقيق.
7. **trim (R-42)** بيحتفظ كمان بـ `AXIS_START/AXIS_INTRO/WARMUP` اللي بعد آخر وحدة كاملة مباشرة (إطار المحور اتكتب والوحدة الأولى اتقطعت). إعادة `AXIS_START` بتصفّر الإطار فمفيش تكرار.
8. **ذيل المستند (HIGHYIELD/BIGPICTURE/FINAL):** لو الموديل كتبه بدري واتقص بيتحفظ ويتلصق لما الوحدات تخلص. لو مش موجود: **استدعاء واحد** بـ `next=tail`، وبعدها `@@FINAL` مصنّع (R-41).
9. **بدون خطة (`plan_present=False`)** + `@@FINAL` + مفيش تقدم = إنهاء بسبب `no_plan_final` (انحراف عن R-41 الحرفي، لأن مفيش وحدات متوقعة نعرف إنها ناقصة).
10. **بعد stall (4):** REPAIR للوحدات البنيوية + **أول وحدة ناقصة بس** (محاولتين)، مش كل الناقص (كان بيستنزف 20+ استدعاء).
11. **`@@P نص` من غير `|`** مش marker (R-11 الحرفي) فبيتعامل كسطر عادي.
12. **المفاتيح keyed غير حساسة لحالة الحروف** (`Title=` = `title=`) وأي مفاتيح مش معروفة بتتخزن من غير تحذير (`time=`, `est_pages=`).
13. **ألوان الأقسام الدلالية:** WARN أحمر-عنابي `#B42318`، EMPH برتقالي `#B94E0A`، RED `#7A1020` بإطار أتخن. كلها ≥ 4.5:1 (اختبار).
14. **FlowChart/WHY دايماً RTL** (الخطوة 1 يمين، السهم شمال) حتى لو الخطوات إنجليزي، تماشياً مع اتجاه الوثيقة.
15. **ANSWERS_AT_END:** الإجابات في صفحة لكل محور، وروابط الصفحة في الاتجاهين.
16. **ذات اللون:** المحور الضمني (legacy) بيحتفظ بلون لكل موضوع زي قبل كده.
17. **bidi:** أضفت قاعدتين لمحرك الـ reorder: `رقم + مسافة + كلمة لاتينية` (3.5 g/day) و`رقم + علامة لاصقة` (40%، 4+) = LTR run واحد. (باقي المنطق زي ما هو.)

## تغيّرات سلوك مقصودة (الـ spec يكسب)
- موضوع من غير `DONE` **ما بيتعرضش** في الـ PDF (كان بيتعرض).
- `@@NAME نص` من غير `|` اتشال.
- ألوان `ACCENTS` من الثالث لقدام اتغيّرت (أول اتنين محفوظين).
- إيموجي ورموز مش في الخط بتتشال بدل ما تظهر tofu، وبتتجمع في ⚠ واحد.

## حدود معروفة
- المرحلة 4 (بوت) مش موجودة؛ `store.save_job/load_job` وجاهزين لو حبيت توصّلها.
- `lecture_explainer_prompt.md` مش متضمَّن (انظر 1).
- DEF/DRUG/CASE مش بتتقسم بين صفحتين (قصيرة بطبيعتها)؛ حالة طويلة جداً ممكن تسيب فراغ.
- الأخطاء وقت الرسم (draw) مش بتتلقط، بس أخطاء بناء البلوك (R-76).
- `src_covered` في الـ FINAL المصنّع بصيغة `عدد/إجمالي`.
- مختبر بـ Python 3.12 وReportLab المثبّت في البيئة؛ ما اختبرتش 3.10 فعلياً (الكود مفيهوش syntax أحدث منه).
- الخط الافتراضي المضمّن IBM Plex Sans Arabic؛ Cairo/Tajawal غير مضمّنين (شوف `fonts/README.md`). Tajawal الثابت ناقصه U+FE8D فبيترفض تلقائياً.

## دمج الشرح مع البوت القديم (النسخة النهائية)
- `bot.py`: زرار inline "📖 اشرح المحاضرة" لما تبعت PDF/MD/TXT + أسئلة META (7 أسئلة + تسخين، كلها بتتخطّى) + زرار "كمّل من حيث وقفت". مسار الصوت متغيّرش.
- `pipeline.py`: مجمّع `gem_l` (مفاتيح الملزمة tier 0 ثم المواضيع tier 1)؛ مسار الـ SRT بيستخدم `lecture_to_pdf_legacy.py` (القديم).
- `gemini_client.py`: `tiers` للأولوية + دعم مرفقات PDF inline.
- `lecture_in.py` (جديد): قراءة md/txt/pdf (pdftotext ← pypdf ← نسخ Gemini للـ PDF المصوّر/العربي المقلوب).
- `prompts/lecture_explainer_prompt.md` (جديد): برومبت الشرح مكتوب على قواعد `markers.py`.
- تقسيم المحاضرة على المفاتيح: خطة واحدة (`PLAN_ONLY`) ← كل محور بمهمة مستقلة بالتوازي (مفتاح لكل محور، سياقه أسطر المحور بس) ← دمج ← استدعاء واحد للذيل/النواقص. `LECTURE_SPLIT=0` يرجّع التتابع، `LECTURE_PARALLEL=N` يحدد عدد المهام المتوازية.
- `.github/workflows/build-telegram-bot-api.yml`: workflow بناء السيرفر المحلي ورفعه في Releases (tba-latest).

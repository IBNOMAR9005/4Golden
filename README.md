# fonts/ — خطوط الـ PDF

ReportLab بيحتاج TTF **ثابتة (static)**؛ الـ variable fonts بيتجاهلها المحرك وبيطبع ⚠.
المحرك بيدوّر هنا أول حاجة (وبعدين مجلدات النظام) بالترتيب ده:

| الدور | الأسماء (بالظبط، `.ttf`) | المصدر (OFL) |
|---|---|---|
| عربي (الأفضلية 1) | `Cairo-Regular.ttf` + `Cairo-Bold.ttf` | fonts.google.com/specimen/Cairo (static instances) |
| عربي (2) | `IBMPlexSansArabic-Regular.ttf` + `IBMPlexSansArabic-Bold.ttf` | github.com/IBM/plex — **متضمّن هنا** |
| عربي (3) | `Tajawal-Regular.ttf` + `Tajawal-Bold.ttf` | fonts.google.com/specimen/Tajawal (ملاحظة: ناقصه حرف الألف المنفصل U+FE8D، فالمحرك بيرفضه تلقائياً) |
| عربي (fallback) | `NotoNaskhArabic-Regular/Bold.ttf`, `Amiri-Regular/Bold.ttf` | Google Fonts |
| لاتيني مساعد | `IBMPlexSans-Regular/Bold.ttf`, `Inter-Regular/Bold.ttf`, `SourceSans3-Regular/Bold.ttf` | Google Fonts |

لو الخط الوحيد اللي معاك variable (مثلاً `Cairo[slnt,wght].ttf`) اعمل static بنفسك:

    pip install fonttools
    fonttools varLib.instancer "Cairo[slnt,wght].ttf" wght=400 -o Cairo-Regular.ttf
    fonttools varLib.instancer "Cairo[slnt,wght].ttf" wght=700 -o Cairo-Bold.ttf

لو الخط العربي المفضّل مش موجود المحرك بيكمل بأي خط في القايمة وبيطبع سطر ⚠ واحد باسم الملف الناقص.
`IBMPlexSansArabic-*.ttf` و`OFL.txt` متضمّنين هنا بترخيص SIL OFL 1.1 (إعادة التوزيع مسموحة).

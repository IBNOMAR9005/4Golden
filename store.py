# -*- coding: utf-8 -*-
"""حالة صغيرة على Drive (تفضل بعد ما Colab يفصل): تفضيلات المستخدم + سجل استهلاك مفاتيح Groq."""
import json, os, re, threading

_PATTERNS = [re.compile(p) for p in (r'\b\d{8,10}:[A-Za-z0-9_-]{30,}\b', r'AIza[A-Za-z0-9_-]{20,}', r'gsk_[A-Za-z0-9]{20,}')]
_SECRET_ENVS = ('BOT_TOKEN', 'GEMINI_KEYS', 'GEMINI_KEYS_PDF', 'GROQ_KEYS')


def _env_secrets():
    out = []
    for n in _SECRET_ENVS:
        for x in re.split(r'[,\n;\s]+', os.environ.get(n, '') or ''):
            if len(x) >= 8:
                out.append(x)
    return out


def redact(text):
    """يشيل أي سر معروف (من متغيرات البيئة أو شكله) من أي نص قبل ما يتسجل/يتحفظ (R-01)."""
    if not isinstance(text, str):
        return text
    for sec in _env_secrets():
        text = text.replace(sec, '[REDACTED]')
    for p in _PATTERNS:
        text = p.sub('[REDACTED]', text)
    return text


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {'prefs': {}, 'groq_ledger': {}}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding='utf-8') as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            tmp = self.path + '.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def prefs(self, uid):
        p = self.data['prefs'].setdefault(str(uid), {})
        p.setdefault('lang', 'ar')
        p.setdefault('fmt', 'srt')
        p.setdefault('topics', True)
        return p

    # ── حالة وظيفة الملزمة (R-49): ملف JSON لكل job، من غير مفاتيح ولا توكنز ──
    def _job_dir(self, job_id):
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(job_id))
        return os.path.join(os.path.dirname(self.path), 'jobs', safe)

    def save_job(self, job_id, state, lines=None):
        d = self._job_dir(job_id)
        os.makedirs(d, exist_ok=True)
        clean = json.loads(redact(json.dumps(state, ensure_ascii=False)))
        with self.lock:
            for name, obj in (('state.json', clean), ('lines.json', lines)):
                if obj is None:
                    continue
                tmp = os.path.join(d, name + '.tmp')
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(redact(json.dumps(obj, ensure_ascii=False)))
                os.replace(tmp, os.path.join(d, name))

    def load_job(self, job_id):
        d = self._job_dir(job_id)
        try:
            with open(os.path.join(d, 'state.json'), encoding='utf-8') as f:
                state = json.load(f)
        except (OSError, ValueError):
            return None, None
        try:
            with open(os.path.join(d, 'lines.json'), encoding='utf-8') as f:
                lines = json.load(f)
        except (OSError, ValueError):
            lines = None
        return state, lines

    def delete_job(self, job_id):
        import shutil
        shutil.rmtree(self._job_dir(job_id), ignore_errors=True)

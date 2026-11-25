# -*- coding: utf-8 -*-
import asyncio, contextlib, io, os, sys
import markers as M, notes, md_prep
import lecture_to_pdf as L
from store import Store, redact
from gemini_client import GeminiPool
from test_notes import FakePool, FULL, cut_before

FAKE = {'BOT_TOKEN': '1234567890:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE12',
        'GEMINI_KEYS': 'AIzaFAKEKEYONEFAKEKEYONE1234567,AIzaFAKEKEYTWOFAKEKEYTWO7654321',
        'GEMINI_KEYS_PDF': 'AIzaFAKEPDFKEYFAKEPDFKEY0001111',
        'GROQ_KEYS': 'gsk_FAKEGROQKEYFAKEGROQKEY99999'}
SECRETS = [FAKE['BOT_TOKEN']] + FAKE['GEMINI_KEYS'].split(',') + [FAKE['GEMINI_KEYS_PDF'], FAKE['GROQ_KEYS']]


def test_secrets_never_printed(tmp_path, monkeypatch, capsys):
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    out_pdf = str(tmp_path / 'o.pdf')
    leaky = FULL.replace('@@FINAL', '@@NOTE | ' + FAKE['GEMINI_KEYS'].split(',')[0] + '\n@@FINAL', 1)   # موديل بيهلوس مفتاح
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        L.parse(leaky)
        M.validate(M.parse(leaky), 60)
        pool = FakePool([cut_before(FULL, '@@TOPIC_START | id=4'), FULL[FULL.index('@@TOPIC_START | id=4'):]])
        st = Store(str(tmp_path / 'store.json'))

        async def ck(acc, led):
            st.save_job('job1', {'acc': acc + '\n' + SECRETS[1], 'done': led.done, 'token': SECRETS[0]},
                        [{'n': 1, 'kind': 'para', 'text': 'x'}])
        res = asyncio.run(notes.generate_units(None, pool, 'sys', 'U', checkpoint=ck, total_lines=60, max_calls=4))
        try:
            L.build_pdf(leaky, out_pdf, None, os.path.join(os.path.dirname(__file__), '..', 'fonts'), total=60)
        except SystemExit:
            pass
        # الـ pool الحقيقي: labels ما فيهاش أي جزء من المفتاح
        gp = GeminiPool(FAKE['GEMINI_KEYS'].split(','), ['m'], 'http://x')
        print(' '.join(gp.labels))
    captured = capsys.readouterr()
    text = buf.getvalue() + captured.out + captured.err
    for sec in SECRETS:
        assert sec not in text
    for tail in (s[-4:] for s in SECRETS):
        assert tail not in ' '.join(gp.labels)
    blob = ''
    for root, _, files in os.walk(str(tmp_path)):
        for f in files:
            if f.endswith('.pdf'):
                continue
            blob += open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
    assert 'REDACTED' in blob
    for sec in SECRETS:
        assert sec not in blob
    assert redact('x ' + SECRETS[2] + ' y') == 'x [REDACTED] y'

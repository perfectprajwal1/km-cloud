#!/usr/bin/env python3
"""Tea-shop reel renderer (test copy). Usage: python tea_reel.py tea_inbox/<ID>/script.txt
Env: GEMINI_KEY (one TTS call), TEA_AUDIO (use this wav instead of calling Gemini), OUT_DIR (default out).
Never posts anything. Writes out/<ID>_tea.mp4 and out/<ID>_tea_report.txt."""
import os, sys, re, json, base64, wave, math, unicodedata, difflib, subprocess as sp, urllib.request, urllib.error, tempfile, shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter, features
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tea_assets')
OUTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outro_final.mp4') if os.environ.get('TEA_OUTRO') == '1' else ''  # outro removed by pk 10-27
VOICES = {'Y': 'Puck', 'U': 'Sadachbia'}
STYLE_PROMPT = ("Speak this as a relaxed, natural conversation in Nepali between two people at a quiet Kathmandu tea shop. "
 "Use clear, warm, conversational delivery at a medium pace. The young man is friendly and curious; the uncle is calm, warm, and matter-of-fact. "
 "Make questions sound naturally inquisitive, not dramatic. Use short pauses between turns and brief pauses at commas. "
 "State numbers clearly without rushing or overemphasizing them. No announcer voice, no theatrical delivery, no echo, no reverb, and no background sounds.")
BOLD = None
for p in ('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public/fonts/Mukta-Bold.ttf')):
    if os.path.exists(p): BOLD = p; break
if not BOLD: print('TEA FAIL: no Devanagari font found'); sys.exit(2)
FONT_WARNINGS = []
HAS_RAQM = features.check_feature('raqm')
if not HAS_RAQM:
    FONT_WARNINGS.append('DEVA SHAPING WARNING: Pillow lacks RAQM; Nepali conjuncts/matras may display incorrectly. Install Pillow with libraqm/HarfBuzz support. Rendering continues with saved voice.')
    print('TEA WARNING:', FONT_WARNINGS[-1], file=sys.stderr)
F = lambda s: ImageFont.truetype(BOLD, s, layout_engine=ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC)
def run(*a): sp.check_call(['ffmpeg', '-v', 'error', '-y'] + list(a))
def dur(f): return float(sp.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).decode())
def fail(m): print('TEA FAIL:', m); sys.exit(2)

def parse(path):
    L = [l.rstrip('\n') for l in open(path, encoding='utf-8')]
    if not L or L[0].strip() != 'STYLE: tea': fail('first line is not STYLE: tea')
    d = {'id': '', 'headline': '', 'lines': [], 'cards': {}, 'warnings': []}
    for l in L[1:]:
        l = l.strip()
        if l.startswith('ID:'): d['id'] = l[3:].strip()
        elif l.startswith('HEADLINE:'): d['headline'] = l[9:].strip()
        elif l[:2] in ('Y:', 'U:'): d['lines'].append((l[0], l[2:].strip()))
        elif l.startswith('CARD'):
            m = re.match(r'CARD\s+(\d+)\s*:\s*(.*)', l)
            if m:
                p = [x.strip() for x in m.group(2).split('|')]
                if len(p) == 3 and all(p):
                    index = int(m.group(1)) - 1
                    if index in d['cards']: d['warnings'].append('Duplicate CARD %d; first valid entry retained' % (index + 1))
                    else: d['cards'][index] = p
                else: d['warnings'].append('Malformed CARD fields ignored: ' + l)
            else: d['warnings'].append('Malformed CARD entry ignored: ' + l)
    if not d['id'] or not d['headline']: fail('ID or HEADLINE missing')
    if len(d['lines']) < 4 or len(d['lines']) > 10: fail('need 4 to 10 dialogue lines')
    if d['lines'][-1][0] != 'Y' and not os.environ.get('TEA_TEST_RELAX'): fail('last line must be the young man asking the question')
    if '?' not in d['lines'][-1][1] and not os.environ.get('TEA_TEST_RELAX'): fail('last line must be a question (has no ?)')
    if any(not t.strip() for _, t in d['lines']): fail('empty dialogue line')
    for index in list(d['cards']):
        if not 0 <= index < len(d['lines']) - 1:
            d['warnings'].append('CARD %d ignored: not a non-final dialogue line' % (index + 1))
            del d['cards'][index]
    for warning in d['warnings']: print('TEA SCRIPT NOTE:', warning)
    return d

def tts(lines, out):
    key = os.environ.get('GEMINI_KEY', '').strip()
    if not key: fail('GEMINI_KEY missing and TEA_AUDIO not set')
    text = STYLE_PROMPT + '\n' + '\n'.join(('Young: ' if s == 'Y' else 'Uncle: ') + t for s, t in lines)
    body = {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
        {"speaker": "Young", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICES['Y']}}},
        {"speaker": "Uncle", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICES['U']}}}]}}}}
    url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent'
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', 'x-goog-api-key': key})
    try: r = json.load(urllib.request.urlopen(req, timeout=240))
    except urllib.error.HTTPError as e: fail('Gemini HTTP %s %s' % (e.code, e.read().decode()[:200].replace(key, '***')))
    except Exception as e: fail('Gemini call failed: ' + type(e).__name__)
    try:
        part = r['candidates'][0]['content']['parts'][0]['inlineData']
        pcm = base64.b64decode(part['data']); mime = part.get('mimeType', '')
    except Exception: fail('Gemini returned no audio')
    m = re.search(r'rate=(\d+)', mime); rate = int(m.group(1)) if m else 24000
    if 'L16' not in mime and 'pcm' not in mime.lower(): fail('unexpected audio type: ' + mime)
    if len(pcm) < rate * 2 * 5: fail('Gemini audio too short')
    with wave.open(out, 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)

def boundaries(wav, lines):
    """Line start times. Snap each char-proportional guess to the best silence gap nearby; report how it was found."""
    total = dur(wav); n = len(lines)
    o = sp.run(['ffmpeg', '-v', 'info', '-i', wav, '-af', 'silencedetect=noise=-38dB:d=0.18', '-f', 'null', '-'], capture_output=True, text=True).stderr
    s = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', o)]; e = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', o)]
    gaps = [((a + b) / 2, b - a) for a, b in zip(s, e) if a > 0.5 and b < total - 0.3]
    w = [len(t) for _, t in lines]; cum = [0]
    for x in w: cum.append(cum[-1] + x)
    bd = [0.0]; used = set(); notes = []
    for i in range(1, n):
        guess = total * cum[i] / cum[-1]; win = total * 0.12
        c = [(g, ln) for g, ln in gaps if abs(g - guess) <= win and g not in used and g > bd[-1] + 0.8]
        if c: g = max(c, key=lambda x: x[1] - abs(x[0] - guess) * 0.5)[0]; used.add(g); bd.append(g); notes.append('gap')
        else: bd.append(guess); notes.append('guess')
    bd.append(total)
    return bd, notes

def wrap(d, t, f, mw):
    L = []; c = ''
    for w in t.split(' '):
        x = (c + ' ' + w).strip()
        if d.textlength(x, font=f) <= mw: c = x
        else: L.append(c); c = w
    L.append(c); return L
def chunks(t, maxc=36):
    out = []; c = ''
    for w in t.split(' '):
        if len((c + ' ' + w).strip()) > maxc and c: out.append(c); c = w
        else: c = (c + ' ' + w).strip()
        if c.endswith((',', '।', '?', '!')) and len(c) >= 12: out.append(c); c = ''
    if c: out.append(c)
    return out
def speech_gaps(wav):
    o = sp.run(['ffmpeg', '-v', 'info', '-i', wav, '-af', 'silencedetect=noise=-35dB:d=0.10', '-f', 'null', '-'], capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r'silence_start: ([0-9.]+)', o)]; en = [float(x) for x in re.findall(r'silence_end: ([0-9.]+)', o)]
    return [(a, b) for a, b in zip(st, en) if b > a]
def chunk_times(cs, a, b, gaps):
    # speech-only timeline of this line: letters are spread over the time the voice is really speaking, then snapped to real pauses
    g = [(max(x, a), min(y, b)) for x, y in gaps if y > a and x < b and min(y, b) > max(x, a)]
    segs = []; p = a
    for x, y in sorted(g):
        if x > p: segs.append((p, x))
        p = max(p, y)
    if p < b: segs.append((p, b))
    S = sum(e - s_ for s_, e in segs) or (b - a)
    def at(sec):
        for s_, e in segs:
            if sec <= e - s_: return s_ + sec
            sec -= e - s_
        return b
    tot = sum(len(c) for c in cs); cum = 0; starts = [a]
    for c in cs[:-1]:
        cum += len(c); t = at(S * cum / tot)
        near = [(abs((x + y) / 2 - t), (x + y) / 2) for x, y in g if abs((x + y) / 2 - t) <= 0.6]
        starts.append(min(near)[1] if near else t)
    starts = sorted(starts); starts[0] = a
    return starts + [b]
def cap_png(name, t, y=420, speaker='Y'):
    # Two-row tea-house caption pill with a speaker accent bar; safe width keeps the right UI gutter clear.
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    f, rows, size = text_rows(d, t, 44, 760, 2, 34)
    heights = [size + 10] * len(rows); h = sum(heights) + 22
    widths = [d.textlength(row, font=f) for row in rows]
    w = min(832, max(widths, default=0) + 66)
    x0 = (1080 - w) / 2; x1 = x0 + w
    accent = (194, 83, 55, 255) if speaker == 'Y' else (206, 163, 98, 255)
    d.rounded_rectangle((x0, y, x1, y + h), radius=24, fill=(30, 25, 22, 220), outline=(250, 235, 207, 80), width=2)
    d.rounded_rectangle((x0 + 9, y + 13, x0 + 15, y + h - 13), radius=3, fill=accent)
    yy = y + 11
    for row, row_h, row_w in zip(rows, heights, widths):
        d.text(((1080 - row_w) / 2, yy), row, font=f, fill=(255, 248, 232, 255))
        yy += row_h
    im.save(name)
def text_rows(d, text, size, width, max_rows, minimum=28):
    for sz in range(size, minimum - 1, -2):
        font = F(sz); rows = wrap(d, text, font, width)
        if len(rows) <= max_rows and all(d.textlength(row, font=font) <= width for row in rows):
            return font, rows, sz
    fail('text does not fit the mobile safe area')

def card_png(name, label, value, sub):
    # Transparent, compact fact panel. The scene and both characters remain visible around it.
    def currency_text(text):
        text = re.sub(r'£\s*([0-9०-९][0-9०-९,.]*)', r'\1 पाउण्ड', text)
        return text.replace('£', 'पाउण्ड')
    label, value, sub = [currency_text(text) for text in (label, value, sub)]
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
    shadow = Image.new('RGBA', im.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(shadow)
    box = (60, 492, 940, 992)
    sd.rounded_rectangle((box[0] + 10, box[1] + 16, box[2] + 10, box[3] + 16), radius=34, fill=(20, 13, 10, 125))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(im); ink = (67, 39, 28, 255); red = (168, 57, 35, 255); paper = (255, 243, 216, 247)
    d.rounded_rectangle(box, radius=34, fill=paper, outline=(255, 251, 237, 245), width=3)
    d.rounded_rectangle((box[0], box[1], box[2], box[1] + 72), radius=34, fill=red)
    d.rectangle((box[0], box[1] + 38, box[2], box[1] + 72), fill=red)
    d.text((96, 507), 'खबर मिनेट', font=F(36), fill=(255, 243, 216, 255))
    # Small drawn cup mark echoes the tea-shop illustration without adding an emoji.
    d.arc((850, 512, 889, 548), 250, 100, fill=(255, 243, 216, 255), width=4)
    d.rounded_rectangle((820, 513, 862, 550), radius=8, outline=(255, 243, 216, 255), width=4)
    d.line((813, 558, 874, 558), fill=(255, 243, 216, 255), width=4)
    for x in (827, 841, 855): d.line((x, 488, x - 3, 502), fill=(255, 243, 216, 255), width=2)
    label_font, labels, label_size = text_rows(d, label, 36, 780, 2, 30)
    y = 582
    for row in labels:
        d.text((94, y), row, font=label_font, fill=ink); y += label_size + 5
    unit = 'पाउण्ड' if value.endswith(' पाउण्ड') else '%' if value.endswith('%') else ''
    main_value = value[:-len(unit)].strip() if unit else value
    # Long values must never touch the divider at y=872: shrink and place so the block (incl. unit) ends by 856.
    value_font = values = value_size = value_y = None
    for size_try in range(100 if unit else 104, 43, -2):
        f_try = F(size_try); rows_try = wrap(d, main_value, f_try, 790)
        if len(rows_try) > 2 or any(d.textlength(row, font=f_try) > 790 for row in rows_try): continue
        block = len(rows_try) * (size_try + 4) + (36 if unit else 0)
        y_try = min(735, max(670, 838 - block))
        if y_try + block <= 856:
            value_font, values, value_size, value_y = f_try, rows_try, size_try, y_try
            break
    if value_font is None: fail('card value does not fit the panel without touching the divider')
    for row in values:
        w = d.textlength(row, font=value_font)
        d.text(((1080 - w) / 2, value_y), row, font=value_font, fill=red)
        value_y += value_size + 4
    if unit:
        unit_font = F(34); w = d.textlength(unit, font=unit_font)
        d.text(((1080 - w) / 2, value_y + 2), unit, font=unit_font, fill=ink)
    d.line((94, 872, 906, 872), fill=(205, 178, 145, 255), width=2)
    sub_font, subs, sub_size = text_rows(d, sub, 30, 780, 2, 26)
    y = 888
    for row in subs:
        d.text((94, y), row, font=sub_font, fill=ink); y += sub_size + 2
    im.save(name)

def _text_rows_soft(d, text, size, width, max_rows, minimum):
    for sz in range(size, minimum - 1, -2):
        font = F(sz); rows = wrap(d, text, font, width)
        if len(rows) <= max_rows and all(d.textlength(row, font=font) <= width for row in rows):
            return font, rows, sz
    raise ValueError('text does not fit the safe area')
def headline_png(name, t):
    # Headline stays below the top UI band and inside the right-side 120px gutter.
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    try:
        f, rows, size = _text_rows_soft(d, t, 48, 790, 2, 42)  # preferred: large, at most two rows
    except ValueError:
        f, rows, size = text_rows(d, t, 48, 790, 3, 30)
    h = 38 + len(rows) * (size + 12) + 18
    x0, y0, x1 = 72, 190, 936
    d.rounded_rectangle((x0, y0, x1, y0 + h), radius=26, fill=(35, 27, 23, 224), outline=(255, 243, 216, 80), width=2)
    d.rounded_rectangle((x0, y0 + 18, x0 + 7, y0 + h - 18), radius=4, fill=(194, 83, 55, 255))
    yy = y0 + 18
    for row in rows:
        w = d.textlength(row, font=f)
        d.text(((1080 - w) / 2, yy), row, font=f, fill=(255, 248, 232, 255))
        yy += size + 12
    im.save(name)
AUDIO_NOTES = []

def mix_morning_audio(voice, target, length):
    """Optional audition mix. Asset/mixer failures preserve plain narration."""
    names = ('morning_birds_cleaned_hq.mp3', 'madal_80bpm_hq.mp3', 'bansuri_rag_jog_hq.mp3', 'tea_pour_hq.mp3')
    if not all(os.path.isfile(os.path.join(A, name)) for name in names):
        print('TEA MORNING: assets missing; plain voice'); AUDIO_NOTES.append('Optional sound assets missing; plain voice'); return voice
    try:
        inputs = ['-i', voice, '-stream_loop', '-1', '-i', os.path.join(A, names[0]), '-stream_loop', '-1', '-i', os.path.join(A, names[1]), '-i', os.path.join(A, names[2]), '-i', os.path.join(A, names[3])]
        phrase2 = max(8, min(24, length - 10))
        filters = ['[0:a]aformat=sample_rates=44100:channel_layouts=mono,asplit=2[v][key]',
            f'[1:a]aformat=sample_rates=44100:channel_layouts=mono,atrim=0:{length},volume=-19dB,afade=t=in:d=1[b]',
            f'[2:a]aformat=sample_rates=44100:channel_layouts=mono,atrim=0:{length},volume=-22dB,afade=t=in:d=1.5[m]',
            '[3:a]aformat=sample_rates=44100:channel_layouts=mono,volume=-16dB,afade=t=in:d=0.2,afade=t=out:st=3:d=0.6,asplit=4[f1][f2][f3][f4]',
            '[f1]adelay=4000[fa];[f2]adelay=15000[fb];[f3]adelay=26000[fc];[f4]adelay=37000[fd]',
            '[4:a]aformat=sample_rates=44100:channel_layouts=mono,atrim=0:1.5,afade=t=out:st=1:d=0.5,volume=-14dB[p]',
            f'[b][m][fa][fb][fc][fd][p]amix=inputs=7:normalize=0:duration=longest,atrim=0:{length},afade=t=out:st={max(0,length-1.5)}:d=1.5[bg]',
            '[bg][key]sidechaincompress=threshold=0.025:ratio=3:attack=20:release=250,volume=16dB[duck]',
            f'[v][duck]amix=inputs=2:normalize=0:duration=longest,atrim=0:{length},afade=t=out:st={max(0,length-0.7)}:d=0.7[premix]']
        run(*inputs, '-filter_complex', ';'.join(filters), '-map', '[premix]', '-ar', '44100', '-ac', '1', 'morning_premix.wav')
        analysis = sp.run(['ffmpeg', '-hide_banner', '-i', 'morning_premix.wav', '-af', 'loudnorm=I=-14:TP=-1.5:print_format=json', '-f', 'null', '-'], capture_output=True, text=True, check=True).stderr
        stats = json.loads(analysis[analysis.rindex('{'):]); gain = -14 - float(stats['input_i'])
        run('-i', 'morning_premix.wav', '-af', f'volume={gain}dB,alimiter=limit=0.79:level=disabled', '-ar', '44100', '-ac', '1', target)
        print('TEA MORNING: optional birds, madal, sparse bansuri, opening pour'); return target
    except Exception as error:
        print('TEA MORNING: mix unavailable (' + type(error).__name__ + '); plain voice'); AUDIO_NOTES.append('Optional mixer failed: ' + type(error).__name__ + '; plain voice'); return voice


def _match_key(s):
    # Pronunciation-tolerant normal form for MATCHING ONLY (never displayed): the voice often says a
    # neighbouring spelling of a number word (baunna/bawanna, athchalis/archalis, paintalis variants).
    s = unicodedata.normalize('NFC', str(s)).replace('\u0902', '\u0901').replace('\u094d', '')
    for aspirated, plain in (('\u0916', '\u0915'), ('\u0918', '\u0917'), ('\u091b', '\u091a'), ('\u091d', '\u091c'),
                             ('\u0920', '\u091f'), ('\u0922', '\u0921'), ('\u0925', '\u0924'), ('\u0927', '\u0926'), ('\u092d', '\u092c')):
        s = s.replace(aspirated, plain)
    return s.replace('\u0940', '\u093f').replace('\u0942', '\u0941')

def card_number_start(value, row):
    """(start_seconds, source) for the card's spoken number phrase inside one dialogue line, or None.

    Exact concatenated-letter match first (the original general matcher); then a pronunciation-normalized
    fuzzy match over short word windows, optionally anchored by the unit word from the card value.
    Returns None when no match is clear - the caller keeps the line-start fallback."""
    number = re.search(r'[0-9\u0966-\u096f]+(?:[,\.][0-9\u0966-\u096f]+)*', value)
    if not number: return None
    try:
        from km_ctc import spoken_form, letters
    except Exception:
        return None
    try:
        phrase = spoken_form(number.group())[0].strip()
    except Exception:
        return None
    if not phrase: return None
    try:
        row_letters = [letters(spoken_form(w['word'])[0]) for w in row]
    except Exception:
        return None
    target = letters(phrase)
    position = ''.join(row_letters).find(target) if target else -1
    if position >= 0:
        cursor = 0
        for word, token in zip(row, row_letters):
            if cursor + len(token) > position:
                return word['start'], 'spoken number (exact)'
            cursor += len(token)
    tail = value[number.end():]
    unit = next((u for u in ('\u0932\u093e\u0916', '\u0915\u0930\u094b\u0921', '\u0939\u091c\u093e\u0930',
                             '\u0905\u0930\u094d\u092c', '\u0916\u0930\u094d\u092c',
                             '\u092a\u094d\u0930\u0924\u093f\u0936\u0924',
                             '\u092a\u093e\u0909\u0923\u094d\u0921') if u in tail), None)
    row_keys = [_match_key(token) for token in row_letters]
    attempts = [(phrase.split() + [unit], 0.78, True)] if unit else []
    attempts.append((phrase.split(), 0.90, False))
    best = None
    for target_words, thresh, with_unit in attempts:
        key = _match_key(letters(' '.join(target_words)))
        if len(key) < 4: continue  # too short to trust a fuzzy hit
        for win in range(max(1, len(target_words) - 1), min(len(row), len(target_words) + 1) + 1):
            for pos in range(0, len(row) - win + 1):
                cand = ''.join(row_keys[pos:pos + win])
                if not cand: continue
                r = difflib.SequenceMatcher(None, key, cand).ratio()
                if r >= thresh and (best is None or r > best[0]):
                    best = (r, pos, with_unit)
    if best is not None:
        return row[best[1]]['start'], 'spoken number (fuzzy %.2f%s)' % (best[0], ' + unit' if best[2] else '')
    return None

def audio_timing(wav, lines, cards):
    """Best-effort local timing. Uncertainty never requests a new voice or stops rendering."""
    import hashlib, math
    from pathlib import Path
    root = Path(__file__).resolve().parent
    identity = hashlib.sha256(Path(wav).read_bytes() + json.dumps(lines, ensure_ascii=False).encode()).hexdigest()
    cache = root / 'one_call_voice' / ('tea_alignment_' + identity)
    total = dur(wav)
    warnings = []
    # A monotonic, bounded fallback exists BEFORE importing or running the optional model.
    try:
        fallback, gap_notes = boundaries(wav, lines)
    except Exception as exc:
        weights = [max(1, len(text)) for _, text in lines]
        fallback = [0.0]
        for weight in weights: fallback.append(fallback[-1] + total * weight / sum(weights))
        gap_notes = ['proportional'] * (len(lines) - 1)
        warnings.append('Silence detection unavailable: ' + type(exc).__name__)
    minimum = min(0.25, total / (2 * len(lines)))
    for i in range(1, len(lines)):
        fallback[i] = min(total - (len(lines) - i) * minimum,
                          max(fallback[i - 1] + minimum, fallback[i]))
    fallback[-1] = total
    words = []
    try: gaps = speech_gaps(wav)
    except Exception: gaps = []
    for i, (_, text) in enumerate(lines):
        tokens = text.split()
        times = chunk_times(tokens, fallback[i], fallback[i + 1], gaps)
        for j, word in enumerate(tokens):
            words.append({'line': i, 'word': word, 'start': times[j], 'end': times[j + 1],
                          'score': None, 'source': 'silence/length estimate'})
    match = None
    acoustic_count = 0
    try:
        sys.path.insert(0, str(root / 'scripts'))
        from km_ctc import Engine, normalize, spoken_form, letters, similarity
        engine = Engine(root / 'models' / 'km_nepali_ctc')
        samples, rate, logits, greedy = engine.infer(wav, cache)
        # Unsupported tokens do not prevent supported tokens from being aligned.
        supported = [(j, normalize(w['word'], engine.vocab)) for j, w in enumerate(words)]
        supported = [(j, token) for j, token in supported if token]
        segments, _ = engine.align(logits, len(samples) / rate, [token for _, token in supported])
        if len(segments) != len(supported): raise ValueError('alignment word count mismatch')
        match = similarity(' '.join(spoken_form(text)[0] for _, text in lines), greedy)
        anchors = []
        previous_end = 0.0
        for (j, _), segment in zip(supported, segments):
            start, end, score = map(float, segment[:3])
            words[j]['score'] = score if math.isfinite(score) else None
            if (match >= 0.65 and all(math.isfinite(v) for v in (start, end, score))
                    and 0 <= start < end <= total + 0.02 and start >= previous_end - 0.02 and score >= -4):
                start, end = max(0.0, previous_end, start), min(end, total)
                if end - start > 0.005:
                    anchors.append((j, start, end))
                    previous_end = end
        # Fill only uncertain runs between reliable acoustic anchors. Original voice stays untouched.
        left_index, left_end = -1, 0.0
        for right_index, right_start, right_end in anchors + [(len(words), total, total)]:
            missing = words[left_index + 1:right_index]
            weight = sum(max(1, len(w['word'])) for w in missing)
            cursor = left_end
            for word in missing:
                end = cursor + max(0.0, right_start - left_end) * max(1, len(word['word'])) / max(1, weight)
                word.update(start=cursor, end=end, source='interpolated between acoustic anchors')
                cursor = end
            if right_index < len(words):
                words[right_index].update(start=right_start, end=right_end, source='acoustic')
            left_index, left_end = right_index, right_end
        acoustic_count = len(anchors)
        if not anchors:
            # Low transcript similarity is NOT a license to trust forced word positions.
            for word in words:
                word['source'] = 'silence/length estimate'
            # Restore the silence-aware timing instead of the interpolation above.
            for i, (_, text) in enumerate(lines):
                row = [w for w in words if w['line'] == i]
                times = chunk_times(text.split(), fallback[i], fallback[i + 1], gaps)
                for j, word in enumerate(row): word.update(start=times[j], end=times[j + 1])
        if acoustic_count < len(words):
            warnings.append('%d/%d words use estimated timing; transcript match %.3f; original voice retained' %
                            (len(words) - acoustic_count, len(words), match))
    except Exception as exc:
        warnings.append('Local acoustic timing unavailable: %s; silence/length timing used; original voice retained' % type(exc).__name__)
    rows = [[w for w in words if w['line'] == i] for i in range(len(lines))]
    edges = [0.0] + [(rows[i - 1][-1]['end'] + rows[i][0]['start']) / 2 for i in range(1, len(lines))] + [total]
    for i in range(1, len(lines)):
        edges[i] = min(total - (len(lines) - i) * minimum, max(edges[i - 1] + minimum, edges[i]))
    captions = []
    for i, (_, text) in enumerate(lines):
        cursor = 0; windows = []
        for chunk in chunks(text):
            count = len(chunk.split()); group = rows[i][cursor:cursor + count]
            start = max(edges[i], group[0]['start'] - 0.06)
            end = min(edges[i + 1], group[-1]['end'] + 0.10)
            if end > start: windows.append((chunk, start, end))
            cursor += count
        # Do not overlap successive rolling captions after adding reading padding.
        for j in range(len(windows) - 1):
            chunk, start, end = windows[j]
            windows[j] = (chunk, start, min(end, windows[j + 1][1]))
        captions.append(windows)
    card_starts = {}; card_sources = {}
    for i, (_, value, _) in cards.items():
        if not 0 <= i < len(lines) - 1: continue
        start = max(edges[i], rows[i][0]['start']); source = 'line start (number not matched)'
        found = card_number_start(value, rows[i])
        if found is not None:
            start = max(edges[i], found[0]); source = found[1]
        elif re.search(r'[0-9\u0966-\u096f]', value):
            warnings.append('Card %d number timing not matched; shown from its line start' % (i + 1))
        card_starts[i] = min(max(edges[i], start), max(edges[i], edges[i + 1] - 0.2))
        card_sources[str(i + 1)] = source
    evidence = {'audio_sha256': hashlib.sha256(Path(wav).read_bytes()).hexdigest(),
                'method': 'local acoustic anchors with soft silence/length fallback, not human listening',
                'match': match, 'acoustic_words': acoustic_count, 'estimated_words': len(words) - acoustic_count,
                'warnings': warnings, 'words': words, 'boundaries': edges, 'card_starts': card_starts,
                'card_sources': card_sources}
    for warning in warnings: print('TEA TIMING NOTE:', warning)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / 'tea_timing.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:
        print('TEA TIMING NOTE: optional alignment cache could not be saved')
    return edges, captions, card_starts, evidence

def main():
    os.environ['START_DIR'] = os.getcwd(); script = sys.argv[1]; D = parse(script); rid = D['id']; lines = D['lines']; n = len(lines)
    if os.environ.get('TEA_AUDIO'): os.environ['TEA_AUDIO'] = os.path.abspath(os.environ['TEA_AUDIO'])
    out_dir = os.environ.get('OUT_DIR', 'out'); os.makedirs(out_dir, exist_ok=True)
    W = tempfile.mkdtemp(prefix='tea_'); os.chdir(W)
    script = os.path.abspath(os.path.join(os.environ.get('START_DIR', '.'), script)) if not os.path.isabs(script) else script
    wav = os.environ.get('TEA_AUDIO') or os.path.join(W, 'voice.wav')
    if not os.environ.get('TEA_AUDIO'): tts(lines, wav)
    total = dur(wav)
    if total < 8 or total > 75: fail('voice length %.1fs looks wrong' % total)
    BD, CAPTIONS, CARD_STARTS, TIMING = audio_timing(wav, lines, D['cards']); notes = [TIMING['method']] * (n - 1); TIMING['warnings'].extend(FONT_WARNINGS + D.get('warnings', []))
    Dn = [BD[i + 1] - BD[i] for i in range(n)]
    H0 = 0.3; OPEN = 1.5
    Wd, Yg, Ob, T2 = [os.path.join(A, x) for x in ('wide.mp4', 'young.mp4', 'uncle.mp4', 'two.mp4')]
    TM = os.path.join(A, 'teamaker.mp4')
    OB = Ob; OBMAX = dur(Ob) - 0.05  # forward only, never reversed or looped
    GRADE = "eq=contrast=1.03:saturation=1.05:brightness=0.004,colorbalance=rs=0.02:gs=0.005:bs=-0.02"
    # Gentle restrained push-in on talking shots: 4x upscale then zoompan (~2%/s, cap 6%), centre anchored.
    CR = lambda x: (f"[0:v]crop=405:720:{x}:0,scale=1620:2880:flags=lanczos,"
                    f"zoompan=z='min(1+0.0008*on,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=24,"
                    f"{GRADE},unsharp=5:5:0.8,fps=24,format=yuv420p,tpad=stop_mode=clone:stop_duration=75[v]")
    # Fix 10-27 9:20PM: during uncle lines never cut to the over-the-shoulder clip (young man's mouth moves, looked out of sync); cut to the wide.
    # Shot rules (Luna, 10-27): first young line wide; later young lines alternate his face close-up and the over-the-shoulder shot;
    # uncle line = his close-up (forward only, short), long ones cut to the two-shot or wide and back; a second uncle line in a row
    # opens on the listening shot; final question = over-the-shoulder. Rotation is seeded by the story id so reels differ.
    seed = sum(ord(c) for c in rid)
    plan = [(TM, 0.5, OPEN, 380, True)]
    YF, OTS = (Yg, 690 - 202), (T2, 677)   # (clip, crop x)
    young_n = 0; prev_u = False
    def add(clip, ss, d_, x, loop):
        if d_ >= 0.25: plan.append((clip, ss, d_, x, loop))
    for i, (sp_, t) in enumerate(lines):
        line_plan_start = len(plan)
        dd = Dn[i] if i else H0 + BD[1] - OPEN
        if sp_ == 'Y':
            if i == 0: add(Wd, 3.0, dd, 700, True)
            elif i == n - 1: add(T2, 2.0 + (seed % 3) * 0.5, dd, 677, True)
            else:
                use_face = ((young_n + seed) % 2 == 0); young_n += 1
                if use_face: add(Yg, 0.5 + (seed % 3) * 0.6, dd, YF[1], True)
                else: add(T2, 2.0 + (seed % 4) * 0.4, dd, 677, True)
            prev_u = False
        else:
            ss = 0.3 + ((i + seed) % 3) * 0.3
            if prev_u:  # second uncle line in a row: start on the listening shot, then his face
                lis = min(max(dd * 0.35, 1.5), 3.0); add(Wd, 3.0 + (seed % 3) * 0.5, lis, 700, True)  # wide: nobody's mouth visibly moves
                add(Ob, ss, min(dd - lis, OBMAX - ss), 470, False)
            elif dd <= OBMAX - ss: add(Ob, ss, dd, 470, False)
            else:
                a_ = min(max(dd * 0.45, 1.5), OBMAX - ss); rest = dd - a_; cut = min(max(rest * 0.5, 1.5), 2.8); back = rest - cut
                add(Ob, ss, a_, 470, False)
                add(Wd, 4.0 + (i % 2), cut, 700, True)  # wide only: the over-the-shoulder clip shows the young man talking
                if back > 0.3: add(Ob, min(ss + a_, OBMAX - 0.3), min(back, 0.3 + OBMAX - min(ss + a_, OBMAX - 0.3)), 470, False)
            prev_u = True
        covered = sum(shot[2] for shot in plan[line_plan_start:])
        if dd - covered > 0.001: plan.append((Wd, 4.0, dd - covered, 700, True))
    plan.append((Wd, 5.0, 3.2, 700, True))
    END = H0 + BD[-1] + 3.2 - 0  # voice end + end screen
    # Keep faces unobscured by fact panels: wide scene only just around each card, so speaker
    # close-ups keep their sentence beats before and after the panel.
    windows = []
    for i in CARD_STARTS:
        ws = max(H0 + BD[i], max(OPEN, H0 + CARD_STARTS[i]) - 0.12)
        we = min(H0 + BD[i + 1], H0 + BD[i + 1] - 0.1 + 0.12)
        if we > ws: windows.append((ws, we))
    adjusted = []; elapsed = 0.0
    for src, ss, duration, x, loop in plan[:-1]:
        cuts = sorted(set([elapsed, elapsed + duration] +
                          [t for a, b in windows for t in (a, b) if elapsed < t < elapsed + duration]))
        for a, b in zip(cuts, cuts[1:]):
            if any(start <= (a + b) / 2 < end for start, end in windows):
                adjusted.append((Wd, 3.0, b - a, 700, True))
            else: adjusted.append((src, ss + a - elapsed, b - a, x, loop))
        elapsed += duration
    plan = adjusted + [plan[-1]]
    # Quantize cumulative cuts, not each segment independently, to prevent drift from many card cuts.
    quantized = []; cumulative = 0.0; previous_frame = 0
    for src, ss, duration, x, loop in plan:
        cumulative += duration
        frame = round(cumulative * 24)
        if frame > previous_frame:
            quantized.append((src, ss, (frame - previous_frame) / 24, x, loop))
            previous_frame = frame
    plan = quantized
    segs = []
    for k, (src, ss, d_, x, loop) in enumerate(plan):
        nm = f'g{k}.mp4'
        run(*(['-stream_loop', '3'] if loop else []), '-ss', str(ss), '-i', src, '-t', f'{max(d_, 1 / 24):.3f}', '-filter_complex', ("[0:v]crop=480:720:710:0,scale=1080:1620:flags=lanczos," + GRADE + ",pad=1080:1920:0:150:color=0xf2d39b,setsar=1,unsharp=5:5:0.6,fps=24,format=yuv420p,tpad=stop_mode=clone:stop_duration=75[v]" if k == len(plan) - 1 else CR(x)), '-map', '[v]', '-an', '-preset', 'veryfast', '-crf', '20', nm)
        segs.append(nm)
    final_wide_start = sum(dur(segment) for segment in segs[:-1])
    open('l.txt', 'w').write(''.join(f'file {s}\n' for s in segs)); run('-f', 'concat', '-i', 'l.txt', '-c', 'copy', 'base.mp4')
    ov = []; k = 0
    for i, (s_, text) in enumerate(lines):
        for c, start, end in CAPTIONS[i]:
            a = H0 + start; e = H0 + end; nm = f'cap{k}.png'; k += 1
            cap_png(nm, c, y=1120 if i == n - 1 else 420, speaker=s_)
            if i == n - 1: e = min(e, final_wide_start - 0.05)
            if e > a: ov.append((nm, a, e, 'static'))
    headline_png('hl.png', D['headline']); ov.append(('hl.png', 0.0, OPEN, 'static'))
    for li, (lab, val, sub) in D['cards'].items():
        if 0 <= li < n - 1:
            nm = f'card{li}.png'; card_png(nm, lab, val, sub); ov.append((nm, max(OPEN, H0 + CARD_STARTS[li]), H0 + BD[li + 1] - 0.1, 'card'))
    inp = ['-i', 'base.mp4']; fc = ''; last = '[0:v]'
    for j, (png, a, e, kind) in enumerate(ov, 1):
        if kind == 'card':
            # Smooth entrance/exit: short alpha fade plus a small vertical settle (Codex's look).
            span = e - a; fi = min(0.16, span / 2)
            inp += ['-loop', '1', '-framerate', '30', '-t', f'{span:.3f}', '-i', png]
            y_expr = (f"if(lt(t,{a + fi:.3f}),10*(1-(t-{a:.3f})/{fi:.3f}),"
                      f"if(gt(t,{e - fi:.3f}),-8*(1-({e:.3f}-t)/{fi:.3f}),0))")
            fc += (f'[{j}:v]format=rgba,fade=t=in:st=0:d={fi:.3f}:alpha=1,'
                   f'fade=t=out:st={max(0.0, span - fi):.3f}:d={fi:.3f}:alpha=1,'
                   f'setpts=PTS+{a:.6f}/TB[img{j}];')
            fc += f"{last}[img{j}]overlay=x=0:y='{y_expr}':eval=frame:enable='between(t,{a:.3f},{e:.3f})'[o{j}];"
        else:
            inp += ['-i', png]
            fc += f"{last}[{j}:v]overlay=0:0:enable='between(t,{a:.2f},{e:.2f})'[o{j}];"
        last = f'[o{j}]' 
    run(*inp, '-filter_complex', fc.rstrip(';'), '-map', last, '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', 'vid.mp4')
    ms = int(H0 * 1000)
    run('-i', wav, '-filter_complex', f'[0:a]adelay={ms}|{ms},loudnorm=I=-14:TP=-1.5:LRA=11,apad,aresample=24000[a]', '-map', '[a]', '-t', f'{END:.2f}', '-c:a', 'aac', 'aud.m4a')
    audio = mix_morning_audio('aud.m4a', 'morning_mix.wav', END)
    run('-i', 'vid.mp4', '-i', audio, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-r', '30', '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-shortest', 'main.mp4')
    final = os.path.join(os.environ.get('START_DIR', '.'), out_dir, f'{rid}_tea.mp4')
    if OUTRO and os.path.exists(OUTRO):
        # outro: video-only safe concat (outro audio re-encoded if present, else silence)
        has_a = bool(sp.check_output(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', OUTRO]).strip())
        od = dur(OUTRO)
        a1 = f'[1:a]aresample=44100,aformat=channel_layouts=stereo,apad,atrim=0:{od:.2f}[a1]' if has_a else f'anullsrc=r=44100:cl=stereo,atrim=0:{od:.2f}[a1]'
        run('-i', 'main.mp4', '-i', OUTRO, '-filter_complex',
            '[0:v]scale=1080:1920,fps=30,format=yuv420p,setsar=1[v0];[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];'
            '[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p,setsar=1[v1];' + a1 + ';'
            '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]', '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', 'final.mp4')
        shutil.copy('final.mp4', final)
    else: shutil.copy('main.mp4', final)
    d_out = dur(final); TIMING['warnings'].extend(AUDIO_NOTES)
    open(final.replace('.mp4', '_timing.json'), 'w', encoding='utf-8').write(json.dumps(TIMING, ensure_ascii=False, indent=2))
    rep = [f'id {rid}', f'lines {n}', f'voice seconds {total:.1f}', 'boundaries ' + ' '.join(f'{b:.2f}' for b in BD), 'boundary method ' + ','.join(notes),
           f'outro {"yes" if OUTRO and os.path.exists(OUTRO) else "no (removed)"}', f'final seconds {d_out:.1f}', f'cards {sorted(D["cards"])}']
    rep += ['card %d shown %.2fs (%s)' % (i + 1, H0 + CARD_STARTS[i], TIMING.get('card_sources', {}).get(str(i + 1), '?')) for i in sorted(CARD_STARTS)]
    rep += ['timing note ' + warning for warning in TIMING.get('warnings', [])]
    open(final.replace('.mp4', '_report.txt'), 'w').write('\n'.join(rep) + '\n'); print('\n'.join(rep)); print('TEA OK', final)

if __name__ == '__main__': main()

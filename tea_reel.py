#!/usr/bin/env python3
"""Tea-shop reel renderer (test copy). Usage: python tea_reel.py tea_inbox/<ID>/script.txt
Env: GEMINI_KEY (one TTS call), TEA_AUDIO (use this wav instead of calling Gemini), OUT_DIR (default out).
Never posts anything. Writes out/<ID>_tea.mp4 and out/<ID>_tea_report.txt."""
import os, sys, re, json, base64, wave, subprocess as sp, urllib.request, urllib.error, tempfile, shutil
from PIL import Image, ImageDraw, ImageFont
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tea_assets')
OUTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'outro_final.mp4') if os.environ.get('TEA_OUTRO') == '1' else ''  # outro removed by pk 10-27
VOICES = {'Y': 'Puck', 'U': 'Sadachbia'}
STYLE_PROMPT = ("Speak this as a relaxed, natural conversation in Nepali between two people at a quiet Kathmandu tea shop. "
 "Use clear, warm, conversational delivery at a medium pace. The young man is friendly and curious; the uncle is calm, warm, and matter-of-fact. "
 "Make questions sound naturally inquisitive, not dramatic. Use short pauses between turns and brief pauses at commas. "
 "State numbers clearly without rushing or overemphasizing them. No announcer voice, no theatrical delivery, no echo, no reverb, and no background sounds.")
BOLD = None
for p in ('/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf', 'public/fonts/Mukta-Bold.ttf'):
    if os.path.exists(p): BOLD = p; break
if not BOLD: print('TEA FAIL: no Devanagari font found'); sys.exit(2)
F = lambda s: ImageFont.truetype(BOLD, s)
def run(*a): sp.check_call(['ffmpeg', '-v', 'error', '-y'] + list(a))
def dur(f): return float(sp.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).decode())
def fail(m): print('TEA FAIL:', m); sys.exit(2)

def parse(path):
    L = [l.rstrip('\n') for l in open(path, encoding='utf-8')]
    if not L or L[0].strip() != 'STYLE: tea': fail('first line is not STYLE: tea')
    d = {'id': '', 'headline': '', 'lines': [], 'cards': {}}
    for l in L[1:]:
        l = l.strip()
        if l.startswith('ID:'): d['id'] = l[3:].strip()
        elif l.startswith('HEADLINE:'): d['headline'] = l[9:].strip()
        elif l[:2] in ('Y:', 'U:'): d['lines'].append((l[0], l[2:].strip()))
        elif l.startswith('CARD'):
            m = re.match(r'CARD\s+(\d+)\s*:\s*(.*)', l)
            if m:
                p = [x.strip() for x in m.group(2).split('|')]
                if len(p) == 3: d['cards'][int(m.group(1)) - 1] = p
    if not d['id'] or not d['headline']: fail('ID or HEADLINE missing')
    if len(d['lines']) < 4 or len(d['lines']) > 10: fail('need 4 to 10 dialogue lines')
    if d['lines'][-1][0] != 'Y' and not os.environ.get('TEA_TEST_RELAX'): fail('last line must be the young man asking the question')
    if '?' not in d['lines'][-1][1] and not os.environ.get('TEA_TEST_RELAX'): fail('last line must be a question (has no ?)')
    if any(not t.strip() for _, t in d['lines']): fail('empty dialogue line')
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
def cap_png(name, t):
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im); sz = 50; f = F(sz)
    while d.textlength(t, font=f) > 940 and sz > 30: sz -= 2; f = F(sz)
    w = d.textlength(t, font=f) + 70; y = 1630
    d.rounded_rectangle(((1080 - w) / 2, y, (1080 + w) / 2, y + 92), radius=28, fill=(15, 10, 8, 205))
    d.text(((1080 - d.textlength(t, font=f)) / 2, y + 14), t, font=f, fill=(255, 255, 255, 255)); im.save(name)
def card_png(name, label, value, sub):
    im = Image.new('RGB', (1080, 1920), (54, 38, 28)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((70, 560, 1010, 1360), radius=50, fill=(255, 244, 222), outline=(190, 60, 30), width=10)
    f1 = F(58); w = d.textlength(label, font=f1); d.text(((1080 - w) / 2, 620), label, font=f1, fill=(90, 60, 40))
    s = 96; f2 = F(s); ls = wrap(d, value, f2, 820)
    while len(ls) > 3: s -= 6; f2 = F(s); ls = wrap(d, value, f2, 820)
    y = 760
    for l in ls:
        w = d.textlength(l, font=f2); d.text(((1080 - w) / 2, y), l, font=f2, fill=(190, 45, 25)); y += s + 26
    f3 = F(50); w = d.textlength(sub, font=f3); d.text(((1080 - w) / 2, 1250), sub, font=f3, fill=(90, 60, 40)); im.save(name)
def headline_png(name, t):
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im); fh = F(72)
    ls = wrap(d, t, fh, 900); h = 40 + 100 * len(ls)
    d.rounded_rectangle((60, 300, 1020, 300 + h), radius=30, fill=(15, 10, 8, 215)); y = 325
    for l in ls:
        w = d.textlength(l, font=fh); d.text(((1080 - w) / 2, y), l, font=fh, fill=(255, 255, 255, 255)); y += 100
    im.save(name)
def question_png(name, t):
    parts = [p.strip() for p in re.split(r'(?<=[?।])\s+', t) if p.strip()]
    rows = []
    d0 = ImageDraw.Draw(Image.new('RGB', (10, 10))); fq = F(58)
    for k, p in enumerate(parts):
        for l in wrap(d0, p, fq, 900): rows.append((l, (255, 90, 60, 255) if (k == len(parts) - 1 and len(parts) > 1) else (255, 255, 255, 255)))
    im = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(im); y = 1490
    d.rounded_rectangle((60, y - 30, 1020, y + 105 * len(rows) + 15), radius=36, fill=(15, 10, 8, 225))
    for l, c in rows:
        w = d.textlength(l, font=fq); d.text(((1080 - w) / 2, y), l, font=fq, fill=c); y += 105
    im.save(name)

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
    BD, notes = boundaries(wav, lines); GAPS = speech_gaps(wav)
    Dn = [BD[i + 1] - BD[i] for i in range(n)]
    H0 = 0.3; OPEN = 1.5
    Wd, Yg, Ob, T2 = [os.path.join(A, x) for x in ('wide.mp4', 'young.mp4', 'uncle.mp4', 'two.mp4')]
    TM = os.path.join(A, 'teamaker.mp4')
    OB = Ob; OBMAX = dur(Ob) - 0.05  # forward only, never reversed or looped
    CR = lambda x: f"[0:v]crop=405:720:{x}:0,scale=1080:1920:flags=lanczos,unsharp=5:5:0.8,fps=24,format=yuv420p[v]"
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
    plan.append((Wd, 5.0, 3.2, 700, True))
    END = H0 + BD[-1] + 3.2 - 0  # voice end + end screen
    segs = []
    for k, (src, ss, d_, x, loop) in enumerate(plan):
        nm = f'g{k}.mp4'
        run(*(['-stream_loop', '3'] if loop else []), '-ss', str(ss), '-i', src, '-t', f'{max(d_, 0.2):.3f}', '-filter_complex', CR(x), '-map', '[v]', '-an', '-preset', 'veryfast', '-crf', '20', nm)
        segs.append(nm)
    open('l.txt', 'w').write(''.join(f'file {s}\n' for s in segs)); run('-f', 'concat', '-i', 'l.txt', '-c', 'copy', 'base.mp4')
    ov = []; k = 0
    for i, (s_, t) in enumerate(lines):
        cs = chunks(t); tm = chunk_times(cs, BD[i], BD[i + 1], GAPS)
        for ci, c in enumerate(cs):
            a = H0 + tm[ci]; e = H0 + tm[ci + 1]; nm = f'cap{k}.png'; k += 1; cap_png(nm, c)
            if i < n - 1: ov.append((nm, a, e))   # last line shows as the question card instead
    headline_png('hl.png', D['headline']); ov.append(('hl.png', 0.0, OPEN))
    for li, (lab, val, sub) in D['cards'].items():
        if 0 <= li < n - 1:
            nm = f'card{li}.png'; card_png(nm, lab, val, sub); ov.append((nm, H0 + BD[li] + Dn[li] * 0.4, H0 + BD[li + 1] - 0.1))
    question_png('q.png', lines[-1][1]); ov.append(('q.png', H0 + BD[n - 1], END))
    inp = ['-i', 'base.mp4']; fc = ''; last = '[0:v]'
    for j, (png, a, e) in enumerate(ov, 1):
        inp += ['-i', png]; fc += f"{last}[{j}:v]overlay=0:0:enable='between(t,{a:.2f},{e:.2f})'[o{j}];"; last = f'[o{j}]'
    run(*inp, '-filter_complex', fc.rstrip(';'), '-map', last, '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', 'vid.mp4')
    ms = int(H0 * 1000)
    run('-i', wav, '-filter_complex', f'[0:a]adelay={ms}|{ms},loudnorm=I=-14:TP=-1.5:LRA=11,apad,aresample=24000[a]', '-map', '[a]', '-t', f'{END:.2f}', '-c:a', 'aac', 'aud.m4a')
    run('-i', 'vid.mp4', '-i', 'aud.m4a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-r', '30', '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-shortest', 'main.mp4')
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
    d_out = dur(final)
    rep = [f'id {rid}', f'lines {n}', f'voice seconds {total:.1f}', 'boundaries ' + ' '.join(f'{b:.2f}' for b in BD), 'boundary method ' + ','.join(notes),
           f'outro {"yes" if OUTRO and os.path.exists(OUTRO) else "no (removed)"}', f'final seconds {d_out:.1f}', f'cards {sorted(D["cards"])}']
    open(final.replace('.mp4', '_report.txt'), 'w').write('\n'.join(rep) + '\n'); print('\n'.join(rep)); print('TEA OK', final)

if __name__ == '__main__': main()

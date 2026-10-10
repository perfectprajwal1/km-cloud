#!/usr/bin/env python3
"""
km_cards.py  -  Khabar Minute card renderer (v10)
Renders every card in story.json as a 1080x1920 PNG on the ONE master paper, logo fixed at x90 y200 w184.
Engine: HTML/CSS in your already-installed Edge or Chrome via Playwright (exact Devanagari shaping,
box-decoration-break:clone pills, same CSS as the Remotion templates). No browser download needed.

RUN (Windows, once):
  pip install playwright pillow numpy scipy
  (no "playwright install" needed: it uses Edge; if Edge is missing run:  python -m playwright install chromium)
  Put Mukta-SemiBold.ttf and Mukta-ExtraBold.ttf (Google Fonts, free, OFL) in ./fonts
  Put logo.png (or logo.jpeg: white corners are keyed out automatically) in ./
RUN (every story):
  python km_cards.py story.json                 -> out/<id>/card_01_hook.png ...
  python km_cards.py story.json --guides        -> same, plus platform safe-zone overlays (QA only)
  python km_cards.py story.json --public ../km-remotion/public   -> also copies paper, logo, baked strips for Remotion
  python km_cards.py --sample                   -> writes story.sample.json (SAMPLE, not real news)
Markup in any text: {{text}} = red pill, [[text]] = red text (only use at >= 64 px). Digits auto-convert to Devanagari.
"""
import argparse, html, json, os, re, shutil, sys
from pathlib import Path

W, H = 1080, 1920
PAPER, INK, GREY, RED = "#ECE7DC", "#1E1C1A", "#5A5650", "#B80000"
DEV = str.maketrans("0123456789", "०१२३४५६७८९")

# ---------------------------------------------------------------- paper (exact v9 recipe)
def make_paper(path, seed=2083, base=(236, 231, 220), mot=3.0, tooth=2.2):
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    rng = np.random.default_rng(seed)
    def octv(s):
        n = ndimage.gaussian_filter(rng.standard_normal((H, W)), s, mode="wrap")
        return n / n.std()
    m = 0.6 * octv(28) + 0.55 * octv(10) + 0.35 * octv(4)
    m = m / m.std() * mot
    t = octv(0.9) * tooth
    out = np.clip(np.array(base)[None, None, :] + (m + t)[..., None], 0, 255)
    Image.fromarray(np.round(out).astype(np.uint8)).save(path)

# ---------------------------------------------------------------- logo (key white corners if no alpha)
def prepare_logo(src, dst):
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.open(src).convert("RGBA")
    if im.getextrema()[3][0] < 255:          # already transparent
        im.save(dst); return im.size
    rgb = im.convert("RGB")
    key = (1, 255, 1)
    for c in [(0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)]:
        if sum(rgb.getpixel(c)) > 600:
            ImageDraw.floodfill(rgb, c, key, thresh=60)
    a = Image.new("L", im.size, 255)
    px, pa = rgb.load(), a.load()
    for y in range(im.height):
        for x in range(im.width):
            if px[x, y] == key: pa[x, y] = 0
    a = a.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    im.putalpha(a); im.save(dst)
    return im.size

# ---------------------------------------------------------------- strip photo duotone (pre-baked, never per frame)
def bake_duotone(src, dst, w=W, h=650):
    from PIL import Image, ImageOps
    im = ImageOps.fit(Image.open(src).convert("L"), (w, h), Image.LANCZOS, centering=(0.5, 0.45))
    im = ImageOps.autocontrast(im, cutoff=1)
    im = im.point(lambda v: max(0, min(255, int((v - 12) * 255 / 228 * 1.0))))
    import numpy as np
    g = np.asarray(im, dtype=float)[..., None] / 255.0
    c0, c1 = np.array([30, 28, 26]), np.array([236, 231, 220])
    out = c0 + (c1 - c0) * (0.5 + (g - 0.5) * 1.1).clip(0, 1)
    Image.fromarray(out.round().astype("uint8")).save(dst)

# ---------------------------------------------------------------- text helpers
def ne(v, decimals=0):
    """number -> Devanagari with Indian grouping (1,25,000); strings: digits converted only."""
    if isinstance(v, (int, float)):
        neg = v < 0; v = abs(v)
        s = f"{v:.{decimals}f}"
        ip, _, fp = s.partition(".")
        if len(ip) > 3:
            head, tail = ip[:-3], ip[-3:]
            head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
            ip = head + "," + tail
        s = ("-" if neg else "") + ip + ("." + fp if fp else "")
        return s.translate(DEV)
    return str(v).translate(DEV)

def rich(t):
    t = html.escape(ne(t or ""))
    t = re.sub(r"\{\{(.+?)\}\}", lambda m: '<span class="pill">' + (m.group(1).replace(" ", "\u00a0") if len(m.group(1)) <= 14 else m.group(1)) + "</span>", t)
    t = re.sub(r"\[\[(.+?)\]\]", r'<span class="red">\1</span>', t)
    return t

# ---------------------------------------------------------------- CSS (mirrors remotion/src/theme.ts)
CSS = """
@font-face{font-family:Mukta;font-weight:600;src:url('FONTDIR/Mukta-SemiBold.ttf')}
@font-face{font-family:Mukta;font-weight:800;src:url('FONTDIR/Mukta-ExtraBold.ttf')}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1920px;overflow:hidden}
body{font-family:Mukta,sans-serif;letter-spacing:0;color:#1E1C1A;position:relative;font-kerning:normal;
     font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.bg{position:absolute;inset:0;width:1080px;height:1920px}
.dark .bg{display:none} body.dark{background:#1E1C1A;color:#ECE7DC}
.logo{position:absolute;left:90px;top:200px;width:184px}
.sample{position:absolute;right:90px;top:214px;background:#1E1C1A;color:#ECE7DC;font:800 44px/1 Mukta;padding:14px 20px 10px;border-radius:6px}
.dark .sample{background:#ECE7DC;color:#1E1C1A}
.c{position:absolute;left:90px;top:430px;width:720px;height:680px}
.hook{font-weight:800;font-size:104px;line-height:1.30}
.hl{font-weight:800;font-size:84px;line-height:1.32}
.sec{font-weight:600;font-size:48px;line-height:1.35;color:#5A5650}
.dark .sec{color:rgba(236,231,220,.70)}
.kick{font-weight:600;font-size:48px;line-height:1;color:#5A5650;margin-bottom:40px}
.dark .kick{color:rgba(236,231,220,.70)}
.red{color:#B80000}
.dark .red{color:#ECE7DC;box-shadow:inset 0 -16px 0 #B80000}
.pill{background:#B80000;color:#ECE7DC;padding:0 .18em;border-radius:6px;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.gap{height:40px}
.num{font-weight:800;font-size:320px;line-height:1.05;white-space:nowrap}
.num small{font-size:.38em}
.num em{font-style:normal;font-size:.30em}
.rule{width:240px;height:16px;background:#B80000;margin:18px 0 40px}
.vs{display:flex;position:relative;height:470px}
.vs > div{width:360px;padding-right:30px} .vs > div + div{padding-left:40px}
.vs .div{position:absolute;left:360px;top:10px;width:2px;height:440px;background:#1E1C1A;padding:0}
.vv{font-weight:800;font-size:140px;line-height:1.1;white-space:nowrap}
.cal{width:300px;height:380px;border:4px solid #1E1C1A;float:left;margin-right:40px;text-align:center}
.cal .mh{background:#1E1C1A;color:#ECE7DC;font:800 52px/1 Mukta;padding:26px 0 18px}
.cal .d{font:800 200px/1.05 Mukta;color:#B80000;margin-top:6px}
.cal .wd{font:600 44px/1 Mukta;color:#5A5650}
.calhl{font-weight:800;font-size:76px;line-height:1.32;width:560px;margin-left:340px}
.row{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid rgba(90,86,80,.4);padding:22px 0 18px}
.row .l{font:600 48px/1.3 Mukta} .row .v{font:800 64px/1.2 Mukta;white-space:nowrap}
.place{font:800 120px/1.15 Mukta}
.qm{font:800 200px/.8 Mukta;color:#5A5650;margin-left:-30px;height:110px}
.q{font:600 72px/1.36 Mukta}
.who{font:800 48px/1.3 Mukta;margin-top:40px} .role{font:600 44px/1.3 Mukta;color:#5A5650}
.pt{display:flex;gap:28px;margin-top:44px;align-items:flex-start}
.chip{flex:0 0 96px;height:96px;background:#1E1C1A;color:#ECE7DC;font:800 64px/104px Mukta;text-align:center;border-radius:6px}
.pt p{font:600 52px/1.32 Mukta;padding-top:8px}
.old{font:800 140px/1.1 Mukta;color:#5A5650;position:relative;display:inline-block;white-space:nowrap}
.old:after{content:"";position:absolute;left:-6px;right:-6px;top:52%;height:8px;background:#1E1C1A}
.arrow{font:800 64px/1 Mukta;margin:10px 0}
.new{font:800 220px/1.05 Mukta;color:#B80000;white-space:nowrap}
.step{display:flex;gap:24px;align-items:center;margin-top:32px}
.dchip{background:#1E1C1A;color:#ECE7DC;font:800 48px/1 Mukta;padding:16px 18px 10px;border-radius:6px;white-space:nowrap}
.dchip.hi{background:#B80000}
.step p{font:600 48px/1.3 Mukta}
.strip{position:absolute;left:0;top:1270px;width:1080px;height:650px;overflow:hidden;border-top:4px solid #1E1C1A}
.dark .strip{border-top-color:rgba(236,231,220,.3)}
.strip img.fill{width:1080px;height:650px;object-fit:cover;display:block}
.strip img.fit{width:1080px;height:650px;object-fit:contain;display:block}
.tag{position:absolute;left:90px;top:24px;background:#1E1C1A;color:#ECE7DC;font:800 44px/1 Mukta;padding:14px 18px 8px;border-radius:6px}
.echo{position:absolute;left:60px;top:-60px;font:800 760px/1 Mukta;color:rgba(30,28,26,.07);white-space:nowrap}
.dark .echo{color:rgba(236,231,220,.07)}
.lab{position:absolute;font:600 44px/1.2 Mukta}
.labb{position:absolute;font:800 48px/1.2 Mukta}
.guide{position:absolute;background:rgba(0,120,255,.18);outline:2px dashed rgba(0,90,200,.7)}
"""

FIT_JS = """
async () => { await document.fonts.ready;
  for (const el of document.querySelectorAll('[data-fit]')) {           // width fit (numbers)
    const min = +el.dataset.fit; let fs = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > el.parentElement.clientWidth + 1 && fs > min) { fs -= 4; el.style.fontSize = fs + 'px'; } }
  for (const el of document.querySelectorAll('[data-fitbox]')) {        // height fit (headlines)
    const max = +el.dataset.fitbox; let fs = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollHeight > max && fs > 60) { fs -= 2; el.style.fontSize = fs + 'px'; } }
  return true; }
"""

def kick(c):
    return f'<div class="kick">{rich(c["kicker"])}</div>' if c.get("kicker") else ""

def num_html(c, key="value"):
    v = c.get(key)
    s = ne(v, c.get("decimals", 0))
    pre = f'<small>{rich(c["prefix"])} </small>' if c.get("prefix") else ""
    unit = f'<em> {rich(c["unit"])}</em>' if c.get("unit") else ""
    return pre + s + unit

# ---------------------------------------------------------------- card bodies
def body(c):
    t = c["type"]
    if t == "engage":
        question = html.escape(c.get("question", ""))
        cta = html.escape(c.get("cta") or "कमेन्टमा भन्नुस्")
        return (f'<div style="position:absolute;left:90px;top:540px;width:900px;text-align:center">'
                f'<div style="font:800 72px/1.35 Mukta;overflow-wrap:break-word">{question}</div>'
                f'<div style="margin-top:64px"><span style="display:inline-block;background:{RED};color:#ECE7DC;'
                f'font:800 48px/1.3 Mukta;padding:18px 30px 12px;border-radius:16px">{cta}</span></div>'
                '<svg width="80" height="80" viewBox="0 0 24 24" style="margin-top:48px" fill="none" stroke="currentColor" stroke-width="1.7">'
                '<path d="M5 3h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-6 4V5a2 2 0 0 1 2-2z"/>'
                '<circle cx="8" cy="10" r=".7"/><circle cx="12" cy="10" r=".7"/><circle cx="16" cy="10" r=".7"/></svg></div>')
    if t == "hook":
        return kick(c) + f'<div class="hook" data-fitbox="560">{rich(c["headline"])}</div><div class="gap"></div><div class="sec">{rich(c.get("sub",""))}</div>'
    if t == "bignum":
        cls = "num" if c.get("dark") else "num red"
        return (kick(c) + (f'<div class="sec">{rich(c["label"])}</div>' if c.get("label") else "")
                + f'<div class="{cls}" style="color:{"#ECE7DC" if c.get("dark") else RED}" data-fit="180">{num_html(c)}</div>'
                + '<div class="rule"></div>' + f'<div class="hl" style="font-size:64px" data-fitbox="260">{rich(c.get("sub",""))}</div>')
    if t == "versus":
        def side(s):
            col = RED if s.get("hi") else "inherit"
            return f'<div><div class="sec">{rich(s["label"])}</div><div class="vv" style="color:{col}" data-fit="80">{rich(ne(s["value"]))}</div><div class="sec">{rich(s.get("note",""))}</div></div>'
        return (kick(c) + (f'<div class="hl" data-fitbox="230">{rich(c["headline"])}</div><div class="gap"></div>' if c.get("headline") else "")
                + f'<div class="vs">{side(c["left"])}<div class="div"></div>{side(c["right"])}</div>')
    if t == "date":
        return (f'<div class="cal"><div class="mh">{rich(c["month"])} {ne(c.get("year",""))}</div>'
                f'<div class="d">{ne(c["day"])}</div><div class="wd">{rich(c.get("weekday",""))}</div></div>'
                f'<div class="calhl" data-fitbox="380">{rich(c["headline"])}</div><div style="clear:both;height:56px"></div>'
                f'<div class="sec">{rich(c.get("sub",""))}</div>')
    if t == "group":
        rows = "".join(f'<div class="row"><span class="l">{rich(r["label"])}</span><span class="v" style="color:{RED if r.get("hi") else "inherit"}">{rich(ne(r["value"]))}</span></div>' for r in c["rows"][:4])
        return kick(c) + f'<div class="hl" data-fitbox="230">{rich(c["headline"])}</div><div style="height:20px"></div>{rows}'
    if t == "place":
        return (kick(c) + f'<div class="place" data-fit="72">{rich(c["place"])}</div><div class="sec">{rich(c.get("area",""))}</div>'
                + f'<div style="height:56px"></div><div class="hl" data-fitbox="350">{rich(c["headline"])}</div>')
    if t == "quote":
        return (f'<div class="qm">“</div><div class="q" data-fitbox="490">{rich(c["quote"])}</div>'
                f'<div class="who">{html.escape(c["name"])}</div><div class="role">{html.escape(c.get("role",""))}</div>')
    if t == "points":
        pts = "".join(f'<div class="pt"><div class="chip">{ne(i+1)}</div><p>{rich(p)}</p></div>' for i, p in enumerate(c["points"][:3]))
        return kick(c) + f'<div class="hl" style="white-space:nowrap" data-fit="56">{rich(c["title"])}</div>{pts}'
    if t == "change":
        return (kick(c) + f'<div class="sec">{rich(c["label"])}</div><div class="old" data-fit="80">{rich(ne(c["old"]))}</div>'
                f'<div class="arrow">↓</div><div class="new" data-fit="120">{rich(ne(c["new"]))}</div>'
                + (f'<div style="height:20px"></div><span class="pill" style="font:800 48px/1.4 Mukta">{rich(c["delta"])}</span>' if c.get("delta") else ""))
    if t == "next":
        st = "".join(f'<div class="step"><span class="dchip{" hi" if s.get("hi") else ""}">{rich(s["date"])}</span><p>{rich(s["text"])}</p></div>' for s in c["steps"][:3])
        return f'<div class="kick">{rich(c.get("kicker","अब के?"))}</div><div class="hl" data-fitbox="260">{rich(c["headline"])}</div>{st}'
    if t == "scale":
        return (kick(c) + f'<div class="num red" style="font-size:300px" data-fit="160">{rich(ne(c["number"]))}</div>'
                + f'<div class="hl" data-fitbox="240">{rich(c["headline"])}</div><div class="gap"></div><div class="sec">{rich(c.get("sub",""))}</div>')
    raise ValueError(f"unknown card type {t}")

# ---------------------------------------------------------------- strip
def strip(c, idx, assets, dark):
    s = c.get("strip") or {"kind": "echo"}
    k = s.get("kind", "echo")
    if k == "none" or c.get("type") == "engage": return ""
    ink = "#ECE7DC" if dark else INK
    if k == "photo":
        tag = f'<div class="tag">{html.escape(s["label"])}</div>' if s.get("label") else ""
        return f'<div class="strip"><img class="fill" src="{assets["strips"][idx]}">{tag}</div>'
    if k == "graphic":
        return f'<div class="strip"><img class="fit" src="{assets["strips"][idx]}"></div>'
    if k == "bars":
        items = s["items"][:3]; mx = max(float(i["value"]) for i in items) or 1; out = []
        for j, it in enumerate(items):
            y = 40 + j * 84; w = max(8, 490 * float(it["value"]) / mx)
            col = RED if it.get("hi") else ink
            out.append(f'<div class="lab" style="left:90px;top:{y+4}px;width:210px">{rich(it["label"])}</div>'
                       f'<div style="position:absolute;left:320px;top:{y}px;width:{w:.0f}px;height:56px;background:{col}"></div>'
                       f'<div class="labb" style="left:{320+w+14:.0f}px;top:{y+4}px">{rich(ne(it.get("display", it["value"])))}</div>')
        return '<div class="strip">' + "".join(out) + "</div>"
    if k == "dots":
        tot, hi = min(int(s["total"]), 100), int(s["hi"]); out = []
        lab = f'<div class="labb" style="left:90px;top:24px">{rich(s.get("label",""))}</div>'
        for j in range(tot):
            x, y = 90 + (j % 20) * 36, 96 + (j // 20) * 36
            col = RED if j < hi else ink
            op = "1" if j < hi else ".85"
            out.append(f'<div style="position:absolute;left:{x}px;top:{y}px;width:26px;height:26px;border-radius:13px;background:{col};opacity:{op}"></div>')
        return '<div class="strip">' + lab + "".join(out) + "</div>"
    if k == "timeline":
        ticks = s["ticks"][:7]; n = len(ticks); step = 900 / max(1, n - 1); out = [f'<div style="position:absolute;left:90px;top:110px;width:900px;height:4px;background:{ink}"></div>']
        for j, tk in enumerate(ticks):
            x = 90 + j * step
            out.append(f'<div style="position:absolute;left:{x-2:.0f}px;top:100px;width:4px;height:24px;background:{ink}"></div>'
                       f'<div class="lab" style="left:{x-60:.0f}px;top:136px;width:120px;text-align:center">{rich(tk)}</div>')
        at = int(s.get("at", 0)); x = 90 + at * step
        out.append(f'<div style="position:absolute;left:{x-14:.0f}px;top:98px;width:28px;height:28px;border-radius:14px;background:{RED}"></div>')
        if s.get("label"):
            out.append(f'<div style="position:absolute;left:{min(max(x-80,90),760):.0f}px;top:24px"><span class="pill" style="font:800 48px/1.3 Mukta">{rich(s["label"])}</span></div>')
        return '<div class="strip">' + "".join(out) + "</div>"
    txt = s.get("text") or c.get("number") or (ne(c["value"], c.get("decimals", 0)) if "value" in c else "")
    return f'<div class="strip"><div class="echo">{html.escape(ne(txt))}</div></div>'

GUIDES = [  # x, y, w, h : platform UI (approx.), union of TikTok / Reels / Shorts
    (0, 0, 1080, 180), (0, 1440, 1080, 480), (930, 820, 150, 880)]

def page(c, idx, story, assets, guides):
    dark = bool(c.get("dark"))
    g = "".join(f'<div class="guide" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px"></div>' for x, y, w, h in GUIDES) if guides else ""
    samp = '<div class="sample">SAMPLE</div>' if story.get("sample") else ""
    css = CSS.replace("FONTDIR", assets["fonts"])
    if c.get("type") == "engage": css += ".c{left:0;top:0;width:1080px;height:1920px}"
    return (f'<!doctype html><html lang="ne"><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body class="{"dark" if dark else ""}"><img class="bg" src="{assets["paper"]}">'
            f'<img class="logo" src="{assets["logo"]}">{samp}<div class="c">{body(c)}</div>{strip(c, idx, assets, dark)}{g}</body></html>')

# ---------------------------------------------------------------- sample story (SAMPLE: invented, not real news)
SAMPLE = {
  "id": "SAMPLE-001", "sample": True, "voice": "ne-NP-SagarNeural", "rate": "+6%", "pitch": "-2Hz",
  "source_spoken": "नमुना स्रोत",
  "cards": [
    {"type": "hook", "headline": "पेट्रोलको मूल्य {{रु. ५}} ले बढ्यो", "sub": "SAMPLE: नमुना, वास्तविक खबर होइन",
     "vo": "नमुना खबर। पेट्रोलको मूल्य पाँच रुपैयाँले बढेको छ।", "strip": {"kind": "echo", "text": "रु. ५"}},
    {"type": "bignum", "dark": True, "label": "प्रति लिटर नयाँ मूल्य", "prefix": "रु.", "value": 180, "sub": "आज मध्यरातदेखि लागू",
     "vo": "अब एक लिटर पेट्रोलको मूल्य एक सय असी रुपैयाँ पुगेको छ, नमुना स्रोतले जनाएको छ।", "say": "असी",
     "strip": {"kind": "bars", "items": [{"label": "पहिले", "value": 175, "display": "रु. 175"}, {"label": "अब", "value": 180, "display": "रु. 180", "hi": True}]}},
    {"type": "versus", "headline": "डिजेल र पेट्रोल", "left": {"label": "डिजेल", "value": "रु. 165"}, "right": {"label": "पेट्रोल", "value": "रु. 180", "hi": True},
     "vo": "डिजेलको मूल्य भने एक सय पैँसट्ठी रुपैयाँमै स्थिर छ।", "strip": {"kind": "bars", "items": [{"label": "डिजेल", "value": 165, "display": "रु. 165"}, {"label": "पेट्रोल", "value": 180, "display": "रु. 180", "hi": True}]}},
    {"type": "date", "month": "असोज", "year": 2083, "day": 17, "weekday": "शनिबार", "headline": "नयाँ मूल्य लागू", "sub": "मध्यरात १२ बजेदेखि",
     "vo": "नयाँ मूल्य असोज सत्र गते मध्यरातदेखि लागू हुनेछ।", "say": "सत्र", "strip": {"kind": "timeline", "ticks": ["साउन", "भदौ", "असोज", "कात्तिक", "मंसिर"], "at": 2, "label": "१७ असोज"}},
    {"type": "group", "headline": "कसलाई असर?", "rows": [{"label": "मोटरसाइकल", "value": "रु. 50/हप्ता", "hi": True}, {"label": "ट्याक्सी", "value": "रु. 300/हप्ता"}, {"label": "सार्वजनिक बस", "value": "निर्णय बाँकी"}],
     "vo": "हप्तामा दस लिटर चलाउने मोटरसाइकलवालालाई पचास रुपैयाँ थपिन्छ।", "strip": {"kind": "dots", "total": 100, "hi": 23, "label": "१०० मध्ये २३ (SAMPLE)"}},
    {"type": "place", "kicker": "कहाँ", "place": "नमुना नगर", "area": "SAMPLE जिल्ला, प्रदेश", "headline": "डिपोमा {{३ दिन}}को मौज्दात",
     "vo": "नमुना नगरको डिपोमा अहिले तीन दिनलाई पुग्ने मौज्दात छ।", "strip": {"kind": "echo", "text": "३ दिन"}},
    {"type": "quote", "quote": "मूल्य समायोजन [[१५ दिनमा]] फेरि हुन्छ", "name": "नमुना प्रवक्ता", "role": "SAMPLE संस्था",
     "vo": "नमुना प्रवक्ताका अनुसार, मूल्य समायोजन पन्ध्र दिनमा फेरि हुन्छ।", "strip": {"kind": "echo", "text": "“"}},
    {"type": "points", "title": "तीन कुरा", "points": ["अन्तर्राष्ट्रिय मूल्य {{बढेको}}", "भन्सार दर उस्तै", "अर्को समीक्षा १५ दिनमा"],
     "vo": "पहिलो, अन्तर्राष्ट्रिय मूल्य बढेको। दोस्रो, भन्सार दर उस्तै। तेस्रो, अर्को समीक्षा पन्ध्र दिनमा।", "strip": {"kind": "echo", "text": "३"}},
    {"type": "change", "label": "एक लिटरको मूल्य", "old": "रु. 175", "new": "रु. 180", "delta": "+रु. ५",
     "vo": "एक सय पचहत्तरबाट एक सय असी रुपैयाँ।", "strip": {"kind": "bars", "items": [{"label": "पहिले", "value": 175, "display": "रु. 175"}, {"label": "अब", "value": 180, "display": "रु. 180", "hi": True}]}},
    {"type": "scale", "number": "२.९%", "headline": "एकैपटक बढेको मूल्य", "sub": "SAMPLE हिसाब",
     "vo": "यो करिब दुई दशमलव नौ प्रतिशतको वृद्धि हो।", "strip": {"kind": "dots", "total": 100, "hi": 3, "label": "१०० मा करिब ३"}},
    {"type": "next", "headline": "अर्को मूल्य समीक्षा", "steps": [{"date": "कात्तिक 2", "text": "अर्को समीक्षा", "hi": True}, {"date": "कात्तिक 15", "text": "नयाँ आपूर्ति सम्झौता"}],
     "vo": "अर्को मूल्य समीक्षा कात्तिक दुई गते हुनेछ।", "strip": {"kind": "timeline", "ticks": ["असोज", "कात्तिक", "मंसिर"], "at": 1, "label": "कात्तिक २"}},
  ]}

# ---------------------------------------------------------------- main
def launch(p):
    for ch in ("msedge", "chrome", None):
        try:
            return p.chromium.launch(channel=ch) if ch else p.chromium.launch()
        except Exception:
            continue
    sys.exit("No Edge/Chrome found. Run:  python -m playwright install chromium")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story", nargs="?")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fonts", default="fonts")
    ap.add_argument("--logo", default=None)
    ap.add_argument("--paper", default="paper_v9.png")
    ap.add_argument("--guides", action="store_true")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--public", default=None, help="Remotion public/ dir to copy assets into")
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    if a.sample or not a.story:
        Path("story.sample.json").write_text(json.dumps(SAMPLE, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote story.sample.json (SAMPLE)");
        if not a.story: return
    story = json.loads(Path(a.story).read_text(encoding="utf-8"))
    base = Path(a.story).resolve().parent
    out = Path(a.out) / story["id"]; (out / "html").mkdir(parents=True, exist_ok=True)
    paper = Path(a.paper)
    if not paper.exists():
        print("paper_v9.png missing: generating the master once (seed 2083)"); make_paper(paper)
    logo_src = Path(a.logo) if a.logo else next((p for p in [Path("logo.png"), Path("logo.jpeg"), Path("logo.jpg")] if p.exists()), None)
    if not logo_src: sys.exit("put logo.png in this folder")
    logo = out / "logo_keyed.png"; prepare_logo(logo_src, logo)
    strips = {}
    for i, c in enumerate(story["cards"]):
        s = c.get("strip") or {}
        if s.get("kind") in ("photo", "graphic"):
            src = (base / s["src"]).resolve()
            dst = out / f"strip_{i+1:02d}.png"
            bake_duotone(src, dst) if s["kind"] == "photo" else shutil.copy(src, dst)
            strips[i] = dst.resolve().as_uri()
    assets = {"paper": paper.resolve().as_uri(), "logo": logo.resolve().as_uri(),
              "fonts": Path(a.fonts).resolve().as_uri(), "strips": strips}
    files = []
    for i, c in enumerate(story["cards"]):
        f = out / "html" / f"card_{i+1:02d}_{c['type']}.html"
        f.write_text(page(c, i, story, assets, a.guides), encoding="utf-8"); files.append(f)
    if a.public:
        pub = Path(a.public); (pub / "strips").mkdir(parents=True, exist_ok=True)
        shutil.copy(paper, pub / "paper_v9.png"); shutil.copy(logo, pub / "logo.png")
        for i in strips: shutil.copy(out / f"strip_{i+1:02d}.png", pub / "strips" / f"strip_{i+1:02d}.png")
        print("assets copied to", pub)
    if a.html_only:
        print("html written to", out / "html"); return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = launch(p); pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for f in files:
            pg.goto(f.resolve().as_uri()); pg.evaluate(FIT_JS)
            png = out / (f.stem + ".png"); pg.screenshot(path=str(png), full_page=False); print("✓", png)
        b.close()

if __name__ == "__main__":
    main()

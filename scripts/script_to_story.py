#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script_to_story.py - Part 2 of the Khabar Minute one-click tool.
Turns one downloaded script package (inbox/<review_id>/*.txt) into a story file
for the reel renderer: stories/<review_id>.json + strips/ pictures.

  py scripts/script_to_story.py inbox/RV_xxx            (finds the .txt inside)
  Optional: inbox/RV_xxx/visuals.json = {"2": {"visual_kind":"place","places":[...]}, "4": {"visual_kind":"concept","nodes":[...]}}
  py scripts/script_to_story.py inbox/RV_xxx            (you approved it, so it always builds; a RED HOLD only prints a warning)

Bottom-half strips (v2):
  Every graphic strip is written twice:
    1. strip["src"]  -> a still PNG (final frame). Works with the old renderer as before.
    2. strip["anim"] -> a motion spec that src/AnimatedStrip.ts plays in Remotion,
                        timed to the card's own length. Each step/place/word gets an
                        "at" (0..1) = where that word is spoken inside the voice line.
  Strip kinds: stat (count-up number / % ring), concept (2-4 steps), place (pins + route),
  phrase (kinetic key phrase + drawn icon badge), and for number lines whose number the
   TOP half already shows (never drawn twice):
     calendar (a date: the week with that day lifted out in red, weekday if spoken),
     track    (a distance: start -> finish route with ticks, a runner travels it),
     units    (a small count: that many tokens, e.g. 18 district pins),
     waffle   (a percentage: 100 squares, that many turn red).
 v3: all four corner marks red, every drawing scaled and centred to fill the 1080x650 strip.
  Lines with no planner fields are read for real numbers (with a unit) or real Nepal
  place names before falling back to phrase.

No AI, no internet, no API keys. Source name is NEVER written into the story.
"""
import hashlib, html as H, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "public" / "fonts"
DEV = str.maketrans("0123456789", "०१२३४५६७८९")
LAT = str.maketrans("०१२३४५६७८९", "0123456789")
RED = "#B80000"
ON_RED = "#FFF6EA"
W, HGT = 1080, 650

def sec(t, name):
    m = re.search(r"--- " + re.escape(name) + r".*? ---\n(.*?)(?=\n--- |\n=== |\Z)", t, re.S)
    return m.group(1).strip() if m else ""

def head(t, key):
    m = re.search(r"^" + re.escape(key) + r":\s*(.*)$", t, re.M)
    return m.group(1).strip() if m else ""

def load_json(s, what):
    try: return json.loads(s)
    except Exception as e: sys.exit("Cannot read " + what + ": " + str(e))

def num_of(v):
    """'१८' -> 18 ; '८ किलोमिटर' -> None (has unit)"""
    s = v.translate(LAT).replace(",", "").strip()
    return int(s) if re.fullmatch(r"\d{1,9}", s) else None

def pill(text, key):
    """wrap the key word in {{ }} (red pill) if it appears in text"""
    return text.replace(key, "{{" + key + "}}", 1) if key and key in text else text

def first_clause(vo, n=70):
    c = re.split(r"[,।]", vo)[0].strip()
    return c if 6 <= len(c) <= n else vo[:n].rsplit(" ", 1)[0]

# ---------------------------------------------------------------- reading the line
PUNCT = "।,.!?:;\"'‘’“”()[]{}-–—"
SUFFIX = ("", "मा", "को", "का", "की", "ले", "बाट", "सम्म", "मै", "लाई", "भित्र", "तिर", "स्थित", "कै", "देखि")
PLACES = ["काठमाडौं", "काठमाडौँ", "ललितपुर", "भक्तपुर", "पोखरा", "विराटनगर", "धरान", "इटहरी", "बुटवल", "भरतपुर", "चितवन",
          "हेटौंडा", "हेटौडा", "जनकपुर", "वीरगन्ज", "बिरगन्ज", "धनगढी", "नेपालगन्ज", "सुर्खेत", "दाङ", "झापा", "इलाम", "मुस्ताङ",
          "सोलुखुम्बु", "कास्की", "रुपन्देही", "कैलाली", "बाँके", "सिराहा", "सप्तरी", "मोरङ", "सुनसरी", "जुम्ला", "डोल्पा", "हुम्ला",
          "बझाङ", "दार्चुला", "पाल्पा", "गोरखा", "लमजुङ", "स्याङ्जा", "नुवाकोट", "धादिङ", "सिन्धुपाल्चोक", "काभ्रे", "काभ्रेपलाञ्चोक",
          "दोलखा", "रामेछाप", "ओखलढुंगा", "ताप्लेजुङ", "पाँचथर", "संखुवासभा", "भोजपुर", "धनकुटा", "उदयपुर", "महोत्तरी", "सर्लाही",
          "रौतहट", "पर्सा", "मकवानपुर", "नवलपरासी", "कपिलवस्तु", "अर्घाखाँची", "गुल्मी", "प्युठान", "रोल्पा", "रुकुम", "सल्यान",
          "बर्दिया", "जाजरकोट", "दैलेख", "कालिकोट", "मुगु", "अछाम", "डोटी", "बाजुरा", "बैतडी", "डडेलधुरा", "कञ्चनपुर", "म्याग्दी",
          "बाग्लुङ", "तनहुँ", "मनाङ", "रसुवा", "खोटाङ", "तेह्रथुम", "सिन्धुली", "धनुषा", "लुम्बिनी", "कोशी", "मधेश", "बागमती",
          "गण्डकी", "कर्णाली", "सुदूरपश्चिम", "भारत", "चीन", "अमेरिका", "जापान", "कतार", "मलेसिया", "दुबई", "बेलायत", "अस्ट्रेलिया",
          "कोरिया"]
UNITS = ("प्रतिशत", "%", "किलोमिटर", "किमि", "मिटर", "जना", "करोड", "अर्ब", "लाख", "हजार", "रुपैयाँ", "रुपियाँ", "डलर", "घण्टा",
         "दिन", "वर्ष", "महिना", "घर", "परिवार", "मेगावाट", "टन", "केजी", "किलो", "डिग्री", "वटा", "ओटा", "पटक", "सिट", "स्थान", "बिघा", "रोपनी")

def _tokens(text):
    return [w.strip(PUNCT) for w in text.split() if w.strip(PUNCT)]

def _base(tok, names):
    for n in names:
        if tok.startswith(n) and tok[len(n):] in SUFFIX: return n
    return None

def find_places(vo):
    out = []
    for t in _tokens(vo):
        b = _base(t, PLACES)
        if b and b not in [p["ne"] for p in out]: out.append({"ne": b})
    return out[:2]

def find_number(vo):
    """first real number in the line that has a unit after it -> '१८ प्रतिशत' / '५ करोड रुपैयाँ'"""
    toks = _tokens(vo)
    for k, t in enumerate(toks):
        m = re.fullmatch(r"([०-९\d][०-९\d,\.]*)(%?)", t)
        if not m: continue
        lat = m.group(1).translate(LAT).replace(",", "")
        if re.fullmatch(r"(19|20)\d\d", lat): continue           # a year, not a stat
        unit = [m.group(2)] if m.group(2) else []
        for u in toks[k + 1:k + 3]:
            b = _base(u, UNITS)
            if not b: break
            unit.append(b)
        if unit: return (m.group(1) + ("" if unit[0] == "%" else " ") + " ".join(unit)).replace(" %", "%").strip()
    return None

def parse_value(value):
    """'१,२००' / '७२%' / '८ किलोमिटर' / 'रु ५ करोड' -> parts the animation can count."""
    v = value.strip()
    m = re.match(r"^(\D*?)([०-९\d][०-९\d,\.]*)\s*(.*)$", v)
    if not m: return {"prefix": "", "num": None, "numText": v, "unit": "", "decimals": 0, "comma": False, "percent": None}
    pre, n, unit = m.group(1), m.group(2), m.group(3).strip()
    lat = n.translate(LAT).replace(",", "")
    try: x = float(lat)
    except ValueError: x = None
    dec = len(lat.split(".")[1]) if "." in lat else 0
    yearish = x is not None and dec == 0 and re.fullmatch(r"(19|20)\d\d", lat) is not None
    if any(mo in pre + " " + unit for mo in MONTHS): x = None   # 'असोज २४' is a date: never count it up
    pct = x if (x is not None and (unit.startswith("%") or unit.startswith("प्रतिशत")) and 0 < x <= 100) else None
    return {"prefix": pre, "num": None if (x is None or yearish or x > 1e9) else x, "numText": (pre + n).translate(DEV),
            "unit": unit.translate(DEV), "decimals": dec, "comma": "," in n, "percent": pct}

def timeline(vo, words, lo=0.05, hi=0.78, gap=0.07):
    """Where each word is spoken inside the line (0..1). Words not in the line get spread evenly."""
    n = len(words); L = max(1, len(vo)); ats = []; cur = 0
    for w in words:
        j = vo.find(w, cur) if w else -1
        if j < 0 and w: j = vo.find(w)
        if j >= 0: cur = j + len(w)
        ats.append(None if j < 0 else lo + (hi - lo) * j / L)
    for k in range(n):
        if ats[k] is None: ats[k] = lo + (hi - lo) * (k / max(1, n - 1) if n > 1 else 0)
    for k in range(1, n):
        ats[k] = max(ats[k], ats[k - 1] + gap)
    if n and ats[-1] > 0.9:
        sh = ats[-1] - 0.9; ats = [max(lo, a - sh) for a in ats]
    return [round(a, 3) for a in ats]


# ---------------------------------------------------------------- text-only strips (v8)
# For lines with no number and no place: use the line's own structure (who said it, what causes what).
# Every word shown is an exact piece of the narration line; anything else is dropped.
ROLES = ("प्रधानमन्त्री", "अर्थमन्त्री", "मन्त्री", "अर्थसचिव", "सचिव", "निर्देशक", "अध्यक्ष", "उपाध्यक्ष", "प्रवक्ता", "गभर्नर",
         "प्रमुख", "महानिर्देशक", "सहसचिव", "कार्यकारी", "सभापति", "सांसद", "प्रवक्ताले", "अधिकारी", "विज्ञ", "अर्थशास्त्री", "उपप्रधानमन्त्री", "सल्लाहकार", "संयोजक")
SAY = ("बताए", "भने", "भन्", "जोड दिए", "जोड दिएका", "उल्लेख", "दाबी गरे", "स्पष्ट पारे", "आग्रह गरे")
CAUSE = ("दिने", "दिन्छ", "ल्याउने", "ल्याउँछ", "बढाउने", "घटाउने", "निम्त्याउने", "सहयोग पुग्ने", "मद्दत गर्ने", "असर पार्ने", "जन्माउने")
DROP_LEAD = ("र", "गरिएको", "गरेको", "भएको", "यो", "यस", "त्यो", "उक्त")

def _strip_le(t):
    for suf in ("ले", "बाट"):
        if t.endswith(suf) and len(t) > len(suf) + 1: return t[:-len(suf)]
    return t

def _sub(vo, start_tok, end_tok, toks):
    """exact piece of vo from token start_tok to end_tok (inclusive), or ''"""
    if start_tok > end_tok or end_tok >= len(toks): return ""
    a = vo.find(toks[start_tok])
    if a < 0: return ""
    pos = 0; idx = []
    for t in toks:
        j = vo.find(t, pos)
        if j < 0: return ""
        idx.append(j); pos = j + len(t)
    return vo[idx[start_tok]: idx[end_tok] + len(toks[end_tok])]

def plan_evidence(vo, cap):
    toks = vo.split(); hit = []
    for t in (cap or "").replace(",", " ").split():
        t = t.strip("।{}")
        if len(t) < 4: continue
        for base in (t, t[:-1], t[:-2]):
            if len(base) >= 4 and base in vo: hit.append(base); break
    runs = []
    for h_ in hit:
        a = vo.find(h_)
        if a < 0: continue
        e = a + len(h_)
        while e < len(vo) and vo[e] not in " ।,": e += 1
        runs.append([a, e])
    runs.sort(); merged = []
    for a, e in runs:
        if merged and a <= merged[-1][1] + 3: merged[-1][1] = max(merged[-1][1], e)
        else: merged.append([a, e])
    merged = [m for m in merged if m[1] - m[0] <= 40][:2]
    if not merged:
        cs = [(m_.start(), m_.end()) for m_ in re.finditer(r"[^,।]+", vo)]
        if cs:
            a, e = max(cs, key=lambda x: x[1] - x[0])
            seg = vo[a:e].strip(); a = vo.find(seg, a); e = a + len(seg)
            w = seg.split()
            if len(w) > 3:
                tail = " ".join(w[-3:]); a = vo.rfind(tail, a, e + 1); e = a + len(tail)
            if e - a <= 40: merged = [[a, e]]
    parts = []; cur = 0
    for a, e in merged:
        if a > cur: parts.append({"t": vo[cur:a]})
        parts.append({"t": vo[a:e], "hl": True}); cur = e
    if cur < len(vo): parts.append({"t": vo[cur:]})
    return {"kind": "evidence", "parts": parts or [{"t": vo}], "vo": vo}

def _plan_text(vo, cap, st):
    """pick a text-only strip for this line (vo is already canonical). Returns a gen dict or None."""
    order = []
    def safe(fn, *a):
        try: return fn(*a)
        except Exception: return None
    vp = safe(plan_voiceprint, vo)
    if vp: order.append(vp)
    wh = safe(plan_who, vo) if not vp else None
    if wh: order.append(wh)
    ch = safe(plan_chain, vo, st.get("org", ""))
    if ch: order.append(ch)
    for fn in (plan_hook, plan_lawstage, plan_verdict, plan_rule, plan_schedule, plan_movement,
               plan_result, plan_compare, plan_money, plan_contrast, plan_roster, plan_quote, plan_incident):
        g = safe(fn, vo)
        if g: order.append(g)
    order.append(plan_evidence(vo, cap))
    for g in order:
        k = g["kind"]
        if k == st.get("prev"): continue
        if k != "evidence" and st.setdefault("n", {}).get(k, 0) >= 2: continue
        if k == "evidence" and st.setdefault("n", {}).get(k, 0) >= 3: continue
        if k != "evidence" and not (spans_exact(g) and required_ok(g)): continue   # empty/mangled field -> skip, caption fallback
        st["n"][k] = st["n"].get(k, 0) + 1; st["prev"] = k
        if k == "voiceprint": st["org"] = g.get("org", "")
        return g
    st["prev"] = "phrase"
    return None

def plan_text(vo, cap, st):
    """v9.3: plan on the canonical (NFC + matra-fixed) text so keywords match, then hand back spans that are
    exact substrings of the text the viewer sees (vo as given)."""
    canon, cs, ce = _canon(vo)
    cap_c = _canon(cap)[0] if cap else cap
    g = _plan_text(canon, cap_c, st)
    if g is None: return None
    g = _uncanon(g, vo, canon, cs, ce)
    if g["kind"] != "evidence" and not spans_exact(g):
        st["n"][g["kind"]] -= 1; st["prev"] = "phrase"
        return None
    return g

def _ats(vo, texts, lo=0.05, hi=0.85, gap=0.06):
    return timeline(vo, texts, lo=lo, hi=hi, gap=gap)

def strip_chain(g, dark):
    ats = _ats(g["vo"], g["nodes"])
    nodes = [{"ne": n, "at": a} for n, a in zip(g["nodes"], ats)]
    return "", {"kind": "chain", "chain": {"nodes": nodes, "speaker": g.get("speaker", ""), "at": round(min(0.9, ats[0] + 0.08), 3)}}, []

def strip_who(g, dark):
    a = _ats(g["vo"], [g["actor"], g["target"]])
    return "", {"kind": "who", "who": {"actor": g["actor"], "verb": g["verb"], "target": g["target"], "at": a[0]}}, []

def strip_evidence(g, dark):
    hls = [p["t"] for p in g["parts"] if p.get("hl")]
    ats = _ats(g["vo"], hls) if hls else []
    k = 0; parts = []
    for p in g["parts"]:
        q = dict(p)
        if p.get("hl"): q["at"] = ats[k]; k += 1
        parts.append(q)
    return "", {"kind": "evidence", "evidence": {"parts": parts, "at": 0.06}}, []

def strip_voiceprint(g, dark):
    at = _ats(g["vo"], [g["hl"]])[0]
    return "", {"kind": "voiceprint", "voiceprint": {"name": g["name"], "role": g["role"], "parts": g["parts"], "at": at}}, []

# ---------------------------------------------------------------- gap strips v9 (kinds A-M)
# Rule-based detectors for the 13 line kinds the old strips could not show.
# Same discipline: every string returned is an exact span of the line; a detector
# returns None unless everything it needs is really there (evidence stays the fallback).
NUM_RE = r"[०-९0-9]+(?:[.,][०-९0-9]+)*"
MONTH_NAMES = ['जनवरी', 'फेब्रुअरी', 'मार्च', 'अप्रिल', 'मे', 'जुन', 'जुलाई', 'अगस्ट', 'सेप्टेम्बर', 'अक्टोबर', 'नोभेम्बर', 'डिसेम्बर', 'बैशाख', 'वैशाख', 'जेठ', 'असार', 'साउन', 'श्रावण', 'भदौ', 'असोज', 'आश्विन', 'कात्तिक', 'कार्तिक', 'मंसिर', 'मङ्सिर', 'पुस', 'पौष', 'माघ', 'फागुन', 'चैत', 'चैत्र']
# whole-token month names (v9.4): "मे" must not match inside उम्मेदवारी / सदस्य, "पुस" not inside पुस्तक
DATE_RE = None  # set below, after tb() exists
RANK_RE = r"(?:[०-९0-9]+औं|पहिलो|दोस्रो|तेस्रो|चौथो|पाँचौं|छैटौं|सातौं|आठौं|नवौं|दसौं)(?:\s*स्थान)?"

# ---- v9.3 helpers: Devanagari-aware token handling ---------------------------------------
DEVR = "\u0900-\u097F"
CASE_SUF = ("मा", "को", "का", "की", "ले", "बाट", "सम्म", "मै", "लाई", "भित्र", "तिर", "कै", "देखि", "भरि", "अघि", "पछि", "सँग", "भन्दा", "माथि")
_SUF_RE = "(?:" + "|".join(CASE_SUF) + ")?"

def tb(words):
    """regex for a WHOLE Devanagari token (optionally + one case suffix). Python's \\b is not usable: the matras
    and virama are not word characters, so \\b would cut a word in the middle."""
    alt = "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))
    return r"(?<![" + DEVR + r"A-Za-z0-9])(?:" + alt + r")(?=" + _SUF_RE + r"(?![" + DEVR + r"A-Za-z0-9]))"

def has_word(text, word):
    return re.search(tb([word]), text) is not None

def _canon(raw):
    """canonical spelling for MATCHING only: NFC, a+e matras -> o/au, ौँ -> ौं, zero-width marks dropped.
    Returns (canon, raw_start_of_each_canon_char, raw_end_of_each_canon_char) so spans map back to the raw text."""
    import unicodedata
    out, st, en = [], [], []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch in "\u200c\u200d":
            i += 1; continue
        two = raw[i:i + 2]
        if two == "ाे": out.append("ो"); st.append(i); en.append(i + 2); i += 2; continue
        if two == "ाै": out.append("ौ"); st.append(i); en.append(i + 2); i += 2; continue
        if ch == "ँ" and out and out[-1] in ("ौ", "औ"): out.append("ं"); st.append(i); en.append(i + 1); i += 1; continue
        for c in unicodedata.normalize("NFC", ch):
            out.append(c); st.append(i); en.append(i + 1)
        i += 1
    return "".join(out), st, en

def _uncanon(g, raw, canon, st, en):
    """rewrite every span string of a plan (made on the canonical text) as the exact substring of the raw text."""
    if canon == raw:
        g["vo"] = raw
        return g
    def fix(s):
        if not isinstance(s, str) or s in raw or not s: return s
        a = canon.find(s)
        if a < 0: return s
        return raw[st[a]: en[a + len(s) - 1]]
    def walk(x, key=""):
        if key in ("vo", "kind"): return x
        if isinstance(x, str): return fix(x)
        if isinstance(x, list): return [walk(y) for y in x]
        if isinstance(x, dict): return {k: walk(v, k) for k, v in x.items()}
        return x
    out = walk(g)
    out["vo"] = raw
    return out

def _tp(vo):
    """tokens with positions: (token_without_edge_punct, start, end, trailing_punct)"""
    out = []
    for m in re.finditer(r"[^\s।]+।*|।+", vo):      # a danda ends a token even without a space ('छ।यस' -> 'छ।' 'यस')
        r = m.group(0); t = r.strip(PUNCT)
        if not t: continue
        a = m.start() + len(r) - len(r.lstrip(PUNCT))
        out.append((t, a, a + len(t), r[len(r.rstrip(PUNCT)):]))
    return out

def _sl(vo, T, i, j):
    return vo[T[i][1]:T[j][2]] if 0 <= i <= j < len(T) else ""

PRON_STEMS = {"उन", "उनी", "उनीहरू", "उनीहरु", "यस", "त्यस", "यी", "ती", "तिनी", "तिनीहरू", "तिनीहरु", "आफू", "आफ्", "हामी", "हाम्रो",
              "यो", "त्यो", "उस", "जस", "उनै", "तिनै", "कसै", "सबै", "यिनी", "यिनीहरू", "यिनीहरु", "मैल", "म", "तपाईं", "तपाईँ"}
def _stem(t):
    for suf in ("लाई", "बाट", "ले", "का", "को", "की", "मा"):
        if t.endswith(suf) and len(t) > len(suf): return t[:-len(suf)]
    return t
def is_pronoun(t): return t in PRON_STEMS or _stem(t) in PRON_STEMS

LEAD_JUNK = {"पनि", "भए", "भने", "र", "तर", "तथा", "कि", "अनि", "यो", "यस", "त्यो", "उक्त", "हुँदा", "गर्दा", "अर्थात्", "त्यस्तै",
             "यस्तै", "साथै", "समेत", "नै", "पो", "त", "गरिएको", "गरेको", "भएको", "यी", "ती", "त्यसपछि", "अनुसार", "छ", "छन्", "हुन्", "हो",
             "भन्दै", "गर्दै", "भए", "गरी", "गरेर", "भएर", "जसले", "जुन", "जसको", "तथापि", "वा", "या", "अथवा", "पश्चात", "पछि", "अघि", "बाहेक", "लागि", "के", "कुन", "कसरी", "किन", "कति"}
ADV_LE = {"त्यसैले", "यसैले", "जसले", "कसले", "उसले", "जसैले", "अहिले", "पहिले", "कहिले", "हिजोआज", "कहिलेकाहीँ", "जतिबेला", "त्यतिबेला", "यतिबेला", "पछिल्लोपल्ले"}
TEMPORAL = ("आइतबार", "सोमबार", "मंगलबार", "बुधबार", "बिहीबार", "शुक्रबार", "शनिबार", "आज", "हिजो", "भोलि", "गत", "हाल")
MULT = {"हजार", "लाख", "करोड", "अर्ब", "खर्ब", "सय", "जना", "प्रतिशत", "दशमलव"}
NUMWORDS = {"एक", "दुई", "तीन", "चार", "पाँच", "छ", "सात", "आठ", "नौ", "दस", "बीस", "तीस", "चालीस", "पचास", "साठी", "सय", "हजार"}
def _is_num(t): return re.fullmatch(NUM_RE, t) is not None or t in NUMWORDS
PART_END = ("एको", "एका", "एकी", "ेको", "ेका", "ेकी", "ने", "दै", "एर", "ेर", "ाई", "दा", "ेपछि", "पछि")

def _span_ok(vo, s):
    """a span must start on a token boundary, not be a loose suffix/particle, and not cut a number"""
    import unicodedata
    if not s or s != s.strip(): return False
    if re.search(r"[A-Za-z]", s): return False
    if s.count("‘") != s.count("’") or s.count("“") != s.count("”") or s.count("'") % 2 or s.count('"') % 2 or s.count("(") != s.count(")"): return False   # cut quote/bracket
    if s[0] in ",.:;।)]}-–—?!" or s[-1] in ",:;-–—([{": return False
    if unicodedata.category(s[0]) in ("Mn", "Mc"): return False
    if not re.search(r"(?<![" + DEVR + r"])" + re.escape(s), vo): return False
    ft = s.split()[0].strip(PUNCT)
    if ft in CASE_SUF or ft in LEAD_JUNK: return False
    if ft in MULT or ft in UNITS:
        a = vo.find(s)
        before = vo[:a].split()
        if before and _is_num(before[-1].strip(PUNCT)): return False
    return True

SKIP_KEYS = {"vo", "kind", "direction", "connector", "org", "parts"}
GATED = {"schedule", "result", "who", "voiceprint", "quote", "chain", "rule", "contrast", "compare", "verdict", "money", "incident", "roster", "movement"}
REQ = {"schedule": ("start",), "result": ("winner", "outcome"), "who": ("actor", "verb", "target"),
       "voiceprint": ("name", "role", "hl"), "quote": ("speaker", "claim"), "chain": ("nodes",),
       "rule": ("condition", "consequence"), "compare": ("left", "right", "leftMeta", "rightMeta"),
       "contrast": ("left", "right", "bridge"), "money": ("amount", "context"), "movement": ("from", "to", "actor"),
       "incident": ("headline",), "verdict": ("subject", "decision"), "roster": ("members",), "hook": ("question",),
       "lawstage": ("stages",)}

def required_ok(g):
    """every required field of the strip must be non-empty (and for chain both nodes); then, for the gated kinds,
    every span must pass _span_ok. Anything else -> skip, the renderer falls back to the clean caption."""
    k = g.get("kind")
    for f in REQ.get(k, ()):
        v = g.get(f)
        if not v: return False
        if isinstance(v, list) and (not all(isinstance(x, str) and x.strip() for x in v) if k == "chain" else False): return False
        if isinstance(v, str) and not v.strip(): return False
    if k == "chain" and len(g["nodes"]) < 2: return False
    if k == "schedule" and not (re.search(r"[०-९0-9]", g["start"]) or g.get("end")): return False
    if k in GATED:
        vo = g.get("vo", "")
        def chk(x, key=""):
            if key in SKIP_KEYS: return True
            if isinstance(x, str): return (not x) or _span_ok(vo, x)
            if isinstance(x, list): return all(chk(y) for y in x)
            if isinstance(x, dict): return all(chk(v, kk) for kk, v in x.items())
            return True
        if not chk(g): return False
    return True


def _verby(t):
    return t.endswith(PART_END) or t.endswith(("उन", "र्न"))

def bad_np(s):
    """a noun phrase that is really an adverb / pronoun / verb form (v9.3 'अहिले' -> 'अहि', 'कसै', 'भन्ने')"""
    ws = s.split()
    if not ws: return True
    if any(_verby(w) or (w + "ले") in ADV_LE or w in ADV_LE for w in ws): return True
    return is_pronoun(ws[-1]) or is_pronoun(ws[0])

DATE_RE = tb(MONTH_NAMES)

SAY_ONE = re.compile(r"^(?:बताए(?:का|को|की)?|बताइन्|बताउँछन्|बताउँछ|भनिन्|भन्छन्|भन्छ|भनेका|भनेकी|उल्लेख|भने)$")
SAY_TWO = {"जोड": ("दि",), "दाबी": ("गर",), "स्पष्ट": ("पार",), "आग्रह": ("गर",)}

def _verb_idx(toks, start=0):
    """index of a whole-token 'said' verb ('भने' only as the clause-final verb, never the conjunction 'if/while')"""
    n = len(toks)
    for k in range(start, n):
        raw = toks[k]; t = raw.strip(PUNCT)
        if t == "भने":
            if k == n - 1 or raw != t: return k
            continue
        if SAY_ONE.match(t): return k
        nx = toks[k + 1].strip(PUNCT) if k + 1 < n else ""
        if t in SAY_TWO and nx.startswith(SAY_TWO[t]): return k
    return -1

ROLE_TAIL = {"अतिथि", "अधिकृत", "विशिष्ट", "सम्माननीय", "माननीय"}
HONOR = {"श्री", "श्रीमती", "डा.", "डा", "प्रा.", "प्रा", "सम्माननीय", "माननीय"}
def _role_hit(t):
    if t in ROLES: return True
    for suf in ("का", "को", "ले", "मा", "लाई"):
        if t.endswith(suf) and t[:-len(suf)] in ROLES: return True
    return False

def plan_voiceprint(vo):
    toks = vo.split()
    j = next((k for k, t in enumerate(toks[:8]) if t.endswith("ले") and len(t) > 3), -1)
    if j < 0: return None
    r = -1
    for k in range(j - 1, -1, -1):
        if _role_hit(toks[k].strip(PUNCT)): r = k; break
    if r < 0 or r >= j: return None
    v = _verb_idx(toks, j + 1)
    if v < 0: return None
    rt = r
    while rt + 1 < j and toks[rt + 1] in ROLE_TAIL: rt += 1
    if rt + 2 < j and toks[rt + 1] in ("तथा", "एवं") : rt += 2                   # 'निर्देशक तथा निर्माता' - the name starts after the second title
    while rt + 1 < j and toks[rt + 1] in ROLE_TAIL: rt += 1
    name_t = toks[rt + 1: j + 1]
    while len(name_t) > 1 and (name_t[0] in HONOR or name_t[0].endswith(PART_END) or name_t[0] in LEAD_JUNK): name_t = name_t[1:]
    if not name_t or len(name_t) > 3: return None
    name_t = list(name_t)
    name_t[-1] = _strip_le(name_t[-1])
    if any(t.endswith(("मा", "बाट", "को", "का", "की")) or t.endswith(PART_END) or t.strip(PUNCT) != t for t in name_t): return None
    if is_pronoun(name_t[-1]) or any(t in ROLES for t in name_t): return None
    name = " ".join(name_t)
    role_t = toks[r: rt + 1]
    for k in range(r - 1, max(-1, r - (5 if r > 0 and toks[r - 1].endswith("का") else 3)), -1):
        tk = toks[k]
        if tk.endswith(("मा", "ले", "बाट")) or tk != tk.strip(PUNCT) or tk in TEMPORAL: break
        role_t.insert(0, tk)
    while role_t and role_t[0] in LEAD_JUNK: role_t = role_t[1:]
    role = " ".join(role_t)
    if not role: return None
    clause = toks[j + 1: v]
    if len(clause) < 2: return None
    nh = 2 if len(clause) >= 3 else 1
    pre = _sub(vo, j + 1, v - nh - 1, toks) if v - nh - 1 >= j + 1 else ""
    hl = _sub(vo, v - nh, v - 1, toks)
    post = vo[vo.find(hl) + len(hl):] if hl else ""
    if not hl or name not in vo.replace("ले", "", 1) and name_t[0] not in vo: return None
    oi = next((x for x, t in enumerate(role_t) if t.endswith(("का", "को")) and len(t) > 3), 0)
    org = " ".join(role_t[:oi + 1])
    for suf in ("का", "को"):
        if org.endswith(suf) and len(org) > 3: org = org[:-len(suf)]; break
    parts = []
    if pre: parts.append({"t": pre + " "})
    parts.append({"t": hl, "hl": True})
    if post: parts.append({"t": post})
    return {"kind": "voiceprint", "name": name, "role": role, "parts": parts, "vo": vo, "org": org, "hl": hl}

def _clean_actor(toks, j):
    a = toks[:j + 1]
    if len(a) > 5: return False
    for k, t in enumerate(a):
        s = t.strip(PUNCT)
        if t != s and k < j: return False                         # comma inside: not one noun phrase
        if k == 0 and (s in LEAD_JUNK or s in ("गत", "आज", "हिजो", "भोलि") or s in ADV_LE): return False
        if k < j and (s.endswith(("मा", "बाट", "मध्ये", "पछि", "अघि", "अनुसार")) or s.endswith(PART_END)): return False
        if s in ("गत", "वर्ष", "महिना") or any(m in s for m in ("आइतबार", "सोमबार", "मंगलबार", "बुधबार", "बिहीबार", "शुक्रबार", "शनिबार")): return False
    s = a[-1].strip(PUNCT)
    if s.endswith("अनुसार") or s in ADV_LE: return False
    return not is_pronoun(s)

def plan_who(vo):
    toks = vo.split()
    j = next((k for k, t in enumerate(toks[:7]) if t.endswith("ले") and len(t) > 3), -1)
    if j < 1: return None
    if not _clean_actor(toks, j): return None
    v = _verb_idx(toks, j + 1)
    if v < 0: return None
    clause = toks[j + 1: v]
    # the target is the last clause only: cut after any later subject ('...ले') or comma
    for k in range(len(clause) - 1, -1, -1):
        s = clause[k].strip(PUNCT)
        if s.endswith("ले") and len(s) > 3: return None          # a second subject owns the verb: not this actor's statement
        if clause[k] != s:
            clause = clause[k + 1:]
            break
    while clause and (clause[0].strip(PUNCT) in LEAD_JUNK or clause[0].endswith("मा") or clause[0].strip(PUNCT) in CASE_SUF): clause = clause[1:]
    while clause and (clause[-1] in ("रहेको", "छ", "गरेको", "भएको", "रहेका", "छन्", "हुन्") or is_pronoun(clause[-1].strip(PUNCT))): clause = clause[:-1]
    if len(clause) < 2 or clause[-1].strip(PUNCT).endswith("दै"): return None
    if len(clause) > 7:
        # clause longer than the strip can show: start only where a new phrase begins (after a case/participle word)
        cut_ = len(clause) - 7
        while cut_ < len(clause) - 2 and not (clause[cut_ - 1].strip(PUNCT).endswith(("मा", "बाट", "लाई", "ले", "को", "का")) or clause[cut_ - 1].strip(PUNCT).endswith(PART_END)): cut_ += 1
        if cut_ >= len(clause) - 2: return None
        clause = clause[cut_:]
    k0 = None
    for k in range(j + 1, v - len(clause) + 1):
        if toks[k: k + len(clause)] == clause: k0 = k; break
    if k0 is None: return None
    while k0 - 1 > j and (toks[k0].strip(PUNCT) in MULT or toks[k0].strip(PUNCT) in UNITS) and _is_num(toks[k0 - 1].strip(PUNCT)):
        k0 -= 1; clause = [toks[k0]] + clause                      # never start in the middle of a number
    if clause[0].strip(PUNCT) in LEAD_JUNK or len(clause) < 2: return None
    target = _sub(vo, k0, k0 + len(clause) - 1, toks)
    actor = _sub(vo, 0, j, toks)
    actor = actor[:-2] if actor.endswith("ले") else actor
    verb = re.match(r"[^\s।]+", toks[v]).group(0)
    if not target or not actor or actor not in vo or target not in vo: return None
    return {"kind": "who", "actor": actor, "verb": verb, "target": target, "vo": vo}

CAUSE_ONE = {"निम्त्याउने", "निम्त्याउँछ", "बढाउने", "घटाउने", "बढाउँछ", "घटाउँछ"}
CAUSE_TWO = {"असर": ("पार्ने", "पार्छ", "पर्ने", "पर्छ", "परेको", "पारेको", "परेका"), "सहयोग": ("पुग्ने", "पुग्छ"), "मद्दत": ("गर्ने", "गर्छ", "पुग्ने")}
INSTITUTION = ("संघ", "संस्था", "निकाय", "कम्पनी", "बैंक", "विभाग", "कार्यालय", "सरकार", "बैठक", "समिति", "मन्त्रालय", "अदालत", "प्रशासन", "पार्टी", "आयोग", "परिषद")
STOP_B = {"भने", "गर्दा", "अर्थात्", "तथा", "पनि", "गर्दै", "भएर", "हुँदा", "र", "तर"}

def plan_chain(vo, speaker):
    T = _tp(vo); toks = [x[0] for x in T]
    cv, ncv = -1, 1
    for k, t in enumerate(toks):
        nx = toks[k + 1] if k + 1 < len(toks) else ""
        if t in CAUSE_TWO and nx in CAUSE_TWO[t]: cv, ncv = k, 2; break
        if t in CAUSE_ONE: cv, ncv = k, 1; break
    if cv < 0: return None
    after = toks[cv + ncv] if cv + ncv < len(toks) else ""
    if after in ("निर्णय", "घोषणा", "तयारी", "योजना", "प्रस्ताव") or (cv > 0 and toks[cv - 1] in ("अगाडि", "अघि")): return None
    j = next((k for k in range(cv - 1, -1, -1) if toks[k].endswith("ले") and len(toks[k]) > 3), -1)
    if j < 0 or cv - j < 2: return None
    # cause side A: up to 3 tokens ending at the 'ले' word, stopping at clause junk
    ai = [j]
    for k in range(j - 1, max(-1, j - 3), -1):
        s = toks[k]
        if T[k][3] or s in LEAD_JUNK or s == "लागि" or s.endswith(("मा", "बाट")) or s.endswith(PART_END) or s in ADV_LE: break
        ai.insert(0, k)
    A = vo[T[ai[0]][1]: T[j][2]]
    if A.endswith("ले"): A = A[:-2]
    if not A or is_pronoun(toks[j][:-2]) or toks[j] in ADV_LE or any(toks[x] in ADV_LE or toks[x] in TEMPORAL for x in ai): return None
    if any(_role_hit(toks[x]) for x in ai) and not toks[cv] == "असर": return None      # a person acting is not a cause
    if not (toks[cv] == "असर" or toks[cv] in CAUSE_TWO) and any(toks[j][:-2].endswith(w) for w in INSTITUTION): return None
    # effect side B: what sits between 'ले' and the cause verb (after 'लाई' when there is one)
    mid = list(range(j + 1, cv))
    for p in range(len(mid) - 1, -1, -1):
        s = toks[mid[p]]
        if T[mid[p]][3] or s in STOP_B or s.endswith(("दै", "एर", "ाई")):
            mid = mid[p + 1:]; break
    lai = [p for p, k in enumerate(mid) if toks[k].endswith("लाई")]
    if lai: mid = mid[lai[-1] + 1:]
    mid = mid[-3:]
    while mid and (toks[mid[0]] in LEAD_JUNK or toks[mid[0]].endswith(PART_END) or toks[mid[0]] in CASE_SUF): mid = mid[1:]
    while mid and toks[mid[-1]] in PARTICLES: mid = mid[:-1]
    if not mid or toks[mid[-1]].endswith(PART_END) or toks[mid[-1]].endswith(("उन", "र्न", "ाउन")): return None
    B = vo[T[mid[0]][1]: T[mid[-1]][2]]
    for suf in ("मा", "बाट", "लाई"):
        if B.endswith(suf) and len(B) > len(suf) + 2: B = B[:-len(suf)]; break
    if not A or not B or A == B or A not in vo or B not in vo: return None
    return {"kind": "chain", "nodes": [A, B], "speaker": (speaker + " भन्छ") if speaker else "", "vo": vo}

def plan_rule(vo):
    T = _tp(vo)
    for k, (t, a, b, tail) in enumerate(T):
        if t not in ("भने", "नत्र", "नभए") or k == 0 or k >= len(T) - 1: continue
        if t == "भने":
            if tail: continue
            y = max((x for x in range(k) if T[x][0] == "यदि"), default=-1)
            if y < 0 or any(T[x][3] for x in range(y, k)): continue
            s = max(y + 1, k - 7); ce = k
        else:
            if T[k][3]: continue
            s = k
            while s > 0 and not T[s - 1][3] and k - (s - 1) <= 8: s -= 1
            if T[s][0] == "यदि": s += 1
            ce = k if t == "नभए" else k - 1
        if s > ce: continue
        e = k + 1
        while e + 1 < len(T) and not T[e][3] and e - k < 8: e += 1
        while e > k + 1 and (T[e][0] in LEAD_JUNK or T[e][0] in CASE_SUF or T[e][0] in PARTICLES): e -= 1     # never end on a dangling particle
        cond = vo[T[s][1]: T[ce][2]]
        cons = vo[T[k + 1][1]: T[e][2]]
        if cond and cons: return {"kind": "rule", "condition": cond, "consequence": cons, "vo": vo}
    return None
SCHED_DATE = DATE_RE + r"\s*(?<![०-९0-9])[०-९0-9]{1,2}(?![०-९0-9])(?:\s*गते?)?"
def _day_ok(s):
    m = re.search(r"[०-९0-9]{1,2}", s.translate(LAT))
    return bool(m) and 1 <= int(m.group(0)) <= 32

def _dateline_junk(vo):
    """bylines / citations / timestamps that only look like a date"""
    if re.search(r"[०-९0-9]{1,2}[:ः][०-९0-9]{1,2}[:ः][०-९0-9]{1,2}", vo): return True
    if re.search(r"[A-Za-z]{3,}", vo): return True
    return len(_tp(vo)) < 5

def plan_schedule(vo):
    if _dateline_junk(vo): return None
    dm = None
    for m in re.finditer(SCHED_DATE, vo):
        if not _day_ok(m.group(0)): continue
        nxt = vo[m.end():].split()
        n0 = nxt[0].strip(PUNCT) if nxt else ""
        if not re.search(r"गते?$", m.group(0).strip()) and (len(n0) == 1 or n0 in UNITS or n0 in UNIT_T): continue   # plate 'मे ४ प', 'जुन ५ वटा'
        dm = m; break
    if not dm: return None
    start = dm.group(0).strip()
    end = ""
    m_d = re.search(r"देखि(?![" + DEVR + r"])", vo[dm.start():])
    if m_d:
        tail = vo[dm.start() + m_d.end():]
        m2 = re.search(SCHED_DATE, tail)
        if m2 and _day_ok(m2.group(0)): end = m2.group(0).strip()
        else:
            m3 = re.match(r"\s*([०-९0-9]{1,2}(?:\s*गते?)?)(?![०-९0-9])", tail)
            if m3 and _day_ok(m3.group(1)):
                nx = tail[m3.end():].split()
                n1 = nx[0].strip(PUNCT) if nx else ""
                if "गत" in m3.group(1) or not n1 or n1.startswith("सम्म") or n1 not in UNITS and n1 not in UNIT_T and len(n1) > 1 and not _is_num(n1):
                    end = m3.group(1).strip()
    if end == start: end = ""
    pl = find_places(vo)
    x = {"kind": "schedule", "start": start, "end": end, "place": pl[0]["ne"] if pl else "", "vo": vo}
    if end: x["connector"] = "देखि"
    return x

WIN_ONE = {"जित्यो", "जित्यौं", "जिते", "जितिन्", "जित्नुभयो", "जित्नुभएको", "हरायो", "हराए", "हराइन्", "जित्यौ", "हराउँदा", "हराएर", "हराएको"}
WIN_TWO = {"विजयी": ("भयो", "भए", "भइन्", "बने", "बनिन्", "घोषित"), "पराजित": ("गर", "भ"), "विजय": ("हासिल", "प्राप्त")}
TITLE_W = ("पदक", "उपाधि", "ट्रफी", "कप", "स्वर्ण", "रजत", "कांस्य", "च्याम्पियन", "शृङ्खला", "पुरस्कार", "फाइनल")
NOT_CONTEST = ("उम्मेदवार", "मनोनयन", "दर्ता", "सहभागी", "अन्तरक्रिया", "अनुभव", "जस्तो लाग्छ", "आशा", "सम्भावना", "सक्छ")

def plan_result(vo):
    if vo.rstrip().endswith("?"): return None
    if any(w in vo for w in NOT_CONTEST): return None
    T = _tp(vo); toks = [x[0] for x in T]
    vi, nv = -1, 1
    for k, t in enumerate(toks):
        nx = toks[k + 1] if k + 1 < len(toks) else ""
        if t in WIN_ONE: vi = k; break
        if t in WIN_TWO and nx.startswith(WIN_TWO[t]): vi, nv = k, 2; break
    if vi < 1: return None
    if vi + nv < len(toks) and toks[vi + nv] == "पनि": return None          # 'जिते पनि ...' is a concession, not a result
    j = next((k for k, t in enumerate(toks[:vi]) if t.endswith("ले") and len(t) > 3 and k < 7), -1)
    if j < 0: return None
    w_idx = [j]
    for k in range(j - 1, max(-1, j - 3), -1):
        s = toks[k]
        if T[k][3] or s in LEAD_JUNK or s.endswith(("मा", "बाट", "ले")) or s.endswith(PART_END): break
        w_idx.insert(0, k)
    winner = vo[T[w_idx[0]][1]: T[j][2]]
    winner = winner[:-2] if winner.endswith("ले") else winner
    if not winner or is_pronoun(toks[j][:-2]) or len(winner.split()) > 3: return None
    loser = ""
    for k in range(j + 1, vi):
        s = toks[k]
        suf = next((x for x in ("लाई", "माथि") if s.endswith(x) and len(s) > len(x) + 1), None)
        if suf:
            li = [k]
            if k - 1 > j:
                p = toks[k - 1]
                if not T[k - 1][3] and p not in ("वर्ष", "साल", "महिना", "हप्ता", "दिन", "राष्ट्र", "टोली", "देश", "खेलाडी", "प्रतिद्वन्द्वि") and not p.endswith(("मा", "बाट", "लाई", "को", "का", "की")) and not (p.endswith("ले") and len(p) > 3) and not _is_num(p) and p not in LEAD_JUNK and not p.endswith(PART_END): li.insert(0, k - 1)
            loser = vo[T[li[0]][1]: T[k][2]][:-len(suf)]
            break
        if s == "विरुद्ध" and k - 1 > j:
            loser = toks[k - 1]; break
    if loser and (is_pronoun(loser) or ":" in loser): loser = ""
    if ":" in winner or _is_num(winner) or winner.split()[0] in ("कति", "कुन"): return None
    title = any(toks[k].startswith(TITLE_W) for k in range(max(j + 1, vi - 3), vi + 1))
    if not loser and not title: return None
    s = vi
    while s - 1 > j and vi - (s - 1) <= 3:
        p = toks[s - 1]
        clean = (not T[s - 1][3]) and (p == "ले" or re.fullmatch(r"[०-९0-9]+[-–][०-९0-9]+", p) or not (p.endswith(("लाई", "माथि", "मा", "बाट", "सँग", "को", "का", "की", "ले")) or p.endswith(PART_END) or p in LEAD_JUNK))
        if not clean: break
        s -= 1
    outcome = vo[T[s][1]: T[vi + nv - 1][2]]
    while outcome and outcome.split()[0] == "ले": outcome = outcome.split(None, 1)[1] if " " in outcome else ""
    if not outcome: return None
    ctx = ""
    m = re.search(NUM_RE + r"\s*(?:वर्ष|दिन|पटक)(?:पछि|अघि|अगाडि|अगावै)?", vo)
    if m: ctx = m.group(0).strip()
    return {"kind": "result", "winner": winner, "loser": loser, "outcome": outcome, "context": ctx, "vo": vo}

UNIT_T = {"प्रतिशत", "जना", "मिलियन", "करोड", "अर्ब", "लाख", "हजार", "रुपैयाँ", "डलर", "वटा", "ओटा", "पटक", "सिट", "मत", "अंक", "स्थान", "वर्ष", "दिन", "किलो", "मिटर", "सय"}
def _unit_of(tok):
    """unit word at the start of tok ('हजारभन्दा' -> 'हजार', 'प्रतिशतसम्म' -> 'प्रतिशत') or ''"""
    for u in sorted(UNIT_T, key=len, reverse=True):
        if tok == u or (tok.startswith(u) and tok[len(u):] in CASE_SUF): return u
    return ""

PARTICLES = {"मात्र", "मात्रै", "नै", "पनि", "जम्मा", "करिब", "लगभग", "साढे", "थप", "समेत", "नकारात्मक", "सकारात्मक", "प्रत्यक्ष", "अप्रत्यक्ष", "गम्भीर", "ठूलो", "धेरै"}
def _label(vo, T, toks, i, lo):
    """up to 2 words just before token i that name what is counted; case suffix trimmed off the last word"""
    idx = []
    p = i - 1
    while p >= lo and toks[p] in PARTICLES and not T[p][3]: p -= 1
    while p >= lo and len(idx) < 2:
        s = toks[p]
        if (T[p][3] and idx) or s in LEAD_JUNK or s in CASE_SUF or _is_num(s) or s.endswith(("बाट", "ले", "लाई")) or s.endswith(PART_END): break
        if idx and s.endswith(("मा", "को", "का", "की")): break
        if "," in s or s.endswith("ले"): break
        idx.insert(0, p); p -= 1
        if T[p + 1][3]: break
    if not idx: return ""
    text = vo[T[idx[0]][1]: T[idx[-1]][2]]
    for suf in ("मा", "को", "का", "की"):
        if text.endswith(suf) and len(text) > len(suf) + 2: text = text[:-len(suf)]; break
    return text

def _is_listy(T, toks, a, b):
    """is the numbered pair part of a 3+ item list (commas between numbered items)?"""
    before = [x for x in range(max(0, a - 6), a) if T[x][3] and "," in T[x][3]]
    if before and any(_is_num(toks[x]) or _unit_of(toks[x]) for x in range(max(0, before[0] - 1), before[0] + 1)): return True
    after = [x for x in range(b, min(len(T), b + 1)) if T[x][3] and "," in T[x][3]]
    if after:
        nxt = range(after[0] + 1, min(len(T), after[0] + 5))
        if any(_is_num(toks[x]) for x in nxt): return True
    return False

def plan_compare(vo):
    """'<label> N unit  र  <label> M unit' -> left/right = the numbers, leftMeta/rightMeta = what each number counts"""
    T = _tp(vo); toks = [x[0] for x in T]
    for k, t in enumerate(toks):
        if t not in ("र", "जुन", "मात्र", "तर") or k < 2 or k > len(T) - 3: continue
        li = k - 1
        while li > 0 and _unit_of(toks[li]) and k - li <= 3: li -= 1
        if not re.fullmatch(NUM_RE, toks[li]): continue
        ri = k + 1
        while ri < len(T) and not re.fullmatch(NUM_RE, toks[ri]) and ri - k <= 3: ri += 1
        if ri >= len(T) or not re.fullmatch(NUM_RE, toks[ri]): continue
        re_ = ri
        while re_ + 1 < len(T) and _unit_of(toks[re_ + 1]) and re_ + 1 - ri <= 2 and not T[re_][3]: re_ += 1
        if any(re.fullmatch(r"(19|20)\d\d", toks[x].translate(LAT)) for x in (li, ri)): continue
        if re_ + 1 < len(T) and toks[re_ + 1] in ("देखि", "देखिको") or toks[li + 1:li + 2] == ["देखि"]: continue     # a range, not two values
        ll = _label(vo, T, toks, li, 0)
        rl = ""
        if ri > k + 1:
            idx = [p for p in range(k + 1, ri) if toks[p] not in PARTICLES and not T[p][3]]
            if idx:
                rl = vo[T[idx[0]][1]: T[idx[-1]][2]]
                for suf in ("मा", "को", "का", "की"):
                    if rl.endswith(suf) and len(rl) > len(suf) + 2: rl = rl[:-len(suf)]; break
        if not ll or not rl or len(ll) < 3 or len(rl) < 3 or re.search(r"[()\[\]‘’'\"“”]", ll + rl) or "," in ll or "," in rl or any(w.endswith(("ले", "बाट", "लाई")) for w in rl.split()): continue
        a0 = li - len(ll.split()) + (0)
        if a0 - 1 >= 0 and "," in T[a0 - 1][3]: continue                  # item of a longer comma list
        if _is_listy(T, toks, li - len(ll.split()), re_): continue
        lend = k - 1
        lu = _unit_of(toks[lend]) if lend > li else ""
        lnum = vo[T[li][1]: T[lend][1] + len(lu)] if lu else vo[T[li][1]: T[lend][2]]
        ru = _unit_of(toks[re_]) if re_ > ri else ""
        rnum = vo[T[ri][1]: T[re_][1] + len(ru)] if ru else vo[T[ri][1]: T[re_][2]]
        return {"kind": "compare", "left": lnum, "leftMeta": ll, "right": rnum, "rightMeta": rl, "vo": vo}
    return None

BRIDGES = ("फरक", "भिन्न")
COPULA = {"छ", "छन्", "हुन्", "हो", "हुन्छ", "हुन्छन्", "थियो", "थिए", "हुँदैन", "देखिन्छ", "पर्छ", "रहेको", "रहेका", "भएको", "भएका"}
def plan_contrast(vo):
    """'A र B ... फरक छ' with the bridge right behind B (max 4 tokens after र)"""
    T = _tp(vo); toks = [x[0] for x in T]
    bi = -1
    for k, t in enumerate(toks):
        if t in BRIDGES and k + 1 < len(toks) and not T[k][3] and toks[k + 1] in COPULA: bi = k; break
        if t == "भन्न" and k + 1 < len(toks) and toks[k + 1] == "मिल्दैन": bi = k; break
    if bi < 0: return None
    ri = next((k for k in range(bi - 1, max(0, bi - 5), -1) if toks[k] == "र"), -1)
    if ri < 1: return None
    r_end = bi - 1
    while r_end > ri and (toks[r_end] in ("बीच", "बिच", "बीचको", "बीचमा", "त", "नै", "पनि") or toks[r_end] in BRIDGES): r_end -= 1
    for x in range(ri + 1, r_end + 1):
        if toks[x].endswith("बीच") and len(toks[x]) > 4: r_end = x; break
    if r_end <= ri or r_end - ri > 3: return None
    rt = toks[ri + 1: r_end + 1]
    if any(t.endswith(PART_END) or t.endswith("भन्दा") or t.startswith("दुवै") for t in rt) or any(x[3] for x in T[ri + 1: r_end]): return None
    li = ri - 1
    ls = li
    while ls - 1 >= 0 and not T[ls - 1][3] and ri - (ls - 1) <= 3 and toks[ls - 1] not in LEAD_JUNK and not toks[ls - 1].endswith(PART_END) and not toks[ls - 1].endswith(("मा", "बाट", "ले", "लाई")): ls -= 1
    left = vo[T[ls][1]: T[li][2]]
    right = vo[T[ri + 1][1]: T[r_end][2]]
    if not left or not right or left == right or T[li][3]: return None
    return {"kind": "contrast", "left": left, "right": right, "bridge": vo[T[bi][1]: T[bi + (1 if toks[bi] == "भन्न" else 0)][2]], "vo": vo}

def plan_quote(vo):
    T = _tp(vo); toks = [x[0] for x in T]
    for k in range(1, len(T) - 1):
        if toks[k] != "अनुसार" or not toks[k - 1].endswith("का") or len(toks[k - 1]) < 3 or T[k - 1][3]: continue
        last = toks[k - 1][:-2]
        if not last or is_pronoun(last): return None
        sp = [k - 1]
        for p in range(k - 2, max(-1, k - 4), -1):
            s = toks[p]
            if T[p][3] or s in LEAD_JUNK or s.endswith(("मा", "ले", "लाई", "बाट", "को")) or s.endswith(PART_END) or s == "लागि": break
            sp.insert(0, p)
        speaker = vo[T[sp[0]][1]: T[k - 1][2]][:-2]
        claim = vo[T[k + 1][1]:].strip().rstrip("।").strip() if k + 1 < len(T) else ""
        claim = _clip(vo, claim, 16)
        if not speaker or not claim or claim not in vo or speaker not in vo: return None
        return {"kind": "quote", "speaker": speaker, "claim": claim, "vo": vo}
    return None



def _span(toks, i, j):
    return " ".join(toks[i:j + 1]) if 0 <= i <= j < len(toks) else ""

def _clip(vo, text, max_tok=8):
    """trim to max_tok tokens, keeping it an exact span of vo"""
    w = text.split()
    return " ".join(w[:max_tok]) if len(w) > max_tok else text

def plan_hook(vo):
    t = vo.strip()
    if not t.startswith("के "): return None
    q = t.rstrip("।").strip()
    if len(q.split()) > 30: return None
    return {"kind": "hook", "question": q, "vo": vo}

def plan_lawstage(vo):
    if not (re.search(r"विधेयक|कानून|कानुनी", vo) or has_word(vo, "ऐन")): return None
    if not re.search(r"पारित|पठाइनेछ|प्रमाणीकरण|दर्ता|लागू", vo): return None
    vocab = ["प्रतिनिधिसभा", "राष्ट्रिय सभा", "राष्ट्रपति", "ऐन"]
    present = [(vo.find(s), s) for s in vocab if (has_word(vo, s) if s == "ऐन" else s in vo)]
    present.sort()
    if len(present) < 2 or not any(s in ("प्रतिनिधिसभा", "राष्ट्रिय सभा") for _, s in present): return None
    # stages up to and including the one nearest before "पारित" are done
    cut = -1
    pj = vo.find("पारित")
    if pj >= 0:
        for pos, s in present:
            if pos < pj: cut += 1
    stages = [{"text": s, "done": i <= cut} for i, (pos, s) in enumerate(present)]
    return {"kind": "lawstage", "stages": stages, "vo": vo}

def plan_verdict(vo):
    dec = None
    for d in ("दोषी ठहर", "निलम्बन", "प्रतिबन्ध", "गुमाउने निश्चित", "बाहिरिएको", "रोक लगाउने"):
        if d in vo: dec = d; break
    if not dec: return None
    toks = vo.split()
    subj = ""
    for k, t in enumerate(toks):
        if t.endswith("लाई") or t.endswith("माथि"):
            st_ = toks[max(0, k - 3):k + 1]
            while st_ and (st_[0].endswith("मा") or st_[0].endswith("का") or st_[0].endswith("को")
                           or st_[0].endswith("सम्बन्धी") or st_[0].endswith("वटै") or st_[0].endswith("वटा")
                           or re.fullmatch(NUM_RE, st_[0].strip(" ,"))):
                st_ = st_[1:]
            s = " ".join(st_)
            for suf in ("लाई", "माथि"):
                if s.endswith(suf): s = s[:-len(suf)]
            s = s.strip(" ,")
            if s and s not in ("उनले",): subj = s; break
    if not subj:
        j = next((k for k, t in enumerate(toks[:7]) if t.endswith("ले") and len(t) > 3), -1)
        if j >= 0:
            subj = _span(toks, max(0, j - 2), j)
            subj = subj[:-2].strip() if subj.endswith("ले") else subj
    if not subj or bad_np(subj) or any(d_ in subj for d_ in ("प्रतिबन्ध", "निलम्बन", "दोषी")): return None
    auth = next((a for a in ("विशेष अदालत", "अदालत", "फिफा", "सरकार", "अख्तियार", "ICC", "आईसीसी") if a in vo), "")
    return {"kind": "verdict", "subject": subj, "decision": dec, "authority": auth, "vo": vo}

def plan_movement(vo):
    toks = vo.split()
    j = next((k for k, t in enumerate(toks) if t.rstrip(" ,") == "छोडेर"), -1)
    if j < 1: return None
    ft = toks[max(0, j - 2):j]
    while ft and ft[0].endswith("ले"): ft = ft[1:]
    frm = " ".join(ft)
    to = _span(toks, j + 1, min(len(toks) - 1, j + 3))
    to = re.split(r"\s(?:जिम्मेवारी|पद|रवाना|भएका|हुने)", to)[0].strip(" ,")
    if not frm or not to: return None
    actor = ""
    a = next((k for k, t in enumerate(toks[:j]) if t.endswith("ले") and len(t) > 3), -1)
    if a >= 0:
        actor = _span(toks, max(0, a - 2), a)
        actor = actor[:-2].strip() if actor.endswith("ले") else actor
    if not actor or bad_np(actor) or bad_np(frm) or len(to.split()) > 3 or to.split()[-1].endswith(PART_END) or any(w.endswith("ले") and len(w) > 3 for w in frm.split()): return None
    return {"kind": "movement", "from": frm, "to": to, "verb": "छोडेर", "actor": actor, "vo": vo}

def plan_money(vo):
    m = re.search(r"(?:(?:साढे|देढ|पौने|करिब|जम्मा)\s+)?" + NUM_RE + r"\s*(?:लाख|करोड|अर्ब|खर्ब)?\s*(?:रुपैयाँ|रु\.?|डलर)?", vo)
    if not m: return None
    span = m.group(0).strip()
    if not re.search(r"लाख|करोड|अर्ब|खर्ब|रुपैयाँ|रु\.?|डलर", span): return None
    if not re.search(r"घुस|ऋण|बजेट|घाटा|मौज्दात|खर्च|लागत|नाफा|आम्दानी|जम्मा|दाबी|बिक्री|मूल्य", vo): return None
    direction = ""
    if re.search(r"घाटा|घटी|घट्यो", vo): direction = "loss"
    elif re.search(r"खर्च|बिक्री|दियो|तिर्यो", vo): direction = "out"
    elif re.search(r"बढी|आम्दानी|नाफा|जम्मा|मौज्दात", vo): direction = "in"
    if "मात्र" in vo: direction = "only"
    clause = max(re.split(r"[,।]", vo), key=lambda s: (span in s) * 100 + len(s) * 0.01)
    ctx = clause.replace(span, "").strip(" ,")
    ctx = _clip(vo, ctx, 7)
    if not ctx or ctx not in vo:
        ctx = _clip(vo, vo.replace(span, "").strip(" ।,"), 7)
    if not ctx or ctx not in vo or len(ctx) < 4 or ctx.startswith(("रु", "रू")): return None
    nxt_ = vo[vo.find(span) + len(span):].lstrip(" ,").split()
    if nxt_ and (_is_num(nxt_[0].strip(PUNCT)) or nxt_[0].strip(PUNCT) in MULT): return None     # compound amount
    cmp_ = ""
    rest = vo[vo.find(span) + len(span):]
    m2 = re.search(NUM_RE + r"\s*(?:लाख|करोड|अर्ब)?\s*(?:रुपैयाँ|रु\.?|डलर)", rest)
    if m2:
        cmp_ = ("जुन " if "जुन" in rest else "") + m2.group(0).strip() + (" मात्र" if "मात्र" in rest[:m2.end() + 8] else "")
        if cmp_ not in vo: cmp_ = m2.group(0).strip()
        if cmp_ not in vo: cmp_ = ""
    return {"kind": "money", "amount": span, "context": ctx, "direction": direction, "compare": cmp_, "vo": vo}

def plan_roster(vo):
    if not re.search(r"टोली|टिम|समूह|सम्झौता", vo): return None
    if vo.count(",") < 1 and " र " not in vo: return None
    m = re.search(r"(?:टोलीमा|टिममा|सम्झौतामा|समूह\s*[‘'\"]?[एबीसीडीA-D][’'\"]?\s*मा)\s*([^।]+)", vo)
    if not m: return None
    seg = m.group(1)
    items = re.split(r"[,،]|\s+र\s+|\s+तथा\s+", seg)
    junk = ("गरी", "छन्", "छ", "रहेका", "परेका", "समावेश", "समेटिएका", "लगायतका", "खेलाडीहरू", "सदस्यीय", "रहेको")
    mem = []
    for it in items:
        w = [x for x in it.strip().split() if x.strip(" ।,") not in junk]
        w = [x.strip(" ।,") for x in w]
        while w and (w[-1].endswith("छन्") or w[-1].endswith("छ") or w[-1] in junk): w = w[:-1]
        while w and w[0] in junk: w = w[1:]
        s = " ".join(w[:4]).strip()
        if s and len(s) > 2 and s in vo and not any(_verby(w_) or w_.endswith(("सँग", "मा", "बाट", "ले")) for w_ in s.split()): mem.append(s)
    if len(mem) < 3: return None
    tm = re.search(r"समूह\s*[‘'\"]?[एबीसीडीA-D][’'\"]?", vo)
    title = tm.group(0).strip() if tm else ""
    return {"kind": "roster", "title": title, "members": mem[:10], "vo": vo}

def plan_incident(vo):
    ev = next((w for w in ("पहिरो", "शव", "उद्धार", "दुर्घटना", "वर्षा", "आगलागी") if w in vo), None)
    if not ev: return None
    cm = re.search(r"(?:" + NUM_RE + r"\s*(?:हजार|लाख|सय|करोड)\s*)*" + NUM_RE + r"\s*जना", vo)
    count = ""
    if cm: count = re.sub(r"\s*जना$", "", cm.group(0)).strip()
    cs = [c.strip() for c in re.split(r"[,।]", vo) if ev in c]
    if not cs: return None
    headline = _clip(vo, cs[0], 8)
    if headline not in vo: return None
    state = ""
    sm = re.search(r"उद्धार[^,।]*जारी|जारी\s*छ|रहेको\s*छ|खटिएको\s*छ", vo)
    if sm: state = sm.group(0).strip()
    if not state:
        vm = re.search(r"(?:शव\s+)?(?:भेटिएको|फेला\s+पारेको)[^,।]*", vo)
        if vm: state = _clip(vo, vm.group(0).strip(), 4)
    if not count and not state: return None
    return {"kind": "incident", "headline": headline, "count": count, "state": state, "vo": vo}

# ---------------------------------------------------------------- gap emitters
def strip_hook(g, dark):
    at = _ats(g["vo"], [g["question"]])[0]
    return "", {"kind": "hook", "hook": {"question": g["question"], "at": at}}, []

def strip_lawstage(g, dark):
    ats = _ats(g["vo"], [s["text"] for s in g["stages"]])
    stages = [{"text": s["text"], "at": a, "done": bool(s.get("done"))} for s, a in zip(g["stages"], ats)]
    return "", {"kind": "lawstage", "lawstage": {"stages": stages, "at": ats[0]}}, []

def strip_verdict(g, dark):
    spans = [g["subject"], g["decision"]] + ([g["authority"]] if g.get("authority") else [])
    ats = _ats(g["vo"], spans)
    x = {"subject": g["subject"], "decision": g["decision"], "at": ats[0]}
    if g.get("authority"): x["authority"] = g["authority"]
    return "", {"kind": "verdict", "verdict": x}, []

def strip_rule(g, dark):
    ats = _ats(g["vo"], [g["condition"], g["consequence"]])
    return "", {"kind": "rule", "rule": {"condition": g["condition"], "consequence": g["consequence"], "at": ats[0]}}, []

def strip_schedule(g, dark):
    spans = [g["start"]] + ([g["end"]] if g.get("end") else [])
    ats = _ats(g["vo"], spans)
    x = {"start": g["start"], "startAt": ats[0], "at": ats[0]}
    if g.get("end"): x["end"] = g["end"]; x["endAt"] = ats[1]
    if g.get("place"): x["place"] = g["place"]
    if g.get("connector"): x["connector"] = g["connector"]
    return "", {"kind": "schedule", "schedule": x}, []

def strip_movement(g, dark):
    ats = _ats(g["vo"], [g["actor"], g["from"], g["to"]])
    return "", {"kind": "movement", "movement": {"from": g["from"], "to": g["to"], "actor": g["actor"], "verb": g["verb"], "at": ats[0]}}, []

def strip_result(g, dark):
    spans = [g["winner"]] + ([g["loser"]] if g.get("loser") else []) + [g["outcome"]]
    ats = _ats(g["vo"], spans)
    x = {"winner": g["winner"], "outcome": g["outcome"], "at": ats[0]}
    if g.get("loser"): x["loser"] = g["loser"]
    if g.get("context"): x["context"] = g["context"]
    return "", {"kind": "result", "result": x}, []

def strip_compare(g, dark):
    ats = _ats(g["vo"], [g["left"], g["right"]])
    x = {"left": g["left"], "right": g["right"], "at": ats[0]}
    if g.get("leftMeta"): x["leftMeta"] = g["leftMeta"]
    if g.get("rightMeta"): x["rightMeta"] = g["rightMeta"]
    return "", {"kind": "compare", "compare": x}, []

def strip_money(g, dark):
    at = _ats(g["vo"], [g["amount"]])[0]
    x = {"amount": g["amount"], "context": g["context"], "at": at}
    if g.get("direction"): x["direction"] = g["direction"]
    if g.get("compare"): x["compare"] = g["compare"]
    return "", {"kind": "money", "money": x}, []

def strip_contrast(g, dark):
    ats = _ats(g["vo"], [g["left"], g["right"]])
    return "", {"kind": "contrast", "contrast": {"left": g["left"], "right": g["right"], "bridge": g.get("bridge", ""), "at": ats[0]}}, []

def strip_roster(g, dark):
    mem = [m for m in g["members"] if m in g["vo"]] or g["members"]
    ats = _ats(g["vo"], mem)
    x = {"members": [{"text": m, "at": a} for m, a in zip(mem, ats)], "at": ats[0]}
    if g.get("title"): x["title"] = g["title"]
    return "", {"kind": "roster", "roster": x}, []

def strip_quote(g, dark):
    spans = [g["speaker"], g["claim"]] if g.get("speaker") else [g["claim"]]
    ats = _ats(g["vo"], spans)
    return "", {"kind": "quote", "quote": {"speaker": g.get("speaker", ""), "claim": g["claim"], "at": ats[0]}}, []

def strip_incident(g, dark):
    at = _ats(g["vo"], [g["headline"]])[0]
    x = {"headline": g["headline"], "at": at}
    if g.get("state"): x["state"] = g["state"]
    if g.get("count"): x["count"] = g["count"]
    return "", {"kind": "incident", "incident": x}, []


SPAN_SKIP_KEYS = {"vo", "kind", "direction"}

def spans_exact(g):
    """every rendered string in a plan must be an exact substring of the voiceover line"""
    vo = g.get("vo", "")
    def ok(x, key=""):
        if key in SPAN_SKIP_KEYS: return True
        if isinstance(x, str): return x in vo
        if isinstance(x, list): return all(ok(y) for y in x)
        if isinstance(x, dict): return all(ok(v, k) for k, v in x.items())
        return True
    return ok(g)


# ---------------------------------------------------------------- story

def find_comment(t):
    """Plain-text PINNED COMMENT section first, else workbook comment_prompt."""
    q = sec(t, "PINNED COMMENT").strip().splitlines()
    q = q[0].strip() if q else ""
    wbj = {}
    try: wbj = json.loads(sec(t, "FULL WORKBOOK JSON")) or {}
    except Exception: pass
    if not isinstance(wbj, dict): wbj = {}
    pinned = (wbj.get("pinned_comment") or q or "").strip()
    if q: return {"question": q, "pinned": pinned, "src": "PINNED COMMENT section"}
    cp = (wbj.get("comment_prompt") or "").strip()
    if cp: return {"question": cp, "pinned": pinned, "src": "FULL WORKBOOK JSON comment_prompt"}
    return {"question": "", "pinned": pinned, "src": ""}

def comment_ok(q):
    if re.search(r"[A-Za-z]", q): return False, "has Latin letters"
    if not re.search(r"[\u0900-\u097F]", q): return False, "no Devanagari"
    if len(q) > 110: return False, "too long for the card (%d chars)" % len(q)
    if "\n" in q: return False, "more than one line"
    return True, ""

def build(pkg_txt, force=False, overrides=None):
    overrides = overrides or {}
    t = pkg_txt
    rid = head(t, "REVIEW ID") or "UNKNOWN"
    red = re.search(r"^\*\*\* RED HOLD", t, re.M) is not None
    fc = head(t, "FACT CHECK")
    problems = []
    if red: problems.append("RED HOLD in script header")
    if fc and not fc.upper().startswith(("PASS", "OK", "VERIFIED")): problems.append("FACT CHECK: " + fc)
    tagged = load_json(sec(t, "TAGGED LINES"), "TAGGED LINES")
    wb = load_json(sec(t, "VISUAL WORKBOOK"), "VISUAL WORKBOOK")
    wbl = {w.get("line_id"): w for w in wb}
    cards, strips, clips = [], {}, []
    tst = {}
    for i, ln in enumerate(tagged):
        plan = ln.get("broll_plan") or {}
        lid = plan.get("line_id", i + 1)
        w = wbl.get(lid, {})
        cap = (w.get("caption_text") or "").strip()
        vo = ln["text"].strip()
        data = plan.get("on_screen_data") or (w.get("visual") or {}).get("on_screen_data") or []
        d = data[0] if data else None
        if i == 0:
            key = (d or {}).get("value", "")
            c = {"type": "hook", "headline": pill(cap or first_clause(vo), key), "sub": (d or {}).get("label", ""), "vo": vo}
        elif d:
            n = num_of(d["value"])
            if n is not None:
                c = {"type": "bignum", "dark": True, "label": d["label"], "prefix": "", "value": n, "sub": cap, "vo": vo}
            else:
                c = {"type": "scale", "number": d["value"], "headline": pill(cap or d["label"], d["value"]), "sub": d["label"], "vo": vo}
        else:
            c = {"type": "points", "title": cap or first_clause(vo), "points": [pill(first_clause(vo, 60), "")], "vo": vo}

        # ---- which bottom strip (visuals.json beats the script's own fields, beats auto)
        ov = overrides.get(str(i + 1)) or overrides.get(i + 1)
        spec = ov if ov else {k: ln[k] for k in ("visual_kind", "nodes", "places", "icon") if k in ln}
        frm = "visuals.json" if ov else ("script" if spec else "auto")
        kind = spec.get("visual_kind") or ""
        why = ""
        if kind == "concept" and not spec.get("nodes"): why = "said concept but has no nodes list"; kind = ""
        if kind == "place" and not spec.get("places"): why = "said place but has no places list"; kind = ""
        if not kind:
            auto_num = None if d else find_number(vo)
            auto_pl = find_places(vo)
            if d: kind, frm = "stat", frm + "+data"
            elif auto_num: kind, frm, d = "stat", "auto: number in line", {"label": cap or first_clause(vo, 40), "value": auto_num}
            elif auto_pl: kind, frm, spec = "place", "auto: place in line", dict(spec, places=auto_pl)
            else:
                tg = plan_text(vo, cap, tst)
                if tg: kind, frm, spec = tg["kind"], "auto: text structure", dict(spec, _tg=tg)
                else: kind = "phrase"
        print("  card", i + 1, "->", kind, "(" + frm + (", " + why if why else "") + ")")
        strip = {"kind": "graphic", "label": "", "src": ""}
        if kind == "action":
            q = plan.get("primary_query") or ln.get("broll") or ""
            clips.append({"card": i + 1, "query": q, "alt": plan.get("alt_queries", []), "what": plan.get("shot_description", ""), "quality": plan.get("quality", "")})
            strip = {"kind": "echo", "text": cap[:12] or "…"}
        elif kind == "concept":
            strip["_gen"] = {"kind": "concept", "nodes": spec["nodes"], "vo": vo}
        elif kind == "place":
            strip["_gen"] = {"kind": "place", "places": spec["places"], "vo": vo}
        elif spec.get("_tg"):
            strip["_gen"] = spec["_tg"]
        elif kind == "stat" and d:
            strip["_gen"] = plan_stat(d, vo, cap, c, spec)
            if strip["_gen"]["kind"] != "stat": print("     number already on top half -> strip shows", strip["_gen"]["kind"], "instead")
        else:
            strip["_gen"] = {"kind": "phrase", "text": cap or first_clause(vo, 40), "icon": spec.get("icon"), "vo": vo}
        c["voice_tone"] = ln.get("voice", "neutral")
        c["strip"] = strip
        cards.append(c)
    # v9.5: engagement question is not a tagged narration line.
    cq = find_comment(t)
    if cq["question"]:
        ok_, why_ = comment_ok(cq["question"])
        if ok_:
            cards.append({"type": "engage", "dark": True, "question": cq["question"], "cta": "कमेन्टमा भन्नुस्",
                          "key": "", "vo": cq["question"] + " कमेन्टमा भन्नुस्।", "voice_tone": "curious",
                          "sfx": {"land": "Message.mp3", "cta": "Click.mp3"}, "strip": {"kind": "none"}})
            print("  card", len(cards), "-> engage (comment question from " + cq["src"] + ")")
        else:
            problems.append("comment question not used as end card: " + why_)
            print("  WARNING: comment question skipped (" + why_ + "): " + cq["question"])
    else:
        print("  WARNING: no comment question found (PINNED COMMENT section / comment_prompt) -> no end card")
    story = {"id": rid, "sample": False, "voice": "ne-NP-SagarNeural", "rate": "+6%", "pitch": "-2Hz", "source_spoken": "", "comment_prompt": cq["question"], "pinned_comment": cq["pinned"], "cards": cards}
    return rid, (story, clips), problems

# ---------------------------------------------------------------- icons
ICONS = {
    "pin": '<path d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "plant": '<path d="M12 21V11"/><path d="M12 11C12 7 9 5 5 5c0 4 2 6 7 6z"/><path d="M12 14c0-3 2-5 6-5 0 3-2 5-6 5z"/>',
    "mountain": '<path d="M2 20l7-12 4 7 3-4 6 9z"/>',
    "people": '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.5 2.5-6 6-6s6 2.5 6 6"/><path d="M15 14.5c3 0 6 2 6 5.5"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h12l-2 4 2 4H5"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M12 7v10"/><path d="M9.5 9.5c0-1 1-2 2.5-2s2.5 1 2.5 2-1 1.8-2.5 2-2.5 1-2.5 2 1 2 2.5 2 2.5-1 2.5-2"/>',
    "chart": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-8"/><path d="M22 20H2"/>',
    "medal": '<circle cx="12" cy="15" r="5"/><path d="M8.5 3l3.5 7 3.5-7"/>',
    "building": '<path d="M4 21V5h10v16"/><path d="M14 10h6v11"/><path d="M7 9h4M7 13h4M7 17h4"/>',
    "road": '<path d="M8 3L5 21"/><path d="M16 3l3 18"/><path d="M12 5v3M12 11v3M12 17v3"/>',
    "star": '<path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.2 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
    "hospital": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/>',
    "school": '<path d="M3 6c3-1.5 6-1.5 9 0v13c-3-1.5-6-1.5-9 0z"/><path d="M21 6c-3-1.5-6-1.5-9 0v13c3-1.5 6-1.5 9 0z"/>',
    "water": '<path d="M12 3s6 6.5 6 11a6 6 0 01-12 0c0-4.5 6-11 6-11z"/><path d="M9 15a3 3 0 003 3"/>',
    "rain": '<path d="M7 15a4 4 0 010-8 5 5 0 019.6-1A4 4 0 0117 15z"/><path d="M8 18l-1 3M12 18l-1 3M16 18l-1 3"/>',
    "bolt": '<path d="M13 2L5 14h6l-1 8 8-12h-6z"/>',
    "plane": '<path d="M2 13l20-8-6 15-4-6z"/><path d="M12 14l10-9"/>',
    "bus": '<rect x="4" y="4" width="16" height="13" rx="2"/><path d="M4 11h16"/><circle cx="8" cy="19.5" r="1.5"/><circle cx="16" cy="19.5" r="1.5"/>',
    "law": '<path d="M12 3v18M7 21h10M5 7h14"/><path d="M5 7l-3 6a3 3 0 006 0z"/><path d="M19 7l-3 6a3 3 0 006 0z"/>',
    "vote": '<rect x="4" y="10" width="16" height="11" rx="1"/><path d="M9 10V4h6v6"/><path d="M8 15h8"/>',
    "fire": '<path d="M12 22c4 0 7-3 7-7 0-4-3-6-4-9-1 3-3 4-4 4 0-2-1-5-3-7 0 4-3 6-3 12 0 4 3 7 7 7z"/>',
    "tree": '<path d="M12 22v-6"/><path d="M12 2l6 9h-3l4 5H5l4-5H6z"/>',
    "factory": '<path d="M3 21V11l6 3V11l6 3V6h4v15z"/><path d="M3 21h18"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "heart": '<path d="M12 20s-8-5-8-11a4.5 4.5 0 018-2.8A4.5 4.5 0 0120 9c0 6-8 11-8 11z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "doc": '<path d="M6 2h9l4 4v16H6z"/><path d="M15 2v4h4M9 11h7M9 15h7M9 19h4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "run": '<circle cx="15" cy="4" r="2"/><path d="M8 21l3-6 3 2v5"/><path d="M11 15l1.5-6.5L17 12l3 1"/><path d="M12.5 8.5L9 8l-3 3"/>',
}
KEYS = [("खानेपानी","water"),("बाढी","water"),("पहिरो","mountain"),("वर्षा","rain"),("मनसुन","rain"),("पानी","water"),
        ("आगलागी","fire"),("आगो","fire"),("अस्पताल","hospital"),("स्वास्थ्य","hospital"),("उपचार","hospital"),
        ("विद्यालय","school"),("शिक्षा","school"),("विद्यार्थी","school"),("बिजुली","bolt"),("ऊर्जा","bolt"),("विद्युत","bolt"),
        ("उडान","plane"),("विमान","plane"),("हवाई","plane"),("यातायात","bus"),("सवारी","bus"),("अदालत","law"),("कानुन","law"),
        ("मुद्दा","law"),("निर्वाचन","vote"),("मतदान","vote"),("चुनाव","vote"),("प्रहरी","shield"),("सुरक्षा","shield"),
        ("जंगल","tree"),("वातावरण","tree"),("उद्योग","factory"),("कारखाना","factory"),("उत्पादन","factory"),
        ("अन्तर्राष्ट्रिय","globe"),("विदेश","globe"),("इन्टरनेट","phone"),("डिजिटल","phone"),("मोबाइल","phone"),
        ("नीति","doc"),("निर्णय","doc"),("प्रतिवेदन","doc"),("मिति","calendar"),
        ("पर्यटन","mountain"),("दौड","run"),("धावक","run"),("खेल","medal"),("ग्रामीण","home"),("गाउँ","home"),("कृषि","plant"),("किसान","plant"),
        ("आर्थिक","coin"),("अर्थतन्त्र","coin"),("अर्थमन्त्री","coin"),("रोजगार","people"),("युवा","people"),("जनता","people"),
        ("सहभागी","people"),("नागरिक","people"),("सडक","road"),("सरकार","building"),("मन्त्रालय","building"),("कार्यालय","building"),
        ("बजेट","coin"),("विकास","chart"),("वृद्धि","chart")]

def icon_for(text, default="star"):
    for k, v in KEYS:
        if k in text: return v
    return default

def _svg(name, color, size, sw=1.6):
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round" style="overflow:visible">%s</svg>'
            % (size, size, color, sw, ICONS.get(name, ICONS["star"])))

PIN_D = "M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z"
def _pin(color, size, hole):
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" style="overflow:visible"><path d="%s" fill="%s"/><circle cx="12" cy="10" r="3" fill="%s"/></svg>'
            % (size, size, PIN_D, color, hole))

def icons_for_anim(names):
    """icon markup with pathLength=1 on every shape so Remotion can 'draw' them."""
    out = {}
    for n in set(names) | {"star"}:
        s = ICONS.get(n, ICONS["star"])
        out[n] = re.sub(r"<(path|circle|rect|line|polyline|ellipse)\b", r'<\1 pathLength="1"', s)
    return out

# ---------------------------------------------------------------- shared layout (AnimatedStrip.ts uses the same numbers)
# Safe area inside the 1080x650 strip: x 80..1000, y 70..580 (corner marks sit outside it).
# Every layout below is centred on that area so the drawing fills the strip with even margins.
CONCEPT_D = {1: 260, 2: 240, 3: 220, 4: 164}
CONCEPT_CY = 262
def concept_layout(n):
    slot = 920 / n; d = CONCEPT_D[n]
    return [80 + slot * k + slot / 2 for k in range(n)], slot, d, CONCEPT_CY

def place_layout(places):
    n = len(places)
    if n == 1: return [540.0], [200], 300
    return [290.0, 790.0], [170 if p.get("focus") else 124 for p in places], 300

def bez(x1, y1, cx, cy, x2, y2, t):
    a = (1 - t) ** 2; b = 2 * (1 - t) * t; c = t * t
    return a * x1 + b * cx + c * x2, a * y1 + b * cy + c * y2

def units_layout(n):
    """grid for n tokens: pick the column count that gives the biggest token in a 900x330 box."""
    best = None
    for cols in range(1, n + 1):
        rows = -(-n // cols)
        step = min(900 / cols, 330 / rows)
        if best is None or step > best[0] + 0.01: best = (step, cols, rows)
    step, cols, rows = best
    step = min(step, 190); size = round(step * 0.78)
    gw, gh = cols * step, rows * step
    cap_h = 92; gap = 34
    top = round(325 - (gh + gap + cap_h) / 2)
    return {"cols": cols, "rows": rows, "step": round(step, 2), "size": size,
            "x0": round(540 - gw / 2, 2), "y0": top, "capY": round(top + gh + gap)}

TRACK = {"x1": 120, "x2": 960, "y": 300}
CAL = {"x0": 80, "cw": 120, "gap": 13.33, "top": 216, "ch": 300, "headY": 100}
WAFFLE = {"x0": 110, "y0": 115, "cell": 36, "gap": 6}

def _corners(ink):
    s, ix, iy = 40, 54, 30
    pts = ["M%d %dV%dH%d" % (ix, iy + s, iy, ix + s), "M%d %dH%dV%d" % (W - ix - s, iy, W - ix, iy + s),
           "M%d %dV%dH%d" % (ix, HGT - iy - s, HGT - iy, ix + s), "M%d %dH%dV%d" % (W - ix - s, HGT - iy, W - ix, HGT - iy - s)]
    return ('<svg class="a" style="left:0;top:0" width="1080" height="650" fill="none" stroke-width="5" stroke-linecap="square">'
            + "".join('<path d="%s" stroke="%s"/>' % (p, RED) for p in pts) + "</svg>")

def _page(body, dark):
    ink = "#ECE7DC" if dark else "#1E1C1A"
    css = ("@font-face{font-family:M;src:url('" + (FONTS / "Mukta-ExtraBold.ttf").resolve().as_uri() + "')}"
           "html,body{margin:0;background:transparent}#b{width:1080px;height:650px;position:relative;overflow:hidden;font-family:M,sans-serif;color:" + ink + "}"
           ".a{position:absolute}.c{text-align:center;line-height:1.25}.red{color:" + RED + "}")
    return "<html><head><meta charset=utf-8><style>" + css + "</style></head><body><div id=b>" + _corners(ink) + body + "</div></body></html>"

def _fit(key, maxw, maxh):
    return 'data-key="%s" data-fit="%d" data-fith="%d"' % (key, maxw, maxh)

# ---------------------------------------------------------------- choosing what a number card's strip shows
MONTHS = ["बैशाख", "वैशाख", "जेठ", "असार", "साउन", "श्रावण", "भदौ", "असोज", "आश्विन", "कात्तिक", "कार्तिक", "मंसिर", "मङ्सिर",
          "पुस", "पौष", "माघ", "फागुन", "चैत", "चैत्र"]
WEEKDAYS = [("आइतबार", "आइत"), ("सोमबार", "सोम"), ("मंगलबार", "मंगल"), ("बुधबार", "बुध"), ("बिहीबार", "बिही"), ("शुक्रबार", "शुक्र"), ("शनिबार", "शनि")]
WD_ALT = {"मङ्गलबार": 2, "बिहिबार": 4}
DIST_UNITS = ("किलोमिटर", "किमि", "मिटर")
COUNT_ICON = [(("जिल्ला", "स्थान", "पालिका", "प्रदेश", "देश", "सहर", "बस्ती", "गाउँ", "वडा"), "pin"),
              (("घर", "परिवार"), "home"), (("विद्यालय", "कलेज"), "school"), (("अस्पताल",), "hospital"),
              (("धावक", "खेलाडी"), "run"), (("जना", "व्यक्ति", "नागरिक", "विद्यार्थी", "मजदुर", "कामदार", "युवा", "महिला", "बालबालिका"), "people"),
              (("सवारी", "बस", "गाडी"), "bus"), (("उडान", "विमान"), "plane"), (("रुख", "बिरुवा"), "tree"), (("पटक", "दिन"), "calendar")]
NOT_COUNTABLE = ("प्रतिशत", "%", "करोड", "अर्ब", "लाख", "हजार", "रुपैयाँ", "रुपियाँ", "डलर", "मेगावाट", "टन", "केजी", "किलो", "डिग्री",
                 "घण्टा", "वर्ष", "महिना", "बिघा", "रोपनी") + DIST_UNITS

def _dev(s): return str(s).translate(DEV)
def _digits(s): return re.sub(r"[^०-९]", "", _dev(s))

def top_text(c):
    """everything the card's TOP half can show (so the strip never repeats it)."""
    bits = [c.get(k) for k in ("headline", "sub", "title", "label", "number")] + list(c.get("points") or [])
    if c.get("value") is not None: bits.append(str(c["value"]))
    return _dev(" ".join(str(b) for b in bits if b)).replace("{{", "").replace("}}", "").replace(",", "")

def shows_number(value, c):
    dg = _digits(value)
    if not dg: return False
    if c.get("type") in ("bignum", "scale"): return True
    return re.search(r"(?<![०-९])" + dg + r"(?![०-९])", re.sub(r"[^०-९]", " ", top_text(c))) is not None

def month_in(s):
    """whole-token month name (v9.3: 'पुस' no longer matches inside 'पुस्तक')"""
    for m in MONTHS:
        if has_word(s, m): return m
    return None

def weekday_in(vo):
    for k, (full, _) in enumerate(WEEKDAYS):
        if full in vo: return k
    for w, k in WD_ALT.items():
        if w in vo: return k
    return None

STOP = {"यो", "त्यो", "सो", "उक्त", "र", "तथा", "भने", "पनि", "नै", "दौड", "यात्रा", "प्रतियोगिता", "कार्यक्रम", "सुरु", "सम्म", "हो",
        "छ", "थियो", "गरी", "गरेर", "भएर", "जुन", "जहाँ", "एक", "दुई"}
def _place_word(toks, k, stem):
    """stem of toks[k] plus the word before it when that word is part of the name (विश्वशान्ति स्तूप)."""
    name = stem
    if k > 0:
        pv = toks[k - 1]
        if (pv not in STOP and not re.search(r"[०-९\d]", pv) and not pv.endswith(("को", "का", "की", "दै", "ई", "एर", "ने", "ो", "बाट", "देखि", "सम्म", "मा", "लाई", "ले"))
                and _base(pv, UNITS) is None and len(pv) > 1):
            name = pv + " " + stem
    return name

def route_ends(vo):
    """'... X बाट सुरु भई ... Y मा पुगेर सकिनेछ' -> (X, Y). Either can be ''."""
    toks = _tokens(vo); a = b = ""
    for k, t in enumerate(toks):
        for suf in ("बाट", "देखि"):
            if not a and t.endswith(suf) and len(t) > len(suf) + 1:
                a = _place_word(toks, k, t[:-len(suf)])
        if not b and t.endswith("सम्म") and len(t) > 5:
            b = _place_word(toks, k, t[:-4])
        if not b and t.endswith("मा") and len(t) > 3 and k + 1 < len(toks) and toks[k + 1].startswith(("पुग", "सकि", "टुङ्ग", "टुंग", "समाप्त")):
            b = _place_word(toks, k, t[:-2])
    return a, b

def strip_number(text, value):
    """the line's text without the number (and its unit) the top half already shows."""
    t = text.replace("{{", "").replace("}}", "").replace(value.strip(), " ")
    toks = t.split(); out = []; k = 0
    while k < len(toks):
        if re.search(r"[०-९\d]", toks[k]):
            k += 1
            while k < len(toks) and _base(toks[k].strip(PUNCT), UNITS): k += 1   # '५ लाख रुपैयाँ' goes as one
            continue
        out.append(toks[k]); k += 1
    return " ".join(out).strip(" ,।")

def plan_stat(d, vo, cap, c, spec):
    """number line -> which strip. A number the top half already shows is NOT drawn again:
       the strip shows what the number means instead (calendar day, route, tokens, share)."""
    value = str(d.get("value", "")).strip(); label = str(d.get("label", "")).strip()
    pv = parse_value(value); dup = shows_number(value, c)
    unit = pv["unit"]; x = pv.get("num")
    raw = None
    try: raw = float(_digits(value).translate(LAT)) if _digits(value) else None
    except ValueError: raw = None
    mon = month_in(value) or (month_in(label + " " + vo) if label in ("मिति", "दिन", "गते") else None)
    base = {"label": label, "value": value, "vo": vo, "cap": cap}
    if mon and raw and 1 <= raw <= 32 and float(raw).is_integer():
        return dict(base, kind="calendar", month=mon, day=int(raw), icon=spec.get("icon") or icon_for(vo, "calendar"))
    if pv["percent"] is not None:
        return dict(base, kind="waffle" if dup else "stat")
    if x is not None and unit.startswith(DIST_UNITS) and x > 0:
        fr, to = route_ends(vo)
        if not (fr or to):
            pl = find_places(vo)
            if len(pl) == 2: fr, to = pl[0]["ne"], pl[1]["ne"]
            elif len(pl) == 1: to = pl[0]["ne"]
        return dict(base, kind="track", total=x, unit=unit, frm=fr, to=to)
    words = (unit + " " + label).strip()
    if (dup and x is not None and float(x).is_integer() and 2 <= x <= 48 and not any(u in words for u in NOT_COUNTABLE)):
        icon = spec.get("icon")
        if not icon:
            for keys, ic in COUNT_ICON:
                if any(k in words for k in keys): icon = ic; break
        return dict(base, kind="units", n=int(x), icon=icon or icon_for(words + " " + vo))
    if dup:
        txt = strip_number(cap, value) if cap else ""
        if len(txt.split()) < 2: txt = strip_number(first_clause(vo, 60), value)
        if len(txt.split()) < 2: txt = label or first_clause(vo, 40)
        return {"kind": "phrase", "text": txt, "icon": spec.get("icon"), "vo": vo}
    return dict(base, kind="stat")

# ---------------------------------------------------------------- the strips: poster HTML + motion spec
def strip_stat(g, dark):
    ink = "#ECE7DC" if dark else "#1E1C1A"
    pv = parse_value(g["value"]); label = g.get("label", "")
    at = timeline(g["vo"], [g["value"].strip()], lo=0.03, hi=0.5)[0]
    anim = {"kind": "stat", "stat": dict(pv, label=label, at=at)}
    if pv["percent"] is not None:
        cx, cy, r = 300, 325, 200; pct = pv["percent"]
        body = ('<svg class="a" style="left:0;top:0" width="1080" height="650" fill="none">'
                '<circle cx="%d" cy="%d" r="%d" stroke="%s" stroke-opacity=".14" stroke-width="30"/>'
                '<circle cx="%d" cy="%d" r="%d" stroke="%s" stroke-width="30" stroke-linecap="round" '
                'stroke-dasharray="%.2f 9999" transform="rotate(-90 %d %d)"/></svg>' % (cx, cy, r, ink, cx, cy, r, RED, 2 * 3.14159265 * r * pct / 100, cx, cy)
                + '<div class="a c red" %s style="left:130px;top:250px;width:340px;font-size:128px;white-space:nowrap;line-height:1.1">%s<span style="font-size:.55em">%s</span></div>'
                % (_fit("num", 340, 150), H.escape(pv["numText"]), H.escape(pv["unit"].replace("प्रतिशत", "%")))
                + '<div class="a" style="left:590px;top:250px;width:110px;height:8px;background:%s"></div>' % RED
                + '<div class="a" %s style="left:590px;top:282px;width:420px;font-size:72px;line-height:1.2">%s</div>' % (_fit("label", 420, 260), H.escape(label)))
    else:
        body = ('<div class="a c red" %s style="left:80px;top:96px;width:920px;font-size:240px;white-space:nowrap;line-height:1.1">%s'
                '<span style="font-size:.34em;color:%s;margin-left:.14em">%s</span></div>' % (_fit("num", 920, 290), H.escape(pv["numText"]), ink, H.escape(pv["unit"]))
                + '<div class="a" style="left:420px;top:410px;width:240px;height:8px;background:%s"></div>' % RED
                + '<div class="a c" %s style="left:90px;top:440px;width:900px;font-size:76px">%s</div>' % (_fit("label", 900, 120), H.escape(label)))
    return body, anim, []

def strip_calendar(g, dark):
    """a week of the month with the day lifted out in red: the day of the week, not the number again."""
    ink = "#ECE7DC" if dark else "#1E1C1A"
    day = g["day"]; mon = g["month"]; wd = weekday_in(g["vo"])
    first = max(1, day - 3) if day <= 28 else day - 6
    days = list(range(first, first + 7)); hi = days.index(day)
    wds = [WEEKDAYS[(wd + k - hi) % 7][1] for k in range(7)] if wd is not None else None
    at = timeline(g["vo"], [g["value"].strip()], lo=0.05, hi=0.5)[0]
    head_txt = mon + ((" · " + WEEKDAYS[wd][0]) if wd is not None else "")
    L = CAL; parts = ['<div class="a c" %s style="left:80px;top:%dpx;width:920px;font-size:64px;line-height:1.2">%s</div>'
                      % (_fit("head", 920, 90), L["headY"], H.escape(mon) + ((' <span class="red">' + H.escape(WEEKDAYS[wd][0]) + "</span>") if wd is not None else ""))]
    for k, dd in enumerate(days):
        x = L["x0"] + k * (L["cw"] + L["gap"]); on = k == hi
        parts.append('<div class="a" style="left:%.1fpx;top:%dpx;width:%dpx;height:%dpx;border-radius:22px;box-sizing:border-box;%s"></div>'
                     % (x, L["top"], L["cw"], L["ch"], ("background:%s" % RED) if on else ("border:3px solid %s;opacity:.28" % ink)))
        col = ON_RED if on else ink
        if wds: parts.append('<div class="a c" style="left:%.1fpx;top:%dpx;width:%dpx;font-size:40px;color:%s;opacity:%s">%s</div>'
                             % (x, L["top"] + 22, L["cw"], col, "1" if on else ".55", H.escape(wds[k])))
        parts.append('<div class="a c" style="left:%.1fpx;top:%dpx;width:%dpx;font-size:%dpx;color:%s;opacity:%s">%s</div>'
                     % (x, L["top"] + (78 if wds else 60), L["cw"], 76, col, "1" if on else ".5", _dev(dd)))
        if on: parts.append('<div class="a" style="left:%.1fpx;top:%dpx">%s</div>' % (x + L["cw"] / 2 - 32, L["top"] + L["ch"] - 92, _svg(g["icon"], ON_RED, 64, 1.8)))
    anim = {"kind": "calendar", "calendar": {"month": mon, "head": head_txt, "weekday": WEEKDAYS[wd][0] if wd is not None else "",
                                             "days": [_dev(x) for x in days], "wds": wds, "hi": hi, "icon": g["icon"], "at": at, "layout": L}}
    return "".join(parts), anim, [g["icon"]]

def _tick_values(total):
    if total <= 12 and float(total).is_integer(): return list(range(0, int(total) + 1))
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10 ** 4, 10 ** 5, 10 ** 6, 10 ** 7, 10 ** 8, 10 ** 9) if total / s <= 8)
    vals = [v * step for v in range(0, int(total // step) + 1)]
    if total - vals[-1] > step * 0.35: vals.append(total)
    else: vals[-1] = total
    return vals

def strip_track(g, dark):
    """distance: the route itself. start and finish names, km ticks, a runner travels it while the line is spoken."""
    ink = "#ECE7DC" if dark else "#1E1C1A"
    total = g["total"]; fr = g.get("frm") or ""; to = g.get("to") or ""
    T = TRACK; x1, x2, y = T["x1"], T["x2"], T["y"]
    vals = _tick_values(total)
    def fmtv(v): return _dev(("%g" % v) if not float(v).is_integer() else str(int(v)))
    ticks = [{"t": fmtv(v), "x": round(x1 + (x2 - x1) * v / total, 1)} for v in vals]
    ticks[-1]["t"] = ""          # the finish point carries the flag, not the number the top half already shows
    words = [w for w in (fr, to) if w]
    ats = timeline(g["vo"], words, lo=0.06, hi=0.8, gap=0.2) if words else []
    a0 = ats[0] if fr else 0.08
    a1 = (ats[-1] if to else 0.8) + 0.06
    a1 = max(a1, a0 + 0.3)
    unit_word = "किलोमिटर" if g["unit"].startswith(("किलोमिटर", "किमि")) else "मिटर"
    cap = (g.get("label") or "").strip()
    cap = (cap + " · " + unit_word) if cap and cap != unit_word else unit_word
    parts = ['<div class="a" style="left:80px;top:96px;width:60px;height:8px;background:%s"></div>' % RED,
             '<div class="a" %s style="left:156px;top:70px;width:700px;font-size:50px;line-height:1.2;opacity:.75">%s</div>' % (_fit("cap", 700, 70), H.escape(cap)),
             '<div class="a" style="left:%dpx;top:%dpx;width:%dpx;height:14px;border-radius:7px;background:%s;opacity:.16"></div>' % (x1, y - 7, x2 - x1, ink),
             '<div class="a" style="left:%dpx;top:%dpx;width:%dpx;height:14px;border-radius:7px;background:%s"></div>' % (x1, y - 7, x2 - x1, RED)]
    for tk in ticks:
        parts.append('<div class="a" style="left:%.1fpx;top:%dpx;width:4px;height:22px;background:%s;opacity:.5"></div>' % (tk["x"] - 2, y + 18, ink))
        if tk["t"]: parts.append('<div class="a c" style="left:%.1fpx;top:%dpx;width:80px;font-size:46px;opacity:.6">%s</div>' % (tk["x"] - 40, y + 44, tk["t"]))
    parts.append('<div class="a" style="left:%dpx;top:%dpx;width:40px;height:40px;border-radius:50%%;background:%s;box-sizing:border-box;border:9px solid %s"></div>' % (x1 - 20, y - 20, ink, "#F3EEE3" if not dark else "#1E1C1A"))
    parts.append('<div class="a" style="left:%dpx;top:%dpx">%s</div>' % (x2 - 85, y - 150, _pin(RED, 170, "#F3EEE3" if not dark else "#1E1C1A")))
    if fr: parts.append('<div class="a" %s style="left:80px;top:%dpx;width:440px;font-size:68px;line-height:1.15">%s</div>' % (_fit("from", 440, 160), y + 108, H.escape(fr)))
    if to: parts.append('<div class="a" %s style="left:560px;top:%dpx;width:440px;font-size:68px;line-height:1.15;text-align:right;color:%s">%s</div>' % (_fit("to", 440, 160), y + 108, RED, H.escape(to)))
    anim = {"kind": "track", "track": {"ticks": ticks, "from": fr, "to": to, "cap": cap, "a0": round(a0, 3), "a1": round(min(a1, 0.92), 3), "layout": T}}
    return "".join(parts), anim, []

def strip_units(g, dark):
    """a count the top half shows (१८ जिल्ला) -> that many tokens, so the size of it is seen, not read twice."""
    ink = "#ECE7DC" if dark else "#1E1C1A"
    n = g["n"]; L = units_layout(n); icon = g["icon"]
    at = timeline(g["vo"], [g["value"].strip()], lo=0.04, hi=0.5)[0]
    label = strip_number(g.get("label") or "", g["value"])
    if not label: label = strip_number(g.get("cap") or first_clause(g["vo"], 60), g["value"])
    if not label or re.search(r"[A-Za-z]", label): label = first_clause(g["vo"], 40)
    parts = []
    for k in range(n):
        r, cc = divmod(k, L["cols"]); last_row_n = n - (L["rows"] - 1) * L["cols"]
        off = (L["cols"] - last_row_n) * L["step"] / 2 if r == L["rows"] - 1 else 0
        x = L["x0"] + off + cc * L["step"] + (L["step"] - L["size"]) / 2; y = L["y0"] + r * L["step"] + (L["step"] - L["size"]) / 2
        if icon == "pin": parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx">%s</div>' % (x, y, _pin(RED, L["size"], "#F3EEE3" if not dark else "#1E1C1A")))
        else: parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx">%s</div>' % (x, y, _svg(icon, RED, L["size"], 1.7)))
    parts.append('<div class="a c" %s style="left:90px;top:%dpx;width:900px;font-size:72px">%s</div>' % (_fit("label", 900, 100), L["capY"], H.escape(label)))
    anim = {"kind": "units", "units": {"n": n, "icon": icon, "label": label, "at": at, "layout": L}}
    return "".join(parts), anim, [icon]

def strip_waffle(g, dark):
    """a share the top half shows (७२%) -> 100 squares, that many turn red."""
    ink = "#ECE7DC" if dark else "#1E1C1A"
    pct = parse_value(g["value"])["percent"]; L = WAFFLE
    at = timeline(g["vo"], [g["value"].strip()], lo=0.04, hi=0.5)[0]
    label = strip_number(g.get("cap") or "", g["value"]) or g.get("label") or ""
    parts = []
    for k in range(100):
        r, cc = divmod(k, 10)
        on = k < round(pct)
        parts.append('<div class="a" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;border-radius:7px;background:%s;opacity:%s"></div>'
                     % (L["x0"] + cc * (L["cell"] + L["gap"]), L["y0"] + (9 - r) * (L["cell"] + L["gap"]), L["cell"], L["cell"], RED if on else ink, "1" if on else ".14"))
    parts.append('<div class="a" style="left:590px;top:230px;width:110px;height:8px;background:%s"></div>' % RED)
    parts.append('<div class="a" %s style="left:590px;top:262px;width:420px;font-size:72px;line-height:1.2">%s</div>' % (_fit("label", 420, 280), H.escape(label)))
    anim = {"kind": "waffle", "waffle": {"pct": pct, "label": label, "at": at, "layout": L}}
    return "".join(parts), anim, []

def strip_concept(g, dark):
    ink = "#ECE7DC" if dark else "#1E1C1A"
    nodes = [dict(ne=str(x.get("ne", "")).strip(), icon=x.get("icon") or icon_for(str(x.get("ne", "")))) for x in g["nodes"][:4]]
    nodes = [x for x in nodes if x["ne"]] or [{"ne": "…", "icon": "star"}]
    ats = timeline(g["vo"], [x["ne"] for x in nodes])
    for x, a in zip(nodes, ats): x["at"] = a
    n = len(nodes); cxs, slot, dd, cy = concept_layout(n); r = dd / 2; parts = []
    for k, nd in enumerate(nodes):
        cx = cxs[k]; last = k == n - 1
        parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx;width:%dpx;height:%dpx;border-radius:50%%;box-sizing:border-box;border:8px solid %s;background:%s"></div>'
                     % (cx - r, cy - r, dd, dd, RED if last else ink, RED if last else "transparent"))
        isz = dd * 0.52
        parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx">%s</div>' % (cx - isz / 2, cy - isz / 2, _svg(nd["icon"], ON_RED if last else ink, isz)))
        parts.append('<div class="a c" %s style="left:%.1fpx;top:%.1fpx;width:%dpx;font-size:68px">%s</div>'
                     % (_fit("n%d" % k, slot - 24, 160), cx - (slot - 24) / 2, cy + r + 30, slot - 24, H.escape(nd["ne"])))
        if not last:
            x1 = cx + r + 12; x2 = cxs[k + 1] - r - 12; L = x2 - x1
            parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx;width:%.1fpx;height:8px;background:%s"></div>' % (x1, cy - 4, max(0, L - 18), RED))
            parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx;width:0;height:0;border-left:24px solid %s;border-top:16px solid transparent;border-bottom:16px solid transparent"></div>' % (x2 - 24, cy - 16, RED))
    return "".join(parts), {"kind": "concept", "concept": {"nodes": nodes}}, [x["icon"] for x in nodes]

def strip_place(g, dark):
    ink = "#ECE7DC" if dark else "#1E1C1A"
    pls = [dict(ne=str(p.get("ne", "")).strip(), sub=str(p.get("sub", "") or "").strip(), focus=bool(p.get("focus"))) for p in g["places"][:2]]
    pls = [p for p in pls if p["ne"]] or [{"ne": "…", "sub": "", "focus": True}]
    if len(pls) == 1: pls[0]["focus"] = True
    elif not any(p["focus"] for p in pls): pls[-1]["focus"] = True
    for p, a in zip(pls, timeline(g["vo"], [p["ne"] for p in pls], lo=0.05, hi=0.6, gap=0.12)): p["at"] = a
    cxs, szs, tip = place_layout(pls); parts = []
    dots = ('<div class="a" style="left:0;top:0;width:1080px;height:650px;opacity:.55;'
            'background-image:radial-gradient(circle,%s 1.8px,transparent 2.2px);background-size:36px 36px;background-position:18px 8px;'
            '-webkit-mask-image:radial-gradient(ellipse 62%% 72%% at 50%% 48%%,#000 30%%,transparent 78%%);mask-image:radial-gradient(ellipse 62%% 72%% at 50%% 48%%,#000 30%%,transparent 78%%)"></div>'
            % ("rgba(236,231,220,.35)" if dark else "rgba(30,28,26,.28)"))
    parts.append(dots)
    if len(pls) == 2:
        hy = [tip - sz * 0.875 + sz * 10 / 24 for sz in szs]
        svg = ['<svg class="a" style="left:0;top:0" width="1080" height="650">']
        for j in range(1, 36):
            x, y = bez(cxs[0], hy[0], 540, 40, cxs[1], hy[1], j / 36)
            svg.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" fill-opacity=".55"/>' % (x, y, ink))
        svg.append("</svg>"); parts.append("".join(svg))
    for k, p in enumerate(pls):
        cx, sz = cxs[k], szs[k]
        parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx;width:%.1fpx;height:20px;border-radius:50%%;background:%s;opacity:.18"></div>' % (cx - sz * 0.27, tip - 8, sz * 0.54, ink))
        parts.append('<div class="a" style="left:%.1fpx;top:%.1fpx">%s</div>' % (cx - sz / 2, tip - sz * 0.875, _pin(RED if p["focus"] else ink, sz, "#F3EEE3" if not dark else "#1E1C1A")))
        if len(pls) == 1:
            parts.append('<div class="a c" %s style="left:90px;top:%dpx;width:900px;font-size:128px">%s</div>' % (_fit("p0", 900, 170), tip + 22, H.escape(p["ne"])))
            if p["sub"]: parts.append('<div class="a c" %s style="left:90px;top:%dpx;width:900px;font-size:56px;opacity:.72">%s</div>' % (_fit("sub0", 900, 80), tip + 190, H.escape(p["sub"])))
        else:
            parts.append('<div class="a c" %s style="left:%.1fpx;top:%dpx;width:460px;font-size:%dpx;color:%s">%s</div>'
                         % (_fit("p%d" % k, 460, 130), cx - 230, tip + 28, 92 if p["focus"] else 76, RED if p["focus"] else ink, H.escape(p["ne"])))
            if p["sub"]: parts.append('<div class="a c" %s style="left:%.1fpx;top:%dpx;width:460px;font-size:46px;opacity:.72">%s</div>'
                                      % (_fit("sub%d" % k, 460, 70), cx - 230, tip + 160, H.escape(p["sub"])))
    return "".join(parts), {"kind": "place", "place": {"places": pls}}, []

def strip_phrase(g, dark):
    ink = "#ECE7DC" if dark else "#1E1C1A"
    raw = g["text"].strip()
    kw = re.search(r"\{\{(.+?)\}\}", raw)
    text = raw.replace("{{", "").replace("}}", "")
    words = text.split() or ["…"]
    icon = g.get("icon") or icon_for(text, None) or icon_for(g["vo"])
    key = -1
    if kw:
        for k, w in enumerate(words):
            if kw.group(1).split()[0] in w: key = k; break
    if key < 0:
        for k, w in enumerate(words):
            if re.search(r"[०-९\d]", w) or any(kk in w for kk, _ in KEYS): key = k; break
    if key < 0: key = max(range(len(words)), key=lambda k: len(words[k].strip(PUNCT)))
    ats = timeline(g["vo"], [w.strip(PUNCT) for w in words], lo=0.06, hi=0.6, gap=0.035)
    wl = [{"t": w, "key": k == key, "at": a} for k, (w, a) in enumerate(zip(words, ats))]
    cx, cy, r = 280, 325, 190; isz = 200
    parts = ['<div class="a" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx;border-radius:50%%;background:%s"></div>'
             % (cx - r, cy - r, 2 * r, 2 * r, RED),
             '<div class="a" style="left:%dpx;top:%dpx">%s</div>' % (cx - isz // 2, cy - isz // 2, _svg(icon, ON_RED, isz, 1.5))]
    spans = []
    for x in wl:
        if x["key"]:
            spans.append('<span style="position:relative;display:inline-block"><span style="position:absolute;left:-.14em;right:-.14em;bottom:.08em;height:.22em;background:%s;border-radius:.06em"></span>'
                         '<span style="position:relative;color:%s">%s</span></span>' % (RED, RED, H.escape(x["t"])))
        else:
            spans.append('<span style="display:inline-block">%s</span>' % H.escape(x["t"]))
    parts.append('<div class="a" style="left:530px;top:70px;width:480px;height:510px;display:flex;align-items:center">'
                 '<div %s style="width:480px;display:flex;flex-wrap:wrap;column-gap:.26em;font-size:100px;line-height:1.28">%s</div></div>'
                 % (_fit("ph", 480, 500), "".join(spans)))
    return "".join(parts), {"kind": "phrase", "phrase": {"words": wl, "icon": icon, "at": ats[0]}}, [icon]

MAKERS = {"stat": strip_stat, "concept": strip_concept, "place": strip_place, "phrase": strip_phrase,
          "calendar": strip_calendar, "track": strip_track, "units": strip_units, "waffle": strip_waffle,
          "chain": strip_chain, "who": strip_who, "evidence": strip_evidence, "voiceprint": strip_voiceprint,
          "hook": strip_hook, "lawstage": strip_lawstage, "verdict": strip_verdict, "rule": strip_rule,
          "schedule": strip_schedule, "movement": strip_movement, "result": strip_result, "compare": strip_compare,
          "money": strip_money, "contrast": strip_contrast, "roster": strip_roster, "quote": strip_quote, "incident": strip_incident}

# ---------------------------------------------------------------- drawing (one browser for the whole story)
FIT_JS = """async () => { await document.fonts.load('80px M'); await document.fonts.ready; const out = {};
  document.querySelectorAll('[data-fit]').forEach(e => { const maxw = +e.dataset.fit, maxh = +e.dataset.fith;
    let s = parseFloat(getComputedStyle(e).fontSize);
    while ((e.scrollWidth > maxw || e.scrollHeight > maxh) && s > 28) { s -= 2; e.style.fontSize = s + 'px'; }
    if (e.dataset.key) out[e.dataset.key] = s; });
  return out; }"""

class Painter:
    """Draw with Chrome/Edge (same engine as the cards, so Nepali letters are shaped correctly)."""
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start(); self.b = None
        for ch in ("msedge", "chrome", None):
            try:
                self.b = self.pw.chromium.launch(channel=ch) if ch else self.pw.chromium.launch(); break
            except Exception:
                continue
        if self.b is None:
            self.pw.stop(); sys.exit("No Edge/Chrome found. Run: python -m playwright install chromium")
        self.pg = self.b.new_page(viewport={"width": W, "height": HGT})
        return self
    def shot(self, page_html, dst):
        tmp = Path(dst).with_suffix(".html"); tmp.write_text(page_html, encoding="utf-8")
        try:
            self.pg.goto(tmp.resolve().as_uri()); self.pg.wait_for_load_state()
            fit = self.pg.evaluate(FIT_JS)
            self.pg.screenshot(path=str(dst), omit_background=True)
        finally:
            tmp.unlink(missing_ok=True)
        return fit
    def __exit__(self, *a):
        try: self.b.close()
        finally: self.pw.stop()

def render_strip(painter, gen, dst_dir, base, dark):
    body, anim, icon_names = MAKERS[gen["kind"]](gen, dark)
    h = hashlib.sha1((json.dumps(gen, ensure_ascii=False, sort_keys=True) + str(dark) + "v3").encode("utf-8")).hexdigest()[:6]
    name = "%s_%s.png" % (base, h)
    fit = painter.shot(_page(body, dark), dst_dir / name)
    anim.update({"v": 3, "dark": dark, "fit": fit or {}, "icons": icons_for_anim(icon_names)})
    return name, anim

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    if not args: sys.exit("usage: py scripts/script_to_story.py inbox/<review_id> [--force]")
    p = Path(args[0]); p = p if p.is_absolute() else Path.cwd() / p
    txt = p if p.is_file() else next(iter(sorted(p.glob("*.txt"))), None)
    if not txt: sys.exit("no .txt script found in " + str(p))
    ov_file = next(iter(sorted(txt.parent.glob("visuals.json"))), None)
    overrides = json.loads(ov_file.read_text(encoding="utf-8-sig")) if ov_file else {}
    print("Script:", txt.name, "| visuals.json:", ("found, cards " + ",".join(map(str, overrides))) if ov_file else "NOT FOUND in " + str(txt.parent))
    rid, res, problems = build(txt.read_text(encoding="utf-8"), force, overrides)
    if res is None:
        print("STOPPED. This script is not safe to turn into a reel:")
        for x in problems: print("  -", x)
        print("Fix it in the review, or run again with --force to build anyway.")
        return 2
    story, clips = res
    outdir = ROOT / "stories"; outdir.mkdir(exist_ok=True)
    sdir = ROOT / "public" / "strips"; sdir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", rid)
    gens = [(i, c) for i, c in enumerate(story["cards"]) if c["strip"].get("_gen")]
    if gens:
        with Painter() as painter:
            for i, c in gens:
                g = c["strip"].pop("_gen")
                name, anim = render_strip(painter, g, sdir, "%s_%02d" % (safe, i + 1), bool(c.get("dark")))
                c["strip"]["src"] = "../public/strips/" + name
                c["strip"]["anim"] = anim
                print("  strip", i + 1, "->", anim["kind"], name)
    (outdir / (rid + ".json")).write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / (rid + ".clips.json")).write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
    if problems: print("NOTE (built because you approved it):", "; ".join(problems))
    print("Story:", outdir / (rid + ".json"))
    print("Cards:", len(story["cards"]), "| b-roll clips still to pick:", len(clips))
    print("Next: py gemini voice, then npm run reel -- stories/" + rid + ".json")
    return 0

if __name__ == "__main__":
    sys.exit(main())


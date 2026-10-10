#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_broll.py - Part 3: gets a real photo for every card that still has no picture.
  py scripts/fetch_broll.py stories/RV_xxx.json
Reads stories/RV_xxx.clips.json (made by script_to_story.py), searches Pexels (free),
saves the photo into stories/broll/, and points the story file at it.
Your key stays in pexels_key.txt next to gemini_key.txt. Nothing is sent anywhere else.
The renderer turns the photo into the house look (duotone + slow zoom). No credit is shown.
"""
import json, sys, urllib.parse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "pexels_key.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def get(url, key=None, binary=False):
    h = {"User-Agent": UA}
    if key: h["Authorization"] = key
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
        b = r.read()
    return b if binary else json.loads(b.decode("utf-8"))

def find_photo(key, q):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": q, "orientation": "landscape", "per_page": 8, "size": "large"})
    res = get(url, key)
    best = None
    for p in res.get("photos", []):
        w, h = p.get("width", 0), p.get("height", 1)
        if w >= 1600 and w / h >= 1.3:          # wide enough for the 1080x650 strip
            best = p; break
    best = best or (res.get("photos") or [None])[0]
    return best

def main():
    if len(sys.argv) < 2: sys.exit("usage: py scripts/fetch_broll.py stories/<id>.json")
    sp = Path(sys.argv[1]); sp = sp if sp.is_absolute() else Path.cwd() / sp
    cp = sp.with_name(sp.stem + ".clips.json")
    if not sp.exists() or not cp.exists(): sys.exit("need " + str(sp) + " and " + str(cp) + " (run script_to_story.py first)")
    if not KEY_FILE.exists(): sys.exit("Put your Pexels key in " + str(KEY_FILE) + " (one line, nothing else).")
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    story = json.loads(sp.read_text(encoding="utf-8")); clips = json.loads(cp.read_text(encoding="utf-8"))
    outdir = sp.parent / "broll"; outdir.mkdir(exist_ok=True)
    done = 0
    for c in clips:
        idx = c["card"] - 1
        queries = [q for q in [c.get("query")] + list(c.get("alt", [])) if q]
        got = None
        for q in queries:
            try: got = find_photo(key, q)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403): sys.exit("Pexels refused the key (HTTP %d). Check pexels_key.txt." % e.code)
                if e.code == 429: sys.exit("Pexels rate limit reached. Try again in an hour.")
                print("  search failed for '%s': HTTP %d" % (q, e.code)); continue
            except Exception as e:
                print("  search failed for '%s': %s" % (q, e)); continue
            if got: print("card %d: '%s' -> photo %s" % (c["card"], q, got.get("id"))); break
        if not got:
            print("card %d: nothing found, keeping the plain strip." % c["card"]); continue
        src = got["src"].get("large2x") or got["src"]["large"]
        dst = outdir / ("%s_%02d.jpg" % (sp.stem, c["card"]))
        dst.write_bytes(get(src, binary=True))
        story["cards"][idx]["strip"] = {"kind": "photo", "label": "", "src": "../stories/broll/" + dst.name}
        done += 1
    sp.write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Done: %d photo(s) added. Now render: npm run reel -- stories/%s" % (done, sp.name))

if __name__ == "__main__":
    main()

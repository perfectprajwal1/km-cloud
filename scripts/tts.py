#!/usr/bin/env python3
"""Per-card Nepali voice + word timings (free, no key).  pip install edge-tts
python scripts/tts.py public/story.json public      -> public/voice/cNN.wav + public/timing.json
Cached by text hash: re-running only re-voices changed cards (saves data)."""
import asyncio, hashlib, json, os, math, subprocess, sys, wave
from pathlib import Path
try:
    import edge_tts
except ImportError:
    edge_tts = None
story = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); pub = Path(sys.argv[2]); (pub / "voice").mkdir(parents=True, exist_ok=True)
VOICE, RATE, PITCH = story.get("voice", "ne-NP-SagarNeural"), story.get("rate", "+6%"), story.get("pitch", "-2Hz")
# HPF 80, -3 dB @ 6.5 kHz (TTS sibilance), +1.5 dB shelf @ 3 kHz, 2:1 comp at -20 dBFS, clip loudness -16 LUFS, 48 kHz
CHAIN = ("highpass=f=80:poles=2,equalizer=f=6500:t=q:w=2:g=-3,highshelf=f=3000:g=1.5,"
         "acompressor=threshold=-20dB:ratio=2:attack=5:release=80,loudnorm=I=-16:TP=-2:LRA=7,aresample=48000")
aligned_f = pub / "aligned_words.json"
alignment = None
if aligned_f.exists():
    try:
        candidate = json.loads(aligned_f.read_text(encoding="utf-8"))
        narration_hash = hashlib.sha256(json.dumps([c.get("vo", "") for c in story["cards"]], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        if (isinstance(candidate, dict) and candidate.get("story_id") == story.get("id") and
                candidate.get("narration_sha256") == narration_hash and
                isinstance(candidate.get("cards"), list) and len(candidate["cards"]) == len(story["cards"])):
            alignment = candidate
            print("Using reviewed audio-specific phrase timing for", story.get("id"))
        else:
            print("TIMING NOTE: audio-specific alignment is stale or incomplete; using estimated word timing. Audio and approved narration are unchanged.")
    except Exception as e:
        print("TIMING NOTE: audio-specific alignment could not be read (%s); using estimated word timing. Audio and approved narration are unchanged." % type(e).__name__)
cache_f = pub / "voice" / "cache.json"
try:
    cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
    if not isinstance(cache, dict): raise ValueError("cache is not an object")
except Exception as e:
    print("TIMING NOTE: voice timing cache is unreadable (%s); cached timing will be rebuilt." % type(e).__name__)
    cache = {}
def duration_ms(path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True)
        value = float(result.stdout.strip()) * 1000
        if math.isfinite(value) and value > 0: return value
    except Exception:
        pass
    try:
        with wave.open(str(path), "rb") as src:
            if src.getframerate() > 0 and src.getnframes() > 0:
                return src.getnframes() * 1000 / src.getframerate()
    except Exception:
        pass
    return 0.0

def own_voice(i, text, wav):
    """Use public/voice_in/cNN.wav (Gemini voice made by gemini_voice.py) if present. Word times are ESTIMATED:
    speech span (silence trimmed) shared between words by letter count."""
    src = pub / "voice_in" / f"c{i+1:02d}.wav"
    if not src.exists():
        if alignment is not None or os.environ.get("KM_REQUIRE_VOICES") == "1":
            raise RuntimeError("Required supplied voice missing; refusing online fallback.")
        if edge_tts is None: raise RuntimeError("Optional free Edge TTS package is unavailable.")
        return None
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af",
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse," + CHAIN,
                    "-ac", "1", str(wav)], check=True)
    ms = duration_ms(wav)
    if ms <= 0:
        print("VOICE NOTE: silence trimming left no measurable samples on card %s; reusing the full supplied audio." % (i+1))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", CHAIN, "-ac", "1", str(wav)], check=True)
        ms = duration_ms(wav)
    if ms <= 0: raise RuntimeError("Supplied voice has no readable audio samples.")
    if alignment is not None:
        try:
            item = alignment["cards"][i]
            if not isinstance(item, dict) or item.get("source_sha256") != hashlib.sha256(src.read_bytes()).hexdigest():
                raise ValueError("source audio hash mismatch")
            words = item.get("words", []); last_end = 0
            if not isinstance(words, list) or not words: raise ValueError("empty word list")
            for w in words:
                if not isinstance(w, dict) or not isinstance(w.get("w"), str) or not w["w"].strip():
                    raise ValueError("invalid aligned token")
                if any(not isinstance(w.get(k), (int,float)) or not math.isfinite(w[k]) for k in ("t", "d")):
                    raise ValueError("invalid aligned milliseconds")
                if w["t"] < last_end or w["d"] < 0 or w["t"] + w["d"] > ms + 100:
                    raise ValueError("invalid aligned bounds/order")
                last_end = w["t"] + w["d"]
            return {"file": f"voice/{wav.name}", "ms": round(ms), "words": words}
        except Exception as e:
            print("TIMING NOTE: card %s alignment is uncertain (%s); using estimated word timing. Audio and approved narration are unchanged." % (i+1, type(e).__name__))
    ws = text.split(); tot = sum(len(w) + 1 for w in ws) or 1; t = 0.0; words = []
    for w in ws:
        d = ms * (len(w) + 1) / tot; words.append({"t": round(t), "d": round(d), "w": w}); t += d
    return {"file": f"voice/{wav.name}", "ms": round(ms), "words": words}
async def one(i, text):
    key = hashlib.sha1(f"{VOICE}|{RATE}|{PITCH}|{text}".encode()).hexdigest()
    wav = pub / "voice" / f"c{i+1:02d}.wav"
    mine = own_voice(i, text, wav)
    if mine: return mine
    if cache.get(str(i), {}).get("key") == key and wav.exists(): return cache[str(i)]["timing"]
    try: com = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH, boundary="WordBoundary")   # edge-tts >= 7
    except TypeError: com = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)               # older: words by default
    mp3, words = bytearray(), []
    async for ch in com.stream():
        if ch["type"] == "audio": mp3 += ch["data"]
        elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
            words.append({"t": round(ch["offset"] / 1e4), "d": round(ch["duration"] / 1e4), "w": ch["text"], "k": ch["type"]})
    if any(w["k"] == "WordBoundary" for w in words): words = [w for w in words if w["k"] == "WordBoundary"]
    tmp = wav.with_suffix(".mp3"); tmp.write_bytes(mp3)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", CHAIN, "-ac", "1", str(wav)], check=True); tmp.unlink()
    ms = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
                              capture_output=True, text=True).stdout) * 1000
    t = {"file": f"voice/{wav.name}", "ms": round(ms), "words": [{k: w[k] for k in ("t", "d", "w")} for w in words]}
    cache[str(i)] = {"key": key, "timing": t}; return t
async def main():
    cards = [await one(i, c.get("vo", "")) for i, c in enumerate(story["cards"])]
    (pub / "timing.json").write_text(json.dumps({"voice": VOICE, "cards": cards}, ensure_ascii=False), encoding="utf-8")
    cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8"); print("OK voice", sum(c["ms"] for c in cards) / 1000, "s")
asyncio.run(main())

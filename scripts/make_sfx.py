#!/usr/bin/env python3
"""Self-made SFX + room tone (no licences needed). python scripts/make_sfx.py public/sfx
Better still: record real paper swipes / a marker on paper with your phone and drop them in with the same names."""
import sys, os, numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt
SR = 48000; out = sys.argv[1] if len(sys.argv) > 1 else "public/sfx"; os.makedirs(out, exist_ok=True)
rng = np.random.default_rng(7)
def bp(x, lo, hi, o=4): return sosfilt(butter(o, [lo, hi], "band", fs=SR, output="sos"), x)
def lp(x, hi, o=2): return sosfilt(butter(o, hi, "low", fs=SR, output="sos"), x)
def env(n, a, d):  # attack/decay in samples
    e = np.ones(n); a = max(1, a); e[:a] = np.linspace(0, 1, a); e[a:] = np.exp(-np.linspace(0, d, n - a)); return e
def save(name, x, peak_db):
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (peak_db / 20)
    fade = int(0.004 * SR); x[-fade:] *= np.linspace(1, 0, fade)
    wavfile.write(f"{out}/{name}.wav", SR, (np.stack([x, x], 1) * 32767).astype(np.int16)); print("✓", name, peak_db, "dBFS")
n = lambda s: int(s * SR); N = lambda s: rng.standard_normal(n(s))
# paper swipe: band-passed noise, 240 ms, 8 ms attack, slight upward sweep feel
x = bp(N(0.24), 1200, 7000) * env(n(0.24), n(0.008), 5) * np.linspace(0.6, 1.0, n(0.24)); save("paper_swipe", x, -20)
# marker squeak: noise through a drifting 2.8 kHz resonance, 320 ms
t = np.arange(n(0.32)) / SR; car = np.sin(2 * np.pi * (2800 + 120 * np.sin(2 * np.pi * 3 * t)) * t)
x = (0.5 * bp(N(0.32), 2000, 4500) + 0.5 * car * bp(N(0.32), 300, 1200)) * env(n(0.32), n(0.02), 2.5); save("marker", x, -24)
# ticks: 25 ms click + 3 kHz ping
t = np.arange(n(0.025)) / SR; x = np.sin(2 * np.pi * 3000 * t) * np.exp(-t * 260); x[:24] += rng.standard_normal(24)
save("tick", x, -28); save("tick_hi", x, -22)
# thump: 70 Hz sine 260 ms decay + 15 ms paper transient
t = np.arange(n(0.30)) / SR; x = np.sin(2 * np.pi * (70 + 30 * np.exp(-t * 30)) * t) * np.exp(-t * 11)
x[: n(0.015)] += 0.35 * bp(N(0.015), 800, 6000); save("thump", x, -12)
# pen tap: 40 ms
t = np.arange(n(0.04)) / SR; x = bp(N(0.04), 900, 5000) * np.exp(-t * 120) + 0.4 * np.sin(2 * np.pi * 420 * t) * np.exp(-t * 90); save("pen_tap", x, -24)
# room tone: brown noise LPF 900 Hz + 110 Hz hum at -60 dBFS, 20 s seamless loop, RMS -34 dBFS = about -38 LUFS (measured)
L = n(20); b = np.cumsum(rng.standard_normal(L + n(1))); b -= lp(b, 20, 1); b = lp(b, 900)[: L + n(1)]
cf = n(1); loop = b[:L].copy(); loop[:cf] = loop[:cf] * np.linspace(0, 1, cf) + b[L:L + cf] * np.linspace(1, 0, cf)
loop = loop / np.sqrt(np.mean(loop ** 2)) * 10 ** (-34 / 20); loop += 10 ** (-60 / 20) * np.sin(2 * np.pi * 110 * np.arange(L) / SR)
wavfile.write(f"{out}/roomtone.wav", SR, (np.stack([loop, loop], 1) * 32767).astype(np.int16)); print("✓ roomtone ~ -38 LUFS")

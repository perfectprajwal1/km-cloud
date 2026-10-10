// Motion rules v12 "Night Desk". All timings in ms, converted at 30 fps. Animate transform + opacity (+ clip-path wipes) only.
import {Easing, interpolate} from 'remotion';
export const FPS = 30;
export const E = {
  settle: Easing.bezier(0.16, 1, 0.3, 1),   // expo-out: kicker, rule, slabs, tiles
  rise: Easing.bezier(0.22, 1, 0.36, 1),    // quint-out: masked line / block rises (the engage question motion)
  wipe: Easing.bezier(0.65, 0, 0.35, 1),    // red pill, strike, strip reveal
  count: Easing.bezier(0.22, 1, 0.36, 1),   // count-ups
  exit: Easing.bezier(0.4, 0, 1, 1),        // exits
  linear: Easing.linear,
};
export const MS = {
  lead: 120,        // cut -> voice onset
  tail: 350,        // voice end -> exit start
  exit: 200, exitFall: 28,                  // exit = content lifts 48 px + fades; the stage never cuts
  enter: 600, rise: 72, stagger: 90, group: 110,          // masked block rise
  line: 600, lineStagger: 90, read: 280, readDim: 0.4,    // masked line rise + read-along brighten (engage)
  kicker: 500, rule: 550, ruleAt: 550, active: 200,
  word: 80, wordIn: 220, wordRise: 24,      // per-WORD entrances (never per letter: keeps conjuncts + matras whole)
  pill: 320, pillLead: 80, pillFlip: 0.45,
  count: 800, countDark: 900, tickEvery: 100, ticks: 6,
  strike: 300, calDrop: 480, calCount: 600,
  strip: 600, stripDelay: 240, bar: 700, barStagger: 90, dot: 14, dotCap: 900, marker: 420,
  drift: 12, push: 0.03, kenBurns: 0.05,
  stageDrift: 26, stageHz: 0.7, stagePush: 0.035,          // engage stage numbers, on global time (continuous across cuts)
  capLead: 80, capMaxWords: 3, capMaxChars: 24, capMorph: 160, capFade: 120,
  lastHold: 600, minCard: 1600, msPerWordEstimate: 430,
};
// Hook (card 1 with "hero"): ms from card start. Restrained slam: no shake, short overshoot.
export const H = {heroSize: 260, spring: {damping: 20, stiffness: 160}, from: 1.08, shake: 180, shakePx: 0,
  sub: 260, when: 1000, line: 250, pivot: 1300, pill: 250};
export const f = (ms: number) => Math.round((ms * FPS) / 1000);
export const prog = (frame: number, startMs: number, durMs: number, ease = E.settle) =>
  interpolate(frame, [f(startMs), f(startMs) + Math.max(1, f(durMs))], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
export const dB = (d: number) => Math.pow(10, d / 20);
// Engage's damped spring, seconds. 0 before start, overshoots then settles on 1.
export const osc = (t: number, start: number, damping: number, freq: number) => {
  const x = t - start; if (x <= 0) return 0;
  const w = freq * Math.sqrt(1 - damping * damping);
  return 1 - Math.exp(-damping * freq * x) * (Math.cos(w * x) + (damping * freq / w) * Math.sin(w * x));
};

import React from 'react';
import {measureText} from '@remotion/layout-utils';
import {parse, ne} from '../fmt';
import {K, Rung} from '../theme';
import {MS, E, prog} from '../motion';
import {PlanItem} from '../types';
import {useCard} from './ctx';
import {Pill, Red} from './Rich';
// The engage question engine, generalised. Text -> unbreakable units (split only at spaces, pills whole) -> measured with
// real Mukta -> balanced into lines (later lines longer, never wider than the column) -> each line rises from its own mask.
type Piece = {t: string; k: 'n' | 'pill' | 'red'; pi: number};
type Unit = {pieces: Piece[]; text: string};
export type Laid = {lines: Unit[][]; size: number; lh: number};
const cache = new Map<string, number>();
export const tw = (text: string, size: number, weight = '800') => {
  const key = `${weight}|${size}|${text}`; let w = cache.get(key);
  if (w == null) { w = measureText({text, fontFamily: 'Mukta', fontWeight: weight, fontSize: size, letterSpacing: '0px'}).width; cache.set(key, w); }
  return w;
};
export const toUnits = (s: string): Unit[] => {
  const units: Unit[] = [{pieces: [], text: ''}]; let pi = 0;
  const add = (p: Piece) => { const u = units[units.length - 1]; u.pieces.push(p); u.text += p.t; };
  parse(s).forEach((g) => {
    if (g.k === 'pill') { add({t: g.t, k: 'pill', pi: pi++}); return; }
    g.t.split(/(\s+)/).forEach((x) => { if (!x) return; if (/^\s+$/.test(x)) { units.push({pieces: [], text: ''}); return; } add({t: x, k: g.k, pi: -1}); });
  });
  return units.filter((u) => u.pieces.length);
};
const unitW = (u: Unit, size: number, weight: string) =>
  u.pieces.reduce((s, p) => s + tw(p.t, size, weight) + (p.k === 'pill' ? 0.36 * size : 0), 0) * 1.04;
const best = (ws: number[], sp: number, maxW: number, k: number): number[] | null => {
  const n = ws.length; if (k > n) return null; let out: number[] | null = null, score = Infinity;
  const lineW = (a: number, b: number) => ws.slice(a, b).reduce((s, x) => s + x, 0) + sp * (b - a - 1);
  const rec = (start: number, left: number, cuts: number[]) => {
    if (left === 1) {
      const all = [...cuts, n]; let prev = 0; const w: number[] = [];
      for (const c of all) { const x = lineW(prev, c); if (x > maxW) return; w.push(x); prev = c; }
      const cost = w.reduce((s, x) => s + (maxW - x) ** 2, 0) + w.slice(1).reduce((s, x, i) => s + Math.max(0, w[i] - x) ** 2 * 2, 0);
      if (cost < score) { score = cost; out = all; } return;
    }
    for (let c = start + 1; c <= n - left + 1; c++) { if (lineW(start, c) > maxW) break; rec(c, left - 1, [...cuts, c]); }
  };
  rec(0, k, []); return out;
};
// v12.1: overlong copy keeps shrinking (x.88, x.78, x.70 of the last rung, never below 44 px) before the greedy wrap, so a very long
// headline stays inside the column instead of climbing into the logo. Rungs above this are untouched, so normal copy lays out identically.
const extend = (ladder: Rung[]): Rung[] => { const l = ladder[ladder.length - 1];
  return [...ladder, ...[0.88, 0.78, 0.7].map((m, i) => ({size: Math.max(44, Math.round(l.size * m / 2) * 2), lh: Math.max(58, Math.round(l.size * m * 1.3 / 2) * 2), max: l.max + 2 + i}))]; };
export const layLines = (s: string, ladder0: Rung[], width: number, weight = '800'): Laid => {
  const units = toUnits(s); const ladder = extend(ladder0);
  for (const r of ladder) {
    const ws = units.map((u) => unitW(u, r.size, weight)); const sp = tw(' ', r.size, weight);
    for (let k = 1; k <= r.max; k++) {
      const cuts = best(ws, sp, width, k);
      if (cuts) { let prev = 0; return {size: r.size, lh: r.lh, lines: cuts.map((c) => { const l = units.slice(prev, c); prev = c; return l; })}; }
    }
  }
  // Exceptional overlong copy: greedy wrap at the smallest rung, never truncated.
  const r = ladder[ladder.length - 1]; const sp = tw(' ', r.size, weight); const lines: Unit[][] = [[]]; let w = 0;
  units.forEach((u) => { const x = unitW(u, r.size, weight); if (lines[lines.length - 1].length && w + sp + x > width) { lines.push([]); w = 0; }
    w += (w ? sp : 0) + x; lines[lines.length - 1].push(u); });
  return {size: r.size, lh: r.lh, lines};
};
export const laidHeight = (l: Laid) => l.lines.length * l.lh;
const norm = (s: string) => ne(s).replace(/[।?!,.:;"“”'‘’()\-–—{}\[\]]/g, '').trim();
// Word-level read-along. Only whitespace boundaries are split; conjuncts and matras stay whole.
// Exact voice matches take priority. Unmatched editorial wording uses a deterministic voice-length sweep,
// rather than freezing at full brightness or borrowing one preceding word's timestamp for an entire line.
const readTimes = (units: Unit[], it: PlanItem): number[] => {
  const ws = it.words.map((w) => norm(w.w)); let j = 0;
  const lengths = units.map((u) => Math.max(1, u.text.length));
  const total = lengths.reduce((a, b) => a + b, 0); let consumed = 0;
  const fallbackEnd = Math.max(MS.read, it.voMs - MS.read);
  return units.map((u, i) => {
    const n = norm(u.text); let hit = -1;
    for (let q = j; q < ws.length; q++) {
      if (ws[q] && n && ws[q] === n) { hit = q; break; }
      // A multiword pill stays one visual unit and lights on its first spoken word.
      const parts = n.split(/\s+/);
      if (parts.length > 1 && parts.every((v, k) => ws[q + k] === v)) { hit = q; break; }
    }
    const fallback = MS.lead + consumed / total * fallbackEnd; consumed += lengths[i];
    if (hit < 0) return fallback;
    j = hit + Math.max(1, n.split(/\s+/).length); return MS.lead + it.words[hit].t;
  });
};
export const Lines: React.FC<{s?: string; ladder: Rung[]; width: number; weight?: string; at?: number; now?: boolean; read?: boolean;
  color?: string; base?: number; laid?: Laid; shadow?: string; exit?: boolean}> =
  ({s, ladder, width, weight = '800', at = 0, now, read = true, color = K.paper, base = 0, laid, shadow = K.text, exit = true}) => {
    const {frame, it, exitP: ex} = useCard(); const exitP = exit ? ex : 0;
    if (!s) return null;
    const L = laid ?? layLines(s, ladder, width, weight);
    const times = null; // v12.5: editorial typography has no reading-brightness sweep. let wi = 0;
    const pad = Math.round(L.size * 0.16);
    return <div style={{width}}>{L.lines.map((ln, li) => {
      const q = now ? 1 : prog(frame, at + li * MS.lineStagger, MS.line, E.rise);
      return <div key={li} style={{height: L.lh, clipPath: undefined}}>
        <div style={{font: `${weight} ${L.size}px/${L.lh}px Mukta`, letterSpacing: '-.005em', whiteSpace: 'nowrap', color, textShadow: shadow,
          opacity: q * (1 - exitP), transform: `translateY(${-exitP * MS.exitFall}px)`}}>
          {ln.map((u, ui) => <React.Fragment key={ui}>{ui ? ' ' : null}<span style={{color: K.paper}}>{u.pieces.map((p, pj) =>
              p.k === 'pill' ? <Pill key={pj} t={p.t} k={base + p.pi} /> : <span key={pj}>{p.t}</span>)}</span></React.Fragment>)}
        </div></div>; })}</div>;
  };

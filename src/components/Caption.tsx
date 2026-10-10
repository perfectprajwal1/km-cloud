import React from 'react';
import {useCurrentFrame, interpolate} from 'remotion';
import {K, G, T} from '../theme';
import {MS, E, f} from '../motion';
import {PlanItem} from '../types';
import {ne} from '../fmt';
import {fitSize} from './fit';
import {tw} from './Lines';
// v12 subtitle band: a glass capsule (engage composer material) at x80, y1140, h100, r50 — inside the 1130-1250 band.
// Text 600 52 -> 40 paper, 1 line, <= 3 words / 24 chars, never red. TEXT SWAPS INSTANTLY (whole words: no per-glyph motion, ever).
// Only the capsule moves: its width morphs to the new chunk in 160 ms expo; it fades in/out 120 ms around voice gaps.
// Engage cards carry no captions (the question is read along on-card).
type Chunk = {s: number; e: number; text: string; dark: boolean};
export const buildChunks = (plan: PlanItem[]): Chunk[] => {
  const out: Chunk[] = [];
  for (const it of plan) {
    if (it.card.type === 'engage') continue;
    const base = it.from * (1000 / 30) + MS.lead; let cur: any[] = []; const n0 = out.length;
    const push = () => { if (cur.length) out.push({s: base + cur[0].t - MS.capLead, e: 0, text: cur.map((w) => w.w).join(' '), dark: !!it.card.dark}); cur = []; };
    for (const w of it.words) {
      const len = [...cur, w].map((x) => x.w).join(' ').length;
      if (cur.length >= MS.capMaxWords || len > MS.capMaxChars) push();
      cur.push(w); if (/[।?!,]$/.test(w.w)) push();
    }
    push();
    const endMs = base + it.voMs + 200;
    for (let i = out.length - 1; i >= n0 && out[i].e === 0; i--) out[i].e = endMs;
  }
  for (let i = 0; i < out.length - 1; i++) out[i].e = Math.min(out[i].e, out[i + 1].s);
  return out;
};
const sizeOf = (txt: string) => fitSize(txt, T.cap, 40, G.cap.max - 2 * G.cap.pad, 1, '600');
const widthOf = (txt: string) => Math.ceil(tw(txt, sizeOf(txt), '600') + 2 * G.cap.pad);
export const Captions: React.FC<{chunks: Chunk[]}> = ({chunks}) => {
  const frame = useCurrentFrame(); const i = chunks.findIndex((x) => frame >= f(x.s) && frame < f(x.e));
  // fade out: hold the last chunk for capFade after it ends, then disappear
  let j = i; let fade = 1;
  if (i < 0) { j = chunks.findIndex((x) => frame >= f(x.e) && frame < f(x.e + MS.capFade)); if (j < 0) return null;
    fade = 1 - interpolate(frame, [f(chunks[j].e), f(chunks[j].e + MS.capFade)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}); }
  const c = chunks[j]; const txt = ne(c.text); const fs = sizeOf(txt); const w1 = widthOf(txt);
  const prev = j > 0 && Math.abs(chunks[j - 1].e - c.s) < 60 ? chunks[j - 1] : null; // contiguous -> morph, else fade in
  const k = interpolate(frame, [f(c.s), f(c.s) + Math.max(1, f(MS.capMorph))], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: E.settle});
  const w = prev ? Math.max(w1, widthOf(ne(prev.text)) + (w1 - widthOf(ne(prev.text))) * k) : w1;
  const op = prev || i < 0 ? fade : interpolate(frame, [f(c.s), f(c.s + MS.capFade)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <div lang="ne" style={{position: 'absolute', left: G.x, top: G.cap.y, width: w, height: G.cap.h, borderRadius: G.cap.h / 2, opacity: op,
    background: `${K.glass}, rgba(17,15,15,.78)`, boxShadow: K.glassRing, overflow: 'hidden'}}>
    <div style={{position: 'absolute', left: G.cap.pad, top: 0, height: G.cap.h, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap',
      font: `600 ${fs}px/1.25 Mukta`, color: K.paper}}>{txt}</div></div>;
};

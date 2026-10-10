import React from 'react';
import {K, G, TS, Rung} from '../theme';
import {Rich} from '../components/Rich';
import {In, useCard} from '../components/ctx';
import {Lines, tw} from '../components/Lines';
import {fitSize} from '../components/fit';
import {MS, E, prog, osc} from '../motion';
import {Stage} from './Stage';
export {Stage};
// Shared v12 parts. Every story card = <Card> (stage + bottom-anchored deck + red end-rule).
export const useInk = () => ({ink: K.paper, grey: K.dim});
// Deck: x80, w860, bottom edge y1040, grows UPWARD (engage logic: the last line always lands in the same place).
export const Card: React.FC<{children: React.ReactNode; rule?: number | false}> = ({children, rule = MS.ruleAt}) =>
  <Stage><div style={{position: 'absolute', left: G.x, width: G.w, bottom: 1920 - G.deck, display: 'flex', flexDirection: 'column', alignItems: 'flex-start'}}>
    {children}</div>{rule === false ? null : <Rule at={rule} />}</Stage>;
// End-rule 120x10 r2 red at (80, 1066), expo scaleX 550 ms.
export const Rule: React.FC<{at?: number}> = ({at = MS.ruleAt}) => { const {frame, exitP, card} = useCard(); const p = card.type === 'hook' ? 1 : prog(frame, at, MS.rule, E.settle);
  return <div style={{position: 'absolute', left: G.x, top: G.rule, width: 120, height: 10, borderRadius: 2, background: K.red, opacity: 1 - exitP,
    transformOrigin: '0 50%', transform: `scaleX(${p})`, boxShadow: '0 0 24px rgba(215,20,30,.45)'}} />; };
// Kicker row (engage "आजको प्रश्न"): 20 px red block (spring .55/18) + 600 40/48 label, paper .62, slides 16 px, expo 500 ms.
export const Kick: React.FC<{s?: string; i?: number; at?: number; now?: boolean; mark?: React.ReactNode}> = ({s, i = 0, at, now, mark}) => {
  const {frame, exitP} = useCard(); const t0 = (at ?? i * MS.stagger) / 1000, t = frame / 30;
  const b = now ? 1 : osc(t, t0 + 0.02, 0.55, 18); const k = now ? 1 : prog(frame, t0 * 1000, MS.kicker, E.settle);
  if (!s && !mark) return null;
  return <div style={{height: 48, display: 'flex', alignItems: 'center', gap: 18, marginBottom: 20, opacity: 1 - exitP, transform: `translateY(${-exitP * MS.exitFall}px)`}}>
    {mark ?? <div style={{width: 20, height: 20, borderRadius: 3, background: K.red, transform: `scale(${b})`, boxShadow: '0 0 24px rgba(215,20,30,.6)'}} />}
    {s ? <div style={{font: '600 40px/48px Mukta', letterSpacing: '.01em', color: K.dim, whiteSpace: 'nowrap', opacity: k, transform: `translateX(${(1 - k) * -16}px)`}}><Rich s={s} /></div> : null}
  </div>; };
// Secondary line: 600 44/60, paper .62, masked rise.
export const Sec: React.FC<{s?: string; i?: number; at?: number; mt?: number; color?: string}> = ({s, i = 1, at, mt = 28, color = K.dim}) =>
  s ? <In i={i} at={at} style={{marginTop: mt}}><div style={{font: '600 44px/60px Mukta', color, width: G.w}}><Rich s={s} /></div></In> : null;
// Headline on the house ladder. `size` (legacy prop) starts the ladder at that size.
export const ladderFrom = (size: number, lines: number, min = 56): Rung[] => {
  const out: Rung[] = []; for (let s = size; s >= min; s -= 8) out.push({size: s, lh: Math.round(s * 1.3), max: lines}); return out;
};
export const Hl: React.FC<{s?: string; i?: number; at?: number; size?: number; lines?: number; width?: number; now?: boolean; lh?: number; read?: boolean; ladder?: Rung[]}> =
  ({s, i = 0, at, size, lines = 3, width = G.w, now, read = true, ladder}) =>
    s ? <Lines s={s} ladder={ladder ?? (size ? ladderFrom(size, lines) : TS.headline.map((r) => ({...r, max: Math.min(r.max + lines - 2, 4)})))} width={width}
      at={0} read={read} /> : null;
// Glass slab (engage composer material).
export const glass = (hi = false, r = 28): React.CSSProperties => ({borderRadius: r, background: hi ? 'linear-gradient(180deg,rgba(215,20,30,.16),rgba(215,20,30,.05))' : K.glass,
  boxShadow: hi ? K.redRing : K.glassRing});
// Figure: big number. Final value reserves the width (prefix/unit never move), the counting value sits on it left-aligned.
export const Figure: React.FC<{final: string; shown?: React.ReactNode; prefix?: string; unit?: string; size: number; color?: string; glow?: number}> =
  ({final, shown, prefix, unit, size, color = K.paper, glow = 0}) =>
    <div style={{font: `800 ${size}px/1.08 Mukta`, letterSpacing: '-.02em', whiteSpace: 'nowrap', color,
      textShadow: `0 2px 0 rgba(0,0,0,.25), 0 0 ${Math.round(size * 0.35)}px rgba(215,20,30,${0.1 + 0.35 * glow})`}}>
      {prefix ? <span style={{fontSize: '.34em', color: K.dim, letterSpacing: 0, marginRight: '.12em'}}>{prefix}</span> : null}
      <span style={{position: 'relative', display: 'inline-block'}}><span style={{visibility: shown == null ? 'visible' : 'hidden'}}>{final}</span>
        {shown == null ? null : <span style={{position: 'absolute', left: 0, top: 0}}>{shown}</span>}</span>
      {unit ? <span style={{fontSize: '.30em', color: K.dim, letterSpacing: 0, marginLeft: '.16em'}}>{unit}</span> : null}</div>;
export const figSize = (full: string, base: number, min: number, width = G.w) => fitSize(full, base, Math.min(min, 110), width, 1);

// v12.1: size the figure from what is really drawn: number at 1 em, prefix at .34 em (+.12 gap), unit at .30 em (+.16 gap). The old call measured
// prefix + number + unit all at figure size, which shrank every figure with a unit ("रु. १,८४० करोड") to a third of its room.
export const figFit = (prefix: string | undefined, num: string, unit: string | undefined, base: number, min: number, width = G.w) => {
  for (let fs = base; fs > min; fs -= 2) {
    const w = (tw(num, fs) + (prefix ? tw(prefix, fs * 0.34) + 0.12 * fs * 0.34 : 0) + (unit ? tw(unit, fs * 0.3) + 0.16 * fs * 0.3 : 0)) * 1.06;
    if (w <= width) return fs;
  }
  return min;
};

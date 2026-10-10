import React from 'react';
import {parse} from '../fmt';
import {K} from '../theme';
import {MS, prog, E} from '../motion';
import {cueMs} from '../plan';
import {useCard} from './ctx';
// v12. {{pill}} = red-gradient slab wipes in left->right (320 ms WIPE, scaleX only), text turns paper at 45%, soft red glow.
// [[red]] = brand red text with a red halo (use >= 52 px). Words split ONLY at spaces; a pill is never split.
export const Pill: React.FC<{t: string; k: number}> = ({t, k}) => {
  const {frame, it} = useCard();
  const p = prog(frame, cueMs(it, 'pill', k), MS.pill, E.wipe);
  return <span style={{position: 'relative', display: 'inline-block', whiteSpace: 'nowrap', padding: '0 .18em', color: K.paper,
    textShadow: p > MS.pillFlip ? '0 1px 0 rgba(0,0,0,.25)' : undefined}}>
    <span style={{position: 'absolute', left: 0, right: 0, top: '.08em', bottom: '.04em', background: K.redFill, borderRadius: '.14em',
      boxShadow: `0 10px 34px -8px rgba(215,20,30,${0.6 * p}), inset 0 2px 0 rgba(243,237,227,.22)`, transformOrigin: '0 50%', transform: `scaleX(${p})`}} />
    <span style={{position: 'relative'}}>{t}</span></span>;
};
export const Red: React.FC<{t: string}> = ({t}) => <span style={{color: K.red, textShadow: K.redText}}>{t}</span>;
export const Rich: React.FC<{s?: string; base?: number; w0?: number}> = ({s, base = 0, w0}) => {
  const {frame} = useCard(); let k = base;
  const segs = parse(s);
  if (w0 == null) return <>{segs.map((g, j) => g.k === 'n' ? <span key={j}>{g.t}</span> : g.k === 'red' ? <Red key={j} t={g.t} /> : <Pill key={j} t={g.t} k={k++} />)}</>;
  const words: React.ReactNode[][] = [[]];
  segs.forEach((g, j) => {
    if (g.k === 'pill') { words[words.length - 1].push(<Pill key={'p' + j} t={g.t} k={k++} />); return; }
    g.t.split(/(\s+)/).forEach((x, q) => {
      if (!x) return; if (/^\s+$/.test(x)) { words.push([]); return; }
      words[words.length - 1].push(g.k === 'red' ? <Red key={`r${j}-${q}`} t={x} /> : <span key={`n${j}-${q}`}>{x}</span>);
    });
  });
  return <>{words.filter((w) => w.length).map((w, n) => { const p = prog(frame, w0 + n * MS.word, MS.wordIn, E.settle);
    return <React.Fragment key={n}>{n ? ' ' : null}<span style={{display: 'inline-block', whiteSpace: 'nowrap', opacity: p,
      transform: `translateY(${(1 - p) * MS.wordRise}px)`}}>{w}</span></React.Fragment>; })}</>;
};
export const pillCount = (s?: string) => parse(s).filter((g) => g.k === 'pill').length;

import React from 'react';
import {K, G, TS} from '../theme';
import {useCard, In} from '../components/ctx';
import {Lines} from '../components/Lines';
import {MS, prog, E} from '../motion';
import {Card} from './ui';
// v12 quote. No red on the speaker, ever: red only on the quote mark and on a number inside the quote.
// 220 px red “ (glyph box 120 high) | quote 600 72/98 -> 52/72, 1-5 lines, masked line rise + engage read-along (dim .4 -> 1 as spoken)
// | attribution at 60 % of VO: 40x4 paper .3 dash, name 800 44, role 600 40 .62.
export const Quote: React.FC = () => { const {card, it, frame, exitP} = useCard(); const m = prog(frame, 0, 420, E.settle);
  return <Card rule={MS.lead + it.voMs * 0.6}>
    <div style={{height: 120, overflow: 'visible', opacity: m * (1 - exitP), transform: `translateY(${(1 - m) * 24 - exitP * MS.exitFall}px)`}}>
      <div style={{font: '800 220px/1 Mukta', color: K.red, marginLeft: -10, marginTop: -14, textShadow: K.redText}}>“</div></div>
    <Lines s={card.quote} ladder={TS.quote} width={G.w} weight="600" at={0} read />
    <In at={MS.lead + it.voMs * 0.6} style={{marginTop: 36}}><div style={{display: 'flex', alignItems: 'center', gap: 20}}>
      <div style={{width: 40, height: 4, borderRadius: 2, background: K.faint}} />
      <div><div style={{font: '800 44px/56px Mukta', color: K.paper}}>{card.name}</div>
        {card.role ? <div style={{font: '600 40px/52px Mukta', color: K.dim}}>{card.role}</div> : null}</div></div></In></Card>; };

import React from 'react';
import {K} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {ne} from '../fmt';
import {MS, prog, E} from '../motion';
import {Card, Kick, Sec, figSize} from './ui';
// v12 change: old -> new as one vertical gesture.
// old 800 120 paper .38 | strike 8 px paper .75 draws at 25 % of VO (WIPE 300) | connector 4x56 paper .2 + red chevron
// | new 800 220 -> 140 red + halo, masked rise 120 ms after the strike | delta pill +300 ms.
export const Change: React.FC = () => { const {card, it, frame} = useCard();
  const tStrike = MS.lead + it.voMs * 0.25; const s = prog(frame, tStrike, MS.strike, E.wipe); const tNew = tStrike + MS.strike + 120;
  const chevron = prog(frame, tNew - 120, 420, E.rise);
  const fs = figSize(ne(card.new), 220, 140);
  return <Card rule={tNew}><Kick s={card.kicker} /><Sec s={card.label} i={0} mt={0} />
    <In i={1} hero style={{marginTop: 8}}><div style={{font: '800 120px/1.15 Mukta', color: K.faint, position: 'relative', display: 'inline-block', whiteSpace: 'nowrap'}}>
      {ne(card.old)}<div style={{position: 'absolute', left: -6, top: '54%', height: 8, borderRadius: 4, width: 'calc(100% + 12px)', background: 'rgba(243,237,227,.75)',
        transformOrigin: '0 50%', transform: `scaleX(${s})`}} /></div></In>
    <In at={tNew - 120}><svg width="40" height="72" viewBox="0 0 40 72" style={{display: 'block', margin: '6px 0 6px 18px'}}>
      <path d="M20 2V60" stroke="rgba(243,237,227,.2)" strokeWidth="4" strokeLinecap="round" /><path d="M8 50L20 64L32 50" stroke={K.red} strokeWidth="5" fill="none" strokeLinecap="round" strokeLinejoin="round" style={{transform: `translateY(${(1 - chevron) * -12}px)`, opacity: chevron}} /></svg></In>
    <In at={tNew}><div style={{font: `800 ${fs}px/1.08 Mukta`, letterSpacing: '-.02em', color: K.red, whiteSpace: 'nowrap', textShadow: K.redText}}>{ne(card.new)}</div></In>
    {card.delta ? <In at={tNew + 300} style={{marginTop: 16}}><span style={{font: '800 48px/1.4 Mukta'}}><Rich s={`{{${card.delta}}}`} /></span></In> : null}</Card>; };

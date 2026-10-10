import React from 'react';
import {K, G} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {fitSize} from '../components/fit';
import {plain} from '../fmt';
import {Card, Kick, Hl} from './ui';
import {MS} from '../motion';
// v12 place: name 800 140 -> 88 (1 line, w860) | red pin 40 + area 600 44 .62 | gap 48 | headline at 30 % of VO.
export const Place: React.FC = () => { const {card, it} = useCard(); const fs = fitSize(plain(card.place), 140, 88, G.w, 1);
  return <Card rule={MS.lead + it.voMs * 0.3}><Kick s={card.kicker} />
    <In i={0}><div style={{font: `800 ${fs}px/1.15 Mukta`, letterSpacing: '-.01em', color: K.paper, whiteSpace: 'nowrap', textShadow: K.text}}><Rich s={card.place} /></div></In>
    {card.area ? <In i={1}><div style={{display: 'flex', alignItems: 'center', gap: 14, font: '600 44px/60px Mukta', color: K.dim}}>
      <svg width="40" height="40" viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z" fill={K.red} /><circle cx="12" cy="10" r="3" fill={K.ink} /></svg>
      <Rich s={card.area} /></div></In> : null}
    <div style={{height: 48}} /><Hl s={card.headline} lines={3} at={MS.lead + it.voMs * 0.3} /></Card>; };

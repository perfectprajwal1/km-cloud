import React from 'react';
import {K, G} from '../theme';
import {useCard} from '../components/ctx';
import {CountUp} from '../components/CountUp';
import {ne} from '../fmt';
import {MS, prog, E} from '../motion';
import {Card, Kick, Hl, Sec, glass, ladderFrom} from './ui';
// v12 date: the one physical object. Glass tile 300x380 r28 drops 40 px (expo 480 ms). Header 92 high: month + year 600 40 paper .8,
// hairline .14 under it. Day 800 190 red + halo, counts from 1 and lands on the spoken day. Weekday 600 40 .62.
// Headline column x420-940 (w520), 76 -> 56, max 4 lines, vertically centred on the tile. Sub under, full width.
export const DateCard: React.FC = () => { const {card, frame, exitP} = useCard(); const p = prog(frame, 0, MS.calDrop, E.settle);
  return <Card rule={MS.calDrop}><Kick s={card.kicker} />
    <div style={{display: 'flex', gap: 40, alignItems: 'center', width: G.w}}>
      <div style={{flex: '0 0 300px', height: 380, position: 'relative', textAlign: 'center', ...glass(false, 28),
        transform: `translateY(${(1 - p) * -40 - exitP * MS.exitFall}px)`, opacity: Math.min(1, p * 1.6) * (1 - exitP)}}>
        <div style={{height: 92, font: '600 40px/96px Mukta', color: 'rgba(243,237,227,.8)', borderBottom: `2px solid ${K.line}`}}>{ne(card.month)} {ne(card.year ?? '')}</div>
        <div style={{font: '800 190px/1.1 Mukta', color: K.red, textShadow: K.redText, marginTop: 6}}><CountUp to={+card.day} from={1} /></div>
        <div style={{font: '600 40px/1 Mukta', color: K.dim}}>{card.weekday}</div></div>
      <Hl s={card.headline} ladder={ladderFrom(76, 4, 56)} width={520} i={2} /></div>
    <Sec s={card.sub} i={4} /></Card>; };

import React from 'react';
import {K, G} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {fitSize} from '../components/fit';
import {ne, plain} from '../fmt';
import {MS} from '../motion';
import {Card, Kick, Hl, glass} from './ui';
// v12 versus: two glass slabs 410 x min 300, gap 40 (x80 / x490). Left enters at 15 % of VO, right at 50 %.
// Slab: padding 36/32, label 600 40/52 .62 | value 800 120 -> 72 (w346, 1 line) | note 600 40/52 .62.
// hi side: red inset ring + red-tinted glass, value red with halo. Equal heights (flex stretch) so the pair reads as one object.
export const Versus: React.FC = () => { const {card, it} = useCard();
  const side = (s: any, k: number) => { const at = MS.lead + it.voMs * (0.15 + 0.35 * k);
    const fs = fitSize(plain(ne(s.value)), 120, 44, 346, 1);
    return <In at={at} style={{flex: '0 0 410px', display: 'flex'}}><div style={{width: 410, minHeight: 300, boxSizing: 'border-box', padding: '36px 32px 32px', ...glass(!!s.hi)}}>
      <div style={{font: '600 40px/52px Mukta', color: K.dim}}><Rich s={s.label} /></div>
      <div style={{font: `800 ${fs}px/1.15 Mukta`, letterSpacing: '-.01em', color: s.hi ? K.red : K.paper, whiteSpace: 'nowrap', marginTop: 18,
        textShadow: s.hi ? K.redText : K.text}}><Rich s={ne(s.value)} /></div>
      {s.note ? <div style={{font: '600 40px/52px Mukta', color: K.dim, marginTop: 10}}><Rich s={s.note} /></div> : null}</div></In>; };
  return <Card rule={MS.lead + it.voMs * 0.5}><Kick s={card.kicker} />{card.headline ? <><Hl s={card.headline} lines={2} /><div style={{height: 36}} /></> : null}
    <div style={{display: 'flex', gap: 40, width: G.w, alignItems: 'stretch'}}>{side(card.left, 0)}{side(card.right, 1)}</div></Card>; };

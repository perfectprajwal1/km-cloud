import React from 'react';
import {G} from '../theme';
import {useCard, In} from '../components/ctx';
import {countWindow} from '../components/CountUp';
import {interpolate} from 'remotion';
import {ne} from '../fmt';
import {f, prog, MS, E} from '../motion';
import {Card, Kick, Sec, Hl, Figure, figFit} from './ui';
// v12 big number. kicker | label (600 44 .62) | figure 800 320 -> 180 (1 line, w860), prefix .34em / unit .30em in paper .62
// counts on COUNT easing and LANDS on the spoken number; red halo flares .45 at land and settles to .2 | sub headline at 55 % of VO | end-rule draws at land.
export const BigNum: React.FC = () => { const {card, it, frame} = useCard(); const dec = card.decimals || 0;
  const final = ne(card.value, dec);
  const fs = figFit(card.prefix, final, card.unit, 320, 110);
  const {start, land} = countWindow(it);
  const v = interpolate(frame, [f(start), f(land)], [it.carry ? +card.value : 0, +card.value], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: E.count});
  const flare = prog(frame, land, 200, E.settle) - 0.55 * prog(frame, land + 200, 700, E.settle);
  return <Card rule={land}><Kick s={card.kicker} /><Sec s={card.label} i={0} mt={0} />
    <In i={1} hero><Figure final={final} shown={ne(dec ? v : Math.round(v), dec)} prefix={card.prefix} unit={card.unit} size={fs} glow={flare} /></In>
    <div style={{height: 20}} /><Hl s={card.sub} lines={2} at={MS.lead + it.voMs * 0.55} width={G.w} /></Card>; };

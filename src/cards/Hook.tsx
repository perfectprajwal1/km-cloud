import React from 'react';
import {spring, useVideoConfig} from 'remotion';
import {K, G, TS} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {Lines} from '../components/Lines';
import {fitSize} from '../components/fit';
import {ne} from '../fmt';
import {MS, H, f, prog, E} from '../motion';
import {Card, Kick, Sec} from './ui';
// v12.2 hook: the end-rule is full at frame 0. Headline lines rise from frame 0 and read along like Engage.
// Plain:  kicker row | display headline (112/144 -> 76/100, 1-4 lines, balanced) | sub at 420 ms | end-rule drawn by 550 ms.
// Hero:   0 hero numeral slams 1.08->1 (spring 20/160), red, red halo | 260 hero_sub per word | 1000 hero_when + 10 px red underline
//         | 1300 headline (masked line rise), pill +250. Keep hero / hero_sub / hero_when plain text (the only pill is in the headline).
export const Hook: React.FC = () => { const {card, frame, exitP} = useCard(); const {fps} = useVideoConfig();
  if (!card.hero) return <Card rule={0}>
    <Kick s={card.kicker} now mark={card.kicker ? undefined : <div style={{width: 20, height: 20, borderRadius: 3, background: K.red, boxShadow: '0 0 24px rgba(215,20,30,.6)'}} />} />
    <Lines s={card.headline} ladder={TS.display} width={G.w} at={0} read />
    <Sec s={card.sub} at={420} mt={24} /></Card>;
  const hero = ne(card.hero); const hs = fitSize(hero, H.heroSize, 150, G.w, 1);
  const sc = spring({frame, fps, config: H.spring, from: H.from, to: 1});
  const s0 = f(H.shake); const dx = frame === s0 ? H.shakePx : frame === s0 + 1 ? -H.shakePx : 0;
  const u = prog(frame, H.when + 100, H.line, E.wipe);
  const out = {opacity: 1 - exitP, transform: `translateY(${-exitP * MS.exitFall}px)`};
  return <Card rule={H.pivot}>
    <div style={out}>
      <div style={{font: `800 ${hs}px/1.08 Mukta`, letterSpacing: '-.02em', color: K.red, whiteSpace: 'nowrap', transformOrigin: '0 70%',
        transform: `translateX(${dx}px) scale(${sc})`, textShadow: K.redText}}>{hero}</div>
      {card.hero_sub ? <Lines s={card.hero_sub} ladder={[{size:76, lh:100, max:2},{size:64, lh:86, max:3}]} width={G.w} at={H.sub} read /> : null}</div>
    {card.hero_when ? <In at={H.when} style={{marginTop: 12}}><div style={{display: 'inline-block', font: '600 44px/60px Mukta', color: K.dim}}>
      {ne(card.hero_when)}<div style={{height: 10, borderRadius: 2, marginTop: 2, background: K.red, transformOrigin: '0 50%', transform: `scaleX(${u})`}} /></div></In> : null}
    <div style={{height: 36}} />
    <Lines s={card.headline} ladder={[{size: 64, lh: 84, max: 2}, {size: 56, lh: 74, max: 3}]} width={G.w} at={0} read /></Card>; };

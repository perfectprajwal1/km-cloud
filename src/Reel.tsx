import React, {useMemo} from 'react';
import {AbsoluteFill, Sequence, delayRender, continueRender, staticFile} from 'remotion';
import {loadFont} from '@remotion/fonts';
import {Props} from './types';
import {buildPlan} from './plan';
import {G} from './theme';
import {CARDS} from './cards';
import {CardCtx, useCard} from './components/ctx';
import {DarkBg, Sample} from './components/Base';
import {Strip} from './components/Strip';
import {Captions, buildChunks} from './components/Caption';
import {CardSound, Bed} from './components/Sound';

const h = delayRender('fonts');
Promise.all([
  loadFont({family: 'Mukta', url: staticFile('fonts/Mukta-SemiBold.ttf'), weight: '600'}),
  loadFont({family: 'Mukta', url: staticFile('fonts/Mukta-ExtraBold.ttf'), weight: '800'}),
  loadFont({family: 'Mukta', url: staticFile('fonts/Mukta-Bold.ttf'), weight: '700'}),
]).then(() => continueRender(h)).catch((e) => { console.error(e); continueRender(h); });

// v12 "Night Desk" root. Story cards are mounted exactly like Engage: FULL canvas, no paper, no root logo, no 90/430 column
// (each card's <Stage> draws its own room + logo). Order per card: card -> <Strip/>; <Captions/> once at the end. G.mount stays 0/0.
const Content: React.FC = () => {
  const {card} = useCard(); const Comp = CARDS[card.type];
  if (!Comp) throw new Error('unknown card type ' + card.type);
  if (card.type === 'engage') return <><DarkBg /><Comp /></>;
  return <><div lang="ne" style={{position: 'absolute', left: G.mount.x, top: G.mount.y, width: 1080, height: 1920, fontFamily: 'Mukta'}}><Comp /></div><Strip /></>;
};

export const Reel: React.FC<Props> = (props) => {
  const plan = useMemo(() => buildPlan(props), [props]);
  const chunks = useMemo(() => buildChunks(plan.filter((it) => it.card.type !== 'engage')), [plan]);
  return <AbsoluteFill style={{fontFamily: 'Mukta', background: '#110F0F'}}>
    {plan.map((it) => <Sequence key={it.idx} from={it.from} durationInFrames={it.frames} name={`${it.idx + 1} ${it.card.type}`}>
      <CardCtx.Provider value={{it, lite: !!props.lite}}>
        <Content />{props.story.sample ? <Sample dark={!!it.card.dark} /> : null}<CardSound it={it} />
      </CardCtx.Provider></Sequence>)}
    <Captions chunks={chunks} />
    <Bed plan={plan} />
  </AbsoluteFill>;
};

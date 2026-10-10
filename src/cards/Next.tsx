import React from 'react';
import {K, G} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {ne} from '../fmt';
import {cueMs} from '../plan';
import {Card, Kick, Hl, glass} from './ui';
// v12 next: kicker 'अब के?' | headline | up to 3 steps on voice beats. Step = date chip (glass r18, 800 44, pad 14/22; hi = red fill + glow)
// + gap 28 + text 600 48/64 paper. Steps gap 28.
export const Next: React.FC = () => { const {card, it} = useCard(); const st = (card.steps || []).slice(0, 3);
  return <Card><Kick s={card.kicker ?? 'अब के?'} /><Hl s={card.headline} lines={2} />
    {st.map((s: any, k: number) => <In key={k} at={cueMs(it, 'beat', k + 0.5, st.length + 0.5)} style={{marginTop: 28}}>
      <div style={{display: 'flex', gap: 28, alignItems: 'center', width: G.w}}>
        <span style={{...glass(false, 18), ...(s.hi ? {background: K.redFill, boxShadow: K.redGlow} : {}), color: K.paper, font: '800 44px/1 Mukta',
          padding: '18px 22px 12px', whiteSpace: 'nowrap'}}>{ne(s.date)}</span>
        <span style={{font: '600 48px/64px Mukta', color: K.paper}}><Rich s={s.text} /></span></div></In>)}</Card>; };

import React from 'react';
import {K, G, TS} from '../theme';
import {useCard, In} from '../components/ctx';
import {Lines} from '../components/Lines';
import {ne} from '../fmt';
import {cueMs} from '../plan';
import {MS, prog, E} from '../motion';
import {Card, Kick, Hl, glass} from './ui';
// v12 points: exactly 3, each enters on its own voice beat (masked rise). The row being spoken is LIVE:
// its 88x88 tile turns engage-red (crossfade 200 ms) and its text is full paper; earlier rows settle to paper .55.
// Row: tile 88x88 r22 (glass) | gap 32 | text 600 52/68 -> 42/56 on w740, max 2 lines (3 at the last rung). Row gap 34.
export const Points: React.FC = () => { const {card, it, frame} = useCard(); const pts = (card.points || []).slice(0, 3);
  const beats = pts.map((_: string, k: number) => cueMs(it, 'beat', k, 3));
  return <Card rule={beats[0]}><Kick s={card.kicker} /><Hl s={card.title} lines={1} />
    {pts.map((p: string, k: number) => {
      const on = prog(frame, beats[k], MS.active, E.settle) - (k < pts.length - 1 ? prog(frame, beats[k + 1], MS.active, E.settle) : 0);
      const past = k < pts.length - 1 ? prog(frame, beats[k + 1], MS.active, E.settle) : 0;
      return <In key={k} at={beats[k]} style={{marginTop: 34}}>
        <div style={{display: 'flex', gap: 32, alignItems: 'flex-start'}}>
          <div style={{position: 'relative', flex: '0 0 88px', height: 88, ...glass(false, 22)}}>
            <div style={{position: 'absolute', inset: 0, borderRadius: 22, background: K.redFill, boxShadow: K.redGlow, opacity: on}} />
            <div style={{position: 'relative', font: '800 52px/92px Mukta', textAlign: 'center', color: K.paper}}>{ne(k + 1)}</div></div>
          <div style={{paddingTop: 10, opacity: 1}}><Lines s={p} ladder={TS.body} width={G.w - 120} weight="600" now read base={k} exit={false} /></div>
        </div></In>; })}</Card>; };

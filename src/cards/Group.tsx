import React from 'react';
import {K, G} from '../theme';
import {useCard, In} from '../components/ctx';
import {Rich} from '../components/Rich';
import {ne} from '../fmt';
import {cueMs} from '../plan';
import {Card, Kick, Hl, glass} from './ui';
// v12 group ("who is affected"): a ledger of glass rows, 104 high, r28, gap 14, pad 0/36, on voice beats.
// label 600 46 paper .8 left | value 800 60 right-aligned at x904. hi row: red ring, value red + halo.
export const Group: React.FC = () => { const {card, it} = useCard(); const rows = (card.rows || []).slice(0, 4);
  return <Card><Kick s={card.kicker} /><Hl s={card.headline} lines={2} /><div style={{height: 20}} />
    {rows.map((r: any, k: number) => <In key={k} at={cueMs(it, 'beat', k, rows.length)} style={{marginTop: 14}}>
      <div style={{width: G.w, height: 104, boxSizing: 'border-box', padding: '0 36px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', ...glass(!!r.hi)}}>
        <span style={{font: '600 46px/1.3 Mukta', color: 'rgba(243,237,227,.8)'}}><Rich s={r.label} /></span>
        <span style={{font: '800 60px/1.2 Mukta', color: r.hi ? K.red : K.paper, whiteSpace: 'nowrap', textShadow: r.hi ? K.redText : undefined}}><Rich s={ne(r.value)} /></span></div></In>)}</Card>; };

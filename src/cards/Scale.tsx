import React from 'react';
import {useCard, In} from '../components/ctx';
import {ne} from '../fmt';
import {MS} from '../motion';
import {Card, Kick, Sec, Hl, Figure, figSize} from './ui';
// v12 scale: same anatomy as BigNum (one figure system). Figure 800 300 -> 160, no count (the number is a phrase, e.g. २.१%).
export const Scale: React.FC = () => { const {card, it} = useCard(); const n = ne(card.number); const fs = figSize(n, 300, 160);
  return <Card rule={MS.lead + it.voMs * 0.3}><Kick s={card.kicker} />
    <In i={0} hero><Figure final={n} size={fs} glow={0.3} /></In><div style={{height: 20}} />
    <Hl s={card.headline} lines={2} at={MS.lead + it.voMs * 0.3} /><Sec s={card.sub} at={MS.lead + it.voMs * 0.6} /></Card>; };

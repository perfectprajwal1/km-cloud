import React, {createContext, useContext} from 'react';
import {useCurrentFrame} from 'remotion';
import {PlanItem} from '../types';
import {MS, prog, E, f} from '../motion';
export const CardCtx = createContext<{it: PlanItem; lite: boolean} | null>(null);
export const useCard = () => {
  const v = useContext(CardCtx)!; const frame = useCurrentFrame();
  const exitStart = v.it.last ? 1e9 : v.it.durMs - MS.exit;
  const exitP = prog(frame, exitStart, MS.exit, E.exit);
  return {...v, frame, card: v.it.card, dark: !!v.it.card.dark, exitP, durF: f(v.it.durMs)};
};
// Entrance (v12): MASKED rise. The block rises 72 px from behind its own bottom edge, 600 ms quint-out, staggered 90 ms.
// Only the bottom edge clips (inset bottom -14 px keeps descenders), so glows, matras and pill shadows are never cut.
// The mask is dropped once settled. Exit: lift 48 px + fade, 200 ms ease-in. No scale, no blur.
export const In: React.FC<{i?: number; at?: number; now?: boolean; hero?: boolean; style?: React.CSSProperties; children: React.ReactNode}> =
  ({i = 0, at, now, hero, style, children}) => {
    const {frame, exitP, it, card} = useCard();
    const skip = now || (hero && it.carry) || (card.dark && hero); // carried / dark hero = already there, hard cut
    const start = at ?? i * MS.stagger;
    const p = skip ? 1 : prog(frame, start, MS.enter, E.rise);
    return <div style={{...style, clipPath: p < 1 ? 'inset(-400px -400px -14px -400px)' : undefined}}>
      <div style={{opacity: Math.min(1, p * 1.6) * (1 - exitP), transform: `translateY(${(1 - p) * MS.rise - exitP * MS.exitFall}px)`}}>{children}</div></div>;
  };

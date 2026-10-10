import React from 'react';
import {Img, staticFile} from 'remotion';
import {K, G} from '../theme';
import {MS, f} from '../motion';
import {useCard} from '../components/ctx';
// The one stage every story card stands on: the engage card's room. Layers, back to front:
// L0 ink #110F0F | L1 red bloom 1100 px @ (180+d, 240) .24 -> .06 | L2 deep bloom 900x700 @ (980-d, 1780) .16 (sits under the strip)
// L3 halftone 18 px dots .07, masked to the bloom | L4 fractal grain .07 overlay | L5 vignette .55 | L6 logo 176 @ 80,168 | L7 content.
// Drift runs on GLOBAL time (it.from + frame), so two cards meet pixel-identical at the cut: the stage never cuts, only the words do.
export const Stage: React.FC<{children: React.ReactNode}> = ({children}) => {
  const {it, frame, lite, durF} = useCard();
  const gt = (it.from + frame) / 30;
  const d = lite ? 0 : Math.sin(gt * MS.stageHz) * MS.stageDrift;
  const push = lite ? 1 : 1 + MS.stagePush * (0.5 + 0.5 * Math.sin(gt * 0.18));
  const mask = `radial-gradient(760px 640px at ${160 + d}px 260px, #000, transparent 75%)`;
  return <div lang="ne" style={{position: 'absolute', left: -G.mount.x, top: -G.mount.y, width: 1080, height: 1920, overflow: 'hidden',
    background: K.ink, color: K.paper, fontFamily: 'Mukta'}}>
    <div style={{position: 'absolute', inset: 0, transform: `scale(${push}) translateX(${d * 0.3}px)`, transformOrigin: '17% 12%'}}>
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(1100px 1100px at ${180 + d}px 240px, rgba(215,20,30,.24), rgba(215,20,30,.06) 45%, transparent 70%)`}} />
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(900px 700px at ${980 - d}px 1780px, rgba(158,12,20,.16), transparent 70%)`}} />
      <div style={{position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(rgba(243,237,227,.9) 1.6px, transparent 2.2px)', backgroundSize: '18px 18px',
        opacity: 0.07, maskImage: mask, WebkitMaskImage: mask}} />
    </div>
    {lite ? null : <svg width="1080" height="1920" style={{position: 'absolute', inset: 0, opacity: 0.07, mixBlendMode: 'overlay'}}>
      <filter id="km-grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" seed="0" />
        <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1 0" /></filter>
      <rect width="100%" height="100%" filter="url(#km-grain)" /></svg>}
    <div style={{position: 'absolute', inset: 0, background: 'radial-gradient(130% 90% at 50% 45%, transparent 55%, rgba(0,0,0,.55) 100%)'}} />
    <Img src={staticFile('logo.png')} style={{position: 'absolute', left: G.logo.x, top: G.logo.y, width: G.logo.w, filter: 'drop-shadow(0 14px 30px rgba(0,0,0,.5))'}} />
    {children}
  </div>;
};

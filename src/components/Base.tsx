import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {C, L} from '../theme';
// Paper: one static master PNG, never animated. Logo: fixed slot, never moves.
export const Paper: React.FC = () => <Img src={staticFile('paper_v9.png')} style={{position: 'absolute', left: 0, top: 0, width: L.W, height: L.H}} />;
export const DarkBg: React.FC = () => <AbsoluteFill style={{background: C.ink}} />;
export const Logo: React.FC = () => <Img src={staticFile('logo.png')} style={{position: 'absolute', left: L.logo.x, top: L.logo.y, width: L.logo.w}} />;
export const Sample: React.FC<{dark: boolean}> = ({dark}) => (
  <div style={{position: 'absolute', right: 90, top: 214, background: dark ? C.paper : C.ink, color: dark ? C.ink : C.paper,
    font: '800 44px/1 Mukta', padding: '14px 20px 10px', borderRadius: 6}}>SAMPLE</div>);

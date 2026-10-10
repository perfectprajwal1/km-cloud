import React from 'react';
import {interpolate} from 'remotion';
import {ne} from '../fmt';
import {MS, f, E} from '../motion';
import {cueMs} from '../plan';
import {useCard} from './ctx';
// Lands exactly on the spoken number (story card "say"), 800 ms (900 on dark), COUNT easing.
export const countWindow = (it: any) => {
  const land = cueMs(it, 'land'); const dur = it.card.dark ? MS.countDark : MS.count;
  return {start: Math.max(0, land - dur), land};
};
export const CountUp: React.FC<{to: number; from?: number; dec?: number}> = ({to, from = 0, dec = 0}) => {
  const {frame, it} = useCard(); const {start, land} = countWindow(it);
  const v = interpolate(frame, [f(start), f(land)], [it.carry ? to : from, to],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: E.count});
  return <>{ne(dec ? v : Math.round(v), dec)}</>;
};

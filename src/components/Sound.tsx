import React from 'react';
import {Audio, Sequence, staticFile} from 'remotion';
import {MS, f, dB} from '../motion';
import {cueMs} from '../plan';
import {countWindow} from './CountUp';
import {PlanItem} from '../types';
import {engageTimes} from '../cards/Engage';
// SFX peaks are baked into the wavs by make_sfx.py (swipe -20, marker -24, tick -28/-22, thump -12, pen -24 dBFS).
const Sfx: React.FC<{name: string; atMs: number; vol?: number}> = ({name, atMs, vol = 1}) =>
  <Sequence from={Math.max(0, f(atMs))} durationInFrames={f(1200)} layout="none"><Audio src={staticFile(`sfx/${name}.wav`)} volume={vol} /></Sequence>;
export const CardSound: React.FC<{it: PlanItem}> = ({it}) => {
  const c = it.card; const out: React.ReactNode[] = [];
  if (c.type === 'engage') {
    const audio = (name: string, atMs: number, vol: number) =>
      <Sequence key={name + atMs} from={f(atMs)} layout="none">
        <Audio src={staticFile(`sfx/${name}`)} volume={vol} />
      </Sequence>;
    return <>{audio(c.sfx?.cta || 'Click.mp3', engageTimes(it).button * 1000, dB(-20))}
      {it.voice ? <Audio src={staticFile(it.voice)} /> : null}</>;
  }
  if (it.idx === 0 || c.dark) out.push(<Sfx key="th" name="thump" atMs={0} vol={0.6} />);
  else out.push(<Sfx key="sw" name="paper_swipe" atMs={0} vol={0.45} />);
  const pills = (JSON.stringify({...c, strip: null}).match(/\{\{/g) || []).length + (c.delta ? 1 : 0);
  for (let k = 0; k < pills; k++) out.push(<Sfx key={'m' + k} name="marker" atMs={cueMs(it, 'pill', k)} vol={0.5} />);
  if (c.type === 'bignum' || c.type === 'date') {
    const {land} = countWindow(it);
    out.push(<Sfx key="t0" name="tick_hi" atMs={land} vol={0.5} />);
  }
  if (c.type === 'change') out.push(<Sfx key="pen" name="pen_tap" atMs={MS.lead + it.voMs * 0.25} vol={0.5} />);
  if (c.strip?.kind === 'timeline') out.push(<Sfx key="pt" name="pen_tap" atMs={MS.lead + MS.stripDelay + 300 + MS.marker * 0.6} />);
  if (it.voice) out.push(<Sequence key="vo" from={f(MS.lead)} layout="none"><Audio src={staticFile(it.voice)} /></Sequence>);
  return <>{out}</>;
};
// Room-tone bed: never silent. -38 LUFS free, ducked 8-10 dB under voice (attack 80 ms from 60 ms before VO, release 400 ms).
export const Bed: React.FC<{plan: PlanItem[]; file?: string}> = ({plan, file = 'sfx/roomtone.wav'}) => {
  const iv = plan.map((p) => { const lead = p.card.type === 'engage' ? 0 : MS.lead;
    return [p.from + f(lead), p.from + f(lead + p.voMs)]; });
  const duck = dB(-10), A = f(80), Rl = f(400), pre = f(60);
  const vol = (fr: number) => {
    let env = 0;
    for (const [s, e] of iv) {
      let v = 0;
      if (fr >= s - pre && fr <= e) v = Math.min(1, (fr - (s - pre)) / Math.max(1, A));
      else if (fr > e && fr < e + Rl) v = 1 - (fr - e) / Rl;
      env = Math.max(env, v);
    }
    return 1 - (1 - duck) * env;
  };
  return <Audio src={staticFile(file)} loop volume={vol} />;
};

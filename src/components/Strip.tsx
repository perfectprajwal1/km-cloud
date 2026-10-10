import React from 'react';
import {Img, staticFile} from 'remotion';
import {K, L} from '../theme';
import {MS, prog, E} from '../motion';
import {ne} from '../fmt';
import {useCard} from './ctx';
import {AnimatedStrip} from './AnimatedStrip';
import {fitSize} from './fit';
// v12.3: full original 1080x650 drawing at y1270. No safe-area shrink.
// The label keeps its own top lane. Some legacy content sits below Reels UI by choice.
const lab: React.CSSProperties = {position: 'absolute', font: '600 42px/56px Mukta', color: K.dim};
export const Strip: React.FC = () => {
  const {frame, card, it, durF, lite, exitP} = useCard();
  const s = card.strip || {kind: 'echo'};
  if (s.kind === 'none') return null;
  const t0 = MS.lead + 120;
  const enter = it.carry ? 1 : prog(frame, t0, 600, E.rise);
  const label = s.label && (s.kind === 'photo' || s.kind === 'graphic');
  const nn = String(it.idx + 1).padStart(2, '0');
  const safeH = 650;
  const labelNode = label ? <div style={{position: 'absolute', left: 80, top: 0, width: 860, height: 38, display: 'flex', alignItems: 'center', gap: 14, color: K.dim,
    font: `600 ${fitSize(ne(s.label), 32, 24, 822, 1, '600')}px/38px Mukta`}}><div style={{width:12,height:12,flexShrink:0,borderRadius:2,background:K.red}} />{ne(s.label)}</div> : null;
  const wrap = (child: React.ReactNode) => <div style={{position:'absolute',left:0,top:L.strip.y,width:L.W,height:L.strip.h,overflow:'hidden'}}>
    <div style={{position:'absolute',inset:0,background:'linear-gradient(180deg,rgba(0,0,0,.22),transparent 110px)'}} />
    <div style={{position:'absolute',left:0,top:0,width:1080,height:2,background:'linear-gradient(90deg,rgba(243,237,227,.08),rgba(243,237,227,.40) 12%,rgba(243,237,227,.40) 88%,rgba(243,237,227,.08))',boxShadow:'0 0 10px rgba(243,237,227,.10)',opacity:1-exitP,clipPath:`inset(0 ${(1-prog(frame,t0,320,E.wipe))*100}% 0 0)`}} />
    <div style={{position:'absolute',left:0,top:0,width:L.W,height:safeH,overflow:'hidden',opacity:enter*(1-exitP),transform:`translateY(${(1-enter)*24-exitP*18}px)`}}>{child}</div>
  </div>;
  if (s.kind === 'photo' || s.kind === 'graphic') {
    const offset = 0;
    return wrap(<>{s.kind === 'photo' && !s.anim ? <><Img src={staticFile(`strips/strip_${nn}.png`)} style={{position:'absolute',left:0,top:offset,width:1080,height:safeH-offset,objectFit:'cover',borderRadius:0,
      transform:lite ? undefined : `scale(${1+0.015*frame/Math.max(1,durF)})`}} /><div style={{position:'absolute',left:0,top:offset,width:1080,height:safeH-offset,background:`linear-gradient(180deg,${K.ink},transparent 110px,transparent 260px,${K.ink})`}} /></> :
      <div style={{position:'absolute',left:0,top:offset,width:1080,height:650}}>
        {s.anim ? <AnimatedStrip anim={s.anim} durationInFrames={durF} /> : <Img src={staticFile(`strips/strip_${nn}.png`)} style={{width:1080,height:650,objectFit:'contain'}} />}
      </div>}{labelNode}</>);
  }
  if (s.kind === 'bars') {
    const items=s.items.slice(0,3); const mx=Math.max(1,...items.map((x:any)=>+x.value));
    return wrap(<>{items.map((x:any,j:number)=>{const p=prog(frame,t0+j*90,700,E.settle);const y=70+j*104;
      // Values have a fixed right column, not a moving label that can crash into the rail.
      return <React.Fragment key={j}><div style={{...lab,left:80,top:y,width:260,fontSize:fitSize(ne(x.label),42,28,250,1,'600'),whiteSpace:'nowrap'}}>{ne(x.label)}</div>
        <div style={{position:'absolute',left:366,top:y,width:370,height:56,borderRadius:28,background:K.ghost}} />
        <div style={{position:'absolute',left:366,top:y,width:Math.max(4,370*(+x.value/mx)*p),height:56,borderRadius:28,opacity:p,background:x.hi?K.redFill:K.dim}} />
        <div style={{...lab,left:758,top:y,width:182,textAlign:'right',color:K.paper,fontSize:fitSize(ne(x.display??x.value),46,28,182,1,'800'),fontWeight:800,opacity:p}}>{ne(x.display??x.value)}</div></React.Fragment>;
    })}</>);
  }
  if (s.kind === 'dots') {
    const tot=Math.max(0,Math.min(100,s.total));
    return wrap(<><div style={{...lab,left:80,top:24,width:860,fontSize:fitSize(ne(s.label),42,28,860,1,'600')}}>{ne(s.label)}</div>
      {Array.from({length:tot}).map((_,j)=>{const q=prog(frame,t0+j*Math.min(10,700/Math.max(1,tot)),180,E.settle);return <div key={j} style={{position:'absolute',left:80+(j%20)*42,top:114+Math.floor(j/20)*46,width:24,height:24,borderRadius:12,
        background:j<s.hi?K.red:K.ghost,opacity:q,transform:`scale(${.92+.08*q})`}} />;})}</>);
  }
  if (s.kind === 'timeline') {
    const ticks=s.ticks.slice(0,7);const step=820/Math.max(1,ticks.length-1);const idx=Math.max(0,Math.min(ticks.length-1,s.at||0));const x=100+idx*step;const m=prog(frame,t0+200,420,E.settle);
    return wrap(<><div style={{position:'absolute',left:100,top:180,width:820,height:4,background:K.line}} /><div style={{position:'absolute',left:100,top:180,width:(x-100)*m,height:4,background:K.red}} />
      {ticks.map((tk:string,j:number)=><React.Fragment key={j}><div style={{position:'absolute',left:98+j*step,top:170,width:4,height:24,background:K.dim}} /><div style={{...lab,left:40+j*step,top:218,width:120,textAlign:'center',fontSize:fitSize(ne(tk),36,24,120,2,'600')}}>{ne(tk)}</div></React.Fragment>)}
      <div style={{position:'absolute',left:x-14,top:168-(1-m)*24,width:28,height:28,borderRadius:14,background:K.red,opacity:m,boxShadow:'0 0 20px rgba(215,20,30,.3)'}} />
      {s.label?<div style={{...lab,left:80,top:36,width:860,color:K.paper,fontSize:fitSize(ne(s.label),44,28,860,1,'800'),fontWeight:800,opacity:m}}>{ne(s.label)}</div>:null}</>);
  }
  const txt=ne(s.text??card.number??(card.value!=null?ne(card.value,card.decimals||0):''));
  const fs=fitSize(txt,720,100,960,1);
  return wrap(<div style={{position:'absolute',left:60,top:-40,width:960,font:`800 ${fs}px/1.1 Mukta`,whiteSpace:'nowrap',color:'rgba(243,237,227,.02)',WebkitTextStroke:'2px rgba(243,237,227,.1)',transform:lite?undefined:`translateX(${-8*frame/Math.max(1,durF)}px)`}}>{txt}</div>);
};

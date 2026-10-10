import React from 'react';
import {Img, staticFile} from 'remotion';
import {measureText} from '@remotion/layout-utils';
import {PlanItem} from '../types';
import {useCard} from '../components/ctx';

const C = {ink: '#110F0F', paper: '#F3EDE3', red: '#D7141E', deep: '#9E0C14'};
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const prog = (t: number, start: number, dur: number) => clamp((t - start) / dur);
const expo = (p: number) => p >= 1 ? 1 : 1 - Math.pow(2, -10 * p);
const quint = (p: number) => 1 - Math.pow(1 - p, 5);
const spring = (t: number, start: number, damping: number, frequency: number) => {
  const x = t - start; if (x <= 0) return 0;
  const w = frequency * Math.sqrt(1 - damping * damping);
  return 1 - Math.exp(-damping * frequency * x) * (Math.cos(w * x) + damping * frequency / w * Math.sin(w * x));
};
const wordText = (s: string) => s.replace(/[।?!,]/g, '').trim();
// The HTML preview assumes question .30-2.85s, CTA 3.0-3.9s. Real voice wins.
export const engageTimes = (it: PlanItem) => {
  const ws = it.words; const split = ws.findIndex((w) => wordText(w.w).includes('कमेन्टमा'));
  const end = it.voMs / 1000;
  const cta = split >= 0 ? ws[split].t / 1000 : Math.max(0.3, end * (3 / 3.9));
  const readEnd = split > 0 ? (ws[split - 1].t + ws[split - 1].d) / 1000 : cta * 0.95;
  return {cta, read0: ws[0]?.t / 1000 || 0, readEnd, composer: Math.max(0.6, cta - 0.4),
    button: Math.max(0.78, cta - 0.22), dots: cta + 0.35, pulse: Math.max(cta + 0.95, end + 0.05)};
};
const width = (s: string, size: number, weight = '800') => measureText({text: s, fontFamily: 'Mukta', fontWeight: weight, fontSize: size, letterSpacing: '-0.005em'}).width;
const layout = (question: string, supplied?: string[]) => {
  const words = question.split(/\s+/).filter(Boolean);
  const split = (size: number, lines: number): string[] | null => {
    if (supplied?.length && supplied.join(' ') === words.join(' ') && supplied.length <= 3 && supplied.every((s) => width(s, size) <= 860)) return supplied;
    let best: string[] | null = null, score = Infinity;
    const test = (a: number, b?: number) => {
      const ls = b == null ? [words.slice(0, a).join(' '), words.slice(a).join(' ')]
        : [words.slice(0, a).join(' '), words.slice(a, b).join(' '), words.slice(b).join(' ')];
      const w = ls.map((s) => width(s, size)); if (w.some((x) => x > 854)) return;
      // Prefer later lines longer, balanced by phrase-sized whitespace breaks.
      const cost = w.reduce((s, x) => s + (860 - x) ** 2, 0) + w.slice(1).reduce((s, x, i) => s + Math.max(0, w[i] - x) ** 2 * 2, 0);
      if (cost < score) {score = cost; best = ls;}
    };
    for (let a = 1; a < words.length; a++) {
      if (lines === 2) test(a); else for (let b = a + 1; b < words.length; b++) test(a, b);
    }
    return best;
  };
  if (!supplied || supplied.length === 2) { const ls = split(112, 2); if (ls) return {lines: ls, size: 112, lh: 144}; }
  for (const size of [100, 92, 84]) {const ls = split(size, 3); if (ls) return {lines: ls, size, lh: 130};}
  // The converter bounds questions to 110 characters. An explicit exceptional
  // oversized line stays verbatim, rather than truncating the viewer's question.
  const rows: string[] = []; let row = '';
  for (const word of words) {if (row && width(row + ' ' + word, 84) > 854) {rows.push(row); row = word;} else row += (row ? ' ' : '') + word;}
  if (row) rows.push(row); return {lines: rows, size: 84, lh: 130};
};

export const Engage: React.FC = () => {
  const {card, it, frame, lite} = useCard(); const t = frame / 30;
  const times = engageTimes(it); const q = layout(card.question || '', card.question_lines);
  const top = 1124 - q.lines.length * q.lh; const drift = lite ? 0 : Math.sin(t * 0.7) * 26;
  const push = lite ? 1 : 1 + 0.035 * clamp(t / (it.durMs / 1000));
  const kicker = expo(prog(t, 0, 0.5)), block = spring(t, 0.02, 0.55, 18);
  const comp = spring(t, times.composer, 0.82, 12), button = spring(t, times.button, 0.5, 16);
  const reveal = quint(prog(t, times.cta, 0.9)); const cta = card.cta || 'कमेन्टमा भन्नुस्';
  const ctaWidth = width(cta, 56, '700');
  const caret = t < times.cta + 1 ? (Math.floor(t * 4) % 2 === 0 || reveal > 0 && reveal < 1) : Math.floor(t * 1.9) % 2 === 0;
  const flat = q.lines.join(' ').split(/\s+/); const total = flat.reduce((s, w) => s + w.length + 1, 0); let consumed = 0, index = 0;
  return <div lang="ne" style={{position: 'absolute', inset: 0, overflow: 'hidden', background: C.ink, color: C.paper, fontFamily: 'Mukta'}}>
    <div style={{position: 'absolute', inset: 0, transform: `scale(${push}) translateX(${drift * 0.3}px)`, transformOrigin: '20% 15%'}}>
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(1100px 1100px at ${180 + drift}px 240px, rgba(215,20,30,.24), rgba(215,20,30,.06) 45%, transparent 70%)`}} />
      <div style={{position: 'absolute', inset: 0, background: `radial-gradient(900px 700px at ${980 - drift}px 1780px, rgba(158,12,20,.16), transparent 70%)`}} />
      <div style={{position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(rgba(243,237,227,.9) 1.6px, transparent 2.2px)', backgroundSize: '18px 18px', opacity: .07,
        maskImage: `radial-gradient(760px 640px at ${160 + drift}px 260px, #000, transparent 75%)`, WebkitMaskImage: `radial-gradient(760px 640px at ${160 + drift}px 260px, #000, transparent 75%)`}} />
    </div>
    <svg width="1080" height="1920" style={{position: 'absolute', inset: 0, opacity: .07, mixBlendMode: 'overlay'}}>
      <filter id="engage-grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" seed="0" /><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 1 0" /></filter>
      <rect width="100%" height="100%" filter="url(#engage-grain)" />
    </svg>
    <div style={{position: 'absolute', inset: 0, background: 'radial-gradient(130% 90% at 50% 45%, transparent 55%, rgba(0,0,0,.55) 100%)'}} />
    <Img src={staticFile('logo.png')} style={{position: 'absolute', left: 80, top: 168, width: 176, filter: 'drop-shadow(0 14px 30px rgba(0,0,0,.5))'}} />
    <div style={{position: 'absolute', left: 80, top: top - 64, height: 48, display: 'flex', alignItems: 'center', gap: 18}}>
      <div style={{width: 20, height: 20, borderRadius: 3, background: C.red, transform: `scale(${block})`, boxShadow: '0 0 24px rgba(215,20,30,.6)'}} />
      <div style={{font: '600 40px/48px Mukta', letterSpacing: '.01em', color: 'rgba(243,237,227,.62)', opacity: kicker, transform: `translateX(${(1-kicker)*-16}px)`}}>आजको प्रश्न</div>
    </div>
    <div style={{position: 'absolute', left: 80, top, width: 860}}>
      {q.lines.map((line, li) => {
        const rise = quint(prog(t, .12 + li * .09, .6));
        return <div key={li} style={{height: q.lh, overflow: 'hidden'}}><div style={{font: `800 ${q.size}px/${q.lh}px Mukta`, letterSpacing: '-.005em', whiteSpace: 'nowrap', transform: `translateY(${(1-rise)*q.lh*.9}px)`, textShadow: '0 2px 0 rgba(0,0,0,.25), 0 18px 50px rgba(0,0,0,.45)'}}>
          {line.split(/\s+/).map((word, wi, words) => {
            const timed = it.words[index++]; const at = timed ? timed.t / 1000 : times.read0 + consumed / total * (times.readEnd - times.read0); consumed += word.length + 1;
            const bright = .4 + .6 * quint(prog(t, at, .28)); const questionMark = word.endsWith('?');
            return <span key={wi} style={{opacity: bright}}>{questionMark ? <>{word.slice(0,-1)}<span style={{color: C.red, marginLeft: '.04em'}}>?</span></> : word}{wi < words.length-1 ? ' ' : ''}</span>;
          })}
        </div></div>;
      })}
    </div>
    <div style={{position: 'absolute', left: 80, top: 1164, width: 120, height: 10, borderRadius: 2, background: C.red, transform: `scaleX(${expo(prog(t,.55,.55))})`, transformOrigin: '0 50%'}} />
    <div style={{position: 'absolute', left: 80, top: 1236, width: 860, height: 148, opacity: clamp(comp*1.4), transform: `translateY(${(1-comp)*60}px)`}}>
      <div style={{position: 'absolute', inset: 0, borderRadius: 74, background: 'linear-gradient(180deg,rgba(243,237,227,.10),rgba(243,237,227,.04))', boxShadow: 'inset 0 0 0 2px rgba(243,237,227,.12), inset 0 2px 0 rgba(243,237,227,.10), 0 30px 80px -20px rgba(0,0,0,.7)', backdropFilter: 'blur(14px)'}} />
      <div style={{position: 'absolute', left: 26, top: 26, width: 96, height: 96, borderRadius: 48, background: 'linear-gradient(160deg,#3A3232,#221C1C)', boxShadow: 'inset 0 0 0 2px rgba(243,237,227,.10)', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="rgba(243,237,227,.55)" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="8.5" r="3.6" /><path d="M5 19.5c1.4-3.3 4-5 7-5s5.6 1.7 7 5" /></svg>
      </div>
      <div style={{position: 'absolute', left: 148, top: 0, height: 148, display: 'flex', alignItems: 'center'}}>
        <div style={{width: ctaWidth * reveal, overflow: 'hidden', whiteSpace: 'nowrap'}}><span style={{font: '700 56px/148px Mukta'}}>{cta}</span></div>
        <div style={{width: 5, height: 62, marginLeft: 6, borderRadius: 3, background: C.paper, opacity: caret ? 1 : 0}} />
      </div>
      {[0,.45].map((offset,i) => {const p=prog(t,times.pulse+offset,.95);return <div key={i} style={{position:'absolute',left:728,top:16,width:116,height:116,borderRadius:58,border:`4px solid ${C.red}`,boxSizing:'border-box',opacity:p>0&&p<1?.6*(1-p):0,transform:`scale(${1+.9*quint(p)})`}} />;})}
      <div style={{position: 'absolute', left: 728, top: 16, width: 116, height: 116, borderRadius: 58, background: `radial-gradient(120% 120% at 30% 20%,#F0303A,${C.red} 45%,${C.deep})`, boxShadow: '0 18px 50px -6px rgba(215,20,30,.6), inset 0 2px 0 rgba(243,237,227,.25)', transform: `scale(${button})`, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none"><path d="M32 9c13.8 0 24 8.9 24 20.5S45.8 50 32 50c-2.6 0-5.1-.3-7.4-.9L13 55l2.6-10.6C11 40.7 8 35.4 8 29.5 8 17.9 18.2 9 32 9Z" fill={C.paper} />
          {[0,1,2].map((i)=>{const active=t>=times.dots, phase=active?(t-times.dots)*5.2-i*.9:-10;const y=phase>0?Math.max(0,Math.sin(phase%(Math.PI*2.4)))*4:0;return <circle key={i} cx={21+i*11} cy={29.5-y} r="3.6" fill={C.red} opacity={active?.55+y/9:.9} />;})}
        </svg>
      </div>
    </div>
  </div>;
};

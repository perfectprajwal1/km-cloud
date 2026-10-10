/**
 * AnimatedStrip.ts - Khabar Minute bottom-half strip (1080x650), animated.  v3
 *
 * Plays the "anim" spec that scripts/script_to_story.py writes into each card:
 *   story.cards[i].strip.anim = {v, kind, dark, fit, icons, ...}
 *   kind: 'stat' | 'concept' | 'place' | 'phrase' | 'calendar' | 'track' | 'units' | 'waffle'
 * Everything is timed to the card length, and each step / place / word comes in at
 * the moment it is spoken in the voice line ("at" = 0..1 of the card).
 *
 * v12 "Night Desk": the strip is the floor of the card's room, not a framed box. Corner marks removed; every plate is engage
 * glass (gradient .10->.04, 2 px inset ring, r28, deep drop shadow); every "filled" thing is the engage red button
 * (radial #F0303A -> #D7141E -> #9E0C14 + red glow); pulses are the engage CTA ring (4 px, scale 1 -> 1.9, .6 -> 0).
 * Always rendered on ink: anim.dark is accepted and ignored. Legacy coordinates are unchanged; Strip scales the drawing into the safe area.
 * v12.2: spring landings are damped, accents fire once, and late beats leave room for settling before exit.
 * v3: all four corner marks are red; every drawing is scaled and centred to fill the strip;
 * number cards whose number the top half already shows get calendar / track / units / waffle
 * (what the number means) instead of the same big number a second time.
 *
 * Use (inside the card's <Sequence>, where the old strip <Img> was):
 *   {card.strip.anim ? <AnimatedStrip anim={card.strip.anim} durationInFrames={durF} /> : <Img src={...} />}
 * If your card is NOT inside its own <Sequence>, pass the timing yourself:
 *   <AnimatedStrip anim={...} startFrame={cardStart} durationInFrames={cardFrames} />
 *
 * Transparent background, so your paper texture shows through. No extra npm packages.
 */
import React from 'react';
import {continueRender, delayRender, Easing, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

const h = React.createElement;
const RED = '#D7141E';
const ON_RED = '#F3EDE3';
const FILL = 'radial-gradient(120% 120% at 30% 20%,#F0303A,#D7141E 45%,#9E0C14)';
const GLOW = '0 18px 50px -6px rgba(215,20,30,.6), inset 0 2px 0 rgba(243,237,227,.25)';
const GLASS = 'linear-gradient(180deg,rgba(243,237,227,.10),rgba(243,237,227,.04))';
const RING = 'inset 0 0 0 2px rgba(243,237,227,.12), inset 0 2px 0 rgba(243,237,227,.10), 0 30px 80px -20px rgba(0,0,0,.7)';
const RED_TEXT = '0 0 50px rgba(215,20,30,.35)';
const glassBox = (filled: boolean, r = 28): React.CSSProperties => filled ? {background: FILL, boxShadow: GLOW, borderRadius: r} : {background: GLASS, boxShadow: RING, borderRadius: r};
// one SVG gradient for discs / rings that must be drawn in SVG
const RedDef = (id: string) => h('defs', {key: 'defs'}, h('radialGradient', {id, cx: '30%', cy: '20%', r: '120%'},
	h('stop', {offset: '0%', stopColor: '#F0303A'}), h('stop', {offset: '45%', stopColor: '#D7141E'}), h('stop', {offset: '100%', stopColor: '#9E0C14'})));
const W = 1080;
const H = 650;
const FONT = 'Mukta';
const PIN_D = 'M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z';

export type StripNode = {ne: string; icon: string; at: number};
export type StripPlace = {ne: string; sub?: string; focus?: boolean; at: number};
export type StripWord = {t: string; key?: boolean; at: number};
export type StripStat = {
	label: string; prefix: string; num: number | null; numText: string; unit: string;
	decimals: number; comma: boolean; percent: number | null; at: number;
};
export type StripCalendar = {
	month: string; head: string; weekday: string; days: string[]; wds: string[] | null; hi: number; icon: string; at: number;
	layout: {x0: number; cw: number; gap: number; top: number; ch: number; headY: number};
};
export type StripTrack = {
	ticks: {t: string; x: number}[]; from: string; to: string; cap: string; a0: number; a1: number;
	layout: {x1: number; x2: number; y: number};
};
export type StripUnits = {
	n: number; icon: string; label: string; at: number;
	layout: {cols: number; rows: number; step: number; size: number; x0: number; y0: number; capY: number};
};
export type StripWaffle = {pct: number; label: string; at: number; layout: {x0: number; y0: number; cell: number; gap: number}};
export type StripChain = {nodes: {ne: string; at: number}[]; speaker: string; at: number};
export type StripVoiceprint = {name: string; role: string; parts: {t: string; hl?: boolean}[]; at: number};
export type StripEvidence = {parts: {t: string; hl?: boolean; at?: number}[]; at: number};
export type StripWho = {actor: string; verb: string; target: string; at: number};
export type StripCompare = {left: string; leftMeta?: string; right: string; rightMeta?: string; relation?: string; at: number};
export type StripRoster = {title?: string; members: {text: string; at: number}[]; focus?: number; at: number};
export type StripSchedule = {start: string; end?: string; place?: string; connector?: string; startAt: number; endAt?: number; at: number};
export type StripRule = {condition: string; consequence: string; otherwise?: string; at: number};
export type StripResult = {winner: string; loser?: string; outcome: string; context?: string; at: number};
export type StripMoney = {amount: string; context: string; direction?: 'in' | 'out' | 'loss' | 'only'; compare?: string; at: number};
export type StripContrast = {left: string; right: string; bridge?: string; at: number};
export type StripMovement = {from: string; to: string; actor: string; verb: string; at: number};
export type StripLawStage = {stages: {text: string; at: number; done?: boolean}[]; at: number};
export type StripVerdict = {subject: string; decision: string; authority?: string; at: number};
export type StripHook = {question: string; at: number};
export type StripQuote = {speaker: string; claim: string; at: number};
export type StripIncident = {headline: string; count?: string; state?: string; at: number};
export type StripAnim = {
	v: number;
	kind: 'stat' | 'concept' | 'place' | 'phrase' | 'calendar' | 'track' | 'units' | 'waffle' | 'chain' | 'voiceprint' | 'evidence' | 'who'
		| 'compare' | 'roster' | 'schedule' | 'rule' | 'result' | 'money' | 'contrast' | 'movement' | 'lawstage' | 'verdict' | 'hook' | 'quote' | 'incident';
	dark?: boolean;
	fit?: Record<string, number>;
	icons?: Record<string, string>;
	stat?: StripStat;
	concept?: {nodes: StripNode[]};
	place?: {places: StripPlace[]};
	phrase?: {words: StripWord[]; icon: string; at: number};
	calendar?: StripCalendar;
	track?: StripTrack;
	units?: StripUnits;
	waffle?: StripWaffle;
	chain?: StripChain;
	voiceprint?: StripVoiceprint;
	evidence?: StripEvidence;
	who?: StripWho;
	compare?: StripCompare;
	roster?: StripRoster;
	schedule?: StripSchedule;
	rule?: StripRule;
	result?: StripResult;
	money?: StripMoney;
	contrast?: StripContrast;
	movement?: StripMovement;
	lawstage?: StripLawStage;
	verdict?: StripVerdict;
	hook?: StripHook;
	quote?: StripQuote;
	incident?: StripIncident;
};
export type AnimatedStripProps = {anim: StripAnim; startFrame?: number; durationInFrames?: number};

// ---------- numbers
const DEV = '०१२३४५६७८९';
const toDev = (s: string) => s.replace(/[0-9]/g, (d) => DEV[Number(d)]);
const groupNe = (int: string) => {
	if (int.length <= 3) return int;
	const last = int.slice(-3);
	let rest = int.slice(0, -3);
	const parts: string[] = [];
	while (rest.length > 2) { parts.unshift(rest.slice(-2)); rest = rest.slice(0, -2); }
	if (rest) parts.unshift(rest);
	return parts.join(',') + ',' + last;
};
const fmtNum = (x: number, decimals: number, comma: boolean) => {
	const s = x.toFixed(decimals);
	const [i, d] = s.split('.');
	return toDev((comma ? groupNe(i) : i) + (d ? '.' + d : ''));
};

// ---------- timing context
type Ctx = {
	f: number; fps: number; dur: number; ink: string; paper: string; dark: boolean; fit: Record<string, number>; icons: Record<string, string>;
	T: (at: number) => number; p: (start: number, len: number) => number; pio: (start: number, len: number) => number;
	sp: (start: number, damping?: number) => number; loop: (start: number, period: number) => number;
};
const EZ = Easing.bezier(0.22, 1, 0.36, 1);
const EIO = Easing.bezier(0.65, 0, 0.35, 1);
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

const makeCtx = (f: number, fps: number, dur: number, anim: StripAnim): Ctx => {
	const dark = true; // v12: one theme (anim.dark kept in the schema, ignored)
	const ramp = (start: number, len: number, easing: (t: number) => number) =>
		interpolate(f, [start, start + Math.max(1, len)], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing});
	return {
		f, fps, dur, dark,
		ink: dark ? '#F3EDE3' : '#110F0F',
		paper: dark ? '#110F0F' : '#F3EDE3',
		fit: anim.fit || {},
		icons: anim.icons || {},
		T: (at) => Math.round(Math.min(Math.max(at || 0, 0), 0.72) * Math.max(1, dur - 18)),
		p: (start, len) => ramp(start, len, EZ),
		pio: (start, len) => ramp(start, len, EIO),
		sp: (start, damping = 13) => (f < start ? 0 : spring({frame: f - start, fps, config: {damping: Math.max(20, damping), stiffness: 140, mass: 0.9}})),
		loop: (start, period) => (f < start || f >= start + period ? -1 : (f - start) / period),
	};
};

const abs = (style: React.CSSProperties): React.CSSProperties => ({position: 'absolute', ...style});
const rise = (q: number, dist = 40): React.CSSProperties => ({opacity: clamp01(q * 1.4), transform: `translateY(${(1 - q) * dist}px)`});

const Icon = (c: Ctx, name: string, size: number, color: string, draw: number, sw = 1.6, key?: string) =>
	h('svg', {
		key, width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: sw,
		strokeLinecap: 'round', strokeLinejoin: 'round',
		style: {overflow: 'visible', strokeDasharray: draw >= 0.999 ? 'none' : 1, strokeDashoffset: 1 - draw},
		dangerouslySetInnerHTML: {__html: c.icons[name] || c.icons.star || ''},
	});

const Pin = (color: string, hole: string, size: number) =>
	h('svg', {width: size, height: size, viewBox: '0 0 24 24', style: {overflow: 'visible'}},
		h('path', {d: PIN_D, fill: color}), h('circle', {cx: 12, cy: 10, r: 3, fill: hole}));

// v12: no corner marks. The strip meets the card through the shared stage, a 2 px hairline and a 120 px top shade (Strip.tsx).

// ---------- STAT: count-up number (or % ring) + rule + label  (only when the top half does NOT already show it)
const Stat = (c: Ctx, st: StripStat) => {
	const s0 = c.T(st.at);
	const cnt = st.num == null ? 1 : c.p(s0, Math.round(c.fps * 1.2));
	const shown = cnt >= 1 || st.num == null ? st.numText : toDev(st.prefix) + fmtNum(st.num * cnt, st.decimals, st.comma);
	const numQ = c.p(s0, 16);
	const label = c.p(s0 + 12, 18);
	if (st.percent != null) {
		const cx = 300, cy = 325, r = 200, C = 2 * Math.PI * r;
		const arc = c.p(s0, Math.round(c.fps * 1.3)) * (st.percent / 100) * C;
		const pulse = c.loop(s0 + Math.round(c.fps * 1.3), 60);
		return [
			h('svg', {key: 'ring', width: W, height: H, fill: 'none', style: abs({left: 0, top: 0, opacity: clamp01(numQ * 2)})},
				h('circle', {cx, cy, r, stroke: c.ink, strokeOpacity: 0.08, strokeWidth: 30}),
				h('circle', {cx, cy, r, stroke: RED, strokeWidth: 30, strokeLinecap: 'round', strokeDasharray: `${arc} 9999`, transform: `rotate(-90 ${cx} ${cy})`}),
				pulse >= 0 ? h('circle', {cx, cy, r: r + 18 + pulse * 40, stroke: RED, strokeWidth: 3, strokeOpacity: 0.3 * (1 - pulse)}) : null),
			h('div', {key: 'num', style: abs({left: 130, top: 250, width: 340, textAlign: 'center', whiteSpace: 'nowrap', lineHeight: 1.1, color: ON_RED, textShadow: RED_TEXT, fontSize: c.fit.num || 128, ...rise(numQ, 30)})},
				shown, h('span', {style: {fontSize: '.55em'}}, st.unit.replace('प्रतिशत', '%'))),
			h('div', {key: 'rule', style: abs({left: 590, top: 250, width: 110, height: 10, borderRadius: 2, background: RED, transformOrigin: 'left', transform: `scaleX(${c.p(s0 + 8, 14)})`})}),
			h('div', {key: 'label', style: abs({left: 590, top: 282, width: 420, lineHeight: 1.2, fontSize: c.fit.label || 72, ...rise(label)})}, st.label),
		];
	}
	return [
		h('div', {key: 'num', style: abs({left: 80, top: 96, width: 920, textAlign: 'center', whiteSpace: 'nowrap', lineHeight: 1.1, color: ON_RED, textShadow: RED_TEXT, fontSize: c.fit.num || 240, ...rise(numQ, 60)})},
			// the final value reserves the width, the counting value sits on top right-aligned: no jitter
			h('span', {style: {position: 'relative', display: 'inline-block'}},
				h('span', {style: {visibility: 'hidden'}}, st.numText),
				h('span', {style: {position: 'absolute', right: 0, top: 0}}, shown)),
			st.unit ? h('span', {style: {fontSize: '.34em', color: c.ink, marginLeft: '.14em', opacity: c.p(s0 + 10, 14)}}, st.unit) : null),
		h('div', {key: 'rule', style: abs({left: 480, top: 410, width: 120, height: 10, borderRadius: 2, background: RED, transform: `scaleX(${c.p(s0 + 8, 16)})`})}),
		h('div', {key: 'label', style: abs({left: 90, top: 440, width: 900, textAlign: 'center', lineHeight: 1.25, fontSize: c.fit.label || 76, ...rise(label)})}, st.label),
	];
};

// ---------- CALENDAR: the week slides in, the day lifts out in red with the event icon (weekday if spoken)
const Calendar = (c: Ctx, cal: StripCalendar) => {
	const L = cal.layout, s = c.T(cal.at), out: React.ReactNode[] = [];
	const headQ = c.p(2, 18);
	out.push(h('div', {key: 'head', style: abs({left: 80, top: L.headY, width: 920, textAlign: 'center', lineHeight: 1.2, fontSize: c.fit.head || 64, ...rise(headQ, 24)})},
		cal.month, cal.weekday ? h('span', {style: {color: ON_RED, opacity: c.p(s + 6, 14)}}, ' ' + cal.weekday) : null));
	cal.days.forEach((dd, k) => {
		const x = L.x0 + k * (L.cw + L.gap), on = k === cal.hi;
		const inQ = c.p(4 + k * 3, 18);
		const lift = on ? c.sp(s, 11) : 0;
		const fillQ = on ? c.p(s, 12) : 0;
		const col = fillQ > 0.5 ? ON_RED : c.ink;
		const cell: React.ReactNode[] = [
			h('div', {key: 'bd', style: abs({left: 0, top: 0, width: L.cw, height: L.ch, ...glassBox(false, 22), opacity: 1 - fillQ})}),
			h('div', {key: 'fl', style: abs({left: 0, top: 0, width: L.cw, height: L.ch, ...glassBox(true, 22), transformOrigin: '50% 100%', transform: `scaleY(${fillQ})`})}),
		];
		if (cal.wds) cell.push(h('div', {key: 'wd', style: abs({left: 0, top: 22, width: L.cw, textAlign: 'center', lineHeight: 1.25, fontSize: 40, color: ON_RED, opacity: on && fillQ > 0.5 ? 1 : 0.55})}, cal.wds[k]));
		cell.push(h('div', {key: 'dn', style: abs({left: 0, top: cal.wds ? 78 : 60, width: L.cw, textAlign: 'center', lineHeight: 1.25, fontSize: 76, color: ON_RED, opacity: on && fillQ > 0.5 ? 1 : 0.5})}, dd));
		if (on) {
			cell.push(h('div', {key: 'ic', style: abs({left: L.cw / 2 - 32, top: L.ch - 92, width: 64, height: 64, opacity: clamp01(fillQ * 2)})}, Icon(c, cal.icon, 64, ON_RED, c.p(s + 8, 22), 1.8)));
			const q = c.loop(s + 16, 54);
			if (q >= 0) cell.push(h('div', {key: 'rp', style: abs({left: -q * 22, top: -q * 22, width: L.cw + q * 44, height: L.ch + q * 44, borderRadius: 22 + q * 14,
				border: `4px solid ${RED}`, boxSizing: 'border-box', opacity: 0.6 * (1 - q)})}));
		}
		out.push(h('div', {key: 'd' + k, style: abs({left: x, top: L.top, width: L.cw, height: L.ch, opacity: clamp01(inQ * 1.4),
			transform: `translateY(${(1 - inQ) * 50 - lift * 16}px) scale(${1 + 0.06 * lift})`})}, cell));
	});
	return out;
};

// ---------- TRACK: distance as the route itself. start -> finish, ticks, a runner travels while it is spoken
const Track = (c: Ctx, tr: StripTrack) => {
	const {x1, x2, y} = tr.layout, out: React.ReactNode[] = [];
	const s0 = c.T(tr.a0), s1 = Math.max(s0 + 20, c.T(tr.a1));
	const base = c.p(2, 20);
	const q = c.pio(s0, s1 - s0);
	const rx = x1 + (x2 - x1) * q;
	out.push(h('div', {key: 'capr', style: abs({left: 80, top: 96, width: 20, height: 20, borderRadius: 3, marginTop: -6, boxShadow: '0 0 24px rgba(215,20,30,.6)', background: RED, transformOrigin: 'left', transform: `scaleX(${c.p(0, 14)})`})}));
	out.push(h('div', {key: 'cap', style: abs({left: 156, top: 70, width: 700, lineHeight: 1.2, fontSize: c.fit.cap || 50, ...rise(c.p(4, 16), 20), opacity: 0.75 * c.p(4, 16)})}, tr.cap));
	out.push(h('div', {key: 'base', style: abs({left: x1, top: y - 7, width: x2 - x1, height: 14, borderRadius: 7, background: c.ink, opacity: 0.08, transformOrigin: 'left', transform: `scaleX(${base})`})}));
	out.push(h('div', {key: 'prog', style: abs({left: x1, top: y - 7, width: Math.max(14, rx - x1), height: 14, borderRadius: 7, background: FILL, boxShadow: '0 0 24px rgba(215,20,30,.45)', opacity: q > 0 ? 1 : 0})}));
	tr.ticks.forEach((tk, k) => {
		const tq = c.p(6 + k * 2, 14), passed = rx >= tk.x - 1 && q > 0;
		out.push(h('div', {key: 'tk' + k, style: abs({left: tk.x - 2, top: y + 18, width: 4, height: 22, background: passed ? RED : c.ink, opacity: (passed ? 1 : 0.5) * tq})}));
		if (tk.t) out.push(h('div', {key: 'tt' + k, style: abs({left: tk.x - 40, top: y + 44, width: 80, textAlign: 'center', lineHeight: 1.25, fontSize: 46,
			color: ON_RED, opacity: (passed ? 1 : 0.6) * tq})}, tk.t));
	});
	const st = c.sp(4);
	out.push(h('div', {key: 'start', style: abs({left: x1 - 20, top: y - 20, width: 40, height: 40, borderRadius: '50%', background: c.ink, boxSizing: 'border-box',
		border: `9px solid ${c.paper}`, transform: `scale(${st})`})}));
	if (tr.from) out.push(h('div', {key: 'from', style: abs({left: 80, top: y + 108, width: 440, lineHeight: 1.15, fontSize: c.fit.from || 68, ...rise(c.p(s0 - 4, 16), 30)})}, tr.from));
	// runner
	if (q > 0 && q < 1) {
		const pl = c.loop(s0, 24);
		out.push(h('div', {key: 'rr', style: abs({left: rx - 34 - pl * 14, top: y - 34 - pl * 14, width: 68 + pl * 28, height: 68 + pl * 28, borderRadius: '50%',
			border: `3px solid ${RED}`, boxSizing: 'border-box', opacity: 0.5 * (1 - pl)})}));
		out.push(h('div', {key: 'run', style: abs({left: rx - 22, top: y - 22, width: 44, height: 44, borderRadius: '50%', background: RED, boxSizing: 'border-box', border: `8px solid ${c.paper}`,
			boxShadow: '0 0 30px rgba(215,20,30,.7)'})}));
	}
	// finish pin drops as the runner arrives
	const drop = c.sp(s1 - 6, 10);
	if (drop > 0) {
		for (const off of [0, 22]) {
			const rq = c.loop(s1 + 6 + off, 46);
			if (rq < 0) continue;
			const rr = 30 + rq * 90;
			out.push(h('div', {key: 'fr' + off, style: abs({left: x2 - rr, top: y - rr * 0.32, width: rr * 2, height: rr * 0.64, borderRadius: '50%',
				border: `3px solid ${RED}`, boxSizing: 'border-box', opacity: 0.5 * (1 - rq)})}));
		}
		out.push(h('div', {key: 'fin', style: abs({left: x2 - 85, top: y - 150, width: 170, height: 170, opacity: clamp01(drop * 3), transform: `translateY(${(1 - drop) * -140}px)`})},
			Pin(RED, c.paper, 170)));
	}
	if (tr.to) out.push(h('div', {key: 'to', style: abs({left: 560, top: y + 108, width: 440, textAlign: 'right', color: ON_RED, lineHeight: 1.15, fontSize: c.fit.to || 68, ...rise(c.p(s1 - 2, 16), 30)})}, tr.to));
	return out;
};

// ---------- UNITS: a count the top half shows -> that many tokens drop in, in reading order
const Units = (c: Ctx, u: StripUnits) => {
	const L = u.layout, s = Math.max(2, c.T(u.at) - 4), out: React.ReactNode[] = [];
	const spread = Math.min(Math.round(c.fps * 1.4), u.n * 3);
	const lastN = u.n - (L.rows - 1) * L.cols;
	for (let k = 0; k < u.n; k++) {
		const r = Math.floor(k / L.cols), cc = k % L.cols;
		const off = r === L.rows - 1 ? ((L.cols - lastN) * L.step) / 2 : 0;
		const x = L.x0 + off + cc * L.step + (L.step - L.size) / 2, y = L.y0 + r * L.step + (L.step - L.size) / 2;
		const t0 = s + Math.round((spread * k) / Math.max(1, u.n - 1));
		const d = c.sp(t0, 10);
		// a soft wave runs across the set once they are all in, so it never sits dead still
		const wv = c.loop(s + spread + 20, 70);
		const bump = wv >= 0 ? Math.max(0, 1 - Math.abs(wv * (u.n + 6) - k - 3) / 3) : 0;
		const tok = u.icon === 'pin' ? Pin(RED, c.paper, L.size) : Icon(c, u.icon, L.size, RED, c.p(t0, 14), 1.7);
		out.push(h('div', {key: 'u' + k, style: abs({left: x, top: y, width: L.size, height: L.size, opacity: clamp01(d * 3),
			transform: `translateY(${(1 - d) * -60 - bump * 3}px) scale(${0.6 + 0.4 * d})`, transformOrigin: '50% 100%'})}, tok));
	}
	const lq = c.p(s + spread + 4, 18);
	out.push(h('div', {key: 'lab', style: abs({left: 90, top: L.capY, width: 900, textAlign: 'center', lineHeight: 1.25, fontSize: c.fit.label || 72, ...rise(lq, 30)})}, u.label));
	return out;
};

// ---------- WAFFLE: a share the top half shows -> 100 squares, that many turn red
const Waffle = (c: Ctx, wf: StripWaffle) => {
	const L = wf.layout, s = Math.max(4, c.T(wf.at)), out: React.ReactNode[] = [];
	const on = Math.round(wf.pct), spread = Math.round(c.fps * 1.3);
	for (let k = 0; k < 100; k++) {
		const r = Math.floor(k / 10), cc = k % 10;
		const gq = c.p(Math.round((r + cc) * 0.8), 12);
		const fq = k < on ? c.p(s + Math.round((spread * k) / Math.max(1, on)), 8) : 0;
		out.push(h('div', {key: 'w' + k, style: abs({left: L.x0 + cc * (L.cell + L.gap), top: L.y0 + (9 - r) * (L.cell + L.gap), width: L.cell, height: L.cell, borderRadius: 7,
			background: fq > 0 ? FILL : c.ink, boxShadow: fq > 0 ? '0 0 14px rgba(215,20,30,.45)' : undefined, opacity: fq > 0 ? 1 : 0.08 * gq, transform: `scale(${fq > 0 ? 0.6 + 0.4 * fq : 0.8 + 0.2 * gq})`})}));
	}
	out.push(h('div', {key: 'rule', style: abs({left: 590, top: 230, width: 110, height: 10, borderRadius: 2, background: RED, transformOrigin: 'left', transform: `scaleX(${c.p(s + 6, 14)})`})}));
	out.push(h('div', {key: 'lab', style: abs({left: 590, top: 262, width: 420, lineHeight: 1.2, fontSize: c.fit.label || 72, ...rise(c.p(s + 10, 18))})}, wf.label));
	return out;
};

// ---------- CONCEPT: steps arrive as they are spoken, arrows draw between them
const CONCEPT_D: Record<number, number> = {1: 260, 2: 240, 3: 220, 4: 164};
const Concept = (c: Ctx, nodes: StripNode[]) => {
	const n = Math.max(1, Math.min(4, nodes.length));
	const slot = 920 / n, d = CONCEPT_D[n], r = d / 2, cy = 262;
	const cxs = nodes.slice(0, n).map((_, k) => 80 + slot * k + slot / 2);
	const starts = nodes.slice(0, n).map((nd) => c.T(nd.at));
	let active = -1;
	starts.forEach((s, k) => { if (c.f >= s + 14) active = k; });
	const out: React.ReactNode[] = [];
	nodes.slice(0, n).forEach((nd, k) => {
		const cx = cxs[k], s = starts[k], last = k === n - 1;
		const pop = c.sp(s);
		const ring = c.p(s, 14);
		const fill = last ? c.p(s + 10, 10) : 0;
		const isz = d * 0.52;
		out.push(h('svg', {key: 'c' + k, width: d + 60, height: d + 60, fill: 'none',
			style: abs({left: cx - r - 30, top: cy - r - 30, opacity: clamp01(pop * 2), transform: `scale(${0.94 + 0.06 * pop})`,
				filter: last && fill > 0.5 ? 'drop-shadow(0 18px 40px rgba(215,20,30,.45))' : undefined})},
			RedDef('kmc' + k),
			h('circle', {cx: r + 30, cy: r + 30, r: r - 4, fill: `url(#kmc${k})`, fillOpacity: fill}),
			h('circle', {cx: r + 30, cy: r + 30, r: r - 4, fill: c.ink, fillOpacity: last ? 0 : 0.06}),
			h('circle', {cx: r + 30, cy: r + 30, r: r - 4, stroke: last ? RED : c.ink, strokeOpacity: last ? 1 : 0.35, strokeWidth: 6, pathLength: 1,
				strokeDasharray: ring >= 0.999 ? 'none' : 1, strokeDashoffset: 1 - ring, transform: `rotate(-90 ${r + 30} ${r + 30})`}),
			(() => { const q = c.loop(s + 14, 45); return active === k && q >= 0 ? h('circle', {cx: r + 30, cy: r + 30, r: (r - 4) * (1 + 0.18 * q), stroke: RED, strokeWidth: 4, strokeOpacity: 0.6 * (1 - q)}) : null; })()));
		out.push(h('div', {key: 'i' + k, style: abs({left: cx - isz / 2, top: cy - isz / 2, width: isz, height: isz, opacity: clamp01(pop * 2), transform: `scale(${0.94 + 0.06 * pop})`})},
			Icon(c, nd.icon, isz, last && fill > 0.5 ? ON_RED : last ? RED : c.ink, c.p(s + 4, 20))));
		out.push(h('div', {key: 't' + k, style: abs({left: cx - (slot - 24) / 2, top: cy + r + 30, width: slot - 24, textAlign: 'center', lineHeight: 1.25,
			fontSize: c.fit['n' + k] || 68, ...rise(c.p(s + 6, 16), 30)})}, nd.ne));
		if (!last) {
			const x1 = cx + r + 12, x2 = cxs[k + 1] - r - 12, L = x2 - x1;
			const a0 = Math.max(s + 8, starts[k + 1] - 12);
			const q = c.p(a0, Math.max(8, starts[k + 1] - a0));
			out.push(h('div', {key: 'l' + k, style: abs({left: x1, top: cy - 3, width: Math.max(0, L - 18), height: 6, borderRadius: 3, background: RED, transformOrigin: 'left', transform: `scaleX(${q})`})}));
			out.push(h('div', {key: 'a' + k, style: abs({left: x2 - 24, top: cy - 16, width: 0, height: 0, borderLeft: `24px solid ${RED}`,
				borderTop: '16px solid transparent', borderBottom: '16px solid transparent', opacity: clamp01((q - 0.75) * 4), transform: `translateX(${(1 - q) * -20}px)`})}));
		}
	});
	return out;
};

// ---------- PLACE: map-dot paper, pins drop, route draws from one place to the next
const bez = (x1: number, y1: number, cx: number, cy: number, x2: number, y2: number, t: number): [number, number] => {
	const a = (1 - t) ** 2, b = 2 * (1 - t) * t, cc = t * t;
	return [a * x1 + b * cx + cc * x2, a * y1 + b * cy + cc * y2];
};
const Place = (c: Ctx, places: StripPlace[]) => {
	const pls = places.slice(0, 2);
	const two = pls.length === 2;
	const cxs = two ? [290, 790] : [540];
	const szs = two ? pls.map((p) => (p.focus ? 170 : 124)) : [200];
	const tip = 300;
	const starts = pls.map((p) => c.T(p.at));
	const mask = 'radial-gradient(ellipse 62% 72% at 50% 48%, #000 30%, transparent 78%)';
	const out: React.ReactNode[] = [
		h('div', {key: 'dots', style: abs({left: 0, top: 0, width: W, height: H, opacity: 0.55 * c.p(0, 24),
			backgroundImage: `radial-gradient(circle, rgba(243,237,227,.22) 1.8px, transparent 2.2px)`,
			backgroundSize: '36px 36px', backgroundPosition: `18px ${8 - c.f * 0.15}px`, WebkitMaskImage: mask, maskImage: mask})}),
	];
	if (two) {
		const hy = szs.map((sz) => tip - sz * 0.875 + (sz * 10) / 24);
		const a0 = starts[0] + 10, a1 = Math.max(a0 + 12, starts[1]);
		const q = c.p(a0, a1 - a0);
		const dots: React.ReactNode[] = [];
		for (let j = 1; j < 36; j++) {
			if (j / 36 > q) break;
			const [x, y] = bez(cxs[0], hy[0], 540, 40, cxs[1], hy[1], j / 36);
			dots.push(h('circle', {key: j, cx: x, cy: y, r: 4, fill: c.ink, fillOpacity: 0.55}));
		}
		const [tx, ty] = bez(cxs[0], hy[0], 540, 40, cxs[1], hy[1], q);
		const travel = q > 0 ? 1 - c.p(starts[1] + 4, 8) : 0;
		out.push(h('svg', {key: 'route', width: W, height: H, style: abs({left: 0, top: 0})}, dots,
			h('circle', {cx: tx, cy: ty, r: 12, fill: RED, stroke: c.paper, strokeWidth: 4, opacity: travel})));
	}
	pls.forEach((p, k) => {
		const cx = cxs[k], sz = szs[k], s = starts[k];
		const drop = c.sp(s, 10);
		const shadowQ = clamp01(drop);
		if (p.focus) {
			for (const off of [0, 25]) {
				const q = c.loop(s + 12 + off, 50);
				if (q < 0) continue;
				const rx = 46 + q * 140;
				out.push(h('div', {key: `rip${k}${off}`, style: abs({left: cx - rx, top: tip - rx * 0.32, width: rx * 2, height: rx * 0.64, borderRadius: '50%',
					border: `4px solid ${RED}`, boxSizing: 'border-box', opacity: 0.6 * (1 - q)})}));
			}
		}
		out.push(h('div', {key: 'sh' + k, style: abs({left: cx - sz * 0.27, top: tip - 8, width: sz * 0.54, height: 20, borderRadius: '50%', background: p.focus ? RED : '#000',
			opacity: (p.focus ? 0.35 : 0.5) * shadowQ, transform: `scale(${0.4 + 0.6 * shadowQ})`})}));
		out.push(h('div', {key: 'pin' + k, style: abs({left: cx - sz / 2, top: tip - sz * 0.875, width: sz, height: sz,
			opacity: clamp01(drop * 3), transform: `translateY(${(1 - drop) * -180}px)`,
			filter: p.focus ? 'drop-shadow(0 16px 30px rgba(215,20,30,.5))' : 'drop-shadow(0 16px 30px rgba(0,0,0,.6))'})}, Pin(p.focus ? RED : c.ink, c.paper, sz)));
		if (!two) {
			out.push(h('div', {key: 'n' + k, style: abs({left: 90, top: tip + 22, width: 900, textAlign: 'center', lineHeight: 1.25, fontSize: c.fit.p0 || 128, ...rise(c.p(s + 8, 16), 50)})}, p.ne));
			if (p.sub) out.push(h('div', {key: 's' + k, style: abs({left: 90, top: tip + 190, width: 900, textAlign: 'center', lineHeight: 1.25, fontSize: c.fit.sub0 || 56, ...rise(c.p(s + 14, 16)), opacity: 0.72 * c.p(s + 14, 16)})}, p.sub));
		} else {
			out.push(h('div', {key: 'n' + k, style: abs({left: cx - 230, top: tip + 28, width: 460, textAlign: 'center', lineHeight: 1.25, color: ON_RED, textShadow: p.focus ? RED_TEXT : undefined,
				fontSize: c.fit['p' + k] || (p.focus ? 92 : 76), ...rise(c.p(s + 8, 16), 40)})}, p.ne));
			if (p.sub) out.push(h('div', {key: 's' + k, style: abs({left: cx - 230, top: tip + 160, width: 460, textAlign: 'center', lineHeight: 1.25, fontSize: c.fit['sub' + k] || 46, ...rise(c.p(s + 14, 16)), opacity: 0.72 * c.p(s + 14, 16)})}, p.sub));
		}
	});
	return out;
};

// ---------- PHRASE: solid red icon disc + the key phrase word by word, key word gets a red underline
const Phrase = (c: Ctx, ph: {words: StripWord[]; icon: string; at: number}) => {
	const s0 = Math.max(0, c.T(ph.at) - 6);
	const cx = 280, cy = 325, r = 190, isz = 200;
	const pop = c.sp(s0);
	const phraseQ = c.p(s0, 18);
	const words = ph.words.map((w, k) => h('span', {key:k, style:{display:'inline-block',color:ON_RED,
		borderBottom:w.key ? '3px solid rgba(215,20,30,.55)' : undefined}}, w.t));
	return [
		h('svg', {key: 'badge', width: 2 * r + 140, height: 2 * r + 140, fill: 'none',
			style: abs({left: cx - r - 70, top: cy - r - 70, opacity: clamp01(pop * 2), transform: `scale(${0.75 + 0.25 * pop})`, filter: 'drop-shadow(0 24px 60px rgba(215,20,30,.45))'})},
			RedDef('kmph'),
			h('circle', {cx: r + 70, cy: r + 70, r, fill: 'url(#kmph)'}),
			h('circle', {cx: r + 70, cy: r + 70, r: r - 1, stroke: 'rgba(243,237,227,.25)', strokeWidth: 2, strokeDasharray: `${Math.PI * r * 0.5} 9999`, transform: `rotate(200 ${r + 70} ${r + 70})`}),
			...[0, 0.45].map((o, i) => { const q = c.loop(s0 + 20 + Math.round(o * c.fps), 60); return q >= 0 ? h('circle', {key: 'rp' + i, cx: r + 70, cy: r + 70, r: r * (1 + 0.45 * (1 - Math.pow(1 - q, 5))), stroke: RED, strokeWidth: 4, strokeOpacity: 0.6 * (1 - q)}) : null; })),
		h('div', {key: 'icon', style: abs({left: cx - isz / 2, top: cy - isz / 2, width: isz, height: isz, transform: `scale(${0.85 + 0.15 * pop})`})},
			Icon(c, ph.icon, isz, ON_RED, c.p(s0 + 6, 26), 1.5)),
		h('div', {key: 'text', style: abs({left: 530, top: 70, width: 480, height: 510, display: 'flex', alignItems: 'center'})},
			h('div', {style: {width: 480, display: 'flex', flexWrap: 'wrap', columnGap: '.26em', fontSize: c.fit.ph || 100, lineHeight: 1.28, ...rise(phraseQ, 18)}}, words)),
	];
};


// ================= TEXT-ONLY STORY STRIPS (v4) =================
// Every word shown comes from the narration / article excerpt (script_to_story checks it is an exact piece).
// Devanagari width estimate: ~0.5em per character. Pick the biggest size that fits maxLines lines in maxW.
const fitSize = (text: string, maxW: number, maxLines: number, max: number, min: number) => {
	const n = Math.max(1, Array.from(text).length);
	for (let sz = max; sz >= min; sz -= 2) {
		const perLine = Math.floor(maxW / (sz * 0.56));
		if (Math.ceil(n / perLine) <= maxLines) return sz;
	}
	return min;
};

// Strip emphasis is static and calm. No read-along marker or brightness sweep.
const Hl = (c: Ctx, key: number, t: string, m: number) =>
  h('span', {key, style: {color: ON_RED}}, t);

const Chip = (c: Ctx, key: string, text: string, x: number, y: number, w: number, hgt: number, q: number, filled: boolean, maxLines = 2) => {
	const n = Math.max(1, Array.from(text).length);
	let sz = 38;
	for (let t = 80; t >= 38; t -= 2) {
		const lines = Math.ceil((n * t * 0.56) / (w - 56));
		if (lines <= maxLines && lines * t * 1.22 <= hgt - 36) { sz = t; break; }
	}
	return h('div', {key, style: abs({left: x, top: y, width: w, height: hgt, boxSizing: 'border-box', display: 'flex', alignItems: 'center', justifyContent: 'center',
		textAlign: 'center', padding: '0 28px', lineHeight: 1.22, fontSize: sz, ...glassBox(filled, 28),
		color: filled ? ON_RED : c.ink, textShadow: filled ? '0 1px 0 rgba(0,0,0,.25)' : undefined, ...rise(q, 36)})}, text);
};

// ---------- CHAIN: A -> B (-> C), arrows draw in as the words are spoken; speaker tag rides on the arrow
const Chain = (c: Ctx, ch: StripChain) => {
	const nodes = ch.nodes.slice(0, 3), n = nodes.length, out: React.ReactNode[] = [];
	const hgt = n === 3 ? 140 : 176, gap = n === 3 ? 50 : 96;
	const total = n * hgt + (n - 1) * gap, y0 = Math.round((H - total) / 2), w = 780, x = (W - w) / 2 - 60;
	nodes.forEach((nd, k) => {
		const s = c.T(nd.at), y = y0 + k * (hgt + gap), last = k === n - 1;
		out.push(Chip(c, 'c' + k, nd.ne, x, y, w, hgt, c.p(s, 16), last && n > 1));
		if (!last) {
			const ns = c.T(nodes[k + 1].at), q = c.p(Math.max(s + 8, ns - 22), 18), ay = y + hgt, ax = x + w / 2;
			out.push(h('svg', {key: 'a' + k, width: 60, height: gap, viewBox: `0 0 60 ${gap}`, fill: 'none', style: abs({left: ax - 30, top: ay, overflow: 'visible'})},
				h('path', {d: `M30 4V${gap - 6}`, stroke: RED, strokeWidth: 6, strokeLinecap: 'round', strokeDasharray: gap, strokeDashoffset: gap * (1 - q)}),
				h('path', {d: `M14 ${gap - 24}L30 ${gap - 4}L46 ${gap - 24}`, stroke: RED, strokeWidth: 6, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: q > 0.85 ? 1 : 0})));
			if (k === 0 && ch.speaker) {
				const tq = c.p(c.T(ch.at), 16);
				out.push(h('div', {key: 'sp', style: abs({left: ax + 56, top: ay + gap / 2 - 36, fontSize: fitSize(ch.speaker, 280, 1, 54, 36), lineHeight: 1.2, color: ON_RED, whiteSpace: 'nowrap',
					background: c.paper, padding: '4px 18px 0', boxShadow: 'inset 0 0 0 2px rgba(215,20,30,.85)', borderRadius: 18, ...rise(tq, 20)})}, ch.speaker));
			}
		}
	});
	return out;
};

// ---------- WHO -> WHAT -> WHOM: two name plates joined by a connector that carries the verb
const Who = (c: Ctx, wh: StripWho) => {
	const s0 = c.T(wh.at), out: React.ReactNode[] = [];
	const cw = 350, hgt = 340, y = 150, xl = 56, xr = W - 56 - cw;
	out.push(Chip(c, 'a', wh.actor, xl, y, cw, hgt, c.p(s0, 16), false, 3));
	const lq = c.p(s0 + 10, 20), mx0 = xl + cw + 14, mx1 = xr - 14, my = y + hgt / 2;
	out.push(h('svg', {key: 'ln', width: W, height: H, fill: 'none', style: abs({left: 0, top: 0, overflow: 'visible'})},
		h('path', {d: `M${mx0} ${my}H${mx1}`, stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeDasharray: mx1 - mx0, strokeDashoffset: (mx1 - mx0) * (1 - lq)}),
		h('path', {d: `M${mx1 - 26} ${my - 22}L${mx1} ${my}L${mx1 - 26} ${my + 22}`, stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: lq > 0.9 ? 1 : 0})));
	out.push(h('div', {key: 'vb', style: abs({left: mx0, top: my - 84, width: mx1 - mx0, textAlign: 'center', color: ON_RED, whiteSpace: 'nowrap', lineHeight: 1.2,
		fontSize: fitSize(wh.verb, mx1 - mx0, 1, 54, 30), ...rise(c.p(s0 + 14, 16), 24)})}, wh.verb));
	out.push(Chip(c, 'b', wh.target, xr, y, cw, hgt, c.p(s0 + 22, 16), true, 3));
	// slow pulse ring on the target once everything has landed
	const pl = c.loop(s0 + 50, 70);
	if (pl >= 0) out.push(h('div', {key: 'pl', style: abs({left: xr - 14 - pl * 18, top: y - 14 - pl * 18, width: cw + 28 + pl * 36, height: hgt + 28 + pl * 36, boxSizing: 'border-box',
		border: `4px solid ${RED}`, borderRadius: 34, opacity: 0.6 * (1 - pl)})}));
	// quiet line under the pair so the lower half is not empty
	out.push(h('div', {key: 'rl', style: abs({left: 56, top: 548, width: W - 112, height: 2, background: c.ink, opacity: 0.14, transformOrigin: 'left', transform: `scaleX(${c.p(s0 + 18, 30)})`})}));
	return out;
};

// ---------- EVIDENCE: the exact sentence on a paper panel, key words swept with a marker as they are spoken
const Evidence = (c: Ctx, ev: StripEvidence) => {
	const full = ev.parts.map((p) => p.t).join('');
	const sz = fitSize(full, 780, 6, 70, 44);
	const q = c.p(c.T(ev.at), 18);
	const hl = ev.parts.map((p, k) => p.hl ? Hl(c, k, p.t, c.p(c.T(p.at ?? ev.at + 0.1), 16)) : h('span', {key: k}, p.t));
	return [
		h('div', {key: 'panel', style: abs({left: 70, top: 70, width: W - 140, height: H - 140, boxSizing: 'border-box', ...glassBox(false, 32), ...rise(q, 40)})}),
		h('div', {key: 'qm', style: abs({left: 104, top: 92, fontSize: 100, lineHeight: 1, color: ON_RED, textShadow: RED_TEXT, opacity: q})}, '\u201C'),
		h('div', {key: 'tx', style: abs({left: 120, top: 150, width: W - 240, height: H - 300, display: 'flex', alignItems: 'center', fontSize: sz, lineHeight: 1.36, opacity: clamp01(q * 1.6)})},
			h('div', {style: {width: '100%'}}, hl)),
	];
};

// ---------- VOICEPRINT: speaker plate + live sound bars + the key clause swept with a marker
const Voiceprint = (c: Ctx, vp: StripVoiceprint) => {
	const s0 = c.T(vp.at), out: React.ReactNode[] = [];
	const pq = c.p(2, 18);
	out.push(h('div', {key: 'plate', style: abs({left: 70, top: 46, width: W - 140, height: 130, boxSizing: 'border-box', display: 'flex', alignItems: 'center', gap: 28, padding: '0 34px',
		...glassBox(true, 36), color: ON_RED, ...rise(pq, 30)})},
		h('svg', {width: 60, height: 60, viewBox: '0 0 24 24', fill: ON_RED}, h('path', {d: 'M12 12a5 5 0 100-10 5 5 0 000 10zm0 2c-4.4 0-8 2.2-8 5v2h16v-2c0-2.8-3.6-5-8-5z'})),
		h('div', {style: {display: 'flex', flexDirection: 'column', lineHeight: 1.18}},
			h('div', {style: {fontSize: fitSize(vp.name, 760, 1, 64, 40)}}, vp.name),
			vp.role ? h('div', {style: {fontSize: fitSize(vp.role, 760, 1, 40, 30), opacity: 0.85}}, vp.role) : null)));
	const full = vp.parts.map((p) => p.t).join('');
	const sz = fitSize(full, 880, 3, 76, 46);
	const hl = vp.parts.map((p, k) => p.hl ? Hl(c, k, p.t, c.p(s0, 18)) : h('span', {key: k}, p.t));
	out.push(h('div', {key: 'q', style: abs({left: 100, top: 205, width: W - 200, height: 250, display: 'flex', alignItems: 'center', fontSize: sz, lineHeight: 1.3, ...rise(c.p(8, 18), 30)})},
		h('div', {style: {width: '100%'}}, hl)));
	// sound bars: lively while the voice runs, settle at the very end
	const N = 33, bw = 14, gp = 14, x0 = Math.round((W - (N * bw + (N - 1) * gp)) / 2), base = 530;
	const live = clamp01((c.dur - c.f) / 10) * c.p(6, 10);
	const bars: React.ReactNode[] = [];
	for (let i = 0; i < N; i++) {
		const e = 0.5 + 0.5 * Math.sin(c.f * 0.33 + i * 0.9) * Math.cos(c.f * 0.17 + i * 0.37);
		const env = 0.25 + 0.75 * Math.abs(Math.sin(i * 0.43 + 1.3)) * (0.35 + 0.65 * Math.abs(Math.sin(c.f * 0.11 + i * 0.21)));
		const hh = 10 + live * (e * env * 86);
		bars.push(h('div', {key: i, style: abs({left: x0 + i * (bw + gp), top: base - hh / 2, width: bw, height: hh, background: i % 2 ? c.ink : RED, borderRadius: 7, opacity: i % 2 ? 0.5 : 0.95, boxShadow: i % 2 ? undefined : '0 0 14px rgba(215,20,30,.45)'})}));
	}
	out.push(...bars);
	return out;
};

const GapPlate = (c: Ctx, key: string, text: string, x: number, y: number, w: number, hgt: number, q: number, filled = false) =>
	Chip(c, key, text, x, y, w, hgt, q, filled, 3);

// ================= GAP STRIPS A-M (v5) =================
// 13 kinds for the lines the first 12 could not show. Same house style: springs,
// draw-in strokes, pulse accents, everything timed to the voice with "at".
// Every string is an exact span of the narration line; fixed labels only: vs, देखि, पछि, फरक.

// pulse ring that fades out once, house style
const Ring = (c: Ctx, key: string, x: number, y: number, w: number, hgt: number, start: number, period: number, radius: number) => {
	const q = c.loop(start, period);
	if (q < 0) return null;
	return h('div', {key, style: abs({left: x - 12 - q * 20, top: y - 12 - q * 20, width: w + 24 + q * 40, height: hgt + 24 + q * 40, boxSizing: 'border-box',
		border: `4px solid ${RED}`, borderRadius: radius + 18 + q * 12, opacity: 0.6 * (1 - q)})});
};

// spring-pop wrapper: children scale 0.7 -> 1 with the spring
const pop = (q: number): React.CSSProperties => ({opacity: clamp01(q * 1.6), transform: `scale(${0.94 + 0.06 * q})`});

// ---------- COMPARE (A): two number plates, vs badge pops, red side pulses
const Compare = (c: Ctx, x: StripCompare) => {
	const s = c.T(x.at), lq = c.p(s, 16), rq = c.p(s + 12, 16), bq = c.sp(s + 20), cw = 410, y = 190;
	const out: React.ReactNode[] = [
		GapPlate(c, 'l', x.left, 56, y, cw, 250, lq),
		GapPlate(c, 'r', x.right, W - 56 - cw, y, cw, 250, rq, true),
		Ring(c, 'rp', W - 56 - cw, y, cw, 250, s + 40, 60, 10),
	];
	if (x.leftMeta) out.push(h('div', {key: 'lm', style: abs({left: 70, top: y - 62, width: cw - 28, textAlign: 'center', fontSize: fitSize(x.leftMeta, cw - 40, 1, 52, 30), color: ON_RED, ...rise(lq, 20)})}, x.leftMeta));
	if (x.rightMeta) out.push(h('div', {key: 'rm', style: abs({left: W - 56 - cw + 14, top: y - 62, width: cw - 28, textAlign: 'center', fontSize: fitSize(x.rightMeta, cw - 40, 1, 52, 30), color: ON_RED, ...rise(rq, 20)})}, x.rightMeta));
	out.push(h('div', {key: 'vs', style: abs({left: W / 2 - 58, top: y + 93, width: 116, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
		background: FILL, color: ON_RED, borderRadius: 32, fontSize: 34, boxShadow: GLOW, ...pop(bq)})}, x.relation || 'vs'));
	out.push(h('div', {key: 'rl', style: abs({left: 56, top: 520, width: W - 112, height: 2, background: c.ink, opacity: 0.14, transformOrigin: 'left', transform: `scaleX(${c.p(s + 26, 26)})`})}));
	return out;
};

// ---------- ROSTER (B): name plates land one by one as spoken; focus member pulses
const Roster = (c: Ctx, x: StripRoster) => {
	const a = x.members.slice(0, 10), cols = a.length > 5 ? 2 : 1, rows = Math.ceil(a.length / cols), gap = 22, cw = cols === 2 ? 452 : 760, x0 = (W - (cols * cw + (cols - 1) * gap)) / 2;
	const out: React.ReactNode[] = [];
	if (x.title) out.push(h('div', {key: 'title', style: abs({left: 70, top: 44, width: 940, textAlign: 'center', fontSize: 54, color: ON_RED, textShadow: RED_TEXT, ...rise(c.p(c.T(x.at), 16), 24)})}, x.title));
	a.forEach((m, i) => {
		const col = Math.floor(i / rows), row = i % rows, px = x0 + col * (cw + gap), py = 126 + row * 106;
		out.push(GapPlate(c, 'm' + i, m.text, px, py, cw, 84, c.p(c.T(m.at), 14), i === x.focus));
		if (i === x.focus) out.push(Ring(c, 'fr' + i, px, py, cw, 84, c.T(m.at) + 24, 56, 10));
	});
	return out;
};

// ---------- SCHEDULE (C): span line draws, a dot travels start -> end, dates pop
const Schedule = (c: Ctx, x: StripSchedule) => {
	const s = c.T(x.at), aq = c.sp(c.T(x.startAt)), bq = c.sp(c.T(x.endAt ?? x.startAt + 0.15)), x1 = 150, x2 = 930, y = 300;
	const t0 = c.T(x.startAt), t1 = Math.max(t0 + 18, c.T(x.endAt ?? x.startAt + 0.15));
	const q = c.pio(t0, t1 - t0), rx = x1 + (x2 - x1) * q;
	const out: React.ReactNode[] = [
		h('div', {key: 'base', style: abs({left: x1, top: y - 5, width: x2 - x1, height: 10, borderRadius: 5, background: c.ink, opacity: 0.08, transformOrigin: 'left', transform: `scaleX(${c.p(2, 18)})`})}),
		h('div', {key: 'prog', style: abs({left: x1, top: y - 5, width: Math.max(10, rx - x1), height: 10, borderRadius: 5, background: FILL, boxShadow: '0 0 24px rgba(215,20,30,.45)', opacity: q > 0 ? 1 : 0})}),
		h('div', {key: 'd0', style: abs({left: x1 - 14, top: y - 14, width: 28, height: 28, borderRadius: '50%', background: c.ink, boxSizing: 'border-box', border: `7px solid ${c.paper}`, transform: `scale(${aq})`})}),
		h('div', {key: 'start', style: abs({left: x1 - 170, top: y - 108, width: 340, textAlign: 'center', whiteSpace: 'nowrap', fontSize: fitSize(x.start, 340, 1, 54, 30), color: ON_RED, ...pop(aq)})}, x.start),
	];
	if (q > 0 && q < 1) out.push(h('div', {key: 'run', style: abs({left: rx - 18, top: y - 18, width: 36, height: 36, borderRadius: '50%', background: RED, boxSizing: 'border-box', border: `7px solid ${c.paper}`, boxShadow: '0 4px 14px rgba(0,0,0,.18)'})}));
	if (x.end) {
		out.push(h('div', {key: 'd1', style: abs({left: x2 - 16, top: y - 16, width: 32, height: 32, borderRadius: '50%', background: RED, boxSizing: 'border-box', border: `7px solid ${c.paper}`, transform: `scale(${bq})`})}));
		out.push(h('div', {key: 'end', style: abs({left: x2 - 170, top: y - 108, width: 340, textAlign: 'center', whiteSpace: 'nowrap', fontSize: fitSize(x.end, 340, 1, 54, 30), color: ON_RED, ...pop(bq)})}, x.end));
	}
	if (x.connector) out.push(h('div', {key: 'label', style: abs({left: x1, top: y + 44, width: x2 - x1, textAlign: 'center', fontSize: 62, ...rise(c.p(s, 18), 22)})}, x.connector));
	if (x.place) out.push(h('div', {key: 'place', style: abs({left: 120, top: y + 120, width: 840, textAlign: 'center', fontSize: fitSize(x.place, 840, 1, 62, 36), ...rise(c.p(s + 10, 18), 22)})}, x.place));
	return out;
};

// ---------- RULE (D): condition plate, arrow draws down, consequence slams filled
const Rule = (c: Ctx, x: StripRule) => {
	const s = c.T(x.at), aq = c.p(s + 10, 16), cq = c.sp(s + 22, 12);
	const out: React.ReactNode[] = [
		GapPlate(c, 'condition', x.condition, 70, 105, 940, 145, c.p(s, 16)),
		h('svg', {key: 'ar', width: 60, height: 90, viewBox: '0 0 60 90', fill: 'none', style: abs({left: 510, top: 262, overflow: 'visible'})},
			h('path', {d: 'M30 4V74', stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeDasharray: 80, strokeDashoffset: 80 * (1 - aq)}),
			h('path', {d: 'M12 56L30 78L48 56', stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: aq > 0.85 ? 1 : 0})),
		h('div', {key: 'cons', style: abs({left: 70, top: 360, width: 940, height: 150, transform: `scale(${0.92 + 0.08 * cq})`, opacity: clamp01(c.p(s + 22, 14) * 1.6)})},
			Chip(c, 'cc', x.consequence, 0, 0, 940, 150, 1, true, 3)),
	];
	if (x.otherwise) out.push(h('div', {key: 'ow', style: abs({left: 70, top: 552, width: 940, textAlign: 'center', fontSize: 44, color: ON_RED, ...rise(c.p(s + 34, 14), 18)})}, x.otherwise));
	return out;
};
// ---------- RESULT (E): winner pops big, loser struck through, outcome rises
const Result = (c: Ctx, x: StripResult) => {
	const s = c.T(x.at), wq = c.sp(s, 11), out: React.ReactNode[] = [];
	out.push(h('div', {key: 'winner', style: abs({left: 90, top: 118, width: 900, textAlign: 'center', fontSize: fitSize(x.winner, 900, 1, 108, 58), color: ON_RED, textShadow: RED_TEXT, ...pop(wq)})}, x.winner));
	out.push(h('div', {key: 'rule', style: abs({left: 480, top: 258, width: 120, height: 10, borderRadius: 2, background: RED, transformOrigin: 'left', transform: `scaleX(${c.p(s + 8, 14)})`})}));
	out.push(h('div', {key: 'outcome', style: abs({left: 90, top: 292, width: 900, textAlign: 'center', fontSize: 56, ...rise(c.p(s + 12, 16), 24)})}, x.outcome));
	if (x.loser) {
		const lq = c.p(s + 24, 16), sq = c.p(s + 32, 12);
		out.push(h('div', {key: 'loser', style: abs({left: 90, top: 400, width: 900, textAlign: 'center', fontSize: 64, opacity: 0.72, position: 'absolute', ...rise(lq, 26)})},
			h('span', {style: {position: 'relative', display: 'inline-block'}},
				x.loser,
				h('span', {style: {position: 'absolute', left: '-3%', top: '54%', width: '106%', height: 6, borderRadius: 3, background: 'rgba(243,237,227,.75)', transformOrigin: 'left', transform: `scaleX(${sq})`}}))));
	}
	if (x.context) out.push(h('div', {key: 'context', style: abs({left: 120, top: 540, width: 840, textAlign: 'center', fontSize: 42, color: ON_RED, ...rise(c.p(s + 36, 14), 18)})}, x.context));
	return out;
};

// ---------- MONEY (F): amount pops big and red with a flow arrow, context plate under
const Money = (c: Ctx, x: StripMoney) => {
	const s = c.T(x.at), aq = c.sp(s, 11), dir = x.direction === 'in' ? '↑' : (x.direction === 'out' || x.direction === 'loss') ? '↓' : '';
	const out: React.ReactNode[] = [
		h('div', {key: 'amount', style: abs({left: 70, top: 92, width: 940, textAlign: 'center', fontSize: fitSize(x.amount, 900, 1, 122, 62), color: ON_RED, textShadow: RED_TEXT, ...pop(aq)})},
			x.amount, dir ? h('span', {style: {fontSize: '.5em', marginLeft: '.18em', opacity: c.p(s + 10, 12)}}, dir) : null),
		GapPlate(c, 'context', x.context, 120, 305, 840, 150, c.p(s + 14, 16)),
		Ring(c, 'rg', 120, 305, 840, 150, s + 34, 64, 10),
	];
	if (x.compare) out.push(h('div', {key: 'cmp', style: abs({left: 120, top: 505, width: 840, textAlign: 'center', fontSize: 48, color: ON_RED, ...rise(c.p(s + 26, 16), 20)})}, x.compare));
	return out;
};

// ---------- CONTRAST (G): two plates, फरक badge slams between them
const Contrast = (c: Ctx, x: StripContrast) => {
	const s = c.T(x.at), bq = c.sp(s + 14, 11);
	return [
		GapPlate(c, 'left', x.left, 60, 200, 410, 220, c.p(s, 16)),
		h('div', {key: 'br', style: abs({left: 475, top: 278, width: 130, height: 64, display: 'flex', alignItems: 'center', justifyContent: 'center',
			background: FILL, color: ON_RED, borderRadius: 32, fontSize: 40, boxShadow: GLOW, ...pop(bq)})}, x.bridge || 'फरक'),
		GapPlate(c, 'right', x.right, 610, 200, 410, 220, c.p(s + 18, 16), true),
		h('div', {key: 'rl', style: abs({left: 56, top: 510, width: W - 112, height: 2, background: c.ink, opacity: 0.14, transformOrigin: 'left', transform: `scaleX(${c.p(s + 28, 24)})`})}),
	];
};

// ---------- MOVEMENT (H): from plate, arrow draws, to plate fills and pulses, actor under
const Movement = (c: Ctx, x: StripMovement) => {
	const s = c.T(x.at), aq = c.p(s + 12, 18), out: React.ReactNode[] = [
		GapPlate(c, 'from', x.from, 70, 175, 360, 190, c.p(s, 16)),
		h('svg', {key: 'ar', width: 230, height: 60, viewBox: '0 0 230 60', fill: 'none', style: abs({left: 425, top: 240, overflow: 'visible'})},
			h('path', {d: 'M6 30H200', stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeDasharray: 200, strokeDashoffset: 200 * (1 - aq)}),
			h('path', {d: 'M182 12L206 30L182 48', stroke: RED, strokeWidth: 7, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: aq > 0.85 ? 1 : 0})),
		h('div', {key: 'verb', style: abs({left: 430, top: 168, width: 220, textAlign: 'center', color: ON_RED, whiteSpace: 'nowrap', fontSize: fitSize(x.verb, 240, 1, 46, 28), ...rise(c.p(s + 8, 14), 18)})}, x.verb),
		GapPlate(c, 'to', x.to, 650, 175, 360, 190, c.p(s + 22, 16), true),
		Ring(c, 'rp', 650, 175, 360, 190, s + 40, 58, 10),
		h('div', {key: 'actor', style: abs({left: 90, top: 410, width: 900, textAlign: 'center', fontSize: fitSize(x.actor, 900, 1, 62, 36), ...rise(c.p(s + 30, 16), 24)})}, x.actor),
	];
	return out;
};

// ---------- LAW STAGES (I): journey plates, done filled, current pulses, arrows draw
const LawStage = (c: Ctx, x: StripLawStage) => {
	const a = x.stages.slice(0, 4), cw = 216, gap = 40, x0 = (W - (a.length * cw + (a.length - 1) * gap)) / 2, out: React.ReactNode[] = [];
	let current = -1;
	a.forEach((s, i) => { if (s.done) current = i; });
	a.forEach((s, i) => {
		const px = x0 + i * (cw + gap), py = 235, q = c.p(c.T(s.at), 16), upcoming = !s.done && i > current;
		out.push(h('div', {key: 'st' + i, style: abs({left: px, top: py, opacity: upcoming ? 0.55 * q : 1})}, Chip(c, 'sc' + i, s.text, 0, 0, cw, 150, q, !!s.done, 3)));
		if (i === current) out.push(Ring(c, 'cr' + i, px, py, cw, 150, c.T(s.at) + 22, 56, 10));
		if (i < a.length - 1) {
			const aq = c.p(c.T(a[i + 1].at) - 6, 14);
			out.push(h('svg', {key: 'ar' + i, width: gap, height: 40, viewBox: `0 0 ${gap} 40`, fill: 'none', style: abs({left: px + cw + 2, top: py + 55, overflow: 'visible'})},
				h('path', {d: `M3 20H${gap - 8}`, stroke: RED, strokeWidth: 6, strokeLinecap: 'round', strokeDasharray: gap, strokeDashoffset: gap * (1 - aq)}),
				h('path', {d: `M${gap - 20} 8L${gap - 6} 20L${gap - 20} 32`, stroke: RED, strokeWidth: 6, strokeLinecap: 'round', strokeLinejoin: 'round', opacity: aq > 0.85 ? 1 : 0})));
		}
	});
	return out;
};

// ---------- VERDICT (J): the decision stamps down with a ring burst
const Verdict = (c: Ctx, x: StripVerdict) => {
	const s = c.T(x.at), sq = c.sp(s, 9), burst = c.loop(s + 10, 46);
	const out: React.ReactNode[] = [
		h('div', {key: 'dec', style: abs({left: 80, top: 96, width: 920, textAlign: 'center', fontSize: fitSize(x.decision, 900, 1, 112, 60), color: ON_RED,
			transform: `scale(${1.5 - 0.5 * sq}) rotate(${-4 * (1 - sq)}deg)`, opacity: clamp01(sq * 2), textShadow: sq > 0.95 ? RED_TEXT : '0 10px 40px rgba(215,20,30,.55)'})}, x.decision),
	];
	if (burst >= 0 && burst < 1) out.push(h('div', {key: 'bu', style: abs({left: 340 - burst * 60, top: 120 - burst * 30, width: 400 + burst * 120, height: 140 + burst * 60, boxSizing: 'border-box',
		border: `4px solid ${RED}`, borderRadius: 36, opacity: 0.6 * (1 - burst)})}));
	out.push(GapPlate(c, 'subject', x.subject, 120, 305, 840, 145, c.p(s + 16, 16), true));
	if (x.authority) out.push(h('div', {key: 'auth', style: abs({left: 120, top: 515, width: 840, textAlign: 'center', fontSize: 44, ...rise(c.p(s + 30, 14), 18)})}, x.authority));
	return out;
};
// ---------- HOOK (K): big red ? badge pops with ripple, the question rises under
const Hook = (c: Ctx, x: StripHook) => {
	const s = c.T(x.at), bq = c.sp(s, 10), rip = c.loop(s + 12, 56);
	const out: React.ReactNode[] = [];
	if (rip >= 0) out.push(h('div', {key: 'rip', style: abs({left: 508 - rip * 26, top: 66 - rip * 26, width: 64 + rip * 52, height: 64 + rip * 52, borderRadius: '50%',
		border: `4px solid ${RED}`, boxSizing: 'border-box', opacity: 0.6 * (1 - rip)})}));
	out.push(h('div', {key: 'badge', style: abs({left: 490, top: 48, width: 100, height: 100, borderRadius: '50%', background: FILL, color: ON_RED, display: 'flex',
		alignItems: 'center', justifyContent: 'center', fontSize: 66, boxShadow: GLOW, ...pop(bq)})}, '?'));
	out.push(h('div', {key: 'q', style: abs({left: 70, top: 190, width: 940, textAlign: 'center', fontSize: fitSize(x.question, 900, 4, 78, 44), lineHeight: 1.32, ...rise(c.p(s + 8, 18), 30)})}, x.question));
	out.push(h('div', {key: 'ul', style: abs({left: 480, top: 560, width: 120, height: 10, borderRadius: 2, background: RED, transformOrigin: 'left', transform: `scaleX(${c.p(s + 24, 18)})`})}));
	return out;
};

// ---------- QUOTE (L): speaker tag, then the claim on a panel like evidence
const Quote = (c: Ctx, x: StripQuote) => {
	const s = c.T(x.at), pq = c.p(s, 14), q = c.p(s + 8, 18);
	return [
		h('div', {key: 'tag', style: abs({left: 90, top: 62, maxWidth: 900, padding: '10px 28px 6px', ...glassBox(true, 40), color: ON_RED,
			fontSize: fitSize(x.speaker, 820, 1, 56, 34), lineHeight: 1.2, ...rise(pq, 22)})}, x.speaker),
		h('div', {key: 'panel', style: abs({left: 70, top: 150, width: W - 140, height: H - 220, boxSizing: 'border-box', ...glassBox(false, 32), ...rise(q, 36)})}),
		h('div', {key: 'qm', style: abs({left: W - 160, top: 172, fontSize: 100, lineHeight: 1, color: ON_RED, textShadow: RED_TEXT, opacity: q})}, '“'),
		h('div', {key: 'tx', style: abs({left: 130, top: 230, width: W - 260, height: H - 380, display: 'flex', alignItems: 'center', fontSize: fitSize(x.claim, W - 260, 4, 72, 42), lineHeight: 1.34, opacity: clamp01(q * 1.6)})},
			h('div', {style: {width: '100%'}}, x.claim)),
	];
};

// ---------- INCIDENT (M): count pops, headline, live state with a pulsing dot
const Incident = (c: Ctx, x: StripIncident) => {
	const s = c.T(x.at), has = !!x.count, cq = c.sp(s, 11), live = c.loop(s + 26, 40);
	const numberOnly = /^[०-९0-9,.]+$/.test(x.count || '');
	const out: React.ReactNode[] = [];
	if (has) {
		out.push(h('div', {key: 'count', style: abs({left: 80, top: 120, width: 330, textAlign: 'center', whiteSpace: 'nowrap', fontSize: fitSize(x.count || '', 330, 1, 140, 32), color: ON_RED, textShadow: RED_TEXT, ...pop(cq)})}, x.count));
		if (numberOnly) out.push(h('div', {key: 'cl', style: abs({left: 90, top: 300, width: 310, textAlign: 'center', fontSize: 40, opacity: 0.7, ...rise(c.p(s + 8, 14), 18)})}, 'जना'));
	}
	out.push(h('div', {key: 'headline', style: abs({left: has ? 450 : 80, top: 150, width: has ? 550 : 920, fontSize: fitSize(x.headline, has ? 550 : 920, 3, 78, 42), lineHeight: 1.26, ...rise(c.p(s + 10, 18), 28)})}, x.headline));
	out.push(h('div', {key: 'dot', style: abs({left: 320, top: 476, width: 26, height: 26, borderRadius: '50%', background: RED, boxShadow: '0 0 20px rgba(215,20,30,.7)', opacity: live >= 0 ? 0.45 + 0.55 * Math.abs(Math.sin(live * Math.PI)) : 1})}));
	if (x.state) out.push(h('div', {key: 'state', style: abs({left: 366, top: 460, width: 620, fontSize: fitSize(x.state, 620, 1, 52, 32), color: ON_RED, ...rise(c.p(s + 24, 16), 20)})}, x.state));
	return out;
};

export const AnimatedStrip: React.FC<AnimatedStripProps> = ({anim, startFrame = 0, durationInFrames}) => {
	const frame = useCurrentFrame();
	const cfg = useVideoConfig();
	const dur = Math.max(30, durationInFrames ?? cfg.durationInFrames);
	const f = frame - startFrame;
	const c = makeCtx(f, cfg.fps, dur, anim);
	let body: React.ReactNode = null;
	if (anim.kind === 'stat' && anim.stat) body = Stat(c, anim.stat);
	else if (anim.kind === 'concept' && anim.concept) body = Concept(c, anim.concept.nodes);
	else if (anim.kind === 'place' && anim.place) body = Place(c, anim.place.places);
	else if (anim.kind === 'phrase' && anim.phrase) body = Phrase(c, anim.phrase);
	else if (anim.kind === 'calendar' && anim.calendar) body = Calendar(c, anim.calendar);
	else if (anim.kind === 'track' && anim.track) body = Track(c, anim.track);
	else if (anim.kind === 'units' && anim.units) body = Units(c, anim.units);
	else if (anim.kind === 'waffle' && anim.waffle) body = Waffle(c, anim.waffle);
	else if (anim.kind === 'chain' && anim.chain) body = Chain(c, anim.chain);
	else if (anim.kind === 'who' && anim.who) body = Who(c, anim.who);
	else if (anim.kind === 'evidence' && anim.evidence) body = Evidence(c, anim.evidence);
	else if (anim.kind === 'voiceprint' && anim.voiceprint) body = Voiceprint(c, anim.voiceprint);
	else if (anim.kind === 'compare' && anim.compare) body = Compare(c, anim.compare);
	else if (anim.kind === 'roster' && anim.roster) body = Roster(c, anim.roster);
	else if (anim.kind === 'schedule' && anim.schedule) body = Schedule(c, anim.schedule);
	else if (anim.kind === 'rule' && anim.rule) body = Rule(c, anim.rule);
	else if (anim.kind === 'result' && anim.result) body = Result(c, anim.result);
	else if (anim.kind === 'money' && anim.money) body = Money(c, anim.money);
	else if (anim.kind === 'contrast' && anim.contrast) body = Contrast(c, anim.contrast);
	else if (anim.kind === 'movement' && anim.movement) body = Movement(c, anim.movement);
	else if (anim.kind === 'lawstage' && anim.lawstage) body = LawStage(c, anim.lawstage);
	else if (anim.kind === 'verdict' && anim.verdict) body = Verdict(c, anim.verdict);
	else if (anim.kind === 'hook' && anim.hook) body = Hook(c, anim.hook);
	else if (anim.kind === 'quote' && anim.quote) body = Quote(c, anim.quote);
	else if (anim.kind === 'incident' && anim.incident) body = Incident(c, anim.incident);
	// slow push-in over the whole card so the strip never sits dead still
	const drift = 1; // No second camera push: the room already moves. One accent per event, never an endless pulse.
	return h('div', {style: {position: 'relative', width: W, height: H, overflow: 'hidden', fontFamily: `${FONT}, Mukta, sans-serif`, color: c.ink}},
		h('div', {style: abs({left: 0, top: 0, width: W, height: H, transform: `scale(${drift})`, transformOrigin: '50% 50%'})}, body));
};

export default AnimatedStrip;

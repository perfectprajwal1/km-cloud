import {MS, H, f} from './motion';
import {PlanItem, Props} from './types';
// Card length = lead + voice + tail + exit (last card: + hold instead of exit).
export const buildPlan = ({story, timing}: Props): PlanItem[] => {
  let from = 0;
  return story.cards.map((card, idx) => {
    const t = timing?.cards?.[idx];
    const est = Math.max(MS.minCard, (card.vo || '').split(/\s+/).filter(Boolean).length * MS.msPerWordEstimate);
    const voMs = t?.ms ?? est;
    const last = idx === story.cards.length - 1;
    const durMs = card.type === 'engage' ? Math.max(MS.minCard, voMs + 1000)
      : Math.max(MS.minCard, MS.lead + voMs + MS.tail + (last ? MS.lastHold : MS.exit));
    const it: PlanItem = {idx, card, from, frames: f(durMs), durMs, voMs, words: t?.words ?? [], voice: t?.file,
      last, carry: !!card.carry};
    from += it.frames; return it;
  });
};
export const totalFrames = (p: Props) => buildPlan(p).reduce((a, b) => a + b.frames, 0);
// When does an event happen (ms from card start)? Tied to the voice where possible.
export const cueMs = (it: PlanItem, kind: 'pill' | 'land' | 'beat', k = 0, n = 1): number => {
  const c = it.card;
  if (kind === 'pill') {
    if (c.type === 'hook' && k === 0) return c.hero ? H.pivot + H.pill : 0;
    if (c.cue_ms != null) return c.cue_ms + k * 400;
    return MS.lead + it.voMs * 0.3 + k * 400 - MS.pillLead;
  }
  if (kind === 'land') {
    if (c.say) {
      const w = it.words.find((x) => x.w.includes(c.say!));
      if (w) return MS.lead + w.t;
    }
    return MS.lead + it.voMs * 0.35 + MS.count;
  }
  // Use an exact spoken opening for a points/group/next row where available; otherwise evenly spread.
  const index = Math.floor(k);
  const row = c.points?.[index] ?? c.rows?.[index]?.label ?? c.steps?.[index]?.text;
  if (row) {
    const opening = String(row).replace(/\{\{|\}\}|\[\[|\]\]/g, '').trim().split(/\s+/)[0];
    const norm = (s: string) => s.replace(/[।?!,.:;]/g, '');
    const w = it.words.find((w) => norm(w.w) === norm(opening));
    if (w) return MS.lead + w.t;
  }
  return MS.lead + (it.voMs * k) / Math.max(1, n);
};

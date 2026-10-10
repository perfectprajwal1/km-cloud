// v12 "Night Desk". C is kept verbatim (outro + any legacy caller). Story cards, strips and the subtitle band use K / G / TS.
export const C = {paper: '#ECE7DC', ink: '#1E1C1A', grey: '#5A5650', red: '#B80000',
  dim: 'rgba(236,231,220,0.70)', rule: 'rgba(90,86,80,0.40)'};
export const L = {W: 1080, H: 1920, x: 90, top: 430, col: 720, wide: 900, safeBottom: 1110,
  logo: {x: 90, y: 200, w: 184}, cap: {y: 1130, h: 120}, strip: {y: 1270, h: 650}};
export const T = {hook: 104, hookLH: 1.3, hl: 84, hlLH: 1.32, num: 320, sec: 48, cap: 52, min: 44, font: 'Mukta'};

// Engage palette = house palette. One red family: hot (highlight) -> red (brand) -> deep (shade).
export const K = {
  ink: '#110F0F', paper: '#F3EDE3', red: '#D7141E', hot: '#F0303A', deep: '#9E0C14',
  dim: 'rgba(243,237,227,.62)', faint: 'rgba(243,237,227,.38)', ghost: 'rgba(243,237,227,.10)', line: 'rgba(243,237,227,.14)',
  glass: 'linear-gradient(180deg,rgba(243,237,227,.10),rgba(243,237,227,.04))',
  glassRing: 'inset 0 0 0 2px rgba(243,237,227,.12), inset 0 2px 0 rgba(243,237,227,.10), 0 30px 80px -20px rgba(0,0,0,.7)',
  redFill: 'radial-gradient(120% 120% at 30% 20%,#F0303A,#D7141E 45%,#9E0C14)',
  redGlow: '0 18px 50px -6px rgba(215,20,30,.6), inset 0 2px 0 rgba(243,237,227,.25)',
  redRing: 'inset 0 0 0 2px rgba(215,20,30,.85), 0 30px 80px -20px rgba(0,0,0,.7)',
  text: '0 2px 0 rgba(0,0,0,.25), 0 18px 50px rgba(0,0,0,.45)',
  redText: '0 2px 0 rgba(0,0,0,.25), 0 0 60px rgba(215,20,30,.35)',
};
// Grid. Text column x80-940 (right 140 px = Reels/Shorts rail). Every story card bottom-anchors its deck at y1040,
// the red end-rule sits at y1066, the subtitle capsule at y1140-1240, the strip at y1270.
// mount = where the root mounts a story card. 0/0 = full canvas (exactly like Engage). Old 90/430 column => {x: 90, y: 430}.
export const G = {x: 80, w: 860, r: 940, logo: {x: 80, y: 168, w: 176}, top: 400, deck: 1040, rule: 1066,
  cap: {y: 1140, h: 100, pad: 40, max: 860}, strip: {y: 1270, h: 650}, mount: {x: 0, y: 0}};
// Type ladders: the first rung whose line budget fits wins. Line-height always >= 1.28 em (matras + conjuncts stay inside masks).
export type Rung = {size: number; lh: number; max: number};
export const TS: Record<'display' | 'headline' | 'quote' | 'body', Rung[]> = {
  display: [{size: 112, lh: 144, max: 2}, {size: 100, lh: 130, max: 3}, {size: 92, lh: 120, max: 3}, {size: 84, lh: 108, max: 4}, {size: 76, lh: 100, max: 4}],
  headline: [{size: 76, lh: 100, max: 2}, {size: 68, lh: 90, max: 3}, {size: 60, lh: 80, max: 4}],
  quote: [{size: 72, lh: 98, max: 3}, {size: 64, lh: 88, max: 4}, {size: 56, lh: 78, max: 5}, {size: 52, lh: 72, max: 5}],
  body: [{size: 52, lh: 68, max: 2}, {size: 46, lh: 62, max: 2}, {size: 42, lh: 56, max: 3}],
};

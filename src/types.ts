export type Word = {t: number; d: number; w: string};           // ms from voice start
export type TimingCard = {file: string; ms: number; words: Word[]};
export type Timing = {voice?: string; cards: TimingCard[]};
export type EngageCard = {type: 'engage'; dark: true; question: string; cta: string; key?: string; vo: string;
  voice_tone?: string; sfx?: {land?: string; cta?: string}; strip: {kind: 'none'}; [k: string]: any};
export type Card = EngageCard | {type: string; dark?: boolean; carry?: boolean; vo?: string; say?: string; cue_ms?: number; strip?: any; [k: string]: any};
export type Story = {id: string; sample?: boolean; cards: Card[]; [k: string]: any};
export type Props = {story: Story; timing: Timing; lite?: boolean};
export type PlanItem = {idx: number; card: Card; from: number; frames: number; durMs: number; voMs: number;
  words: Word[]; voice?: string; last: boolean; carry: boolean};

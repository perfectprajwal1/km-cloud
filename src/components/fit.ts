import {measureText} from '@remotion/layout-utils';
// Largest size <= base so text fits maxLines in width (approximate, +6% safety for Devanagari matras).
export const fitSize = (text: string, base: number, min: number, width: number, maxLines: number, weight = '800') => {
  for (let fs = base; fs > min; fs -= 2) {
    const w = measureText({text, fontFamily: 'Mukta', fontWeight: weight, fontSize: fs, letterSpacing: '0px'}).width * 1.06;
    if (Math.ceil(w / width) <= maxLines) return fs;
  }
  return min;
};

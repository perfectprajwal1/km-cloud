const DEV = '०१२३४५६७८९';
export const ne = (v: unknown, dec = 0): string => {
  if (typeof v === 'number') {
    const neg = v < 0; let [ip, fp] = Math.abs(v).toFixed(dec).split('.');
    if (ip.length > 3) ip = ip.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + ip.slice(-3); // Indian grouping
    return ((neg ? '-' : '') + ip + (fp ? '.' + fp : '')).replace(/\d/g, (d) => DEV[+d]);
  }
  return String(v ?? '').replace(/\d/g, (d) => DEV[+d]);
};
export type Seg = {t: string; k: 'n' | 'pill' | 'red'};
export const parse = (s = ''): Seg[] => {
  const out: Seg[] = []; const re = /\{\{(.+?)\}\}|\[\[(.+?)\]\]/g; let last = 0; let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({t: s.slice(last, m.index), k: 'n'});
    out.push(m[1] != null ? {t: m[1], k: 'pill'} : {t: m[2], k: 'red'}); last = re.lastIndex;
  }
  if (last < s.length) out.push({t: s.slice(last), k: 'n'});
  return out.map((x) => ({...x, t: ne(x.t)}));
};
export const plain = (s = '') => parse(s).map((x) => x.t).join('');

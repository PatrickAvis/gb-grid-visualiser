export const SERIES = [
  { key: 'PN', label: 'PN', name: 'Physical Notification', color: '#1261a0', dash: '' },
  { key: 'MELS', label: 'MEL', name: 'Maximum Export Limit', color: '#b04700', dash: '9 4' },
  { key: 'SEL', label: 'SEL', name: 'Stable Export Limit', color: '#157347', dash: '3 3' },
  { key: 'MILS', label: 'MIL', name: 'Maximum Import Limit', color: '#873eaa', dash: '10 3 2 3' },
];
const API = 'https://data.elexon.co.uk/bmrs/api/v1';
const number = value => value !== null && value !== '' && value !== undefined && Number.isFinite(Number(value)) ? Number(value) : null;

export function physicalSegments(rows, bmu, start, end) {
  const result = { PN: [], MELS: [], MILS: [] };
  for (const row of rows) {
    if (row.bmUnit !== bmu || !result[row.dataset]) continue;
    const a = Date.parse(row.timeFrom), b = Date.parse(row.timeTo);
    const v = number(row.levelFrom), w = number(row.levelTo);
    if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a || v === null || w === null || b <= start || a >= end) continue;
    const from = Math.max(a, start), to = Math.min(b, end);
    result[row.dataset].push({ from, to, v: v + (w-v)*(from-a)/(b-a), w: v + (w-v)*(to-a)/(b-a) });
  }
  for (const segments of Object.values(result)) segments.sort((a,b) => a.from-b.from);
  return result;
}

export function selSegments(baseline, changes, bmu, start, end) {
  const points = [...baseline.map(r=>({...r, level:r.value})), ...changes]
    .filter(r=>r.bmUnit===bmu && r.dataset==='SEL' && number(r.level)!==null)
    .map(r=>({time:Date.parse(r.time), value:Number(r.level)}))
    .filter(r=>Number.isFinite(r.time) && r.time<=end)
    .sort((a,b)=>a.time-b.time);
  const unique = new Map(points.map(p=>[p.time,p]));
  const ordered = [...unique.values()];
  return ordered.flatMap((p,i)=>{
    const from=Math.max(start,p.time), to=Math.min(end,ordered[i+1]?.time ?? end);
    return to>from ? [{from,to,v:p.value,w:p.value}] : [];
  });
}

export function valueAt(segments, time) {
  // At a shared boundary, the new segment takes precedence.
  const segment = [...segments].reverse().find(s=>s.from<=time && s.to>=time);
  return segment ? segment.v+(segment.w-segment.v)*(time-segment.from)/(segment.to-segment.from) : null;
}

export function acceptanceSegments(rows, bmu, start, end) {
  return rows.flatMap(row => {
    const segments = physicalSegments([{...row, dataset:'PN'}], bmu, start, end).PN;
    return segments.map(segment => ({...segment, row}));
  }).sort((a,b) => a.from-b.from || String(a.row.acceptanceNumber).localeCompare(String(b.row.acceptanceNumber)));
}

export function bidOfferPeriods(rows, bmu, start, end) {
  const periods = new Map();
  for (const row of rows) {
    if (row.bmUnit !== bmu || !(Date.parse(row.timeTo)>start && Date.parse(row.timeFrom)<end)) continue;
    const key = `${row.settlementDate} / SP ${row.settlementPeriod}`;
    if (!periods.has(key)) periods.set(key, []);
    periods.get(key).push(row);
  }
  return [...periods].sort(([a],[b]) => a.localeCompare(b, undefined, {numeric:true})).map(([label, entries]) => ({
    label, entries: entries.sort((a,b) => Number(a.pairId)-Number(b.pairId) || Date.parse(a.timeFrom)-Date.parse(b.timeFrom)),
  }));
}

export async function fetchBmuSeries(bmu, start, end, signal) {
  async function get(path, params) {
    const url = new URL(API+path);
    for (const [key,value] of Object.entries(params)) {
      for (const item of Array.isArray(value)?value:[value]) url.searchParams.append(key,item);
    }
    const response = await fetch(url, {signal, cache:'no-store'});
    if (!response.ok) throw new Error(`Elexon returned HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.data)) throw new Error('Unexpected Elexon response');
    return payload.data;
  }
  const from=new Date(start).toISOString(), to=new Date(end).toISOString();
  const results = await Promise.allSettled([
    get('/balancing/physical',{bmUnit:bmu,from,to,dataset:['PN','MELS','MILS']}),
    get('/balancing/dynamic',{bmUnit:bmu,snapshotAt:from,dataset:'SEL'}),
    get('/datasets/SEL',{bmUnit:bmu,from,to}),
    get('/balancing/acceptances',{bmUnit:bmu,from,to}),
    get('/balancing/bid-offer',{bmUnit:bmu,from,to}),
  ]);
  if (signal.aborted) throw signal.reason || new Error('Request cancelled');
  const rows = i=>results[i].status==='fulfilled'?results[i].value:[];
  const series=physicalSegments(rows(0),bmu,start,end);
  // Do not carry a baseline across a window if change retrieval failed.
  series.SEL=results[2].status==='fulfilled'?selSegments(rows(1),rows(2),bmu,start,end):[];
  const labels=['PN / MEL / MIL','SEL initial limit','SEL changes','Accepted instructions','Submitted bid/offer data'];
  const errors=results.flatMap((r,i)=>r.status==='rejected'?[`${labels[i]}: ${r.reason.message}`]:[]);
  return {series, errors,
    acceptances: acceptanceSegments(rows(3),bmu,start,end),
    bidOffers: bidOfferPeriods(rows(4),bmu,start,end),
    acceptancesAvailable: results[3].status==='fulfilled',
    bidOffersAvailable: results[4].status==='fulfilled',
  };
}

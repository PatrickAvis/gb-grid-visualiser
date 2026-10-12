// Public feeds. No persistence: refreshing an enabled layer requests a new snapshot.
export const ELEXON = 'https://data.elexon.co.uk/bmrs/api/v1';
export const NESO = 'https://api.neso.energy/api/3/action/datastore_search';
export const BOUNDARY_RESOURCE = '38a18ec1-9e40-465d-93fb-301e80fd1352';
export const number = value => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);

export async function getJson(url, signal) {
  const response = await fetch(url, {signal});
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}
function url(base, params) {
  const result = new URL(base);
  for (const [key, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : [value]) result.searchParams.append(key, item);
  }
  return result;
}
function rows(payload) {
  if (!Array.isArray(payload.data)) throw new Error('Unexpected feed response');
  return payload.data;
}
export function latestNotices(data) {
  const latest = new Map();
  for (const row of data) {
    const key = row.mrid || String(row.id), old = latest.get(key);
    if (!old || Number(row.revisionNumber) > Number(old.revisionNumber)
      || (Number(row.revisionNumber) === Number(old.revisionNumber) && row.publishTime > old.publishTime)) latest.set(key, row);
  }
  return [...latest.values()];
}
export function activeNotices(data, from, to) {
  // Resolve revisions BEFORE filtering, so a dismissal cannot resurrect an older notice.
  return latestNotices(data).filter(row => row.eventStatus === 'Active'
    && Date.parse(row.eventStartTime) < to && Date.parse(row.eventEndTime) > from)
    .sort((a,b) => a.eventStartTime.localeCompare(b.eventStartTime));
}
export async function fetchOutages(from, to, signal) {
  const list = latestNotices(rows(await getJson(url(`${ELEXON}/remit/list/by-event`, {
    from: new Date(from).toISOString(), to: new Date(to).toISOString(), latestRevisionOnly: true,
  }), signal)));
  const details = [];
  // Bounded batches avoid hundreds of concurrent per-message requests. Fail the
  // snapshot if any batch is missing; never label an incomplete snapshot as clear.
  for (let i=0; i<list.length; i+=50) {
    const ids = list.slice(i,i+50).map(row => row.id);
    const batch = rows(await getJson(url(`${ELEXON}/remit`, {messageId: ids}), signal));
    if (ids.some(id => !batch.some(row => String(row.id) === String(id)))) throw new Error('Incomplete outage response; retry refresh');
    details.push(...batch);
  }
  return activeNotices(details, from, to);
}
export function latestFlows(data) {
  const latest = new Map();
  for (const row of data) {
    if (!row.interconnectorName || !Number.isFinite(Date.parse(row.startTime))) continue;
    const old = latest.get(row.interconnectorName);
    if (!old || row.startTime > old.startTime || (row.startTime === old.startTime && row.publishTime > old.publishTime)) latest.set(row.interconnectorName, row);
  }
  // Do not fall back to an older value when the most recent observation is null.
  return [...latest.values()].map(row => ({...row, generation: number(row.generation)}))
    .sort((a,b) => a.interconnectorName.localeCompare(b.interconnectorName));
}
export async function fetchFlows(now, signal) {
  return latestFlows(rows(await getJson(url(`${ELEXON}/generation/outturn/interconnectors`, {
    from: new Date(now-24*3600000).toISOString(), to: new Date(now).toISOString(),
  }), signal)));
}
export async function fetchBoundaries(signal) {
  async function search(params) {
    const payload = await getJson(url(NESO, {resource_id: BOUNDARY_RESOURCE, ...params}), signal);
    if (!payload.success || !Array.isArray(payload.result?.records)) throw new Error('Unexpected boundary response');
    return payload.result;
  }
  const latest = await search({limit:1, sort:'Date_ Time GMT_BST desc'});
  if (!latest.records.length) return [];
  const period = latest.records[0]['Date_ Time GMT_BST'];
  const result = await search({limit:1000, filters:JSON.stringify({'Date_ Time GMT_BST':period})});
  if (result.total > result.records.length) throw new Error('Incomplete boundary response');
  return result.records.sort((a,b) => a['Constraint Group'].localeCompare(b['Constraint Group']));
}

export function siteIndex(plants, links) {
  const normalize = id => String(id || '').replace(/^(way|node|relation)\//,'');
  const sites = new Map(plants.features.map(feature => [normalize(feature.properties.osm_id), feature]));
  const index = new Map();
  for (const row of links) {
    const site = sites.get(normalize(row.osm_id));
    const lat = number(site?.properties.latitude), lon = number(site?.properties.longitude);
    if (!site || lat == null || lon == null || Math.abs(lat)>90 || Math.abs(lon)>180) continue;
    // Exact BMU IDs only; no speculative matching of asset names or EIC codes.
    if (row.bmu_id) index.set(row.bmu_id, {lat,lon,name:site.properties.name || row.plant_name,bmu:row.bmu_id,properties:site.properties});
  }
  return index;
}

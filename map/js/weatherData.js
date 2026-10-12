const cache = new Map();
export const weatherFields = ['wind_speed_10m','wind_direction_10m','wind_speed_120m','wind_direction_120m','wind_gusts_10m','temperature_2m','cloud_cover'];
export const weatherNumber = v => v == null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v);
export const weatherTimeLabel = t => new Date(t).toISOString().slice(0,16).replace('T',' ')+' UTC';
// Meteorological direction is where wind comes FROM. Arrows point towards it travels.
export const windRotation = from => ((from + 180) % 360 + 360) % 360;
export function weatherAt(data, time) {
  const index = data.hourly.time.indexOf(time/1000);
  return Object.fromEntries(weatherFields.map(key=>[key,index<0 ? null : weatherNumber(data.hourly[key]?.[index])]));
}
export async function fetchWeather(points, signal, refresh=false) {
  const key=JSON.stringify(points), old=cache.get(key);
  if(!refresh && old && Date.now()-old.fetchedAt<30*60000)return old;
  const url=new URL('https://api.open-meteo.com/v1/forecast');
  const params={latitude:points.map(p=>p.lat).join(','),longitude:points.map(p=>p.lon).join(','),hourly:weatherFields.join(','),wind_speed_unit:'ms',timeformat:'unixtime',timezone:'GMT',forecast_hours:49,cell_selection:'nearest'};
  for(const [k,v] of Object.entries(params))url.searchParams.set(k,v);
  const response=await fetch(url,{signal});
  if(!response.ok)throw new Error(`Weather request failed (${response.status})`);
  const payload=await response.json(), rows=Array.isArray(payload)?payload:[payload];
  if(rows.length!==points.length || rows.some(r=>!Array.isArray(r.hourly?.time) || !r.hourly.time.length || r.hourly_units?.wind_speed_120m!=='m/s'))throw new Error('Incomplete weather response');
  const result={rows,fetchedAt:Date.now()};
  cache.set(key,result);
  if(cache.size>80)cache.delete(cache.keys().next().value);
  return result;
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {windRotation,weatherAt,fetchWeather} from '../map/js/weatherData.js';
import {windVector,createWindField} from '../map/js/windField.js';
test('wind field interpolates components across north and never fills missing/outside cells',()=>{
  const points=[{lat:0,lon:0},{lat:0,lon:1},{lat:1,lon:0},{lat:1,lon:1}];
  const field=createWindField(points,[359,1,359,1].map(d=>windVector(10,d)));
  assert.ok(Math.abs(field(0.5,0.5).u)<0.001);assert.ok(field(0.5,0.5).v<-9.9);
  assert.equal(field(-0.1,0.5),null);
  assert.equal(createWindField(points,[null,...[0,0,0].map(d=>windVector(10,d))])(0.5,0.5),null);
  assert.deepEqual(windVector(0,null),{u:0,v:0});
});
test('meteorological from bearing becomes downwind arrow bearing',()=>{
  assert.equal(windRotation(0),180);assert.equal(windRotation(270),90);assert.equal(windRotation(180),0);
});
test('exact forecast hour is required and missing weather is not zero',()=>{
  const data={hourly:{time:[0,3600],wind_speed_120m:[0,null],wind_direction_120m:[360,90]}};
  assert.equal(weatherAt(data,0).wind_speed_120m,0);
  assert.equal(weatherAt(data,3600000).wind_speed_120m,null);
  assert.equal(weatherAt(data,1800000).wind_speed_120m,null);
});
test('forecast uses UTC seconds, m/s, nearest land/sea grid and caches successful requests',async()=>{
  const original=globalThis.fetch,urls=[];
  globalThis.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>({latitude:54,longitude:-2,hourly_units:{wind_speed_120m:'m/s'},hourly:{time:[0]}})};};
  try {
    const points=[{lat:54,lon:-2}];await fetchWeather(points);await fetchWeather(points);
    assert.equal(urls.length,1);assert.equal(urls[0].searchParams.get('cell_selection'),'nearest');assert.equal(urls[0].searchParams.get('timeformat'),'unixtime');assert.equal(urls[0].searchParams.get('forecast_hours'),'49');
    await fetchWeather(points,undefined,true);assert.equal(urls.length,2);
  } finally{globalThis.fetch=original;}
});
test('failed or incomplete multi-point feed is rejected',async()=>{
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async()=>({ok:false,status:429});await assert.rejects(fetchWeather([{lat:55,lon:0}]),/429/);
    globalThis.fetch=async()=>({ok:true,json:async()=>[]});await assert.rejects(fetchWeather([{lat:55,lon:0}]),/Incomplete/);
  }finally{globalThis.fetch=original;}
});

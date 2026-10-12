import test from 'node:test';
import assert from 'node:assert/strict';
import {activeNotices, latestFlows, siteIndex, fetchOutages, fetchBoundaries} from '../map/js/operationalData.js';

test('dismissed revisions suppress older active notices; overlap and future windows are respected',()=>{
  const base={mrid:'a',id:1,revisionNumber:1,eventStatus:'Active',eventStartTime:'2026-10-10T00:00:00Z',eventEndTime:'2026-10-20T00:00:00Z'};
  const start=Date.parse('2026-10-12T00:00:00Z'),end=start+7*86400000;
  assert.deepEqual(activeNotices([base,{...base,id:2,revisionNumber:2,eventStatus:'Dismissed'}],start,end),[]);
  assert.equal(activeNotices([base,{...base,mrid:'b',eventStartTime:new Date(end).toISOString()}],start,end).length,1);
});
test('latest outturn preserves negative and zero flows, missing values stay missing',()=>{
  const row={interconnectorName:'A',startTime:'2026-10-12T12:00:00Z',generation:-100};
  assert.equal(latestFlows([row])[0].generation,-100);
  assert.equal(latestFlows([row,{...row,startTime:'2026-10-12T12:30:00Z',generation:null}])[0].generation,null);
  assert.equal(latestFlows([{...row,generation:0}])[0].generation,0);
});
test('outage joins require exact linked BMU and valid coordinates',()=>{
  const plants={features:[{properties:{osm_id:123,latitude:51,longitude:-1,name:'Plant'}},{properties:{osm_id:456,latitude:null,longitude:1}}]};
  const index=siteIndex(plants,[{osm_id:'way/123',bmu_id:'T_TEST-1'},{osm_id:'way/456',bmu_id:'T_BAD'}]);
  assert.equal(index.get('T_TEST-1').name,'Plant');assert.equal(index.has('TEST-1'),false);assert.equal(index.has('T_BAD'),false);
});
test('missing outage batch fails instead of presenting incomplete availability',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async url=>({ok:true,json:async()=>({data:url.pathname.endsWith('/by-event')?[{id:1,mrid:'a',revisionNumber:1}]:[]})});
  try {await assert.rejects(fetchOutages(0,1000),/Incomplete outage/);} finally {globalThis.fetch=original;}
});
test('boundary fetch requests all groups at the latest published local period',async()=>{
  const original=globalThis.fetch,urls=[];
  globalThis.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>({success:true,result:{total:1,records:[{'Date_ Time GMT_BST':'2026-10-10T23:30:00','Constraint Group':'SCOTEX',Flow_MW:500,Limit_MW:1000}]}})};};
  try {assert.equal((await fetchBoundaries()).length,1);assert.deepEqual(JSON.parse(urls[1].searchParams.get('filters')),{'Date_ Time GMT_BST':'2026-10-10T23:30:00'});} finally {globalThis.fetch=original;}
});

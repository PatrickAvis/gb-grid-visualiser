import test from 'node:test';
import assert from 'node:assert/strict';
import {physicalSegments,selSegments,valueAt,fetchBmuSeries} from '../map/js/bmuSeries.js';
const iso=n=>new Date(n).toISOString();
test('physical ramps clip to the window; missing values and other BMUs stay absent',()=>{
 const row={dataset:'PN',bmUnit:'A',timeFrom:iso(0),timeTo:iso(100),levelFrom:-20,levelTo:80};
 const series=physicalSegments([row,{...row,bmUnit:'B'},{...row,dataset:'MILS',levelFrom:null}],'A',20,80);
 assert.deepEqual(series.PN,[{from:20,to:80,v:0,w:60}]);assert.deepEqual(series.MILS,[]);
 assert.equal(valueAt(series.PN,50),30);assert.equal(valueAt(series.PN,90),null);
});
test('SEL carries an older baseline, steps at changes and does not invent initial coverage',()=>{
 const baseline=[{dataset:'SEL',bmUnit:'A',time:iso(0),value:20}];
 const changes=[{dataset:'SEL',bmUnit:'A',time:iso(50),level:30}];
 const segments=selSegments(baseline,changes,'A',10,100);
 assert.deepEqual(segments,[{from:10,to:50,v:20,w:20},{from:50,to:100,v:30,w:30}]);
 assert.equal(valueAt(segments,50),30);
 assert.equal(valueAt(selSegments([],changes,'A',10,100),20),null);
});
test('API queries use effective-time filters and never carry SEL through failed changes',async()=>{
 const original=globalThis.fetch,urls=[];
 globalThis.fetch=async url=>{urls.push(url);if(url.pathname.endsWith('/datasets/SEL'))return {ok:false,status:503};return {ok:true,json:async()=>({data:url.pathname.endsWith('/dynamic')?[{dataset:'SEL',bmUnit:'A',time:iso(0),value:20}]:[]})};};
 try{
  const result=await fetchBmuSeries('A',10,100,new AbortController().signal);
  assert.deepEqual(result.series.SEL,[]);assert.equal(result.errors.length,1);
  assert.deepEqual(urls[0].searchParams.getAll('dataset'),['PN','MELS','MILS']);
  assert.equal(urls[2].searchParams.get('from'),iso(10));
 }finally{globalThis.fetch=original;}
});

test('overlapping instructions retain identity, issue time and clipped ramp levels',async()=>{
 const {acceptanceSegments}=await import('../map/js/bmuSeries.js');
 const row={bmUnit:'A',timeFrom:iso(0),timeTo:iso(100),levelFrom:500,levelTo:600,acceptanceNumber:1,acceptanceTime:iso(-100)};
 const result=acceptanceSegments([row,{...row,acceptanceNumber:2,acceptanceTime:iso(-50),levelTo:700},{...row,bmUnit:'B'}],'A',20,80);
 assert.equal(result.length,2);assert.equal(result[0].v,520);assert.equal(result[1].w,660);
 assert.equal(result[0].row.acceptanceNumber,1);assert.equal(result[1].row.acceptanceTime,iso(-50));
});
test('bid offer periods preserve negative and zero prices, distinct dates and numeric period order',async()=>{
 const {bidOfferPeriods}=await import('../map/js/bmuSeries.js');
 const row={bmUnit:'A',timeFrom:iso(0),timeTo:iso(100),settlementDate:'2026-10-25',settlementPeriod:10,pairId:-1,levelFrom:-200,levelTo:-200,bid:-185,offer:0};
 const result=bidOfferPeriods([row,{...row,settlementPeriod:2},{...row,settlementDate:'2026-10-26'},{...row,bmUnit:'B'}],'A',0,100);
 assert.equal(result.length,3);assert.equal(result[0].label,'2026-10-25 / SP 2');
 assert.equal(result[1].entries[0].bid,-185);assert.equal(result[1].entries[0].offer,0);
});
test('failed acceptance request is distinct from a successful empty bid offer response',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async url=>url.pathname.endsWith('/acceptances')?{ok:false,status:503}:{ok:true,json:async()=>({data:[]})};
 try{
  const result=await fetchBmuSeries('A',0,100,new AbortController().signal);
  assert.equal(result.acceptancesAvailable,false);assert.equal(result.bidOffersAvailable,true);
  assert.deepEqual(result.acceptances,[]);assert.match(result.errors[0],/Accepted instructions/);
 }finally{globalThis.fetch=original;}
});

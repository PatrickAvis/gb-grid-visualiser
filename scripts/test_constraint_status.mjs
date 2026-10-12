import test from 'node:test';
import assert from 'node:assert/strict';
import {constraintStatus,gbDate} from '../map/js/constraintStatus.js';
const row=(flow,limit,period='2026-10-13T12:00:00')=>({Flow_MW:flow,Limit_MW:limit,'Date_ Time GMT_BST':period});
const options={today:'2026-10-12'};
test('directional export margin and threshold colours preserve MW values',()=>{
  const excess=constraintStatus(row(6000,3000),options);assert.equal(excess.color,'#dc2626');assert.equal(excess.exceedance,3000);assert.equal(excess.headroom,-3000);
  assert.equal(constraintStatus(row(2700,3000),options).color,'#d97706');
  assert.equal(constraintStatus(row(2699,3000),options).color,'#16a34a');
  assert.equal(constraintStatus(row(3000,3000),options).exceedance,0);
  assert.equal(constraintStatus(row(1,0),options).color,'#dc2626');
});
test('old forecasts are grey unless explicitly viewing historical risk',()=>{
  const old=row(6000,3000,'2026-10-10T23:30:00');
  assert.equal(constraintStatus(old,options).color,'#64748b');
  assert.equal(constraintStatus(old,{...options,historical:true}).color,'#dc2626');
  assert.equal(constraintStatus(old,{...options,historical:true}).historical,true);
});
test('missing, reverse and invalid limits are never a green indication',()=>{
  for(const data of [undefined,row(null,3000),row(-500,3000),row(500,-1),row(500,3000,'')]){
    const status=constraintStatus(data,options);assert.equal(status.color,'#64748b');assert.equal(status.headroom,null);
  }
});
test('GB date respects BST across the UTC day boundary',()=>{
  assert.equal(gbDate(new Date('2026-07-01T23:30:00Z')),'2026-07-02');
});

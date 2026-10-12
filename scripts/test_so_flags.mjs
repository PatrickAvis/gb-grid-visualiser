import test from 'node:test';
import assert from 'node:assert/strict';
import {soStatus, activitySoStatus, matchesSoFilter} from '../map/js/soFlags.js';
import {bmActivityBidMarkerStyle} from '../map/js/styles.js';
import {instructionTitle} from '../map/js/bmuBalancing.js';

test('SO flags distinguish published false from absent or malformed data',()=>{
  assert.equal(soStatus(true),'flagged');
  assert.equal(soStatus(false),'unflagged');
  for(const value of [null,undefined,'false',0]) assert.equal(soStatus(value),'unknown');
  assert.equal(activitySoStatus({}),'unknown');
  assert.match(instructionTitle({row:{}}),/SO flag unknown/);
});
test('any-flagged filter includes mixed activity only when it contains flagged actions',()=>{
  assert.equal(matchesSoFilter({so_flag_status:'mixed',so_flagged_actions:1},'any-flagged'),true);
  assert.equal(matchesSoFilter({so_flag_status:'mixed',so_flagged_actions:0},'any-flagged'),false);
  assert.equal(matchesSoFilter({},'unflagged'),false);
  assert.equal(matchesSoFilter({},'unknown'),true);
  assert.equal(matchesSoFilter({so_flag_status:'mixed'},'flagged'),false);
});
test('SO outlines preserve the generation fill and distinguish mixed/unknown',()=>{
  const props={source_bucket:'wind',abs_volume_mwh:10};
  const a=bmActivityBidMarkerStyle({...props,so_flag_status:'flagged'});
  const b=bmActivityBidMarkerStyle({...props,so_flag_status:'unflagged'});
  assert.equal(a.fillColor,b.fillColor);assert.notEqual(a.color,b.color);
  assert.ok(bmActivityBidMarkerStyle({...props,so_flag_status:'mixed'}).dashArray);
  assert.ok(bmActivityBidMarkerStyle(props).dashArray);
});

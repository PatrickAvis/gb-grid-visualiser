import assert from 'node:assert/strict';
import test from 'node:test';
import { LineStyleSymbolizer } from '../map/js/sources/pmtiles.js';
const geometry=[[{x:0,y:0},{x:10,y:20},{x:30,y:40}]];
function context(){return {strokes:[],points:[],save(){},restore(){},beginPath(){},setLineDash(v){this.dash=v},moveTo(x,y){this.points.push([x,y])},lineTo(x,y){this.points.push([x,y])},stroke(){this.strokes.push({width:this.lineWidth,dash:this.dash,color:this.strokeStyle})}};}
test('solid routes draw every vertex at the requested width',()=>{const c=context();new LineStyleSymbolizer(()=>({weight:7,color:'#f00',opacity:.9})).draw(c,geometry,9,{props:{}});assert.deepEqual(c.points,[[0,0],[10,20],[30,40]]);assert.deepEqual(c.strokes,[{width:7,dash:[],color:'#f00'}]);});
test('cable dashes retain their requested width',()=>{const c=context();new LineStyleSymbolizer(()=>({weight:5,dashArray:'6 4'})).draw(c,geometry,9,{props:{}});assert.equal(c.strokes[0].width,5);assert.deepEqual(c.strokes[0].dash,[6,4]);});
test('hidden categories never stroke',()=>{const c=context();new LineStyleSymbolizer(()=>({weight:0,opacity:0})).draw(c,geometry,9,{props:{}});assert.equal(c.strokes.length,0);});

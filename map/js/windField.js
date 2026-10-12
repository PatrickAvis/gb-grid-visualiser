// Interpolate vector components, not compass bearings (359° and 1° meet at north).
export function windVector(speed, from) {
  if(speed==null || !Number.isFinite(speed) || speed<0)return null;
  if(speed===0)return {u:0,v:0};
  if(from==null || !Number.isFinite(from))return null;
  const angle=from*Math.PI/180;
  return {u:-speed*Math.sin(angle),v:-speed*Math.cos(angle)};
}
export function createWindField(points, vectors) {
  const lats=[...new Set(points.map(p=>p.lat))].sort((a,b)=>a-b);
  const lons=[...new Set(points.map(p=>p.lon))].sort((a,b)=>a-b);
  const lookup=new Map(points.map((p,i)=>[`${p.lat},${p.lon}`,vectors[i]]));
  function bracket(values,value){
    if(value<values[0] || value>values.at(-1))return null;
    const i=Math.min(values.length-2,Math.max(0,values.findIndex(v=>v>=value)-1));
    return [values[i],values[i+1]];
  }
  return (lat,lon)=>{
    const a=bracket(lats,lat),b=bracket(lons,lon);if(!a||!b)return null;
    const corners=[lookup.get(`${a[0]},${b[0]}`),lookup.get(`${a[0]},${b[1]}`),lookup.get(`${a[1]},${b[0]}`),lookup.get(`${a[1]},${b[1]}`)];
    if(corners.some(v=>!v))return null;
    const x=(lon-b[0])/(b[1]-b[0]),y=(lat-a[0])/(a[1]-a[0]);
    const weights=[(1-x)*(1-y),x*(1-y),(1-x)*y,x*y];
    const u=corners.reduce((s,c,i)=>s+c.u*weights[i],0),v=corners.reduce((s,c,i)=>s+c.v*weights[i],0);
    return {u,v,speed:Math.hypot(u,v)};
  };
}
export function windRgb(speed) {
  const stops=[[0,63,113,181],[5,64,175,179],[10,115,190,125],[15,232,201,99],[20,218,134,93],[30,172,77,127]];
  let i=0;while(i<stops.length-2&&speed>stops[i+1][0])i++;
  const a=stops[i],b=stops[i+1],t=Math.max(0,Math.min(1,(speed-a[0])/(b[0]-a[0])));
  return a.slice(1).map((v,j)=>Math.round(v+(b[j+1]-v)*t));
}

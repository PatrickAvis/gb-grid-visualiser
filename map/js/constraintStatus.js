import {number} from './operationalData.js';
export function gbDate(now=new Date()) {
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const part=key=>parts.find(p=>p.type===key).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function constraintStatus(row,{today=gbDate(),historical=false}={}) {
  const flow=number(row?.Flow_MW),limit=number(row?.Limit_MW),period=row?.['Date_ Time GMT_BST'];
  const unknown=label=>({color:'#64748b',label,headroom:null,exceedance:null});
  if(flow==null||limit==null||limit<0||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(period||''))return unknown('No usable forecast');
  // Reverse flows cannot be assessed against a positive-direction export limit.
  if(flow<0)return unknown('Reverse flow — import limit not assessed');
  const headroom=limit-flow,exceedance=Math.max(0,-headroom);
  let status=flow>limit ? {color:'#dc2626',label:'Forecast exceeds export limit'}
    : flow>=limit*0.9 ? {color:'#d97706',label:'Near export limit (90–100%)'}
    : {color:'#16a34a',label:'Below export limit (<90%)'};
  const old=period.slice(0,10)<today;
  if(old&&!historical)status={color:'#64748b',label:'Historical forecast — risk colour hidden'};
  return {...status,headroom,exceedance,historical:old};
}

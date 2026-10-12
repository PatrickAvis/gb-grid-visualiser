import {fetchBoundaries,getJson,number} from './operationalData.js';
import {constraintStatus} from './constraintStatus.js';
import {escapeHtml as esc} from './utils.js';

const gw=v=>v==null?'Unavailable':`${(v/1000).toFixed(3)} GW`;
const definitions={B4:{code:'SSE_SP2',title:'B4 · Northern Scotland'},B6:{code:'SCOTEX',title:'B6 · Scotland export'}};

export function installConstraintZones(map) {
  const box=document.createElement('details');box.className='layer-group constraint-zones';box.open=true;
  box.innerHTML=`<summary>Constraint area colours</summary><label><input type="checkbox" id="constraint-zones-enabled"> Shade Scottish export areas</label>
    <label>Area <select aria-label="Constraint area"><option value="B4">B4 · Northern Scotland</option><option value="B6">B6 · Scotland export</option></select></label>
    <label><input type="checkbox" class="constraint-history"> Colour historical forecasts</label>
    <button type="button" disabled>Refresh forecast</button><button type="button" class="constraint-details" disabled>View area details</button>
    <p role="status">Enable to fetch the latest published forecast period.</p>
    <p class="constraint-legend"><span style="color:#dc2626">● Exceeds limit</span> · <span style="color:#d97706">● 90–100%</span> · <span style="color:#16a34a">● Below 90%</span> · <span style="color:#64748b">● Historical / unknown</span></p>
    <p>One nested area at a time. Illustrative land shading north of the boundary; excludes offshore assets and Shetland. Export constraint margin, not generation minus local demand. Independent of zone filters.</p>`;
  document.getElementById('layer-list').prepend(box);
  const enabled=box.querySelector('input'),select=box.querySelector('select'),history=box.querySelector('.constraint-history'),refresh=box.querySelector('button'),details=box.querySelector('.constraint-details'),status=box.querySelector('[role=status]');
  const pane=map.getPane('constraintAreas')||map.createPane('constraintAreas');pane.style.zIndex='370';
  // Separate renderer/pane leaves existing asset layers above the translucent fill.
  const renderer=L.svg({pane:'constraintAreas'});
  const group=L.layerGroup();let controller=null,geometry=null,rows=[],loadedAt=null,currentLayer=null,currentHtml='';
  function showDetails(){if(currentLayer)L.popup().setLatLng(currentLayer.getBounds().getCenter()).setContent(currentHtml).openOn(map);}
  function render(){
    group.clearLayers();currentLayer=null;details.disabled=true;if(!enabled.checked||!geometry)return;
    const id=select.value,definition=definitions[id],feature=geometry.features.find(f=>f.properties.boundary_id===id);
    if(!feature){status.textContent=`No reviewed area geometry for ${id}.`;return;}
    const row=rows.find(r=>r['Constraint Group']===definition.code),risk=constraintStatus(row,{historical:history.checked});
    const period=row?.['Date_ Time GMT_BST']||'Unavailable';
    const suffix=risk.historical?' Historical period.':'';
    status.textContent=`${definition.title}: ${risk.label}. Period: ${period} GB local time.${suffix} Fetched ${loadedAt || 'unavailable'}.`;
    const fields={'Area':definition.title,'Constraint group':definition.code,'Status':risk.label,'Forecast flow (north → south)':gw(number(row?.Flow_MW)),'Export limit':gw(number(row?.Limit_MW)),'Headroom (limit − flow)':gw(risk.headroom),'Exceedance above limit':gw(risk.exceedance),'Forecast period':period+' GB local time (GMT/BST)','Historical':risk.historical?'Yes':'No / unknown'};
    currentHtml=`<strong>${esc(definition.title)}</strong><table class="popup-table">${Object.entries(fields).map(([k,v])=>`<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table>
      <p>${esc(feature.properties.geometry_note)}</p><p>Headroom is the published export limit minus forecast flow. Exceedance is max(flow − limit, 0). These nested boundary values must not be added together. Neither value is actual curtailment, a dispatch instruction or a local generation-demand balance. Amber starts at 90%, an application display threshold, not a NESO warning.</p>
      <p><a target="_blank" rel="noopener noreferrer" href="https://www.neso.energy/data-portal/day-ahead-constraint-flows-and-limits">NESO forecast source</a> · <a target="_blank" rel="noopener noreferrer" href="https://www.neso.energy/industry-information/balancing-services/local-constraint-market">B4 / B6 area context</a></p>`;
    currentLayer=L.geoJSON(feature,{renderer,style:{color:risk.color,fillColor:risk.color,fillOpacity:0.27,weight:1.5,dashArray:risk.historical?'5 4':null}}).addTo(group);
    currentLayer.bindTooltip(`${definition.title}: ${risk.label}`).bindPopup(currentHtml);
    details.disabled=false;
  }
  async function load(){
    controller?.abort();const current=new AbortController();controller=current;
    const timer=setTimeout(()=>current.abort(new Error('Forecast request timed out')),45000);
    group.clearLayers();currentLayer=null;rows=[];details.disabled=true;refresh.disabled=true;select.disabled=true;history.disabled=true;status.textContent='Fetching constraint forecast…';
    try{
      const [areas,data]=await Promise.all([getJson('../data/regions/uk/map/constraint_areas.geojson',current.signal),fetchBoundaries(current.signal)]);
      if(controller!==current||!enabled.checked)return;
      geometry=areas;rows=data;loadedAt=new Date().toISOString().slice(0,16).replace('T',' ')+' UTC';render();
    }catch(error){if(controller===current&&enabled.checked){geometry=null;status.textContent=`Unavailable: ${error.message}. No current area forecast displayed.`;}}
    finally{clearTimeout(timer);if(controller===current){refresh.disabled=!enabled.checked;select.disabled=false;history.disabled=false;}}
  }
  enabled.onchange=()=>{if(enabled.checked){group.addTo(map);load();}else{controller?.abort();controller=null;map.removeLayer(group);group.clearLayers();currentLayer=null;refresh.disabled=true;details.disabled=true;select.disabled=false;history.disabled=false;status.textContent='Area colours off.';}};
  select.onchange=render;history.onchange=render;refresh.onclick=load;details.onclick=showDetails;
  return {destroy(){controller?.abort();controller=null;map.removeLayer(group);map.removeLayer(renderer);box.remove();}};
}

import {fetchOutages, fetchFlows, fetchBoundaries, getJson, siteIndex, number} from './operationalData.js';
import {interconnectorSites, boundaryIds} from './operationalLocations.js';
import {escapeHtml as esc} from './utils.js';
import {popupRows} from './popups.js';
import {plantSourceBucket} from './styles.js';
import {fuelTypeColor, fuelTypeLabel} from './fuelTypes.js';

const sources = {
  outages:'https://bmrs.elexon.co.uk/remit',
  flows:'https://bmrs.elexon.co.uk/interconnector-flows',
  boundaries:'https://www.neso.energy/data-portal/day-ahead-constraint-flows-and-limits',
};
const mw = value => number(value) == null ? 'Unavailable' : `${Number(value).toLocaleString('en-GB')} MW`;
const utc = value => Number.isFinite(typeof value==='number' ? value : Date.parse(value)) ? new Date(value).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,' UTC') : 'Unknown';
const table = props => `<table class="popup-table">${Object.entries(props).map(([k,v])=>`<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table>`;
const direction = value => value == null ? 'Unavailable' : value > 0 ? 'Import to GB' : value < 0 ? 'Export from GB' : 'Zero flow';

export function installOperationalContext(map, config) {
  const section = document.createElement('details');
  section.className='layer-group operational-context'; section.open=true;
  section.innerHTML='<summary>Operational context</summary><p>Fetch on selection; refresh for updates. These layers are independent of zone filters.</p>';
  document.getElementById('layer-list').prepend(section);
  const states=[];

  function detail(title, props, kind, site, extra='') {
    return `<strong>${esc(title)}</strong>${table(props)}${extra}<p><a href="${sources[kind]}" target="_blank" rel="noopener noreferrer">${kind==='boundaries'?'NESO':'Elexon'} source</a></p>`
      + (site ? popupRows({latitude:site.lat,longitude:site.lon,...(site.bmu ? {bmu_id:site.bmu}: {})},[]) : '');
  }
  function addEntry(state, title, html, site=null, shape=null, color='#a15c00') {
    let layer=shape;
    if (site) layer=L.circleMarker([site.lat,site.lon],{radius:8,color,fillColor:color,fillOpacity:0.8,weight:2});
    if (layer) {
      layer.addTo(state.group).bindPopup(html).bindTooltip(title);
    }
    const button=document.createElement('button');button.type='button';button.textContent=title+(layer?'':' · not mapped');
    button.onclick=()=>{
      if(layer) {
        const center=site ? [site.lat,site.lon] : layer.getBounds().getCenter();
        if(site)map.setView(center,Math.max(map.getZoom(),8));else map.fitBounds(layer.getBounds(),{maxZoom:8});
        // A GeoJSON group has no point anchor; open explicitly at its centre.
        L.popup().setLatLng(center).setContent(html).openOn(map);
      } else L.popup().setLatLng(map.getCenter()).setContent(html).openOn(map);
    };
    state.list.append(button);
    return Boolean(layer);
  }
  async function outages(state, signal, now) {
    const end=now+7*86400000;
    const [notices,plants,links]=await Promise.all([
      fetchOutages(now,end,signal),getJson(config.layers.plants.url,signal),getJson(config.plantBmuMapUrl,signal),
    ]);
    signal.throwIfAborted();
    const index=siteIndex(plants,Array.isArray(links)?links:links.entries || []);
    let mapped=0;
    for(const row of notices) {
      const site=index.get(row.assetId);
      const fuel=plantSourceBucket(site?.properties || {});
      const fuelLabel=fuel==='other' ? 'Other / unknown' : fuelTypeLabel(fuel);
      const title=`${row.assetId || row.affectedUnit || row.mrid} · ${fuelLabel} · ${Date.parse(row.eventStartTime)>now?'Upcoming':'Ongoing'} · ${row.unavailabilityType || 'Outage'}`;
      const profile=Array.isArray(row.outageProfile)&&row.outageProfile.length
        ? `<details><summary>Published capacity profile (${row.outageProfile.length} segments)</summary>${row.outageProfile.map(p=>table({'From':utc(p.startTime),'To':utc(p.endTime),'Capacity as published':mw(p.capacity)})).join('')}</details>` : '';
      mapped+=addEntry(state,title,detail(site?.name || title,{
        'Notice':row.messageHeading || row.eventType,'Asset':row.assetId || row.affectedUnit,
        'Generation type (mapped site)':fuelLabel,
        'Status':row.eventStatus,'Start':utc(row.eventStartTime),'End':utc(row.eventEndTime),
        'Normal capacity':mw(row.normalCapacity),'Available (notice)':mw(row.availableCapacity),
        'Unavailable (notice)':mw(row.unavailableCapacity),'Cause':row.cause || 'Not supplied',
        'Published':utc(row.publishTime),'Revision':row.revisionNumber,'Message ID':row.id,
      },'outages',site,`<p>${esc(row.relatedInformation || '')}</p><p>Notice capacities are not a current MEL reading. Overlapping notices are not summed.</p>${profile}`),site,null,fuelTypeColor(fuel));
    }
    return `${notices.length} active notices overlapping now–${utc(end)}; ${mapped} mapped by exact BMU ID. Marker colours match the plant generation types; grey means other/unknown. Type comes from the mapped site. No marker does not mean available.`;
  }
  async function flows(state, signal, now) {
    const data=await fetchFlows(now,signal);signal.throwIfAborted();let mapped=0;
    for(const row of data) {
      const site=interconnectorSites[row.interconnectorName];
      const stale=now-Date.parse(row.startTime)>2*3600000;
      const value=row.generation;
      const title=`${row.interconnectorName} · ${direction(value)} ${value==null?'':mw(Math.abs(value))}${stale?' · older than 2h':''}`;
      mapped+=addEntry(state,title,detail(row.interconnectorName,{
        'Half-hour average':mw(value),'Direction':direction(value),'Period start':utc(row.startTime),
        'Published':utc(row.publishTime),'Freshness':stale?'Older than two hours':'Recent half-hourly outturn',
        'Location':site?.name || 'Not yet mapped',
      },'flows',site,'<p>Positive = import to GB; negative = export from GB. Marker represents the GB connection area, not a cable route or instantaneous measurement.</p>'),site,null,value==null?'#64748b':value<0?'#a855f7':'#0891b2');
    }
    return `${data.length} links reported in the last 24 hours; ${mapped} mapped. Cyan: import/zero; purple: export; grey: unavailable. Individual period timestamps are in the details.`;
  }
  async function boundaries(state, signal) {
    const data=await fetchBoundaries(signal);
    // The list remains useful even when an optional local boundary file is absent.
    let geometry=null;
    const cfg=Object.values(config.layers).find(layer=>layer.url?.endsWith('/etys_boundaries_web.geojson'));
    if(cfg)try {geometry=await getJson(cfg.url,signal);} catch(error) {if(signal.aborted)throw error;}
    signal.throwIfAborted();let mapped=0;
    for(const row of data) {
      const code=row['Constraint Group'],id=boundaryIds[code];
      const feature=geometry?.features.find(f=>(f.properties.boundary_id || f.properties.name)===id);
      const flow=number(row.Flow_MW),limit=number(row.Limit_MW);
      // Do not manufacture utilisation ratios: direction conventions and large
      // published limit values need context from NESO's constraint definitions.
      const shape=feature ? L.geoJSON(feature,{style:{color:'#d97706',weight:5,dashArray:'8 5'}}) : null;
      const title=`${code}${id?' / '+id:''} · ${mw(flow)} / ${mw(limit)}`;
      mapped+=addEntry(state,title,detail(code,{
        'Forecast flow':mw(flow),'Published limit':mw(limit),
        'Forecast period':`${row['Date_ Time GMT_BST']} GB local time (GMT/BST)`,
        'Boundary':id || 'No reviewed geometry match',
      },'boundaries',null,'<p>Day-ahead forecast snapshot, not measured flow or live circuit loading. This is the latest period available from the feed, which may be historical.</p>'),null,shape);
    }
    const period=data[0]?.['Date_ Time GMT_BST'];
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    return `${data.length} groups; ${mapped} mapped. Dashed amber: forecast boundary. Latest period: ${period || 'none'} GB local time.${period&&period.slice(0,10)<today?' HISTORICAL — before today.':''} Flow / limit shown in MW. Unmatched groups remain in the list.`;
  }
  for(const [key,title,loader] of [
    ['outages','REMIT outages · now + 7 days',outages],
    ['flows','Interconnectors · half-hourly outturn',flows],
    ['boundaries','Boundaries · day-ahead forecast',boundaries],
  ]) {
    const box=document.createElement('div');box.className='operational-feed';
    const label=document.createElement('label'),toggle=document.createElement('input');toggle.type='checkbox';toggle.id=`context-${key}`;
    label.append(toggle,document.createTextNode(title));
    const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Refresh';refresh.disabled=true;
    const status=document.createElement('p');status.setAttribute('role','status');status.textContent='Not fetched';
    const list=document.createElement('div');list.className='operational-list';list.hidden=true;
    box.append(label,refresh,status,list);section.append(box);
    const state={key,group:L.layerGroup(),list,controller:null};states.push(state);
    async function load() {
      state.controller?.abort();const controller=new AbortController();state.controller=controller;
      const timer=setTimeout(()=>controller.abort(new Error('Feed timed out; retry refresh')),90000);
      state.group.clearLayers();list.replaceChildren();refresh.disabled=true;status.textContent='Fetching public feed…';
      try {
        const message=await loader(state,controller.signal,Date.now());
        if(state.controller!==controller || !toggle.checked)return;
        status.textContent=`${message} Fetched ${utc(Date.now())}.`;
      } catch(error) {
        if(state.controller!==controller || !toggle.checked)return;
        state.group.clearLayers();list.replaceChildren();status.textContent=`Unavailable: ${error.message}. No current snapshot displayed.`;
      } finally {clearTimeout(timer);if(state.controller===controller)refresh.disabled=!toggle.checked;}
    }
    toggle.onchange=()=>{
      list.hidden=!toggle.checked;
      if(toggle.checked){state.group.addTo(map);load();}
      else {state.controller?.abort();state.controller=null;map.removeLayer(state.group);state.group.clearLayers();list.replaceChildren();refresh.disabled=true;status.textContent='Off';}
    };
    refresh.onclick=load;
  }
  return {destroy(){for(const state of states){state.controller?.abort();state.controller=null;map.removeLayer(state.group);}section.remove();}};
}

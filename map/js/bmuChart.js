import { SERIES, fetchBmuSeries, valueAt } from './bmuSeries.js';
import { escapeHtml } from './utils.js';
import { instructionColor, instructionId, instructionTitle, mountBalancingDetails } from './bmuBalancing.js';

const timeLabel = time => new Date(time).toLocaleTimeString('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit'});
const dateLabel = time => Number.isFinite(time) ? new Date(time).toISOString().replace('T',' ').slice(0,16)+' UTC' : 'Not supplied';

export function installBmuChart(map) {
  const panel=document.createElement('section');
  panel.className='bmu-chart-panel'; panel.hidden=true;
  panel.setAttribute('aria-label','BMU operating data');
  panel.innerHTML=`<header><div><strong>BMU operating data</strong><div class="bmu-chart-subtitle">Last 6 hours · MW · UTC</div></div><button type="button" class="bmu-chart-close" aria-label="Close BMU chart">×</button></header>
    <div class="bmu-chart-controls"><label>BMU <select aria-label="Chart BMU"></select></label><button type="button" class="bmu-chart-refresh">Refresh</button></div>
    <p class="bmu-chart-status" role="status"></p><div class="bmu-chart-content"></div>
    <p class="bmu-chart-note">Notifications, limits and instructions are not metered output. Gaps mean no data; signs follow Elexon. SEL is held until its next change.</p>
    <a href="https://bmrs.elexon.co.uk/" target="_blank" rel="noopener noreferrer">Source: Elexon Insights / NESO</a>`;
  document.body.append(panel);
  L.DomEvent.disableClickPropagation(panel); L.DomEvent.disableScrollPropagation(panel);
  const select=panel.querySelector('select'), status=panel.querySelector('.bmu-chart-status'), content=panel.querySelector('.bmu-chart-content');
  let controller, generation=0;
  function close() { generation++; controller?.abort(); panel.hidden=true; }
  panel.querySelector('.bmu-chart-close').onclick=close;
  panel.addEventListener('keydown',event=>{if(event.key==='Escape')close();});

  function render(data,start,end) {
    const {series,acceptances}=data;
    const values=[...Object.values(series).flat(),...acceptances].flatMap(s=>[s.v,s.w]);
    if (!values.length) {
      content.innerHTML='<p>No chart data available for this BMU in the last six hours.</p><div class="bmu-balancing-details"></div>';
      mountBalancingDetails(content.querySelector('.bmu-balancing-details'),data,()=>{});
      return;
    }
    let low=Math.min(0,...values), high=Math.max(0,...values);
    const pad=Math.max((high-low)*0.08,1); low-=pad; high+=pad;
    const x=t=>60+(t-start)/(end-start)*600, y=v=>235-(v-low)/(high-low)*200;
    const ticks=Array.from({length:5},(_,i)=>{
      const v=low+(high-low)*i/4;
      return `<line x1="60" x2="660" y1="${y(v)}" y2="${y(v)}" stroke="#e0e5eb"/><text x="52" y="${y(v)+4}" text-anchor="end">${Number(v.toFixed(1))}</text>`;
    }).join('');
    const times=Array.from({length:7},(_,i)=>{const t=start+(end-start)*i/6;return `<text x="${x(t)}" y="260" text-anchor="middle">${timeLabel(t)}</text>`;}).join('');
    const paths=SERIES.map(s=>`<path data-series="${s.key}" d="${series[s.key].map(p=>`M${x(p.from)},${y(p.v)} L${x(p.to)},${y(p.w)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="2.5" stroke-dasharray="${s.dash}"/>`).join('');
    const instructionPaths=acceptances.map(s=>`<path data-acceptance="${escapeHtml(instructionId(s))}" d="M${x(s.from)},${y(s.v)} L${x(s.to)},${y(s.w)}" fill="none" stroke="${instructionColor}" stroke-width="3" stroke-dasharray="5 2"><title>${escapeHtml(instructionTitle(s))}</title></path>`).join('');
    content.innerHTML=`<div class="bmu-chart-legend">${SERIES.map(s=>`<label style="color:${s.color}"><input type="checkbox" data-series="${s.key}" checked> ${s.label}<span>${escapeHtml(s.name)}</span></label>`).join('')}<label style="color:${instructionColor}"><input type="checkbox" class="bmu-instructions-toggle" checked> Instructions<span>Individual accepted levels</span></label></div>
      <svg viewBox="0 0 700 280" role="img" aria-label="PN, MEL, SEL, MIL and individual accepted instructions over the last six hours, in megawatts"><text x="12" y="18">MW</text>${ticks}${times}${paths}${instructionPaths}<line class="bmu-chart-cursor" x1="660" x2="660" y1="30" y2="235" stroke="#637083" stroke-dasharray="2 3"/></svg>
      <label class="bmu-chart-time">Inspect time <input type="range" min="0" max="360" value="360" aria-label="Inspect chart time"></label>
      <div class="bmu-chart-readout" aria-live="polite"></div><div class="bmu-balancing-details"></div>`;
    const svg=content.querySelector('svg'), slider=content.querySelector('input[type=range]'), readout=content.querySelector('.bmu-chart-readout');
    let selectedInstruction='', inspectedTime=end;
    const instructionToggle=content.querySelector('.bmu-instructions-toggle');
    function inspect(t) {
      inspectedTime=t;
      const cursor=svg.querySelector('.bmu-chart-cursor'); cursor.setAttribute('x1',x(t)); cursor.setAttribute('x2',x(t));
      readout.innerHTML=`<strong>${dateLabel(t)}</strong><div>${SERIES.map(s=>{const v=valueAt(series[s.key],t);return `<span style="color:${s.color}">${s.label}: <b>${v===null?'No data':v.toFixed(1)+' MW'}</b></span>`;}).join('')}</div>`;
      if(instructionToggle.checked) {
        const active=acceptances.filter(s=>(!selectedInstruction || instructionId(s)===selectedInstruction) && s.from<=t && s.to>=t);
        readout.innerHTML+=`<div style="color:${instructionColor}">${active.length?active.map(s=>`#${escapeHtml(instructionId(s))}: ${valueAt([s],t).toFixed(1)} MW (issued ${escapeHtml(dateLabel(Date.parse(s.row.acceptanceTime)))})`).join('<br>'):(data.acceptancesAvailable?'No returned instruction at this time':'Instruction data unavailable')}</div>`;
      }
    }
    slider.oninput=()=>inspect(start+Number(slider.value)/360*(end-start));
    svg.onpointermove=event=>{const rect=svg.getBoundingClientRect();const fraction=Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*700-60)/600));slider.value=Math.round(fraction*360);inspect(start+fraction*(end-start));};
    for (const checkbox of content.querySelectorAll('input[data-series]')) checkbox.onchange=()=>{svg.querySelector(`path[data-series="${checkbox.dataset.series}"]`).style.display=checkbox.checked?'':'none';};
    function highlight(id) {
      selectedInstruction=id;
      for(const path of svg.querySelectorAll('[data-acceptance]')) {
        path.style.display=instructionToggle.checked?'':'none';
        path.style.opacity=id && path.dataset.acceptance!==id?'0.15':'1';
        path.setAttribute('stroke-width',id && path.dataset.acceptance===id?'5':'3');
      }
      inspect(inspectedTime);
    }
    instructionToggle.onchange=()=>highlight(selectedInstruction);
    mountBalancingDetails(content.querySelector('.bmu-balancing-details'),data,highlight);
    inspect(end);
  }

  async function load() {
    controller?.abort(); controller=new AbortController();
    const signal=controller.signal, request=++generation, bmu=select.value;
    const end=Date.now(), start=end-6*60*60*1000;
    status.textContent=`Loading ${bmu} from Elexon…`; content.replaceChildren();
    const timer=setTimeout(()=>controller?.signal===signal && controller.abort(new Error('Elexon request timed out. Please refresh to retry.')),25000);
    try {
      const data=await fetchBmuSeries(bmu,start,end,signal);
      if(request!==generation)return;
      render(data,start,end);
      const {errors}=data;
      status.textContent=`${dateLabel(start)} – ${dateLabel(end)}. Fetched ${dateLabel(Date.now())}.${errors.length?' '+errors.join('; '):''}`;
    } catch(error) {
      if(request!==generation)return;
      status.textContent=`Unable to load ${bmu}: ${error.message}. Use Refresh to retry.`;
    } finally { clearTimeout(timer); }
  }
  select.onchange=load; panel.querySelector('.bmu-chart-refresh').onclick=load;
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-bmu-select]');
    if (!button || ![...select.options].some(o=>o.value===button.dataset.bmuSelect)) return;
    select.value=button.dataset.bmuSelect; panel.hidden=false; load();
  });
  map.on('popupopen',event=>{
    const source=event.popup.getElement()?.querySelector('[data-bmu-ids]');
    if(!source){close();return;}
    const ids=source.dataset.bmuIds.split(';').map(id=>id.trim()).filter(Boolean);
    select.replaceChildren(...ids.map(id=>new Option(id,id)));
    select.value=ids.find(id=>id.startsWith('T_')) || ids[0];
    panel.hidden=false; load();
  });
  return {close};
}

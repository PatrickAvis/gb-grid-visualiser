import { escapeHtml } from './utils.js';

export const instructionColor = '#c6263e';
export const instructionId = segment => String(segment.row.acceptanceNumber ?? 'Unknown');
const time = value => {
  const date=new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString().replace('T',' ').replace('.000Z',' UTC') : 'Not supplied';
};
const value = n => n!==null && n!==undefined && n!=='' && Number.isFinite(Number(n)) ? Number(n).toFixed(2) : 'Not supplied';
const flags = row => [['soFlag','SO'],['storFlag','STOR'],['rrFlag','RR'],['deemedBoFlag','Deemed']].filter(([key])=>row[key]===true).map(([,label])=>label).join(', ') || 'None';
export function instructionTitle(s) {
  return `Instruction ${instructionId(s)} · issued ${time(s.row.acceptanceTime)} · ${time(s.row.timeFrom)} to ${time(s.row.timeTo)} · ${value(s.row.levelFrom)} → ${value(s.row.levelTo)} MW · Flags: ${flags(s.row)}`;
}

export function mountBalancingDetails(container, data, onSelect) {
  const {acceptances,bidOffers,acceptancesAvailable,bidOffersAvailable}=data;
  const ids=[...new Set(acceptances.map(instructionId))];
  container.innerHTML=`<details class="bmu-bm-details"><summary>Accepted instructions (${ids.length})</summary>
    <p>Individual instructed MW levels. Instructions can overlap or revise earlier instructions; traces are not combined into a final dispatch profile. No trace means no returned instruction, not zero output.</p>
    ${!acceptancesAvailable?'<p>Instruction data unavailable. Use Refresh to retry.</p>':!ids.length?'<p>No accepted instructions returned for this window.</p>':`<label>Highlight instruction <select aria-label="Highlight instruction"><option value="">All instructions</option>${ids.map(id=>`<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join('')}</select></label>
    <div class="bmu-table-scroll"><table><thead><tr><th>Instruction</th><th>Issued (UTC)</th><th>Effective (UTC)</th><th>Level (MW)</th><th>Flags</th></tr></thead><tbody>${acceptances.map(s=>`<tr><td><button type="button" data-instruction="${escapeHtml(instructionId(s))}">${escapeHtml(instructionId(s))}</button></td><td>${escapeHtml(time(s.row.acceptanceTime))}</td><td>${escapeHtml(time(s.row.timeFrom))}<br>to ${escapeHtml(time(s.row.timeTo))}</td><td>${value(s.row.levelFrom)} → ${value(s.row.levelTo)}</td><td>${flags(s.row)}</td></tr>`).join('')}</tbody></table></div>`}</details>
    <details class="bmu-bm-details"><summary>Submitted bid/offer prices</summary><p>Pair levels are MW relative to PN. Bid and offer prices are £/MWh; these are submissions, not accepted volumes or payments. Settlement date and period use GB market time; interval timestamps below are UTC.</p>
    ${!bidOffersAvailable?'<p>Bid/offer data unavailable. Use Refresh to retry.</p>':!bidOffers.length?'<p>No submitted bid/offer data returned for this window.</p>':'<label>Settlement period <select aria-label="Bid offer settlement period"></select></label><div class="bmu-bod-table bmu-table-scroll"></div>'}</details>`;
  const instructionSelect=container.querySelector('select[aria-label="Highlight instruction"]');
  if(instructionSelect) {
    instructionSelect.onchange=()=>onSelect(instructionSelect.value);
    for(const button of container.querySelectorAll('[data-instruction]'))button.onclick=()=>{instructionSelect.value=button.dataset.instruction;onSelect(instructionSelect.value);};
  }
  const periodSelect=container.querySelector('select[aria-label="Bid offer settlement period"]');
  if(periodSelect) {
    periodSelect.replaceChildren(...bidOffers.map((period,index)=>new Option(period.label,String(index))));
    periodSelect.value=String(bidOffers.length-1);
    const render=()=>{
      const entries=bidOffers[Number(periodSelect.value)].entries;
      container.querySelector('.bmu-bod-table').innerHTML=`<table><thead><tr><th>Pair</th><th>Interval (UTC)</th><th>Level from → to (MW relative to PN)</th><th>Bid (£/MWh)</th><th>Offer (£/MWh)</th></tr></thead><tbody>${entries.map(row=>`<tr><td>${escapeHtml(row.pairId)}</td><td>${escapeHtml(time(row.timeFrom))}<br>to ${escapeHtml(time(row.timeTo))}</td><td>${value(row.levelFrom)} → ${value(row.levelTo)}</td><td>${value(row.bid)}</td><td>${value(row.offer)}</td></tr>`).join('')}</tbody></table>`;
    };
    periodSelect.onchange=render;render();
  }
}

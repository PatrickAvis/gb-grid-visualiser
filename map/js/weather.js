import {fetchWeather,weatherAt,weatherTimeLabel,weatherNumber} from './weatherData.js';
import {createWindField,windVector} from './windField.js';
import {createWindCanvas} from './windCanvas.js';
import {escapeHtml as esc} from './utils.js';
let selectedTime=null;
const attribution='<a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Weather by Open-Meteo</a> · CC BY 4.0';
const format=(v,unit)=>v==null?'Unavailable':`${v.toFixed(1)} ${unit}`;
function changeTime(time){selectedTime=time;document.dispatchEvent(new CustomEvent('weather-time-change'));}

export function installWindWeather(map) {
  const section=document.createElement('details');section.className='layer-group wind-weather';section.open=true;
  section.innerHTML=`<summary>Wind & weather</summary><label><input type="checkbox" id="wind-enabled"> Wind speed & animated flows</label>
    <label>Height <select aria-label="Wind height"><option value="120">120 m</option><option value="10">10 m</option></select></label>
    <label>Forecast <input type="range" min="0" max="48" value="0" disabled aria-label="Wind forecast hour"></label><output></output>
    <label>Opacity <input type="range" min="20" max="100" value="80" aria-label="Wind opacity"></label><button type="button" disabled>Refresh weather</button><label><input type="checkbox" class="wind-pause"> Pause animation</label>
    <p role="status">Enable to fetch a 48-hour forecast.</p><div class="wind-speed-legend" aria-label="Wind speed colour scale in metres per second"><div></div><span>0</span><span>5</span><span>10</span><span>15</span><span>20</span><span>30 m/s</span></div>
    <p>Trails move downwind; colour shows speed. Covers the nearby Atlantic and north-west Europe (44–66° N, 20° W–16° E). Samples are 1° around GB and 2° farther out. Animation speed is illustrative. Not turbine measurements or power output. ${attribution}</p>`;
  document.getElementById('layer-list').prepend(section);
  const enabled=section.querySelector('#wind-enabled'),height=section.querySelector('select'),slider=section.querySelector('[aria-label="Wind forecast hour"]'),opacity=section.querySelector('[aria-label="Wind opacity"]'),refresh=section.querySelector('button'),status=section.querySelector('[role=status]'),output=section.querySelector('output');
  const canvas=createWindCanvas(map);canvas.setOpacity(0.8);let controller=null,data=null,times=[];
  // Retain the existing GB detail while extending coverage without a full dense
  // European grid. The field interpolator supports unequal coordinate spacing.
  const latitudes=[44,46,48,...Array.from({length:13},(_,i)=>50+i),64,66];
  const longitudes=[-20,-18,-16,-14,-12,-10,...Array.from({length:11},(_,i)=>-8+i),4,6,8,10,12,14,16];
  const points=latitudes.flatMap(lat=>longitudes.map(lon=>({lat,lon})));
  function render(){
    canvas.setField(null);if(!data || !enabled.checked)return;
    const time=times[Number(slider.value)];changeTime(time);output.textContent=weatherTimeLabel(time);
    const vectors=data.rows.map(row=>{
      const values=weatherAt(row,time);
      return windVector(values[`wind_speed_${height.value}m`],values[`wind_direction_${height.value}m`]);
    });
    canvas.setField(createWindField(points,vectors));
  }

  async function load(force=false){
    controller?.abort();const current=new AbortController();controller=current;
    const timer=setTimeout(()=>current.abort(new Error('Weather request timed out')),45000);
    data=null;canvas.setField(null);slider.disabled=true;refresh.disabled=true;output.textContent='';changeTime(null);status.textContent='Fetching wind forecast…';
    try{
      const result=await fetchWeather(points,current.signal,force);
      if(controller!==current || !enabled.checked)return;
      data=result;
      times=result.rows[0].hourly.time.map(t=>t*1000).filter(t=>result.rows.every(r=>r.hourly.time.includes(t/1000))).slice(0,49);
      if(!times.length)throw new Error('No common forecast hours');
      slider.max=times.length-1;slider.value=0;slider.disabled=false;
      status.textContent=`Hourly forecast · fetched ${weatherTimeLabel(result.fetchedAt)}. Smoothed 1–2° samples across the nearby Atlantic and north-west Europe; zooming does not add forecast detail.`;render();
    }catch(error){if(controller===current && enabled.checked){data=null;status.textContent=`Weather unavailable: ${error.message}. Refresh to retry.`;}}
    finally{clearTimeout(timer);if(controller===current)refresh.disabled=!enabled.checked;}
  }
  enabled.onchange=()=>{if(enabled.checked){load();}else{controller?.abort();controller=null;canvas.setField(null);slider.disabled=true;refresh.disabled=true;output.textContent='';status.textContent='Wind overlay off.';changeTime(null);}};
  slider.oninput=render;height.onchange=render;opacity.oninput=()=>canvas.setOpacity(Number(opacity.value)/100);section.querySelector('.wind-pause').onchange=event=>canvas.setPaused(event.target.checked);refresh.onclick=()=>load(true);
  return {destroy(){controller?.abort();controller=null;canvas.destroy();section.remove();changeTime(null);}};
}

export function mountAssetWeather(overview) {
  const anchor=overview.querySelector('[data-weather-lat]');
  if(!anchor)return ()=>{};
  const lat=weatherNumber(anchor.dataset.weatherLat),lon=weatherNumber(anchor.dataset.weatherLon);
  if(lat==null || lon==null || Math.abs(lat)>90 || Math.abs(lon)>180)return ()=>{};
  const box=document.createElement('section');box.className='asset-weather';
  box.innerHTML='<h2>Weather forecast</h2><button type="button">Refresh weather</button><p role="status">Loading weather…</p><div class="weather-values"></div><details><summary>Hourly forecast · next 48 hours</summary><div class="weather-hours"></div></details>';
  overview.insertBefore(box,overview.querySelector('.asset-satellite'));
  const status=box.querySelector('[role=status]'),values=box.querySelector('.weather-values'),hours=box.querySelector('.weather-hours'),button=box.querySelector('button');
  let controller=null,data=null;
  function render(){
    if(!data)return;
    const row=data.rows[0],time=selectedTime??row.hourly.time[0]*1000,v=weatherAt(row,time);
    values.innerHTML=`<p><b>${esc(weatherTimeLabel(time))}</b></p><dl><dt>Wind at 120 m</dt><dd>${format(v.wind_speed_120m,'m/s')} · from ${format(v.wind_direction_120m,'°')}</dd><dt>Wind at 10 m</dt><dd>${format(v.wind_speed_10m,'m/s')} · from ${format(v.wind_direction_10m,'°')}</dd><dt>Gusts at 10 m</dt><dd>${format(v.wind_gusts_10m,'m/s')}</dd><dt>Temperature at 2 m</dt><dd>${format(v.temperature_2m,'°C')}</dd><dt>Cloud cover</dt><dd>${format(v.cloud_cover,'%')}</dd></dl><p>Modelled conditions near the asset; heights above ground. Gusts refer to the preceding hour. Wind is not a prediction of electrical output. ${attribution}</p>`;
  }
  async function load(force=false){
    controller?.abort();const current=new AbortController();controller=current;const timer=setTimeout(()=>current.abort(new Error('Weather request timed out')),30000);
    data=null;values.replaceChildren();hours.replaceChildren();button.disabled=true;status.textContent='Loading weather…';
    try{
      const result=await fetchWeather([{lat,lon}],current.signal,force);
      if(controller!==current)return;data=result;
      status.textContent=`Fetched ${weatherTimeLabel(result.fetchedAt)}. Model grid point: ${result.rows[0].latitude.toFixed(3)}, ${result.rows[0].longitude.toFixed(3)}. Select wind-overlay time to inspect this forecast.`;
      hours.innerHTML='<table class="popup-table"><thead><tr><th>UTC</th><th>120 m wind (m/s)</th><th>From (°)</th><th>10 m gust (m/s)</th></tr></thead><tbody>'+result.rows[0].hourly.time.map(t=>{
        const v=weatherAt(result.rows[0],t*1000);return `<tr><td>${esc(weatherTimeLabel(t*1000))}</td><td>${format(v.wind_speed_120m,'')}</td><td>${format(v.wind_direction_120m,'')}</td><td>${format(v.wind_gusts_10m,'')}</td></tr>`;
      }).join('')+'</tbody></table>';render();
    }catch(error){if(controller===current)status.textContent=`Weather unavailable: ${error.message}. Refresh to retry.`;}
    finally{clearTimeout(timer);if(controller===current)button.disabled=false;}
  }
  button.onclick=()=>load(true);document.addEventListener('weather-time-change',render);load();
  return ()=>{controller?.abort();controller=null;document.removeEventListener('weather-time-change',render);};
}

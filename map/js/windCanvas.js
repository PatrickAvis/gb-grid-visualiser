import {windRgb} from './windField.js';

// Two non-interactive canvases below infrastructure: speed raster + particle trails.
export function createWindCanvas(map) {
  const pane=map.getPane('windWeather') || map.createPane('windWeather');
  pane.style.zIndex='350';pane.style.pointerEvents='none';
  const root=document.createElement('div');root.className='wind-canvas-layer leaflet-zoom-hide';root.style.pointerEvents='none';
  const raster=document.createElement('canvas'),trails=document.createElement('canvas');
  raster.className='wind-speed-canvas';trails.className='wind-flow-canvas';root.append(raster,trails);
  for(const canvas of [raster,trails]){canvas.style.position='absolute';canvas.setAttribute('aria-hidden','true');}
  let field=null,frame=0,particles=[],last=0,paused=false,attached=false,grid=[],cols=0,width=0,height=0;
  const step=8,reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  function sample(x,y){
    if(x<0||y<0||x>=width||y>=height)return null;
    return grid[Math.floor(y/step)*cols+Math.floor(x/step)];
  }
  function seed(){
    for(let i=0;i<30;i++){const x=Math.random()*width,y=Math.random()*height;if(sample(x,y))return {x,y,age:Math.random()*80};}
    return {x:0,y:0,age:100};
  }
  function stop(){cancelAnimationFrame(frame);frame=0;}
  function animate(now){
    if(!attached||paused||document.hidden||!field)return;
    frame=requestAnimationFrame(animate);if(now-last<32)return;
    const dt=Math.min((now-last)/1000,0.06);last=now;
    const ctx=trails.getContext('2d');ctx.globalCompositeOperation='destination-in';ctx.fillStyle='rgba(0,0,0,0.90)';ctx.fillRect(0,0,width,height);ctx.globalCompositeOperation='source-over';
    ctx.strokeStyle='rgba(255,255,255,0.85)';ctx.lineWidth=1.2;ctx.beginPath();
    for(let i=0;i<particles.length;i++){
      let p=particles[i];const v=sample(p.x,p.y);
      if(!v||p.age++>90){particles[i]=seed();continue;}
      // Display velocity is deliberately scaled, not a real-time air parcel track.
      const x=p.x+v.u*dt*2.6,y=p.y-v.v*dt*2.6;
      if(sample(x,y)){ctx.moveTo(p.x,p.y);ctx.lineTo(x,y);p.x=x;p.y=y;}else particles[i]=seed();
    }
    ctx.stroke();
  }
  function start(){stop();last=performance.now();if(!paused&&!document.hidden&&!reduced.matches&&field&&attached)frame=requestAnimationFrame(animate);}
  function redraw(){
    stop();if(!attached)return;
    L.DomUtil.setPosition(root,map.containerPointToLayerPoint([0,0]));
    const size=map.getSize();width=size.x;height=size.y;
    for(const c of [raster,trails]){c.width=width;c.height=height;}
    grid=[];if(!field)return;
    cols=Math.ceil(width/step);const rows=Math.ceil(height/step),small=document.createElement('canvas');small.width=cols;small.height=rows;
    const ctx=small.getContext('2d'),pixels=ctx.createImageData(cols,rows);
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
      const ll=map.containerPointToLatLng([x*step+step/2,y*step+step/2]),v=field(ll.lat,ll.lng),i=y*cols+x;grid[i]=v;
      if(v){const rgb=windRgb(v.speed);pixels.data.set([...rgb,180],i*4);}
    }
    ctx.putImageData(pixels,0,0);raster.getContext('2d').drawImage(small,0,0,width,height);
    particles=Array.from({length:Math.min(2200,Math.round(width*height/600))},seed);start();
  }
  function moving(){stop();root.style.visibility='hidden';}
  function moved(){root.style.visibility='';redraw();}
  function visibility(){start();}
  map.on('movestart zoomstart',moving);map.on('moveend resize',moved);document.addEventListener('visibilitychange',visibility);reduced.addEventListener('change',visibility);
  return {
    setField(value){field=value;if(value&&!attached){pane.append(root);attached=true;}if(!value){stop();root.remove();attached=false;grid=[];}else redraw();},
    setOpacity(value){root.style.opacity=String(value);},
    setPaused(value){paused=value;start();},
    destroy(){stop();root.remove();attached=false;map.off('movestart zoomstart',moving);map.off('moveend resize',moved);document.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',visibility);},
  };
}

"""Probe-only reader and pure scorers for the Magic Move texture feed."""
from __future__ import annotations

import math
import statistics
from typing import Any, Iterable

READ_PROGRESS = (0.25, 0.5, 0.75)
# Provisional: run2-cmp/direct used the experiment reference (fixed 16x16 staging-canvas centre), so it cannot register the floor; dP 1.36/2.44 were weak separations; re-bank from Phase 0 headless captures with this instrument.
ALPHA_POSTER_FLOOR = 2.5
LABEL_SPREAD_FLOOR = 24.0
LABEL_SLOPE_TOLERANCE = 0.02
RIDER_OPACITY_FLOOR = 0.02
# Provisional paint-coverage limit: re-bank from Phase 0 callback/upload gaps with this instrument.
MAX_INTER_FEED_GAP_MS = 50.0
# Provisional: covers the measured cold-start prefixes (max 315 ms); tighten after the deck-load warm-up.
PRE_DRAW_GRACE_MS = 320.0
SOURCE_RECT_TOLERANCE_PX = 1.0
# Provisional: re-bank from Phase 0 headless captures alongside ALPHA_POSTER_FLOOR.
ALPHA_HOLD_MARGIN = 6.0
# Provisional: re-bank from Phase 0 headless captures alongside ALPHA_POSTER_FLOOR.
COUNTER_HOLD_MARGIN = 1.0


INSTRUMENT_JS = r"""
(function(){
  'use strict';
  if(window.__obedMmFeedProbe)return;
  var READS=[0.25,0.5,0.75],PATCH_UV=[[0.2,0.2],[0.5,0.2],[0.8,0.2],[0.2,0.5],[0.5,0.5],[0.8,0.5],[0.2,0.8],[0.5,0.8],[0.8,0.8]];
  var S={config:null,entries:[],contexts:[],live:[],frames:[],browserFrames:[],handbacks:[],media:[],mediaOverflow:0,artwork:[],errors:[],tamper:null,killedOnce:[],forcedDecoders:{},uploads:[],claims:[],standDowns:[],departures:[],costs:[]};
  var originalGetContext=HTMLCanvasElement.prototype.getContext;
  var locationName=new WeakMap(),programUniforms=new WeakMap(),textureInfo=new WeakMap();
  var decoderState=new WeakMap(),entryState={},decoderGeneration=0,media=HTMLMediaElement.prototype,originalPause=media.pause,originalPlay=media.play;
  function finite(v){return typeof v==='number'&&isFinite(v)}
  function frameTime(){var t=document.timeline&&document.timeline.currentTime;return finite(t)?t:null}
  function browserFrame(t){
    if(!finite(t))return null;var last=S.browserFrames[S.browserFrames.length-1];
    if(last&&last.timestamp===t)return last.index;
    var row={index:S.browserFrames.length,timestamp:t};S.browserFrames.push(row);return row.index;
  }
  function noteError(where,e){if(S.errors.length<50)S.errors.push({where:where,error:String(e&&e.stack||e)})}
  function scene(){
    var n=parseInt(String(location.hash||'').replace(/^#/,''),10);return Number.isInteger(n)?n:null;
  }
  function moduleRead(){
    var api=window.__OBED_MM_FEED__;
    if(!api)return null;
    try{return typeof api.report==='function'?api.report():JSON.parse(JSON.stringify(api));}
    catch(e){return {error:String(e)}}
  }
  function decoderFor(objectId){
    if(S.forcedDecoders[objectId])return S.forcedDecoders[objectId];
    var seam=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed;
    try{return seam&&typeof seam.decoderFor==='function'?seam.decoderFor(objectId):null}catch(e){return null}
  }
  function decoderForEntry(entry){
    var state=entryState[entry.id],v=state&&state.decoder;
    if(v&&(sameId(v.__obedInstance,entry.objectId)||sameId(v.__obedInstance,entry.dstObjectId)))return v;
    v=decoderFor(entry.planObjectId);
    if(!v&&entry.planDstObjectId)v=decoderFor(entry.planDstObjectId);
    if(v)armDecoder(v,entry);
    return v;
  }
  function decoderRead(entry){
    var v=decoderForEntry(entry);
    var r=v&&v.getBoundingClientRect?v.getBoundingClientRect():null;
    return v?{objectId:entry.objectId,instance:v.__obedInstance==null?null:String(v.__obedInstance),elId:v.__obedElId==null?null:v.__obedElId,currentTime:v.currentTime,
      paused:!!v.paused,readyState:v.readyState,presentedFrames:v.__obedPresentedFrames==null?null:v.__obedPresentedFrames,
      mediaTime:v.__obedMediaTime==null?null:v.__obedMediaTime,opacityProduct:opacityProduct(v),visible:visible(v),
      rect:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null}:null;
  }
  function moveFor(v){var state=decoderState.get(v);return state&&state.move||null}
  function mediaEvent(kind,v,extra){
    var move=moveFor(v),state=decoderState.get(v),current=scene();
    if(kind==='pause'&&v.__obedPosterHeld&&!(move&&move.atScene===current+1)){var pendingMoves=entries().filter(function(e){return e.atScene===current+1&&
        (sameId(v.__obedInstance,e.objectId)||sameId(v.__obedInstance,e.dstObjectId))});
      if(pendingMoves.length===1){var next=entryState[pendingMoves[0].id]||{};move={serial:null,atScene:pendingMoves[0].atScene,
        entryId:pendingMoves[0].id,objectId:pendingMoves[0].objectId,generation:state&&state.generation,visit:(next.visit||0)+1}}
      else if(pendingMoves.length>1)move={serial:null,atScene:current+1,entryId:null,generation:state&&state.generation,visit:null}}
    if(move&&move.atScene!==current&&move.atScene!==current+1)move=null;
    if(!move){var candidates=entries().filter(function(e){return (e.atScene===current||e.atScene===current+1)&&
        (sameId(v.__obedInstance,e.objectId)||sameId(v.__obedInstance,e.dstObjectId))});
      if(candidates.length===1){var pending=entryState[candidates[0].id]||{};move={serial:null,atScene:candidates[0].atScene,
        entryId:candidates[0].id,generation:state&&state.generation,visit:(pending.visit||0)+(current===candidates[0].atScene-1?1:0)}}}
    if(!move)return;if(S.media.length>=20000){S.mediaOverflow++;return}
    S.media.push(Object.assign({kind:kind,t:performance.now(),serial:move.serial,atScene:move.atScene,entryId:move.entryId,
      generation:move.generation==null&&state?state.generation:move.generation,visit:move.visit==null?(entryState[move.entryId]||{}).visit:move.visit,
      instance:v.__obedInstance==null?null:String(v.__obedInstance),elId:v.__obedElId==null?null:v.__obedElId,
      currentTime:v.currentTime,paused:!!v.paused,presentedFrames:v.__obedPresentedFrames==null?null:v.__obedPresentedFrames,
      mediaTime:v.__obedMediaTime==null?null:v.__obedMediaTime},extra||{}));
    if(kind==='pause'&&v.__obedPosterHeld&&move.entryId)S.departures.push({t:performance.now(),serial:move.serial,atScene:move.atScene,entryId:move.entryId,
      objectId:move.objectId||null,generation:move.generation==null&&state?state.generation:move.generation,
      visit:move.visit==null?(entryState[move.entryId]||{}).visit:move.visit});
  }
  media.pause=function(){mediaEvent('pause',this);return originalPause.apply(this,arguments)};
  media.play=function(){mediaEvent('play',this);return originalPlay.apply(this,arguments)};
  function armDecoder(v,entry){
    var state=decoderState.get(v);
    if(!state){state={entries:{},move:null,generation:++decoderGeneration};decoderState.set(v,state)}
    state.entries[entry.id]=entry;entryState[entry.id]=entryState[entry.id]||{ring:[]};entryState[entry.id].decoder=v;
    if(state.armed)return;state.armed=true;
    v.addEventListener('seeking',function(){mediaEvent('seeking',v)},true);
    if(typeof v.requestVideoFrameCallback==='function'){
      var callback=function(now,meta){var costStart=performance.now();v.__obedPresentedFrames=meta.presentedFrames;v.__obedMediaTime=meta.mediaTime;
        mediaEvent('videoFrame',v,{now:now,presentedFrames:meta.presentedFrames,mediaTime:meta.mediaTime});
        Object.keys(state.entries).forEach(function(id){var e=state.entries[id],size=entryState[id].leafSize||e.feed&&e.feed.from&&e.feed.from.size;
          if(scene()===e.atScene){var dom=domRead(v,e),stamp=frameTime(),domFrame={now:now,t:performance.now(),frameIndex:browserFrame(stamp),
            frameTimestamp:stamp,mediaTime:meta.mediaTime,presentedFrames:meta.presentedFrames,dom:dom};
            var domFrames=entryState[id].domFrames;domFrames.push(domFrame);if(domFrames.length>12)domFrames.shift();
            S.handbacks.forEach(function(handback){if(handback.entryId===id&&handback.decoder===v&&!handback.complete&&!handback.timedOut&&domFrame.frameIndex>=handback.closedFrameIndex){
              handback.frames.push(domFrame);if(handback.frames.length>=3)handback.complete=true}})}
          var current=scene(),move=state.move,moveLive=move&&move.entryId===id&&S.live.some(function(pair){return pair[1].serial===move.serial&&pair[1].frame});if(!size||!(current===e.atScene-1||moveLive))return;try{var ring=entryState[id].ring;ring.push({frame:meta.presentedFrames,mediaTime:meta.mediaTime,patches:capture(v,size,entryState[id])});if(ring.length>18)ring.shift()}catch(x){noteError('rVFC capture',x)}});
        S.costs.push(performance.now()-costStart);if(S.costs.length>1000)S.costs.shift();
        v.requestVideoFrameCallback(callback)};v.requestVideoFrameCallback(callback);
    }
  }
  function opacityProduct(el){var o=1;for(var n=el;n&&n.nodeType===1;n=n.parentElement)o*=+(getComputedStyle(n).opacity||0);return o}
  function visible(el){
    if(!el||!el.isConnected)return false;
    var s=getComputedStyle(el),r=el.getBoundingClientRect();
    return s.display!=='none'&&s.visibility==='visible'&&r.width>0&&r.height>0&&(!el.checkVisibility||el.checkVisibility({opacityProperty:true,visibilityProperty:true}));
  }
  function sourceRectError(entry,v){try{var q=entry&&entry.srcRect;if(!q||!finite(q.x)||!finite(q.y)||!finite(q.w)||!finite(q.h)||!(q.w>0&&q.h>0))return null;var stage=document.getElementById('stage'),ow=stage&&stage.offsetWidth,oh=stage&&stage.offsetHeight;if(!stage||!finite(ow)||!finite(oh)||!(ow>1&&oh>1))return null;var sr=stage.getBoundingClientRect();if(!sr||!finite(sr.left)||!finite(sr.top)||!finite(sr.width)||!finite(sr.height)||!(sr.width>1&&sr.height>1))return null;var sx=sr.width/ow,sy=sr.height/oh,avg=(sx+sy)/2;if(!finite(sx)||!finite(sy)||!(sx>0&&sy>0&&avg>0)||Math.abs(sx-sy)/avg>0.001)return null;var r=v&&v.getBoundingClientRect?v.getBoundingClientRect():null;if(!r||!finite(r.left)||!finite(r.top)||!finite(r.right)||!finite(r.bottom)||!finite(r.width)||!finite(r.height)||!(r.width>0&&r.height>0))return null;var L=sr.left+q.x*sx,T=sr.top+q.y*sx,R=sr.left+(q.x+q.w)*sx,B=sr.top+(q.y+q.h)*sx;if(!finite(L)||!finite(T)||!finite(R)||!finite(B))return null;var error=Math.max(Math.abs(r.left-L),Math.abs(r.top-T),Math.abs(r.right-R),Math.abs(r.bottom-B))/sx;return finite(error)?error:null}catch(e){return null}}
  function stageMap(){var stage=document.getElementById('stage');if(!stage||!(stage.offsetWidth>1))return null;var r=stage.getBoundingClientRect();return {stage:stage,s:r.width/stage.offsetWidth,ox:r.left,oy:r.top}}
  function expectedBox(entry,v){var m=stageMap(),r=entry&&entry.dstRect;if(m&&r)return {stage:m.stage,x:m.ox+r.x*m.s,y:m.oy+r.y*m.s,w:r.w*m.s,h:r.h*m.s,s:m.s};
    var vr=v&&v.getBoundingClientRect?v.getBoundingClientRect():null;return vr&&m?{stage:m.stage,x:vr.left,y:vr.top,w:vr.width,h:vr.height,s:m.s}:null}
  function commonParent(a,b){var seen=[];for(var n=a;n;n=n.parentNode)seen.push(n);for(var q=b;q;q=q.parentNode)if(seen.indexOf(q)>=0)return q;return null}
  function plainStack(node,top){for(var n=node;n&&n!==top;n=n.parentElement){var s=getComputedStyle(n);if(s.position!=='static'&&s.zIndex!=='auto'&&s.zIndex!=='0')return false}return true}
  function domRead(v,entry){
    var box=expectedBox(entry,v),stage=box&&box.stage,r=v&&v.getBoundingClientRect?v.getBoundingClientRect():null;
    if(!v||!box||!r)return null;var canvases=[],pos=10*box.s,size=16*box.s;
    stage.querySelectorAll('canvas').forEach(function(c){if(/^\d+-canvas$/.test(String(c.id||'')))return;var cr=c.getBoundingClientRect();
      if(Math.abs(cr.left-box.x)<=pos&&Math.abs(cr.top-box.y)<=pos&&Math.abs(cr.width-box.w)<=size&&Math.abs(cr.height-box.h)<=size&&visible(c))canvases.push(c)});
    var after=canvases.length?canvases.every(function(c){return !!(c.compareDocumentPosition(v)&Node.DOCUMENT_POSITION_FOLLOWING)}):null;
    var same=canvases.length?canvases.every(function(c){var top=commonParent(c,v);return !!top&&plainStack(c,top)&&plainStack(v,top)}):null;
    return {connected:!!v.isConnected,inStage:!!stage.contains(v),onBody:!!(v.parentElement&&v.parentElement===document.body),
      opacityProduct:opacityProduct(v),shown:visible(v),canvasCount:canvases.length,afterCanvas:after,sameStackingContext:same,
      rectError:Math.max(Math.abs(r.left-box.x),Math.abs(r.top-box.y),Math.abs(r.width-box.w),Math.abs(r.height-box.h))};
  }
  function entries(){return S.entries}
  // Facts carry lowercased objectIds; the plan, core seam and player use the export's spelling.
  function sameId(a,b){return typeof a==='string'&&typeof b==='string'&&a.toLowerCase()===b.toLowerCase()}
  function planRow(entry){
    var plan=window.__OBED_CONTINUITY__,rows=plan&&Array.isArray(plan.boundaries)?plan.boundaries:[];
    var found=rows.filter(function(row){return row&&row.atScene===entry.atScene&&row.src&&sameId(row.src.objectId,entry.objectId)&&
      (!entry.dstObjectId||row.dst&&sameId(row.dst.objectId,entry.dstObjectId))});
    return found.length===1?found[0]:null;
  }
  function entriesAt(atScene){return entries().filter(function(e){return e.atScene===atScene})}
  function resolveAtScene(){
    var current=scene(),candidates=[current==null?null:current+1,current];
    for(var i=0;i<candidates.length;i++)if(entriesAt(candidates[i]).length)return candidates[i];
    return null;
  }
  function project(m,W,H,x,y){
    var cx=m[0]*x+m[4]*y+m[12],cy=m[1]*x+m[5]*y+m[13],cw=m[3]*x+m[7]*y+m[15];
    return [((cx/cw)+1)/2*W,((cy/cw)+1)/2*H];
  }
  function quad(m,W,H,size){return [project(m,W,H,0,0),project(m,W,H,size[0],0),project(m,W,H,size[0],size[1]),project(m,W,H,0,size[1])]}
  function bounds(points,W,H,grow){
    var xs=points.map(function(p){return p[0]}),ys=points.map(function(p){return p[1]});
    grow=grow||0;var x0=Math.max(0,Math.floor(Math.min.apply(null,xs)-grow)),x1=Math.min(W,Math.ceil(Math.max.apply(null,xs)+grow));
    var y0=Math.max(0,Math.floor(Math.min.apply(null,ys)-grow)),y1=Math.min(H,Math.ceil(Math.max.apply(null,ys)+grow));
    return {x:x0,y:y0,w:Math.max(0,x1-x0),h:Math.max(0,y1-y0)};
  }
  function area(poly){var out=0;for(var i=0;i<poly.length;i++){var a=poly[i],b=poly[(i+1)%poly.length];out+=a[0]*b[1]-b[0]*a[1]}return out/2}
  function insideGrow(point,poly,grow){
    if(!poly||poly.length!==4)return false;var sign=area(poly)>=0?1:-1;
    for(var i=0;i<4;i++){var a=poly[i],b=poly[(i+1)%4],dx=b[0]-a[0],dy=b[1]-a[1],cross=sign*(dx*(point[1]-a[1])-dy*(point[0]-a[0]));
      if(cross < -grow*Math.sqrt(dx*dx+dy*dy))return false}return true;
  }
  function overlapsGrow(a,b,grow){
    var polys=[a,b];for(var p=0;p<polys.length;p++)for(var i=0;i<polys[p].length;i++){var x=polys[p][i],y=polys[p][(i+1)%polys[p].length],nx=-(y[1]-x[1]),ny=y[0]-x[0],n=Math.sqrt(nx*nx+ny*ny);if(!n)continue;nx/=n;ny/=n;
      var aa=a.map(function(q){return q[0]*nx+q[1]*ny}),bb=b.map(function(q){return q[0]*nx+q[1]*ny});if(Math.max.apply(null,aa)<Math.min.apply(null,bb)-grow||Math.max.apply(null,bb)+grow<Math.min.apply(null,aa))return false}return true;
  }
  function pixelPatch(gl,b){if(!b||b.w<1||b.h<1)return null;var px=new Uint8Array(b.w*b.h*4);
    gl.readPixels(b.x,b.y,b.w,b.h,gl.RGBA,gl.UNSIGNED_BYTE,px);return {rect:b,pixels:px}}
  function meanAt(px,w,h,x,y,r){
    var out=[0,0,0],n=0;for(var yy=Math.max(0,Math.floor(y-r));yy<=Math.min(h-1,Math.ceil(y+r));yy++)for(var xx=Math.max(0,Math.floor(x-r));xx<=Math.min(w-1,Math.ceil(x+r));xx++){
      var i=(yy*w+xx)*4;out[0]+=px[i];out[1]+=px[i+1];out[2]+=px[i+2];n++}return n?[out[0]/n,out[1]/n,out[2]/n]:null;
  }
  function keyFor(uv){return uv[0]+','+uv[1]}
  function capture(source,size,state){
    if(!source||!size||!size[0]||!size[1])return null;state=state||{};var c=state.captureCanvas;
    if(!c){c=state.captureCanvas=document.createElement('canvas');c.width=81;c.height=30;state.captureContext=c.getContext('2d',{willReadFrequently:true})}
    var ctx=state.captureContext,iw=source.videoWidth||source.naturalWidth||source.width,ih=source.videoHeight||source.naturalHeight||source.height;
    if(!iw||!ih)return null;ctx.clearRect(0,0,81,30);PATCH_UV.forEach(function(uv,i){var sx=Math.max(0,uv[0]*iw-12*iw/size[0]),sy=Math.max(0,uv[1]*ih-12*ih/size[1]),sw=Math.min(24*iw/size[0],iw-sx),sh=Math.min(24*ih/size[1],ih-sy);ctx.drawImage(source,sx,sy,sw,sh,i*9,0,9,9)});
    for(var j=0;j<17;j++){var x=(24+40*j)/1920*iw,y=24/540*ih,rx=3*iw/size[0],ry=3*ih/size[1];ctx.drawImage(source,Math.max(0,x-rx),Math.max(0,y-ry),2*rx,2*ry,j,27,1,1)}
    var px=ctx.getImageData(0,0,81,30).data,vectors={};PATCH_UV.forEach(function(uv,i){var out=[];for(var y=0;y<3;y++)for(var x=0;x<3;x++){var m=meanAt(px,81,30,i*9+1+x*3,1+y*3,1);out=out.concat(m||[])}vectors[keyFor(uv)]=out.length===27?out:null});
    var values=[];for(var k=0;k<17;k++){var p=(27*81+k)*4;values.push((px[p]+px[p+1]+px[p+2])/3)}var lo=Math.min.apply(null,values),hi=Math.max.apply(null,values),cut=(lo+hi)/2,bits=values.map(function(v){return v>cut?1:0}),counter=null;
    if(hi-lo>=80&&bits[0]===1&&bits[1]===0&&bits[15]===0&&bits[16]===1){var n=0;for(var q=2;q<14;q++)n=n*2+bits[q];if(bits.slice(2,14).reduce(function(a,b){return a+b},0)%2===bits[14])counter=n}
    return {vectors:vectors,counter:counter};
  }
  function vectorFromGl(gl,m,layerSize,textureSize,uv,flip){
    var out=[],rx=8/textureSize[0],ry=8/textureSize[1];for(var y=-1;y<=1;y++)for(var x=-1;x<=1;x++){
      var lx=(uv[0]+x*rx)*layerSize[0],ly=(flip?1-(uv[1]+y*ry):uv[1]+y*ry)*layerSize[1],p=project(m,gl.drawingBufferWidth,gl.drawingBufferHeight,lx,ly);
      var b={x:Math.max(0,Math.round(p[0])-1),y:Math.max(0,Math.round(p[1])-1),w:3,h:3};b.w=Math.min(b.w,gl.drawingBufferWidth-b.x);b.h=Math.min(b.h,gl.drawingBufferHeight-b.y);
      var read=pixelPatch(gl,b);if(!read)return null;var q=meanAt(read.pixels,b.w,b.h,(b.w-1)/2,(b.h-1)/2,2);if(!q)return null;out=out.concat(q)}return out;
  }
  function counterFromGl(gl,m,size,flip){
    var values=[];for(var i=0;i<17;i++){var ux=(24+40*i)/1920,uy=24/540,lx=ux*size[0],ly=(flip?1-uy:uy)*size[1],p=project(m,gl.drawingBufferWidth,gl.drawingBufferHeight,lx,ly);
      var b={x:Math.max(0,Math.round(p[0])-1),y:Math.max(0,Math.round(p[1])-1),w:3,h:3};b.w=Math.min(3,gl.drawingBufferWidth-b.x);b.h=Math.min(3,gl.drawingBufferHeight-b.y);var read=pixelPatch(gl,b),q=read&&meanAt(read.pixels,b.w,b.h,1,1,2);if(!q)return null;values.push((q[0]+q[1]+q[2])/3)}
    var lo=Math.min.apply(null,values),hi=Math.max.apply(null,values),cut=(lo+hi)/2,bits=values.map(function(v){return v>cut?1:0});if(hi-lo<80||bits[0]!==1||bits[1]!==0||bits[15]!==0||bits[16]!==1)return null;
    var n=0;for(var k=2;k<14;k++)n=n*2+bits[k];return bits.slice(2,14).reduce(function(a,b){return a+b},0)%2===bits[14]?n:null;
  }
  function distance(a,b){if(!a||!b||a.length!==b.length)return null;var d=0;for(var i=0;i<a.length;i++)d+=Math.abs(a[i]-b[i]);return d/a.length}
  function safeUv(uv,m,layerSize,textureSize,flip,later,W,H,leafQuad){
    var rx=9/textureSize[0],ry=9/textureSize[1],points=[[-1,-1],[1,-1],[1,1],[-1,1]].map(function(p){return project(m,W,H,(uv[0]+p[0]*rx)*layerSize[0],(flip?1-(uv[1]+p[1]*ry):uv[1]+p[1]*ry)*layerSize[1])});
    var inside=points.every(function(p){return insideGrow(p,leafQuad,0)}),covered=later.some(function(q){return overlapsGrow(points,q,2)});
    return {inside:inside,covered:covered};
  }
  function labelStats(read,after,later){
    var before=read.under;if(!before||!after||before.pixels.length!==after.pixels.length)return null;
    var xs=[],ys=[],sx=0,sy=0,lo=255,hi=0,b=before.rect;
    for(var y=0;y<b.h;y++)for(var x=0;x<b.w;x++){var point=[b.x+x+.5,b.y+y+.5];if(!insideGrow(point,read.quad,-3)||later.some(function(q){return insideGrow(point,q,2)}))continue;
      var i=(y*b.w+x)*4;for(var c=0;c<3;c++){var a=before.pixels[i+c],z=after.pixels[i+c];xs.push(a);ys.push(z);sx+=a;sy+=z;lo=Math.min(lo,a);hi=Math.max(hi,a)}}
    if(!xs.length)return {entryId:read.entryId,serial:read.serial,atScene:read.atScene,opacity:read.opacity,spread:0,slope:null};
    var n=xs.length,mx=sx/n,my=sy/n,cov=0,v=0;for(var j=0;j<n;j++){cov+=(xs[j]-mx)*(ys[j]-my);v+=(xs[j]-mx)*(xs[j]-mx)}
    return {entryId:read.entryId,serial:read.serial,atScene:read.atScene,opacity:read.opacity,spread:hi-lo,slope:v?cov/v:null};
  }
  function wrap(gl,canvas){
    if(gl.__obedMmFeedProbe)return;
    gl.__obedMmFeedProbe=true;
    var atScene=resolveAtScene();S.live.forEach(function(pair){if(pair[1].frame)finishFrame(pair[0],pair[1])});
    var active=entriesAt(atScene),O={},G={unit:gl.TEXTURE0,bindings:{},program:null,flip:false,premultiply:false,
      frame:null,serial:S.contexts.length+1,regularUploads:0,atScene:atScene,entries:active,closed:false};
    ['texImage2D','activeTexture','bindTexture','pixelStorei','useProgram','getUniformLocation','uniform1f','uniformMatrix4fv','clear','drawArrays','drawElements'].forEach(function(n){O[n]=gl[n]});
    var contextRecord={serial:G.serial,id:canvas.id,createdAt:performance.now(),firstDrawAt:null,closedAt:null,closedFrameIndex:null,atScene:atScene,lost:false,entryIds:active.map(function(e){return e.id})};G.context=contextRecord;
    S.contexts.push(contextRecord);S.live.push([gl,G]);
    active.forEach(function(e){var es=entryState[e.id];es.visit=(es.visit||0)+1;es.serial=G.serial;
      [S.claims,S.standDowns].forEach(function(stream){stream.forEach(function(row){if(row.serial===null&&row.entryId===e.id&&row.atScene===atScene)row.serial=G.serial})});
      var v=decoderForEntry(e),ds=v&&decoderState.get(v);[S.media,S.departures].forEach(function(stream){stream.forEach(function(row){
        if(row.serial===null&&row.entryId===e.id&&row.atScene===atScene&&row.visit===es.visit&&ds&&row.generation===ds.generation)row.serial=G.serial})});
      if(v){armDecoder(v,e);decoderState.get(v).move={serial:G.serial,atScene:atScene,entryId:e.id,objectId:e.objectId,
        generation:decoderState.get(v).generation,visit:es.visit}}});
    gl.activeTexture=function(u){G.unit=u;return O.activeTexture.apply(gl,arguments)};
    gl.bindTexture=function(target,texture){if(target===gl.TEXTURE_2D)G.bindings[G.unit]=texture;return O.bindTexture.apply(gl,arguments)};
    gl.pixelStorei=function(p,v){if(p===gl.UNPACK_FLIP_Y_WEBGL)G.flip=!!v;if(p===gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL)G.premultiply=!!v;return O.pixelStorei.apply(gl,arguments)};
    gl.useProgram=function(p){G.program=p;return O.useProgram.apply(gl,arguments)};
    gl.getUniformLocation=function(p,n){var q=O.getUniformLocation.apply(gl,arguments);if(q)locationName.set(q,n);return q};
    function setUniform(loc,value){if(!G.program||!loc)return;var u=programUniforms.get(G.program)||{};u[locationName.get(loc)||'?']=value;programUniforms.set(G.program,u)}
    gl.uniform1f=function(loc,v){setUniform(loc,v);return O.uniform1f.apply(gl,arguments)};
    gl.uniformMatrix4fv=function(loc,tr,v){setUniform(loc,Array.prototype.slice.call(v,0,16));return O.uniformMatrix4fv.apply(gl,arguments)};
    gl.texImage2D=function(){
      var src=arguments.length<9?arguments[5]:null,w=arguments.length>=9?arguments[3]:src&&(src.videoWidth||src.width||src.naturalWidth),
          h=arguments.length>=9?arguments[4]:src&&(src.videoHeight||src.height||src.naturalHeight),texture=G.bindings[G.unit];
      var isVideo=!!(src&&((typeof HTMLVideoElement!=='undefined'&&src instanceof HTMLVideoElement)||(typeof VideoFrame!=='undefined'&&src instanceof VideoFrame)||typeof src.currentTime==='number'));
      if(G.frame)G.frame.uploads++;
      if(texture){var previous=textureInfo.get(texture)||{},poster=previous.poster,ordinal=previous.ordinal,size=previous.size;
        if(!isVideo){ordinal=++G.regularUploads;var planned=G.entries.filter(function(e){return [e.feed&&e.feed.from,e.feed&&e.feed.to].some(function(p){return p&&p.upload===ordinal})})[0];if(src&&planned)try{poster=capture(src,[w,h],entryState[planned.id])}catch(e){noteError('poster capture',e)}}
        if(!isVideo)size=[w,h];var info={serial:G.serial,ordinal:ordinal,size:size,uploadedSize:isVideo?[w,h]:null,flip:G.flip,premultiply:G.premultiply,poster:poster,video:isVideo,presentedFrames:src&&src.__obedPresentedFrames,mediaTime:src&&src.__obedMediaTime};textureInfo.set(texture,info);
        if(isVideo)S.uploads.push({serial:G.serial,atScene:G.atScene,t:performance.now(),frameN:G.frame&&G.frame.n,
          frameIndex:G.frame&&G.frame.frameIndex,frameTimestamp:G.frame&&G.frame.frameTimestamp,textureOrdinal:ordinal,
          presentedFrames:info.presentedFrames,mediaTime:info.mediaTime})}
      return O.texImage2D.apply(gl,arguments);
    };
    gl.clear=function(){
      if(G.frame){collectRiders(gl,G);finishFrame(gl,G)}
      var stamp=frameTime();G.frame={serial:G.serial,atScene:G.atScene,n:S.frames.length+1,t:performance.now(),frameTime:stamp,
        frameIndex:browserFrame(stamp),frameTimestamp:stamp,draws:0,uploads:0,rows:[],labels:[],riders:[],
        srcErr:{},quads:{},under:[],labelExpected:[],module:moduleRead(),pixelsDone:false};
      var result=O.clear.apply(gl,arguments);collectRiders(gl,G);return result;
    };
    function draw(name,args){
      if(!G.frame){var unframed=O[name].apply(gl,args);if(contextRecord.firstDrawAt===null)contextRecord.firstDrawAt=performance.now();return unframed}
      var F=G.frame,draw=++F.draws,u=G.program?(programUniforms.get(G.program)||{}):{},table=G.entries[0]&&G.entries[0].draws&&G.entries[0].draws.draws||[],drawFact=table.filter(function(r){return r.draw===draw})[0];
      if(drawFact&&u.MVPMatrix)F.quads[draw]=quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,drawFact.layerSize);
      if(drawFact&&finite(drawFact.labelBoxOpacity)&&F.quads[draw])G.entries.forEach(function(e){var fed=e.feed&&F.quads[e.feed.draw];if(!fed)return;
        var overlap=bounds(fed,gl.drawingBufferWidth,gl.drawingBufferHeight,0),lb=bounds(F.quads[draw],gl.drawingBufferWidth,gl.drawingBufferHeight,0);
        if(overlap.x>=lb.x+lb.w||lb.x>=overlap.x+overlap.w||overlap.y>=lb.y+lb.h||lb.y>=overlap.y+overlap.h)return;
        F.labelExpected.push({entryId:e.id,draw:draw});var b=bounds(F.quads[draw],gl.drawingBufferWidth,gl.drawingBufferHeight,4),under=pixelPatch(gl,b);if(under)F.under.push({entryId:e.id,serial:G.serial,atScene:G.atScene,
          draw:draw,opacity:drawFact.labelBoxOpacity,quad:F.quads[draw],under:under})});
      var textures=[0,1].map(function(unit){var tex=G.bindings[gl.TEXTURE0+unit],info=tex&&textureInfo.get(tex);return info?{unit:unit,ordinal:info.ordinal,size:info.size,uploadedSize:info.uploadedSize,
        video:info.video,presentedFrames:info.presentedFrames,mediaTime:info.mediaTime,_poster:info.poster,flip:info.flip}:null});
      var result=O[name].apply(gl,args);
      if(contextRecord.firstDrawAt===null)contextRecord.firstDrawAt=performance.now();
      G.entries.filter(function(e){return e.feed&&e.feed.draw===draw}).forEach(function(e){
        var layerSize=drawFact&&drawFact.layerSize,leafSize=textures[0]&&textures[0].size,points=u.MVPMatrix&&layerSize?quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,layerSize):null;
        var decoder=decoderRead(e),v=decoderForEntry(e),reference=null;try{if(v&&leafSize)reference=capture(v,leafSize,entryState[e.id])}catch(x){noteError('same-task reference',x)}
        if(leafSize)entryState[e.id].leafSize=leafSize.slice();
        F.rows.push({serial:G.serial,atScene:G.atScene,entryId:e.id,objectId:e.objectId,dstObjectId:e.dstObjectId,draw:draw,t:F.t,quad:points,_matrix:u.MVPMatrix?u.MVPMatrix.slice():null,_layerSize:layerSize,
          mixFactor:Object.prototype.hasOwnProperty.call(u,'mixFactor')?u.mixFactor:null,decoder:decoder,_reference:reference,
          textures:textures.map(function(t){return t?Object.assign({},t):null})});
      });
      var drawCount=G.entries[0]&&G.entries[0].draws&&G.entries[0].draws.drawCount;
      if(draw===drawCount)finalizePixels(gl,G,F);
      return result;
    }
    gl.drawArrays=function(){return draw('drawArrays',arguments)};
    gl.drawElements=function(){return draw('drawElements',arguments)};
    canvas.addEventListener('webglcontextlost',function(){contextRecord.lost=true;if(G.frame)finishFrame(gl,G)},true);
  }
  function laterQuads(F,draw){return Object.keys(F.quads).filter(function(k){return +k>draw}).map(function(k){return F.quads[k]})}
  function bestGeneric(gl,F,row){
    var tex=row.textures[0],textureSize=tex&&tex.size,layerSize=row._layerSize,m=row.quad&&row.quad.length===4&&F.quads[row.draw]?row._matrix:null;
    if(!tex||!textureSize||!layerSize||!m||!row._reference)return {patchInside:false,coveredByLaterDraw:false};
    var later=laterQuads(F,row.draw),best=null,anyInside=false,anyClear=false;
    PATCH_UV.forEach(function(uv){var safe=safeUv(uv,m,layerSize,textureSize,tex.flip,later,gl.drawingBufferWidth,gl.drawingBufferHeight,row.quad);if(!safe.inside)return;anyInside=true;if(safe.covered)return;anyClear=true;
      var key=keyFor(uv),video=row._reference.vectors[key],poster=tex._poster&&tex._poster.vectors[key],final=vectorFromGl(gl,m,layerSize,textureSize,uv,tex.flip),dSep=distance(video,poster);
      if(final&&video&&finite(dSep)&&(!best||dSep>best.dSep))best={uv:uv,final:final,video:video,poster:poster,dSep:dSep}});
    return best?{patchInside:true,coveredByLaterDraw:false,choice:best}:{patchInside:anyInside,coveredByLaterDraw:anyInside&&!anyClear};
  }
  function counterSafe(gl,F,row,m,size,flip){
    var later=laterQuads(F,row.draw),inside=true,covered=false;
    for(var i=0;i<17;i++){var ux=(24+40*i)/1920,uy=24/540,p=project(m,gl.drawingBufferWidth,gl.drawingBufferHeight,ux*size[0],(flip?1-uy:uy)*size[1]);
      inside=inside&&insideGrow(p,row.quad,0);covered=covered||later.some(function(q){return insideGrow(p,q,2)})}
    return {inside:inside,covered:covered};
  }
  function holdMatch(entry,row,choice){
    var candidates=(entryState[entry.id]&&entryState[entry.id].ring||[]).map(function(ref){return {frame:ref.frame,vector:choice&&ref.patches&&ref.patches.vectors[keyFor(choice.uv)]}}).filter(function(x){return x.vector});
    if(choice&&choice.poster)candidates.push({frame:0,vector:choice.poster});var scored=candidates.map(function(x){return {frame:x.frame,distance:distance(choice&&choice.final,x.vector)}}).filter(function(x){return finite(x.distance)}).sort(function(a,b){return a.distance-b.distance});
    return scored.length>=2?{kind:'alpha',bestFrame:scored[0].frame,matchDistance:scored[0].distance,matchMargin:scored[1].distance-scored[0].distance}:null;
  }
  function holdCounterMatch(entry,row,value){
    var candidates=(entryState[entry.id]&&entryState[entry.id].ring||[]).map(function(ref){return {frame:ref.frame,counter:ref.patches&&ref.patches.counter}}).filter(function(x){return Number.isInteger(x.counter)});
    var poster=row.textures[0]&&row.textures[0]._poster&&row.textures[0]._poster.counter;if(Number.isInteger(poster))candidates.push({frame:0,counter:poster});
    var scored=candidates.map(function(x){return {frame:x.frame,distance:Math.abs(value-x.counter)}}).sort(function(a,b){return a.distance-b.distance});
    return Number.isInteger(value)&&scored.length>=2?{kind:'counter',bestFrame:scored[0].frame,matchDistance:scored[0].distance,matchMargin:scored[1].distance-scored[0].distance}:null;
  }
  function finalizePixels(gl,G,F){
    if(F.pixelsDone)return;F.pixelsDone=true;
    F.rows.forEach(function(row){var entry=G.entries.filter(function(e){return e.id===row.entryId})[0],tex=row.textures[0],m=row._matrix;
      if(!entry||!tex||!m){row.feedRead={patchInside:false,coveredByLaterDraw:false,kind:null,late:true};delete row._reference;return}
      var counterSafeRead=counterSafe(gl,F,row,m,row._layerSize,tex.flip),counter=row._reference&&row._reference.counter;
      if(counter!==null&&counter!==undefined){var finalCounter=counterFromGl(gl,m,row._layerSize,tex.flip);row.feedRead={patchInside:counterSafeRead.inside,coveredByLaterDraw:counterSafeRead.covered,kind:'counter',
        counter:finalCounter,referenceCounter:counter};row.holdMatch=holdCounterMatch(entry,row,finalCounter)}
      else{var selected=bestGeneric(gl,F,row),choice=selected.choice;row.feedRead={patchInside:selected.patchInside,coveredByLaterDraw:selected.coveredByLaterDraw,kind:'alpha',
        dVideo:choice?distance(choice.final,choice.video):null,dPoster:choice?distance(choice.final,choice.poster):null,dSep:choice?choice.dSep:null};row.holdMatch=choice?holdMatch(entry,row,choice):null}
      delete row._reference;row.textures.forEach(function(t){if(t)delete t._poster});delete row._matrix;delete row._layerSize;
    });
    F.under.forEach(function(read){var after=pixelPatch(gl,read.under.rect),row=labelStats(read,after,laterQuads(F,read.draw));if(row)F.labels.push(row)});F.under=[];
    F.riders=[];collectRiders(gl,G);
  }
  function finishFrame(gl,G){
    var F=G.frame;if(!F)return;
    if(!F.pixelsDone){F.rows.forEach(function(row){row.feedRead={patchInside:false,coveredByLaterDraw:false,kind:null,late:true};row.holdMatch=null;delete row._reference;delete row._matrix;delete row._layerSize});F.under=[]}
    F.riders.forEach(function(row){row.sourceRectError=Object.prototype.hasOwnProperty.call(F.srcErr,row.entryId)?F.srcErr[row.entryId]:0});delete F.srcErr;
    F.glErrors=[];S.frames.push(F);G.frame=null;
  }
  function finishContext(G,stamp,index){
    if(G.closed)return;G.closed=true;stamp=finite(stamp)?stamp:frameTime();index=Number.isInteger(index)?index:browserFrame(stamp);
    if(G.context){G.context.closedAt=stamp;G.context.closedFrameIndex=index}
    G.entries.forEach(function(entry){var v=decoderForEntry(entry),uploads=S.uploads.filter(function(row){return row.serial===G.serial&&row.atScene===G.atScene});
      var prior=(entryState[entry.id].domFrames||[]).filter(function(row){return row.frameIndex>=index}).slice(0,3);
      S.handbacks.push({entryId:entry.id,serial:G.serial,atScene:G.atScene,entry:entry,decoder:v,closedAt:stamp,closedFrameIndex:index,
        closedDom:v?domRead(v,entry):null,frames:prior,complete:prior.length>=3,timedOut:false,deadline:performance.now()+1000,lastUpload:uploads.length?uploads[uploads.length-1]:null})});
    if(S.tamper&&S.tamper.kind==='after-feed'&&S.tamper.applied!==true&&G.atScene===S.tamper.atScene){S.tamper.failed=true;S.tamper.reason='target move context finished without a trigger'}
  }
  function installKillSwitch(){
    if(!S.config||!S.config.killHoldUpload)return;var api=window.__OBED_MM_FEED__;
    if(api&&typeof api.once==='function'&&!api.__obedProbeOnce){api.__obedProbeOnce=api.once;api.once=function(id){S.killedOnce.push({objectId:id,t:performance.now()});return false}}
  }
  HTMLCanvasElement.prototype.getContext=function(type){
    var gl=originalGetContext.apply(this,arguments);
    try{if(gl&&/^\d+-canvas$/.test(this.id)&&/webgl/.test(String(type)))wrap(gl,this)}catch(e){noteError('getContext',e)}
    return gl;
  };
  function configure(config){
    if(S.config)return true;
    S.config=config||{};S.tamper=S.config.tamper?{kind:S.config.tamper,atScene:Number.isInteger(S.config.tamperScene)?S.config.tamperScene:null,applied:false}:null;
    S.entries=(Array.isArray(S.config.entries)?S.config.entries:[]).map(function(source){var e=JSON.parse(JSON.stringify(source)),planned=JSON.stringify(e.feed),row=planRow(e),runtime=row&&row.feed&&typeof row.feed==='object'?JSON.parse(JSON.stringify(row.feed)):null;e.planObjectId=row?row.src.objectId:e.objectId;e.planDstObjectId=row&&row.dst?row.dst.objectId:e.dstObjectId;e.feed=runtime;if(S.tamper&&S.tamper.kind==='ordinal'&&(!Number.isInteger(S.tamper.atScene)||e.atScene===S.tamper.atScene)&&planned!==JSON.stringify(runtime))S.tamper.applied=true;return e});
    entries().forEach(function(e){entryState[e.id]={ring:[],domFrames:[],visit:0};var v=decoderFor(e.planObjectId);if(v)armDecoder(v,e)});
    S.live.forEach(function(pair){var G=pair[1],atScene=resolveAtScene(),active=entriesAt(atScene),context=S.contexts.filter(function(c){return c.serial===G.serial})[0];G.atScene=atScene;G.entries=active;if(context){context.atScene=atScene;context.entryIds=active.map(function(e){return e.id})}active.forEach(function(e){entryState[e.id].serial=G.serial;var v=decoderForEntry(e),ds=v&&decoderState.get(v);if(ds)ds.move={serial:G.serial,atScene:atScene,entryId:e.id,objectId:e.objectId,generation:ds.generation,visit:entryState[e.id].visit}})});
    installKillSwitch();
    if(S.tamper&&S.tamper.kind==='after-feed')requestAnimationFrame(afterFeedTamper);
    return true;
  }
  function bootstrap(config){
    if(window.__OBED_CONTINUITY__)return configure(config);var value;
    try{Object.defineProperty(window,'__OBED_CONTINUITY__',{configurable:true,get:function(){return value},set:function(plan){value=plan;Object.defineProperty(window,'__OBED_CONTINUITY__',{configurable:true,writable:true,value:plan});configure(config)}})}catch(e){noteError('bootstrap',e)}
    return true;
  }
  function afterFeedTamper(){
    if(!S.tamper||S.tamper.applied===true||S.tamper.failed===true)return;
    var target=S.live.filter(function(pair){var G=pair[1];return !G.closed&&(!Number.isInteger(S.tamper.atScene)||G.atScene===S.tamper.atScene)})[0],G=target&&target[1];
    if(!G){requestAnimationFrame(afterFeedTamper);return}
    var found=entries().filter(function(e){return S.tamper&&(!Number.isInteger(S.tamper.atScene)||e.atScene===S.tamper.atScene)&&S.uploads.some(function(u){return u.serial===G.serial&&u.atScene===e.atScene&&[e.feed&&e.feed.from,e.feed&&e.feed.to].some(function(p){return p&&p.upload===u.textureOrdinal})})})[0];found=found&&found.planObjectId;
    if(found){
      var v=decoderFor(found),start=v&&v.__obedPresentedFrames;
      if(v&&typeof v.requestVideoFrameCallback==='function')v.requestVideoFrameCallback(function(){
        if(!S.tamper||S.tamper.applied===true||S.tamper.failed===true||G.closed)return;
        var seam=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed,original=seam&&seam.decoderFor;
        S.forcedDecoders[found]=v;
        S.tamper.triggerPresented=v.__obedPresentedFrames;S.tamper.triggeredAt=performance.now();S.tamper.applied=true;
        if(typeof original==='function')seam.decoderFor=function(id){return id===found?null:original.call(seam,id)};
      });
      S.tamper=Object.assign({},S.tamper,{objectId:found,lastPresented:start,armedAt:performance.now()});return;
    }
    requestAnimationFrame(afterFeedTamper);
  }
  function entryForObject(objectId){
    var found=entries().filter(function(e){return sameId(e.objectId,objectId)}),current=scene(),next=found.filter(function(e){return e.atScene===current+1});
    if(next.length===1)return next[0];var here=found.filter(function(e){return e.atScene===current});if(here.length===1)return here[0];return found.length===1?found[0]:null;
  }
  function armSeam(){
    var feed=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed;if(!feed||feed.__obedMmFeedProbe)return;
    feed.__obedMmFeedProbe=true;var claim=feed.claim,stand=feed.onStandDown;
    if(typeof claim==='function')feed.claim=function(objectId){var result=claim.apply(feed,arguments),entry=entryForObject(objectId),v=decoderFor(objectId),move=v&&moveFor(v);S.claims.push({objectId:objectId,entryId:entry&&entry.id,serial:move&&entry&&move.atScene===entry.atScene?move.serial:null,atScene:entry&&entry.atScene,t:performance.now(),claimed:result===true});return result};
    if(typeof stand==='function')feed.onStandDown=function(objectId,reason){var v=decoderFor(objectId),move=v&&moveFor(v),result=stand.apply(feed,arguments),entry=entryForObject(objectId);S.standDowns.push({objectId:objectId,entryId:entry&&entry.id,serial:move&&entry&&move.atScene===entry.atScene?move.serial:null,atScene:entry&&entry.atScene,t:performance.now(),reason:reason==null?null:String(reason),accepted:result===true});return result};
  }
  function collectRiders(gl,G){var F=G.frame,canvas=gl.canvas;if(!F||G.closed||!canvas||!canvas.isConnected)return;var cr=canvas.getBoundingClientRect();
    G.entries.forEach(function(e){var v=decoderForEntry(e);if(v&&visible(v)){var x=sourceRectError(e,v),has=Object.prototype.hasOwnProperty.call(F.srcErr,e.id);if(!has)F.srcErr[e.id]=x;else if(F.srcErr[e.id]!==null)F.srcErr[e.id]=x===null?null:Math.max(F.srcErr[e.id],x)}if(F.riders.some(function(r){return r.entryId===e.id}))return;var d=decoderRead(e);if(d)F.riders.push({entryId:e.id,serial:G.serial,atScene:G.atScene,instance:d.instance,visible:d.visible,
      opacityProduct:d.opacityProduct,intersectsCanvas:!!(d.rect&&d.visible&&d.rect.x<cr.right&&d.rect.x+d.rect.w>cr.left&&d.rect.y<cr.bottom&&d.rect.y+d.rect.h>cr.top)})})}
  function riderTick(stamp){
    var frameStamp=frameTime(),index=browserFrame(frameStamp);armSeam();installKillSwitch();entries().forEach(function(e){decoderForEntry(e)});
    S.live.forEach(function(pair){collectRiders(pair[0],pair[1])});
    S.live.forEach(function(pair){var G=pair[1],canvas=pair[0].canvas;if(G.frame&&(!canvas||!canvas.isConnected||scene()!==G.atScene))finishFrame(pair[0],G);if(!canvas||!canvas.isConnected)finishContext(G,frameStamp,index)});
    S.handbacks.forEach(function(h){if(!h.complete&&!h.timedOut&&performance.now()>=h.deadline)h.timedOut=true});settledArtwork();requestAnimationFrame(riderTick);
  }
  function rectMatchesFact(node,fact){for(var n=node;n&&n.nodeType===1;n=n.parentElement){var r=n.getBoundingClientRect&&n.getBoundingClientRect();if(r&&Math.abs(r.left-fact.x)<=2&&Math.abs(r.top-fact.y)<=2&&Math.abs(r.right-(fact.x+fact.w))<=2&&Math.abs(r.bottom-(fact.y+fact.h))<=2)return true}return false}
  function settledArtwork(){
    entries().forEach(function(e){var state=entryState[e.id];if(!state||state.artworkDone||!state.serial||S.live.some(function(pair){return pair[1].serial===state.serial&&pair[1].frame})||!Array.isArray(e.artwork)||!e.artwork.length)return;var v=decoderForEntry(e);
      if(!v||!sameId(v.__obedInstance,e.dstObjectId)||!visible(v))return;var vr=v.getBoundingClientRect(),stage=document.getElementById('stage'),sr=stage&&stage.getBoundingClientRect(),info=window.__OBED_CONTINUITY_INFO__;
      if(!sr||!info||!info.authoredWidth||!info.authoredHeight)return;var serial=state.serial||null,rows=[];
      e.artwork.forEach(function(fact){var r=fact.rect;if(!r)return;var ar={x:sr.x+r.x*sr.width/info.authoredWidth,y:sr.y+r.y*sr.height/info.authoredHeight,w:r.w*sr.width/info.authoredWidth,h:r.h*sr.height/info.authoredHeight};
        var left=Math.max(vr.left,ar.x),right=Math.min(vr.right,ar.x+ar.w),top=Math.max(vr.top,ar.y),bottom=Math.min(vr.bottom,ar.y+ar.h);if(right<=left||bottom<=top)return;
        var x=(left+right)/2,y=(top+bottom)/2;if(!finite(x)||!finite(y))return;
        var style=document.createElement('style'),stack=[],vi=-1;style.textContent='*{pointer-events:auto!important}';try{(document.head||document.documentElement).appendChild(style);stack=document.elementsFromPoint(x,y);vi=stack.indexOf(v)}finally{if(style.parentNode)style.parentNode.removeChild(style)}
        rows.push({entryId:e.id,serial:serial,atScene:e.atScene,artworkAbove:vi<0?null:stack.slice(0,vi).some(function(n){return !(n.contains&&n.contains(v))&&rectMatchesFact(n,ar)})})});if(rows.length){S.artwork=S.artwork.concat(rows);state.artworkDone=true}}
    );
  }
  function p95(values){if(!values.length)return null;var a=values.slice().sort(function(x,y){return x-y}),p=(a.length-1)*.95,l=Math.floor(p),h=Math.ceil(p);return l===h?a[l]:a[l]+(a[h]-a[l])*(p-l)}
  function droppedMedia(){var counts={};S.media.forEach(function(row){if(row.serial===null)counts[row.atScene]=(counts[row.atScene]||0)+1});return Object.keys(counts).map(function(key){return {atScene:+key,count:counts[key]}})}
  requestAnimationFrame(riderTick);
  window.__obedMmFeedProbe={version:2,bootstrap:bootstrap,configure:configure,report:function(){S.live.forEach(function(pair){if(pair[1].frame){collectRiders(pair[0],pair[1]);finishFrame(pair[0],pair[1])}});S.handbacks.forEach(function(h){if(!h.complete&&!h.timedOut&&performance.now()>=h.deadline)h.timedOut=true});return {kind:'mm-feed',version:2,config:S.config,
    contexts:S.contexts,frames:S.frames.slice().sort(function(a,b){return a.t-b.t}),media:S.media.filter(function(row){return row.serial!==null}),mediaDropped:droppedMedia(),mediaOverflow:S.mediaOverflow,artwork:S.artwork,errors:S.errors,
    browserFrames:S.browserFrames,handbacks:S.handbacks.map(function(h){return {entryId:h.entryId,serial:h.serial,atScene:h.atScene,closedAt:h.closedAt,
      closedFrameIndex:h.closedFrameIndex,closedDom:h.closedDom,frames:h.frames,complete:h.complete,timedOut:h.timedOut,lastUpload:h.lastUpload}}),
    uploads:S.uploads,claims:S.claims,standDowns:S.standDowns,departures:S.departures,callbackCostP95Ms:p95(S.costs),module:moduleRead(),tamper:S.tamper,killedOnce:S.killedOnce}}};
})();
"""


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _verdict(value: bool | None, reason: str | None = None, **detail: Any) -> dict[str, Any]:
    out = {"verdict": value, **detail}
    if reason:
        out["reason"] = ("inconclusive: " if value is None and not reason.startswith("inconclusive:") else "") + reason
    return out


def feed_interval(record: Any) -> dict[str, float] | None:
    if not isinstance(record, dict) or record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return None
    interval = record.get("interval")
    if not isinstance(interval, dict) or not _finite(interval.get("start")) or not _finite(interval.get("end")):
        return None
    if interval["end"] < interval["start"]:
        return None
    return {"start": float(interval["start"]), "end": float(interval["end"])}


def verdict_records(
    report: Any, entries: Iterable[dict[str, Any]], *, continuous_expected: bool,
) -> dict[str, dict[str, Any]]:
    """Normalize the in-page producer into fail-closed per-carry scorer records."""
    if not isinstance(report, dict):
        return {}
    entries = list(entries)
    tamper = report.get("tamper")
    if isinstance(tamper, dict) and tamper.get("kind") and tamper.get("applied") is not True:
        return {
            entry["id"]: {
                "mode": "unavailable", "reason": "the requested feed tamper was not applied",
                "continuousExpected": continuous_expected,
            }
            for entry in entries if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
    contexts = [row for row in report.get("contexts") or [] if isinstance(row, dict)]
    frames = sorted(
        (row for row in report.get("frames") or [] if isinstance(row, dict)),
        key=lambda row: row.get("t") if _finite(row.get("t")) else math.inf,
    )
    media_rows = [row for row in report.get("media") or [] if isinstance(row, dict)]
    artwork_rows = [row for row in report.get("artwork") or [] if isinstance(row, dict)]
    uploads = [row for row in report.get("uploads") or [] if isinstance(row, dict)]
    claims = [row for row in report.get("claims") or [] if isinstance(row, dict)]
    stand_downs = [row for row in report.get("standDowns") or [] if isinstance(row, dict)]
    departures = [row for row in report.get("departures") or [] if isinstance(row, dict)]
    handbacks = [row for row in report.get("handbacks") or [] if isinstance(row, dict)]
    browser_frames = [row for row in report.get("browserFrames") or [] if isinstance(row, dict)]
    media_dropped = [row for row in report.get("mediaDropped") or [] if isinstance(row, dict)]
    media_overflow = report.get("mediaOverflow")
    records: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        entry_id = entry["id"]
        moves = [
            context for context in contexts
            if context.get("atScene") == entry.get("atScene") and isinstance(context.get("serial"), int)
            and not isinstance(context.get("serial"), bool) and isinstance(context.get("entryIds"), list)
            and entry_id in context["entryIds"]
        ]
        visits = [_visit_record(
            report, entry, move, frames, media_rows, artwork_rows, uploads, claims, stand_downs, departures,
            handbacks=handbacks, browser_frames=browser_frames, continuous_expected=continuous_expected,
            media_overflow=media_overflow,
            media_dropped=media_dropped,
        ) for move in moves]
        if len(visits) == 1:
            records[entry_id] = visits[0]
        elif visits:
            records[entry_id] = {"mode": visits[0]["mode"] if all(v["mode"] == visits[0]["mode"] for v in visits) else "unavailable",
                                 "reason": "repeated visits are scored independently", "visits": visits,
                                 "continuousExpected": continuous_expected}
    return records


def _visit_record(
    report: dict[str, Any], entry: dict[str, Any], move: dict[str, Any], frames: list[dict[str, Any]],
    media_rows: list[dict[str, Any]], artwork_rows: list[dict[str, Any]], uploads: list[dict[str, Any]],
    claims: list[dict[str, Any]], stand_downs: list[dict[str, Any]], departures: list[dict[str, Any]], *,
    handbacks: list[dict[str, Any]], browser_frames: list[dict[str, Any]],
    continuous_expected: bool, media_overflow: Any, media_dropped: list[dict[str, Any]],
) -> dict[str, Any]:
    entry_id, serial, at_scene = entry["id"], move.get("serial"), entry.get("atScene")
    object_id = entry.get("objectId")
    move_frames = [f for f in frames if f.get("serial") == serial and f.get("atScene") == at_scene
                   and _finite(f.get("n")) and _finite(f.get("t")) and isinstance(f.get("rows"), list)]
    related_frames = [f for f in frames if f.get("atScene") == at_scene and (
        f.get("serial") == serial or any(
            isinstance(r, dict) and (r.get("entryId") == entry_id or r.get("objectId") == object_id)
            for r in (f.get("rows") if isinstance(f.get("rows"), list) else [])
        )
    )]
    frames_complete = bool(move_frames) and len(move_frames) == len(related_frames) and all(
        isinstance(f.get("labels"), list) and isinstance(f.get("riders"), list)
        and isinstance(f.get("labelExpected"), list)
        and all(isinstance(r, dict) and isinstance(r.get("entryId"), str) for r in f["rows"])
        and all(isinstance(r, dict) and isinstance(r.get("entryId"), str) for r in f["labels"])
        and all(isinstance(r, dict) and isinstance(r.get("entryId"), str) for r in f["riders"])
        and all(isinstance(r, dict) and isinstance(r.get("entryId"), str) for r in f["labelExpected"])
        for f in move_frames
    )
    rows_by_frame = [[r for r in f["rows"] if isinstance(r, dict) and r.get("entryId") == entry_id]
                     for f in move_frames]
    rows = [r for group in rows_by_frame for r in group]
    usable = move.get("lost") is False
    planned = entry.get("feed") if isinstance(entry.get("feed"), dict) else {}
    expected = [v for v in (planned.get("from"), planned.get("to")) if isinstance(v, dict)]
    expected_ordinals = {v.get("upload") for v in expected if isinstance(v.get("upload"), int)}
    bound = bool(rows) and all(any(
        isinstance(texture, dict) and texture.get("ordinal") == wanted.get("upload") and texture.get("size") == wanted.get("size")
        for row in rows for texture in row.get("textures") or []
    ) for wanted in expected)
    interval = None
    first_t = min((f["t"] for f in move_frames if _finite(f.get("t"))), default=None)
    matching = lambda row: row.get("entryId") == entry_id or (row.get("entryId") is None and row.get("objectId") == object_id)
    related_claims = [r for r in claims if matching(r) and r.get("atScene") == at_scene]
    related_stands = [r for r in stand_downs if matching(r) and r.get("atScene") == at_scene]
    related_departures = [r for r in departures if r.get("atScene") == at_scene
                          and (matching(r) or not isinstance(r.get("entryId"), str))]
    claims_complete = all(r.get("entryId") == entry_id and r.get("serial") == serial for r in related_claims)
    stands_complete = all(r.get("entryId") == entry_id and r.get("serial") == serial for r in related_stands)
    departures_complete = all(r.get("entryId") == entry_id and r.get("serial") == serial for r in related_departures)
    entry_claims = [r for r in related_claims if r.get("entryId") == entry_id and r.get("serial") == serial]
    entry_stands = [r for r in related_stands if r.get("entryId") == entry_id and r.get("serial") == serial
                    and r.get("accepted") is True]
    move_stands = [r for r in entry_stands if _finite(first_t) and _finite(r.get("t")) and r["t"] >= first_t]
    entry_departures = [r for r in related_departures if r.get("entryId") == entry_id and r.get("serial") == serial]
    if not (claims_complete and stands_complete and departures_complete):
        mode, reason = "unavailable", "the feed mode stream is partial or unattributed"
    elif move_stands:
        mode, reason = "standDown", None
    elif any(r.get("claimed") is True for r in entry_claims):
        mode, reason = "continuous", None
    elif entry_departures:
        mode, reason = "departure", None
    else:
        mode, reason = "unavailable", "the core feed seam did not identify a feed or departure mode"
    related_uploads = [r for r in uploads if r.get("atScene") == at_scene and r.get("textureOrdinal") in expected_ordinals]
    uploads_complete = all(r.get("serial") == serial and _finite(r.get("frameN")) and _finite(r.get("t"))
                           for r in related_uploads)
    entry_uploads = [r for r in related_uploads if r.get("serial") == serial]
    move_frame_ns = {f["n"] for f in move_frames}
    move_uploads = [r for r in entry_uploads if r.get("frameN") in move_frame_ns]
    fed_frame_ns = {r.get("frameN") for r in move_uploads if _finite(r.get("frameN"))}
    fed_frame_times = sorted(float(f["frameTime"]) for f, group in zip(move_frames, rows_by_frame, strict=True)
                             if group and f.get("n") in fed_frame_ns and _finite(f.get("frameTime")))
    move_frame_times = sorted(float(f["frameTime"]) for f in move_frames if _finite(f.get("frameTime")))
    frame_times_complete = len(move_frame_times) == len(move_frames)
    frame_periods = [b - a for a, b in zip(move_frame_times, move_frame_times[1:])]
    period = statistics.median(frame_periods) if frame_periods else 1000 / 60
    last_move_frame_time = move_frame_times[-1] if frame_times_complete and move_frame_times else None
    closed_at = move.get("closedAt")
    last_upload_row = max(move_uploads, key=lambda row: row["t"] if _finite(row.get("t")) else -math.inf, default=None)
    upload_frame_time = last_upload_row.get("frameTimestamp") if isinstance(last_upload_row, dict) else None
    canvas_linger = float(closed_at) - float(upload_frame_time) \
        if _finite(closed_at) and _finite(upload_frame_time) else None
    interval_starts = [value for value in (move.get("createdAt"), move_frame_times[0] if move_frame_times else None)
                       if _finite(value)]
    interval_start = min(interval_starts) if interval_starts else None
    interval_end = float(closed_at) if _finite(closed_at) else last_move_frame_time + 1.5 * period \
        if last_move_frame_time is not None else None
    interval = {"start": interval_start, "end": interval_end} if usable and bound and fed_frame_times \
        and interval_start is not None and interval_end is not None and interval_end >= interval_start else None
    upload_times = sorted(float(r["t"]) for r in move_uploads if _finite(r.get("t")))
    gaps = [b - a for a, b in zip(upload_times, upload_times[1:])]
    wanted_frame_ns = {f.get("n") for f, group in zip(move_frames, rows_by_frame, strict=True) if group and _finite(f.get("n"))}
    last_upload = next((r.get("presentedFrames") for r in reversed(entry_uploads) if _finite(r.get("presentedFrames"))), None)
    stand = move_stands[0] if move_stands else None
    reupload = None if stand is None else any(_finite(r.get("t")) and r["t"] > stand.get("t", math.inf) for r in entry_uploads)
    presented = [r["decoder"].get("presentedFrames") for r in rows if isinstance(r.get("decoder"), dict)
                 and _finite(r["decoder"].get("presentedFrames"))]
    sampled = [(r["t"], r.get("feedRead")) for r in rows if _finite(r.get("t")) and isinstance(r.get("feedRead"), dict)]
    feed_reads: list[dict[str, Any]] = []
    if len(sampled) >= 3 and sampled[-1][0] > sampled[0][0]:
        start, end = sampled[0][0], sampled[-1][0]
        for progress in READ_PROGRESS:
            _, read = min(sampled, key=lambda pair: abs((pair[0] - start) / (end - start) - progress))
            feed_reads.append({"progress": progress, **read})
    rider_rows = [[r for r in f.get("riders") or [] if isinstance(r, dict) and r.get("entryId") == entry_id]
                  for f in move_frames]
    pre_draw_frames = next((index for index, frame in enumerate(move_frames)
                            if not isinstance(frame.get("draws"), int) or isinstance(frame["draws"], bool)
                            or frame["draws"] != 0), len(move_frames))
    first_draw = next((frame for frame in move_frames
                       if isinstance(frame.get("draws"), int) and not isinstance(frame["draws"], bool)
                       and frame["draws"] > 0), None)
    first_draw_at = move.get("firstDrawAt")
    pre_draw_ms = float(first_draw_at) - float(move_frames[0]["t"]) \
        if first_draw is not None and _finite(first_draw_at) and first_draw_at >= first_draw["t"] else None
    prefix_geometry = all(
        len(group) == 1 and _finite(group[0].get("sourceRectError"))
        and 0 <= group[0]["sourceRectError"] <= SOURCE_RECT_TOLERANCE_PX
        for group in rider_rows[:pre_draw_frames]
    )
    exempt = (
        pre_draw_frames > 0 and first_draw is not None
        and pre_draw_ms is not None and 0 <= pre_draw_ms <= PRE_DRAW_GRACE_MS
        and prefix_geometry
        and not any(_finite(stand.get("t")) and stand["t"] <= first_draw_at for stand in entry_stands)
    )
    exempted = [r for group in rider_rows[:pre_draw_frames] for r in group] if exempt else []
    riders = [] if first_draw is None else [
        r for group in rider_rows[pre_draw_frames if exempt else 0:] for r in group
    ]
    rider_coverage = bool(move_frames) \
        and all(isinstance(f.get("draws"), int) and not isinstance(f["draws"], bool) and f["draws"] >= 0 for f in move_frames) \
        and all(len(group) == 1 and _rider_readable(group[0]) for group in rider_rows)
    labels = [r for f in move_frames for r in f.get("labels") or [] if isinstance(r, dict) and r.get("entryId") == entry_id]
    expected_labels = sum(
        1 for f in move_frames for r in f.get("labelExpected") or []
        if isinstance(r, dict) and r.get("entryId") == entry_id
    )
    label_coverage = bool(move_frames) and all(
        len([r for r in f.get("labels") or [] if isinstance(r, dict) and r.get("entryId") == entry_id])
        == len([r for r in f.get("labelExpected") or [] if isinstance(r, dict) and r.get("entryId") == entry_id])
        for f in move_frames
    )
    last_t = max((f["t"] for f in move_frames if _finite(f.get("t"))), default=None)
    related_media = [r for r in media_rows if r.get("atScene") == at_scene
                     and (r.get("entryId") == entry_id or not isinstance(r.get("entryId"), str))]
    media_complete = not any(r.get("atScene") == at_scene and isinstance(r.get("count"), int)
                             and not isinstance(r.get("count"), bool) and r["count"] > 0 for r in media_dropped) \
        and all(r.get("entryId") == entry_id and r.get("serial") == serial for r in related_media)
    media = [r for r in related_media if r.get("entryId") == entry_id and r.get("serial") == serial]
    resume = next((r for r in media if r.get("kind") == "play" and _finite(r.get("t")) and _finite(last_t) and r["t"] > last_t), None)
    pauses = [r for r in media if r.get("kind") == "pause" and resume and _finite(r.get("t")) and r["t"] < resume["t"]
              and not any(p.get("kind") == "play" and _finite(p.get("t")) and r["t"] < p["t"] < resume["t"] for p in media)]
    pause = pauses[-1] if pauses else None
    after = next((r for r in media if r.get("kind") == "videoFrame" and resume and _finite(r.get("t")) and r["t"] >= resume["t"]), None)
    frame_duration = _source_frame_duration(
        media, created_at=move.get("createdAt"), source_fps=entry.get("sourceFps"),
    ) or _source_frame_duration(media, source_fps=entry.get("sourceFps"))
    clock_rows = [r.get("decoder") for r in rows if _finite(r.get("t")) and (
        pause is None or r["t"] >= pause["t"]
    ) and (not resume or r["t"] <= resume["t"])]
    clock_readable = bool(clock_rows) and all(isinstance(d, dict) and _finite(d.get("currentTime"))
                                               and _finite(d.get("presentedFrames")) and isinstance(d.get("paused"), bool)
                                               for d in clock_rows)
    clock_still = None if not clock_readable else all(d["paused"] is True for d in clock_rows) \
        and len({d["currentTime"] for d in clock_rows}) == 1 and len({d["presentedFrames"] for d in clock_rows}) == 1
    poster: dict[str, Any] = {
        "mode": "standDown" if mode == "standDown" else "departure", "mediaOverflow": media_overflow,
        "holdPauseMissing": pause is None, "clockReadable": clock_readable, "clockStill": clock_still,
        "departurePauseBeforeMove": bool(pause and _finite(first_t) and pause["t"] <= first_t),
        "lastUploadedFrame": last_upload,
        "lastUploadedMediaTime": last_upload_row.get("mediaTime") if isinstance(last_upload_row, dict) else None,
        "successfulFeed": bool(entry_uploads),
    }
    if pause and resume and after and _finite(frame_duration):
        poster.update({
            "pauseTime": pause["t"], "settleTime": resume["t"], "pauseCurrentTime": pause.get("currentTime"),
            "settleCurrentTime": clock_rows[-1].get("currentTime") if clock_readable else resume.get("currentTime"),
            "pauseFrame": pause.get("presentedFrames"), "firstAfterFrame": after.get("presentedFrames"),
            "pauseMediaTime": pause.get("mediaTime"), "firstAfterMediaTime": after.get("mediaTime"),
            "frameDurationS": frame_duration, "clockToleranceS": frame_duration * .49,
            "seeked": any(r.get("kind") == "seeking" and pause["t"] <= r.get("t", -math.inf) <= resume["t"] for r in media),
            "resumedFromZero": after.get("mediaTime", 1) <= 0,
        })
    window_frames = move_frames if mode != "standDown" or stand is None else [f for f in move_frames if _finite(f.get("t")) and f["t"] >= stand["t"]]
    held_frames = [
        (frame, [row for row in frame.get("rows") or []
                 if isinstance(row, dict) and row.get("entryId") == entry_id])
        for frame in window_frames
    ]
    held_frames = [(frame, group) for frame, group in held_frames if group]
    chosen_frames = [] if mode not in ("departure", "standDown") or not held_frames else [
        held_frames[0], held_frames[len(held_frames) // 2], held_frames[-1],
    ]
    hold_reads: list[dict[str, Any]] = []
    if len(chosen_frames) == 3:
        selected = []
        for _frame, group in chosen_frames:
            match = next((r.get("holdMatch") for r in group if isinstance(r.get("holdMatch"), dict)), None)
            if not isinstance(match, dict):
                textures = [
                    texture for row in group for texture in row.get("textures") or []
                    if isinstance(texture, dict) and texture.get("ordinal") in expected_ordinals
                    and isinstance(texture.get("presentedFrames"), int)
                    and not isinstance(texture.get("presentedFrames"), bool)
                ]
                frames = {texture["presentedFrames"] for texture in textures}
                if len(frames) == 1 and textures:
                    match = {
                        "kind": "texture", "bestFrame": next(iter(frames)),
                        "textureOrdinals": sorted({texture["ordinal"] for texture in textures}),
                    }
            selected.append(match)
        if all(isinstance(match, dict) for match in selected):
            hold_reads = [{"phase": phase, **match} for phase, match in zip(("first", "middle", "last"), selected, strict=True)]
    common = {"usableContext": usable, "boundTextures": bound, "interval": interval,
              "canvasLingerMs": canvas_linger}
    feed = {
        **common, "complete": frames_complete and uploads_complete and claims_complete,
        "mode": mode, "reads": feed_reads, "presentedFrames": presented,
        "framesFed": len(move_uploads), "continuousCoverage": mode == "continuous" and bool(wanted_frame_ns)
        and wanted_frame_ns <= fed_frame_ns,
        "maxInterFeedGapMs": max(gaps, default=0.0),
    }
    advanced = isinstance(last_upload, (int, float)) and any(r.get("kind") == "videoFrame" and _finite(r.get("presentedFrames"))
                                                               and r["presentedFrames"] > last_upload for r in media)
    hold = {
        **common, "complete": frames_complete and uploads_complete and media_complete and stands_complete
        and departures_complete, "mode": "standDown" if mode == "standDown" else "departure", "reads": hold_reads,
        "lastPresentedBeforeDeparture": pause.get("presentedFrames") if pause else None, "lastUploadedFrame": last_upload,
        "successfulFeed": bool(entry_uploads), "advancedDecoder": advanced, "reuploadAfterStandDown": reupload,
        "mediaOverflow": media_overflow,
    }
    related_artwork = [r for r in artwork_rows if r.get("atScene") == at_scene
                       and (r.get("entryId") == entry_id or not isinstance(r.get("entryId"), str))]
    artwork_complete = all(r.get("entryId") == entry_id and r.get("serial") == serial
                           and isinstance(r.get("artworkAbove"), bool)
                           for r in related_artwork)
    artwork = [r for r in related_artwork if r.get("entryId") == entry_id and r.get("serial") == serial]
    visit_handbacks = [r for r in handbacks if r.get("entryId") == entry_id and r.get("serial") == serial
                       and r.get("atScene") == at_scene]
    handback = _handback_record(
        visit_handbacks[0] if len(visit_handbacks) == 1 else None,
        media, last_upload_row, move, browser_frames, source_fps=entry.get("sourceFps"),
    )
    poster["complete"] = frames_complete and media_complete and departures_complete
    return {
        "mode": mode, "reason": reason, "evidenceVersion": report.get("version", 1), **common,
        "continuousExpected": continuous_expected,
        "feed": feed, "rider": {"riders": riders, "coverage": rider_coverage, "complete": frames_complete,
                                 "preDrawFrames": pre_draw_frames, "preDrawMs": pre_draw_ms, "exempt": exempt,
                                 "exemptedVisibleSamples": sum(_rider_offender(row) for row in exempted)},
        "labels": {
            "labels": labels, "expected": expected_labels,
            "coverage": label_coverage, "complete": frames_complete,
        },
        "hold": hold, "poster": poster, "artwork": {"reads": artwork, "complete": artwork_complete},
        "handback": handback,
        "module": report.get("module"),
    }


def _rider_readable(row: Any) -> bool:
    return isinstance(row, dict) and isinstance(row.get("visible"), bool) and _finite(row.get("opacityProduct")) \
        and isinstance(row.get("intersectsCanvas"), bool)


def _rider_offender(row: Any) -> bool:
    return _rider_readable(row) and row["visible"] and row["intersectsCanvas"] \
        and row["opacityProduct"] > RIDER_OPACITY_FLOOR


def _source_frame_duration(
    media: list[dict[str, Any]], *, created_at: Any = None, source_fps: Any = None,
) -> float | None:
    frames = [row for row in media if row.get("kind") == "videoFrame"
              and _finite(row.get("mediaTime")) and _finite(row.get("presentedFrames"))
              and (not _finite(created_at) or _finite(row.get("t")) and row["t"] >= created_at)]
    steps = [
        (b["mediaTime"] - a["mediaTime"], b["presentedFrames"] - a["presentedFrames"])
        for a, b in zip(frames, frames[1:])
        if b["presentedFrames"] > a["presentedFrames"] and b["mediaTime"] > a["mediaTime"]
    ]
    if not steps:
        return None
    single = [delta for delta, presented in steps if presented == 1]
    if _finite(source_fps) and source_fps > 0:
        duration = 1 / float(source_fps)
    else:
        if not single:
            return None
        duration = min(delta / presented for delta, presented in steps)
        if not any(abs(delta - duration) <= duration * .2 for delta in single):
            return None
    if not duration > 0:
        return None

    def consistent(delta: float) -> bool:
        multiple = round(delta / duration)
        return multiple >= 1 and abs(delta - multiple * duration) <= duration * .2

    if single and sum(consistent(delta) for delta in single) < math.ceil(len(single) * .8):
        return None
    return duration if all(consistent(delta) for delta, _presented in steps) else None


def _handback_record(
    handback: dict[str, Any] | None, media: list[dict[str, Any]], last_upload: dict[str, Any] | None,
    move: dict[str, Any], browser_frames: list[dict[str, Any]], *, source_fps: Any = None,
) -> dict[str, Any]:
    mapping_complete = bool(browser_frames) and all(
        row.get("index") == index and _finite(row.get("timestamp"))
        for index, row in enumerate(browser_frames)
    )
    frames = handback.get("frames") if isinstance(handback, dict) else None
    closed_index = handback.get("closedFrameIndex") if isinstance(handback, dict) else move.get("closedFrameIndex")
    closed_at = handback.get("closedAt") if isinstance(handback, dict) else move.get("closedAt")
    last_index = last_upload.get("frameIndex") if isinstance(last_upload, dict) else None
    last_stamp = last_upload.get("frameTimestamp") if isinstance(last_upload, dict) else None
    mapped = {row.get("index"): row.get("timestamp") for row in browser_frames if isinstance(row, dict)}
    endpoints = [(closed_index, closed_at), (last_index, last_stamp)] + [
        (row.get("frameIndex"), row.get("frameTimestamp"))
        for row in (frames[:3] if isinstance(frames, list) else []) if isinstance(row, dict)
    ]
    mapping_complete = mapping_complete and len(endpoints) == 5 and all(
        isinstance(index, int) and not isinstance(index, bool) and _finite(stamp)
        and index in mapped and mapped[index] == stamp
        for index, stamp in endpoints
    )
    duration_source = "fps" if _finite(source_fps) and source_fps > 0 else "rvfc"
    duration = _source_frame_duration(media, created_at=move.get("createdAt"), source_fps=source_fps)
    return {
        "complete": bool(isinstance(handback, dict) and handback.get("complete") is True and not handback.get("timedOut")
                         and isinstance(frames, list) and len(frames) >= 3),
        "timedOut": handback.get("timedOut") if isinstance(handback, dict) else None,
        "frameMappingComplete": mapping_complete,
        "lastUpload": {
            "frameIndex": last_index, "frameTimestamp": last_stamp,
            "mediaTime": last_upload.get("mediaTime") if isinstance(last_upload, dict) else None,
            "presentedFrames": last_upload.get("presentedFrames") if isinstance(last_upload, dict) else None,
        },
        "closed": {
            "frameIndex": closed_index, "timestamp": closed_at,
            "dom": handback.get("closedDom") if isinstance(handback, dict) else None,
        },
        "presented": frames if isinstance(frames, list) else [],
        "sourceFrameDurationS": duration,
        "durationSource": duration_source,
        "adjacentFrames": closed_index - last_index == 1
        if isinstance(closed_index, int) and isinstance(last_index, int) else None,
        "canvasLingerMs": closed_at - last_stamp if _finite(closed_at) and _finite(last_stamp) else None,
    }


def score_feed_live(record: Any, *, continuous_expected: bool = True, alpha_floor: float = ALPHA_POSTER_FLOOR) -> dict[str, Any]:
    def finish(value: bool | None, reason: str | None = None, **detail: Any) -> dict[str, Any]:
        return _verdict(value, reason, alphaFloor=alpha_floor, provisional=True, **detail)

    if not isinstance(record, dict):
        return finish(None, "feed evidence is missing")
    if record.get("complete") is False:
        return finish(None, "the feed producer stream is partial or unattributed")
    if continuous_expected and record.get("mode") in (None, "unavailable"):
        return finish(None, "the feed mode is unreadable", mode=record.get("mode"))
    if continuous_expected and record.get("mode") != "continuous":
        return finish(False, "continuous feed was expected", mode=record.get("mode"))
    if continuous_expected and record.get("continuousCoverage") is False:
        return finish(False, "continuous upload coverage is incomplete")
    reads = record.get("reads")
    if not isinstance(reads, list):
        return finish(None, "feed reads are unreadable")
    wanted = set(READ_PROGRESS)
    got = {float(r.get("progress")) for r in reads if isinstance(r, dict) and _finite(r.get("progress"))}
    if got != wanted:
        return finish(None, f"feed reads cover {sorted(got)}, expected {sorted(wanted)}")
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return finish(None, "the GL context or bound textures were unavailable")
    checks: list[dict[str, Any]] = []
    ambiguous = False
    for read in sorted(reads, key=lambda r: r["progress"]):
        if read.get("patchInside") is not True or read.get("coveredByLaterDraw") is not False:
            return finish(None, "a feed patch is outside the leaf or covered by a later draw", reads=reads)
        kind = read.get("kind")
        if kind == "counter":
            if not _finite(read.get("counter")) or not _finite(read.get("referenceCounter")):
                return finish(None, "a counter read is undecodable", reads=reads)
            ok = abs(read["counter"] - read["referenceCounter"]) <= 1
        elif kind == "alpha":
            if not _finite(read.get("dVideo")) or not _finite(read.get("dPoster")) or not _finite(read.get("dSep")):
                return finish(None, "an Alpha distance is unreadable", reads=reads)
            if read["dSep"] < alpha_floor:
                ambiguous = True
                ok = True
            else:
                ok = read["dVideo"] <= read["dPoster"] / 2
        else:
            return finish(None, f"unknown feed read kind {kind!r}")
        checks.append({"progress": read["progress"], "ok": ok})
    if not all(row["ok"] for row in checks):
        return finish(False, "a sampled GL patch did not match the live decoder", checks=checks)
    if ambiguous:
        return finish(None, "the poster/live separation is below the registered floor", checks=checks)
    presented = [v for v in record.get("presentedFrames") or [] if _finite(v)]
    if len(presented) < 2:
        return finish(None, "fewer than two decoder frame readings were recorded", checks=checks)
    if len(set(presented)) < 2:
        return finish(False, "decoder frames did not advance", checks=checks)
    if continuous_expected:
        if record.get("continuousCoverage") is not True:
            return finish(None, "continuous upload coverage is unreadable", checks=checks)
        gap, limit = record.get("maxInterFeedGapMs"), MAX_INTER_FEED_GAP_MS
        if not _finite(gap):
            return finish(None, "the maximum inter-feed gap is unreadable", checks=checks)
        if gap > limit:
            return finish(False, "the maximum inter-feed gap exceeds the paint-coverage limit", gapMs=gap, limitMs=limit)
    return finish(True, checks=checks, interval=feed_interval(record))


def score_no_rider_above_canvas(record: Any) -> dict[str, Any]:
    if isinstance(record, dict) and record.get("complete") is False:
        return _verdict(None, "the rider producer stream is partial or unattributed")
    if isinstance(record, dict) and record.get("coverage") is not True:
        return _verdict(None, "the rider census does not cover every move frame")
    frames = record.get("riders") if isinstance(record, dict) else None
    if not isinstance(frames, list) or not frames:
        return _verdict(None, "no rider census was recorded")
    if not all(isinstance(row, dict) and isinstance(row.get("visible"), bool) and _finite(row.get("opacityProduct"))
               and isinstance(row.get("intersectsCanvas"), bool) for row in frames):
        return _verdict(None, "a rider census row is unreadable")
    offenders = [row for row in frames if _rider_offender(row)]
    return _verdict(not offenders, "a carried decoder composited above the GL canvas" if offenders else None,
                    offenders=offenders[:10], sampleCount=len(frames))


def _dom_handback_ok(value: Any) -> bool | None:
    if not isinstance(value, dict):
        return None
    required = ("connected", "inStage", "onBody", "shown", "opacityProduct", "canvasCount",
                "afterCanvas", "sameStackingContext")
    if any(key not in value for key in required) or not all(isinstance(value.get(key), bool) for key in (
        "connected", "inStage", "onBody", "shown",
    )) or not _finite(value.get("opacityProduct")) or not isinstance(value.get("canvasCount"), int):
        return None
    if value["canvasCount"] != 1:
        return None
    if not all(value.get(key) is True for key in ("afterCanvas", "sameStackingContext")):
        return False if any(value.get(key) is False for key in ("afterCanvas", "sameStackingContext")) else None
    return value["connected"] and value["inStage"] and not value["onBody"] and value["shown"] \
        and value["opacityProduct"] > 0


def score_handback_continuity(
    record: Any, *, mode: str = "continuous", max_source_frames: int = 2,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "hand-back evidence is missing")
    last, closed, presented = record.get("lastUpload"), record.get("closed"), record.get("presented")
    last = last if isinstance(last, dict) else {}
    closed = closed if isinstance(closed, dict) else {}
    presented = presented if isinstance(presented, list) else []
    dom_values = [closed.get("dom"), *(row.get("dom") for row in presented[:3] if isinstance(row, dict))]
    dom_checks = [_dom_handback_ok(value) for value in dom_values]
    duration = record.get("sourceFrameDurationS")
    duration_source = record.get("durationSource")
    first = presented[0] if presented else None
    media_readable = _finite(last.get("mediaTime")) and isinstance(first, dict) and _finite(first.get("mediaTime"))
    delta = first["mediaTime"] - last["mediaTime"] if media_readable else None
    duration_readable = _finite(duration) and duration > 0 and duration_source in ("fps", "rvfc")
    source_frames = round(delta / duration) if _finite(delta) and duration_readable else None
    last_index, closed_index = last.get("frameIndex"), closed.get("frameIndex")
    detail = {
        "lastUploadMediaTime": last.get("mediaTime"),
        "firstPresentedMediaTime": first.get("mediaTime") if isinstance(first, dict) else None,
        "deltaS": delta, "sourceFrameDurationS": duration, "durationSource": duration_source,
        "sourceFrames": source_frames,
        "maxSourceFrames": max_source_frames, "canvasLingerMs": record.get("canvasLingerMs"),
        "frameGap": closed_index - last_index
        if isinstance(closed_index, int) and isinstance(last_index, int) else None,
        "dom": dom_values,
    }
    if mode == "continuous" and record.get("adjacentFrames") is not True:
        if record.get("adjacentFrames") is False:
            return _verdict(False, "the last upload was not in the frame immediately before canvas removal", **detail)
    if any(value is False for value in dom_checks):
        return _verdict(False, "a static poster was exposed during DOM hand-back", **detail)
    if _finite(delta) and delta < -1e-6:
        return _verdict(False, "hand-back media time moved backwards", **detail)
    if record.get("complete") is not True:
        return _verdict(None, "the three-frame hand-back read window is incomplete",
                        timedOut=record.get("timedOut"), **detail)
    if record.get("frameMappingComplete") is not True:
        return _verdict(None, "the shared browser-frame mapping is incomplete", **detail)
    if not isinstance(record.get("lastUpload"), dict) or not isinstance(record.get("closed"), dict) \
            or not isinstance(record.get("presented"), list) or len(presented) < 3:
        return _verdict(None, "hand-back endpoints are missing", **detail)
    if not media_readable or not duration_readable:
        return _verdict(None, "hand-back media-time endpoints or source-frame duration are unreadable", **detail)
    if mode == "continuous" and record.get("adjacentFrames") is not True:
        return _verdict(None, "the upload/removal frame adjacency is unreadable", **detail)
    if len(dom_checks) != 4 or any(value is None for value in dom_checks):
        return _verdict(None, "DOM hand-back coverage is unreadable", **detail)
    if source_frames <= max_source_frames and duration_source != "fps":
        return _verdict(None, "the source frame rate is unknown, so the hand-back cannot pass", **detail)
    return _verdict(source_frames <= max_source_frames,
                    "hand-back exceeded the source-frame tolerance" if source_frames > max_source_frames else None,
                    **detail)


def score_labels_over_feed(record: Any) -> dict[str, Any]:
    if isinstance(record, dict) and record.get("complete") is False:
        return _verdict(None, "the label producer stream is partial or unattributed")
    if isinstance(record, dict) and record.get("coverage") is not True:
        return _verdict(None, "the label reads do not cover every overlapping label draw")
    rows = record.get("labels") if isinstance(record, dict) else None
    if isinstance(rows, list) and not rows and record.get("expected") == 0:
        return _verdict(True, labels=[], notApplicable=True)
    if not isinstance(rows, list) or not rows:
        return _verdict(None, "no label-over-feed reads were recorded")
    checks, inconclusive = [], False
    for row in rows:
        if not isinstance(row, dict) or not all(_finite(row.get(k)) for k in ("opacity", "spread")):
            inconclusive = True
            continue
        if row["spread"] < LABEL_SPREAD_FLOOR or not _finite(row.get("slope")):
            inconclusive = True
            continue
        expected = 1 - row["opacity"]
        checks.append({**row, "expected": expected, "ok": abs(row["slope"] - expected) <= LABEL_SLOPE_TOLERANCE})
    if any(not row["ok"] for row in checks):
        return _verdict(False, "a label did not composite over the feed", labels=checks)
    if not checks or inconclusive:
        return _verdict(None, "a label-over-feed read is inconclusive", labels=checks)
    return _verdict(True, labels=checks)


def score_hold_frame(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "hold-frame evidence is missing")
    if record.get("complete") is False:
        return _verdict(None, "the held-frame producer stream is partial or unattributed")
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return _verdict(None, "the exact-hold rendering path is unavailable")
    mode = record.get("mode")
    if mode not in ("departure", "standDown"):
        return _verdict(None, f"unknown hold mode {mode!r}")
    if record.get("mediaOverflow") not in (0, None):
        return _verdict(None, "the media event buffer overflowed")
    if mode == "standDown" and record.get("successfulFeed") is True and record.get("advancedDecoder") is not True:
        return _verdict(None, "post-feed stand-down lacks successful-feed and advanced-decoder evidence")
    if mode == "standDown" and record.get("reuploadAfterStandDown") is True:
        return _verdict(False, "a texture was uploaded after stand-down")
    if mode == "standDown" and record.get("reuploadAfterStandDown") is None:
        return _verdict(None, "post-stand-down upload evidence is unreadable")
    target = record.get("lastUploadedFrame") if record.get("successfulFeed") is True \
        else record.get("lastPresentedBeforeDeparture")
    reads = record.get("reads")
    if not isinstance(target, int) or isinstance(target, bool) or not isinstance(reads, list) or len(reads) < 3:
        return _verdict(None, "the held target or its first/middle/last reads are missing")
    if {read.get("phase") for read in reads if isinstance(read, dict)} != {"first", "middle", "last"}:
        return _verdict(None, "the held reads do not cover first, middle, and last draw")
    for read in reads:
        if not isinstance(read, dict) or not isinstance(read.get("bestFrame"), int) \
                or read.get("kind") not in ("alpha", "counter", "texture"):
            return _verdict(None, "a held-frame match is unreadable", reads=reads)
        if read["kind"] == "texture":
            ordinals = read.get("textureOrdinals")
            if not isinstance(ordinals, list) or not ordinals or not all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in ordinals
            ):
                return _verdict(None, "a retained texture reading is unreadable", reads=reads)
            continue
        if not _finite(read.get("matchMargin")):
            return _verdict(None, "a held-frame match is unreadable", reads=reads)
        required = ALPHA_HOLD_MARGIN if read["kind"] == "alpha" else COUNTER_HOLD_MARGIN
        if read["matchMargin"] < required:
            return _verdict(None, "a held-frame match is ambiguous", reads=reads)
    matches = [read["bestFrame"] for read in reads]
    return _verdict(all(frame == target for frame in matches), "the GL canvas did not retain the exact target frame" if any(frame != target for frame in matches) else None,
                    mode=mode, targetFrame=target, matchedFrames=matches,
                    interval=feed_interval(record) or record.get("interval"))


def score_poster_hold(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "poster-hold evidence is missing")
    if record.get("complete") is False:
        return _verdict(None, "the poster-hold producer stream is partial or unattributed")
    if record.get("mediaOverflow") not in (0, None):
        return _verdict(None, "the media event buffer overflowed")
    if record.get("holdPauseMissing") is True:
        return _verdict(False if record.get("clockStill") is False else None, "the move-anchored hold pause is missing")
    if record.get("clockReadable") is False:
        return _verdict(None, "a decoder read is missing from the hold window")
    if record.get("clockStill") is False:
        return _verdict(False, "the decoder clock advanced during the hold")
    required = (
        "pauseTime", "settleTime", "pauseCurrentTime", "settleCurrentTime",
        "pauseMediaTime", "firstAfterMediaTime", "frameDurationS", "clockToleranceS",
    )
    if not all(_finite(record.get(k)) for k in required) or not all(
        isinstance(record.get(k), int) and not isinstance(record.get(k), bool)
        for k in ("pauseFrame", "firstAfterFrame")
    ):
        return _verdict(None, "the poster-hold clock or frame record is unreadable")
    if record["settleTime"] < record["pauseTime"]:
        return _verdict(None, "the poster-hold interval is reversed")
    if record.get("mode", "departure") == "departure" and record.get("departurePauseBeforeMove") is False:
        return _verdict(False, "the decoder was not paused before the move")
    if record.get("seeked") is not False:
        return _verdict(False, "the held decoder sought during the move")
    frame_duration = record["frameDurationS"]
    tolerance = record["clockToleranceS"]
    if frame_duration <= 0 or tolerance < 0 or tolerance >= frame_duration / 2:
        return _verdict(None, "the frame duration or sub-half-frame clock tolerance is unreadable")
    if abs(record["settleCurrentTime"] - record["pauseCurrentTime"]) > tolerance:
        return _verdict(False, "the decoder clock advanced during the hold")
    if record["firstAfterFrame"] <= 0 or record.get("resumedFromZero") is True:
        return _verdict(False, "the decoder restarted from frame zero")
    mode = record.get("mode", "departure")
    base_frame = record.get("lastUploadedFrame") if record.get("successfulFeed") is True else record["pauseFrame"]
    base_media_time = record.get("lastUploadedMediaTime") if record.get("successfulFeed") is True \
        else record["pauseMediaTime"]
    if not isinstance(base_frame, int) or isinstance(base_frame, bool) or not _finite(base_media_time):
        return _verdict(None, "the held resume target is unreadable")
    media_step = record["firstAfterMediaTime"] - base_media_time
    frame_step = record["firstAfterFrame"] - base_frame
    if frame_step <= 0:
        return _verdict(False, "the decoder did not present the held-plus-one frame")
    source_steps = round(media_step / frame_duration)
    if media_step <= 0 or source_steps != frame_step \
            or abs(media_step - source_steps * frame_duration) > frame_duration / 2:
        return _verdict(False, "the post-resume media time did not continue from the held frame", exactHeldPlusOne=False)
    resumed_from_pause = frame_step == 1
    if mode != "standDown" and mode != "departure":
        return _verdict(None, f"unknown poster-hold mode {mode!r}")
    last_upload = record.get("lastUploadedFrame")
    successful_feed = record.get("successfulFeed") is True
    if mode == "standDown" and successful_feed and (not isinstance(last_upload, int) or isinstance(last_upload, bool)):
        return _verdict(None, "the last uploaded frame is unreadable")
    if mode == "standDown" and successful_feed and record["pauseFrame"] < last_upload:
        return _verdict(None, "the pause frame precedes the retained upload")
    discontinuity = frame_step > 1
    return _verdict(True, mode=mode, exactHeldPlusOne=resumed_from_pause if not discontinuity else False,
                    resumedFromPausePlusOne=resumed_from_pause,
                    resumptionDiscontinuity=(frame_step - 1 if discontinuity else 0),
                    resumedFromFrame=base_frame)


def score_artwork_above(record: Any) -> dict[str, Any]:
    if isinstance(record, dict) and record.get("complete") is False:
        return _verdict(None, "the artwork producer stream is partial or unattributed")
    rows = record.get("reads") if isinstance(record, dict) else None
    if not isinstance(rows, list) or not rows:
        return _verdict(None, "no settled artwork reads were recorded")
    if not all(isinstance(row, dict) and isinstance(row.get("artworkAbove"), bool) for row in rows):
        return _verdict(None, "a settled artwork read is unreadable")
    return _verdict(all(row["artworkAbove"] for row in rows),
                    "authored artwork was not above the settled decoder" if not all(row["artworkAbove"] for row in rows) else None,
                    reads=rows)


def combine(*verdicts: dict[str, Any]) -> bool | None:
    values = [row.get("verdict") for row in verdicts]
    return None if any(value is None for value in values) else all(values)


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(v) for v in values if _finite(v))
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

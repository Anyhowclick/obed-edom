"""Probe-only reader and pure scorers for the Magic Move texture feed."""
from __future__ import annotations

import math
from typing import Any, Iterable

READ_PROGRESS = (0.25, 0.5, 0.75)
# Provisional: run2-cmp/direct used the experiment reference (fixed 16x16 staging-canvas centre), so it cannot register the floor; dP 1.36/2.44 were weak separations; re-bank from Phase 0 headless captures with this instrument.
ALPHA_POSTER_FLOOR = 2.5
LABEL_SPREAD_FLOOR = 24.0
LABEL_SLOPE_TOLERANCE = 0.02
RIDER_OPACITY_FLOOR = 0.02


INSTRUMENT_JS = r"""
(function(){
  'use strict';
  if(window.__obedMmFeedProbe)return;
  var READS=[0.25,0.5,0.75],PATCH_UV=[[0.2,0.2],[0.5,0.2],[0.8,0.2],[0.2,0.5],[0.5,0.5],[0.8,0.5],[0.2,0.8],[0.5,0.8],[0.8,0.8]];
  var S={config:null,entries:[],contexts:[],live:[],frames:[],holds:[],media:[],artwork:[],errors:[],tamper:null,killedOnce:[],forcedDecoders:{}};
  var originalGetContext=HTMLCanvasElement.prototype.getContext;
  var locationName=new WeakMap(),programUniforms=new WeakMap(),textureInfo=new WeakMap();
  var decoderState=new WeakMap(),entryState={},media=HTMLMediaElement.prototype,originalPause=media.pause,originalPlay=media.play;
  function finite(v){return typeof v==='number'&&isFinite(v)}
  function noteError(where,e){if(S.errors.length<50)S.errors.push({where:where,error:String(e&&e.stack||e)})}
  function scene(){
    try{var snap=window.__obedLive&&window.__obedLive.snapshot&&window.__obedLive.snapshot();if(snap&&Number.isInteger(snap.scene))return snap.scene}catch(e){}
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
    if(v&&((v.__obedInstance===entry.objectId)||(v.__obedInstance===entry.dstObjectId)))return v;
    v=decoderFor(entry.objectId);
    if(!v&&entry.dstObjectId)v=decoderFor(entry.dstObjectId);
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
    if(move&&move.atScene!==current&&move.atScene!==current+1)move=null;
    if(!move&&state){var candidates=Object.keys(state.entries).map(function(id){return state.entries[id]}).filter(function(e){return e.atScene===current||e.atScene===current+1});
      if(candidates.length===1)move={serial:null,atScene:candidates[0].atScene,entryId:candidates[0].id}}
    if(!move||S.media.length>=20000)return;
    S.media.push(Object.assign({kind:kind,t:performance.now(),serial:move.serial,atScene:move.atScene,entryId:move.entryId,
      instance:v.__obedInstance==null?null:String(v.__obedInstance),elId:v.__obedElId==null?null:v.__obedElId,
      currentTime:v.currentTime,paused:!!v.paused,presentedFrames:v.__obedPresentedFrames==null?null:v.__obedPresentedFrames,
      mediaTime:v.__obedMediaTime==null?null:v.__obedMediaTime},extra||{}));
  }
  media.pause=function(){mediaEvent('pause',this);return originalPause.apply(this,arguments)};
  media.play=function(){mediaEvent('play',this);return originalPlay.apply(this,arguments)};
  function armDecoder(v,entry){
    var state=decoderState.get(v);
    if(!state){state={entries:{},move:null};decoderState.set(v,state)}
    state.entries[entry.id]=entry;entryState[entry.id]=entryState[entry.id]||{ring:[]};entryState[entry.id].decoder=v;
    if(state.armed)return;state.armed=true;
    v.addEventListener('seeking',function(){mediaEvent('seeking',v)},true);
    if(typeof v.requestVideoFrameCallback==='function'){
      var callback=function(now,meta){v.__obedPresentedFrames=meta.presentedFrames;v.__obedMediaTime=meta.mediaTime;
        mediaEvent('videoFrame',v,{now:now,presentedFrames:meta.presentedFrames,mediaTime:meta.mediaTime});
        Object.keys(state.entries).forEach(function(id){var e=state.entries[id],size=entryState[id].leafSize||e.feed&&e.feed.from&&e.feed.from.size;
          if(!size)return;try{var ring=entryState[id].ring;ring.push({frame:meta.presentedFrames,mediaTime:meta.mediaTime,patches:capture(v,size)});if(ring.length>18)ring.shift()}catch(x){noteError('rVFC capture',x)}});
        v.requestVideoFrameCallback(callback)};v.requestVideoFrameCallback(callback);
    }
  }
  function opacityProduct(el){var o=1;for(var n=el;n&&n.nodeType===1;n=n.parentElement)o*=+(getComputedStyle(n).opacity||0);return o}
  function visible(el){
    if(!el||!el.isConnected)return false;
    var s=getComputedStyle(el),r=el.getBoundingClientRect();
    return s.display!=='none'&&s.visibility==='visible'&&r.width>0&&r.height>0&&(!el.checkVisibility||el.checkVisibility({opacityProperty:true,visibilityProperty:true}));
  }
  function entries(){return S.entries}
  function runtimeFeed(entry){
    var plan=window.__OBED_CONTINUITY__,rows=plan&&Array.isArray(plan.boundaries)?plan.boundaries:[];
    var found=rows.filter(function(row){return row&&row.atScene===entry.atScene&&row.src&&row.src.objectId===entry.objectId&&
      (!entry.dstObjectId||row.dst&&row.dst.objectId===entry.dstObjectId)});
    return found.length===1&&found[0].feed&&typeof found[0].feed==='object'?JSON.parse(JSON.stringify(found[0].feed)):null;
  }
  function entriesAt(atScene){return entries().filter(function(e){return e.atScene===atScene})}
  function resolveAtScene(){
    var current=scene(),candidates=[current,current==null?null:current+1];
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
  function canvasPixels(source,w,h){
    if(!source||!w||!h)return null;var c=document.createElement('canvas');c.width=w;c.height=h;var ctx=c.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(source,0,0,w,h);return {pixels:ctx.getImageData(0,0,w,h).data,w:w,h:h};
  }
  function counterFrom(s){
    if(!s)return null;var values=[];for(var i=0;i<17;i++){var x=(24+40*i)/1920*s.w,y=24/540*s.h,m=meanAt(s.pixels,s.w,s.h,x,y,Math.max(1,Math.min(s.w/1920,s.h/540)*6));if(!m)return null;values.push((m[0]+m[1]+m[2])/3)}
    var lo=Math.min.apply(null,values),hi=Math.max.apply(null,values),cut=(lo+hi)/2,bits=values.map(function(v){return v>cut?1:0});
    if(hi-lo<80||bits[0]!==1||bits[1]!==0||bits[15]!==0||bits[16]!==1)return null;
    var n=0;for(var j=2;j<14;j++)n=n*2+bits[j];var parity=bits.slice(2,14).reduce(function(a,b){return a+b},0)%2;
    return parity===bits[14]?n:null;
  }
  function keyFor(uv){return uv[0]+','+uv[1]}
  function vectorFromPixels(s,uv){
    var out=[],rx=8/s.w,ry=8/s.h;for(var y=-1;y<=1;y++)for(var x=-1;x<=1;x++){
      var m=meanAt(s.pixels,s.w,s.h,(uv[0]+x*rx)*s.w,(uv[1]+y*ry)*s.h,1);if(!m)return null;out=out.concat(m)}return out;
  }
  function capture(source,size){
    var s=canvasPixels(source,size[0],size[1]);if(!s)return null;var vectors={};PATCH_UV.forEach(function(uv){vectors[keyFor(uv)]=vectorFromPixels(s,uv)});
    return {vectors:vectors,counter:counterFrom(s)};
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
    var fake={pixels:new Uint8ClampedArray(17*4),w:17,h:1};for(var j=0;j<17;j++){fake.pixels[j*4]=fake.pixels[j*4+1]=fake.pixels[j*4+2]=values[j];fake.pixels[j*4+3]=255}
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
    S.live.forEach(function(pair){if(pair[1].frame)finishFrame(pair[0],pair[1])});
    var atScene=resolveAtScene(),active=entriesAt(atScene),O={},G={unit:gl.TEXTURE0,bindings:{},program:null,flip:false,premultiply:false,
      frame:null,serial:S.contexts.length+1,uploads:0,atScene:atScene,entries:active,closed:false};
    ['texImage2D','activeTexture','bindTexture','pixelStorei','useProgram','getUniformLocation','uniform1f','uniformMatrix4fv','clear','drawArrays','drawElements'].forEach(function(n){O[n]=gl[n]});
    var contextRecord={serial:G.serial,id:canvas.id,createdAt:performance.now(),atScene:atScene,lost:false,entryIds:active.map(function(e){return e.id})};
    S.contexts.push(contextRecord);S.live.push([gl,G]);
    active.forEach(function(e){entryState[e.id].serial=G.serial;S.media.forEach(function(row){if(row.serial===null&&row.entryId===e.id&&row.atScene===atScene)row.serial=G.serial});
      var v=decoderForEntry(e);if(v){armDecoder(v,e);decoderState.get(v).move={serial:G.serial,atScene:atScene,entryId:e.id}}});
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
      G.uploads++;if(G.frame)G.frame.uploads++;
      if(texture){var previous=textureInfo.get(texture),isVideo=!!(src&&typeof src.currentTime==='number'),poster=previous&&previous.poster;
        if(!isVideo&&src)try{poster=capture(src,[w,h])}catch(e){noteError('poster capture',e)}
        textureInfo.set(texture,{serial:G.serial,ordinal:G.uploads,size:[w,h],flip:G.flip,premultiply:G.premultiply,poster:poster,
          video:isVideo,presentedFrames:src&&src.__obedPresentedFrames,mediaTime:src&&src.__obedMediaTime})}
      return O.texImage2D.apply(gl,arguments);
    };
    gl.clear=function(){
      if(G.frame)finishFrame(gl,G);
      G.frame={serial:G.serial,atScene:G.atScene,n:S.frames.length+1,t:performance.now(),draws:0,uploads:0,rows:[],labels:[],riders:[],
        quads:{},under:[],module:moduleRead(),pixelsDone:false};
      return O.clear.apply(gl,arguments);
    };
    function draw(name,args){
      if(!G.frame)return O[name].apply(gl,args);
      var F=G.frame,draw=++F.draws,u=G.program?(programUniforms.get(G.program)||{}):{},table=G.entries[0]&&G.entries[0].draws&&G.entries[0].draws.draws||[],drawFact=table.filter(function(r){return r.draw===draw})[0];
      if(drawFact&&u.MVPMatrix)F.quads[draw]=quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,drawFact.layerSize);
      if(drawFact&&finite(drawFact.labelBoxOpacity)&&F.quads[draw])G.entries.forEach(function(e){var fed=e.feed&&F.quads[e.feed.draw];if(!fed)return;
        var overlap=bounds(fed,gl.drawingBufferWidth,gl.drawingBufferHeight,0),lb=bounds(F.quads[draw],gl.drawingBufferWidth,gl.drawingBufferHeight,0);
        if(overlap.x>=lb.x+lb.w||lb.x>=overlap.x+overlap.w||overlap.y>=lb.y+lb.h||lb.y>=overlap.y+overlap.h)return;
        var b=bounds(F.quads[draw],gl.drawingBufferWidth,gl.drawingBufferHeight,4),under=pixelPatch(gl,b);if(under)F.under.push({entryId:e.id,serial:G.serial,atScene:G.atScene,
          draw:draw,opacity:drawFact.labelBoxOpacity,quad:F.quads[draw],under:under})});
      var textures=[0,1].map(function(unit){var tex=G.bindings[gl.TEXTURE0+unit],info=tex&&textureInfo.get(tex);return info?{unit:unit,ordinal:info.ordinal,size:info.size,
        video:info.video,presentedFrames:info.presentedFrames,mediaTime:info.mediaTime,_poster:info.poster,flip:info.flip}:null});
      var result=O[name].apply(gl,args);
      G.entries.filter(function(e){return e.feed&&e.feed.draw===draw}).forEach(function(e){
        var layerSize=e.feed.from.size,leafSize=textures[0]&&textures[0].size,points=u.MVPMatrix?quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,layerSize):null;
        var decoder=decoderRead(e),v=decoderForEntry(e),reference=null;try{if(v&&leafSize)reference=capture(v,leafSize)}catch(x){noteError('same-task reference',x)}
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
    canvas.addEventListener('webglcontextlost',function(){contextRecord.lost=true;G.closed=true;if(G.frame)finishFrame(gl,G)},true);
  }
  function laterQuads(F,draw){return Object.keys(F.quads).filter(function(k){return +k>draw}).map(function(k){return F.quads[k]})}
  function bestGeneric(gl,F,row){
    var tex=row.textures[0],textureSize=tex&&tex.size,layerSize=row._layerSize,m=row.quad&&row.quad.length===4&&F.quads[row.draw]?programMatrixForRow(row,F):null;
    if(!tex||!textureSize||!layerSize||!m||!row._reference)return {patchInside:false,coveredByLaterDraw:false};
    var later=laterQuads(F,row.draw),best=null,anyInside=false,anyClear=false;
    PATCH_UV.forEach(function(uv){var safe=safeUv(uv,m,layerSize,textureSize,tex.flip,later,gl.drawingBufferWidth,gl.drawingBufferHeight,row.quad);if(!safe.inside)return;anyInside=true;if(safe.covered)return;anyClear=true;
      var key=keyFor(uv),video=row._reference.vectors[key],poster=tex._poster&&tex._poster.vectors[key],final=vectorFromGl(gl,m,layerSize,textureSize,uv,tex.flip),dPoster=distance(final,poster);
      if(final&&video&&finite(dPoster)&&(!best||dPoster>best.dPoster))best={uv:uv,final:final,video:video,poster:poster,dPoster:dPoster}});
    return best?{patchInside:true,coveredByLaterDraw:false,choice:best}:{patchInside:anyInside,coveredByLaterDraw:anyInside&&!anyClear};
  }
  function programMatrixForRow(row,F){return row._matrix||null}
  function counterSafe(gl,F,row,m,size,flip){
    var later=laterQuads(F,row.draw),inside=true,covered=false;
    for(var i=0;i<17;i++){var ux=(24+40*i)/1920,uy=24/540,p=project(m,gl.drawingBufferWidth,gl.drawingBufferHeight,ux*size[0],(flip?1-uy:uy)*size[1]);
      inside=inside&&insideGrow(p,row.quad,0);covered=covered||later.some(function(q){return insideGrow(p,q,2)})}
    return {inside:inside,covered:covered};
  }
  function holdMatch(entry,row,choice){
    var candidates=(entryState[entry.id]&&entryState[entry.id].ring||[]).map(function(ref){return {frame:ref.frame,vector:choice&&ref.patches&&ref.patches.vectors[keyFor(choice.uv)]}}).filter(function(x){return x.vector});
    if(choice&&choice.poster)candidates.push({frame:0,vector:choice.poster});var scored=candidates.map(function(x){return {frame:x.frame,distance:distance(choice&&choice.final,x.vector)}}).filter(function(x){return finite(x.distance)}).sort(function(a,b){return a.distance-b.distance});
    return scored.length>=2?{bestFrame:scored[0].frame,matchDistance:scored[0].distance,matchMargin:scored[1].distance-scored[0].distance,requiredMargin:6.0}:null;
  }
  function holdCounterMatch(entry,row,value){
    var candidates=(entryState[entry.id]&&entryState[entry.id].ring||[]).map(function(ref){return {frame:ref.frame,counter:ref.patches&&ref.patches.counter}}).filter(function(x){return Number.isInteger(x.counter)});
    var poster=row.textures[0]&&row.textures[0]._poster&&row.textures[0]._poster.counter;if(Number.isInteger(poster))candidates.push({frame:0,counter:poster});
    var scored=candidates.map(function(x){return {frame:x.frame,distance:Math.abs(value-x.counter)}}).sort(function(a,b){return a.distance-b.distance});
    return Number.isInteger(value)&&scored.length>=2?{bestFrame:scored[0].frame,matchDistance:scored[0].distance,matchMargin:scored[1].distance-scored[0].distance,requiredMargin:1.0}:null;
  }
  function finalizePixels(gl,G,F){
    if(F.pixelsDone)return;F.pixelsDone=true;
    F.rows.forEach(function(row){var entry=G.entries.filter(function(e){return e.id===row.entryId})[0],tex=row.textures[0],m=row._matrix;
      if(!entry||!tex||!m){row.feedRead={patchInside:false,coveredByLaterDraw:false};delete row._reference;return}
      var counterSafeRead=counterSafe(gl,F,row,m,row._layerSize,tex.flip),counter=row._reference&&row._reference.counter;
      if(counter!==null&&counter!==undefined){var finalCounter=counterFromGl(gl,m,row._layerSize,tex.flip);row.feedRead={patchInside:counterSafeRead.inside,coveredByLaterDraw:counterSafeRead.covered,kind:'counter',
        counter:finalCounter,referenceCounter:counter};row.holdMatch=holdCounterMatch(entry,row,finalCounter)}
      else{var selected=bestGeneric(gl,F,row),choice=selected.choice;row.feedRead={patchInside:selected.patchInside,coveredByLaterDraw:selected.coveredByLaterDraw,kind:'alpha',
        dVideo:choice?distance(choice.final,choice.video):null,dPoster:choice?distance(choice.final,choice.poster):null};row.holdMatch=choice?holdMatch(entry,row,choice):null}
      delete row._reference;row.textures.forEach(function(t){if(t)delete t._poster});delete row._matrix;delete row._layerSize;
    });
    F.under.forEach(function(read){var after=pixelPatch(gl,read.under.rect),row=labelStats(read,after,laterQuads(F,read.draw));if(row)F.labels.push(row)});F.under=[];
  }
  function finishFrame(gl,G){
    var F=G.frame;if(!F)return;
    if(!F.pixelsDone)finalizePixels(gl,G,F);
    var errors=[],guard=0,code;while((code=gl.getError())!==gl.NO_ERROR&&guard++<8)errors.push(code);F.glErrors=errors;S.frames.push(F);G.frame=null;
  }
  HTMLCanvasElement.prototype.getContext=function(type){
    var gl=originalGetContext.apply(this,arguments);
    try{if(gl&&/^\d+-canvas$/.test(this.id)&&/webgl/.test(String(type)))wrap(gl,this)}catch(e){noteError('getContext',e)}
    return gl;
  };
  function configure(config){
    S.config=config||{};S.tamper=S.config.tamper||null;
    S.entries=(Array.isArray(S.config.entries)?S.config.entries:[]).map(function(source){var e=JSON.parse(JSON.stringify(source));e.feed=runtimeFeed(e);return e});
    entries().forEach(function(e){entryState[e.id]={ring:[]};var v=decoderFor(e.objectId);if(v)armDecoder(v,e)});
    if(S.config.killHoldUpload){
      var api=window.__OBED_MM_FEED__;
      if(api&&typeof api.once==='function'&&!api.__obedProbeOnce){var once=api.once;api.__obedProbeOnce=once;api.once=function(id){S.killedOnce.push({objectId:id,t:performance.now()});return false}}
    }
    if(S.tamper==='after-feed')requestAnimationFrame(afterFeedTamper);
    return true;
  }
  function afterFeedTamper(){
    var api=moduleRead(),found=api&&api.entries&&Object.keys(api.entries).find(function(k){var e=api.entries[k];return e&&e.framesFed>0&&e.state!=='stoodDown'});
    if(found){
      var v=decoderFor(found),start=v&&v.__obedPresentedFrames;
      if(v&&typeof v.requestVideoFrameCallback==='function')v.requestVideoFrameCallback(function(){
        var seam=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed,original=seam&&seam.decoderFor;
        S.forcedDecoders[found]=v;
        S.tamper.triggerPresented=v.__obedPresentedFrames;S.tamper.triggeredAt=performance.now();
        if(typeof original==='function')seam.decoderFor=function(id){return id===found?null:original.call(seam,id)};
      });
      S.tamper={kind:'after-feed',objectId:found,lastPresented:start,armedAt:performance.now()};return;
    }
    requestAnimationFrame(afterFeedTamper);
  }
  function riderTick(){
    S.live.forEach(function(pair){var gl=pair[0],G=pair[1],F=G.frame,canvas=gl.canvas;if(!F||G.closed||!canvas||!canvas.isConnected)return;var cr=canvas.getBoundingClientRect();
      G.entries.forEach(function(e){var d=decoderRead(e);if(d)F.riders.push({entryId:e.id,serial:G.serial,atScene:G.atScene,instance:d.instance,visible:d.visible,
        opacityProduct:d.opacityProduct,intersectsCanvas:!!(d.rect&&d.visible&&d.rect.x<cr.right&&d.rect.x+d.rect.w>cr.left&&d.rect.y<cr.bottom&&d.rect.y+d.rect.h>cr.top)})})});
    settledArtwork();S.live.forEach(function(pair){var G=pair[1],canvas=pair[0].canvas;if(G.frame&&(!canvas||!canvas.isConnected||scene()!==G.atScene))finishFrame(pair[0],G)});requestAnimationFrame(riderTick);
  }
  function settledArtwork(){
    entries().forEach(function(e){var state=entryState[e.id];if(!state||state.artworkDone||!Array.isArray(e.artwork)||!e.artwork.length)return;var v=decoderForEntry(e);
      if(!v||String(v.__obedInstance)!==String(e.dstObjectId)||!visible(v))return;var vr=v.getBoundingClientRect(),stage=document.getElementById('stage'),sr=stage&&stage.getBoundingClientRect(),info=window.__OBED_CONTINUITY_INFO__;
      if(!sr||!info||!info.authoredWidth||!info.authoredHeight)return;var serial=state.serial||null,rows=[];
      e.artwork.forEach(function(fact){var r=fact.rect;if(!r)return;var ar={x:sr.x+r.x*sr.width/info.authoredWidth,y:sr.y+r.y*sr.height/info.authoredHeight,w:r.w*sr.width/info.authoredWidth,h:r.h*sr.height/info.authoredHeight};
        var left=Math.max(vr.left,ar.x),right=Math.min(vr.right,ar.x+ar.w),top=Math.max(vr.top,ar.y),bottom=Math.min(vr.bottom,ar.y+ar.h);if(right<=left||bottom<=top)return;
        var x=(left+right)/2,y=(top+bottom)/2;if(!finite(x)||!finite(y))return;
        var stack=document.elementsFromPoint(x,y),vi=stack.findIndex(function(node){return node===v||node.contains&&node.contains(v)||v.contains&&v.contains(node)});
        rows.push({entryId:e.id,serial:serial,atScene:e.atScene,artworkAbove:vi>0})});if(rows.length){S.artwork=S.artwork.concat(rows);state.artworkDone=true}}
    );
  }
  requestAnimationFrame(riderTick);
  window.__obedMmFeedProbe={version:1,configure:configure,report:function(){return {kind:'mm-feed',version:1,config:S.config,
    contexts:S.contexts,frames:S.frames.slice().sort(function(a,b){return a.t-b.t}),holds:S.holds,media:S.media,artwork:S.artwork,errors:S.errors,
    module:moduleRead(),tamper:S.tamper,killedOnce:S.killedOnce}}};
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
    if interval["end"] <= interval["start"]:
        return None
    return {"start": float(interval["start"]), "end": float(interval["end"])}


def verdict_records(
    report: Any, entries: Iterable[dict[str, Any]], *, continuous_expected: bool,
) -> dict[str, dict[str, Any]]:
    """Normalize the in-page producer into fail-closed per-carry scorer records."""
    if not isinstance(report, dict):
        return {}
    contexts = [row for row in report.get("contexts") or [] if isinstance(row, dict)]
    frames = sorted(
        (row for row in report.get("frames") or [] if isinstance(row, dict)),
        key=lambda row: row.get("t") if _finite(row.get("t")) else math.inf,
    )
    module = report.get("module") if isinstance(report.get("module"), dict) else {}
    module_entries = module.get("entries") if isinstance(module.get("entries"), dict) else {}
    media_rows = [row for row in report.get("media") or [] if isinstance(row, dict)]
    artwork_rows = [row for row in report.get("artwork") or [] if isinstance(row, dict)]
    records: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        entry_id = entry["id"]
        object_id = entry.get("objectId")
        moves = [
            context for context in contexts
            if context.get("atScene") == entry.get("atScene")
            and entry_id in (context.get("entryIds") or [])
        ]
        serial = moves[0].get("serial") if len(moves) == 1 else None
        move_frames = [
            frame for frame in frames
            if frame.get("serial") == serial and frame.get("atScene") == entry.get("atScene")
        ]
        rows = [
            row for frame in move_frames for row in frame.get("rows") or []
            if isinstance(row, dict) and row.get("entryId") == entry_id
        ]
        usable = len(moves) == 1 and moves[0].get("lost") is False
        planned = entry.get("feed") if isinstance(entry.get("feed"), dict) else {}
        expected = [planned.get("from"), planned.get("to")]
        expected = [value for value in expected if isinstance(value, dict)]
        bound = bool(rows) and all(any(
            isinstance(texture, dict) and texture.get("ordinal") == wanted.get("upload")
            and texture.get("size") == wanted.get("size")
            for row in rows for texture in row.get("textures") or []
        ) for wanted in expected)
        times = sorted(float(row["t"]) for row in rows if _finite(row.get("t")))
        interval = {"start": times[0], "end": times[-1]} if len(times) > 1 and times[-1] > times[0] else None
        telemetry = module_entries.get(object_id) if isinstance(module_entries.get(object_id), dict) else {}
        state = telemetry.get("state")
        module_mode = telemetry.get("mode")
        mode = "standDown" if state == "stoodDown" else module_mode
        if mode not in ("continuous", "once", "departure", "standDown"):
            mode = None
        riders = [
            rider for frame in move_frames for rider in frame.get("riders") or []
            if isinstance(rider, dict) and rider.get("entryId") == entry_id
        ]
        labels = [
            label for frame in move_frames for label in frame.get("labels") or []
            if isinstance(label, dict) and label.get("entryId") == entry_id
        ]
        presented = [
            row["decoder"].get("presentedFrames") for row in rows if isinstance(row.get("decoder"), dict)
            and _finite(row["decoder"].get("presentedFrames"))
        ]
        sampled = [(row["t"], row.get("feedRead")) for row in rows if _finite(row.get("t")) and isinstance(row.get("feedRead"), dict)]
        feed_reads: list[dict[str, Any]] = []
        if len(sampled) >= 3 and sampled[-1][0] > sampled[0][0]:
            start, end = sampled[0][0], sampled[-1][0]
            for progress in READ_PROGRESS:
                _, read = min(sampled, key=lambda pair: abs((pair[0] - start) / (end - start) - progress))
                feed_reads.append({"progress": progress, **read})
        hold_sampled = [(row["t"], row.get("holdMatch")) for row in rows if _finite(row.get("t")) and isinstance(row.get("holdMatch"), dict)]
        hold_reads: list[dict[str, Any]] = []
        if len(hold_sampled) >= 3:
            chosen = (hold_sampled[0], hold_sampled[len(hold_sampled) // 2], hold_sampled[-1])
            hold_reads = [{"phase": phase, **row[1]} for phase, row in zip(("first", "middle", "last"), chosen, strict=True)]
        common = {"usableContext": usable, "boundTextures": bound, "interval": interval}
        feed = {
            **common, "mode": module_mode, "reads": feed_reads, "presentedFrames": presented,
            "advancing": len(set(presented)) > 1,
            "continuousCoverage": module_mode == "continuous" and telemetry.get("framesFed", 0) > 0 and state != "stoodDown",
            "maxInterFeedGapMs": telemetry.get("maxInterFeedGapMs"),
            "maxInterFeedGapLimitMs": telemetry.get("maxInterFeedGapLimitMs"),
        }
        media = [
            row for row in media_rows
            if row.get("entryId") == entry_id and row.get("serial") == serial and row.get("atScene") == entry.get("atScene")
        ]
        pause = next((row for row in media if row.get("kind") == "pause" and _finite(row.get("t"))), None)
        play = next((row for row in media if row.get("kind") == "play" and pause and row.get("t", -math.inf) > pause["t"]), None)
        after = next((row for row in media if row.get("kind") == "videoFrame" and play and row.get("t", -math.inf) >= play["t"]), None)
        before_times = [
            row.get("mediaTime") for row in media
            if row.get("kind") == "videoFrame" and pause and row.get("t", math.inf) <= pause["t"] and _finite(row.get("mediaTime"))
        ]
        durations = [b - a for a, b in zip(before_times, before_times[1:]) if b > a]
        frame_duration = sorted(durations)[len(durations) // 2] if durations else None
        last_upload = telemetry.get("lastUploadedFrame")
        poster: dict[str, Any] = {"mode": "standDown" if mode == "standDown" else "departure"}
        if pause and play and after and _finite(frame_duration):
            poster.update({
                "pauseTime": pause["t"], "settleTime": play["t"],
                "pauseCurrentTime": pause.get("currentTime"), "settleCurrentTime": play.get("currentTime"),
                "pauseFrame": pause.get("presentedFrames"), "firstAfterFrame": after.get("presentedFrames"),
                "pauseMediaTime": pause.get("mediaTime"), "firstAfterMediaTime": after.get("mediaTime"),
                "frameDurationS": frame_duration, "clockToleranceS": frame_duration * 0.49,
                "seeked": any(row.get("kind") == "seeking" and pause["t"] <= row.get("t", -math.inf) <= play["t"] for row in media),
                "resumedFromZero": after.get("mediaTime", 1) <= 0, "lastUploadedFrame": last_upload,
            })
        module_samples = []
        for frame in move_frames:
            snapshot = frame.get("module") if isinstance(frame.get("module"), dict) else {}
            snapshot_entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), dict) else {}
            sample = snapshot_entries.get(object_id)
            if isinstance(sample, dict):
                module_samples.append(sample)
        stood_down = next((sample for sample in module_samples if sample.get("state") == "stoodDown"), None)
        advanced = isinstance(last_upload, int) and any(
            row.get("kind") == "videoFrame" and _finite(row.get("presentedFrames")) and row["presentedFrames"] > last_upload
            for row in media
        )
        hold = {
            **common, "mode": "standDown" if mode == "standDown" else "departure", "reads": hold_reads,
            "lastPresentedBeforeDeparture": pause.get("presentedFrames") if pause else None,
            "lastUploadedFrame": last_upload, "successfulFeed": telemetry.get("framesFed", 0) > 0,
            "advancedDecoder": advanced,
            "reuploadAfterStandDown": None if stood_down is None else any(
                sample.get("framesFed") != stood_down.get("framesFed") for sample in module_samples[module_samples.index(stood_down):]
            ),
        }
        artwork = [
            row for row in artwork_rows
            if row.get("entryId") == entry_id and row.get("atScene") == entry.get("atScene")
            and (row.get("serial") is None or row.get("serial") == serial)
        ]
        records[entry_id] = {
            "mode": mode, **common, "continuousExpected": continuous_expected,
            "feed": feed, "rider": {"riders": riders}, "labels": {"labels": labels},
            "hold": hold, "poster": poster,
            "artwork": {"reads": artwork},
        }
    return records


def score_feed_live(record: Any, *, continuous_expected: bool = True, alpha_floor: float = ALPHA_POSTER_FLOOR) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "feed evidence is missing")
    if continuous_expected and record.get("mode") not in ("continuous", "once"):
        return _verdict(None, "the feed mode is unreadable", mode=record.get("mode"))
    if continuous_expected and record.get("mode") != "continuous":
        return _verdict(False, "continuous feed was expected", mode=record.get("mode"))
    if continuous_expected and record.get("continuousCoverage") is False:
        return _verdict(False, "continuous upload coverage is incomplete")
    reads = record.get("reads")
    if not isinstance(reads, list):
        return _verdict(None, "feed reads are unreadable")
    wanted = set(READ_PROGRESS)
    got = {float(r.get("progress")) for r in reads if isinstance(r, dict) and _finite(r.get("progress"))}
    if got != wanted:
        return _verdict(None, f"feed reads cover {sorted(got)}, expected {sorted(wanted)}")
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return _verdict(None, "the GL context or bound textures were unavailable")
    checks: list[dict[str, Any]] = []
    ambiguous = False
    for read in sorted(reads, key=lambda r: r["progress"]):
        if read.get("patchInside") is not True or read.get("coveredByLaterDraw") is not False:
            return _verdict(None, "a feed patch is outside the leaf or covered by a later draw", reads=reads)
        kind = read.get("kind")
        if kind == "counter":
            if not _finite(read.get("counter")) or not _finite(read.get("referenceCounter")):
                return _verdict(None, "a counter read is undecodable", reads=reads)
            ok = abs(read["counter"] - read["referenceCounter"]) <= 1
        elif kind == "alpha":
            if not _finite(read.get("dVideo")) or not _finite(read.get("dPoster")):
                return _verdict(None, "an Alpha distance is unreadable", reads=reads)
            if read["dPoster"] < alpha_floor:
                ambiguous = True
                ok = True
            else:
                ok = read["dVideo"] <= read["dPoster"] / 2
        else:
            return _verdict(None, f"unknown feed read kind {kind!r}")
        checks.append({"progress": read["progress"], "ok": ok})
    if not all(row["ok"] for row in checks):
        return _verdict(False, "a sampled GL patch did not match the live decoder", checks=checks)
    if ambiguous:
        return _verdict(None, "the poster/live separation is below the registered floor", checks=checks)
    advancing = record.get("advancing") is True or (
        isinstance(record.get("presentedFrames"), list) and len(set(record["presentedFrames"])) >= 2
    )
    if not advancing:
        return _verdict(False, "decoder frames did not advance", checks=checks)
    if continuous_expected:
        if record.get("continuousCoverage") is not True:
            return _verdict(None, "continuous upload coverage is unreadable", checks=checks)
        gap, limit = record.get("maxInterFeedGapMs"), record.get("maxInterFeedGapLimitMs")
        if not _finite(gap) or not _finite(limit):
            return _verdict(None, "the maximum inter-feed gap is unreadable", checks=checks)
        if gap > limit:
            return _verdict(False, "the maximum inter-feed gap exceeds the paint-coverage limit", gapMs=gap, limitMs=limit)
    return _verdict(True, checks=checks, interval=feed_interval(record))


def score_no_rider_above_canvas(record: Any) -> dict[str, Any]:
    frames = record.get("riders") if isinstance(record, dict) else None
    if not isinstance(frames, list) or not frames:
        return _verdict(None, "no rider census was recorded")
    if not all(isinstance(row, dict) and isinstance(row.get("visible"), bool) and _finite(row.get("opacityProduct"))
               and isinstance(row.get("intersectsCanvas"), bool) for row in frames):
        return _verdict(None, "a rider census row is unreadable")
    offenders = [row for row in frames if row["visible"] and row["intersectsCanvas"] and row["opacityProduct"] > RIDER_OPACITY_FLOOR]
    return _verdict(not offenders, "a carried decoder composited above the GL canvas" if offenders else None,
                    offenders=offenders[:10], sampleCount=len(frames))


def score_labels_over_feed(record: Any) -> dict[str, Any]:
    rows = record.get("labels") if isinstance(record, dict) else None
    if not isinstance(rows, list) or not rows:
        return _verdict(None, "no label-over-feed reads were recorded")
    checks = []
    for row in rows:
        if not isinstance(row, dict) or not all(_finite(row.get(k)) for k in ("opacity", "spread", "slope")):
            return _verdict(None, "a label-over-feed read is unreadable")
        if row["spread"] < LABEL_SPREAD_FLOOR:
            return _verdict(None, "the under-label spread is below 24", labels=rows)
        expected = 1 - row["opacity"]
        checks.append({**row, "expected": expected, "ok": abs(row["slope"] - expected) <= LABEL_SLOPE_TOLERANCE})
    return _verdict(all(row["ok"] for row in checks), "a label did not composite over the feed" if not all(row["ok"] for row in checks) else None,
                    labels=checks)


def score_hold_frame(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "hold-frame evidence is missing")
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return _verdict(None, "the exact-hold rendering path is unavailable")
    mode = record.get("mode")
    if mode not in ("departure", "standDown"):
        return _verdict(None, f"unknown hold mode {mode!r}")
    if mode == "standDown" and not (record.get("successfulFeed") is True and record.get("advancedDecoder") is True):
        return _verdict(None, "post-feed stand-down lacks successful-feed and advanced-decoder evidence")
    if mode == "standDown" and record.get("reuploadAfterStandDown") is not False:
        return _verdict(False, "a texture was uploaded after stand-down")
    target = record.get("lastPresentedBeforeDeparture") if mode == "departure" else record.get("lastUploadedFrame")
    reads = record.get("reads")
    if not isinstance(target, int) or isinstance(target, bool) or not isinstance(reads, list) or len(reads) < 3:
        return _verdict(None, "the held target or its first/middle/last reads are missing")
    if {read.get("phase") for read in reads if isinstance(read, dict)} != {"first", "middle", "last"}:
        return _verdict(None, "the held reads do not cover first, middle, and last draw")
    for read in reads:
        if not isinstance(read, dict) or not isinstance(read.get("bestFrame"), int) or not _finite(read.get("matchMargin")) \
                or not _finite(read.get("requiredMargin")):
            return _verdict(None, "a held-frame match is unreadable", reads=reads)
        if read["matchMargin"] < read["requiredMargin"]:
            return _verdict(None, "a held-frame match is ambiguous", reads=reads)
    matches = [read["bestFrame"] for read in reads]
    return _verdict(all(frame == target for frame in matches), "the GL canvas did not retain the exact target frame" if any(frame != target for frame in matches) else None,
                    mode=mode, targetFrame=target, matchedFrames=matches,
                    interval=feed_interval(record) or record.get("interval"))


def score_poster_hold(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "poster-hold evidence is missing")
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
    media_step = record["firstAfterMediaTime"] - record["pauseMediaTime"]
    resumed_from_pause = abs(media_step - frame_duration) <= frame_duration / 2
    if not resumed_from_pause:
        return _verdict(False, "the first media time after settle was not one frame after the pause", exactHeldPlusOne=False)
    if mode != "standDown" and mode != "departure":
        return _verdict(None, f"unknown poster-hold mode {mode!r}")
    last_upload = record.get("lastUploadedFrame")
    if mode == "standDown" and (not isinstance(last_upload, int) or isinstance(last_upload, bool)):
        return _verdict(None, "the last uploaded frame is unreadable")
    if mode == "standDown" and record["pauseFrame"] < last_upload:
        return _verdict(None, "the pause frame precedes the retained upload")
    discontinuity = mode == "standDown" and record["pauseFrame"] > last_upload
    return _verdict(True, mode=mode, exactHeldPlusOne=resumed_from_pause if not discontinuity else False,
                    resumedFromPausePlusOne=resumed_from_pause,
                    resumptionDiscontinuity=(record["pauseFrame"] - last_upload if discontinuity else 0),
                    resumedFromFrame=record["pauseFrame"])


def score_artwork_above(record: Any) -> dict[str, Any]:
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

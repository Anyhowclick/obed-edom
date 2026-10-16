from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie as binary  # noqa: E402
import live_evidence_contract as contract  # noqa: E402
import mm_feed_instrument as feed  # noqa: E402


def _node(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_js_and_python_counter_decoders_share_the_conformance_table() -> None:
    instrument = json.dumps(feed.INSTRUMENT_JS)
    payload = json.dumps({"layout": binary.layout(), "cases": binary.decoder_conformance_vectors()})
    result = _node(f"""
global.window=global;global.performance={{now:()=>0}};global.requestAnimationFrame=()=>1;
class Media{{pause(){{}} play(){{}}}}class Canvas{{getContext(){{return null}}}}
global.HTMLMediaElement=Media;global.HTMLCanvasElement=Canvas;eval({instrument});const input={payload};
console.log(JSON.stringify(input.cases.map(row=>window.__obedMmFeedProbe.decodeCounter(row.levels,row.layout===undefined?input.layout:row.layout))));
""")
    expected = [
        {"counter": case["counter"], "levels": case["levels"], "reason": case["reason"]}
        for case in binary.decoder_conformance_vectors()
    ]
    python = [
        binary.decode_counter(case["levels"], case["layout"] if "layout" in case else binary.layout())
        for case in binary.decoder_conformance_vectors()
    ]
    assert result == python == expected


def test_realistic_fake_gl_sampling_lifecycle_and_shutdown() -> None:
    instrument = json.dumps(feed.INSTRUMENT_JS)
    counter_layout = json.dumps(binary.layout())
    script = r"""
const layout=LAYOUT;let clock=0,raf=[],cancelled=[],removed=0,videoCancelled=0,draws=0,reads=0,glReads=0,presentDraws=[],contextOptions=[],captureSizes=[],glReadRects=[];
global.window=global; global.location={hash:'#1'}; global.performance={now:()=>++clock};
global.requestAnimationFrame=(fn)=>(raf.push(fn),raf.length);
global.cancelAnimationFrame=id=>cancelled.push(id);
class Media {pause(){this.paused=true} play(){this.paused=false;return Promise.resolve()}}
class Video extends Media {
  constructor(id,dst,w,h,rect,counter=false,track=false){super();this.__obedInstance=id;this.__obedDst=dst;this.__obedElId=id.length;this.currentTime=1;this.paused=false;this.readyState=4;this.videoWidth=w;this.videoHeight=h;this.width=w;this.height=h;this.rect=rect;this.counter=counter;this.drawSource=null;this.opacity='0';this.isConnected=true;this.nodeType=1;this.parentElement=null;this.listeners=[];this.callbacks=[];this.callbackId=0;this.track=track}
  addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){if(this.track&&this.listeners.some(row=>row[0]===k&&row[1]===f))removed++;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}requestVideoFrameCallback(f){const id=++this.callbackId;this.callbacks.push([id,f]);return id}cancelVideoFrameCallback(id){const before=this.callbacks.length;cancelled.push(id);this.callbacks=this.callbacks.filter(row=>row[0]!==id);if(this.callbacks.length<before)videoCancelled++}checkVisibility(){return this.visibility!==false}
  present(frame){this.__obedPresentedFrames=frame;this.__obedMediaTime=frame/30;this.currentTime=frame/30;const before=draws,pending=this.callbacks.splice(0);for(const row of pending)row[1](clock,{presentedFrames:frame,mediaTime:frame/30});presentDraws.push(draws-before)}
  getBoundingClientRect(){return this.rect} contains(n){return n===this}
  pixel(x,y){
    if(this.counter){const value=(this.__obedPresentedFrames||0)%4096,data=Array.from({length:12},(_,i)=>(value>>(11-i))&1),bits=[1,0,...data,data.reduce((a,b)=>a+b,0)%2,0,1],yy=24/540*this.videoHeight;
      for(let j=0;j<17;j++){const xx=(24+40*j)/1920*this.videoWidth;if(Math.abs(x-xx)<7&&Math.abs(y-yy)<7)return bits[j]?240:10}}
    const u=Math.max(0,Math.min(.999,x/this.videoWidth)),v=Math.max(0,Math.min(.999,y/this.videoHeight));
    return 35+Math.floor(u*10)*10+Math.floor(v*8)*3+((this.__obedPresentedFrames||0)%10)*12;
  }
}
class ImageSource {constructor(w,h,value){this.width=w;this.height=h;this.naturalWidth=w;this.naturalHeight=h;this.value=value}pixel(){return this.value}}
global.HTMLMediaElement=Media; global.HTMLVideoElement=Video;
class Context2D {
  constructor(canvas){this.canvas=canvas;this.data=new Uint8ClampedArray(0);this.options=null}
  ensure(){const n=this.canvas.width*this.canvas.height*4;if(this.data.length!==n)this.data=new Uint8ClampedArray(n)}
  clearRect(){this.data.fill(0)}
  drawImage(s,sx,sy,sw,sh,dx,dy,dw,dh){this.ensure();draws++;captureSizes.push([s.__obedInstance||null,this.canvas.width,this.canvas.height]);for(let y=0;y<dh;y++)for(let x=0;x<dw;x++){const px=sx+(x+.5)*sw/dw,py=sy+(y+.5)*sh/dh,v=s.pixel(px,py),i=((dy+y)*this.canvas.width+dx+x)*4;this.data[i]=this.data[i+1]=this.data[i+2]=v;this.data[i+3]=255}}
  getImageData(x,y,w,h){this.ensure();reads++;const out=new Uint8ClampedArray(w*h*4);for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const a=((y+yy)*this.canvas.width+x+xx)*4,b=(yy*w+xx)*4;out.set(this.data.slice(a,a+4),b)}return {data:out}}
}
class Canvas {constructor(id='',gl=null,track=false){this.id=id;this._gl=gl;this._2d=new Context2D(this);this.width=0;this.height=0;this.isConnected=true;this.listeners=[];this.nodeType=1;this.parentElement=null;this.track=track}getContext(t,o){if(t==='2d'){this._2d.options=o;contextOptions.push(o);return this._2d}return this._gl}addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){if(this.track&&this.listeners.some(row=>row[0]===k&&row[1]===f))removed++;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:1920,bottom:540,width:1920,height:540}}}
global.HTMLCanvasElement=Canvas;
const originalGetContext=Canvas.prototype.getContext,originalPause=Media.prototype.pause,originalPlay=Media.prototype.play;
global.getComputedStyle=(el)=>({opacity:el instanceof Video?el.opacity:'1',display:'block',visibility:'visible'});
let stageX=0,stageY=0,stageSX=1,stageSY=1;
const styleParent={appendChild(n){n.parentNode=this},removeChild(n){n.parentNode=null}},stage={offsetWidth:1920,offsetHeight:540,querySelectorAll:()=>[],contains:()=>false,getBoundingClientRect(){const width=1920*stageSX,height=540*stageSY;return {x:stageX,y:stageY,left:stageX,top:stageY,right:stageX+width,bottom:stageY+height,width,height}}};
const overlay={nodeType:1,parentElement:null,contains:()=>false,getBoundingClientRect:()=>({left:0,top:0,right:1920,bottom:540})},labelNode={nodeType:1,parentElement:null,contains:()=>false,getBoundingClientRect:()=>({left:50,top:50,right:250,bottom:150})};
const videos={alpha:new Video('alpha','dalpha',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540},false,true),broken:new Video('broken','dbroken',160,90,{x:550,y:0,left:550,top:0,right:1050,bottom:540,width:500,height:540}),counter:new Video('counter','dcounter',960,270,{x:1100,y:0,left:1100,top:0,right:1920,bottom:540,width:820,height:540},true,true),hold:new Video('hold','dhold',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),killed:new Video('killed','dkilled',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),geo1:new Video('geo1','dgeo1',200,100,{x:0,y:0,left:0,top:0,right:1,bottom:1,width:1,height:1}),geo2:new Video('geo2','dgeo2',200,100,{x:0,y:0,left:0,top:0,right:1,bottom:1,width:1,height:1})};
const decoders={...videos,'alpha-hop':videos.alpha,'alpha-final':videos.alpha};
global.document={timeline:{get currentTime(){return clock}},head:styleParent,documentElement:styleParent,createElement:(k)=>k==='canvas'?new Canvas():{textContent:'',parentNode:null,nodeType:1,parentElement:null},getElementById:(id)=>id==='stage'?stage:null,elementsFromPoint:(x)=>x<500?[overlay,labelNode,videos.alpha]:[overlay,videos.broken]};
const originalDecoderFor=id=>decoders[id]||null,originalClaim=()=>true,originalStand=()=>true,seam={decoderFor:originalDecoderFor,claim:originalClaim,onStandDown:originalStand};global.__OBED_P2_PRESERVE__={feed:seam};
const originalOnce=()=>true;global.__OBED_MM_FEED__={once:originalOnce,entries:{}};
const drawTable={drawCount:4,draws:[{draw:1,layerSize:[100,100],labelBoxOpacity:null},{draw:2,layerSize:[100,100],labelBoxOpacity:null},{draw:3,layerSize:[1920,540],labelBoxOpacity:null},{draw:4,layerSize:[20,20],labelBoxOpacity:.61}]};
const entries=[['alpha',1,[100,100]],['broken',2,[100,100]],['counter',3,[1920,540]]].map(([id,draw,size])=>({id:'carry-'+id,objectId:id,dstObjectId:'d'+id,atScene:2,feed:{draw,from:{upload:draw,size},to:null},draws:drawTable,artwork:[]}));
entries[0].artwork=[{rect:{x:50,y:50,w:200,h:100}}];entries[1].artwork=[{rect:{x:600,y:50,w:200,h:100}}];
const simpleDraws={drawCount:1,draws:[{draw:1,layerSize:[100,100],labelBoxOpacity:null}]};
entries.push({id:'carry-hold',objectId:'hold',dstObjectId:'dhold',atScene:4,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'carry-killed',objectId:'killed',dstObjectId:'dkilled',atScene:6,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'chain-10',objectId:'alpha',dstObjectId:'alpha-hop',atScene:10,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'chain-11',objectId:'alpha-hop',dstObjectId:'alpha-final',atScene:11,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'chain-14',objectId:'alpha-final',dstObjectId:'alpha-end',atScene:14,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'geo-1',objectId:'geo1',dstObjectId:'dgeo1',atScene:20,srcRect:{x:100,y:50,w:200,h:100},feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'geo-2',objectId:'geo2',dstObjectId:'dgeo2',atScene:20,srcRect:{x:400,y:50,w:200,h:100},feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'source-missing',objectId:'missing',dstObjectId:'dmissing',atScene:24,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
const boundaries=entries.map(e=>({atScene:e.atScene,underArtwork:true,src:{objectId:e.objectId},dst:{objectId:e.dstObjectId},feed:e.feed}));
global.__OBED_CONTINUITY_INFO__={authoredWidth:1920,authoredHeight:540};
""" + "\neval(" + instrument + ");\n" + r"""
function tick(){const pending=raf.splice(0);for(const cb of pending)cb()}
window.__obedMmFeedProbe.bootstrap({entries,killHoldUpload:true,tamper:'after-feed',tamperScene:10,counterLayout:layout});
window.__OBED_CONTINUITY__={boundaries};
const continuityDescriptor=Object.getOwnPropertyDescriptor(window,'__OBED_CONTINUITY__');
for(let i=0;i<601;i++)tick();for(const id of ['alpha','broken','counter'])seam.claim(id);
const rolloverState={};videos.counter.__obedPresentedFrames=4095;const rolloverHigh=window.__obedMmFeedProbe.sample(videos.counter,{size:[1920,540],state:rolloverState,layout});videos.counter.__obedPresentedFrames=4096;const rolloverZero=window.__obedMmFeedProbe.sample(videos.counter,{size:[1920,540],state:rolloverState,layout});
let active,bound,sources,matrix,drawNo,pixels,program={},matrixLoc={},mixLoc={};
function rectFor(m,size){const x=((m[12]+1)/2)*1920,y=((m[13]+1)/2)*540,w=m[0]*size[0]/2*1920,h=m[5]*size[1]/2*540;return {x:Math.round(x),y:Math.round(y),w:Math.round(w),h:Math.round(h)}}
function paintSource(source,rect){for(let y=0;y<rect.h;y++)for(let x=0;x<rect.w;x++){const v=source.pixel((x+.5)/rect.w*(source.videoWidth||source.width),(y+.5)/rect.h*(source.videoHeight||source.height)),i=((rect.y+y)*1920+rect.x+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=v;pixels[i+3]=255}}
function paintLabel(rect){for(let y=0;y<rect.h;y++)for(let x=0;x<rect.w;x++){const i=((rect.y+y)*1920+rect.x+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=Math.round(pixels[i]*.39);pixels[i+3]=255}}
function makeGl(){active=100;bound={};sources=new WeakMap();matrix=null;drawNo=0;pixels=new Uint8ClampedArray(1920*540*4);return {canvas:null,TEXTURE0:100,TEXTURE_2D:2,UNPACK_FLIP_Y_WEBGL:3,UNPACK_PREMULTIPLY_ALPHA_WEBGL:4,RGBA:5,UNSIGNED_BYTE:6,drawingBufferWidth:1920,drawingBufferHeight:540,
 activeTexture(u){active=u},bindTexture(t,texture){bound[active]=texture},pixelStorei(){},useProgram(){},getUniformLocation(p,n){return n==='MVPMatrix'?matrixLoc:mixLoc},uniform1f(){},uniformMatrix4fv(l,t,v){matrix=Array.from(v)},
 clear(){drawNo=0;pixels.fill(0)},drawElements(){this.drawArrays()},drawArrays(){drawNo++;const sizes=[[100,100],[100,100],[1920,540],[20,20]],r=rectFor(matrix,sizes[drawNo-1]);if(drawNo===4)paintLabel(r);else paintSource(sources.get(bound[active]),r);this.completedAt=performance.now()},
 texImage2D(){const source=arguments[5],s0=source.drawSource||source;sources.set(bound[active],Object.create(s0,{__obedPresentedFrames:{value:s0.__obedPresentedFrames}}))},readPixels(x,y,w,h,f,t,a){glReads++;glReadRects.push([this.canvas&&this.canvas.id,w,h]);for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const src=((y+yy)*1920+x+xx)*4,dst=(yy*w+xx)*4;a.set(pixels.slice(src,src+4),dst)}}}}
const gl=makeGl();
const originalDraw=gl.drawArrays,originalUpload=gl.texImage2D,canvas=new Canvas('0-canvas',gl,true);gl.canvas=canvas;canvas.getContext('webgl');
const textures={alpha:{},broken:{},counter:{}},posters={alpha:new ImageSource(100,100,8),broken:new ImageSource(100,100,8),counter:new ImageSource(1920,540,8)};
videos.broken.drawSource=posters.broken;
for(const id of ['alpha','broken','counter']){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures[id]);gl.texImage2D(0,0,0,0,0,posters[id])}
const matrices={alpha:[.005208333,0,0,0,0,.02,0,0,0,0,1,0,-1,-1,0,1],broken:[.005208333,0,0,0,0,.02,0,0,0,0,1,0,-.427083333,-1,0,1],counter:[.0004448785,0,0,0,0,.0037037037,0,0,0,0,1,0,.145833333,-1,0,1],label:[.010416667,0,0,0,0,.018518519,0,0,0,0,1,0,-.947916667,-.814814815,0,1]};
gl.useProgram(program);const m=gl.getUniformLocation(program,'MVPMatrix');
for(let frame=1;frame<=20;frame++)videos.counter.present(frame);
for(let n=1;n<=4;n++){
  for(const v of Object.values(videos))v.present(n+9);
  gl.clear();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures.alpha);gl.texImage2D(0,0,0,0,0,videos.alpha);gl.uniformMatrix4fv(m,false,matrices.alpha);gl.drawArrays();
  gl.bindTexture(gl.TEXTURE_2D,textures.broken);gl.texImage2D(0,0,0,0,0,videos.broken);gl.uniformMatrix4fv(m,false,matrices.broken);gl.drawArrays();
  gl.bindTexture(gl.TEXTURE_2D,textures.counter);gl.texImage2D(0,0,0,0,0,videos.counter);gl.uniformMatrix4fv(m,false,matrices.counter);gl.drawArrays();
  gl.uniformMatrix4fv(m,false,matrices.label);gl.drawArrays();tick();
}
function present(video,frame){video.present(frame)}
function openContext(id,track=false){const next=makeGl(),baseDraw=next.drawArrays,canvas=new Canvas(id,next,track);next.canvas=canvas;canvas.getContext('webgl');next.useProgram(program);return {gl:next,canvas,baseDraw,m:next.getUniformLocation(program,'MVPMatrix')}}
function posterTexture(move,poster){const texture={};move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,poster);return texture}
function drawHeld(move,texture,video,upload){for(let n=0;n<3;n++){move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);if(upload&&n===0)move.gl.texImage2D(0,0,0,0,0,video);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}}
location.hash='#3';for(const frame of [31,32,33])present(videos.hold,frame);seam.onStandDown('hold','pre-departure');videos.hold.__obedPosterHeld=true;videos.hold.pause();
const holdMove=openContext('1-canvas',true),originalDraw2=holdMove.baseDraw,holdTexture=posterTexture(holdMove,new ImageSource(100,100,8));drawHeld(holdMove,holdTexture,videos.hold,true);videos.hold.play();present(videos.hold,34);
location.hash='#5';for(const frame of [41,42,43])present(videos.killed,frame);videos.killed.__obedPosterHeld=true;videos.killed.pause();window.__OBED_MM_FEED__.once('killed');
const killedMove=openContext('2-canvas'),killedTexture=posterTexture(killedMove,new ImageSource(100,100,8));drawHeld(killedMove,killedTexture,videos.killed,false);videos.killed.play();present(videos.killed,44);
function runChain(atScene,startFrame,id,objectId,dstObjectId){location.hash='#'+(atScene-1);seam.claim(objectId);const move=openContext(id),texture=posterTexture(move,new ImageSource(100,100,8));location.hash='#'+atScene;for(let n=0;n<4;n++){present(videos.alpha,startFrame+n);move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,videos.alpha);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}videos.alpha.__obedInstance=dstObjectId}
function runMidMoveStandDown(){location.hash='#13';for(const frame of [69,70])present(videos.alpha,frame);seam.claim('alpha-final');const move=openContext('5-canvas'),texture=posterTexture(move,new ImageSource(100,100,8));for(const frame of [71,72]){present(videos.alpha,frame);move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,videos.alpha);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}present(videos.alpha,73);seam.onStandDown('alpha-final','after-feed');videos.alpha.__obedPosterHeld=true;videos.alpha.pause();location.hash='#14';for(let n=0;n<2;n++){move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}videos.alpha.play();present(videos.alpha,74);videos.alpha.__obedInstance='alpha-end'}
videos.broken.drawSource=null;runChain(10,51,'3-canvas','alpha','alpha-hop');location.hash='#10';videos.alpha.__obedPosterHeld=true;videos.alpha.pause();videos.alpha.__obedPosterHeld=false;videos.alpha.play();runChain(11,61,'4-canvas','alpha-hop','alpha-final');runMidMoveStandDown();
videos.alpha.__obedInstance='dalpha';videos.broken.__obedInstance='dbroken';tick();
function screenRect(q,dx=0,dw=0){const left=stageX+q.x*stageSX+dx,top=stageY+q.y*stageSX,width=q.w*stageSX+dw,height=q.h*stageSX;return {x:left,y:top,left,top,right:left+width,bottom:top+height,width,height}}
location.hash='#20';stageX=10;stageY=20;stageSX=.5;stageSY=.5;videos.geo1.opacity='1';videos.geo2.opacity='1';
const q1={x:100,y:50,w:200,h:100},q2={x:400,y:50,w:200,h:100};videos.geo1.rect=screenRect(q1,.25,.25);videos.geo2.rect=screenRect(q2,1,0);
const geoMove=openContext('6-canvas'),geoTexture=posterTexture(geoMove,new ImageSource(100,100,8));geoMove.gl.clear();geoMove.gl.activeTexture(geoMove.gl.TEXTURE0);geoMove.gl.bindTexture(geoMove.gl.TEXTURE_2D,geoTexture);geoMove.gl.uniformMatrix4fv(geoMove.m,false,matrices.alpha);videos.geo1.visibility=false;videos.geo1.rect=screenRect(q1,100,100);tick();videos.geo1.visibility=true;videos.geo1.rect=screenRect(q1);videos.geo2.rect=screenRect(q2);tick();geoMove.gl.drawArrays();const firstCompletedAt=geoMove.gl.completedAt;
videos.geo1.rect=screenRect(q1,100,100);videos.geo2.rect=screenRect(q2,100,100);geoMove.gl.clear();geoMove.gl.activeTexture(geoMove.gl.TEXTURE0);geoMove.gl.bindTexture(geoMove.gl.TEXTURE_2D,geoTexture);geoMove.gl.uniformMatrix4fv(geoMove.m,false,matrices.alpha);geoMove.gl.drawArrays();videos.geo1.rect=screenRect(q1);videos.geo2.rect=screenRect(q2);const stickyMove=openContext('9-canvas');stickyMove.gl.clear();stageSY=.6;tick();stageSY=.5;location.hash='#22';const unframed=openContext('7-canvas'),unframedTexture=posterTexture(unframed,new ImageSource(100,100,8));unframed.gl.activeTexture(unframed.gl.TEXTURE0);unframed.gl.bindTexture(unframed.gl.TEXTURE_2D,unframedTexture);unframed.gl.uniformMatrix4fv(unframed.m,false,matrices.alpha);unframed.gl.drawArrays();const unframedCompletedAt=unframed.gl.completedAt;
const thrownGl=makeGl();thrownGl.drawArrays=function(){this.completedAt=performance.now();throw new Error('draw failed')};const thrownCanvas=new Canvas('8-canvas',thrownGl);thrownGl.canvas=thrownCanvas;thrownCanvas.getContext('webgl');try{thrownGl.drawArrays()}catch(e){}
location.hash='#23';const missingMove=openContext('10-canvas'),missingTexture=posterTexture(missingMove,new ImageSource(100,100,8));location.hash='#24';missingMove.gl.clear();missingMove.gl.activeTexture(missingMove.gl.TEXTURE0);missingMove.gl.bindTexture(missingMove.gl.TEXTURE_2D,missingTexture);missingMove.gl.uniformMatrix4fv(missingMove.m,false,matrices.alpha);missingMove.gl.drawArrays();
const queued=Object.values(videos).flatMap(v=>v.callbacks.map(row=>row[1])),instrumentGetContext=Canvas.prototype.getContext,productGl={},productGetContext=function(){return instrumentGetContext.apply(this,arguments)};Canvas.prototype.getContext=productGetContext;for(const name of ['texImage2D','activeTexture','bindTexture','pixelStorei','useProgram','getUniformLocation','uniform1f','uniformMatrix4fv','clear','drawArrays','drawElements']){const owned=gl[name];productGl[name]=function(){return owned.apply(gl,arguments)};gl[name]=productGl[name]}
const finalReport=window.__obedMmFeedProbe.report(),drawsAtReport=draws,readsAtReport=reads,glAtReport=glReads,contexts=Object.fromEntries(finalReport.contexts.map(c=>[c.id,c])),firstContext=contexts['6-canvas'],geoFrames=finalReport.frames.filter(f=>f.serial===firstContext.serial),stickyContext=contexts['9-canvas'],stickyFrame=finalReport.frames.filter(f=>f.serial===stickyContext.serial).at(-1),geometryFirst=geoFrames[0].riders.map(r=>[r.entryId,r.sourceRectError]),geometryAfterDraw=geoFrames[1].riders.map(r=>[r.entryId,r.sourceRectError]),geometrySticky=stickyFrame.riders.map(r=>[r.entryId,r.sourceRectError]);
for(const callback of queued)callback(clock,{presentedFrames:999,mediaTime:33.3});while(raf.length)tick();canvas.getContext('webgl');gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures.alpha);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.useProgram(program);const postLoc=gl.getUniformLocation(program,'MVPMatrix');gl.uniform1f(mixLoc,1);gl.uniformMatrix4fv(postLoc,false,matrices.alpha);gl.texImage2D(0,0,0,0,0,posters.alpha);gl.clear();gl.drawArrays();gl.drawElements();videos.alpha.pause();videos.alpha.play();window.__OBED_MM_FEED__.once('alpha');seam.claim('alpha');seam.onStandDown('alpha','late');
const descriptorAfter=Object.getOwnPropertyDescriptor(window,'__OBED_CONTINUITY__');
const harnessChecks={geometryFirst,geometryAfterDraw,geometrySticky,rollover:[rolloverHigh.counter,rolloverZero.counter],framed:{completedAt:firstCompletedAt,firstDrawAt:contexts['6-canvas'].firstDrawAt},unframed:{completedAt:unframedCompletedAt,firstDrawAt:contexts['7-canvas'].firstDrawAt},thrown:{completedAt:thrownGl.completedAt,firstDrawAt:contexts['8-canvas'].firstDrawAt},draws,reads,glReads,presentDraws,contextOptions,captureSizes,glReadRects,callbacksRemaining:Object.values(videos).reduce((n,v)=>n+v.callbacks.length,0),videoCancelled,post:{draws:draws-drawsAtReport,reads:reads-readsAtReport,glReads:glReads-glAtReport},frozen:Object.isFrozen(finalReport)&&Object.isFrozen(finalReport.frames[0].rows[0]),removed,cancelled:cancelled.length,restored:{getContext:Canvas.prototype.getContext===productGetContext,pause:Media.prototype.pause===originalPause,play:Media.prototype.play===originalPlay,once:window.__OBED_MM_FEED__.once===originalOnce,decoderFor:seam.decoderFor===originalDecoderFor,claim:seam.claim===originalClaim,stand:seam.onStandDown===originalStand,draw:gl.drawArrays===productGl.drawArrays,upload:gl.texImage2D===productGl.texImage2D,draw2:holdMove.gl.drawArrays===originalDraw2,descriptor:descriptorAfter.value===continuityDescriptor.value&&descriptorAfter.writable===continuityDescriptor.writable&&descriptorAfter.configurable===continuityDescriptor.configurable}};
console.log(JSON.stringify({report:finalReport,harnessChecks}));
"""
    script = script.replace("LAYOUT", counter_layout)
    result = _node(script)
    report = result["report"]
    checks = result["harnessChecks"]
    assert dict(checks["geometryFirst"]) == {"geo-1": 1.0, "geo-2": 2.0}
    assert dict(checks["geometryAfterDraw"]) == {"geo-1": 0.0, "geo-2": 0.0}
    assert dict(checks["geometrySticky"]) == {"geo-1": None, "geo-2": None}
    assert checks["framed"]["firstDrawAt"] > checks["framed"]["completedAt"]
    assert checks["unframed"]["firstDrawAt"] > checks["unframed"]["completedAt"]
    assert checks["thrown"]["firstDrawAt"] is None
    assert checks["rollover"] == [4095, 0]
    assert contract.first_errors(contract.mm_feed_report(report), limit=20) == []
    continuous_entries = [
        {"id": f"carry-{name}", "objectId": name, "dstObjectId": f"d{name}", "atScene": 2,
         "feed": {"draw": draw, "from": {"upload": draw, "size": size}, "to": None}}
        for name, draw, size in (("alpha", 1, [100, 100]), ("broken", 2, [100, 100]),
                                 ("counter", 3, [1920, 540]))
    ]
    continuous_entries.extend({
        "id": f"chain-{scene}", "objectId": object_id, "dstObjectId": dst_id, "atScene": scene,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None},
    } for scene, object_id, dst_id in ((10, "alpha", "alpha-hop"), (11, "alpha-hop", "alpha-final")))
    stand_entry = [{
        "id": "chain-14", "objectId": "alpha-final", "dstObjectId": "alpha-end", "atScene": 14,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None},
    }]
    hold_entries = [{
        "id": f"carry-{name}", "objectId": name, "dstObjectId": f"d{name}", "atScene": scene,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None},
    } for name, scene in (("hold", 4), ("killed", 6))]
    records = feed.verdict_records(report, continuous_entries, continuous_expected=True)
    hold_records = feed.verdict_records(report, hold_entries, continuous_expected=False)
    stand_records = feed.verdict_records(report, stand_entry, continuous_expected=True)
    assert feed.score_feed_live(records["carry-alpha"]["feed"])["verdict"] is True
    assert feed.score_feed_live(records["carry-broken"]["feed"])["verdict"] is False
    assert records["carry-broken"]["feed"]["continuousCoverage"] is True
    assert feed.score_feed_live(records["carry-counter"]["feed"])["verdict"] is True
    assert feed.score_feed_live(records["chain-10"]["feed"])["verdict"] is True
    assert feed.score_feed_live(records["chain-11"]["feed"])["verdict"] is True
    assert feed.score_feed_live(stand_records["chain-14"]["feed"])["verdict"] is False
    assert feed.score_no_rider_above_canvas(records["carry-alpha"]["rider"])["verdict"] is True
    assert feed.score_labels_over_feed(records["carry-alpha"]["labels"])["verdict"] is True
    assert feed.score_artwork_above(records["carry-alpha"]["artwork"])["verdict"] is True
    assert feed.score_artwork_above(records["carry-broken"]["artwork"])["verdict"] is False
    assert feed.score_hold_frame(records["carry-alpha"]["hold"])["verdict"] is None
    assert feed.score_hold_frame(hold_records["carry-hold"]["hold"])["verdict"] is True
    assert feed.score_poster_hold(hold_records["carry-hold"]["poster"])["verdict"] is True
    assert feed.score_hold_frame(hold_records["carry-killed"]["hold"])["verdict"] is False
    assert feed.score_poster_hold(hold_records["carry-killed"]["poster"])["verdict"] is True
    assert feed.score_hold_frame(stand_records["chain-14"]["hold"])["verdict"] is True, json.dumps(
        stand_records["chain-14"], indent=2,
    )
    stand_poster = feed.score_poster_hold(stand_records["chain-14"]["poster"])
    assert stand_poster["verdict"] is True
    assert stand_poster["resumptionDiscontinuity"] == 1
    assert stand_poster["exactHeldPlusOne"] is False
    assert all(read["kind"] == "counter" for read in records["carry-counter"]["feed"]["reads"]), json.dumps(
        records["carry-counter"]["feed"]["reads"]
    )
    counter_rows = [row for frame in report["frames"] for row in frame["rows"]
                    if row["entryId"] == "carry-counter"]
    counter_matches = [row for row in counter_rows if row["holdMatch"] is not None]
    assert counter_matches and all(
        row["holdMatch"]["bestFrame"] == row["textures"][0]["presentedFrames"] for row in counter_matches
    )
    missing_read = next(row["feedRead"] for frame in report["frames"] for row in frame["rows"]
                        if row["entryId"] == "source-missing")
    assert missing_read["referenceCounter"] is None and missing_read["referenceReason"] == "source"
    alpha_texture = next(row for frame in report["frames"] if frame["serial"] == 1
                         for row in frame["rows"] if row["entryId"] == "carry-alpha")["textures"][0]
    assert alpha_texture["size"] == [100, 100] and alpha_texture["uploadedSize"] == [160, 90]
    counter_texture = next(row for frame in report["frames"] if frame["serial"] == 1
                           for row in frame["rows"] if row["entryId"] == "carry-counter")["textures"][0]
    assert counter_texture["size"] == [1920, 540] and counter_texture["uploadedSize"] == [960, 270]
    assert [(row["entryId"], row["serial"]) for row in report["claims"]] == [
        ("carry-alpha", 1), ("carry-broken", 1), ("carry-counter", 1), ("chain-10", 4), ("chain-11", 5),
        ("chain-14", 6),
    ]
    assert [(row["entryId"], row["serial"]) for row in report["departures"]] == [
        ("carry-hold", 2), ("carry-killed", 3), ("chain-11", 5), ("chain-14", 6),
    ]
    hold_departure = next(row for row in report["departures"] if row["entryId"] == "carry-hold")
    hold_context = next(row for row in report["contexts"] if row["serial"] == 2)
    assert hold_departure["t"] < hold_context["createdAt"]
    assert hold_departure["generation"] > 0 and hold_departure["visit"] == 1
    assert [(row["entryId"], row["serial"]) for row in report["standDowns"]] == [
        ("carry-hold", 2), ("chain-14", 6),
    ]
    assert [row["objectId"] for row in report["killedOnce"]] == ["killed"]
    assert report["mediaDropped"] == []
    assert report["tamper"]["applied"] is True and "attempts" not in report["tamper"]
    assert records["carry-alpha"]["feed"]["framesFed"] == 4
    entries_by_id = {entry["id"]: entry for entry in continuous_entries + stand_entry + hold_entries}
    entries_by_id.update({
        "geo-1": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
        "geo-2": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
        "source-missing": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
    })
    entry_sets: set[tuple[str, ...]] = set()
    poster_samples = 0
    for context_row in report["contexts"]:
        entry_set = tuple(context_row["entryIds"])
        if not entry_set or entry_set in entry_sets:
            continue
        entry_sets.add(entry_set)
        poster_samples += len({
            side["upload"] for entry_id in entry_set
            for side in (entries_by_id[entry_id]["feed"].get("from"), entries_by_id[entry_id]["feed"].get("to"))
            if side is not None
        })
    frame_samples = sum(row["decoder"] is not None for frame in report["frames"] for row in frame["rows"])
    presented_samples = sum(checks["presentDraws"])
    expected_capture_count = poster_samples + frame_samples + presented_samples + len(checks["rollover"])
    assert checks["draws"] == checks["reads"] == expected_capture_count, (
        poster_samples, frame_samples, presented_samples,
    )
    counter_sampling = report["sampling"]["entries"]["carry-counter"]
    assert counter_sampling["references"] == report["sampling"]["referenceCapacity"]
    assert report["sampling"]["entries"]["chain-10"]["latestFrame"] == 54
    assert report["sampling"]["entries"]["chain-11"]["latestFrame"] == 70
    assert all(handback["complete"] and len(handback["frames"]) == 3 for handback in report["handbacks"])
    successful_gl_reads = sum(
        row["feedRead"].get("counterReason") is None if row["feedRead"]["kind"] == "counter"
        else row["feedRead"]["kind"] == "alpha" and row["feedRead"].get("dVideo") is not None
        for frame in report["frames"] for row in frame["rows"]
    )
    assert checks["glReads"] == successful_gl_reads + 2 * sum(
        len(frame["labels"]) for frame in report["frames"]
    )
    assert max(checks["presentDraws"]) <= 1
    assert ["alpha", 192, 108] in checks["captureSizes"]
    assert ["counter", 192, 54] in checks["captureSizes"]
    assert any(canvas_id == "0-canvas" and width <= 12 and height >= 14
               for canvas_id, width, height in checks["glReadRects"])
    assert all(options == {"willReadFrequently": False} for options in checks["contextOptions"])
    assert checks["post"] == {"draws": 0, "reads": 0, "glReads": 0}
    assert checks["frozen"] is True
    assert checks["removed"] == 4 and checks["cancelled"] >= 1
    assert checks["videoCancelled"] >= 1 and checks["callbacksRemaining"] == 0
    assert all(checks["restored"].values())

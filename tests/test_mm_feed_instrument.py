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


def _cost_probe(
    instrument: str, *, recorder: bool = True, callbacks: int = 1,
    recorder_failure: str | None = None,
) -> dict:
    return _node(f"""
global.window=global;global.location={{hash:'#1'}};let step=1,now=0,raf=[];
global.performance={{now:()=>{{now+=step;return now}}}};
global.requestAnimationFrame=fn=>(raf.push(fn),raf.length);global.cancelAnimationFrame=()=>{{}};
class Media{{pause(){{}} play(){{return Promise.resolve()}}}}
class Video extends Media{{constructor(){{super();this.__obedInstance='A';this.__obedElId=1;this.currentTime=0;this.paused=false;this.readyState=4;this.videoWidth=320;this.videoHeight=180;this.isConnected=true;this.callbacks=[];this.next=0}}addEventListener(){{}}removeEventListener(){{}}requestVideoFrameCallback(fn){{this.callbacks.push(fn);return ++this.next}}cancelVideoFrameCallback(){{}}getBoundingClientRect(){{return {{x:0,y:0,left:0,top:0,right:10,bottom:10,width:10,height:10}}}}checkVisibility(){{return true}}}}
class Canvas{{getContext(){{return null}}}}global.HTMLMediaElement=Media;global.HTMLVideoElement=Video;global.HTMLCanvasElement=Canvas;
global.getComputedStyle=()=>({{opacity:'1',display:'block',visibility:'visible'}});
global.document={{timeline:{{currentTime:0}},getElementById:()=>null,createElement:()=>new Canvas(),head:null,documentElement:null}};
const video=new Video(),stack=[],hooks={{}},recorderFailure={json.dumps(recorder_failure)};
if({json.dumps(recorder)})global.__obedCost={{install(h){{if(recorderFailure==='install')return false;if(!hooks[h])hooks[h]={{count:0,chunks:[]}};return true}},enter(h){{if(recorderFailure==='enter')return false;stack.push(h);return true}},leave(h){{if(recorderFailure==='leave')return false;if(stack.pop()!==h)return false;hooks[h].count++;hooks[h].chunks.push(step);return true}},stop(){{return true}},read(h,o,n){{if(typeof h==='string')return (hooks[h]&&hooks[h].chunks||[]).slice(o||0,(o||0)+(n||1e9));return {{version:1,stopped:false,errors:[],hooks,frames:{{count:0,chunks:[]}}}}}}}};
global.__OBED_P2_PRESERVE__={{feed:{{decoderFor:id=>id==='A'?video:null}}}};
global.__OBED_CONTINUITY__={{boundaries:[{{atScene:2,src:{{objectId:'A'}},dst:{{objectId:'A2'}},feed:{{draw:1,from:{{upload:1,size:[320,180]}},to:null}}}}]}};
eval({json.dumps(instrument)});
global.__obedMmFeedProbe.bootstrap({{entries:[{{id:'entry-A',atScene:2,objectId:'A',dstObjectId:'A2',feed:{{draw:1,from:{{upload:1,size:[320,180]}},to:null}},draws:{{drawCount:1,draws:[]}},artwork:[]}}]}});
location.hash='#9';
for(let i=0;i<{callbacks};i++){{step=i<51?100:1;const callback=video.callbacks.shift();if(!callback)throw new Error('missing callback '+i);callback(now,{{presentedFrames:i+1,mediaTime:(i+1)/30}})}}
const report=global.__obedMmFeedProbe.report();console.log(JSON.stringify({{health:report.hookHealth,p95:report.callbackCostP95Ms}}));
""")


def test_feed_cost_accounting_is_optional_balanced_and_whole_capture() -> None:
    absent = _cost_probe(feed.INSTRUMENT_JS, recorder=False)
    assert absent["health"]["accountingComplete"] is False
    assert all(not row["installed"] for row in absent["health"]["hooks"].values())

    observed = _cost_probe(feed.INSTRUMENT_JS, callbacks=1001)
    assert observed["health"]["accountingComplete"] is True
    assert observed["health"]["hooks"]["feed.rvfc"]["callbackCount"] == 1001
    assert observed["p95"] == 100

    for failure in ("install", "enter", "leave"):
        rejected = _cost_probe(feed.INSTRUMENT_JS, recorder_failure=failure)
        assert rejected["health"]["accountingComplete"] is False
        assert rejected["health"]["errors"]
    assert all(
        not row["installed"]
        for row in _cost_probe(feed.INSTRUMENT_JS, recorder_failure="install")["health"]["hooks"].values()
    )
    enter_rejected = _cost_probe(feed.INSTRUMENT_JS, recorder_failure="enter")["health"]["hooks"]["feed.rvfc"]
    assert enter_rejected["callbackCount"] == 1 and enter_rejected["enterCount"] == 0
    leave_rejected = _cost_probe(feed.INSTRUMENT_JS, recorder_failure="leave")["health"]["hooks"]["feed.rvfc"]
    assert leave_rejected["enterCount"] == 1 and leave_rejected["leaveCount"] == 0

    unbalanced = feed.INSTRUMENT_JS.replace(
        "costLeave('feed.rvfc',entered);S.rvfcCosts.push",
        "S.rvfcCosts.push",
        1,
    )
    assert _cost_probe(unbalanced)["health"]["accountingComplete"] is False

    truncated = feed.INSTRUMENT_JS.replace(
        "S.rvfcCosts.push(performance.now()-costStart)",
        "S.rvfcCosts.push(performance.now()-costStart);if(S.rvfcCosts.length>1000)S.rvfcCosts.shift()",
        1,
    )
    assert _cost_probe(truncated, callbacks=1001)["p95"] < 20


def test_realistic_fake_gl_sampling_lifecycle_and_shutdown() -> None:
    instrument = json.dumps(feed.INSTRUMENT_JS)
    counter_layout = json.dumps(binary.layout())
    script = r"""
const layout=LAYOUT;let clock=0,raf=[],cancelled=[],removed=0,videoCancelled=0,draws=0,reads=0,failedCaptureDraws=0,glReads=0,presentDraws=[],contextOptions=[],captureSizes=[],glReadRects=[],nativeCostViolations=0;
global.window=global; global.location={hash:'#1'}; global.performance={now:()=>++clock};
const costState={stopped:false,errors:[],stack:[],hooks:{},frames:[],sameHookNesting:0};
global.__obedCost={
  install(hook){if(costState.stopped||typeof hook!=='string'||!hook)return false;if(!costState.hooks[hook])costState.hooks[hook]={installed:true,count:0,chunks:[]};return true},
  enter(hook){if(costState.stopped)return false;const row=costState.hooks[hook];if(!row||!row.installed)return false;if(costState.stack.some(span=>span.hook===hook))costState.sameHookNesting++;costState.stack.push({hook,start:clock,nested:0});return true},
  leave(hook){const end=clock,span=costState.stack[costState.stack.length-1];if(costState.stopped||!span||span.hook!==hook)return false;costState.stack.pop();const total=end-span.start,row=costState.hooks[hook];row.count++;row.chunks.push(Math.max(0,total-span.nested));if(costState.stack.length)costState.stack[costState.stack.length-1].nested+=total;return true},
  stop(){if(costState.stopped)return true;if(costState.stack.length)costState.errors.push('unclosed spans');costState.stack.length=0;costState.stopped=true;return true},
  read(hook,offset,n){if(typeof hook==='string'){const row=costState.hooks[hook];return row?row.chunks.slice(offset||0,(offset||0)+(n||row.chunks.length)):[]}return {version:1,stopped:costState.stopped,errors:costState.errors.slice(),hooks:costState.hooks,frames:{count:costState.frames.length,chunks:costState.frames.slice()}}}
};
global.requestAnimationFrame=(fn)=>(raf.push(fn),raf.length);
global.cancelAnimationFrame=id=>cancelled.push(id);
class Media {pause(){this.paused=true} play(){this.paused=false;return Promise.resolve()}}
class Video extends Media {
  constructor(id,dst,w,h,rect,counter=false,track=false){super();this.__obedInstance=id;this.__obedDst=dst;this.__obedElId=id.length;this.currentTime=1;this.paused=false;this.readyState=4;this.videoWidth=w;this.videoHeight=h;this.width=w;this.height=h;this.rect=rect;this.counter=counter;this.drawSource=null;this.opacity='0';this.isConnected=true;this.nodeType=1;this.parentElement=null;this.listeners=[];this.callbacks=[];this.callbackId=0;this.track=track}
  addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){if(this.track&&this.listeners.some(row=>row[0]===k&&row[1]===f))removed++;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}requestVideoFrameCallback(f){const id=++this.callbackId;this.callbacks.push([id,f]);return id}cancelVideoFrameCallback(id){const before=this.callbacks.length;this.callbacks=this.callbacks.filter(row=>row[0]!==id);if(this.callbacks.length<before)videoCancelled++}checkVisibility(){return this.visibility!==false}
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
class NoPosterSource extends ImageSource {pixel(){throw new Error('poster unavailable')}}
global.HTMLMediaElement=Media; global.HTMLVideoElement=Video;
class Context2D {
  constructor(canvas){this.canvas=canvas;this.data=new Uint8ClampedArray(0);this.options=null}
  ensure(){const n=this.canvas.width*this.canvas.height*4;if(this.data.length!==n)this.data=new Uint8ClampedArray(n)}
  clearRect(){this.data.fill(0)}
  drawImage(s,sx,sy,sw,sh,dx,dy,dw,dh){this.ensure();captureSizes.push([s.__obedInstance||null,this.canvas.width,this.canvas.height]);try{for(let y=0;y<dh;y++)for(let x=0;x<dw;x++){const px=sx+(x+.5)*sw/dw,py=sy+(y+.5)*sh/dh,v=s.pixel(px,py),i=((dy+y)*this.canvas.width+dx+x)*4;this.data[i]=this.data[i+1]=this.data[i+2]=v;this.data[i+3]=255}}catch(e){failedCaptureDraws++;throw e}draws++}
  getImageData(x,y,w,h){this.ensure();reads++;const out=new Uint8ClampedArray(w*h*4);for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const a=((y+yy)*this.canvas.width+x+xx)*4,b=(yy*w+xx)*4;out.set(this.data.slice(a,a+4),b)}return {data:out}}
}
class Canvas {constructor(id='',gl=null,track=false){this.id=id;this._gl=gl;this._2d=new Context2D(this);this.width=0;this.height=0;this.isConnected=true;this.listeners=[];this.nodeType=1;this.parentElement=null;this.track=track}getContext(t,o){if(t==='2d'){this._2d.options=o;contextOptions.push(o);return this._2d}return this._gl}addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){if(this.track&&this.listeners.some(row=>row[0]===k&&row[1]===f))removed++;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:1920,bottom:540,width:1920,height:540}}}
global.HTMLCanvasElement=Canvas;
const originalGetContext=Canvas.prototype.getContext,originalPause=Media.prototype.pause,originalPlay=Media.prototype.play;
global.getComputedStyle=(el)=>({opacity:el instanceof Video?el.opacity:'1',display:'block',visibility:'visible'});
let stageX=0,stageY=0,stageSX=1,stageSY=1;
const styleParent={appendChild(n){n.parentNode=this},removeChild(n){n.parentNode=null}},stage={offsetWidth:1920,offsetHeight:540,querySelectorAll:()=>[],contains:()=>false,getBoundingClientRect(){const width=1920*stageSX,height=540*stageSY;return {x:stageX,y:stageY,left:stageX,top:stageY,right:stageX+width,bottom:stageY+height,width,height}}};
const overlay={nodeType:1,parentElement:null,contains:()=>false,getBoundingClientRect:()=>({left:0,top:0,right:1920,bottom:540})},labelNode={nodeType:1,parentElement:null,contains:()=>false,getBoundingClientRect:()=>({left:50,top:50,right:250,bottom:150})};
const videos={alpha:new Video('alpha','dalpha',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540},false,true),broken:new Video('broken','dbroken',160,90,{x:550,y:0,left:550,top:0,right:1050,bottom:540,width:500,height:540}),counter:new Video('counter','dcounter',960,270,{x:1100,y:0,left:1100,top:0,right:1920,bottom:540,width:820,height:540},true,true),hold:new Video('hold','dhold',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),killed:new Video('killed','dkilled',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),revisit:new Video('revisit','drevisit',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),ordinal:new Video('ordinal','dordinal',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),early:new Video('early','dearly',160,90,{x:0,y:0,left:0,top:0,right:500,bottom:540,width:500,height:540}),geo1:new Video('geo1','dgeo1',200,100,{x:0,y:0,left:0,top:0,right:1,bottom:1,width:1,height:1}),geo2:new Video('geo2','dgeo2',200,100,{x:0,y:0,left:0,top:0,right:1,bottom:1,width:1,height:1})};
const decoders={};
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
entries.push({id:'carry-revisit',objectId:'revisit',dstObjectId:'drevisit',atScene:26,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'carry-ordinal',objectId:'ordinal',dstObjectId:'dordinal',atScene:28,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
const counterDraws={drawCount:1,draws:[{draw:1,layerSize:[1920,540],labelBoxOpacity:null}]};
entries.push({id:'carry-counter-hold',objectId:'counter',dstObjectId:'dcounter',atScene:30,feed:{draw:1,from:{upload:1,size:[1920,540]},to:null},draws:counterDraws,artwork:[]});
entries.push({id:'chain-34',objectId:'alpha-end',dstObjectId:'alpha-n4',atScene:34,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
entries.push({id:'carry-early-claim',objectId:'early',dstObjectId:'dearly',atScene:38,feed:{draw:1,from:{upload:1,size:[100,100]},to:null},draws:simpleDraws,artwork:[]});
const boundaries=entries.map(e=>({atScene:e.atScene,underArtwork:true,src:{objectId:e.objectId},dst:{objectId:e.dstObjectId},feed:e.feed}));
global.__OBED_CONTINUITY_INFO__={authoredWidth:1920,authoredHeight:540};
""" + "\neval(" + instrument + ");\n" + r"""
function tick(){const pending=raf.splice(0);for(const cb of pending)cb()}
let active,bound,sources,matrix,drawNo,pixels,flipY,failPatch=false,program={},matrixLoc={},mixLoc={};
location.hash='#22';const missingMove=openContext('10-canvas'),missingTexture=posterTexture(missingMove,new ImageSource(100,100,8));location.hash='#23';
window.__obedMmFeedProbe.bootstrap({entries,killHoldUpload:true,tamper:'after-feed',tamperScene:10,counterLayout:layout});
window.__OBED_CONTINUITY__={boundaries};Object.assign(decoders,videos,{'alpha-hop':videos.alpha,'alpha-final':videos.alpha,'alpha-end':videos.alpha});location.hash='#1';
const continuityDescriptor=Object.getOwnPropertyDescriptor(window,'__OBED_CONTINUITY__');
for(let i=0;i<601;i++)tick();for(const id of ['alpha','broken','counter'])seam.claim(id);
const rolloverState={};videos.counter.__obedPresentedFrames=4095;const rolloverHigh=window.__obedMmFeedProbe.sample(videos.counter,{size:[1920,540],state:rolloverState,layout});videos.counter.__obedPresentedFrames=4096;const rolloverZero=window.__obedMmFeedProbe.sample(videos.counter,{size:[1920,540],state:rolloverState,layout});
function rectFor(m,size){const x=((m[12]+1)/2)*1920,y=((m[13]+1)/2)*540,w=m[0]*size[0]/2*1920,h=m[5]*size[1]/2*540;return {x:Math.round(x),y:Math.round(y),w:Math.round(w),h:Math.round(h)}}
function paintSource(source,rect){for(let y=0;y<rect.h;y++)for(let x=0;x<rect.w;x++){const v=source.pixel((x+.5)/rect.w*(source.videoWidth||source.width),(source.flipY?1-(y+.5)/rect.h:(y+.5)/rect.h)*(source.videoHeight||source.height)),i=((rect.y+y)*1920+rect.x+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=v;pixels[i+3]=255}}
function paintLabel(rect){for(let y=0;y<rect.h;y++)for(let x=0;x<rect.w;x++){const i=((rect.y+y)*1920+rect.x+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=Math.round(pixels[i]*.39);pixels[i+3]=255}}
function makeGl(){active=100;flipY=false;bound={};sources=new WeakMap();matrix=null;drawNo=0;pixels=new Uint8ClampedArray(1920*540*4);return {canvas:null,TEXTURE0:100,TEXTURE_2D:2,UNPACK_FLIP_Y_WEBGL:3,UNPACK_PREMULTIPLY_ALPHA_WEBGL:4,RGBA:5,UNSIGNED_BYTE:6,drawingBufferWidth:1920,drawingBufferHeight:540,
 activeTexture(u){active=u},bindTexture(t,texture){bound[active]=texture},pixelStorei(p,v){if(p===3)flipY=!!v},useProgram(){},getUniformLocation(p,n){return n==='MVPMatrix'?matrixLoc:mixLoc},uniform1f(){},uniformMatrix4fv(l,t,v){matrix=Array.from(v)},
 clear(){if(costState.stack.length)nativeCostViolations++;drawNo=0;pixels.fill(0)},drawElements(){this.drawArrays()},drawArrays(){if(costState.stack.length)nativeCostViolations++;drawNo++;const sizes=this.layerSizes||[[100,100],[100,100],[1920,540],[20,20]],r=rectFor(matrix,sizes[drawNo-1]);if(drawNo===4)paintLabel(r);else paintSource(sources.get(bound[active]),r);this.completedAt=performance.now()},
 texImage2D(){if(costState.stack.length)nativeCostViolations++;const source=arguments[5],s0=source.drawSource||source;sources.set(bound[active],Object.create(s0,{__obedPresentedFrames:{value:s0.__obedPresentedFrames},flipY:{value:flipY}}))},readPixels(x,y,w,h,f,t,a){if(failPatch&&w<20){failPatch=false;throw new Error('read failed')}glReads++;glReadRects.push([this.canvas&&this.canvas.id,w,h]);for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const src=((y+yy)*1920+x+xx)*4,dst=(yy*w+xx)*4;a.set(pixels.slice(src,src+4),dst)}}}}
const gl=makeGl();
const originalDraw=gl.drawArrays,originalUpload=gl.texImage2D,canvas=new Canvas('0-canvas',gl,true);gl.canvas=canvas;canvas.getContext('webgl');
const textures={alpha:{},broken:{},counter:{}},posters={alpha:new ImageSource(100,100,8),broken:new ImageSource(100,100,8),counter:new ImageSource(1920,540,8)};
videos.broken.drawSource=posters.broken;
for(const id of ['alpha','broken','counter']){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures[id]);gl.texImage2D(0,0,0,0,0,posters[id])}
const matrices={alpha:[.005208333,0,0,0,0,.02,0,0,0,0,1,0,-1,-1,0,1],broken:[.005208333,0,0,0,0,.02,0,0,0,0,1,0,-.427083333,-1,0,1],counter:[.0004448785,0,0,0,0,.0037037037,0,0,0,0,1,0,.145833333,-1,0,1],label:[.010416667,0,0,0,0,.018518519,0,0,0,0,1,0,-.947916667,-.814814815,0,1]};
gl.useProgram(program);const m=gl.getUniformLocation(program,'MVPMatrix');
for(let frame=1;frame<=20;frame++)videos.counter.present(frame);
for(let n=1;n<=4;n++){
  for(const v of Object.values(videos))v.present(n+9);failPatch=n===2;
  gl.clear();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures.alpha);gl.texImage2D(0,0,0,0,0,videos.alpha);gl.uniformMatrix4fv(m,false,matrices.alpha);gl.drawArrays();
  gl.bindTexture(gl.TEXTURE_2D,textures.broken);gl.texImage2D(0,0,0,0,0,videos.broken);gl.uniformMatrix4fv(m,false,matrices.broken);gl.drawArrays();
  gl.bindTexture(gl.TEXTURE_2D,textures.counter);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);gl.texImage2D(0,0,0,0,0,videos.counter);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);if(n===3)videos.counter.present(13);gl.uniformMatrix4fv(m,false,matrices.counter);gl.drawArrays();
  gl.uniformMatrix4fv(m,false,matrices.label);gl.drawArrays();tick();
}
function present(video,frame){video.present(frame)}
function openContext(id,track=false){const next=makeGl(),baseDraw=next.drawArrays,canvas=new Canvas(id,next,track);next.canvas=canvas;canvas.getContext('webgl');next.useProgram(program);next.pixelStorei(next.UNPACK_FLIP_Y_WEBGL,true);return {gl:next,canvas,baseDraw,m:next.getUniformLocation(program,'MVPMatrix')}}
function posterTexture(move,poster){const texture={};move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,poster);return texture}
function drawHeld(move,texture,video,upload){for(let n=0;n<3;n++){move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);if(upload&&n===0)move.gl.texImage2D(0,0,0,0,0,video);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}}
location.hash='#3';for(const frame of [31,32,33])present(videos.hold,frame);seam.onStandDown('hold','pre-departure');videos.hold.__obedPosterHeld=true;videos.hold.pause();
const holdMove=openContext('1-canvas',true),originalDraw2=holdMove.baseDraw,holdTexture=posterTexture(holdMove,new ImageSource(100,100,8));drawHeld(holdMove,holdTexture,videos.hold,true);videos.hold.play();present(videos.hold,34);
location.hash='#5';for(const frame of [41,42,43])present(videos.killed,frame);videos.killed.__obedPosterHeld=true;videos.killed.pause();window.__OBED_MM_FEED__.once('killed');
const killedMove=openContext('2-canvas'),killedTexture=posterTexture(killedMove,new ImageSource(100,100,8));drawHeld(killedMove,killedTexture,videos.killed,false);videos.killed.play();present(videos.killed,44);killedMove.canvas.isConnected=false;tick();location.hash='#6';for(const frame of [45,46,47])present(videos.killed,frame);
function runChain(atScene,startFrame,id,objectId,dstObjectId){location.hash='#'+(atScene-1);seam.claim(objectId);const move=openContext(id),texture=posterTexture(move,new ImageSource(100,100,8));location.hash='#'+atScene;for(let n=0;n<4;n++){present(videos.alpha,startFrame+n);move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,videos.alpha);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}videos.alpha.__obedInstance=dstObjectId}
function runMidMoveStandDown(){location.hash='#13';for(const frame of [69,70])present(videos.alpha,frame);seam.claim('alpha-final');const move=openContext('5-canvas'),texture=posterTexture(move,new ImageSource(100,100,8));for(const frame of [71,72]){present(videos.alpha,frame);move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.texImage2D(0,0,0,0,0,videos.alpha);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}present(videos.alpha,73);seam.onStandDown('alpha-final','after-feed');videos.alpha.__obedPosterHeld=true;videos.alpha.pause();location.hash='#14';for(let n=0;n<2;n++){move.gl.clear();move.gl.activeTexture(move.gl.TEXTURE0);move.gl.bindTexture(move.gl.TEXTURE_2D,texture);move.gl.uniformMatrix4fv(move.m,false,matrices.alpha);move.gl.drawArrays();tick()}videos.alpha.play();present(videos.alpha,74);videos.alpha.__obedInstance='alpha-end'}
videos.broken.drawSource=null;runChain(10,51,'3-canvas','alpha','alpha-hop');location.hash='#10';videos.alpha.__obedPosterHeld=true;videos.alpha.pause();videos.alpha.__obedPosterHeld=false;videos.alpha.play();runChain(11,61,'4-canvas','alpha-hop','alpha-final');runMidMoveStandDown();
videos.alpha.__obedInstance='dalpha';videos.broken.__obedInstance='dbroken';tick();
function screenRect(q,dx=0,dw=0){const left=stageX+q.x*stageSX+dx,top=stageY+q.y*stageSX,width=q.w*stageSX+dw,height=q.h*stageSX;return {x:left,y:top,left,top,right:left+width,bottom:top+height,width,height}}
location.hash='#20';stageX=10;stageY=20;stageSX=.5;stageSY=.5;videos.geo1.opacity='1';videos.geo2.opacity='1';
const q1={x:100,y:50,w:200,h:100},q2={x:400,y:50,w:200,h:100};videos.geo1.rect=screenRect(q1,.25,.25);videos.geo2.rect=screenRect(q2,1,0);
const geoMove=openContext('6-canvas'),geoTexture=posterTexture(geoMove,new ImageSource(100,100,8));geoMove.gl.clear();geoMove.gl.activeTexture(geoMove.gl.TEXTURE0);geoMove.gl.bindTexture(geoMove.gl.TEXTURE_2D,geoTexture);geoMove.gl.uniformMatrix4fv(geoMove.m,false,matrices.alpha);videos.geo1.visibility=false;videos.geo1.rect=screenRect(q1,100,100);tick();geoMove.gl.clear();videos.geo1.visibility=true;videos.geo1.rect=screenRect(q1);videos.geo2.rect=screenRect(q2);tick();geoMove.gl.clear();geoMove.gl.drawArrays();const firstCompletedAt=geoMove.gl.completedAt;
videos.geo1.rect=screenRect(q1,100,100);videos.geo2.rect=screenRect(q2,100,100);geoMove.gl.clear();geoMove.gl.activeTexture(geoMove.gl.TEXTURE0);geoMove.gl.bindTexture(geoMove.gl.TEXTURE_2D,geoTexture);geoMove.gl.uniformMatrix4fv(geoMove.m,false,matrices.alpha);geoMove.gl.drawArrays();videos.geo1.rect=screenRect(q1);videos.geo2.rect=screenRect(q2);const stickyMove=openContext('9-canvas');stickyMove.gl.clear();stageSY=.6;tick();stageSY=.5;
const repairedMove=openContext('15-canvas'),repairedTexture=posterTexture(repairedMove,new ImageSource(100,100,8));repairedMove.gl.clear();repairedMove.gl.activeTexture(repairedMove.gl.TEXTURE0);repairedMove.gl.bindTexture(repairedMove.gl.TEXTURE_2D,repairedTexture);repairedMove.gl.uniformMatrix4fv(repairedMove.m,false,matrices.alpha);tick();repairedMove.gl.clear();videos.geo1.visibility=false;videos.geo2.visibility=false;repairedMove.gl.drawArrays();videos.geo1.visibility=true;videos.geo2.visibility=true;
location.hash='#22';const coldMove=openContext('13-canvas'),coldTexture=posterTexture(coldMove,new ImageSource(100,100,8));coldMove.gl.activeTexture(coldMove.gl.TEXTURE0);coldMove.gl.bindTexture(coldMove.gl.TEXTURE_2D,coldTexture);coldMove.gl.texImage2D(0,0,0,0,0,videos.geo1);coldMove.canvas.isConnected=false;tick();
location.hash='#20';const unframed=openContext('7-canvas'),unframedTexture=posterTexture(unframed,new ImageSource(100,100,8));unframed.gl.activeTexture(unframed.gl.TEXTURE0);unframed.gl.bindTexture(unframed.gl.TEXTURE_2D,unframedTexture);unframed.gl.uniformMatrix4fv(unframed.m,false,matrices.alpha);unframed.gl.drawArrays();const unframedCompletedAt=unframed.gl.completedAt;
const thrownGl=makeGl();thrownGl.drawArrays=function(){this.completedAt=performance.now();throw new Error('draw failed')};const thrownCanvas=new Canvas('8-canvas',thrownGl);thrownGl.canvas=thrownCanvas;thrownCanvas.getContext('webgl');try{thrownGl.drawArrays()}catch(e){}
location.hash='#24';missingMove.gl.clear();missingMove.gl.activeTexture(missingMove.gl.TEXTURE0);missingMove.gl.bindTexture(missingMove.gl.TEXTURE_2D,missingTexture);missingMove.gl.texImage2D(0,0,0,0,0,videos.alpha);missingMove.gl.uniformMatrix4fv(missingMove.m,false,matrices.alpha);missingMove.gl.drawArrays();
function runRevisit(startFrame,id){location.hash='#25';tick();videos.revisit.__obedInstance='revisit';videos.revisit.__obedPosterHeld=true;for(const frame of [startFrame,startFrame+1,startFrame+2])present(videos.revisit,frame);videos.revisit.pause();const move=openContext(id),texture=posterTexture(move,new ImageSource(100,100,8));location.hash='#26';drawHeld(move,texture,videos.revisit,true);videos.revisit.play();present(videos.revisit,startFrame+3);move.canvas.isConnected=false;tick();location.hash='#24';tick()}
runRevisit(81,'11-canvas');runRevisit(101,'12-canvas');
location.hash='#27';tick();for(const frame of [111,112,113])present(videos.ordinal,frame);seam.onStandDown('ordinal','ordinal');videos.ordinal.__obedPosterHeld=true;videos.ordinal.pause();const ordinalMove=openContext('14-canvas'),ordinalTexture=posterTexture(ordinalMove,new NoPosterSource(100,100,8));location.hash='#28';drawHeld(ordinalMove,ordinalTexture,videos.ordinal,true);
location.hash='#29';tick();for(const frame of [121,122,123])present(videos.counter,frame);videos.counter.__obedPosterHeld=true;videos.counter.pause();const counterHoldMove=openContext('18-canvas'),counterHoldTexture=posterTexture(counterHoldMove,new ImageSource(1920,540,8));counterHoldMove.gl.layerSizes=[[1920,540]];location.hash='#30';for(let n=0;n<3;n++){counterHoldMove.gl.clear();counterHoldMove.gl.activeTexture(counterHoldMove.gl.TEXTURE0);counterHoldMove.gl.bindTexture(counterHoldMove.gl.TEXTURE_2D,counterHoldTexture);if(n===0)counterHoldMove.gl.texImage2D(0,0,0,0,0,videos.counter);counterHoldMove.gl.uniformMatrix4fv(counterHoldMove.m,false,matrices.counter);counterHoldMove.gl.drawArrays();tick()}videos.counter.play();present(videos.counter,124);
location.hash='#32';const transientMove=openContext('16-canvas');location.hash='#33';tick();transientMove.canvas.isConnected=false;tick();videos.alpha.__obedInstance='alpha-end';runChain(34,131,'17-canvas','alpha-end','alpha-n4');
location.hash='#36';tick();delete decoders.early;seam.claim('early');decoders.early=videos.early;location.hash='#37';tick();const earlyMove=openContext('19-canvas'),earlyTexture=posterTexture(earlyMove,new ImageSource(100,100,8));location.hash='#38';for(let n=0;n<3;n++){present(videos.early,141+n);earlyMove.gl.clear();earlyMove.gl.activeTexture(earlyMove.gl.TEXTURE0);earlyMove.gl.bindTexture(earlyMove.gl.TEXTURE_2D,earlyTexture);earlyMove.gl.texImage2D(0,0,0,0,0,videos.early);earlyMove.gl.uniformMatrix4fv(earlyMove.m,false,matrices.alpha);earlyMove.gl.drawArrays();tick()}
const queued=Object.values(videos).flatMap(v=>v.callbacks.map(row=>row[1])),instrumentGetContext=Canvas.prototype.getContext,productGl={},productGetContext=function(){return instrumentGetContext.apply(this,arguments)};Canvas.prototype.getContext=productGetContext;for(const name of ['texImage2D','activeTexture','bindTexture','pixelStorei','useProgram','getUniformLocation','uniform1f','uniformMatrix4fv','clear','drawArrays','drawElements']){const owned=gl[name];productGl[name]=function(){return owned.apply(gl,arguments)};gl[name]=productGl[name]}
const finalReport=window.__obedMmFeedProbe.report();window.__obedCost.stop();const costReport=window.__obedCost.read(),drawsAtReport=draws,readsAtReport=reads,glAtReport=glReads,contexts=Object.fromEntries(finalReport.contexts.map(c=>[c.id,c])),firstContext=contexts['6-canvas'],geoFrames=finalReport.frames.filter(f=>f.serial===firstContext.serial),stickyContext=contexts['9-canvas'],stickyFrames=finalReport.frames.filter(f=>f.serial===stickyContext.serial),stickyFrame=stickyFrames[stickyFrames.length-1],geometryFirst=geoFrames[0].riders.map(r=>[r.entryId,r.sourceRectError]),geometryAfterDraw=geoFrames.find(f=>f.riders.length&&f.riders.every(r=>r.sourceRectError===0)).riders.map(r=>[r.entryId,r.sourceRectError]),geometrySticky=stickyFrame.riders.map(r=>[r.entryId,r.sourceRectError]);
for(const callback of queued)callback(clock,{presentedFrames:999,mediaTime:33.3});while(raf.length)tick();canvas.getContext('webgl');gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures.alpha);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.useProgram(program);const postLoc=gl.getUniformLocation(program,'MVPMatrix');gl.uniform1f(mixLoc,1);gl.uniformMatrix4fv(postLoc,false,matrices.alpha);gl.texImage2D(0,0,0,0,0,posters.alpha);gl.clear();gl.drawArrays();gl.drawElements();videos.alpha.pause();videos.alpha.play();window.__OBED_MM_FEED__.once('alpha');seam.claim('alpha');seam.onStandDown('alpha','late');
const descriptorAfter=Object.getOwnPropertyDescriptor(window,'__OBED_CONTINUITY__');
const harnessChecks={probeVersion:window.__obedMmFeedProbe.version,geometryFirst,geometryAfterDraw,geometrySticky,rollover:[rolloverHigh.counter,rolloverZero.counter],framed:{completedAt:firstCompletedAt,firstDrawAt:contexts['6-canvas'].firstDrawAt},unframed:{completedAt:unframedCompletedAt,firstDrawAt:contexts['7-canvas'].firstDrawAt},thrown:{completedAt:thrownGl.completedAt,firstDrawAt:contexts['8-canvas'].firstDrawAt},unplanned:{count:finalReport.unplannedContextCount,contexts:['13-canvas','16-canvas'].filter(id=>contexts[id]),frames:finalReport.frames.filter(f=>f.atScene===null).length,uploads:finalReport.uploads.filter(row=>row.atScene===null).length},draws,reads,failedCaptureDraws,glReads,presentDraws,contextOptions,captureSizes,glReadRects,costReport,sameHookNesting:costState.sameHookNesting,nativeCostViolations,callbacksRemaining:Object.values(videos).reduce((n,v)=>n+v.callbacks.length,0),videoCancelled,post:{draws:draws-drawsAtReport,reads:reads-readsAtReport,glReads:glReads-glAtReport},frozen:Object.isFrozen(finalReport)&&Object.isFrozen(finalReport.frames[0].rows[0])&&window.__obedMmFeedProbe.report()===finalReport,removed,cancelled:cancelled.length,restored:{getContext:Canvas.prototype.getContext===productGetContext,pause:Media.prototype.pause===originalPause,play:Media.prototype.play===originalPlay,once:window.__OBED_MM_FEED__.once===originalOnce,decoderFor:seam.decoderFor===originalDecoderFor,claim:seam.claim===originalClaim,stand:seam.onStandDown===originalStand,draw:gl.drawArrays===productGl.drawArrays,upload:gl.texImage2D===productGl.texImage2D,draw2:holdMove.gl.drawArrays===originalDraw2,descriptor:descriptorAfter.value===continuityDescriptor.value&&descriptorAfter.writable===continuityDescriptor.writable&&descriptorAfter.configurable===continuityDescriptor.configurable}};
console.log(JSON.stringify({report:finalReport,harnessChecks}));
"""
    script = script.replace("LAYOUT", counter_layout)
    result = _node(script)
    report = result["report"]
    contexts = {row["id"]: row for row in report["contexts"]}
    checks = result["harnessChecks"]
    assert report["version"] == checks["probeVersion"] == 3
    assert dict(checks["geometryFirst"]) == {"geo-1": 1.0, "geo-2": 2.0}
    assert dict(checks["geometryAfterDraw"]) == {"geo-1": 0.0, "geo-2": 0.0}
    assert dict(checks["geometrySticky"]) == {"geo-1": None, "geo-2": None}
    assert checks["framed"]["firstDrawAt"] > checks["framed"]["completedAt"]
    assert checks["unframed"]["firstDrawAt"] > checks["unframed"]["completedAt"]
    assert checks["thrown"]["firstDrawAt"] is None
    assert checks["unplanned"] == {"count": 3, "contexts": [], "frames": 0, "uploads": 0}
    assert checks["rollover"] == [4095, 0]
    assert contract.first_errors(contract.mm_feed_report(report), limit=20) == []
    assert report["hookHealth"]["accountingComplete"] is True, json.dumps(report["hookHealth"], sort_keys=True)
    assert checks["costReport"]["stopped"] is True and checks["costReport"]["errors"] == []
    assert checks["sameHookNesting"] == 0
    assert checks["nativeCostViolations"] == 0
    assert {
        hook: report["hookHealth"]["hooks"][hook]["enterCount"]
        for hook in ("feed.raf", "feed.draw")
    } == {"feed.raf": 1274, "feed.draw": 336}
    for hook in contract.FEED_COST_HOOKS:
        health = report["hookHealth"]["hooks"][hook]
        recorded = checks["costReport"]["hooks"][hook]
        assert health["installed"] is True
        assert health["callbackCount"] == health["enterCount"] == health["leaveCount"] == recorded["count"]
        assert len(recorded["chunks"]) == recorded["count"]
    continuous_entries = [
        {"id": f"carry-{name}", "objectId": name, "dstObjectId": f"d{name}", "atScene": 2,
         "feed": {"draw": draw, "from": {"upload": draw, "size": size}, "to": None}}
        for name, draw, size in (("alpha", 1, [100, 100]), ("broken", 2, [100, 100]),
                                 ("counter", 3, [1920, 540]))
    ]
    continuous_entries.extend({
        "id": f"chain-{scene}", "objectId": object_id, "dstObjectId": dst_id, "atScene": scene,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None},
    } for scene, object_id, dst_id in ((10, "alpha", "alpha-hop"), (11, "alpha-hop", "alpha-final"),
                                      (34, "alpha-end", "alpha-n4")))
    early_entry = {
        "id": "carry-early-claim", "objectId": "early", "dstObjectId": "dearly", "atScene": 38,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None},
    }
    continuous_entries.append(early_entry)
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
    counter_hold_entry = [{"id": "carry-counter-hold", "objectId": "counter",
                           "dstObjectId": "dcounter", "atScene": 30,
                           "feed": {"draw": 1, "from": {"upload": 1, "size": [1920, 540]}, "to": None}}]
    counter_hold = feed.verdict_records(report, counter_hold_entry, continuous_expected=False)["carry-counter-hold"]
    stand_records = feed.verdict_records(report, stand_entry, continuous_expected=True)
    revisit_entry = [{"id": "carry-revisit", "objectId": "revisit", "dstObjectId": "drevisit", "atScene": 26,
                      "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None}}]
    revisit_records = feed.verdict_records(report, revisit_entry, continuous_expected=False)["carry-revisit"]
    early_record = feed.verdict_records(report, [early_entry], continuous_expected=True)["carry-early-claim"]
    for normalized in (records["carry-alpha"], hold_records["carry-hold"],
                       stand_records["chain-14"], revisit_records):
        assert contract.first_errors(contract.feed_verdict_record(normalized), limit=20) == []
    assert revisit_records["reason"] == "repeated visits are scored independently"
    assert [visit["departureExposure"]["visit"] for visit in revisit_records["visits"]] == [1, 2]
    assert [visit["hold"]["lastUploadedFrame"] for visit in revisit_records["visits"]] == [83, 103]
    assert report["sampling"]["entries"]["carry-revisit"]["references"] == 4
    assert all(feed.score_departure_exposure(visit["departureExposure"])["verdict"] is True
               for visit in revisit_records["visits"]), json.dumps(revisit_records["visits"], indent=2)
    assert early_record["mode"] == "continuous"
    assert early_record["departureExposure"]["complete"] is False
    early_claim = next(row for row in report["claims"] if row["entryId"] == "carry-early-claim")
    assert early_claim["decoder"] is None and early_claim["generation"] is None and early_claim["visit"] is None

    stale_report = json.loads(json.dumps(report))
    stale_serial = contexts["12-canvas"]["serial"]
    stale_departure = next(row for row in stale_report["departures"]
                           if row["entryId"] == "carry-revisit" and row["serial"] == stale_serial)
    stale_report["departures"].remove(stale_departure)
    stale_report["claims"].append({
        "objectId": "revisit", "entryId": "carry-revisit", "serial": stale_serial,
        "atScene": 26, "t": stale_departure["t"], "claimed": True,
        "generation": stale_departure["generation"], "visit": 1,
        "source": "claim", "decoder": stale_departure["decoder"],
    })
    assert contract.first_errors(contract.mm_feed_report(stale_report), limit=20) == []
    stale_visits = feed.verdict_records(
        stale_report, revisit_entry, continuous_expected=False,
    )["carry-revisit"]["visits"]
    assert stale_visits[1]["departureExposure"]["complete"] is False
    no_pause_entry = [{"id": "geo-1", "objectId": "geo1", "dstObjectId": "dgeo1", "atScene": 20,
                       "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None}}]
    no_pause = feed.verdict_records(report, no_pause_entry, continuous_expected=False)["geo-1"]
    assert all(visit["departureExposure"]["start"]["source"] == "context" for visit in no_pause["visits"])
    departure_verdicts = [feed.score_departure_exposure(visit["departureExposure"])["verdict"]
                          for visit in no_pause["visits"]]
    assert False in departure_verdicts and True in departure_verdicts and None in departure_verdicts, json.dumps(
        no_pause["visits"], indent=2,
    )
    assert False in [feed.score_poster_hold(visit["poster"])["verdict"] for visit in no_pause["visits"]]
    promoted_entry = [{"id": "source-missing", "objectId": "missing", "dstObjectId": "dmissing", "atScene": 24,
                       "feed": {"draw": 1, "from": {"upload": 1, "size": [100, 100]}, "to": None}}]
    promoted = feed.verdict_records(report, promoted_entry, continuous_expected=False)["source-missing"]
    assert promoted["mode"] == "unavailable"
    assert promoted["reason"] == "context became planned without complete evidence"
    assert feed.score_feed_live(promoted["feed"], continuous_expected=False)["verdict"] is None
    assert feed.score_no_rider_above_canvas(promoted["rider"])["verdict"] is None
    assert feed.score_labels_over_feed(promoted["labels"])["verdict"] is None
    assert feed.score_hold_frame(promoted["hold"])["verdict"] is None
    assert feed.score_poster_hold(promoted["poster"])["verdict"] is None
    assert feed.score_resume(promoted["resume"])["verdict"] is None
    assert feed.score_artwork_above(promoted["artwork"])["verdict"] is None
    assert feed.score_handback_continuity(promoted["handback"])["verdict"] is None
    assert feed.score_feed_live(records["carry-alpha"]["feed"])["verdict"] is True
    foreign = json.loads(json.dumps(report))
    next(row for row in foreign["uploads"]
         if row["serial"] == contexts["0-canvas"]["serial"] and row["frameN"] is not None)["serial"] = 3
    foreign_record = feed.verdict_records(foreign, continuous_entries, continuous_expected=True)["carry-alpha"]
    assert feed.score_feed_live(foreign_record["feed"])["verdict"] is None
    assert all(read["dVideo"] < 2 for read in records["carry-alpha"]["feed"]["reads"])
    assert feed.score_feed_live(records["carry-broken"]["feed"])["verdict"] is False
    assert records["carry-broken"]["feed"]["continuousCoverage"] is True
    assert feed.score_feed_live(records["carry-counter"]["feed"])["verdict"] is True
    assert feed.score_feed_live(records["chain-10"]["feed"])["verdict"] is True
    assert feed.score_feed_live(records["chain-11"]["feed"])["verdict"] is True
    assert records["chain-34"]["mode"] == "continuous" and "visits" not in records["chain-34"]
    assert not any(row["entryId"] == "chain-34" for row in report["departures"])
    assert feed.score_feed_live(records["chain-34"]["feed"])["verdict"] is True
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
    stand_resume = feed.score_resume(stand_records["chain-14"]["resume"])
    assert stand_resume["verdict"] is True
    assert stand_resume["report"] is False
    assert stand_resume["dropSize"] == 0
    assert all(read["kind"] == "counter" for read in records["carry-counter"]["feed"]["reads"]), json.dumps(
        records["carry-counter"]["feed"]["reads"]
    )
    counter_rows = [row for frame in report["frames"] for row in frame["rows"]
                    if row["entryId"] == "carry-counter"]
    assert all("holdMatch" not in row for row in counter_rows)
    hold_rows = [row for frame in report["frames"] for row in frame["rows"] if row["entryId"] == "carry-hold"]
    assert hold_rows and all(row["holdMatch"]["targetFrame"] == 33 for row in hold_rows)
    assert all(row["holdMatch"]["matches"] for row in hold_rows)
    counter_hold_rows = [row for frame in report["frames"] for row in frame["rows"]
                         if row["entryId"] == "carry-counter-hold"]
    assert counter_hold_rows and all(
        isinstance(row.get("holdMatch"), dict)
        and row["holdMatch"]["bestFrame"] == row["textures"][0]["presentedFrames"]
        for row in counter_hold_rows
    ), json.dumps(counter_hold_rows, indent=2)
    assert feed.score_hold_frame(counter_hold["hold"])["verdict"] is True
    ordinal_rows = [row for frame in report["frames"] for row in frame["rows"]
                    if row["entryId"] == "carry-ordinal"]
    assert ordinal_rows and all(row["feedRead"]["kind"] == "alpha" and row["feedRead"]["dVideo"] is not None
                                for row in ordinal_rows)
    assert all(row["holdMatch"]["matches"] and not any(match["poster"] for match in row["holdMatch"]["matches"])
               for row in ordinal_rows)
    missing_read = next(row["feedRead"] for frame in report["frames"] for row in frame["rows"]
                        if row["entryId"] == "source-missing")
    assert missing_read["referenceCounter"] is None and missing_read["referenceReason"] == "source"
    alpha_texture = next(row for frame in report["frames"] if frame["serial"] == contexts["0-canvas"]["serial"]
                         for row in frame["rows"] if row["entryId"] == "carry-alpha")["textures"][0]
    assert alpha_texture["size"] == [100, 100] and alpha_texture["uploadedSize"] == [160, 90]
    counter_texture = next(row for frame in report["frames"] if frame["serial"] == contexts["0-canvas"]["serial"]
                           for row in frame["rows"] if row["entryId"] == "carry-counter")["textures"][0]
    assert counter_texture["size"] == [1920, 540] and counter_texture["uploadedSize"] == [960, 270]
    assert [(row["entryId"], row["serial"]) for row in report["claims"]] == [
        ("carry-alpha", contexts["0-canvas"]["serial"]),
        ("carry-broken", contexts["0-canvas"]["serial"]),
        ("carry-counter", contexts["0-canvas"]["serial"]),
        ("chain-10", contexts["3-canvas"]["serial"]),
        ("chain-11", contexts["4-canvas"]["serial"]),
        ("chain-14", contexts["5-canvas"]["serial"]),
        ("chain-34", contexts["17-canvas"]["serial"]),
        ("carry-early-claim", contexts["19-canvas"]["serial"]),
    ]
    expected_departures = {
        ("carry-hold", contexts["1-canvas"]["serial"]),
        ("carry-killed", contexts["2-canvas"]["serial"]),
        ("chain-11", contexts["4-canvas"]["serial"]),
        ("chain-14", contexts["5-canvas"]["serial"]),
        ("carry-revisit", contexts["11-canvas"]["serial"]),
        ("carry-revisit", contexts["12-canvas"]["serial"]),
        ("carry-ordinal", contexts["14-canvas"]["serial"]),
        ("carry-counter-hold", contexts["18-canvas"]["serial"]),
        *((entry_id, contexts[context_id]["serial"])
          for context_id in ("6-canvas", "9-canvas", "15-canvas", "7-canvas", "8-canvas")
          for entry_id in ("geo-1", "geo-2")),
    }
    assert {(row["entryId"], row["serial"]) for row in report["departures"]} == expected_departures
    hold_departure = next(row for row in report["departures"] if row["entryId"] == "carry-hold")
    hold_context = contexts["1-canvas"]
    assert hold_departure["t"] < hold_context["createdAt"]
    assert hold_departure["generation"] > 0 and hold_departure["visit"] == 1
    assert [(row["entryId"], row["serial"]) for row in report["standDowns"]] == [
        ("carry-hold", contexts["1-canvas"]["serial"]),
        ("chain-14", contexts["5-canvas"]["serial"]),
        ("carry-ordinal", contexts["14-canvas"]["serial"]),
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
        "carry-revisit": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
        "carry-ordinal": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
        "carry-counter-hold": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
        "carry-early-claim": {"feed": {"draw": 1, "from": {"upload": 1}, "to": None}},
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
    poster_samples += sum(context_row["entryIds"] == ["carry-revisit"] for context_row in report["contexts"]) - 1
    poster_samples += "15-canvas" in contexts
    frame_samples = sum(row["decoder"] is not None for frame in report["frames"] for row in frame["rows"])
    presented_samples = sum(checks["presentDraws"])
    assert checks["failedCaptureDraws"] == 1
    expected_capture_count = poster_samples - checks["failedCaptureDraws"] \
        + frame_samples + presented_samples + len(checks["rollover"])
    assert checks["draws"] == checks["reads"] == expected_capture_count, (
        poster_samples, frame_samples, presented_samples,
    )
    counter_sampling = report["sampling"]["entries"]["carry-counter"]
    assert counter_sampling["references"] == report["sampling"]["referenceCapacity"]
    assert report["sampling"]["entries"]["chain-10"]["latestFrame"] == 54
    assert report["sampling"]["entries"]["chain-11"]["latestFrame"] == 70
    assert [(row["entryId"], row["complete"], len(row["frames"])) for row in report["handbacks"]] == [
        ("carry-killed", True, 3), ("carry-revisit", False, 0), ("carry-revisit", False, 0),
    ]
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


def _departure_record() -> dict:
    return {
        "complete": True, "entryId": "carry-a", "serial": 7, "atScene": 4,
        "visit": 2, "generation": 1, "decoder": {"instance": "a", "elId": 3},
        "context": {"serial": 7, "id": "7-canvas"},
        "start": {"t": 1.0, "source": "pause", "decoderVisible": True},
        "firstDraw": {"t": 2.0, "frameN": 9}, "ordering": True,
        "intervalCoverage": True, "posterExposure": False,
        "preDrawVisibility": [True], "hiddenWholePreDraw": False,
        "riders": [{"visible": False, "opacityProduct": 0.0, "intersectsCanvas": True}],
    }


def test_departure_exposure_scores_repaired_early_hide_overlay_and_missing() -> None:
    repaired = _departure_record()
    assert feed.score_departure_exposure(repaired)["verdict"] is True
    early_hide = {**repaired, "posterExposure": True, "preDrawVisibility": [True, False]}
    assert feed.score_departure_exposure(early_hide)["verdict"] is False
    all_hidden = {**repaired, "posterExposure": False, "preDrawVisibility": [False, False],
                  "hiddenWholePreDraw": True}
    hidden = feed.score_departure_exposure(all_hidden)
    assert hidden["verdict"] is None
    assert "decoder hidden for the whole pre-draw interval" in hidden["reason"]
    leading_hidden = {**repaired, "posterExposure": False, "preDrawVisibility": [False, True]}
    leading = feed.score_departure_exposure(leading_hidden)
    assert leading["verdict"] is None
    assert "pending owner classification" in leading["reason"]
    overlay = {**repaired, "riders": [{"visible": True, "opacityProduct": 1.0,
                                        "intersectsCanvas": True}]}
    assert feed.score_departure_exposure(overlay)["verdict"] is False
    missing = {**repaired, "visit": None}
    assert feed.score_departure_exposure(missing)["verdict"] is None


def _resume_record(*, source_advance: float = 1) -> dict:
    frame_duration = 1 / 30
    return {
        "complete": True, "mode": "departure", "mediaOverflow": 0,
        "holdPauseMissing": False, "clockReadable": True, "clockStill": True,
        "pauseTime": 1.0, "settleTime": 2.0, "pauseCurrentTime": 2.0,
        "settleCurrentTime": 2.0, "pauseFrame": 65, "firstAfterFrame": 67,
        "pauseMediaTime": 65 * frame_duration,
        "firstAfterMediaTime": (66 + source_advance) * frame_duration,
        "frameDurationS": frame_duration, "clockToleranceS": frame_duration * .49,
        "seeked": False, "resumedFromZero": False, "successfulFeed": True,
        "lastUploadedFrame": 66, "lastUploadedMediaTime": 66 * frame_duration,
        "departurePauseBeforeMove": True,
    }


def test_resume_reports_only_fully_evidenced_one_frame_drop() -> None:
    exact = feed.score_resume(_resume_record(source_advance=1))
    assert exact["verdict"] is True and exact["report"] is False and exact["exactHeldPlusOne"] is True
    one_drop_record = _resume_record(source_advance=2)
    poster_hold = feed.score_poster_hold(one_drop_record)
    assert poster_hold["verdict"] is True
    assert poster_hold["resumptionDiscontinuity"] == 0
    assert poster_hold["exactHeldPlusOne"] is True
    assert poster_hold["resumedFromPausePlusOne"] is True
    one_drop = feed.score_resume(one_drop_record)
    assert one_drop["verdict"] is True and one_drop["report"] is True and one_drop["dropSize"] == 1
    two_drop = feed.score_resume(_resume_record(source_advance=3))
    assert two_drop["verdict"] is False and two_drop["report"] is False and two_drop["dropSize"] == 2
    inconsistent = feed.score_resume(_resume_record(source_advance=1.45))
    assert inconsistent["verdict"] is None and inconsistent["report"] is False
    assert "clocks are inconsistent" in inconsistent["reason"]
    missing = _resume_record()
    missing.pop("firstAfterMediaTime")
    assert feed.score_resume(missing)["verdict"] is None


def test_alpha_hold_uses_measured_neighbourhood_and_counter_stays_exact() -> None:
    measured = [
        {"frame": 9, "poster": False, "distance": 1.0, "targetDistance": 2.0},
        {"frame": 10, "poster": False, "distance": 2.0, "targetDistance": 0.0},
        {"frame": 8, "poster": False, "distance": 8.0, "targetDistance": 8.0},
        {"frame": 0, "poster": True, "distance": 20.0, "targetDistance": 20.0},
    ]
    record = {
        "complete": True, "usableContext": True, "boundTextures": True, "mode": "departure",
        "mediaOverflow": 0, "successfulFeed": True, "lastUploadedFrame": 10,
        "reads": [{"phase": phase, "kind": "alpha", "bestFrame": 9, "matchMargin": 1.0,
                   "targetFrame": 10, "matches": measured} for phase in ("first", "middle", "last")],
    }
    verdict = feed.score_hold_frame(record)
    assert verdict["verdict"] is True and verdict["exactness"] == "neighbourhood"
    assert all(row["offsets"] == [-1, 0] for row in verdict["neighbourhood"])
    poster = json.loads(json.dumps(record))
    for read in poster["reads"]:
        read["bestFrame"] = 0
        for row in read["matches"]:
            if not row["poster"] and row["targetDistance"] < feed.ALPHA_HOLD_MARGIN:
                row["distance"] = 10.0
        next(row for row in read["matches"] if row["poster"])["distance"] = 0.0
    assert feed.score_hold_frame(poster)["verdict"] is False
    distinguishable = json.loads(json.dumps(record))
    for read in distinguishable["reads"]:
        read["bestFrame"] = 8
        for row in read["matches"]:
            if not row["poster"] and row["targetDistance"] < feed.ALPHA_HOLD_MARGIN:
                row["distance"] = 10.0
        next(row for row in read["matches"] if row["frame"] == 8)["distance"] = 0.0
    assert feed.score_hold_frame(distinguishable)["verdict"] is False
    unreadable = json.loads(json.dumps(record))
    unreadable["reads"][0]["matches"][0]["targetDistance"] = None
    assert feed.score_hold_frame(unreadable)["verdict"] is None
    counter = {**record, "reads": [{"phase": phase, "kind": "counter", "bestFrame": 10,
                                     "matchMargin": feed.COUNTER_HOLD_MARGIN}
                                    for phase in ("first", "middle", "last")]}
    assert feed.score_hold_frame(counter)["exactness"] == "exact"
    counter["reads"][1]["bestFrame"] = 9
    assert feed.score_hold_frame(counter)["verdict"] is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda rows: rows[-1].update(distance=5.2), "target/poster separation"),
        (lambda rows: rows[2].update(frame=3, distance=5.1, targetDistance=25.0),
         "target/distinguishable separation"),
        (lambda rows: rows[-1].update(distance=4.9, targetDistance=1.5),
         "poster indistinguishable from target"),
        (lambda rows: rows.pop(), "poster row missing"),
    ],
)
def test_alpha_hold_refuses_unseparated_or_unreadable_neighbourhoods(change: object, reason: str) -> None:
    measured = [
        {"frame": 10, "poster": False, "distance": 5.0, "targetDistance": 0.0},
        {"frame": 9, "poster": False, "distance": 5.0, "targetDistance": 2.0},
        {"frame": 8, "poster": False, "distance": 20.0, "targetDistance": 25.0},
        {"frame": 0, "poster": True, "distance": 20.0, "targetDistance": 30.0},
    ]
    change(measured)  # type: ignore[operator]
    record = {
        "complete": True, "usableContext": True, "boundTextures": True, "mode": "departure",
        "mediaOverflow": 0, "successfulFeed": True, "lastUploadedFrame": 10,
        "reads": [{"phase": phase, "kind": "alpha", "bestFrame": 10, "matchMargin": 0.1,
                   "targetFrame": 10, "matches": json.loads(json.dumps(measured))}
                  for phase in ("first", "middle", "last")],
    }
    verdict = feed.score_hold_frame(record)
    assert verdict["verdict"] is None, reason


def test_legacy_alpha_hold_keeps_the_base_margin() -> None:
    record = {
        "complete": True, "usableContext": True, "boundTextures": True, "mode": "departure",
        "mediaOverflow": 0, "successfulFeed": True, "lastUploadedFrame": 10,
        "reads": [{"phase": phase, "kind": "alpha", "bestFrame": 10,
                   "matchMargin": feed.ALPHA_HOLD_MARGIN - .1}
                  for phase in ("first", "middle", "last")],
    }
    assert feed.score_hold_frame(record)["verdict"] is None


def test_counter_deck_refuses_alpha_fallback_and_no_pause_is_a_control_failure() -> None:
    alpha = {"progress": .25, "patchInside": True, "coveredByLaterDraw": False, "kind": "alpha",
             "dVideo": 0.0, "dPoster": 20.0, "dSep": 20.0, "referenceCounter": None}
    live = {
        "complete": True, "mode": "continuous", "continuousCoverage": True,
        "usableContext": True, "boundTextures": True, "counterLayout": binary.layout(),
        "reads": [{**alpha, "progress": progress} for progress in feed.READ_PROGRESS],
        "presentedFrames": [1, 2], "maxInterFeedGapMs": 16.0,
    }
    refused = feed.score_feed_live(live)
    assert refused["verdict"] is None
    assert "counter-deck decoder reference" in refused["reason"]
    assert feed.score_poster_hold({"complete": True, "mediaOverflow": 0,
                                   "holdPauseMissing": True, "clockStill": None})["verdict"] is None
    assert feed.score_poster_hold({"complete": True, "mediaOverflow": 0,
                                   "holdPauseMissing": True, "clockStill": False})["verdict"] is False


def test_normalization_marks_real_d7_aspect_but_not_alpha_as_counter_deck() -> None:
    def normalize(size: list[int]) -> dict:
        entry = {"id": "b0to1:counter-a.mov#1->counter-a.mov#1:carry", "objectId": "counter-a",
                 "dstObjectId": "counter-a-next", "atScene": 2,
                 "feed": {"draw": 1, "from": {"upload": 1, "size": size}, "to": None}}
        row = {"serial": 1, "atScene": 2, "entryId": entry["id"], "objectId": "counter-a",
               "t": 2.0, "textures": [{"ordinal": 1, "size": size}], "decoder": None}
        report = {
            "version": 2, "config": {"counterLayout": binary.layout()},
            "contexts": [{"serial": 1, "id": "0-canvas", "createdAt": 1.0, "firstDrawAt": 2.0,
                          "closedAt": None, "lost": False, "atScene": 2, "entryIds": [entry["id"]]}],
            "frames": [{"serial": 1, "atScene": 2, "n": 1, "t": 2.0, "frameTime": 2.0,
                        "draws": 1, "rows": [row], "labels": [], "riders": [], "labelExpected": []}],
            "media": [], "mediaDropped": [], "mediaOverflow": 0, "artwork": [], "uploads": [],
            "claims": [{"entryId": entry["id"], "objectId": "counter-a", "atScene": 2,
                        "serial": 1, "claimed": True}],
            "standDowns": [], "departures": [], "handbacks": [], "browserFrames": [],
        }
        return feed.verdict_records(report, [entry], continuous_expected=True)[entry["id"]]

    assert normalize([800, 225])["feed"]["counterLayout"] == binary.layout()
    assert normalize([484, 272])["feed"]["counterLayout"] is None

from __future__ import annotations

import copy
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
    assert result == [
        binary.decode_counter(case["levels"], case.get("layout", binary.layout()))
        for case in binary.decoder_conformance_vectors()
    ]


def test_realistic_fake_gl_sampling_lifecycle_and_shutdown() -> None:
    instrument = json.dumps(feed.INSTRUMENT_JS)
    counter_layout = json.dumps(binary.layout())
    script = r"""
const layout=LAYOUT;let now=0,raf=[],cancelled=[],draws=0,reads=0,removed=0,contexts=[],failRead=false;
global.window=global;global.location={hash:'#1'};global.performance={now:()=>++now};
global.requestAnimationFrame=fn=>(raf.push(fn),raf.length);global.cancelAnimationFrame=id=>cancelled.push(id);
class Media{pause(){this.paused=true}play(){this.paused=false;return Promise.resolve()}}
const originalPause=Media.prototype.pause,originalPlay=Media.prototype.play;
class Video extends Media{
  constructor(id='movie-a',counter=true){super();this.__obedInstance=id;this.__obedElId=id.length;this.counter=counter;this.currentTime=0;this.paused=false;this.readyState=4;this.videoWidth=1920;this.videoHeight=540;this.width=1920;this.height=540;this.frame=0;this.callbacks=[];this.listeners=[];this.isConnected=true;this.nodeType=1;this.parentElement=null}
  addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){removed+=this.listeners.some(row=>row[0]===k&&row[1]===f)?1:0;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}
  requestVideoFrameCallback(f){this.callbacks.push(f);return this.callbacks.length}cancelVideoFrameCallback(){this.callbacks=[]}checkVisibility(){return true}
  getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:1920,bottom:540,width:1920,height:540}}
  present(frame){this.frame=frame;this.currentTime=frame/30;const pending=this.callbacks.splice(0);pending.forEach(cb=>cb(now,{presentedFrames:frame,mediaTime:frame/30}))}
  pixel(x,y){const value=this.frame&4095;if(this.counter){const bits=[1,0,...Array.from({length:12},(_,i)=>(value>>(11-i))&1),0,0,1];bits[14]=bits.slice(2,14).reduce((a,b)=>a+b,0)%2;for(let i=0;i<layout.blockRects.length;i++){const r=layout.blockRects[i];if(x>=r[0]&&x<r[0]+r[2]&&y>=r[1]&&y<r[1]+r[3])return bits[i]?255:0}}return 30+((Math.floor(x/80)+Math.floor(y/60)+value)%8)*20}
}
class ImageSource{constructor(value){this.width=1920;this.height=540;this.naturalWidth=1920;this.naturalHeight=540;this.value=value}pixel(){return this.value}}
class Context2D{
  constructor(canvas){this.canvas=canvas;this.data=new Uint8ClampedArray(0);this.options=null}ensure(){const n=this.canvas.width*this.canvas.height*4;if(this.data.length!==n)this.data=new Uint8ClampedArray(n)}
  drawImage(source,sx,sy,sw,sh,dx,dy,dw,dh){this.ensure();draws++;for(let y=0;y<dh;y++)for(let x=0;x<dw;x++){const value=source.pixel(sx+(x+.5)*sw/dw,sy+(y+.5)*sh/dh),i=((dy+y)*this.canvas.width+dx+x)*4;this.data[i]=this.data[i+1]=this.data[i+2]=value;this.data[i+3]=255}}
  getImageData(x,y,w,h){this.ensure();reads++;if(failRead){failRead=false;throw new Error('read failed')}const out=new Uint8ClampedArray(w*h*4);for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const a=((y+yy)*this.canvas.width+x+xx)*4,b=(yy*w+xx)*4;out.set(this.data.slice(a,a+4),b)}return {data:out}}
}
class Canvas{
  constructor(id='',gl=null){this.id=id;this._gl=gl;this._2d=new Context2D(this);this.width=0;this.height=0;this.isConnected=true;this.nodeType=1;this.parentElement=null;this.listeners=[]}
  getContext(kind,options){if(kind==='2d'){this._2d.options=options;contexts.push(options);return this._2d}return this._gl}
  addEventListener(k,f){this.listeners.push([k,f])}removeEventListener(k,f){removed+=this.listeners.some(row=>row[0]===k&&row[1]===f)?1:0;this.listeners=this.listeners.filter(row=>row[0]!==k||row[1]!==f)}
  getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:1920,bottom:540,width:1920,height:540}}
}
global.HTMLMediaElement=Media;global.HTMLVideoElement=Video;global.HTMLCanvasElement=Canvas;
const originalGetContext=Canvas.prototype.getContext,stage={offsetWidth:1920,offsetHeight:540,contains:()=>true,querySelectorAll:()=>[],getBoundingClientRect:()=>({x:0,y:0,left:0,top:0,right:1920,bottom:540,width:1920,height:540})};
global.getComputedStyle=el=>({opacity:el instanceof Video?'0':'1',display:'block',visibility:'visible',position:'static',zIndex:'auto'});
global.document={timeline:{get currentTime(){return now}},createElement:k=>k==='canvas'?new Canvas():{nodeType:1,parentElement:null},getElementById:id=>id==='stage'?stage:null};
let decoder=null,decoders={};const originalClaim=()=>true,originalStand=()=>true,seam={decoderFor:id=>decoders[id]||null,claim:originalClaim,onStandDown:originalStand};global.__OBED_P2_PRESERVE__={feed:seam};
const feedPlan={draw:1,from:{upload:1,size:[1920,540]},to:null},entry={id:'carry-a',objectId:'movie-a',dstObjectId:'movie-b',atScene:2,feed:feedPlan,draws:{drawCount:1,draws:[{draw:1,layerSize:[1920,540],labelBoxOpacity:null}]},artwork:[],srcRect:{x:0,y:0,w:1920,h:540}};
const alphaEntry={id:'carry-alpha',objectId:'movie-c',dstObjectId:'movie-d',atScene:4,feed:feedPlan,draws:entry.draws,artwork:[],srcRect:entry.srcRect};
global.__OBED_CONTINUITY__={boundaries:[{atScene:2,src:{objectId:'movie-a'},dst:{objectId:'movie-b'},feed:feedPlan},{atScene:4,src:{objectId:'movie-c'},dst:{objectId:'movie-d'},feed:feedPlan}]};
eval(INSTRUMENT);window.__obedMmFeedProbe.bootstrap({entries:[entry,alphaEntry],counterLayout:layout});
function tick(){const pending=raf.splice(0);pending.forEach(callback=>callback(now))}tick();const idle={draws,reads};decoder=new Video();decoders['movie-a']=decoder;tick();
for(let frame=1;frame<=20;frame++)decoder.present(frame);
const ringBefore={draws,reads};decoder.frame=4095;const wrapHigh=window.__obedMmFeedProbe.sample(decoder,{size:[1920,540],state:{},layout});decoder.frame=4096;const wrapZero=window.__obedMmFeedProbe.sample(decoder,{size:[1920,540],state:{},layout});
decoder.frame=37;const directBefore={draws,reads};const direct=window.__obedMmFeedProbe.sample(decoder,{size:[1920,540],state:{},layout});const directCounts={draws:draws-directBefore.draws,reads:reads-directBefore.reads};
const sourceFailure=window.__obedMmFeedProbe.sample(null,{size:[1920,540],state:{},layout}),badLayout=JSON.parse(JSON.stringify(layout));badLayout.blockRects[0][0]=-1;
const boundsFailure=window.__obedMmFeedProbe.sample(decoder,{size:[1920,540],state:{},layout:badLayout});failRead=true;const readFailure=window.__obedMmFeedProbe.sample(decoder,{size:[1920,540],state:{},layout});
decoder.__obedPosterHeld=true;decoder.pause();
let active=1,bound={},program={},matrixLoc={},sources=new WeakMap(),glReads=0,pixels=new Uint8Array(1920*540*4);
function makeGl(){return {canvas:null,TEXTURE0:1,TEXTURE_2D:2,UNPACK_FLIP_Y_WEBGL:3,UNPACK_PREMULTIPLY_ALPHA_WEBGL:4,RGBA:5,UNSIGNED_BYTE:6,drawingBufferWidth:1920,drawingBufferHeight:540,
 activeTexture(v){active=v},bindTexture(t,v){bound[active]=v},pixelStorei(){},useProgram(){},getUniformLocation(){return matrixLoc},uniform1f(){},uniformMatrix4fv(){},clear(){pixels.fill(0)},drawArrays(){},drawElements(){},texImage2D(){sources.set(bound[active],arguments[5])},readPixels(x,y,w,h,f,t,out){glReads++;for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++){const value=decoder.pixel(x+xx,y+yy),i=(yy*w+xx)*4;out[i]=out[i+1]=out[i+2]=value;out[i+3]=255}}}}
const gl=makeGl();
const glOriginal={drawArrays:gl.drawArrays,texImage2D:gl.texImage2D},canvas=new Canvas('0-canvas',gl);gl.canvas=canvas;canvas.getContext('webgl');gl.useProgram(program);const loc=gl.getUniformLocation(program,'MVPMatrix');
const texture={};gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(0,0,0,0,0,new ImageSource(8));seam.claim('movie-a');location.hash='#2';
decoder.__obedPosterHeld=false;decoder.play();for(let frame=21;frame<=24;frame++){decoder.present(frame);gl.clear();gl.texImage2D(0,0,0,0,0,decoder);gl.uniformMatrix4fv(loc,false,[2/1920,0,0,0,0,2/540,0,0,0,0,1,0,-1,-1,0,1]);gl.drawArrays();tick()}
canvas.isConnected=false;tick();for(let frame=25;frame<=27;frame++)decoder.present(frame);
location.hash='#3';decoder=new Video('movie-c',false);decoders['movie-c']=decoder;tick();for(let frame=1;frame<=18;frame++)decoder.present(frame);
const gl2=makeGl(),canvas2=new Canvas('1-canvas',gl2);gl2.canvas=canvas2;canvas2.getContext('webgl');gl2.useProgram(program);const loc2=gl2.getUniformLocation(program,'MVPMatrix'),texture2={};gl2.activeTexture(gl2.TEXTURE0);gl2.bindTexture(gl2.TEXTURE_2D,texture2);gl2.texImage2D(0,0,0,0,0,new ImageSource(8));seam.claim('movie-c');location.hash='#4';
for(let frame=19;frame<=21;frame++){decoder.present(frame);gl2.clear();gl2.texImage2D(0,0,0,0,0,decoder);gl2.uniformMatrix4fv(loc2,false,[2/1920,0,0,0,0,2/540,0,0,0,0,1,0,-1,-1,0,1]);gl2.drawArrays();tick()}
const first=window.__obedMmFeedProbe.report(),drawsAtReport=draws,readsAtReport=reads,glAtReport=glReads;while(raf.length)tick();decoder.present(28);const second=window.__obedMmFeedProbe.report();
console.log(JSON.stringify({direct,directCounts,wrapHigh,wrapZero,sourceFailure,boundsFailure,readFailure,idle,ringBefore,draws,reads,glReads,report:first,same:first===second,frozen:Object.isFrozen(first),post:{draws:draws-drawsAtReport,reads:reads-readsAtReport,glReads:glReads-glAtReport},
 options:contexts,restored:{pause:Media.prototype.pause===originalPause,play:Media.prototype.play===originalPlay,getContext:Canvas.prototype.getContext===originalGetContext,draw:gl.drawArrays===glOriginal.drawArrays,upload:gl.texImage2D===glOriginal.texImage2D,draw2:gl2.__obedMmFeedProbe===undefined,claim:seam.claim===originalClaim,stand:seam.onStandDown===originalStand},removed,cancelled:cancelled.length,configureAfter:window.__obedMmFeedProbe.configure({})}));
""".replace("LAYOUT", counter_layout).replace("INSTRUMENT", instrument)
    result = _node(script)
    assert result["idle"] == {"draws": 0, "reads": 0}
    assert result["ringBefore"] == {"draws": 20, "reads": 20}
    assert result["direct"]["counter"] == 37 and result["direct"]["reason"] is None
    assert result["directCounts"] == {"draws": 1, "reads": 1}
    assert [result[name]["reason"] for name in ("sourceFailure", "boundsFailure", "readFailure")] == [
        "source", "bounds", "read",
    ]
    assert (result["wrapHigh"]["counter"], result["wrapZero"]["counter"]) == (4095, 0), (
        result["wrapHigh"], result["wrapZero"],
    )
    assert result["draws"] == result["reads"]
    assert result["draws"] == 57
    assert all(options == {"willReadFrequently": False} for options in result["options"])
    report = result["report"]
    assert report["errors"] == []
    assert report["sampling"]["referenceCapacity"] == 18
    assert report["sampling"]["entries"]["carry-a"]["references"] == 18
    assert report["sampling"]["entries"]["carry-a"]["latestFrame"] == 24
    assert report["sampling"]["entries"]["carry-alpha"]["references"] == 18
    assert report["sampling"]["entries"]["carry-alpha"]["latestFrame"] == 21
    assert report["departures"][0]["entryId"] == "carry-a"
    assert report["handbacks"][0]["complete"] is True and len(report["handbacks"][0]["frames"]) == 3
    counter_reads = [row["feedRead"] for frame in report["frames"] for row in frame["rows"]
                     if row["entryId"] == "carry-a"]
    assert [read["referenceCounter"] for read in counter_reads] == [21, 22, 23, 24]
    assert all(read["counterReason"] is None for read in counter_reads)
    alpha_reads = [row["feedRead"] for frame in report["frames"] for row in frame["rows"]
                   if row["entryId"] == "carry-alpha"]
    assert len(alpha_reads) == 3 and all(read["kind"] == "alpha" for read in alpha_reads)
    assert result["glReads"] == len(report["frames"])
    assert contract.first_errors(contract.mm_feed_report(report), limit=40) == []
    entry = {
        "id": "carry-a", "objectId": "movie-a", "dstObjectId": "movie-b", "atScene": 2,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [1920, 540]}, "to": None},
    }
    record = feed.verdict_records(report, [entry], continuous_expected=True)["carry-a"]
    alpha_entry = {
        "id": "carry-alpha", "objectId": "movie-c", "dstObjectId": "movie-d", "atScene": 4,
        "feed": {"draw": 1, "from": {"upload": 1, "size": [1920, 540]}, "to": None},
    }
    alpha_record = feed.verdict_records(report, [alpha_entry], continuous_expected=True)["carry-alpha"]
    assert feed.score_feed_live(record["feed"])["verdict"] is True
    assert feed.score_feed_live(alpha_record["feed"])["verdict"] is True
    assert feed.score_no_rider_above_canvas(record["rider"])["verdict"] is True

    broken_feed = copy.deepcopy(alpha_record["feed"])
    broken_feed["reads"][1]["dVideo"] = broken_feed["reads"][1]["dPoster"]
    assert feed.score_feed_live(broken_feed)["verdict"] is False
    assert broken_feed["continuousCoverage"] is True
    counter_feed = record["feed"]
    chain_10_feed = copy.deepcopy(alpha_record["feed"])
    chain_11_feed = copy.deepcopy(alpha_record["feed"])
    assert feed.score_feed_live(counter_feed)["verdict"] is True
    assert feed.score_feed_live(chain_10_feed)["verdict"] is True
    assert feed.score_feed_live(chain_11_feed)["verdict"] is True
    stood_down_feed = copy.deepcopy(alpha_record["feed"])
    stood_down_feed["mode"] = "standDown"
    assert feed.score_feed_live(stood_down_feed)["verdict"] is False
    assert feed.score_labels_over_feed({
        "coverage": True, "labels": [{"opacity": .61, "spread": 30.0, "slope": .39}],
    })["verdict"] is True
    assert feed.score_artwork_above({"reads": [{"artworkAbove": True}]})["verdict"] is True
    assert feed.score_artwork_above({"reads": [{"artworkAbove": False}]})["verdict"] is False
    assert feed.score_hold_frame(alpha_record["hold"])["verdict"] is None

    def hold_record(mode: str = "departure") -> dict:
        target = 42 if mode == "departure" else 41
        return {
            "mode": mode, "usableContext": True, "boundTextures": True,
            "lastPresentedBeforeDeparture": 42, "lastUploadedFrame": target,
            "successfulFeed": True, "advancedDecoder": True, "reuploadAfterStandDown": False,
            "reads": [{"phase": phase, "bestFrame": target, "kind": "alpha", "matchMargin": 8.0}
                      for phase in ("first", "middle", "last")],
        }

    def poster_record(mode: str = "departure") -> dict:
        return {
            "mode": mode, "pauseTime": 1.0, "settleTime": 2.5, "pauseCurrentTime": 5.0,
            "settleCurrentTime": 5.0, "pauseFrame": 42, "firstAfterFrame": 43, "seeked": False,
            "pauseMediaTime": 5.0, "firstAfterMediaTime": 5.0 + 1 / 30, "frameDurationS": 1 / 30,
            "clockToleranceS": .49 / 30, "resumedFromZero": False, "lastUploadedFrame": 41,
            "lastUploadedMediaTime": 5.0 - 1 / 30, "successfulFeed": mode == "standDown",
            "clockReadable": True, "clockStill": True, "departurePauseBeforeMove": True,
            "holdPauseMissing": False,
        }

    departure_hold = hold_record()
    departure_poster = poster_record()
    killed_hold = hold_record()
    killed_hold["reads"][-1]["bestFrame"] = 0
    killed_poster = poster_record()
    stand_hold = hold_record("standDown")
    assert feed.score_hold_frame(departure_hold)["verdict"] is True
    assert feed.score_poster_hold(departure_poster)["verdict"] is True
    assert feed.score_hold_frame(killed_hold)["verdict"] is False
    assert feed.score_poster_hold(killed_poster)["verdict"] is True
    assert feed.score_hold_frame(stand_hold)["verdict"] is True
    stand_poster = feed.score_poster_hold(poster_record("standDown"))
    assert stand_poster["verdict"] is True
    assert stand_poster["resumptionDiscontinuity"] == 1
    assert stand_poster["exactHeldPlusOne"] is False
    assert result["same"] is True and result["frozen"] is True
    assert result["post"] == {"draws": 0, "reads": 0, "glReads": 0}
    assert all(result["restored"].values())
    assert result["removed"] >= 2 and result["cancelled"] >= 1
    assert result["configureAfter"] is False

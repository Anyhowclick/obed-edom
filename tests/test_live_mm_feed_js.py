"""Contract tests for the Stage B Magic Move texture-feed module."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from obed_edom import live_mm_feed_js

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import mm_feed_variants  # noqa: E402
import mm_feed_instrument  # noqa: E402

NODE = shutil.which("node")
PINNED_MM_FEED_SHA256 = "f1fe0dd644359962c4c71cce46424ac3e24eb4ac42d1f9053a103d24463b81bf"


def _entry(
    object_id: str = "A",
    *,
    draw: int = 1,
    draw_count: int = 1,
    upload: int = 1,
    size: tuple[int, int] = (320, 180),
    to: tuple[int, tuple[int, int]] | None = None,
) -> dict:
    return {
        "atScene": 2,
        "action": "bridge",
        "movieKey": object_id.lower(),
        "underArtwork": True,
        "src": {"objectId": object_id, "rect": {"x": 0, "y": 0, "w": 10, "h": 10}},
        "dst": {"objectId": f"{object_id}2", "rect": {"x": 0, "y": 0, "w": 10, "h": 10}},
        "feed": {
            "draw": draw,
            "drawCount": draw_count,
            "from": {"upload": upload, "size": list(size)},
            "to": None if to is None else {"upload": to[0], "size": list(to[1])},
        },
    }


def _plan(*entries: dict) -> dict:
    return {
        "schema": 2,
        "movies": {entry["movieKey"]: {"assetKeys": [f'{entry["movieKey"]}.mov']} for entry in entries},
        "boundaries": list(entries),
    }


_HARNESS = r"""
const assert = require('assert');
global.window = global;
global.location = {hash:'#1'};
let clock = 100;
global.performance = {now(){ clock += 5; return clock; }};
const raf = [];
global.requestAnimationFrame = function(fn){ raf.push(fn); return raf.length; };

class Media {
  pause(){ this.paused=true; }
  play(){ this.paused=false; return Promise.resolve(); }
  addEventListener(){}
}
global.HTMLMediaElement = Media;
class Video extends Media {
  constructor(name){
    super();
    this.name=name; this.readyState=2; this.videoWidth=320; this.videoHeight=180; this.currentTime=1;
    this.paused=true; this.__obedInstance=name; this.isConnected=true; this.nodeType=1; this.parentElement=null;
  }
  getBoundingClientRect(){ return {x:0,y:0,left:0,top:0,width:320,height:180,right:320,bottom:180}; }
  checkVisibility(){ return true; }
}
global.HTMLVideoElement = Video;
global.getComputedStyle = function(){ return {opacity:'1',display:'block',visibility:'visible'}; };

const warmUploads = [];
function makeGl(name){
  const gl = {
    name, TEXTURE0:33984, TEXTURE_2D:3553, ACTIVE_TEXTURE:34016,
    CURRENT_PROGRAM:35725, TEXTURE_BINDING_2D:32873,
    UNPACK_FLIP_Y_WEBGL:37440, UNPACK_PREMULTIPLY_ALPHA_WEBGL:37441,
    RGBA:6408, UNSIGNED_BYTE:5121, NO_ERROR:0,
    active:33984, program:null, flip:false, premultiply:false, nextError:0,
    bindings:new Map(), videoUploads:[], calls:[], textureN:0,
    drawingBufferWidth:1920, drawingBufferHeight:1080,
    getParameter(p){
      if(p===this.ACTIVE_TEXTURE)return this.active;
      if(p===this.CURRENT_PROGRAM)return this.program;
      if(p===this.TEXTURE_BINDING_2D)return this.bindings.get(this.active)||null;
      if(p===this.UNPACK_FLIP_Y_WEBGL)return this.flip;
      if(p===this.UNPACK_PREMULTIPLY_ALPHA_WEBGL)return this.premultiply;
      return null;
    },
    createTexture(){ return {name:name+'-warm-'+(++this.textureN)}; },
    deleteTexture(t){ this.calls.push(['deleteTexture',t]); },
    activeTexture(unit){ this.active=unit; this.calls.push(['activeTexture',unit]); },
    bindTexture(target,texture){ if(target===this.TEXTURE_2D)this.bindings.set(this.active,texture); this.calls.push(['bindTexture',this.active,texture]); },
    pixelStorei(p,value){ if(p===this.UNPACK_FLIP_Y_WEBGL)this.flip=!!value; if(p===this.UNPACK_PREMULTIPLY_ALPHA_WEBGL)this.premultiply=!!value; },
    texImage2D(){
      const args=Array.from(arguments), source=args.length<9?args[5]:null;
      if(source instanceof Video){
        const row={source,texture:this.bindings.get(this.active)||null,unit:this.active,flip:this.flip,premultiply:this.premultiply};
        this.videoUploads.push(row); if(name==='warm')warmUploads.push(row);
      }
    },
    useProgram(program){ this.program=program; },
    getUniformLocation(program,uniform){ return {program,uniform}; },
    uniform1f(){}, uniform1fv(){}, uniformMatrix4fv(){},
    clear(){ this.calls.push(['clear']); },
    drawArrays(){ this.calls.push(['drawArrays']); },
    drawElements(){ this.calls.push(['drawElements']); },
    readPixels(x,y,w,h,format,type,pixels){ pixels.fill(0); },
    getError(){ const value=this.nextError; this.nextError=0; return value; }
  };
  return gl;
}

const warmGl = makeGl('warm');
let baseCalls = 0, preCalls = 0, g2Calls = 0;
const fake2d = {
  clearRect(){}, drawImage(){},
  getImageData(){ return {data:new Uint8Array(81*30*4)}; }
};
class Canvas {
  constructor(id,gl){
    this.id=id||''; this._gl=gl||warmGl; this._gl.canvas=this;
    this.width=1920; this.height=1080; this.listeners={}; this.isConnected=true;
  }
  addEventListener(name,fn){ this.listeners[name]=fn; }
  dispatch(name){ if(this.listeners[name])this.listeners[name]({type:name}); }
  getBoundingClientRect(){ return {x:0,y:0,left:0,top:0,width:1920,height:1080,right:1920,bottom:1080}; }
}
Canvas.prototype.getContext = function(type){ baseCalls++; return type==='2d'?fake2d:this._gl; };
const baseGetContext = Canvas.prototype.getContext;
Canvas.prototype.getContext = function(){ preCalls++; return baseGetContext.apply(this,arguments); };
Canvas.prototype.getContext.__obedMmFeedProbe = 1;
const preGetContext = Canvas.prototype.getContext;
Canvas.prototype.getContext = function(){ g2Calls++; return preGetContext.apply(this,arguments); };
Canvas.prototype.getContext.__obedGlReplay = 1;
global.HTMLCanvasElement = Canvas;
global.document = {
  timeline:{currentTime:0}, head:null, documentElement:null,
  createElement(name){ assert.strictEqual(name,'canvas'); return new Canvas('',warmGl); },
  getElementById(){ return null; }, elementsFromPoint(){ return []; }
};

const decoders = {A:new Video('A'), B:new Video('B')};
const calls = {decoder:[],claim:[],stand:[]};
let claimResult = true;
let snapshotScene = 1, snapshotBusy = false, snapshotState = 'IdleAtFinalState';
global.__OBED_P2_PRESERVE__ = {feed:{
  version:1,
  decoderFor(id){ calls.decoder.push(id); return decoders[id]||null; },
  claim(id){ calls.claim.push({id,scene:location.hash,snapshot:global.__obedLive.snapshot()}); return claimResult; },
  onStandDown(id,reason){ calls.stand.push({id,reason,late:false}); return true; },
  note(){}
}};
global.__obedLive = {snapshot(){ return {playerState:snapshotState,busy:snapshotBusy,sceneId:snapshotScene}; }};
global.__OBED_CONTINUITY__ = PLAN;

function texture(name){ return {name}; }
function upload(gl,tex,size,unit,flip,premultiply){
  gl.activeTexture(gl.TEXTURE0+unit);
  gl.bindTexture(gl.TEXTURE_2D,tex);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,flip);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,premultiply);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,{width:size[0],height:size[1]});
}
function bind(gl,tex,unit){ gl.activeTexture(gl.TEXTURE0+unit); gl.bindTexture(gl.TEXTURE_2D,tex); }
function program(gl,mix){
  const value={mix}; gl.useProgram(value);
  if(mix==='present'){ const loc=gl.getUniformLocation(value,'mixFactor'); gl.uniform1f(loc,0.5); }
  if(mix==='known'){ gl.getUniformLocation(value,'mixFactor'); }
  return value;
}
function idleTick(){ const fn=raf.shift(); assert(fn); fn(); }
"""


def _run_node(
    plan: dict,
    scenario: str,
    *,
    continuous: bool = True,
    once: bool = True,
    script: str | None = None,
    before_module: str = "",
    constants: dict[str, str] | None = None,
) -> None:
    if NODE is None:
        pytest.skip("node is not installed")
    source = script or live_mm_feed_js.mm_feed_script(continuous=continuous, once=once)
    match = re.fullmatch(r'<script id="obed-mm-feed">(.*)</script>\n', source, re.DOTALL)
    assert match
    code = (
        "const PLAN="
        + json.dumps(plan, separators=(",", ":"))
        + ";\nconst MODULE="
        + json.dumps(match.group(1))
        + ";\n"
        + "".join(
            f"const {name}={json.dumps(value)};\n"
            for name, value in (constants or {}).items()
        )
        + _HARNESS
        + "\n"
        + before_module
        + "\neval(MODULE);\nassert(global.__OBED_MM_FEED__);\n"
        + scenario
    )
    completed = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr


def test_python_api_version_sha_flags_and_script_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    assert live_mm_feed_js.MM_FEED_VERSION == 1
    expected = hashlib.sha256(live_mm_feed_js.MM_FEED_JS.encode()).hexdigest()
    assert live_mm_feed_js.js_sha256() == expected == PINNED_MM_FEED_SHA256
    assert live_mm_feed_js.PINNED_MM_FEED_SHA256 == PINNED_MM_FEED_SHA256
    script = live_mm_feed_js.mm_feed_script(continuous=True, once=False)
    assert script.startswith('<script id="obed-mm-feed">') and script.endswith("</script>\n")
    assert "var CONTINUOUS = true;" in script and "var ONCE = false;" in script
    assert "__OBED_MM_FEED_CONTINUOUS__" not in script
    assert "__OBED_MM_FEED_ONCE__" not in script
    assert "</script" not in script.removesuffix("</script>\n")
    monkeypatch.setattr(live_mm_feed_js, "MM_FEED_JS", "x</ScRiPt y")
    assert "x<\\/ScRiPt y" in live_mm_feed_js.mm_feed_script(continuous=False, once=True)
    with pytest.raises(TypeError, match="must be bool"):
        live_mm_feed_js.mm_feed_script(continuous=1, once=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be bool"):
        live_mm_feed_js.mm_feed_script(continuous=True, once=None)  # type: ignore[arg-type]


def test_continuous_feed_two_leaves_state_identity_chain_and_page_api() -> None:
    plan = _plan(
        _entry("A", draw=2, draw_count=3, upload=1, to=(2, (640, 360))),
        _entry("B", draw=3, draw_count=3, upload=3),
    )
    _run_node(
        plan,
        r"""
assert.deepStrictEqual(calls.claim.map(x=>x.id),['A','B']);
assert(calls.claim.every(x=>x.scene==='#1' && x.snapshot.busy===false));
assert.strictEqual(warmUploads.length,2);
const gl=makeGl('player'), canvas=new Canvas('0-canvas',gl), wrapped=canvas.getContext('webgl');
assert.strictEqual(wrapped,gl);
assert.strictEqual(g2Calls,2);
assert.strictEqual(preCalls,2);
assert.strictEqual(baseCalls,2);

const a0=texture('a0'),a1=texture('a1'),b0=texture('b0');
upload(gl,a0,[320,180],0,true,false);
upload(gl,a1,[640,360],1,false,true);
upload(gl,b0,[320,180],0,true,true);

function frame(){
  gl.clear();
  program(gl,'absent'); gl.drawElements(4,6,gl.UNSIGNED_BYTE,0);
  bind(gl,a0,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
  program(gl,'present');
  gl.drawArrays(4,0,6);
  assert.strictEqual(gl.active,gl.TEXTURE0);
  assert.strictEqual(gl.bindings.get(gl.TEXTURE0),a0);
  assert.strictEqual(gl.bindings.get(gl.TEXTURE0+1),a1);
  assert.strictEqual(gl.flip,false);
  assert.strictEqual(gl.premultiply,false);
  bind(gl,b0,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent');
  gl.drawElements(4,6,gl.UNSIGNED_BYTE,0);
}
gl.clear(); gl.clear();
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'armed');
frame(); frame();
assert.strictEqual(gl.videoUploads.length,6);
assert.deepStrictEqual(gl.videoUploads.slice(0,3).map(x=>x.source.name),['A','A','B']);
assert.deepStrictEqual(gl.videoUploads.slice(0,3).map(x=>x.texture.name),['a0','a1','b0']);
assert.deepStrictEqual(gl.videoUploads.slice(0,3).map(x=>[x.flip,x.premultiply]),[[true,false],[false,true],[true,true]]);
const api=global.__OBED_MM_FEED__;
assert.strictEqual(Object.isFrozen(api),false);
assert.deepStrictEqual(Object.keys(api).sort(),['entries','once','take','version']);
const fields=['framesFed','hold','maxInterFeedGapMs','mode','p95Ms','reason','state'];
assert.deepStrictEqual(Object.keys(api.entries.A).sort(),fields.slice().sort());
assert.deepStrictEqual(Object.keys(api.entries),['A','B']);
assert.strictEqual(api.entries.A.framesFed,2);
assert.strictEqual(api.entries.B.framesFed,2);
assert.strictEqual(api.entries.A.state,'fed');
assert.strictEqual(api.entries.B.state,'fed');
assert.strictEqual(api.once('A'),false);
api.take({},2);
assert.strictEqual(api.take.lastScene,2);
assert.strictEqual(typeof api.take.lastAt,'number');
api.extra='writable';
assert.strictEqual(api.extra,'writable');
assert(calls.decoder.filter(x=>x==='A').length>=3);
assert.deepStrictEqual(calls.stand,[]);
location.hash='#2'; snapshotScene=2; idleTick();
location.hash='#1'; snapshotScene=1; idleTick();
assert.deepStrictEqual(calls.claim.map(x=>x.id),['A','B','A','B']);
assert.strictEqual(api.entries.A.framesFed,0);
const nextGl=makeGl('next'),nextCanvas=new Canvas('1-canvas',nextGl); nextCanvas.getContext('webgl');
const n0=texture('n0'),n1=texture('n1');
upload(nextGl,n0,[320,180],0,true,false); upload(nextGl,n1,[640,360],1,false,true);
nextGl.clear(); program(nextGl,'absent'); nextGl.drawElements(4,6,nextGl.UNSIGNED_BYTE,0);
bind(nextGl,n0,0); bind(nextGl,n1,1); nextGl.activeTexture(nextGl.TEXTURE0); program(nextGl,'present'); nextGl.drawArrays(4,0,6);
assert.strictEqual(api.entries.A.state,'fed');
assert.strictEqual(api.entries.A.framesFed,1);
""",
    )


def test_real_instrument_observes_module_uploads_after_zero_draw_frame() -> None:
    entry = _entry("A")
    probe_entry = {
        "id": "entry-A",
        "atScene": 2,
        "objectId": "A",
        "dstObjectId": "A2",
        "feed": entry["feed"],
        "draws": {"drawCount": 1, "draws": []},
    }
    before_module = f"""
eval(INSTRUMENT);
assert(global.__obedMmFeedProbe);
global.__obedMmFeedProbe.bootstrap({json.dumps({"entries": [probe_entry]}, separators=(",", ":"))});
const instrumentTick=raf.shift(); assert(instrumentTick); instrumentTick();
"""
    _run_node(
        _plan(entry),
        r"""
assert.strictEqual(calls.claim.length,1);
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const first=texture('first'); upload(gl,first,[320,180],0,true,false);
gl.clear(); gl.clear();
bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
gl.clear();
bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
const report=global.__obedMmFeedProbe.report();
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'fed');
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.framesFed,2);
assert.deepStrictEqual(report.frames.map(x=>x.draws),[0,1,1]);
assert.deepStrictEqual(report.uploads.map(x=>x.frameN),[2,3]);
assert.deepStrictEqual(report.uploads.map(x=>x.textureOrdinal),[1,1]);
assert.strictEqual(report.claims.length,1);
assert.strictEqual(report.claims[0].claimed,true);
assert.strictEqual(report.claims[0].serial,1);
""",
        before_module=before_module,
        constants={"INSTRUMENT": mm_feed_instrument.INSTRUMENT_JS},
    )


def test_player_context_is_not_wrapped_until_an_entry_is_armed() -> None:
    entry = _entry("A")
    entry["atScene"] = 3
    _run_node(
        _plan(entry),
        r"""
const cold=makeGl('cold'),coldCanvas=new Canvas('0-canvas',cold),coldDraw=cold.drawArrays;
coldCanvas.getContext('webgl');
assert.strictEqual(cold.drawArrays,coldDraw);
assert.deepStrictEqual(calls.claim,[]);
location.hash='#2'; snapshotScene=2; idleTick();
assert.deepStrictEqual(calls.claim.map(x=>x.id),['A']);
const hot=makeGl('hot'),hotCanvas=new Canvas('1-canvas',hot),hotDraw=hot.drawArrays;
hotCanvas.getContext('webgl');
assert.notStrictEqual(hot.drawArrays,hotDraw);
""",
    )


@pytest.mark.parametrize(("continuous", "expected_state"), [(True, "fed"), (False, "held")])
def test_context_accepts_hash_already_advanced_for_continuous_and_once(
    continuous: bool, expected_state: str
) -> None:
    request_once = "" if continuous else "assert.strictEqual(global.__OBED_MM_FEED__.once('A'),true);"
    _run_node(
        _plan(_entry("A")),
        f"""
{request_once}
location.hash='#2'; snapshotScene=2;
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl),originalDraw=gl.drawArrays;
canvas.getContext('webgl');
assert.notStrictEqual(gl.drawArrays,originalDraw);
const first=texture('first'); upload(gl,first,[320,180],0,true,false);
gl.clear(); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,{json.dumps(expected_state)});
assert.strictEqual(gl.videoUploads.length,1);
const lateGl=makeGl('late'),lateCanvas=new Canvas('1-canvas',lateGl),lateDraw=lateGl.drawArrays;
lateCanvas.getContext('webgl');
assert.strictEqual(lateGl.drawArrays,lateDraw);
const wrong=texture('wrong'); upload(lateGl,wrong,[319,180],0,true,false);
lateGl.clear(); bind(lateGl,wrong,0); lateGl.activeTexture(lateGl.TEXTURE0); program(lateGl,'absent'); lateGl.drawArrays(4,0,6);
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,{json.dumps(expected_state)});
assert.deepStrictEqual(calls.stand,[]);
""",
        continuous=continuous,
        once=True,
    )


@pytest.mark.parametrize("failure", ["ordinal", "size", "unit", "mix-missing", "mix-present"])
def test_binding_mismatches_fail_closed(failure: str) -> None:
    has_to = failure != "mix-present"
    program_mode = "absent" if failure == "mix-missing" else "present" if has_to or failure == "mix-present" else "absent"
    entry = _entry("A", to=(2, (640, 360)) if has_to else None)
    if failure == "ordinal":
        entry["feed"]["from"]["upload"] = 9
    if failure == "size":
        entry["feed"]["from"]["size"] = [321, 180]
    _run_node(
        _plan(entry),
        f"""
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const a0=texture('a0'),a1=texture('a1');
upload(gl,a0,[320,180],0,true,false);
{'''upload(gl,a1,[640,360],1,false,true);''' if has_to else ''}
gl.clear(); bind(gl,a0,0);
{'''bind(gl,a1,1);''' if has_to else ''}
gl.activeTexture(gl.TEXTURE0{'+1' if failure == 'unit' else ''});
program(gl,{json.dumps(program_mode)});
gl.drawArrays(4,0,6);
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'stoodDown');
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.reason,'binding-mismatch');
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.hold,'baked');
assert.deepStrictEqual(calls.stand.map(x=>x.reason),['binding-mismatch']);
""",
    )


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        ("identity", "identity-change"),
        ("shared", "shared-texture"),
        ("gl-error", "gl-error"),
        ("context-lost", "context-lost"),
        ("decoder", "decoder-mismatch"),
    ],
)
def test_runtime_stand_down_reasons_call_the_current_seam(failure: str, reason: str) -> None:
    entries = (
        [_entry("A", draw=1, draw_count=2, upload=1), _entry("B", draw=2, draw_count=2, upload=2)]
        if failure == "shared"
        else [_entry("A")]
    )
    _run_node(
        _plan(*entries),
        f"""
const late=[];
global.__OBED_P2_PRESERVE__.feed.onStandDown=function(id,why){{ late.push({{id,why}}); return true; }};
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const first=texture('first'); upload(gl,first,[320,180],0,true,false);
if({json.dumps(failure)}==='context-lost'){{
  canvas.dispatch('webglcontextlost'); idleTick();
  assert.deepStrictEqual(calls.claim.map(x=>x.id),['A']);
}}
else if({json.dumps(failure)}==='decoder'){{ decoders.A=null; gl.clear(); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6); }}
else if({json.dumps(failure)}==='shared'){{
  gl.clear(); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
  upload(gl,first,[320,180],0,true,false); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
}} else {{
  gl.clear(); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent');
  if({json.dumps(failure)}==='gl-error')gl.nextError=1280;
  gl.drawArrays(4,0,6);
  if({json.dumps(failure)}==='identity'){{
    const second=texture('second'); upload(gl,second,[320,180],0,true,false);
    gl.clear(); bind(gl,second,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
  }}
}}
assert(late.some(x=>x.why==={json.dumps(reason)}));
assert(Object.values(global.__OBED_MM_FEED__.entries).some(x=>x.reason==={json.dumps(reason)}));
""",
    )


def test_no_feed_requires_a_ready_draw_reached_in_that_frame() -> None:
    plan = _plan(_entry("A"))
    _run_node(
        plan,
        r"""
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const first=texture('first'); upload(gl,first,[320,180],0,true,false);
gl.clear(); gl.clear(); gl.clear();
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'armed');
bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'fed');
assert.deepStrictEqual(calls.stand,[]);
""",
    )
    missed_plan = _plan(_entry("A", draw=1, draw_count=2))
    _run_node(
        missed_plan,
        r"""
const api=global.__OBED_MM_FEED__;
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const first=texture('first'); upload(gl,first,[320,180],0,true,false);
gl.clear(); bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
assert.strictEqual(api.once('A'),true);
gl.clear();
bind(gl,first,0); gl.activeTexture(gl.TEXTURE0); program(gl,'absent'); gl.drawArrays(4,0,6);
gl.drawElements(4,6,gl.UNSIGNED_BYTE,0);
assert.strictEqual(api.entries.A.state,'held');
assert.strictEqual(api.entries.A.reason,null);
assert.strictEqual(api.entries.A.hold,'exact');
assert.strictEqual(gl.videoUploads.length,1);
assert.deepStrictEqual(calls.stand,[]);
""",
        continuous=False,
        once=True,
    )


def test_once_uploads_each_texture_once_never_claims_and_keeps_baked_fallback_reason() -> None:
    plan = _plan(_entry("A", to=(2, (640, 360))))
    _run_node(
        plan,
        r"""
assert.deepStrictEqual(calls.claim,[]);
const api=global.__OBED_MM_FEED__;
assert.strictEqual(api.entries.A.mode,'once');
assert.strictEqual(api.once('A'),true);
assert.strictEqual(api.once('A'),true);
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const a0=texture('a0'),a1=texture('a1');
upload(gl,a0,[320,180],0,true,false); upload(gl,a1,[640,360],1,false,true);
gl.clear(); gl.clear();
assert.strictEqual(api.entries.A.state,'armed');
gl.clear(); bind(gl,a0,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0);
gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
program(gl,'present'); gl.drawArrays(4,0,6);
assert.strictEqual(gl.videoUploads.length,2);
assert.strictEqual(api.entries.A.state,'held');
assert.strictEqual(api.entries.A.hold,'exact');
assert.strictEqual(api.entries.A.framesFed,1);
assert.strictEqual(gl.active,gl.TEXTURE0);
assert.strictEqual(gl.bindings.get(gl.TEXTURE0),a0);
assert.strictEqual(gl.bindings.get(gl.TEXTURE0+1),a1);
assert.strictEqual(gl.flip,false); assert.strictEqual(gl.premultiply,false);
gl.clear(); bind(gl,a0,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0); program(gl,'present'); gl.drawArrays(4,0,6);
assert.strictEqual(gl.videoUploads.length,2);
assert.strictEqual(api.once('A'),true);
gl.clear(); bind(gl,a0,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0); program(gl,'present'); gl.drawArrays(4,0,6);
assert.strictEqual(gl.videoUploads.length,2);
""",
        continuous=False,
        once=True,
    )
    _run_node(
        plan,
        r"""
const api=global.__OBED_MM_FEED__; assert.strictEqual(api.once('A'),true);
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const wrong=texture('wrong'); upload(gl,wrong,[319,180],0,true,false);
const a1=texture('a1'); upload(gl,a1,[640,360],1,false,true);
gl.clear(); bind(gl,wrong,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0); program(gl,'present'); gl.drawArrays(4,0,6);
assert.strictEqual(api.entries.A.state,'stoodDown');
assert.strictEqual(api.entries.A.reason,'binding-mismatch');
assert.strictEqual(api.entries.A.hold,'baked');
assert.strictEqual(api.entries.A.framesFed,0);
assert.deepStrictEqual(calls.claim,[]);
""",
        continuous=False,
        once=True,
    )


def test_from_only_variant_skips_to_upload_and_refuses_bad_requests() -> None:
    original = live_mm_feed_js.mm_feed_script(continuous=True, once=True)
    changed = mm_feed_variants.variant_script("from-only", original)
    assert changed != original
    assert "var uploadTargets = [targets[0]];" in changed
    assert "record.binding.to ? [targets[0], targets[1]]" not in changed
    _run_node(
        _plan(_entry("A", to=(2, (640, 360)))),
        r"""
const gl=makeGl('player'),canvas=new Canvas('0-canvas',gl); canvas.getContext('webgl');
const a0=texture('a0'),a1=texture('a1');
upload(gl,a0,[320,180],0,true,false); upload(gl,a1,[640,360],1,false,true);
gl.clear(); bind(gl,a0,0); bind(gl,a1,1); gl.activeTexture(gl.TEXTURE0); program(gl,'present'); gl.drawArrays(4,0,6);
assert.strictEqual(gl.videoUploads.length,1);
assert.strictEqual(gl.videoUploads[0].texture,a0);
assert.strictEqual(global.__OBED_MM_FEED__.entries.A.state,'fed');
""",
        script=changed,
    )
    with pytest.raises(ValueError, match="unknown feed variant"):
        mm_feed_variants.variant_script("to-only", original)
    with pytest.raises(ValueError, match="anchor occurs 0 times"):
        mm_feed_variants.variant_script("from-only", "<script></script>")

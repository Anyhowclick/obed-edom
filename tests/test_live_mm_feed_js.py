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

NODE = shutil.which("node")
PINNED_MM_FEED_SHA256 = "4bef83a54e7e65dfdee6bfc0b43615b69c202ee93681cacee46e83cf448ec4c4"


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

class Video {
  constructor(name){ this.name=name; this.readyState=2; this.videoWidth=320; this.videoHeight=180; this.currentTime=1; }
}
global.HTMLVideoElement = Video;

const warmUploads = [];
function makeGl(name){
  const gl = {
    name, TEXTURE0:33984, TEXTURE_2D:3553, ACTIVE_TEXTURE:34016,
    CURRENT_PROGRAM:35725, TEXTURE_BINDING_2D:32873,
    UNPACK_FLIP_Y_WEBGL:37440, UNPACK_PREMULTIPLY_ALPHA_WEBGL:37441,
    RGBA:6408, UNSIGNED_BYTE:5121, NO_ERROR:0,
    active:33984, program:null, flip:false, premultiply:false, nextError:0,
    bindings:new Map(), videoUploads:[], calls:[], textureN:0,
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
    uniform1f(){}, uniform1fv(){},
    clear(){ this.calls.push(['clear']); },
    drawArrays(){ this.calls.push(['drawArrays']); },
    drawElements(){ this.calls.push(['drawElements']); },
    getError(){ const value=this.nextError; this.nextError=0; return value; }
  };
  return gl;
}

const warmGl = makeGl('warm');
let baseCalls = 0, preCalls = 0, g2Calls = 0;
class Canvas {
  constructor(id,gl){ this.id=id||''; this._gl=gl||warmGl; this.width=1920; this.height=1080; this.listeners={}; }
  addEventListener(name,fn){ this.listeners[name]=fn; }
  dispatch(name){ if(this.listeners[name])this.listeners[name]({type:name}); }
}
Canvas.prototype.getContext = function(){ baseCalls++; return this._gl; };
const baseGetContext = Canvas.prototype.getContext;
Canvas.prototype.getContext = function(){ preCalls++; return baseGetContext.apply(this,arguments); };
Canvas.prototype.getContext.__obedMmFeedProbe = 1;
global.HTMLCanvasElement = Canvas;
global.document = {createElement(name){ assert.strictEqual(name,'canvas'); return new Canvas('',warmGl); }};

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

eval(MODULE);
assert(global.__OBED_MM_FEED__);
const moduleGetContext = Canvas.prototype.getContext;
Canvas.prototype.getContext = function(){ g2Calls++; return moduleGetContext.apply(this,arguments); };
Canvas.prototype.getContext.__obedGlReplay = 1;

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
        + _HARNESS
        + "\n"
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
        _entry("A", draw=1, draw_count=2, upload=1, to=(2, (640, 360))),
        _entry("B", draw=2, draw_count=2, upload=3),
    )
    _run_node(
        plan,
        r"""
assert.deepStrictEqual(calls.claim.map(x=>x.id),['A','B']);
assert(calls.claim.every(x=>x.scene==='#1' && x.snapshot.busy===false));
assert.strictEqual(warmUploads.length,2);
const gl=makeGl('player'), canvas=new Canvas('0-canvas',gl), wrapped=canvas.getContext('webgl');
assert.strictEqual(wrapped,gl);
assert.strictEqual(g2Calls,1);
assert.strictEqual(preCalls,2);
assert.strictEqual(baseCalls,2);

const a0=texture('a0'),a1=texture('a1'),b0=texture('b0');
upload(gl,a0,[320,180],0,true,false);
upload(gl,a1,[640,360],1,false,true);
upload(gl,b0,[320,180],0,true,true);

function frame(){
  gl.clear();
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
nextGl.clear(); bind(nextGl,n0,0); bind(nextGl,n1,1); nextGl.activeTexture(nextGl.TEXTURE0); program(nextGl,'present'); nextGl.drawArrays(4,0,6);
assert.strictEqual(api.entries.A.state,'fed');
assert.strictEqual(api.entries.A.framesFed,1);
""",
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
        ("no-feed", "no-feed"),
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
if({json.dumps(failure)}==='no-feed'){{ gl.clear(); gl.clear(); }}
else if({json.dumps(failure)}==='context-lost'){{ canvas.dispatch('webglcontextlost'); }}
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

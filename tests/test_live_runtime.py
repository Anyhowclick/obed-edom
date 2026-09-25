from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from obed_edom import live_runtime


def test_unknown_player_is_refused():
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="live output"):
        live_runtime.patch_player(b"unknown player")
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="preview"):
        live_runtime.patch_rendering(b"unknown player")


def test_patch_requires_exactly_one_hook(monkeypatch):
    for player in (b"no hook", live_runtime._ANCHOR * 2):
        monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
        with pytest.raises(live_runtime.LiveRuntimeUnsupported):
            live_runtime.patch_player(player)


def test_patch_preserves_surrounding_player(monkeypatch):
    player = b"before;" + live_runtime._ANCHOR + b";after"
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
    patched = live_runtime.patch_player(player, mm_opacity=False)
    assert patched.startswith(b"before;UC=new Eg,")
    assert patched.endswith(b",UC.displayManager.showWaitingIndicator();after")


def test_observation_tracks_automatic_chain_and_actual_slide():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the player observation hook")
    script = """
const window = {};
const UC = {
  script: {showMode: 0, events: [{}, {automaticPlay: true}, {}],
    slideIndexFromSceneIndexLookup: {0: 0, 1: 0, 2: 1}},
  currentSceneIndex: 0, nextSceneIndex: 1, currentSlideIndex: 0,
  state: 'IdleAtInitialState', queuedUserAction: null,
  changeState(state) { this.state = state; },
  setCurrentSceneIndexTo(scene) { this.currentSceneIndex = scene; }
};
""" + live_runtime._INSTALL.decode() + ";" + """
const results = [window.__obedLive.snapshot()];
UC.changeState('Playing'); results.push(window.__obedLive.snapshot());
UC.changeState('IdleAtFinalState'); results.push(window.__obedLive.snapshot());
UC.nextSceneIndex = 2; results.push(window.__obedLive.snapshot());
UC.setCurrentSceneIndexTo(2); UC.currentSlideIndex = -1; UC.nextSceneIndex = -1;
results.push(window.__obedLive.snapshot());
UC.script.showMode = 1; results.push(window.__obedLive.snapshot());
console.log(JSON.stringify(results));
"""
    result = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
    initial, playing, chain, settled, end, automatic = json.loads(result.stdout)
    assert initial["ready"] and initial["canAdvance"] and initial["canGoTo"]
    assert initial["autoPlayRunLength"] == 0 and initial["autoPlayRunKinds"] == []
    assert playing["busy"] and not playing["canGoTo"]
    assert playing["autoPlayRunLength"] is None and playing["autoPlayRunKinds"] is None
    assert chain["busy"] and not chain["ready"]
    assert chain["autoPlayRunLength"] == 1 and chain["autoPlayRunKinds"] == [None]
    assert settled["ready"] and settled["exportedSlideIndex"] == 0
    assert settled["autoPlayRunLength"] == 0 and settled["autoPlayRunKinds"] == []
    assert end["exportedSlideIndex"] == 1 and end["sceneId"] == 2
    assert end["ready"] and not end["canAdvance"]
    assert end["autoPlayRunLength"] == 0 and end["autoPlayRunKinds"] == []
    assert end["revision"] > initial["revision"] and end["buildIndex"] is None
    assert not automatic["ready"] and automatic["refusalReason"]


def test_auto_play_run_length_and_kinds():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the player observation hook")
    script = """
const window = {};
const UC = {
  script: {showMode: 0, events: [
      {automaticPlay: true, effects: [{name: 'apple:movie-start'}]},
      {automaticPlay: true, effects: [{name: 'apple:movie-start'}]},
      {automaticPlay: false, effects: [{name: 'apple:dissolve-character'}]},
      {automaticPlay: true, effects: [{name: 'apple:movie-start'}]},
    ],
    slideIndexFromSceneIndexLookup: {0: 0, 1: 0, 2: 1, 3: 1}},
  currentSceneIndex: 0, nextSceneIndex: 1, currentSlideIndex: 0,
  state: 'IdleAtInitialState', queuedUserAction: null,
  changeState(state) { this.state = state; },
  setCurrentSceneIndexTo(scene) { this.currentSceneIndex = scene; this.nextSceneIndex = scene + 1; }
};
""" + live_runtime._INSTALL.decode() + ";" + """
const results = [window.__obedLive.snapshot()];
UC.setCurrentSceneIndexTo(1); UC.changeState('IdleAtFinalState');
results.push(window.__obedLive.snapshot());
UC.script.events = null;
results.push(window.__obedLive.snapshot());
delete UC.script.events;
results.push(window.__obedLive.snapshot());
UC.script.events = 'not-an-array';
results.push(window.__obedLive.snapshot());
UC.script = null;
results.push(window.__obedLive.snapshot());
console.log(JSON.stringify(results));
"""
    result = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
    leading_run, click_boundary, events_null, events_absent, events_non_array, script_null = json.loads(result.stdout)
    assert leading_run["autoPlayRunLength"] == 2
    assert leading_run["autoPlayRunKinds"] == ["apple:movie-start", "apple:movie-start"]
    # nextSceneIndex (2) is the click-driven dissolve-character build; the run must
    # stop there rather than skip ahead to event 3's automaticPlay.
    assert click_boundary["autoPlayRunLength"] == 0
    assert click_boundary["autoPlayRunKinds"] == []
    # script.events null/absent/non-array must not throw (script itself stays truthy).
    for result_case in (events_null, events_absent, events_non_array, script_null):
        assert result_case["autoPlayRunLength"] is None
        assert result_case["autoPlayRunKinds"] is None


def test_slide_number_showing_reflects_the_overlay_controller():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the player observation hook")
    script = """
const window = {};
const UC = {
  script: null, currentSceneIndex: 0, nextSceneIndex: -1, currentSlideIndex: 0,
  state: 'IdleAtInitialState', queuedUserAction: null,
  slideNumberController: {isShowing: true},
  changeState(state) { this.state = state; },
  setCurrentSceneIndexTo(scene) { this.currentSceneIndex = scene; }
};
""" + live_runtime._INSTALL.decode() + ";" + """
const results = [window.__obedLive.snapshot()];
UC.slideNumberController.isShowing = false;
results.push(window.__obedLive.snapshot());
delete UC.slideNumberController;
results.push(window.__obedLive.snapshot());
console.log(JSON.stringify(results));
"""
    result = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
    showing, hidden, absent = json.loads(result.stdout)
    assert showing["slideNumberShowing"] is True
    assert hidden["slideNumberShowing"] is False
    assert absent["slideNumberShowing"] is False


MAIN_OUTPUT = Path("/Users/anyhowclick/Desktop/work/obed-edom/output")
REAL_PLAYER = MAIN_OUTPUT / "p2-binary" / "html-player" / "assets" / "player" / "main.js"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
EFFECT_1_TO_2 = FIXTURE_ROOT / "effect_1_to_2.json"
SOURCE_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
SLOT4_ALPHA = 0.29468628764152527
EB_EFFECTS = {"apple:magic-move-implied-motion-path", "apple:ca-text-shimmer", "apple:ca-text-sparkle"}


def _hook_only(player: bytes) -> bytes:
    """Today's (pre-mm_opacity) output, built independently of patch_player."""
    return player.replace(
        live_runtime._ANCHOR,
        b"UC=new Eg," + live_runtime._INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )


def _synthetic_player(anchors: list[bytes] | None = None) -> bytes:
    anchors = [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS] if anchors is None else anchors
    return b"before;" + live_runtime._ANCHOR + b";" + b";".join(anchors) + b";after"


def _pin(monkeypatch, player: bytes) -> None:
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())


def test_mm_opacity_off_is_byte_identical_to_the_hook_only_output(monkeypatch):
    player = _synthetic_player()
    _pin(monkeypatch, player)
    off = live_runtime.patch_player(player, mm_opacity=False)
    assert hashlib.sha256(off).hexdigest() == hashlib.sha256(_hook_only(player)).hexdigest()
    on = live_runtime.patch_player(player)
    assert on != off
    # Undoing exactly the replacements on the default (on) output gives the off output back.
    reverted = on
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert on.count(after) == 1
        reverted = reverted.replace(after, before)
    assert hashlib.sha256(reverted).hexdigest() == hashlib.sha256(off).hexdigest()


def test_patch_rendering_is_the_live_output_minus_the_observation_hook(monkeypatch):
    # The preview serves patch_rendering; live serves patch_player. They must differ only by the hook.
    player = _synthetic_player()
    _pin(monkeypatch, player)
    rendering = live_runtime.patch_rendering(player)
    assert live_runtime.patch_player(player) == _hook_only(rendering)
    assert live_runtime._INSTALL not in rendering
    assert rendering.count(live_runtime._ANCHOR) == 1
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert rendering.count(before) == 0 and rendering.count(after) == 1


# Each patcher that applies the Magic Move opacity replacements: live output and the dashboard preview.
MM_PATCHERS = {"patch_player": live_runtime.patch_player, "patch_rendering": live_runtime.patch_rendering}


@pytest.mark.parametrize("patcher", MM_PATCHERS)
@pytest.mark.parametrize("index", range(len(live_runtime._MM_OPACITY_REPLACEMENTS)))
@pytest.mark.parametrize("count", [0, 2])
def test_mm_opacity_refuses_a_missing_or_duplicated_anchor(monkeypatch, index, count, patcher):
    anchors = [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS]
    anchors[index : index + 1] = [anchors[index]] * count
    player = _synthetic_player(anchors)
    _pin(monkeypatch, player)
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="Magic Move opacity anchor"):
        MM_PATCHERS[patcher](player)
    # The off path never looks at these anchors.
    assert live_runtime.patch_player(player, mm_opacity=False) == _hook_only(player)


@pytest.mark.parametrize("patcher", MM_PATCHERS)
@pytest.mark.parametrize("index", range(len(live_runtime._MM_OPACITY_REPLACEMENTS)))
def test_mm_opacity_refuses_a_replacement_that_is_not_unique(monkeypatch, index, patcher):
    # The anchor is unique but its replacement text already occurs once, so it would occur twice after.
    player = _synthetic_player() + b";" + live_runtime._MM_OPACITY_REPLACEMENTS[index][1]
    _pin(monkeypatch, player)
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="Magic Move opacity patch"):
        MM_PATCHERS[patcher](player)


def _real_player() -> bytes:
    if not REAL_PLAYER.is_file():
        pytest.skip("real player export not available")
    player = REAL_PLAYER.read_bytes()
    assert hashlib.sha256(player).hexdigest() == live_runtime.PLAYER_SHA256
    return player


def test_mm_opacity_anchors_are_unique_on_the_real_player():
    player = _real_player()
    assert player.count(live_runtime._ANCHOR) == 1
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert player.count(before) == 1
        assert player.count(after) == 0
    assert player.count(b"obedOpacity") == 0 and player.count(b"__obed") == 0
    patched = live_runtime.patch_player(player)
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert patched.count(before) == 0
        assert patched.count(after) == 1
    assert live_runtime.patch_player(player, mm_opacity=False) == _hook_only(player)


# sha256 of patch_player(real, mm_opacity=...). False: recorded on 3eb3b0fe (hook only, unchanged since).
# True: with the hand-back replacements R6-R8 (keynote_live_handback_geometry.plan.md); was 21476f78... with R1-R5.
REAL_PATCHED_SHA256 = {
    True: "e17264c0a0067c6651ab5582efbdd2656536b696c5d39f078a08ba836dacd2f3",
    False: "7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de",
}
REAL_RENDERING_SHA256 = "5797b302a3d58a27a5bcf80cd2f7544b026015779736d5b6fb9420a0ebee524c"


@pytest.mark.parametrize("flag", [True, False])
def test_patch_player_output_is_pinned_on_the_real_player(flag):
    player = _real_player()
    assert hashlib.sha256(live_runtime.patch_player(player, mm_opacity=flag)).hexdigest() == REAL_PATCHED_SHA256[flag]


def test_patch_rendering_is_the_live_output_minus_the_hook_on_the_real_player():
    player = _real_player()
    rendering = live_runtime.patch_rendering(player)
    assert _hook_only(rendering) == live_runtime.patch_player(player)
    assert b"__obedLive" not in rendering
    assert hashlib.sha256(rendering).hexdigest() == REAL_RENDERING_SHA256


# Hand-back geometry (keynote_live_handback_geometry.plan.md §3.2): R6-R8 are the last three replacements, at these
# byte offsets of the stock player.
HANDBACK_OFFSETS = {
    b"B[g].toTexture=R.createTexture(this.gl,i)}}return B}": 2263321,
    b'case"contents":C=e.toTexture}}var T=': 2190367,
    b"this.textureManager.loadScene(B)}unloadTextures(){": 2347821,
}


def test_handback_replacements_are_the_last_three():
    assert [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS[-3:]] == list(HANDBACK_OFFSETS)
    # No replacement's text contains any anchor, so none can be re-matched or reverted into another.
    for _, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS:
            assert before not in after


def test_handback_anchors_are_unique_on_the_synthetic_player(monkeypatch):
    player = _synthetic_player()
    _pin(monkeypatch, player)
    patched = live_runtime.patch_player(player)
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS[-3:]:
        assert player.count(before) == 1 and player.count(after) == 0
        assert patched.count(before) == 0 and patched.count(after) == 1


def test_handback_anchors_are_unique_on_the_real_player():
    player = _real_player()
    assert player.count(b"obedMix") == 0 and player.count(b"__obedHandbackTextures") == 0
    for before, offset in HANDBACK_OFFSETS.items():
        assert player.count(before) == 1
        assert player.find(before) == offset
    patched = live_runtime.patch_player(player)
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS[-3:]:
        assert patched.count(before) == 0 and patched.count(after) == 1
    # Decision 5b: the rule requires a scale change; translation only enters through the destination-rect match.
    assert patched.count(b"1===sx&&1===sy&&(ok=!1);") == 1
    assert b"0===tx" not in patched
    off = live_runtime.patch_player(player, mm_opacity=False)
    assert b"obedMix" not in off and b"__obedHandbackTextures" not in off


def _apply_in_order(player: bytes, replacements) -> bytes:
    for before, after in replacements:
        assert player.count(before) == 1
        player = player.replace(before, after)
        assert player.count(after) == 1
    return player


@pytest.mark.parametrize("real", [False, True], ids=["synthetic", "real"])
def test_opacity_and_handback_replacements_compose_in_either_order(monkeypatch, real):
    if real:
        player = _real_player()
    else:
        player = _synthetic_player()
        _pin(monkeypatch, player)
    replacements = live_runtime._MM_OPACITY_REPLACEMENTS
    opacity_first = _apply_in_order(player, replacements)
    handback_first = _apply_in_order(player, replacements[-3:] + replacements[:-3])
    assert opacity_first == handback_first == live_runtime.patch_rendering(player)


SWAP_HIDE_DEFERRED = b"setTimeout(this.handleAnimateEffectDidBegin"


def test_mm_opacity_hides_the_swapped_node_synchronously_on_the_real_player():
    player = _real_player()
    before, after = live_runtime._MM_OPACITY_REPLACEMENTS[4]
    assert before == b"Q&&setTimeout(this.handleAnimateEffectDidBegin.bind(this,Q),0)"
    assert player.count(before) == 1 and player.count(after) == 0
    assert player.count(SWAP_HIDE_DEFERRED) == 1
    patched = live_runtime.patch_player(player)
    assert patched.count(after) == 1
    assert patched.count(SWAP_HIDE_DEFERRED) == 0
    # Off keeps the stock deferred hide.
    off = live_runtime.patch_player(player, mm_opacity=False)
    assert off.count(SWAP_HIDE_DEFERRED) == 1 and off.count(after) == 0


def _run_animate_effect_will_begin(node: str, player: str, started: bool = True) -> dict:
    """Run the real `animateEffectWillBegin` + `handleAnimateEffectDidBegin` cut out of `player` with a stub renderer
    and record, in order, draw / animate / hide (the swapped node's opacity set) when the method returns and after the
    event loop drains. started=True: the renderer's loop already runs (every effect `animateEffects` starts), so
    `animate` must not be called; False: a fresh renderer (a child effect from `handleEffectDidComplete`), whose
    `animate` draws the first frame synchronously. This proves task order only; that the hide and the first GL frame
    reach the same painted frame rests on the browser running rAF callbacks before paint."""
    methods = _cut(player, "animateEffectWillBegin(A){", "handleEffectDidComplete(A){")
    script = """
const events=[];
const node={style:{_o:'',get opacity(){return this._o},set opacity(v){events.push('hide');this._o=v}}};
const document={getElementById:(id)=>id==='swap'?node:null};
const started=%s;
class P{constructor(){this.glRenderer={c:{animationStarted:started,draw:(e)=>events.push('draw'),
  animate(){if(started)throw new Error('loop already running');events.push('animate')}}}}%s}
new P().animateEffectWillBegin({canvasId:'c',effect:'mm',nodeToSwapId:'swap'});
const sync={events:[...events],opacity:node.style.opacity};
new P().animateEffectWillBegin({canvasId:'c',effect:'mm',nodeToSwapId:'absent'});
setTimeout(()=>console.log(JSON.stringify({sync,drained:{events,opacity:node.style.opacity}})),5);
""" % ("true" if started else "false", methods)
    result = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the extracted player methods")
    return node


def test_mm_opacity_swapped_node_is_hidden_in_the_same_task_as_the_first_draw():
    node, player = _node(), _real_player()
    stock = _run_animate_effect_will_begin(node, _hook_only(player).decode())
    patched = _run_animate_effect_will_begin(node, live_runtime.patch_player(player).decode())
    # Stock: the draw is queued but the outgoing node is still visible when the task ends, so a rAF that
    # lands before the setTimeout(0) paints both the GL frame and the DOM copy.
    assert stock == {"sync": {"events": ["draw"], "opacity": ""}, "drained": {"events": ["draw", "draw", "hide"], "opacity": 0}}
    # Patched: hidden before the task ends; a missing node is still a no-op.
    assert patched == {"sync": {"events": ["draw", "hide"], "opacity": 0},
                       "drained": {"events": ["draw", "hide", "draw"], "opacity": 0}}


def test_mm_opacity_hides_the_swapped_node_after_a_fresh_loops_first_frame():
    # Review r2 F6: with the draw loop not yet started, `animate()` draws the first frame synchronously; the patched
    # hide follows it in the same task (draw -> animate -> hide), stock hides one timer later.
    node, player = _node(), _real_player()
    stock = _run_animate_effect_will_begin(node, _hook_only(player).decode(), started=False)
    patched = _run_animate_effect_will_begin(node, live_runtime.patch_player(player).decode(), started=False)
    assert stock["sync"] == {"events": ["draw", "animate"], "opacity": ""}
    assert stock["drained"]["events"] == ["draw", "animate", "draw", "animate", "hide"]
    assert patched["sync"] == {"events": ["draw", "animate", "hide"], "opacity": 0}
    assert patched["drained"] == {"events": ["draw", "animate", "hide", "draw", "animate"], "opacity": 0}


def test_mm_opacity_patched_real_player_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to syntax-check the patched player")
    player = _real_player()
    for flag in (True, False):
        path = tmp_path / f"main-{flag}.js"
        path.write_bytes(live_runtime.patch_player(player, mm_opacity=flag))
        subprocess.run([node, "--check", str(path)], check=True, capture_output=True)
    path = tmp_path / "main-rendering.js"
    path.write_bytes(live_runtime.patch_rendering(player))
    subprocess.run([node, "--check", str(path)], check=True, capture_output=True)


def _cut(source: str, start: str, end: str) -> str:
    i = source.index(start)
    assert source.count(start) == 1
    return source[i : source.index(end, i)]


def _extracted_methods(player: str, patched: bool) -> str:
    """The real `QB` class, `fB`'s node/chain helpers + `textureInfoFromEffect`, and `eB.drawFrame`'s
    no-animation Opacity expression, cut verbatim out of the player (patched or stock)."""
    qb = _cut(player, "class QB{", "class eB{")
    tie = _cut(player, "__obedNodeOpacity(A){" if patched else "textureInfoFromEffect(A,B,g,C,Q){", "draw(A){if(A.baseLayer)")
    no_animation = _cut(player, "var w=e.initialState.hidden?0:", ";t.setGLFloat(w") + ";"
    return (
        qb
        + "\nclass F{" + tie + "}\n"
        + "function noAnimation(e, parentOpacity){const self={parentOpacity};return (function(){"
        + no_animation + "return w}).call(self)}\n"
    )


def _player_texture_tree(node: dict) -> dict:
    """The fields of the player's parsed layer (`VB`) that the extracted methods read."""
    return {
        "initialState": node["initialState"],
        "animations": node.get("animations") or [],
        "textureId": node.get("texture"),
        "texturedRectangle": node.get("texturedRectangle"),
        "bounds": {"offset": {"pointX": 0, "pointY": 0}, "width": node["initialState"]["width"], "height": node["initialState"]["height"]},
        "layers": [_player_texture_tree(child) for child in node.get("layers") or []],
    }


def _run_extracted(node: str, player: str, patched: bool, effect: dict) -> list[list[float]]:
    # Easing is stubbed linear (`kA.doubleForAnimationCurve`) and the matrix helpers (`u`) are identity:
    # only the Opacity uniform is observed.
    script = """
class kA{doubleForAnimationCurve(n,x){return x}}
class KA{}
const u={translateMatrix4:(m)=>m,rotateMatrix4AboutXYZ:(m)=>m,scaleMatrix4:(m)=>m};
%s
const root=%s;
const out=[];
for (const percent of [0,0.5,1]){
  const textures=[];
  new F().textureInfoFromEffect(root,'x',{pointX:0,pointY:0},root.initialState.opacity,textures);
  const values=[];
  for (const t of textures){
    let opacity=null;
    const shader={setGLFloat:(v,n)=>{if(n==='Opacity')opacity=v},setMat4WithTransform3D(){}};
    const gl={blendFunc(){},activeTexture(){},bindTexture(){},ONE:1,ONE_MINUS_SRC_ALPHA:2,TEXTURE0:0,TEXTURE1:1,TEXTURE_2D:3};
    if(!t.animations.length){opacity=noAnimation(t,root.initialState.opacity);}
    else {new QB(gl).renderFrameWithContext(shader,{drawWithShader(){}},{textureInfo:t,effectDuration:1500,baseTransform:[],percent,isBlending:false});}
    values.push(opacity);
  }
  out.push(values);
}
console.log(JSON.stringify(out));
""" % (_extracted_methods(player, patched), json.dumps(_player_texture_tree(effect["baseLayer"])))
    result = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def test_mm_opacity_real_patched_methods_draw_the_authored_opacity_on_p2_1_to_2():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the extracted player methods")
    player = _real_player()
    effect = json.loads(EFFECT_1_TO_2.read_text())
    stock = _run_extracted(node, _hook_only(player).decode(), False, effect)
    patched = _run_extracted(node, live_runtime.patch_player(player).decode(), True, effect)
    # Rows are p = 0, 0.5, 1; columns are the eB slots in effect.textures order. Slot 1 is the leaf fade.
    assert stock == [[1, 1, 1, 1, 1], [1, 0, 1, 1, 1], [1, 0, 1, 1, 1]]
    assert patched == [[1, 1, 1, 1, SLOT4_ALPHA], [1, 0, 1, 1, SLOT4_ALPHA], [1, 0, 1, 1, SLOT4_ALPHA]]
    # The dashboard preview's bytes (no observation hook) draw the same values.
    assert _run_extracted(node, live_runtime.patch_rendering(player).decode(), True, effect) == patched
    # The Python mirror below agrees with the real bytes on every slot and point.
    assert [[new for _, new in row] for row in _mirror(effect)] == patched
    assert [[old for old, _ in row] for row in _mirror(effect)] == stock


def _anim(prop: str, start, end, fill: str = "both") -> dict:
    return {"property": prop, "from": {"scalar": start}, "to": {"scalar": end}, "fillMode": fill,
            "beginTime": 0, "duration": 1.5, "timingFunction": "Linear"}


def _group(*animations: dict) -> dict:
    return {"animations": list(animations), "fillMode": "both", "beginTime": 0, "duration": 1.5}


def _layer(opacity: float = 1, animations=(), layers=None, texture: str | None = None) -> dict:
    node = {
        "initialState": {"opacity": opacity, "hidden": False, "width": 10, "height": 10,
                         "anchorPoint": {"pointX": 0.5, "pointY": 0.5}, "rotation": 0, "scale": 1},
        "animations": list(animations),
    }
    if texture:
        node["texture"], node["texturedRectangle"] = texture, {}
    else:
        node["layers"] = layers or []
    return node


def _wrapped(*wrapper_animations: dict, model: float = 0.4) -> dict:
    """Root -> one wrapper (model opacity `model`, the given animation groups) -> one constant 0.5 leaf."""
    return _layer(layers=[_layer(model, wrapper_animations, [_layer(0.5, texture="leaf")])])


# Each tree: (root layer, expected patched Opacity per leaf; None = unchanged from the stock value).
SYNTHETIC_TREES = {
    "wrapper-fade": (_wrapped(_group(_anim("opacity", 1, 0))), [None]),
    "non-both-constant": (_wrapped(_group(_anim("opacity", 0.4, 0.4, fill="forwards"))), [None]),
    "two-opacity-animations": (_wrapped(_group(_anim("opacity", 0.4, 0.4), _anim("opacity", 0.4, 0.4))), [None]),
    "hidden-animation": (_wrapped(_group(_anim("opacity", 0.4, 0.4), _anim("hidden", True, True))), [None]),
    # F4: an opacity animation two groups deep is not read by the node rule, so it must not fall back to the
    # model value (0.4 here, which would give 0.2 instead of the stock 0.5).
    "nested-group-animation": (_wrapped(_group(_group(_anim("opacity", 1, 1)))), [None]),
    "textured-root": (_layer(0.6, texture="root"), [None]),
    # 1 (root) x 0.4 (wrapper, constant `both`) x 0.5 (leaf model).
    "constant-translucent-wrapper": (_wrapped(_group(_anim("opacity", 0.4, 0.4))), [1 * 0.4 * 0.5]),
    # The faded middle node B makes both leaves under it (direct, and via constant C) unchanged; the sibling
    # leaf under A still gets A's chain value.
    "null-from-a-middle-node": (
        _layer(layers=[_layer(0.4, [_group(_anim("opacity", 0.4, 0.4))], [
            _layer(1, [_group(_anim("opacity", 1, 0))], [
                _layer(0.5, texture="b-leaf"),
                _layer(0.5, [_group(_anim("opacity", 0.5, 0.5))], [_layer(0.5, texture="c-leaf")]),
            ]),
            _layer(0.5, texture="a-leaf"),
        ])]),
        [None, None, 1 * 0.4 * 0.5],
    ),
    # Decision 5 residual: a leaf fade under a translucent constant wrapper keeps the stock fade.
    "leaf-fade-under-constant-wrapper": (
        _layer(layers=[_layer(0.4, [_group(_anim("opacity", 0.4, 0.4))],
                              [_layer(0.5, [_group(_anim("opacity", 1, 0))], texture="leaf")])]),
        [None],
    ),
}


@pytest.mark.parametrize("name", SYNTHETIC_TREES)
def test_mm_opacity_real_patched_methods_agree_with_the_mirror_on_synthetic_trees(name):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the extracted player methods")
    player = _real_player()
    root, expected = SYNTHETIC_TREES[name]
    effect = {"duration": 1.5, "baseLayer": root}
    stock = _run_extracted(node, _hook_only(player).decode(), False, effect)
    patched = _run_extracted(node, live_runtime.patch_player(player).decode(), True, effect)
    mirror = _mirror(effect)
    assert [[old for old, _ in row] for row in mirror] == stock
    assert [[new for _, new in row] for row in mirror] == patched
    for stock_row, patched_row in zip(stock, patched):
        assert patched_row == [old if want is None else want for old, want in zip(stock_row, expected)]


# §5 census mirror: old vs new Opacity per eB-drawn leaf, in Python, following the player's arithmetic
# (`fB.textureInfoFromEffect`, `QB.renderFrameWithContext`, `eB.drawFrame`) and R1-R4. Easing is taken
# as linear: it only feeds from != to animations, and those never reach a non-null chain value.

_UNDEFINED = object()
PERCENTS = (0, 0.5, 1)


def _animations(node: dict) -> list[dict]:
    out = []
    for entry in node.get("animations") or []:
        out.extend([entry] if entry.get("property") else entry.get("animations") or [])
    return out


def _node_opacity(node: dict) -> float | None:
    state = node["initialState"]
    opacity, count = None, 0
    for animation in _animations(node):
        if animation.get("property") == "opacity":
            opacity, count = animation, count + 1
        elif animation.get("property") == "hidden" or animation.get("animations") is not None:
            count = 2
    if state.get("hidden") or count > 1:
        return None
    if opacity is None:
        value = state.get("opacity")
    elif opacity["from"]["scalar"] == opacity["to"]["scalar"] and opacity.get("fillMode") == "both":
        value = opacity["to"]["scalar"]
    else:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _chain_opacity(parent, node: dict):
    if parent is None:
        return None
    value = _node_opacity(node)
    return None if value is None else (1 if parent is _UNDEFINED else parent) * value


def _texture_infos(node: dict, parent, out: list) -> list:
    obed = None if parent is _UNDEFINED else _chain_opacity(parent, node)
    if node.get("texture"):
        out.append((node, obed))
    else:
        for child in node.get("layers") or []:
            _texture_infos(child, _chain_opacity(parent, node), out)
    return out


def _old_opacity(leaf: dict, parent_opacity: float, percent: float, effect_duration: float) -> float:
    state = leaf["initialState"]
    value = 0 if state.get("hidden") else parent_opacity * state["opacity"]
    if not leaf.get("animations"):
        return value
    start = end = 1
    fraction = 0
    for animation in leaf["animations"][0]["animations"]:
        if animation.get("property") != "opacity":
            continue
        start, end = animation["from"]["scalar"], animation["to"]["scalar"]
        begin, duration = 1000 * animation["beginTime"], 1000 * animation["duration"]
        if effect_duration != duration:
            x = percent * effect_duration
            fraction = 0 if x < begin else 1 if x > begin + duration else (x - begin) / duration
        else:
            fraction = percent
    if start != end:
        value = start + (end - start) * fraction
    return value


def _mirror(effect: dict) -> list[list[tuple[float, float]]]:
    """[[(old, new) per leaf] per percent] for one eB-drawn effect."""
    base = effect["baseLayer"]
    parent_opacity = base["initialState"]["opacity"]
    leaves = _texture_infos(base, _UNDEFINED, [])
    rows = []
    for percent in PERCENTS:
        row = []
        for leaf, obed in leaves:
            old = _old_opacity(leaf, parent_opacity, percent, 1000 * effect["duration"])
            row.append((old, old if obed is None else obed))
        rows.append(row)
    return rows


def _effects(node):
    if isinstance(node, dict):
        if "baseLayer" in node and "name" in node and "type" in node:
            yield node
        for value in node.values():
            yield from _effects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _effects(value)


def _signature(node):
    """Effect content without texture/object ids (the committed 1->2 fixture has sanitized texture ids)."""
    if isinstance(node, dict):
        return {k: _signature(v) for k, v in node.items() if k not in ("texture", "toTexture", "objectID")}
    if isinstance(node, list):
        return [_signature(v) for v in node]
    return node


def _census(json_paths) -> tuple[dict[str, int], set[tuple[bool, int]]]:
    """Stats and the changed set {(is P2 1->2, leaf index)} over distinct eB-drawn transitions."""
    reference = _signature(json.loads(EFFECT_1_TO_2.read_text()))
    seen, stats, changed = set(), {"effects": 0, "leaves": 0, "one_to_two": 0}, set()
    for path in json_paths:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        for effect in _effects(data):
            if effect["type"] != "transition" or effect["name"] not in EB_EFFECTS:
                continue
            digest = hashlib.sha1(json.dumps(effect, sort_keys=True).encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            is_one_to_two = _signature(effect) == reference
            stats["effects"] += 1
            stats["one_to_two"] += is_one_to_two
            rows = _mirror(effect)
            stats["leaves"] += len(rows[0])
            for row in rows:
                for index, (old, new) in enumerate(row):
                    if old != new:
                        changed.add((is_one_to_two, index))
    return stats, changed


def test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_in_committed_fixtures():
    effect = json.loads(EFFECT_1_TO_2.read_text())
    rows = _mirror(effect)
    for row in rows:
        assert [old == new for old, new in row] == [True, True, True, True, False]
        assert row[4] == (1, SLOT4_ALPHA)
    paths = sorted(FIXTURE_ROOT.rglob("*.json"))
    stats, changed = _census(paths)
    assert stats["one_to_two"] >= 1 and stats["effects"] > stats["one_to_two"]
    assert changed == {(True, 4)}


@pytest.mark.skipif(not MAIN_OUTPUT.is_dir(), reason="main checkout output/ not available")
def test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_across_real_exports():
    roots = sorted(header.parent.parent for header in MAIN_OUTPUT.rglob("assets/header.json"))
    paths = [path for root in roots for path in sorted((root / "assets").glob("*/*.json"))]
    if not paths:
        pytest.skip("no real exports under output/")
    stats, changed = _census(paths)
    assert stats["one_to_two"] >= 1
    assert changed == {(True, 4)}


@pytest.mark.skipif(not SOURCE_DECK.is_file(), reason="P2 source deck (Minimal Alpha_DSK.key) not available")
def test_mm_opacity_chain_product_matches_the_authored_iwa_opacity():
    """Owner decision 6: the source deck's green square, read offline from IWA with the Magic Move shape-style
    resolver, is authored at the opacity the mirror computes for slot 4 (IWA stores float32)."""
    pytest.importorskip("keynote_parser")
    from obed_edom import iwa_runs
    from obed_edom.iwa_kindindex import derive_kind_index

    objects = iwa_runs._load_deck(SOURCE_DECK)[0]
    slide = objects[iwa_runs.slide_order(objects)[0][0]]
    shapes = [objects[str(rec["id"])] for rec in derive_kind_index(slide, objects) if rec["kind"] == "shape"]
    translucent = [shape for shape in shapes if iwa_runs._mm_shape_style(shape, objects)["opacity"] < 1]
    assert len(translucent) == 1, "the green square must be the only translucent shape on slide 1"
    square = translucent[0]

    effect = json.loads(EFFECT_1_TO_2.read_text())
    wrapper = effect["baseLayer"]["layers"][4]["initialState"]
    geometry = square["super"]["super"]["geometry"]
    assert geometry["size"]["width"] == pytest.approx(wrapper["width"], abs=1e-3)
    assert geometry["size"]["height"] == pytest.approx(wrapper["height"], abs=1e-3)
    assert geometry["position"]["x"] + geometry["size"]["width"] / 2 == pytest.approx(wrapper["position"]["pointX"], abs=1e-3)
    assert geometry["position"]["y"] + geometry["size"]["height"] / 2 == pytest.approx(wrapper["position"]["pointY"], abs=1e-3)

    style_id = iwa_runs._style_id(square)
    fills = []
    while style_id in objects:
        props = objects[style_id]["super"].get("shapeProperties") or {}
        if "fill" in props:
            fills.append(props["fill"]["color"])
        parent = ((objects[style_id]["super"].get("super") or {}).get("parent") or {}).get("identifier")
        style_id = str(parent) if parent is not None else None
    color = fills[0]
    assert color["g"] > 0.5 and color["r"] < 0.2 and color["b"] < 0.2, "slot 4 must be the green square"

    authored = iwa_runs._mm_shape_style(square, objects)["opacity"]
    assert authored == pytest.approx(_mirror(effect)[0][4][1], abs=1e-6)
    assert authored == pytest.approx(SLOT4_ALPHA, abs=1e-6)

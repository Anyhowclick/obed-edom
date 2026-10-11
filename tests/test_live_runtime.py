from __future__ import annotations

import hashlib
import itertools
import json
import math
import shutil
import subprocess

from pathlib import Path
from unittest.mock import ANY

import pytest

from obed_edom import live_runtime
from obed_edom.fixture_paths import fixture, main_checkout


def test_unknown_player_is_refused():
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="live output"):
        live_runtime.patch_player(b"unknown player")
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="preview"):
        live_runtime.patch_rendering(b"unknown player")


def test_patch_requires_exactly_one_hook(monkeypatch):
    for player in (b"no hook", live_runtime._ANCHOR * 2):
        monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)
        with pytest.raises(live_runtime.LiveRuntimeUnsupported):
            live_runtime.patch_player(player)


def test_patch_preserves_surrounding_player(monkeypatch):
    player = b"before;" + live_runtime._ANCHOR + b";after"
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)
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


MAIN_OUTPUT = main_checkout() / "output"
REAL_PLAYER = fixture("p2-binary") / "html-player" / "assets" / "player" / "main.js"
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
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)


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


OLD_PLAYER_SHA256 = "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354"
NEW_PLAYER_SHA256 = "17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91"
# The current Keynote's export (2,369,526 bytes); REAL_PLAYER is the older 2,369,488-byte export.
NEW_PLAYER = MAIN_OUTPUT / "fixtures" / "keynote-player-17c0c938" / "main.js"
REAL_PLAYERS = {OLD_PLAYER_SHA256: REAL_PLAYER, NEW_PLAYER_SHA256: NEW_PLAYER}
# The only difference between the two: the newer player passes `isEvalSupported:!1` to both PDF.js getDocument calls.
NEW_PLAYER_INSERTIONS = (
    (b"{url:Q,cMapUrl:_C,cMapPacked:!0,disableRange:!0", b",isEvalSupported:!1", b"};C.getDocument(A)"),
    (b"C.getDocument({data:Q,cMapUrl:_C,cMapPacked:!0", b",isEvalSupported:!1", b"}).promise."),
)


def _real_player(sha: str = OLD_PLAYER_SHA256) -> bytes:
    if not REAL_PLAYERS[sha].is_file():
        pytest.skip("real player export not available")
    player = REAL_PLAYERS[sha].read_bytes()
    assert hashlib.sha256(player).hexdigest() == sha
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


# sha256 of patch_player(real, mm_opacity=...) and patch_rendering(real), per stock player.
# Old False: recorded on 3eb3b0fe (hook only, unchanged since). True and rendering: with the dissolve replacements
# D1-D4 = R9-R12 (keynote_live_dissolve_crossfade.plan.md); were 574274e8... / fd811938... (old) and 330ef72c... /
# 33fcdcd2... (new) with R1-R8, and old True 21476f78... with R1-R5. New False: recorded when the new player was admitted.
REAL_PATCHED_SHA256 = {
    OLD_PLAYER_SHA256: {
        True: "49d56adcfafe90edd1584da2092af78810b5228bfb8dbec61e8b118a00a0c6f3",
        False: "7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de",
    },
    NEW_PLAYER_SHA256: {
        True: "7a5e315bae89da6050e21efd0d03fac6537158a5d70fd5ae4c390a8ab1137a68",
        False: "4f9fbffd95e4649543142b2e95586babd9d75f0a0d9a4974e21d6f33c8389e3b",
    },
}
REAL_RENDERING_SHA256 = {
    OLD_PLAYER_SHA256: "117fd39db497a696e71bc9a598287b77aed7021939f0a38c8ae21a096b203df8",
    NEW_PLAYER_SHA256: "52d7edb5ff73b2092781a1f32a4ecb6dc0c22247bc2d9d534df5d8115ec51083",
}


def test_supported_players_pin_exactly_the_recorded_outputs():
    assert live_runtime.SUPPORTED_PLAYERS == {
        sha: (REAL_PATCHED_SHA256[sha][True], REAL_PATCHED_SHA256[sha][False], REAL_RENDERING_SHA256[sha])
        for sha in REAL_PLAYERS
    }


@pytest.mark.parametrize("sha", REAL_PLAYERS)
@pytest.mark.parametrize("flag", [True, False])
def test_patch_player_output_is_pinned_on_the_real_player(flag, sha):
    player = _real_player(sha)
    assert hashlib.sha256(live_runtime.patch_player(player, mm_opacity=flag)).hexdigest() == REAL_PATCHED_SHA256[sha][flag]


@pytest.mark.parametrize("sha", REAL_PLAYERS)
def test_patch_rendering_is_the_live_output_minus_the_hook_on_the_real_player(sha):
    player = _real_player(sha)
    rendering = live_runtime.patch_rendering(player)
    assert _hook_only(rendering) == live_runtime.patch_player(player)
    assert b"__obedLive" not in rendering
    assert hashlib.sha256(rendering).hexdigest() == REAL_RENDERING_SHA256[sha]


def _without_insertions(data: bytes) -> bytes:
    for before, inserted, after in NEW_PLAYER_INSERTIONS:
        assert data.count(before + inserted + after) == 1
        data = data.replace(before + inserted + after, before + after)
    return data


def test_new_player_is_the_old_player_plus_two_pdfjs_options_outside_every_anchor():
    old, new = _real_player(OLD_PLAYER_SHA256), _real_player(NEW_PLAYER_SHA256)
    assert len(new) - len(old) == 2 * len(b",isEvalSupported:!1")
    assert old.count(b"isEvalSupported") == 11 and new.count(b"isEvalSupported") == 13
    assert hashlib.sha256(_without_insertions(new)).hexdigest() == OLD_PLAYER_SHA256
    inserted = [(new.index(before + text) + len(before), len(text)) for before, text, _ in NEW_PLAYER_INSERTIONS]
    anchors = [live_runtime._ANCHOR] + [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS]
    for anchor in anchors:
        assert old.count(anchor) == new.count(anchor) == 1
        start = new.index(anchor)
        for offset, length in inserted:
            assert start + len(anchor) <= offset or offset + length <= start
    for _, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert old.count(after) == new.count(after) == 0
    for flag in (True, False):
        assert _without_insertions(live_runtime.patch_player(new, mm_opacity=flag)) == live_runtime.patch_player(old, mm_opacity=flag)
    assert _without_insertions(live_runtime.patch_rendering(new)) == live_runtime.patch_rendering(old)


@pytest.mark.parametrize("pin", range(3))
def test_patched_output_must_match_its_pin(monkeypatch, pin):
    player = _synthetic_player()
    pins = [ANY] * 3
    pins[pin] = "0" * 64
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), tuple(pins))
    patchers = (live_runtime.patch_player, lambda p: live_runtime.patch_player(p, mm_opacity=False), live_runtime.patch_rendering)
    for index, patcher in enumerate(patchers):
        if index == pin:
            with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="pinned digest"):
                patcher(player)
        else:
            patcher(player)


# Hand-back geometry (keynote_live_handback_geometry.plan.md §3.2) is R6-R8; the dissolve cross-fade
# (keynote_live_dissolve_crossfade.plan.md §3.1, §6.1) is D1-D4 = R9-R12. Their anchors' byte offsets on the old and
# new stock players: R8 and D4 sit after both `isEvalSupported` insertions, so they move by 38.
HANDBACK = slice(5, 8)
DISSOLVE = slice(8, 12)
ANCHOR_OFFSETS = {
    b"B[g].toTexture=R.createTexture(this.gl,i)}}return B}": (2263321, 2263321),
    b'case"contents":C=e.toTexture}}var T=': (2190367, 2190367),
    b"this.textureManager.loadScene(B)}unloadTextures(){": (2347821, 2347859),
    b"return B}renderEffects(A){": (2311794, 2311794),
    b"const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});": (2312557, 2312557),
    b"this.cssRenderer.draw(a),a.removeChild(w)}": (2313053, 2313053),
    b"jumpToScene_partFour(A,B){if(this.displayScene(A),": (2353722, 2353760),
}


def test_handback_and_dissolve_replacements_follow_the_opacity_ones():
    replacements = live_runtime._MM_OPACITY_REPLACEMENTS
    assert len(replacements) == 12
    assert [before for before, _ in replacements[HANDBACK.start : DISSOLVE.stop]] == list(ANCHOR_OFFSETS)


def test_handback_anchors_are_unique_on_the_synthetic_player(monkeypatch):
    player = _synthetic_player()
    _pin(monkeypatch, player)
    patched = live_runtime.patch_player(player)
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS[HANDBACK]:
        assert player.count(before) == 1 and player.count(after) == 0
        assert patched.count(before) == 0 and patched.count(after) == 1


@pytest.mark.parametrize("sha", REAL_PLAYERS)
def test_handback_and_dissolve_anchors_sit_at_their_offsets_on_the_real_player(sha):
    player = _real_player(sha)
    assert player.count(b"obedMix") == 0 and player.count(b"__obedHandbackTextures") == 0
    assert player.count(b"obedDissolve") == 0 and player.count(b"__obedFreeze") == 0
    column = list(REAL_PLAYERS).index(sha)
    for before, offsets in ANCHOR_OFFSETS.items():
        assert player.count(before) == 1
        assert player.find(before) == offsets[column]
    # §6.1: the hook and all twelve anchors are 13 disjoint byte intervals of the stock player.
    anchors = [live_runtime._ANCHOR] + [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS]
    intervals = sorted((player.find(anchor), player.find(anchor) + len(anchor)) for anchor in anchors)
    assert len(intervals) == 13
    assert all(end <= start for (_, end), (start, _) in zip(intervals, intervals[1:]))
    patched = live_runtime.patch_player(player)
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS[HANDBACK.start : DISSOLVE.stop]:
        assert patched.count(before) == 0 and patched.count(after) == 1
    # Decision 5b: the rule requires a scale change; translation only enters through the destination-rect match.
    assert patched.count(b"1===sx&&1===sy&&(ok=!1);") == 1
    assert b"0===tx" not in patched
    # The provisional colour tuples and tone map (§9.0) are spliced in once each.
    assert patched.count(b"Q=" + live_runtime._FREEZE_QUALIFIED_TUPLES + b",") == 1
    assert patched.count(b"(UC.__obedLut=" + live_runtime._FREEZE_TONE_LUT + b")") == 1
    off = live_runtime.patch_player(player, mm_opacity=False)
    for marker in (b"obedMix", b"__obedHandbackTextures", b"obedDissolve", b"__obedFreeze", b"__obedShape"):
        assert marker not in off


def _apply_in_order(player: bytes, replacements) -> bytes:
    for before, after in replacements:
        assert player.count(before) == 1
        player = player.replace(before, after)
        assert player.count(after) == 1
    return player


@pytest.mark.parametrize("sha", [None, *REAL_PLAYERS], ids=["synthetic", "real-old", "real-new"])
def test_opacity_handback_and_dissolve_replacements_compose_in_every_order(monkeypatch, sha):
    if sha:
        player = _real_player(sha)
    else:
        player = _synthetic_player()
        _pin(monkeypatch, player)
    replacements = live_runtime._MM_OPACITY_REPLACEMENTS
    # No replacement's text contains any anchor, its own included, so none can be re-matched or reverted into another.
    for _, after in replacements:
        for before, _ in replacements:
            assert before not in after
    groups = (replacements[: HANDBACK.start], replacements[HANDBACK], replacements[DISSOLVE])
    outputs = {_apply_in_order(player, [r for group in order for r in group]) for order in itertools.permutations(groups)}
    assert outputs == {live_runtime.patch_rendering(player)}


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


@pytest.mark.parametrize("sha", REAL_PLAYERS)
def test_mm_opacity_patched_real_player_parses(tmp_path, sha):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to syntax-check the patched player")
    player = _real_player(sha)
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


# Dissolve cross-fade (keynote_live_dissolve_crossfade.plan.md §3, §8): the real D1-D4 methods cut out of each patched
# player, run under Node against stub sheets and stub DOMs. Ports the planner's `node_r6_test_r12.py`,
# `node_r12_near.py`, `node_ids.py`, `node_f3_r12_test.py` and `node_f3_r12_decks.py` with their tables in Python.

OUTPUT_FIXTURES = MAIN_OUTPUT / "fixtures"
FREEZE_SLIDE = "C75DC221-E44A-4762-9B1F-3C2FAAF7D19E"
FREEZE_EFFECT = FIXTURE_ROOT / "minimal_alpha_dsk" / "assets" / FREEZE_SLIDE / f"{FREEZE_SLIDE}.json"
FREEZE_DECKS = {
    "P2": OUTPUT_FIXTURES / "p2-binary" / "html-unmodified" / "assets",
    "DSK": OUTPUT_FIXTURES / "minimal-alpha-dsk-17c0c938" / "html" / "assets",
}

# The player's module-scope names the real `let TB`, `yB`/`WB`/`VB` classes read, stubbed as `node_ids.py` does.
DISSOLVE_PLAYER_SCOPE = r"""
const UC={animationManager:{styleSheet:null,createAnimation(n){return {appendRule(){}}}}};
function p(){return false} function r(A){return A.replace(/\./g,"-")} function n(x){return x}
const LC="-webkit-animation-timing-function",xC="-webkit-transform-origin",OC="-webkit-transform",TC="-webkit-transform-origin-z",hg="opacity",lg="visibility",PC="-webkit-backface-visibility",XC="background-image",SC=!1,mC=!0,pC=!1,HC=!1;
"""

# A CSSOM stub: `drop` empties a declaration on read-back (unsupported value), `throwAt` makes that insert throw.
DISSOLVE_CONSTRUCTION_JS = r"""
class P{%METHODS%}
function sheet(o={}){let calls=0;const rules=[];return {rules,insertRule(text,i){calls++;if(o.throwAt===calls)throw new Error('insert');
  const m=/^(.*)\{(.*):(.*)\}$/.exec(text);const prop=m[2]==='isolation'?'isolation':'mixBlendMode';const ok=!(o.drop||[]).includes(m[2]);
  rules.splice(i,0,{selectorText:m[1],style:{[prop]:ok?m[3]:''}});return i},get cssRules(){return rules}}}
const IN=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const pp=new P();
const tree=(e)=>e.baseLayer.layers[0].layers;
const summary={dissolve:0,cut:0,stock:0,mutated:0,badCopy:0,badIds:0,stockTouched:0};
for(const e of IN.transitions){UC.animationManager.styleSheet=sheet();const b=JSON.stringify(e);const before=TB;const C={type:e.type,name:e.name,baseLayer:e.baseLayer};
  const res=pp.__obedDissolveLayer(C);if(JSON.stringify(e)!==b)summary.mutated++;const rules=UC.animationManager.styleSheet.rules;
  if(res===e.baseLayer){summary.stock++;if(rules.length||C.obedDissolve||TB!==before)summary.stockTouched++;continue}
  const L=res.layers[0].layers,a=L[0].animations[0],cut=e.name==='none';summary[cut?'cut':'dissolve']++;
  const ok=cut?C.obedDissolve==='cut'&&rules.length===0&&L[0].initialState.hidden===true&&a.property==='hidden'&&a.from.scalar===true&&a.to.scalar===false
    :C.obedDissolve==='dissolve'&&L[0].initialState.opacity===0&&a.property==='opacity'&&a.from.scalar===0&&a.to.scalar===1&&a.duration===tree(e)[1].animations[0].duration;
  if(!ok||L[1]!==tree(e)[1]||L.length!==2)summary.badCopy++;
  const v=new VB(res,{name:e.name,type:e.type,objectID:e.objectID});const c=v.layers[0];
  const ids=[v.layerId,c.layerId,c.layers[0].layerId,c.layers[1].layerId,TB];
  const want=cut?[]:[['#layer'+(before+2)+',#layer'+(before+3),'mixBlendMode','plus-lighter'],['#layer'+(before+1),'isolation','isolate']];
  if(JSON.stringify(ids)!==JSON.stringify([before,before+1,before+2,before+3,before+4])||JSON.stringify(rules.map(x=>[x.selectorText,...Object.entries(x.style)[0]]))!==JSON.stringify(want))summary.badIds++;}
const pick=n=>JSON.parse(JSON.stringify(IN.transitions.find(e=>e.name===n&&e.baseLayer&&e.baseLayer.layers&&e.baseLayer.layers[0]&&e.baseLayer.layers[0].layers)));
const at=(o,path)=>path.reduce((x,k)=>x[k],o);
const near={};
for(const [name,[effect,ops,opts]] of Object.entries(IN.nearMisses)){const e=pick(effect);
  for(const [op,path,value] of ops){const parent=at(e,path.slice(0,-1)),key=path[path.length-1];
    if(op==='set')parent[key]=value;else if(op==='delete')delete parent[key];else parent[key].push(JSON.parse(JSON.stringify(at(e,value))))}
  UC.animationManager.styleSheet=sheet(opts);const C={type:e.type,name:e.name,baseLayer:e.baseLayer};const res=pp.__obedDissolveLayer(C);
  near[name]=res===e.baseLayer&&!C.obedDissolve?'stock':'copied:'+C.obedDissolve}
const failures={};
for(const [name,o] of Object.entries(IN.failures)){UC.animationManager.styleSheet=o.noStyleSheet?undefined:sheet(o);
  const e=pick('apple:dissolve');const before=TB;const C={type:e.type,name:e.name,baseLayer:e.baseLayer};const res=pp.__obedDissolveLayer(C);
  const v=new VB(res,{name:e.name,type:e.type,objectID:e.objectID});const built=[v.layers[0].layerId,v.layers[0].layers[0].layerId,v.layers[0].layers[1].layerId];
  const rules=(UC.animationManager.styleSheet||{rules:[]}).rules;
  failures[name]={stock:res===e.baseLayer,kind:C.obedDissolve||null,skippedIds:v.layerId-before,rules:rules.length,
    rulesTargetBuilt:rules.some(x=>built.some(id=>x.selectorText.split(',').includes('#layer'+id))),incomingOpacity:v.layers[0].layers[0].opacity,
    incomingRules:v.layers[0].layers[0].cssAnimationRules.length}}
console.log(JSON.stringify({summary,near,failures}));
"""


def _leaf(index: int) -> list:
    return ["baseLayer", "layers", 0, "layers", index]


OUTGOING = _leaf(1) + ["animations", 0]
BOTH_DECLARATIONS_DROPPED = {"drop": ["isolation", "mix-blend-mode"]}
# name -> (exported effect it mutates, [(set | delete | push, path, value or source path)], sheet options) and whether
# the predicate engages. 21 Dissolve and 10 cut near-misses stay stock (§3.2), beside one positive control each.
DISSOLVE_NEAR_MISSES = {
    "dissolveBaseline": ("apple:dissolve", [], {}),
    "cssUnsupported": ("apple:dissolve", [], BOTH_DECLARATIONS_DROPPED),
    "buildType": ("apple:dissolve", [("set", ["type"], "buildIn")], {}),
    "otherName": ("apple:dissolve", [("set", ["name"], "apple:dissolve character")], {}),
    "from05": ("apple:dissolve", [("set", OUTGOING + ["from", "scalar"], 0.5)], {}),
    "twoAnims": ("apple:dissolve", [("push", _leaf(1) + ["animations"], OUTGOING)], {}),
    "incomingAnimated": (
        "apple:dissolve", [("set", _leaf(0) + ["animations"], [{"property": "opacity", "from": {"scalar": 1}, "to": {"scalar": 1}}])], {}
    ),
    "threeLeaves": ("apple:dissolve", [("push", ["baseLayer", "layers", 0, "layers"], _leaf(0))], {}),
    "incomingTranslucent": ("apple:dissolve", [("set", _leaf(0) + ["initialState", "opacity"], 0.5)], {}),
    "keyTimes": ("apple:dissolve", [("set", OUTGOING + ["keyTimes"], [0, 1])], {}),
    "noLayers": ("apple:dissolve", [("delete", ["baseLayer", "layers"], None)], {}),
    "videoLayer": ("apple:dissolve", [("set", _leaf(0) + ["isVideoLayer"], True)], {}),
    "posterLayer": ("apple:dissolve", [("set", _leaf(1) + ["isWebVideoPosterLayer"], True)], {}),
    "leafObjectID": ("apple:dissolve", [("set", _leaf(1) + ["objectID"], "X")], {}),
    "containerObjectID": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "objectID"], "X")], {}),
    "affine": ("apple:dissolve", [("set", _leaf(0) + ["initialState", "affineTransform"], [1, 0, 0, 1, 5, 0])], {}),
    "rotation": ("apple:dissolve", [("set", _leaf(1) + ["initialState", "rotation"], 0.1)], {}),
    "scale": ("apple:dissolve", [("set", _leaf(1) + ["initialState", "scale"], 1.1)], {}),
    "transform3d": (
        "apple:dissolve", [("set", _leaf(0) + ["initialState", "transform"], [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -0.001, 0, 0, 0, 1])], {}
    ),
    "leafSublayer": ("apple:dissolve", [("set", _leaf(0) + ["initialState", "sublayerTransform", 11], -0.001)], {}),
    "containerRotation": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "initialState", "rotation"], 0.2)], {}),
    "nullBase": ("apple:dissolve", [("set", ["baseLayer"], None)], {}),
    "cutBaseline": ("none", [], {}),
    "cutDuration100ms": ("none", [("set", OUTGOING + ["duration"], 0.1)], {}),
    "cutFillRemoved": ("none", [("set", OUTGOING + ["fillMode"], "removed")], {}),
    "cutFillForwards": ("none", [("set", OUTGOING + ["fillMode"], "forwards")], {}),
    "cutBegin05": ("none", [("set", OUTGOING + ["beginTime"], 0.5)], {}),
    "cutTiming": ("none", [("set", OUTGOING + ["timingFunction"], "EaseInEaseOut")], {}),
    "cutTimeOffset": ("none", [("set", OUTGOING + ["timeOffset"], 0.2)], {}),
    "cutRepeat": ("none", [("set", OUTGOING + ["repeatCount"], 2)], {}),
    "cutAutoreverse": ("none", [("set", OUTGOING + ["autoreverses"], True)], {}),
    "cutSwapped": ("none", [("set", OUTGOING + ["from", "scalar"], True), ("set", OUTGOING + ["to", "scalar"], False)], {}),
    "cutOpacity": ("none", [("set", OUTGOING + ["property"], "opacity")], {}),
}
DISSOLVE_NEAR_MISS_ENGAGED = {"dissolveBaseline": "copied:dissolve", "cutBaseline": "copied:cut"}
# Construction failures (§3.2): each builds the export's own tree; a partial insert abandons the four ids it named.
_STOCK_BUILD = {"stock": True, "kind": None, "rulesTargetBuilt": False, "incomingOpacity": 1, "incomingRules": 0}
DISSOLVE_CONSTRUCTION_FAILURES = {
    "droppedBlend": ({"drop": ["mix-blend-mode"]}, dict(_STOCK_BUILD, skippedIds=4, rules=2)),
    "droppedIsolation": ({"drop": ["isolation"]}, dict(_STOCK_BUILD, skippedIds=4, rules=2)),
    "throwFirstInsert": ({"throwAt": 1}, dict(_STOCK_BUILD, skippedIds=0, rules=0)),
    "throwSecondInsert": ({"throwAt": 2}, dict(_STOCK_BUILD, skippedIds=4, rules=1)),
    "noStyleSheet": ({"noStyleSheet": True}, dict(_STOCK_BUILD, skippedIds=0, rules=0)),
    "success": ({}, {"stock": False, "kind": "dissolve", "skippedIds": 0, "rules": 2, "rulesTargetBuilt": True,
                     "incomingOpacity": 0, "incomingRules": 1}),
}


def _transitions(*roots: Path) -> list[dict]:
    """Every exported transition effect under the export roots (each `header.json`'s slides), in a stable order."""
    effects = []
    for header in sorted(header for root in roots for header in root.rglob("header.json")):
        for sid in json.loads(header.read_text())["slideList"]:
            path = header.parent / sid / f"{sid}.json"
            if path.is_file():
                for event in json.loads(path.read_text()).get("events") or []:
                    effects.extend(e for e in event.get("effects") or [] if e.get("type") == "transition")
    return effects


# The freeze stub DOM (`node_f3_r12_test.py`): §1.1's live slide with UA-correct replaced overflow and a zero-height
# static body; the video is a Proxy recording any write or method call other than the three reads D4 may make.
FREEZE_STUB_JS = r"""
let TB=0;const EFF=%EFF%;
class P{constructor(si){this.sceneIndex=si}%METHODS%}
globalThis.DOMMatrix=class{constructor(s){const m=/matrix(3d)?\(([^)]*)\)/.exec(s);const v=m[2].split(',').map(Number);this.is2D=!m[1];this.a=v[0];this.b=v[1];this.c=m[1]?v[4]:v[2];this.d=m[1]?v[5]:v[3]}};
const BASE={display:'block',opacity:'1',transform:'none',filter:'none',mixBlendMode:'normal',clipPath:'none',maskImage:'none',zIndex:'auto',overflowX:'visible',overflowY:'visible',position:'absolute',
  borderTopLeftRadius:'0px',borderTopRightRadius:'0px',borderBottomLeftRadius:'0px',borderBottomRightRadius:'0px',objectPosition:'50% 50%',paddingTop:'0px',paddingLeft:'0px',paddingRight:'0px',paddingBottom:'0px',
  borderTopStyle:'none',borderRightStyle:'none',borderBottomStyle:'none',borderLeftStyle:'none',objectFit:'contain',backgroundColor:'rgba(0, 0, 0, 0)',backgroundImage:'none',boxShadow:'none',outlineStyle:'none',
  transformStyle:'flat',scale:'none',rotate:'none',translate:'none',offsetPath:'none',clip:'auto',backdropFilter:'none',objectViewBox:'none',contain:'none',contentVisibility:'visible',isolation:'auto',
  perspective:'none',backfaceVisibility:'visible',willChange:'auto',zoom:'1',imageRendering:'auto',visibility:'visible',borderImageSource:'none',webkitBoxReflect:'none',content:'normal',columnRuleStyle:'none'};
const r6=v=>Math.round(v*1e6)/1e6;
function run(o){
  const touched=[];const all=[];const draws=[];const s=o.scale||1,ox=(o.off||[0,0])[0],oy=(o.off||[0,0])[1];const TR=r=>[ox+r[0]*s,oy+r[1]*s,r[2]*s,r[3]*s];
  const el=(tag,id,cs,rect0,parent,extra)=>{const rect=TR(rect0);const e=Object.assign({tagName:tag,id,nodeType:1,_cs:Object.assign({},BASE,tag==='CANVAS'?{objectFit:'fill',overflowX:'clip',overflowY:'clip'}:{},tag==='VIDEO'?{overflowX:'clip',overflowY:'clip'}:{},cs||{}),childNodes:[],children:[],style:{},parentElement:parent||null,
     getBoundingClientRect:()=>({left:rect[0],top:rect[1],width:rect[2],height:rect[3],right:rect[0]+rect[2],bottom:rect[1]+rect[3]}),
     checkVisibility(op){for(let p=this;p;p=p.parentElement){if(p._cs.display==='none')return false;if(op&&op.opacityProperty&&+p._cs.opacity===0)return false}if(this._cs.display==='contents')return false;if(op&&op.visibilityProperty&&this._cs.visibility!=='visible')return false;return true},contains(x){for(let p=x;p;p=p.parentElement)if(p===this)return true;return false},getElementsByTagName(){return all.filter(x=>x!==this&&this.contains(x))},
     appendChild(c){if(this._throw)throw new Error('append');if(c.children&&!c.tagName){c.children.forEach(x=>this.children.push(x));c.children=[]}else this.children.push(c)}},extra||{});all.push(e);return e};
  const html=el('HTML','html',Object.assign({position:'static'},o.htmlCs||{}),[0,0,1920,1080]);const body=el('BODY','body',{position:'static',backgroundColor:'rgb(0, 0, 0)',overflowX:'hidden',overflowY:'hidden'},[0,0,1920,0],html);
  const area=el('DIV','stageArea',{overflowX:'hidden',overflowY:'hidden',visibility:'hidden'},[0,0,1920,1080],body);
  const stage=el('DIV','stage',Object.assign({transformStyle:'preserve-3d',transform:'matrix(1, 0, 0, 1, 0, 0)',visibility:'hidden'},o.stageCs||{}),[0,0,1920,1080],area);
  const root=el('DIV','layer1',Object.assign({transform:'matrix(1, 0, 0, 1, 0, 0)'},o.rootCs||{}),[0,0,1920,1080],stage);
  if(o.earlyZ)el('CANVAS','zcover',{zIndex:'5'},[100,780,400,100],root);if(o.earlyCanvas)el('CANVAS','early',o.earlyCanvas,[100,780,400,100],root);
  if(o.behind)el('CANVAS','behind',{},[100,780,400,100],root);
  const oldBase=el('DIV','layer9',o.chainStatic?{position:'static'}:{},[0,0,1920,1080],root);
  const mlayer=el('DIV','layerM',Object.assign(o.chainStatic?{position:'static'}:{},o.layerCs||{}),o.clip||[109,795,952,268],oldBase);
  const raw=el('VIDEO','vid',Object.assign(o.chainStatic?{position:'static'}:{},o.videoCs||{}),o.vrect||[109,795,952,268],mlayer,{readyState:o.rs==null?4:o.rs,videoWidth:1920,videoHeight:540,checkVisibility:()=>o.visible!==false});
  const video=new Proxy(raw,{set(t,k,v){touched.push('set '+String(k));t[k]=v;return true},get(t,k){const v=t[k];if(typeof v==='function'&&!['checkVisibility','getBoundingClientRect','contains'].includes(k))touched.push('call '+String(k));return v}});
  all[all.indexOf(raw)]=video;
  if(o.video2)el('VIDEO','vid2',o.video2cs||{},[600,800,400,200],mlayer,{readyState:4,videoWidth:1920,videoHeight:540});
  if(o.fg){let par=root;if(o.fg.group){par=el('DIV','grp',o.fg.group,[0,0,1920,1080],root);if(o.fg.sibling)el('CANVAS','sib',{},[1500,100,100,100],par)}
    if(o.fg.wrap)par=el('DIV','fgwrap',o.fg.wrap,o.fg.rect,par);if(o.fg.hostGroup)par=el('DIV','fghost',o.fg.hostGroup,[0,0,1920,1080],par);const fe=el(o.fg.tag||'CANVAS','fg',o.fg.cs||{},o.fg.rect,o.fg.outside?body:par);if(o.fg.pseudo)fe._pseudo=o.fg.pseudo;if(o.fg.text)fe.childNodes=[{nodeType:3,data:'Hi'}]}
  const t1=el('DIV','layer10',{},[0,0,1920,1080],stage),c1=el('DIV','layer11',{},[0,0,1920,1080],t1);el('DIV','layer12',{},[0,0,1920,1080],c1);
  const leafOut=el('DIV','layer13',{},[0,0,1920,1080],c1);const wrap=o.noWrap?null:el('DIV','layer13-opacity',{},[0,0,1920,1080],leafOut);
  if(o.appendThrows&&wrap)wrap._throw=true;
  const ids={};all.forEach(e=>ids[e.id]=e);if(o.noOldBase)delete ids.layer9;
  let put=null;const px=(w,h)=>{const d=new Uint8ClampedArray(w*h*4).fill(o.grey==null?255:o.grey);for(let p=3;p<d.length;p+=4)d[p]=255;if(o.alphaAt!=null&&o.alphaAt<w*h)d[o.alphaAt*4+3]=o.alphaVal==null?254:o.alphaVal;return d};
  globalThis.document={documentElement:html,body,getElementById:id=>ids[id]||null,querySelectorAll:()=>all.filter(e=>e.tagName==='VIDEO'),getElementsByTagName:()=>all,
    createDocumentFragment:()=>({children:[],appendChild(c){this.children.push(c)}}),
    createElement:t=>t==='canvas'?{style:{},width:0,height:0,getContext(){const ctx={globalAlpha:1,drawImage:(src,...a)=>{if(o.drawThrows&&src===video)throw new Error('draw');draws.push([src.id,ctx.globalAlpha,...a.map(r6)])},getImageData:(x,y,w,h)=>({data:px(w,h)}),putImageData:(D)=>{put=D.data[0]}};return ctx}}:{style:{},children:[],appendChild(c){this.children.push(c)}}};
  globalThis.getComputedStyle=(e,p)=>p?{content:(e._pseudo&&e._pseudo[p])||'none'}:(e._cs||BASE);globalThis.innerWidth=1920;globalThis.window=globalThis;globalThis.innerHeight=1080;
  const tuple=o.vf===undefined?['bt709','bt709','bt709',false]:o.vf;let vfOpened=0,vfClosed=0;
  if(tuple==='missing')delete globalThis.VideoFrame;else globalThis.VideoFrame=class{constructor(x){if(tuple==='throws')throw new Error('vf');vfOpened++;this.colorSpace={primaries:tuple[0],transfer:tuple[1],matrix:tuple[2],fullRange:tuple[3]}}close(){vfClosed++}};
  let clk=0;globalThis.performance={now:()=>{const v=clk;clk+=o.clock||1;return v}};globalThis.__obedTakeMs=undefined;
  const U={script:o.throwScript?null:{slideWidth:1920,slideHeight:1080,events:[{effects:[EFF]}]},playbackController:{kpfEvent:{baseLayer:{layerId:9}}}};globalThis.UC=U;
  P.prototype.__obedFreezeTake(U,0);const taken=U.__obedFrozen?U.__obedFrozen.holders.length:0;
  new P(0).__obedFreeze({obedDissolve:o.kind||'dissolve'},{layers:[{layers:[{layerId:12},{layerId:13}]}]});
  const h=(wrap&&wrap.children[0])||leafOut.children[0];const geo=h?[h.style.left,h.style.top,h.style.width,h.style.height].map(v=>r6(parseFloat(v))).join(','):'';
  return {taken,inWrap:wrap?wrap.children.length:0,inLeaf:leafOut.children.length,draws:draws.filter(d=>d[0]!=='vid'),geo,put,
    touched,ms:U.__obedTakeMs,windowMs:globalThis.__obedTakeMs,slotCleared:UC.__obedFrozen===null,vfOpened,vfClosed};
}
const CASES=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const out={};for(const k in CASES)out[k]=run(CASES[k]);console.log(JSON.stringify(out));
"""

# §3.2's allowlist, one out-of-profile computed value per property. Each value is applied, alone, to the movie chain
# (`layerM`), the `<video>` and a redrawn foreground canvas (plain bitmap), or a confined non-intersecting `div` (paint
# gate), per the family lists below; every such row must skip the take.
OUT_OF_PROFILE = {
    "display": "flex", "position": "relative", "contain": "paint", "contentVisibility": "auto",
    "filter": "drop-shadow(rgb(0, 0, 0) -200px 0px 0px)", "backdropFilter": "blur(4px)", "mixBlendMode": "screen",
    "isolation": "isolate", "clipPath": "circle(50%)", "maskImage": "linear-gradient(black, transparent)",
    "clip": "rect(0px, 10px, 10px, 0px)", "zIndex": "2", "translate": "5px", "rotate": "10deg", "scale": "2",
    "offsetPath": 'path("M0 0 L9 9")', "willChange": "transform", "zoom": "2", "outlineStyle": "solid",
    "perspective": "500px", "backfaceVisibility": "hidden", "transformStyle": "preserve-3d", "visibility": "hidden",
    "overflowX": "clip", "transform": "matrix(-1, 0, 0, 1, 0, 0)",
    "backgroundColor": "rgb(0, 128, 0)", "backgroundImage": "url(x.png)", "boxShadow": "rgb(255, 0, 0) -200px 0px 0px 0px",
    "borderTopStyle": "solid", "borderTopLeftRadius": "8px", "paddingTop": "4px", "objectViewBox": "inset(25%)",
    "imageRendering": "pixelated", "borderImageSource": "linear-gradient(red, red)", "webkitBoxReflect": "left 0px",
    "content": 'url("foreground.png")', "columnRuleStyle": "solid",
}
CHAIN_PROPERTIES = (
    "display", "position", "contain", "contentVisibility", "filter", "backdropFilter", "mixBlendMode", "isolation",
    "clipPath", "maskImage", "clip", "zIndex", "translate", "rotate", "scale", "offsetPath", "willChange", "zoom",
    "outlineStyle", "perspective", "backfaceVisibility", "transformStyle", "visibility", "overflowX", "transform",
)
# Companions keep the row about its own property: both overflow axes move together; `preserve-3d` is allowed without
# a transform (the build wrappers), so it needs one.
CHAIN_COMPANIONS = {"overflowX": {"overflowY": "clip"}, "transformStyle": {"transform": "matrix(1, 0, 0, 1, 5, 5)"}}
BITMAP_PROPERTIES = (
    "backgroundColor", "backgroundImage", "boxShadow", "borderTopStyle", "borderTopLeftRadius", "outlineStyle",
    "paddingTop", "objectViewBox", "imageRendering", "backdropFilter",
)
GATE_PROPERTIES = (
    "boxShadow", "filter", "backdropFilter", "outlineStyle", "borderImageSource", "webkitBoxReflect", "content",
    "columnRuleStyle",
)
FG_RECT = [788, 673, 353, 313]
CONFINED = [1100, 800, 100, 100]
ROTATED = "matrix(0.98, 0.17, -0.17, 0.98, 0, 0)"


def _fg(**kwargs) -> dict:
    return {"rect": FG_RECT, **kwargs}


def _gate(**kwargs) -> dict:
    return {"fg": _fg(**{"tag": "DIV", "rect": CONFINED, **kwargs})}


FREEZE_GEO = "109,795.125,952,267.75"
FREEZE_FILL_GEO = "109,795,960,270"
FREEZE_SKIP = {"taken": 0, "inWrap": 0, "inLeaf": 0, "draws": [], "put": None, "geo": ""}
FREEZE_ADMIT = {"taken": 1, "inWrap": 1, "inLeaf": 0, "draws": [], "put": 255, "geo": FREEZE_GEO}
FG_DRAW = [1369.411765, -246.302521, 711.932773, 631.260504]
# name -> (stub options, expected take/attach count and target, redraws [id, alpha, x, y, w, h], `L` output, geometry).
FREEZE_ROWS = {
    "success": ({}, FREEZE_ADMIT),
    "stage2560": ({"scale": 4 / 3}, dict(FREEZE_ADMIT, geo="109,795.125,952,14.875")),
    "letterbox": ({"scale": 0.75, "off": [240, 135]}, FREEZE_ADMIT),
    "uniformScale": ({"layerCs": {"transform": "matrix(0.75, 0, 0, 0.75, 10, 20)"}}, FREEZE_ADMIT),
    "realCut": ({"kind": "cut", "noWrap": True}, dict(FREEZE_ADMIT, inWrap=0, inLeaf=1)),
    "dissolveMissingWrapper": ({"noWrap": True}, dict(FREEZE_ADMIT, inWrap=0, geo="")),
    "appendThrows": ({"appendThrows": True}, dict(FREEZE_ADMIT, inWrap=0, geo="")),
    "letterboxedVideo": ({"vrect": [109, 700, 952, 500]}, dict(FREEZE_ADMIT, geo="109,816.125,952,263.875")),
    "clippedPanel": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden"}, "clip": [109, 795, 300, 268]},
                     dict(FREEZE_ADMIT, geo="109,795.125,300,267.75")),
    "fillSameAspect": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 960, 270], "clip": [109, 795, 960, 270]},
                       dict(FREEZE_ADMIT, geo=FREEZE_FILL_GEO)),
    "fillAspectChange": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 952, 134], "clip": [109, 795, 952, 134]}, FREEZE_SKIP),
    "fgCanvas": ({"fg": _fg()}, dict(FREEZE_ADMIT, draws=[["fg", 1, *FG_DRAW]])),
    "fgTranslucent": ({"fg": _fg(cs={"opacity": "0.2947"})}, dict(FREEZE_ADMIT, draws=[["fg", 0.2947, *FG_DRAW]])),
    "fgGroupOpacityAlone": ({"fg": _fg(group={"opacity": "0.5"})}, dict(FREEZE_ADMIT, draws=[["fg", 0.5, *FG_DRAW]])),
    "fgGroupOpacityWithSibling": ({"fg": _fg(group={"opacity": "0.5"}, sibling=True)}, FREEZE_SKIP),
    "fgPlacementFill": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 960, 270], "clip": [109, 795, 960, 270],
                         "fg": _fg(rect=[788, 850, 353, 313])},
                        dict(FREEZE_ADMIT, geo=FREEZE_FILL_GEO, draws=[["fg", 1, 1358, 110, 706, 626]])),
    "fgNotIntersecting": ({"fg": _fg(rect=[1300, 100, 300, 200])}, FREEZE_ADMIT),
    "fgPlainDiv": ({"fg": _fg(tag="DIV")}, FREEZE_ADMIT),
    "fgDivWithBg": ({"fg": _fg(tag="DIV", cs={"backgroundColor": "rgb(0, 0, 0)"})}, FREEZE_SKIP),
    "fgImg": ({"fg": _fg(tag="IMG")}, FREEZE_SKIP),
    "fgOutsideScene": ({"fg": _fg(outside=True)}, FREEZE_SKIP),
    "fgClippedBranch": ({"fg": _fg(wrap={"overflowX": "hidden", "overflowY": "hidden"})}, FREEZE_SKIP),
    "fgCanvas_objectFitContain": ({"fg": _fg(cs={"objectFit": "contain"})}, FREEZE_SKIP),
    "fgBranch_contain": ({"fg": _fg(wrap={"contain": "paint"})}, FREEZE_SKIP),
    "fgBranch_rotate": ({"fg": _fg(cs={"transform": ROTATED})}, FREEZE_SKIP),
    "earlierPositionedBehind": ({"earlyCanvas": {}}, FREEZE_ADMIT),
    "earlierStatic": ({"earlyCanvas": {"position": "static"}}, FREEZE_SKIP),
    "earlierPositionedOverStaticChain": ({"chainStatic": True, "earlyCanvas": {}}, FREEZE_SKIP),
    "earlierZIndex": ({"earlyZ": True}, FREEZE_SKIP),
    "flexOrder": ({"rootCs": {"display": "flex"}, "earlyCanvas": {"order": "1"}}, FREEZE_SKIP),
    "overlappingVideos": ({"video2": True}, dict(FREEZE_ADMIT, taken=2, inWrap=2, draws=[["vid2", 1, 0, 0]])),
    "overlapLaterNotAdmitted": ({"video2": True, "video2cs": {"objectFit": "cover"}}, FREEZE_SKIP),
    "sparseAlpha": ({"alphaAt": 12345}, FREEZE_SKIP),
    "edgeAlpha": ({"alphaAt": 0, "alphaVal": 0}, FREEZE_SKIP),
    "lowerTransparency": ({"alphaAt": 400 * 1920 + 5, "alphaVal": 0}, FREEZE_SKIP),
    "notReady": ({"rs": 1}, FREEZE_SKIP),
    "invisible": ({"visible": False}, FREEZE_SKIP),
    "translucentAncestor": ({"layerCs": {"opacity": "0.5"}}, FREEZE_SKIP),
    "drawThrows": ({"drawThrows": True}, FREEZE_SKIP),
    "noOldBase": ({"noOldBase": True}, FREEZE_SKIP),
    "clippedAway": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden"}, "clip": [0, 0, 50, 50]}, FREEZE_SKIP),
    "lutGrey128": ({"grey": 128}, dict(FREEZE_ADMIT, put=139)),
    "stageNonUniform": ({"stageCs": {"transform": "matrix(1, 0, 0, 0.99, 0, 0)"}}, FREEZE_SKIP),
    "stageNearUniform": ({"stageCs": {"transform": "matrix(1, 0, 0, 0.9995, 0, 0)"}}, FREEZE_ADMIT),
    "tupleFullRange": ({"vf": ["bt709", "bt709", "bt709", True]}, FREEZE_SKIP),
    "tupleBt2020Primaries": ({"vf": ["bt2020", "bt709", "bt2020-ncl", False]}, FREEZE_SKIP),
    "tupleNullTransfer": ({"vf": ["bt709", None, "bt709", False]}, FREEZE_SKIP),
    "tupleUntaggedNulls": ({"vf": [None, None, None, None]}, FREEZE_SKIP),
    "videoFrameMissing": ({"vf": "missing"}, FREEZE_SKIP),
    "videoFrameThrows": ({"vf": "throws"}, FREEZE_SKIP),
    "costSuccess": ({"clock": 37}, FREEZE_ADMIT),
    "costRejected": ({"clock": 37, "rs": 1}, FREEZE_SKIP),
    "costException": ({"clock": 37, "throwScript": True}, FREEZE_SKIP),
    "leafOverflowVisible": ({"videoCs": {"overflowX": "visible", "overflowY": "visible"}}, FREEZE_ADMIT),
    "rootOverflowHidden": ({"htmlCs": {"overflowX": "hidden", "overflowY": "hidden"}}, FREEZE_ADMIT),
    "bodyStaticClipIgnored": ({"htmlCs": {"overflowX": "hidden", "overflowY": "hidden"}}, FREEZE_ADMIT),
    "wrapperPreserve3dNoTransform": ({"layerCs": {"transformStyle": "preserve-3d"}}, FREEZE_ADMIT),
    "chain_transformNonUniform": ({"layerCs": {"transform": "matrix(1, 0, 0, 0.8, 0, 0)"}}, FREEZE_SKIP),
    "chain_transformRotate": ({"layerCs": {"transform": ROTATED}}, FREEZE_SKIP),
    "chain_transform3d": ({"layerCs": {"transform": "matrix3d(1,0,0,0,0,1,0,0,0,0,1,-0.001,0,0,0,1)"}}, FREEZE_SKIP),
    "chain_overflowOneAxis": ({"layerCs": {"overflowX": "hidden"}}, FREEZE_SKIP),
    "chain_overflowRadius": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden", "borderTopLeftRadius": "50%"}}, FREEZE_SKIP),
    "video_objectPosition": ({"videoCs": {"objectPosition": "0% 50%"}}, FREEZE_SKIP),
    "video_cover": ({"videoCs": {"objectFit": "cover"}}, FREEZE_SKIP),
    "gate_listItem": (_gate(cs={"display": "list-item"}), FREEZE_SKIP),
    "gate_before": (_gate(pseudo={"::before": '"x"'}), FREEZE_SKIP),
    "gate_after": (_gate(pseudo={"::after": 'url("x.png")'}), FREEZE_SKIP),
    "gate_text": (_gate(text=True), FREEZE_SKIP),
    "gate_replacedOverflowCover": (_gate(tag="IMG", cs={"overflowX": "visible", "overflowY": "visible", "objectFit": "cover"}),
                                   FREEZE_SKIP),
    "gate_imgShiftedOutside": (_gate(tag="IMG", cs={"overflowX": "visible", "overflowY": "visible", "objectFit": "contain",
                                                    "objectPosition": "-200px 0px"}), FREEZE_SKIP),
    "gate_canvasShiftedOutside": (_gate(tag="CANVAS", cs={"overflowX": "visible", "overflowY": "visible",
                                                          "objectPosition": "-200px 0px"}), FREEZE_SKIP),
    "gate_canvasShiftedClipped": ({"fg": _fg(cs={"objectPosition": "-50px 0px"})}, FREEZE_SKIP),
    "gate_svgStroke": (_gate(tag="svg"), FREEZE_SKIP),
    "gate_hiddenOriginVisiblePseudo": (_gate(cs={"visibility": "hidden"}, pseudo={"::before": '"x"'}), FREEZE_SKIP),
    "gate_displayContentsText": (_gate(cs={"display": "contents"}, text=True), FREEZE_SKIP),
    "gate_displayContentsPseudo": (_gate(cs={"display": "contents"}, pseudo={"::after": '"x"'}), FREEZE_SKIP),
    "gate_confinedNonIntersecting": (_gate(), FREEZE_ADMIT),
    "gate_suppressedTextIgnored": (_gate(text=True, hostGroup={"display": "none"}), FREEZE_ADMIT),
    "gate_opacityZeroTextIgnored": (_gate(text=True, hostGroup={"opacity": "0"}), FREEZE_ADMIT),
    "gate_scriptTextIgnored": ({"fg": _fg(tag="SCRIPT", rect=[0, 0, 0, 0], text=True)}, FREEZE_ADMIT),
    "gate_hiddenShadowIgnored": (_gate(cs={"boxShadow": OUT_OF_PROFILE["boxShadow"], "visibility": "hidden"}), FREEZE_ADMIT),
}
for _prop in CHAIN_PROPERTIES:
    FREEZE_ROWS[f"chain_{_prop}"] = ({"layerCs": {_prop: OUT_OF_PROFILE[_prop], **CHAIN_COMPANIONS.get(_prop, {})}}, FREEZE_SKIP)
for _prop in BITMAP_PROPERTIES:
    FREEZE_ROWS[f"video_{_prop}"] = ({"videoCs": {_prop: OUT_OF_PROFILE[_prop]}}, FREEZE_SKIP)
    FREEZE_ROWS[f"fgCanvas_{_prop}"] = ({"fg": _fg(cs={_prop: OUT_OF_PROFILE[_prop]})}, FREEZE_SKIP)
for _prop in GATE_PROPERTIES:
    FREEZE_ROWS[f"gate_{_prop}"] = (_gate(cs={_prop: OUT_OF_PROFILE[_prop]}), FREEZE_SKIP)


# Deck stub DOMs (`node_f3_r12_decks.py`): the live slide shown before each movie slide's outgoing Dissolve, built from
# the export JSON the way `NB.addNode`, `xB.initVideo` and `renderMovie` do (computed style = inline style + UA).
FREEZE_DECKS_JS = r"""
let TB=0;
class P{constructor(si){this.sceneIndex=si}%METHODS%}
globalThis.DOMMatrix=class{constructor(s){const m=/matrix(3d)?\(([^)]*)\)/.exec(s);const v=m[2].split(',').map(Number);this.is2D=!m[1];this.a=v[0];this.b=v[1];this.c=m[1]?v[4]:v[2];this.d=m[1]?v[5]:v[3]}};
const UA={display:'block',contain:'none',contentVisibility:'visible',isolation:'auto',perspective:'none',backfaceVisibility:'visible',willChange:'auto',zoom:'1',imageRendering:'auto',opacity:'1',transform:'none',filter:'none',mixBlendMode:'normal',clipPath:'none',maskImage:'none',zIndex:'auto',overflowX:'visible',overflowY:'visible',position:'static',
 borderTopLeftRadius:'0px',borderTopRightRadius:'0px',borderBottomLeftRadius:'0px',borderBottomRightRadius:'0px',objectPosition:'50% 50%',paddingTop:'0px',paddingLeft:'0px',paddingRight:'0px',paddingBottom:'0px',
 borderTopStyle:'none',borderRightStyle:'none',borderBottomStyle:'none',borderLeftStyle:'none',objectFit:'fill',backgroundColor:'rgba(0, 0, 0, 0)',backgroundImage:'none',boxShadow:'none',outlineStyle:'none',
 transformStyle:'flat',borderImageSource:'none',webkitBoxReflect:'none',content:'normal',columnRuleStyle:'none',scale:'none',rotate:'none',translate:'none',offsetPath:'none',clip:'auto',backdropFilter:'none',objectViewBox:'none',visibility:'visible'};
const mul=(A,B)=>[A[0]*B[0]+A[2]*B[1],A[1]*B[0]+A[3]*B[1],A[0]*B[2]+A[2]*B[3],A[1]*B[2]+A[3]*B[3],A[0]*B[4]+A[2]*B[5]+A[4],A[1]*B[4]+A[3]*B[5]+A[5]];
function run(C){
  const all=[];let vids=[];
  const mk=(tag,id,cs,w,h,parent,M,org)=>{const e={tagName:tag,id,nodeType:1,_cs:Object.assign({},UA,tag==='VIDEO'?{objectFit:'contain',overflowX:'clip',overflowY:'clip'}:{},tag==='CANVAS'?{overflowX:'clip',overflowY:'clip'}:{},cs),childNodes:[],children:[],style:{},parentElement:parent||null,_w:w,_h:h,_M:M||[1,0,0,1,0,0],_o:org||[w/2,h/2],
    contains(x){for(let p=x;p;p=p.parentElement)if(p===this)return true;return false},getElementsByTagName(){const o=[];const w=n=>{n.children.forEach(c=>{o.push(c);w(c)})};w(this);return o},
    checkVisibility(op){for(let p=this;p;p=p.parentElement){if(p._cs.display==='none')return false;if(op&&op.opacityProperty&&+p._cs.opacity===0)return false}if(op&&op.visibilityProperty&&this._cs.visibility!=='visible')return false;return true},
    appendChild(c){if(c.children&&!c.tagName){c.children.forEach(x=>{x.parentElement=this;this.children.push(x)});c.children=[]}else{c.parentElement=this;this.children.push(c)}},
    getBoundingClientRect(){let A=[1,0,0,1,0,0];const ch=[];for(let p=this;p;p=p.parentElement)ch.unshift(p);for(const p of ch){const o=p._o;A=mul(A,[1,0,0,1,o[0],o[1]]);A=mul(A,p._M);A=mul(A,[1,0,0,1,-o[0],-o[1]])}
      const pts=[[0,0],[this._w,0],[0,this._h],[this._w,this._h]].map(([x,y])=>[A[0]*x+A[2]*y+A[4],A[1]*x+A[3]*y+A[5]]);const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
      const l=Math.min(...xs),t=Math.min(...ys),r=Math.max(...xs),b=Math.max(...ys);return {left:l,top:t,right:r,bottom:b,width:r-l,height:b-t}}};all.push(e);if(parent)parent.children.push(e);return e};
  const html=mk('HTML','html',{},1920,1080,null);const body=mk('BODY','body',{backgroundColor:'rgb(0, 0, 0)',overflowX:'hidden',overflowY:'hidden'},1920,0,html);
  const area=mk('DIV','stageArea',{position:'absolute',overflowX:'hidden',overflowY:'hidden',visibility:'hidden'},1920,1080,body);
  const stage=mk('DIV','stage',{position:'absolute',transform:'matrix(1, 0, 0, 1, 0, 0)',transformStyle:'preserve-3d',visibility:'hidden'},1920,1080,area);
  const T=C.tree;const root=mk('DIV','layer1',{position:'absolute',transform:'matrix(1, 0, 0, 1, 0, 0)'},T.initialState.width,T.initialState.height,stage);let id=2;
  const builtSet=new Set(C.built);
  function add(parent,g,builtAnc,movieObj){const st=g.initialState,w=st.width,h=st.height,a=st.affineTransform,ax=st.anchorPoint.pointX,ay=st.anchorPoint.pointY;
    const ox=st.position.pointX-ax*w,oy=st.position.pointY-ay*h;const hidden=st.hidden&&!builtAnc&&!builtSet.has(g.objectID);
    const cs={position:'absolute',transform:`matrix(${a[0]}, ${a[1]}, ${a[2]}, ${a[3]}, ${a[4]+ox}, ${a[5]+oy})`,opacity:String(st.opacity),visibility:hidden?'hidden':'visible'};
    if(st.masksToBounds){cs.overflowX='hidden';cs.overflowY='hidden'}
    if(st.backgroundColor){const c=st.backgroundColor;cs.backgroundColor=`rgba(${c.map((v,i)=>i<3?Math.round(255*v):v).join(', ')})`}
    const Q=mk('DIV','layer'+(id++),cs,w,h,parent,[a[0],a[1],a[2],a[3],a[4]+ox,a[5]+oy],[ax*w,ay*h]);
    const mo=movieObj||(g.objectID&&C.movies[g.objectID]?g.objectID:null);
    if(g.texture){if(mo&&(!g.layers||!g.layers.length)&&!C._placed[mo]){C._placed[mo]=1;const nat=C.movies[mo];
        Q._cs.visibility='hidden';mk('CANVAS',g.texture.slice(0,8)+'-poster',{position:'absolute',transform:'matrix(1, 0, 0, 1, 0, 0)',visibility:'hidden'},w,h,Q);
        C._defer.push(()=>{const md=mk('DIV','movieDiv-'+mo.slice(0,8),{position:'absolute',transform:cs.transform,opacity:'1',visibility:'visible'},w,h,parent,Q._M,Q._o);
          let in_=md;for(const nm of ['opacity','position','transform-rotation-z','transform-scale-x','transform-scale-y','bounds','contents'])in_=mk('DIV',md.id+'-'+nm,{position:'absolute',transformStyle:'preserve-3d'},w,h,in_);
          in_=mk('DIV',md.id+'-inner',{position:'absolute',transform:'matrix(1, 0, 0, 1, 0, 0)'},w,h,in_);
          const v=mk('VIDEO','vid-'+mo.slice(0,8),{position:'absolute',visibility:'visible'},w,h,in_);v.readyState=4;v.videoWidth=nat[0];v.videoHeight=nat[1];vids.push(v)})}
      else mk('CANVAS',g.texture.slice(0,8),{position:'absolute',transform:'matrix(1, 0, 0, 1, 0, 0)'},w,h,Q)}
    for(const l of g.layers||[])add(Q,l,builtAnc||builtSet.has(g.objectID),mo&&(g.layers||[]).length===1?mo:(movieObj||null))}
  C._placed={};C._defer=[];for(const l of T.layers||[])add(root,l,false,null);C._defer.forEach(f=>f());
  const ids={};all.forEach(e=>ids[e.id]=e);const draws=[];
  const pre=(n,o=[])=>{o.push(n);n.children.forEach(c=>pre(c,o));return o};const tree=pre(html);globalThis.document={documentElement:html,body,getElementById:x=>x==='stage'?stage:(ids[x]||null),querySelectorAll:()=>tree.filter(e=>e.tagName==='VIDEO'),getElementsByTagName:()=>tree,
    createDocumentFragment:()=>({children:[],appendChild(c){this.children.push(c)}}),
    createElement:t=>t==='canvas'?{style:{},getContext(){const ctx={globalAlpha:1,drawImage:(s,...a)=>{if(s.tagName!=='VIDEO')draws.push([s.id,+ctx.globalAlpha.toFixed(4),...a.map(x=>Math.round(x))])},
      getImageData:(x,y,w,h)=>{const d=new Uint8ClampedArray(w*h*4).fill(255);return {data:d}},putImageData(){}};return ctx}}:{style:{},children:[],appendChild(c){this.children.push(c)}}};
  globalThis.getComputedStyle=(e,p)=>p?{content:'none'}:e._cs;globalThis.innerWidth=1920;globalThis.window=globalThis;globalThis.innerHeight=1080;globalThis.VideoFrame=class{constructor(x){this.colorSpace={primaries:'bt709',transfer:'bt709',matrix:'bt709',fullRange:false}}close(){}};
  const U={script:{slideWidth:1920,slideHeight:1080,events:[{effects:[C.effect]}]},playbackController:{kpfEvent:{baseLayer:{layerId:1}}}};globalThis.UC=U;
  P.prototype.__obedFreezeTake(U,0);
  const F=U.__obedFrozen;return {videos:vids.length,holders:F?F.holders.map(h=>[h.style.left,h.style.top,h.style.width,h.style.height].map(x=>Math.round(parseFloat(x)))):[],draws};
}
const CASES=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const out={};for(const C of CASES)out[C.label]=run(C);console.log(JSON.stringify(out));
"""

# §8's deck table: movies, holders (slide px, rounded) and redrawn foreground (id, alpha, rect in video px, rounded).
_DSK7_REDRAWS = [["84D61F77", 1, 32, 1, 1030, 260], ["7262F462", 1, 1262, 9, 16, 1066], ["0A370629", 1, 12, -3, 1143, 262],
                 ["183D386F", 1, 1227, -7, 1292, 1094], ["054DC953", 1, 1240, 5, 16, 1070], ["ED5928A0", 1, 1272, -3, 840, 262]]
_P2_SLIDE2 = {"videos": 1, "holders": [[105, 794, 960, 270]], "draws": [["3F22E494", 0.2947, 1368, -242, 706, 626]]}
FREEZE_DECK_TABLE = {
    "P2 slide 2 event 3": _P2_SLIDE2,
    "P2 slide 4 event 1": {"videos": 1, "holders": [[323, 708, 1274, 358]], "draws": []},
    "DSK slide 2 event 3": _P2_SLIDE2,
    "DSK slide 3 event 1": {"videos": 2, "holders": [[194, 796, 960, 270], [1153, 795, 484, 272]], "draws": []},
    "DSK slide 5 event 1": {"videos": 1, "holders": [[323, 697, 1274, 358]], "draws": []},
    "DSK slide 7 event 1": {"videos": 2, "holders": [[358, 800, 476, 267], [39, 799, 320, 270]], "draws": _DSK7_REDRAWS},
}


def _render_movies(node, out: dict) -> dict:
    if isinstance(node, dict):
        if node.get("name") == "renderMovie" and node.get("objectID"):
            out[node["objectID"]] = (node.get("movie") or {}).get("asset")
        for value in node.values():
            _render_movies(value, out)
    elif isinstance(node, list):
        for value in node:
            _render_movies(value, out)
    return out


def _freeze_deck_cases() -> list[dict]:
    """The scene shown before each movie slide's outgoing Dissolve: the previous event's tree, its builds applied."""
    cases = []
    for deck, root in FREEZE_DECKS.items():
        if not root.is_dir():
            pytest.skip("deck exports under output/fixtures not available")
        for index, sid in enumerate(json.loads((root / "header.json").read_text())["slideList"]):
            slide = json.loads((root / sid / f"{sid}.json").read_text())
            movies = _render_movies(slide, {})
            for k, event in enumerate(slide["events"]):
                effect = (event.get("effects") or [None])[0]
                if not movies or not effect or effect.get("type") != "transition" or effect.get("name") != "apple:dissolve":
                    continue
                previous = slide["events"][max(0, k - 1)]
                built = sorted(e["objectID"] for e in previous.get("effects") or [] if e.get("type") == "buildIn" and e.get("objectID"))
                sizes = {o: slide["assets"].get(asset) or {} for o, asset in movies.items()}
                cases.append({"label": f"{deck} slide {index + 1} event {k}", "tree": previous["baseLayer"], "built": built,
                              "movies": {o: [s.get("width"), s.get("height")] for o, s in sizes.items()}, "effect": effect})
    return cases


def _run_node_file(node: str, tmp_path: Path, name: str, script: str, data) -> dict:
    (tmp_path / f"{name}.js").write_text(script)
    (tmp_path / f"{name}.json").write_text(json.dumps(data))
    paths = [str(tmp_path / f"{name}.js"), str(tmp_path / f"{name}.json")]
    result = subprocess.run([node, *paths], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


DISSOLVE_NODE_CASES = ("construction", "freeze_stub", "freeze_decks")


@pytest.mark.parametrize("case", DISSOLVE_NODE_CASES)
@pytest.mark.parametrize("sha", REAL_PLAYERS)
def test_dissolve_real_patched_methods_on_node(tmp_path, sha, case):
    node, player = _node(), _real_player(sha)
    patched = live_runtime.patch_player(player).decode()
    methods = _cut(patched, "__obedShape(C){", "renderEffects(A){")
    assert live_runtime._MM_OPACITY_REPLACEMENTS[DISSOLVE][0][1] == b"return B}" + methods.encode() + b"renderEffects(A){"
    if case == "construction":
        # §8: all 133 transitions on disk (the committed fixtures' 16 among them) give 46 Dissolves copied with two
        # rules on exactly the ids `VB` then allocates pre-order (root, container, incoming, outgoing = TB .. TB+3),
        # 8 cuts and 79 stock, with no export mutated.
        if not OUTPUT_FIXTURES.is_dir():
            pytest.skip("export fixtures under output/ not available")
        transitions = _transitions(OUTPUT_FIXTURES, FIXTURE_ROOT)
        assert len(_transitions(FIXTURE_ROOT)) == 16 and len(transitions) == 133
        classes = _cut(patched, "let TB=0;class yB{", "class bB{")
        script = DISSOLVE_PLAYER_SCOPE + classes + DISSOLVE_CONSTRUCTION_JS.replace("%METHODS%", methods)
        # Near-misses and failures mutate copies of the first full-shape Dissolve (P2 2->3) and cut in this order.
        failures = {name: options for name, (options, _) in DISSOLVE_CONSTRUCTION_FAILURES.items()}
        data = {"transitions": transitions, "nearMisses": DISSOLVE_NEAR_MISSES, "failures": failures}
        result = _run_node_file(node, tmp_path, case, script, data)
        assert result["summary"] == {"dissolve": 46, "cut": 8, "stock": 79, "mutated": 0, "badCopy": 0, "badIds": 0, "stockTouched": 0}
        assert result["near"] == {name: DISSOLVE_NEAR_MISS_ENGAGED.get(name, "stock") for name in DISSOLVE_NEAR_MISSES}
        misses = [effect for name, (effect, _, _) in DISSOLVE_NEAR_MISSES.items() if name not in DISSOLVE_NEAR_MISS_ENGAGED]
        assert (misses.count("apple:dissolve"), misses.count("none")) == (21, 10)
        assert result["failures"] == {name: expected for name, (_, expected) in DISSOLVE_CONSTRUCTION_FAILURES.items()}
    elif case == "freeze_stub":
        effect = json.loads(FREEZE_EFFECT.read_text())["events"][1]["effects"][0]
        script = FREEZE_STUB_JS.replace("%METHODS%", methods).replace("%EFF%", json.dumps(effect))
        result = _run_node_file(node, tmp_path, case, script, {name: options for name, (options, _) in FREEZE_ROWS.items()})
        assert len(FREEZE_ROWS) == 134
        for name, (options, expected) in FREEZE_ROWS.items():
            row = result[name]
            assert {k: row[k] for k in expected} == expected, name
            # The video is only read; the cost is published on every path; the slot is always consumed; every
            # VideoFrame is closed; a gate row is refused before any candidate is read.
            assert row["touched"] == [], name
            assert row["ms"] == row["windowMs"] == options.get("clock", 1), name
            assert row["slotCleared"] and row["vfOpened"] == row["vfClosed"], name
            if name.startswith("gate_") and expected == FREEZE_SKIP:
                assert row["vfOpened"] == 0, name
    else:
        cases = _freeze_deck_cases()
        result = _run_node_file(node, tmp_path, case, FREEZE_DECKS_JS.replace("%METHODS%", methods), cases)
        assert result == FREEZE_DECK_TABLE

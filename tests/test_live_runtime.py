from __future__ import annotations

import collections
import hashlib
import itertools
import json
import math
import re
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
    player = b"before;" + live_runtime._ANCHOR + b";" + live_runtime._CONTINUITY_TAKE_ANCHOR + b";after"
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)
    patched = live_runtime.patch_player(player, mm_opacity=False)
    assert patched.startswith(b"before;UC=new Eg,")
    assert b",UC.displayManager.showWaitingIndicator();" in patched
    assert patched.endswith(b";after")
    assert patched.count(live_runtime._CONTINUITY_TAKE_REPLACEMENT) == 1


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
# Stage T's texture-repair fixture is a real deck added for texture repair only; the census corpora below predate it.
TEXTURE_FIXTURE = fixture("alpha-dsk-textures")
REAL_PLAYER = fixture("p2-binary") / "html-player" / "assets" / "player" / "main.js"
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
EFFECT_1_TO_2 = FIXTURE_ROOT / "effect_1_to_2.json"
SOURCE_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
SLOT4_ALPHA = 0.29468628764152527
EB_EFFECTS = {"apple:magic-move-implied-motion-path", "apple:ca-text-shimmer", "apple:ca-text-sparkle"}


def _hook_only(player: bytes) -> bytes:
    """The observation-hook output, built independently of patch_player."""
    return player.replace(
        live_runtime._ANCHOR,
        b"UC=new Eg," + live_runtime._INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )


def _base_live_output(player: bytes) -> bytes:
    return live_runtime._apply_continuity_take(_hook_only(player))


def _synthetic_player(anchors: list[bytes] | None = None) -> bytes:
    anchors = [before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS] if anchors is None else anchors
    return b"before;" + live_runtime._ANCHOR + b";" + b";".join(anchors) + b";after"


def _pin(monkeypatch, player: bytes) -> None:
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)


def test_mm_opacity_off_is_the_hook_plus_the_continuity_take(monkeypatch):
    player = _synthetic_player()
    _pin(monkeypatch, player)
    off = live_runtime.patch_player(player, mm_opacity=False)
    assert hashlib.sha256(off).hexdigest() == hashlib.sha256(_base_live_output(player)).hexdigest()
    on = live_runtime.patch_player(player)
    assert on != off
    # Undoing exactly the replacements on the default (on) output gives the off output back.
    reverted = on
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert on.count(after) == 1
        reverted = reverted.replace(after, before)
    assert hashlib.sha256(live_runtime._apply_continuity_take(reverted)).hexdigest() == hashlib.sha256(off).hexdigest()


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


@pytest.mark.parametrize("mm_opacity", [True, False])
def test_continuity_take_runs_before_teardown_with_mm_opacity_on_and_off(mm_opacity):
    method = (
        live_runtime._MM_OPACITY_REPLACEMENTS[-1][1]
        if mm_opacity
        else live_runtime._CONTINUITY_TAKE_REPLACEMENT
    ).decode() + "0){}}"
    script = f"""
const events = [];
const window = {{__OBED_MM_FEED__: {{take(controller, scene) {{
  events.push(['take', controller.name, scene]);
}}}}}};
const PB = {{prototype: {{__obedFreezeTake(controller, scene) {{ events.push(['freeze', controller.name, scene]); }}}}}};
class Player {{ {method} }}
const controller = {{name: 'player', displayScene(scene) {{ events.push(['display', scene]); }}}};
Player.prototype.jumpToScene_partFour.call(controller, 7, true);
Player.prototype.jumpToScene_partFour.call(controller, 8, false);
window.__OBED_MM_FEED__.take = function() {{ events.push(['throw']); throw new Error('take'); }};
Player.prototype.jumpToScene_partFour.call(controller, 9, true);
console.log(JSON.stringify(events));
"""
    result = json.loads(subprocess.run([_node(), "-e", script], check=True, text=True, capture_output=True).stdout)
    expected = [["take", "player", 7]]
    if mm_opacity:
        expected.append(["freeze", "player", 7])
    expected.extend([["display", 7], ["display", 8], ["throw"]])
    if mm_opacity:
        expected.append(["freeze", "player", 9])
    expected.append(["display", 9])
    assert result == expected


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
    message = "continuity-take anchor" if index == len(live_runtime._MM_OPACITY_REPLACEMENTS) - 1 else "Magic Move opacity anchor"
    with pytest.raises(live_runtime.LiveRuntimeUnsupported, match=message):
        MM_PATCHERS[patcher](player)
    if index == len(live_runtime._MM_OPACITY_REPLACEMENTS) - 1:
        with pytest.raises(live_runtime.LiveRuntimeUnsupported, match="continuity-take anchor"):
            live_runtime.patch_player(player, mm_opacity=False)
    else:
        assert live_runtime.patch_player(player, mm_opacity=False) == _base_live_output(player)


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
    assert live_runtime.patch_player(player, mm_opacity=False) == _base_live_output(player)


# sha256 of patch_player(real, mm_opacity=...) and patch_rendering(real), per stock player.
# False includes the Stage B continuity-take callback. True and rendering include it with the dissolve replacements
# D1-D4 = R9-R12 at plan rev 17 (keynote_live_dissolve_crossfade.plan.md); rev 13's D1 gave 409a0395... / 53ee23db... (old)
# and 5dd3997e... / b366bd91... (new); rev 12's D1 gave bfeb9377... / a211b1c3... (old)
# and 6c941ac1... / 50231d3c... (new); rev 9's D1 gave 49d56adc... / 117fd39d... (old)
# and 7a5e315b... / 52d7edb5... (new); were 574274e8... / fd811938... (old) and 330ef72c... / 33fcdcd2... (new) with R1-R8,
# and old True 21476f78... with R1-R5. New False: recorded when the new player was admitted.
REAL_PATCHED_SHA256 = {
    OLD_PLAYER_SHA256: {
        True: "dfcf5e9b5af150715ba0fb8addab325deeb161e937ae0cca69b4934678e214e2",
        False: "aa7d69241c2c4b7b5adbdbca19af36f2ec73bf9fad48eb2c3f6a2aeda66f2243",
    },
    NEW_PLAYER_SHA256: {
        True: "ad0a7ca3c33685fe8f78e5223bfde0fb79ac66d44d2e49f22040a7ce16e949d7",
        False: "322d7419c4c3814e67b169ae69c291f671c16e1807ec21760b5160514976ceee",
    },
}
REAL_RENDERING_SHA256 = {
    OLD_PLAYER_SHA256: "354212ac25f215b3fa8057ea6bbb27cd52c5e8f769204a3d6bd5ffa4970beba4",
    NEW_PLAYER_SHA256: "67ea6cad3c6d4a06acc0340aee9eae35d2d4713bf4d211f807ad7fb948cd243b",
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
    # The qualified colour tuple is spliced in once; identity tone (decision 10) adds no tone table and no pixel writeback.
    assert patched.count(b"Q=" + live_runtime._FREEZE_QUALIFIED_TUPLES + b",") == 1
    assert b"__obedLut" not in patched and patched.count(b"putImageData") == player.count(b"putImageData")
    off = live_runtime.patch_player(player, mm_opacity=False)
    for marker in (b"obedMix", b"__obedHandbackTextures", b"obedDissolve", b"__obedFreeze", b"__obedShape"):
        assert marker not in off
    # Shadow-DOM invariant (§3.2, r9 2): the take refuses open shadow roots but cannot see closed ones, so nothing on a
    # supported page may create an author shadow root: not the stock or patched player, the export pages, or the host.
    rendering = live_runtime.patch_rendering(player)
    players = {"stock": SHADOW_PINS["player"], "off": SHADOW_PINS["player"],
               "on": sorted(SHADOW_PINS["player"] + SHADOW_PINS["patch"]), "rendering": sorted(SHADOW_PINS["player"] + SHADOW_PINS["patch"])}
    assert {name: _shadow_occurrences(data) for name, data in zip(players, (player, off, patched, rendering))} == players
    pages = sorted(OUTPUT_FIXTURES.rglob("index.html"))
    p2_page = FREEZE_DECKS["P2"].parent / "index.html"
    assert {root.parent / "index.html" for root in FREEZE_DECKS.values()} <= set(pages)
    assert {str(path): _shadow_occurrences(path.read_bytes()) for path in pages} == {str(path): [] for path in pages}
    host = Path(live_runtime.__file__).parent.parent
    assert set(SHADOW_PINS) - {"player", "patch"} <= set(SHADOW_HOST_FILES)
    assert {name: _shadow_occurrences((host / name).read_bytes()) for name in SHADOW_HOST_FILES} == {
        name: SHADOW_PINS.get(name, []) for name in SHADOW_HOST_FILES}
    # Planted controls: each spelling of a creation API, spliced into the stock player and into the P2 export page, is
    # an occurrence outside the pins.
    for planted, flagged in SHADOW_DOM_PLANTED.items():
        assert _shadow_extra(player + planted, SHADOW_PINS["player"]) == flagged, planted
        assert _shadow_extra(p2_page.read_bytes() + planted, []) == flagged, planted


SHADOW_TOKEN = re.compile(r"(?<![\w$-])[\w$-]*(?:shadow|customelements)[\w$-]*", re.IGNORECASE)
SHADOW_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
SHADOW_JOIN = re.compile(r"(['\"`])\s*\+\s*(['\"`])")
SHADOW_CONTEXT = 12
# Every `shadow`/`customelements` token on the supported pages, pinned per source with its normalised context:
# `player` is each stock player (and `off`), `patch` what `on`/`rendering` add (the take's CSS reads and its single
# `!n.shadowRoot&&(` refusal), the rest are host files under `src/`. Regenerate only after reading every new occurrence.
# The host files are the ones whose JS reaches a supported page: the player patch and hook (`live_runtime.py`), the live
# output page and its scripts (`live_host.py`, `live_continuity_js.py`, `live_gl_replay_js.py`) and the Build Preview page
# (`html_preview.py`). Other modules never reach a page, so prose there ("shadow") is not scanned.
SHADOW_HOST_FILES = ("obed_edom/live_runtime.py", "obed_edom/live_host.py", "obed_edom/live_continuity_js.py",
                     "obed_edom/live_gl_replay_js.py", "obed_edom/html_preview.py")
SHADOW_PINS = {
    'player': [
        ('-moz-box-shadow', ' 40px black;-moz-box-shadow:0px 0px 40p'),
        ('-moz-box-shadow', '(0,0,0,0.5);-moz-box-shadow:0px 2px 4px'),
        ('-ms-box-shadow', '(0,0,0,0.5);-ms-box-shadow:0px 2px 4px'),
        ('-webkit-box-shadow', ' 40px black;-webkit-box-shadow:0px 0px 40p'),
        ('-webkit-box-shadow', '5,255,0.68);-webkit-box-shadow:0px 2px 4px'),
        ('ShadowPosition', '],Normal:[],ShadowPosition:[],ShadowTe'),
        ('ShadowTexCoord', 'Position:[],ShadowTexCoord:[],Previous'),
        ('box-shadow', 'height:40px;box-shadow:0px 0px 40p'),
        ('shadow', '(){return B.shadow}}),Object.d'),
        ('shadow', '(A=!0),(0,C.shadow)(this,"isSy'),
        ('shadow', ')&&(Q=A)},B.shadow=o,B.string3'),
        ('shadow', ';return(0,C.shadow)(this,"_com'),
        ('shadow', ';return(0,C.shadow)(this,"_loa'),
        ('shadow', ';return(0,C.shadow)(this,"isFo'),
        ('shadow', ';return(0,Q.shadow)(this,"_isS'),
        ('shadow', ';return(0,Q.shadow)(this,"_key'),
        ('shadow', ';return(0,Q.shadow)(this,"_key'),
        ('shadow', ';return(0,e.shadow)(this,"rawD'),
        ('shadow', 'Property(A,"shadow",{enumerabl'),
        ('shadow', 'es)(A),(0,Q.shadow)(this,"_col'),
        ('shadow', 'urn(0,_util.shadow)(this,"_set'),
        ('shadow', 'urn(0,_util.shadow)(this,"anno'),
        ('shadow', 'urn(0,_util.shadow)(this,"isPu'),
        ('shadow', 'urn(0,_util.shadow)(this,"isPu'),
        ('shadow', 'urn(0,_util.shadow)(this,"load'),
        ('shadow', '{return(0,Q.shadow)(this,"dire'),
        ('shadow', '{return(0,Q.shadow)(this,"hcmF'),
        ('shadow', '{return(0,Q.shadow)(this,"imag'),
        ('shadow', '{return(0,Q.shadow)(this,"supp'),
        ('shadow', '{return(0,Q.shadow)(this,"supp'),
        ('shadow', '{return(0,e.shadow)(this,"_def'),
        ('shadow', '}return(0,C.shadow)(this,"isFo'),
    ],
    'patch': [
        ('boxShadow', '&"none"===w.boxShadow&&"none"===w'),
        ('boxShadow', 'n"none"===w.boxShadow&&"none"===w'),
        ('boxShadow', '|"none"!==z.boxShadow||bd(z)||"no'),
        ('shadowRoot', 'n){return!n.shadowRoot&&(pc(n)||!G'),
    ],
    'obed_edom/live_runtime.py': [
        ('boxShadow', '&"none"===w.boxShadow&&"none"===w'),
        ('boxShadow', '\'"none"!==z.boxShadow||bd(z)||"no'),
        ('boxShadow', 'n"none"===w.boxShadow\'\n    b\'&&"n'),
        ('shadow', 'and no open shadow root on the'),
        ('shadow', 'e no author shadow roots (a ch'),
        ('shadowRoot', 'n){return!n.shadowRoot&&(pc(n)||!G'),
    ],
}
SHADOW_DOM_PLANTED = {
    b"host.attachShadow({mode:'closed'})": {"attachShadow"},
    b"host['attach'+'Shadow']({mode:'closed'})": {"attachShadow"},
    b"var a='attach';host[a+'Shadow']({mode:'closed'})": {"Shadow"},
    b"host['attach\\u0053hadow']({mode:'closed'})": {"attachShadow"},
    b"host[\"attach\\x53hadow\"]({mode:'closed'})": {"attachShadow"},
    b"h['attach'+('boxShadow').slice(3)]({mode:'closed'})": {"boxShadow"},
    b"h['attach'+('!n.shadowRoot&&(').slice(3,9).replace('s','S')]({mode:'closed'})": {"shadowRoot"},
    b'<template shadowrootmode="open"></template>': {"shadowrootmode"},
    b'<template SHADOWROOTMODE="closed"></template>': {"SHADOWROOTMODE"},
    b'<template shadowroot="open"></template>': {"shadowroot"},
    b"customElements.define('x-a',A)": {"customElements"},
    b"window['custom'+'Elements'].define('x-a',A)": {"customElements"},
}


def _shadow_occurrences(data: bytes) -> list[tuple[str, str]]:
    """Every token containing `shadow` or `customelements` in any letter case (HTML attribute names are case-insensitive),
    after decoding JS escapes and joining adjacent string literals, with its surrounding context. A static tripwire, not a
    proof: it catches any new or moved spelling, including one assembled from pinned words, but a name built without any
    such token (character codes, base64, arithmetic) is outside it, which is acceptable because the scanned sources are
    pinned players, our own exports and our own host."""
    text = data.decode("latin-1")
    text = SHADOW_JOIN.sub("", SHADOW_ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2) or m.group(3), 16)), text))
    return sorted((m.group(), text[max(0, m.start() - SHADOW_CONTEXT) : m.end() + SHADOW_CONTEXT]) for m in SHADOW_TOKEN.finditer(text))


def _shadow_extra(data: bytes, pins: list[tuple[str, str]]) -> set[str]:
    return {token for token, _ in (collections.Counter(_shadow_occurrences(data)) - collections.Counter(pins)).elements()}


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


def _corpus_headers(root: Path, pattern: str = "assets/header.json") -> list[Path]:
    return sorted(header for header in root.rglob(pattern) if TEXTURE_FIXTURE not in header.parents)


def test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_in_committed_fixtures():
    effect = json.loads(EFFECT_1_TO_2.read_text())
    rows = _mirror(effect)
    for row in rows:
        assert [old == new for old, new in row] == [True, True, True, True, False]
        assert row[4] == (1, SLOT4_ALPHA)
    paths = sorted(path for path in FIXTURE_ROOT.rglob("*.json") if not {"alpha_dsk_repaired", "alpha_dsk_repaired_full"} & set(path.parts))
    stats, changed = _census(paths)
    assert stats["one_to_two"] >= 1 and stats["effects"] > stats["one_to_two"]
    assert changed == {(True, 4)}


@pytest.mark.skipif(not MAIN_OUTPUT.is_dir(), reason="main checkout output/ not available")
def test_mm_opacity_census_mirror_changes_only_p2_1_to_2_slot_4_across_real_exports():
    roots = sorted(header.parent.parent for header in _corpus_headers(MAIN_OUTPUT))
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
# `_freeze_deck_cases()` over FREEZE_DECKS, trimmed to the fields the deck stub reads. Regenerate with
# `json.dumps(_freeze_deck_cases(), separators=(",", ":"))`; the census case checks it still matches the exports.
FREEZE_DECK_FIXTURE = FIXTURE_ROOT / "dissolve_freeze_decks.json"
# Every on-disk `none` cut's outgoing animation (all 8 are identical; the census case checks it).
CUT_OUTGOING = {"additive": False, "timeOffset": 0, "beginTime": 0, "from": {"scalar": False}, "repeatCount": 0, "fillMode": "both",
                "duration": 0.001, "autoreverses": False, "property": "hidden", "to": {"scalar": True}, "removedOnCompletion": False}
CUT_EFFECT = {"beginTime": 0, "effects": [], "duration": 0.001, "type": "transition", "attributes": {"direction": 0}, "name": "none",
              "objectID": "0"}

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
const mirrors=(a,x)=>JSON.stringify(a)===JSON.stringify(Object.assign({},x,{from:x.to,to:x.from}));
const canon=v=>Array.isArray(v)?'['+v.map(canon).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canon(v[k])).join(',')+'}':JSON.stringify(v);
function expectedCopy(e){const b=JSON.parse(JSON.stringify(e.baseLayer)),i=b.layers[0].layers[0],x=b.layers[0].layers[1].animations[0];
  if(e.name==='none')i.initialState.hidden=true;else i.initialState.opacity=0;i.animations=[Object.assign({},x,{from:x.to,to:x.from})];return b}
const callSites=(()=>{const ev=[];const COPY={copy:1};class VB0{constructor(b,o){ev.push(['VB',b===COPY,o.name,o.type,o.objectID])}}
  (function(C,e){const VB=VB0;%D2%}).call({__obedDissolveLayer(C){ev.push(['layer',C.name]);return COPY}},{name:'apple:dissolve',type:'transition'},'obj');return ev})();
const summary={dissolve:0,cut:0,stock:0,mutated:0,badCopy:0,badIds:0,stockTouched:0};const mirrorControls={};
for(const e of IN.transitions){UC.animationManager.styleSheet=sheet();const b=JSON.stringify(e);const before=TB;const C={type:e.type,name:e.name,baseLayer:e.baseLayer};
  const res=pp.__obedDissolveLayer(C);if(JSON.stringify(e)!==b)summary.mutated++;const rules=UC.animationManager.styleSheet.rules;
  if(res===e.baseLayer){summary.stock++;if(rules.length||C.obedDissolve||TB!==before)summary.stockTouched++;continue}
  const L=res.layers[0].layers,a=L[0].animations[0],x=tree(e)[1].animations[0],cut=e.name==='none';summary[cut?'cut':'dissolve']++;
  const ok=cut?C.obedDissolve==='cut'&&rules.length===0&&L[0].initialState.hidden===true:C.obedDissolve==='dissolve'&&L[0].initialState.opacity===0;
  if(!ok||L[0].animations.length!==1||!mirrors(a,x)||L[1]!==tree(e)[1]||L.length!==2||canon(res)!==canon(expectedCopy(e)))summary.badCopy++;
  if(!mirrorControls[C.obedDissolve])mirrorControls[C.obedDissolve]={mirror:mirrors(a,x),duration:mirrors(Object.assign({},a,{duration:a.duration*100}),x),
    beginTime:mirrors(Object.assign({},a,{beginTime:a.beginTime+0.5}),x),fillMode:mirrors(Object.assign({},a,{fillMode:'forwards'}),x)};
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
  UC.animationManager.styleSheet=sheet(opts);const snap=canon(e);const C={type:e.type,name:e.name,baseLayer:e.baseLayer};const res=pp.__obedDissolveLayer(C);
  near[name]=(res===e.baseLayer&&!C.obedDissolve?'stock':'copied:'+C.obedDissolve)+(canon(e)===snap?'':':inputMutated')}
const failures={};
for(const [name,o] of Object.entries(IN.failures)){UC.animationManager.styleSheet=o.noStyleSheet?undefined:sheet(o);
  const e=pick('apple:dissolve');const snap=canon(e);const before=TB;const C={type:e.type,name:e.name,baseLayer:e.baseLayer};const res=pp.__obedDissolveLayer(C);
  const v=new VB(res,{name:e.name,type:e.type,objectID:e.objectID});const built=[v.layers[0].layerId,v.layers[0].layers[0].layerId,v.layers[0].layers[1].layerId];
  const rules=(UC.animationManager.styleSheet||{rules:[]}).rules;
  failures[name]={inputIntact:canon(e)===snap,stock:res===e.baseLayer,kind:C.obedDissolve||null,skippedIds:v.layerId-before,rules:rules.length,
    rulesTargetBuilt:rules.some(x=>built.some(id=>x.selectorText.split(',').includes('#layer'+id))),incomingOpacity:v.layers[0].layers[0].opacity,
    incomingRules:v.layers[0].layers[0].cssAnimationRules.length}}
console.log(JSON.stringify({summary,mirrorControls,near,failures,callSites}));
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
    "outgoingPath": ("apple:dissolve", [("set", OUTGOING + ["path"], "M0 0 L1 1")], {}),
    "outgoingNestedAnimations": ("apple:dissolve", [("set", OUTGOING + ["animations"], [])], {}),
    "outgoingProperty": ("apple:dissolve", [("set", OUTGOING + ["property"], "transform.scale.x")], {}),
    "outgoingDestination": ("apple:dissolve", [("set", OUTGOING + ["to", "scalar"], 0.5)], {}),
    "extraContainer": ("apple:dissolve", [("push", ["baseLayer", "layers"], ["baseLayer", "layers", 0])], {}),
    "rootTexture": ("apple:dissolve", [("set", ["baseLayer", "texture"], "T")], {}),
    "containerTexture": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "texture"], "T")], {}),
    "rootAnimation": ("apple:dissolve", [("set", ["baseLayer", "animations"], [{"property": "opacity"}])], {}),
    "containerAnimation": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "animations"], [{"property": "opacity"}])], {}),
    "incomingNoTexture": ("apple:dissolve", [("delete", _leaf(0) + ["texture"], None)], {}),
    "outgoingNoTexture": ("apple:dissolve", [("delete", _leaf(1) + ["texture"], None)], {}),
    "incomingSublayers": ("apple:dissolve", [("set", _leaf(0) + ["layers"], [{}])], {}),
    "outgoingSublayers": ("apple:dissolve", [("set", _leaf(1) + ["layers"], [{}])], {}),
    "incomingHidden": ("apple:dissolve", [("set", _leaf(0) + ["initialState", "hidden"], True)], {}),
    "containerHidden": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "initialState", "hidden"], True)], {}),
    "containerOpacity": ("apple:dissolve", [("set", ["baseLayer", "layers", 0, "initialState", "opacity"], 0.5)], {}),
    "incomingObjectID": ("apple:dissolve", [("set", _leaf(0) + ["objectID"], "X")], {}),
    "affineLength": ("apple:dissolve", [("set", _leaf(1) + ["initialState", "affineTransform"], [1, 0, 0, 1, 0])], {}),
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
_STOCK_BUILD = {"inputIntact": True, "stock": True, "kind": None, "rulesTargetBuilt": False, "incomingOpacity": 1, "incomingRules": 0}
DISSOLVE_CONSTRUCTION_FAILURES = {
    "droppedBlend": ({"drop": ["mix-blend-mode"]}, dict(_STOCK_BUILD, skippedIds=4, rules=2)),
    "droppedIsolation": ({"drop": ["isolation"]}, dict(_STOCK_BUILD, skippedIds=4, rules=2)),
    "throwFirstInsert": ({"throwAt": 1}, dict(_STOCK_BUILD, skippedIds=0, rules=0)),
    "throwSecondInsert": ({"throwAt": 2}, dict(_STOCK_BUILD, skippedIds=4, rules=1)),
    "noStyleSheet": ({"noStyleSheet": True}, dict(_STOCK_BUILD, skippedIds=0, rules=0)),
    "success": ({}, {"inputIntact": True, "stock": False, "kind": "dissolve", "skippedIds": 0, "rules": 2, "rulesTargetBuilt": True,
                     "incomingOpacity": 0, "incomingRules": 1}),
}


def _transitions(*roots: Path) -> list[dict]:
    """Every exported transition effect under the export roots (each `header.json`'s slides), in a stable order."""
    effects = []
    for header in sorted(header for root in roots for header in _corpus_headers(root, "header.json")):
        for sid in json.loads(header.read_text())["slideList"]:
            path = header.parent / sid / f"{sid}.json"
            if path.is_file():
                for event in json.loads(path.read_text()).get("events") or []:
                    effects.extend(e for e in event.get("effects") or [] if e.get("type") == "transition")
    return effects


# The freeze stub DOM (`node_f3_r12_test.py`): §1.1's live slide with UA-correct replaced overflow and a zero-height
# static body; the video is a Proxy recording any write or method call other than the three reads D4 may make.
FREEZE_STUB_JS = r"""
let TB=0;const EFF=%EFF%,CUT=%CUT%;
const RAW=new WeakMap(),rawOf=n=>RAW.get(n)||n;
const detach=c=>{const r=rawOf(c),p=r.parentElement;if(p){const l=rawOf(p).children,i=l.indexOf(c);if(i>=0)l.splice(i,1)}r.parentElement=null};
function adopt(p,c,ref){if(c&&!c.tagName&&c.children){c.children.slice().forEach(k=>adopt(p,k,ref));return c}
  detach(c);const l=rawOf(p).children,i=ref?l.indexOf(ref):-1;i>=0?l.splice(i,0,c):l.push(c);rawOf(c).parentElement=p;return c}
const domMethods=me=>({append(...a){a.forEach(c=>adopt(me(),c))},prepend(...a){const f=rawOf(me()).children[0];a.forEach(c=>adopt(me(),c,f))},
  insertBefore(c,r){return adopt(me(),c,r)},replaceChild(n,o){adopt(me(),n,o);detach(o);return o},removeChild(c){detach(c);return c},remove(){detach(me())},
  before(...a){const p=rawOf(me()).parentElement;a.forEach(c=>adopt(p,c,me()))},after(...a){const p=rawOf(me()).parentElement,l=rawOf(p).children,nx=l[l.indexOf(me())+1];a.forEach(c=>adopt(p,c,nx))},
  replaceWith(...a){const p=rawOf(me()).parentElement;a.forEach(c=>adopt(p,c,me()));detach(me())},replaceChildren(...a){rawOf(me()).children.slice().forEach(detach);a.forEach(c=>adopt(me(),c))}});
function node(tag,extra){const n=Object.assign({tagName:tag,style:{},children:[],parentElement:null},extra||{});
  return Object.assign(n,domMethods(()=>n),{appendChild(c){return adopt(n,c)}},extra||{})}

class P{constructor(si){this.sceneIndex=si}%METHODS%}
function sheet(){const rules=[];return {insertRule(t,i){const m=/^(.*)\{(.*):(.*)\}$/.exec(t);rules.splice(i,0,{style:{[m[2]==='isolation'?'isolation':'mixBlendMode']:m[3]}})},get cssRules(){return rules}}}
function callSites(){const ev=[];const PB={prototype:{__obedFreezeTake(U,A){ev.push(['take',U===ctl,A])}}};const STOP={};
  const ctl={displayScene(A){ev.push(['display',A]);throw STOP}};class J{%D4%}
  for(const B of [true,false])try{J.prototype.jumpToScene_partFour.call(ctl,3,B)}catch(e){if(e!==STOP)throw e}
  const d3=function(a,w,C,A){%D3%;
  d3.call({cssRenderer:{draw(a){ev.push(['draw',a.id])}},__obedFreeze(C,A){ev.push(['freeze',C,A])}},{id:'a',removeChild(w){ev.push(['remove',w])}},'w','C','A');return ev}
globalThis.DOMMatrix=class{constructor(s){const m=/matrix(3d)?\(([^)]*)\)/.exec(s);const v=m[2].split(',').map(Number);this.is2D=!m[1];this.a=v[0];this.b=v[1];this.c=m[1]?v[4]:v[2];this.d=m[1]?v[5]:v[3]}};
const BASE={left:'0px',top:'0px',display:'block',opacity:'1',transform:'none',filter:'none',mixBlendMode:'normal',clipPath:'none',maskImage:'none',zIndex:'auto',overflowX:'visible',overflowY:'visible',position:'absolute',
  borderTopLeftRadius:'0px',borderTopRightRadius:'0px',borderBottomLeftRadius:'0px',borderBottomRightRadius:'0px',objectPosition:'50% 50%',paddingTop:'0px',paddingLeft:'0px',paddingRight:'0px',paddingBottom:'0px',
  borderTopStyle:'none',borderRightStyle:'none',borderBottomStyle:'none',borderLeftStyle:'none',objectFit:'contain',backgroundColor:'rgba(0, 0, 0, 0)',backgroundImage:'none',boxShadow:'none',outlineStyle:'none',
  transformStyle:'flat',scale:'none',rotate:'none',translate:'none',offsetPath:'none',clip:'auto',backdropFilter:'none',objectViewBox:'none',contain:'none',contentVisibility:'visible',isolation:'auto',
  perspective:'none',backfaceVisibility:'visible',willChange:'auto',zoom:'1',imageRendering:'auto',visibility:'visible',borderImageSource:'none',webkitBoxReflect:'none',content:'normal',columnRuleStyle:'none'};
const r6=v=>Math.round(v*1e6)/1e6;
const READS=['checkVisibility','getBoundingClientRect','contains','getElementsByTagName'];
const TARGETS=['layer13-opacity','layer13'];
const MEDIA={play(){},pause(){},load(){},fastSeek(){},requestVideoFrameCallback(){},cancelVideoFrameCallback(){},captureStream(){},setAttribute(){},removeAttribute(){},
  addEventListener(){},removeEventListener(){},dispatchEvent(){},remove(){},replaceWith(){},cloneNode(){},appendChild(){},insertBefore(){},removeChild(){},focus(){},blur(){}};
function guard(raw,touched,media){const rec=(t,k)=>{if(typeof k==='string'&&!(k in t)){touched.push(raw.id+' unknown '+k);return function(){touched.push(raw.id+' call '+k)}}
  const v=t[k];return typeof v==='function'&&!READS.includes(k)?function(...a){
    if(!(k==='appendChild'&&TARGETS.includes(raw.id)&&a.length===1&&a[0]&&!a[0].tagName))touched.push(raw.id+' call '+String(k));return v.apply(t,a)}:v};
  const style=new Proxy(Object.assign(raw.style,{setProperty(){},removeProperty(){}}),{set(t,k,v){touched.push(raw.id+' set style.'+String(k));t[k]=v;return true},
    deleteProperty(t,k){touched.push(raw.id+' delete style.'+String(k));return delete t[k]},get:rec});
  return new Proxy(Object.assign(raw,media===false?{}:MEDIA,raw._own),{set(t,k,v){touched.push(raw.id+' set '+String(k));t[k]=v;return true},deleteProperty(t,k){touched.push(raw.id+' delete '+String(k));return delete t[k]},
    get(t,k){return k==='style'?style:rec(t,k)}})}
function guardControl(){const touched=[];const v=guard({id:'ctl',style:{},_own:{},getBoundingClientRect(){}},touched);v.style.opacity='0';v.style.setProperty('opacity','0');v.pause();v.play();v.muted=true;v.remove();
  v.toggleAttribute('hidden',true);v.style.translate;v.getBoundingClientRect();return touched}
function run(o){globalThis.devicePixelRatio=o.dpr||1;
  const touched=[];const all=[];const draws=[];const appends=[];const raws={};const rawList=[];const s=o.scale||1,ox=(o.off||[0,0])[0],oy=(o.off||[0,0])[1];const TR=r=>[ox+r[0]*s,oy+r[1]*s,r[2]*s,r[3]*s];
  const el=(tag,id,cs,rect0,parent,extra)=>{const rect=TR(rect0);const e=Object.assign({tagName:tag,id,nodeType:1,localName:tag.toLowerCase(),namespaceURI:'http://www.w3.org/1999/xhtml',shadowRoot:null,_pseudo:null,_cs:Object.assign({},BASE,tag==='CANVAS'?{objectFit:'fill',overflowX:'clip',overflowY:'clip'}:{},tag==='VIDEO'?{overflowX:'clip',overflowY:'clip'}:{},cs||{}),childNodes:[],children:[],style:{},parentElement:parent||null,
     getBoundingClientRect:()=>({left:rect[0],top:rect[1],width:rect[2],height:rect[3],right:rect[0]+rect[2],bottom:rect[1]+rect[3]}),
     checkVisibility(op){for(let p=this;p;p=p.parentElement){if(p._cs.display==='none')return false;if(op&&op.opacityProperty&&+p._cs.opacity===0)return false}if(this._cs.display==='contents')return false;if(op&&op.visibilityProperty&&this._cs.visibility!=='visible')return false;return true},contains(x){for(let p=x;p;p=p.parentElement)if(p===this)return true;return false},getElementsByTagName(){return all.filter(x=>x!==this&&this.contains(x))},
     appendChild(c){appends.push(e.id+':'+(c.tagName?'element':'fragment:'+c.children.length));if(e._throw||e._throwAt&&++e._n===e._throwAt)throw new Error('append');
       return adopt(g,c)}},domMethods(()=>g));
     e._own=extra||{};raws[id]=e;rawList.push(e);const g=guard(e,touched,tag==='VIDEO');RAW.set(g,e);PRE.add(g);if(parent)rawOf(parent).children.push(g);all.push(g);return g};
  const PRE=new Set(),fresh=n=>!PRE.has(n);
  const place=()=>JSON.stringify(rawList.map(e=>[e.id,e.parentElement&&(rawOf(e.parentElement).id||'new'),e.parentElement?rawOf(e.parentElement).children.indexOf(RAW_G.get(e)):-1]));
  const RAW_G=new Map();
  const snapshot=()=>JSON.stringify(rawList.map(e=>Object.keys(e).sort().filter(k=>typeof e[k]!=='function'&&k!=='_n')
    .map(k=>[k,k==='parentElement'?e[k]&&(rawOf(e[k]).id||'new'):k==='children'?e[k].filter(c=>!TARGETS.includes(e.id)||!fresh(c)).map(c=>fresh(c)?'new':rawOf(c).id):e[k]])));
  const html=el('HTML','html',Object.assign({position:'static'},o.htmlCs||{}),[0,0,1920,1080]);const body=el('BODY','body',Object.assign({position:'static',backgroundColor:'rgb(0, 0, 0)',overflowX:'hidden',overflowY:'hidden'},o.bodyCs||{}),[0,0,1920,0],html);
  const area=el('DIV','stageArea',Object.assign({overflowX:'hidden',overflowY:'hidden',visibility:'hidden'},o.areaCs||{}),[0,0,1920,1080],body);
  const stage=el('DIV','stage',Object.assign({transformStyle:'preserve-3d',transform:'matrix(1, 0, 0, 1, 0, 0)',visibility:'hidden'},o.stageCs||{}),[0,0,1920,1080],area);
  const root=el('DIV','layer1',Object.assign({transform:'matrix(1, 0, 0, 1, 0, 0)'},o.rootCs||{}),[0,0,1920,1080],stage);
  if(o.earlyZ)el('CANVAS','zcover',{zIndex:'5'},[100,780,400,100],root);if(o.earlyCanvas)el('CANVAS','early',o.earlyCanvas,[100,780,400,100],root);
  if(o.behind)el('CANVAS','behind',{},[100,780,400,100],root);
  const oldBase=el('DIV','layer9',o.chainStatic?{position:'static'}:{},o.baseRect||[0,0,1920,1080],root);
  const mlayer=el('DIV','layerM',Object.assign(o.chainStatic?{position:'static'}:{},o.layerCs||{}),o.clip||[109,795,952,268],oldBase);
  const video=el('VIDEO','vid',Object.assign(o.chainStatic?{position:'static'}:{},o.videoCs||{}),o.vrect||[109,795,952,268],o.videoOutside?body:mlayer,
    {readyState:o.rs==null?4:o.rs,videoWidth:(o.videoSize||[1920,540])[0],videoHeight:(o.videoSize||[1920,540])[1],checkVisibility:()=>o.visible!==false});
  if(o.video2)el('VIDEO','vid2',o.video2cs||{},o.video2rect||[600,800,400,200],mlayer,{readyState:o.video2rs==null?4:o.video2rs,videoWidth:1920,videoHeight:540});
  if(o.fg){let par=root;if(o.fg.group){par=el('DIV','grp',o.fg.group,[0,0,1920,1080],root);if(o.fg.sibling)el('CANVAS','sib',{},[1500,100,100,100],par)}
    if(o.fg.wrap)par=el('DIV','fgwrap',o.fg.wrap,o.fg.rect,par);if(o.fg.hostGroup)par=el('DIV','fghost',o.fg.hostGroup,[0,0,1920,1080],par);el(o.fg.tag||'CANVAS','fg',o.fg.cs||{},o.fg.rect,o.fg.outside?body:par);if(o.fg.pseudo)raws.fg._pseudo=o.fg.pseudo;if(o.fg.text)raws.fg.childNodes=[{nodeType:3,data:'Hi'}]}
  if(o.fg2)el('CANVAS','fg2',{},o.fg2,root);
  if(o.ext){let par=body;o.ext.forEach((x,i)=>{const id='ext'+i;par=el(x.tag||'DIV',id,x.cs||{},x.rect||[-200,0,100,100],par);if(x.text)raws[id].childNodes=[{nodeType:3,data:'Hi'}];
    if(x.shadow)raws[id].shadowRoot={mode:'open'};if(x.pseudo)raws[id]._pseudo=x.pseudo;if(x.ns){raws[id].namespaceURI=x.ns;raws[id].localName=(x.tag||'div').toLowerCase()}})}
  const t1=el('DIV','layer10',{},[0,0,1920,1080],stage),c1=el('DIV','layer11',{},[0,0,1920,1080],t1);el('DIV','layer12',{},[0,0,1920,1080],c1);
  const leafOut=el('DIV','layer13',{},[0,0,1920,1080],c1);const wrap=o.noWrap?null:el('DIV','layer13-opacity',{},[0,0,1920,1080],leafOut);
  const rw=raws['layer13-opacity'];if(o.appendThrows&&wrap)rw._throw=true;if(o.throwAt&&wrap){rw._throwAt=o.throwAt;rw._n=0}
  const ids={};all.forEach(e=>ids[e.id]=e);if(o.noOldBase)delete ids.layer9;
  let put=null,partialReads=0;const traces=[];let clk=0;const tick=()=>{clk+=o.clock||1};const px=(w,h)=>{const d=new Uint8ClampedArray(w*h*4).fill(o.grey==null?255:o.grey);for(let p=3;p<d.length;p+=4)d[p]=255;(o.pixels||[]).forEach((c,i)=>d.set(c,4*i));if(o.alphaAt!=null&&o.alphaAt<w*h)d[o.alphaAt*4+3]=o.alphaVal==null?254:o.alphaVal;return d};
  globalThis.document={documentElement:html,body,getElementById:id=>ids[id]||null,querySelectorAll:()=>all.filter(e=>e.tagName==='VIDEO'),getElementsByTagName:()=>all,
    querySelector:q=>{if(q!==':modal,:popover-open,:fullscreen')throw new Error('query '+q);return o.topLayer?all[0]:null},
    createDocumentFragment:()=>{const f={children:[]};f.appendChild=c=>adopt(f,c);return f},
    createElement:t=>t==='canvas'?node('CANVAS',{width:0,height:0,getContext(){const cv=this,tr=[];traces.push(tr);const ctx={globalAlpha:1,
      drawImage:(src,...a)=>{tick();if(o.drawThrows&&src===video)throw new Error('draw');draws.push([src.id,ctx.globalAlpha,...a.map(r6)]);
        tr.push(src.tagName==='VIDEO'?['video',src.id,...a.map(r6)]:['fg',src.id,ctx.globalAlpha,...a.map(r6)])},
      getImageData:(x,y,w,h)=>{tick();tr.push(['get',x,y,w,h]);if(x||y||w!==cv.width||h!==cv.height)partialReads++;return {data:px(w,h)}},
      putImageData:(D,x,y)=>{tick();tr.push(['put',x,y]);put=Array.from(D.data.slice(0,4*Math.max(3,(o.pixels||[]).length)))}};return ctx}}):node(t.toUpperCase())};
  globalThis.getComputedStyle=(e,p)=>(tick(),p)?Object.assign({content:'none',position:'static'},(v=>typeof v==='string'?{content:v}:v)(e._pseudo&&e._pseudo[p])):(e._cs||BASE);globalThis.innerWidth=(o.viewport||[1920,1080])[0];globalThis.window=globalThis;globalThis.innerHeight=(o.viewport||[1920,1080])[1];
  const tuple=o.vf===undefined?['bt709','bt709','bt709',false]:o.vf;let vfOpened=0,vfClosed=0;
  if(tuple==='missing')delete globalThis.VideoFrame;else globalThis.VideoFrame=class{constructor(x){tick();if(tuple==='throws')throw new Error('vf');vfOpened++;this.colorSpace={primaries:tuple[0],transfer:tuple[1],matrix:tuple[2],fullRange:tuple[3]}}close(){vfClosed++}};
  globalThis.performance={now:()=>clk};globalThis.__obedTakeMs=undefined;delete globalThis.__obedPlacement;
  if(o.placement!==null)Object.defineProperty(globalThis,'__obedPlacement',{configurable:true,get:()=>o.placement===undefined?'snap':o.placement});
  const E=o.cut?CUT:o.renamed?Object.assign({},EFF,{name:'apple:dissolve character'}):EFF,ev=o.event||0;
  const events=Array.from({length:ev+1},()=>({effects:[]}));if(!o.noEffect)events[ev]={effects:[E]};
  const U={script:o.throwScript?null:{slideWidth:1920,slideHeight:1080,events},playbackController:{kpfEvent:{baseLayer:{layerId:9}}},
    animationManager:{styleSheet:sheet()}};globalThis.UC=U;
  rawList.forEach(e=>RAW_G.set(e,all[rawList.indexOf(e)]));let firstTaken=null;const tree0=snapshot(),place0=place();
  if(o.stale){raws.vid.readyState=4;P.prototype.__obedFreezeTake(U,0);firstTaken=U.__obedFrozen?U.__obedFrozen.holders.length:0;raws.vid.readyState=o.rs;
    const sh=node('DIV');sh.appendChild(node('CANVAS',{width:0,height:0}));U.__obedFrozen={scene:0,holders:[sh]}}
  traces.length=0;const c0=clk;P.prototype.__obedFreezeTake(U,ev);const work=clk-c0;
  const taken=U.__obedFrozen?U.__obedFrozen.holders.length:0;const clearedByTake=U.__obedFrozen===null;
  const C={type:E.type,name:E.name,baseLayer:E.baseLayer};if('kind' in o)C.obedDissolve=o.kind;else new P(0).__obedDissolveLayer(C);
  new P('attachScene' in o?o.attachScene:ev).__obedFreeze(C,{layers:[{layers:[{layerId:12},{layerId:13}]}]});
  const attached=[...(wrap?raws['layer13-opacity'].children:[]),...raws.layer13.children].filter(fresh);
  const badHolders=attached.filter(h=>h.children.length!==1||!fresh(h.children[0])||h.children[0].tagName!=='CANVAS'||h.children[0].children.length||
    h.children[0].parentElement!==h).length;
  const holders=attached.map(h=>{const c=h.children[0],g=st=>[st.left,st.top,st.width,st.height].map(v=>r6(parseFloat(v))).join(',');
    return [h.style.position+'/'+h.style.overflow,g(h.style),c.width+'x'+c.height,c.style.position,g(c.style)]});
  return {taken,inWrap:wrap?raws['layer13-opacity'].children.filter(fresh).length:0,inLeaf:raws.layer13.children.filter(fresh).length,badHolders,placeChanged:place()!==place0,draws:draws.filter(d=>d[0]!=='vid'),holders,put,appends,kind:C.obedDissolve||null,
    traces,work,treeChanged:snapshot()!==tree0,touched,ms:U.__obedTakeMs,windowMs:globalThis.__obedTakeMs,slotCleared:UC.__obedFrozen===null,clearedByTake,firstTaken,vfOpened,vfClosed,partialReads};
}
const CASES=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const out={guardControl:guardControl(),callSites:callSites()};for(const k in CASES)out[k]=run(CASES[k]);console.log(JSON.stringify(out));
"""
FREEZE_GUARD_CONTROL = ["ctl set style.opacity", "ctl call setProperty", "ctl call pause", "ctl call play", "ctl set muted",
                        "ctl call remove",
                        "ctl unknown toggleAttribute", "ctl call toggleAttribute", "ctl unknown translate"]
# D4 takes before `displayScene` only when it plays the scene (B); D3 attaches after the draw, before the old DOM goes.
FREEZE_CALL_SITES = [["take", True, 3], ["display", 3], ["display", 3], ["draw", "a"], ["freeze", "C", "A"], ["remove", "w"]]

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
    "borderTopStyle": "solid", "borderRightStyle": "dashed", "borderBottomStyle": "double", "borderLeftStyle": "dotted",
    "borderTopLeftRadius": "8px", "borderTopRightRadius": "8px", "borderBottomLeftRadius": "8px", "borderBottomRightRadius": "8px",
    "paddingTop": "4px", "paddingRight": "4px", "paddingBottom": "4px", "paddingLeft": "4px", "objectViewBox": "inset(25%)",
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
# Every border, radius and padding member the plain-bitmap and clipping predicates read.
EDGE_PROPERTIES = (
    "borderTopStyle", "borderRightStyle", "borderBottomStyle", "borderLeftStyle",
    "borderTopLeftRadius", "borderTopRightRadius", "borderBottomLeftRadius", "borderBottomRightRadius",
)
BITMAP_PROPERTIES = (
    "backgroundColor", "backgroundImage", "boxShadow", *EDGE_PROPERTIES, "outlineStyle",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "objectViewBox", "imageRendering", "backdropFilter",
)
GATE_PROPERTIES = (
    "boxShadow", "filter", "backdropFilter", "outlineStyle", "borderImageSource", "webkitBoxReflect", "content",
    "columnRuleStyle",
)
# Paint families the gate refuses, and non-rendering elements whose text it ignores.
GATE_REFUSED_TAGS = ("IMG", "svg", "OBJECT", "EMBED", "IFRAME", "INPUT", "TEXTAREA", "SELECT", "BUTTON")
GATE_IGNORED_TAGS = ("HEAD", "SCRIPT", "STYLE", "LINK", "META", "TITLE", "BASE", "TEMPLATE", "NOSCRIPT")
FG_RECT = [788, 673, 353, 313]
CONFINED = [1100, 800, 100, 100]
ROTATED = "matrix(0.98, 0.17, -0.17, 0.98, 0, 0)"


def _fg(**kwargs) -> dict:
    return {"rect": FG_RECT, **kwargs}


def _gate(**kwargs) -> dict:
    return {"fg": _fg(**{"tag": "DIV", "rect": CONFINED, **kwargs})}


def _round(value: float) -> int:
    return math.floor(value + 0.5)


def _js(value: float) -> str:
    """A number as the stub prints it: rounded to 6 places, then JS `Number#toString`."""
    value = math.floor(value * 1e6 + 0.5) / 1e6
    return str(int(value)) if value == int(value) else repr(value)


def _snapped(vrect, clip=(0, 0, 1920, 1080), natural=(1920, 540), video="vid", dpr=1) -> tuple[list, list]:
    """Independent §3.2 geometry for one movie with the live base layer = slide (`kx` = `ky` = 1): every edge snapped to
    the device grid (1/DPR slide px). Returns the holder row (position/overflow, snapped slide-px region, device-pixel
    canvas, its CSS rect) and the canvas trace (the movie drawn into its snapped content box, then the whole backing read
    back). `natural` None is `object-fit: fill`."""
    f = min(vrect[2] / natural[0], vrect[3] / natural[1]) if natural else None
    cw, ch = (natural[0] * f, natural[1] * f) if natural else vrect[2:]
    cx, cy = vrect[0] + (vrect[2] - cw) / 2, vrect[1] + (vrect[3] - ch) / 2
    u0, v0, u1, v1 = (_round(z * dpr) for z in (cx, cy, cx + cw, cy + ch))
    a0, b0 = _round(max(clip[0], cx) * dpr), _round(max(clip[1], cy) * dpr)
    a1, b1 = _round(min(clip[0] + clip[2], cx + cw) * dpr), _round(min(clip[1] + clip[3], cy + ch) * dpr)
    w, h = _js((a1 - a0) / dpr), _js((b1 - b0) / dpr)
    holder = ["absolute/hidden", f"{_js(a0 / dpr)},{_js(b0 / dpr)},{w},{h}", f"{a1 - a0}x{b1 - b0}", "absolute", f"0,0,{w},{h}"]
    return holder, [["video", video, u0 - a0, v0 - b0, u1 - u0, v1 - v0], ["get", 0, 0, a1 - a0, b1 - b0]]


def _redraw(element: str, rect, alpha=1, origin=(109, 795)) -> list:
    """A foreground canvas redrawn into its snapped rect, in canvas pixels from the holder's snapped origin."""
    l, t = _round(rect[0]), _round(rect[1])
    return ["fg", element, alpha, l - origin[0], t - origin[1], _round(rect[0] + rect[2]) - l, _round(rect[1] + rect[3]) - t]


DEFAULT = _snapped([109, 795, 952, 268])
DPR2 = _snapped([109, 795, 952, 268], dpr=2)
DPR15 = _snapped([109, 795, 952, 268], dpr=1.5)
DPR15_FILL = _snapped([109, 795, 313, 263], natural=None, dpr=1.5)
QUARTER_BOX = [109, 795.25, 952, 268]
DPR2_QUARTER = _snapped(QUARTER_BOX, natural=None, dpr=2)
DEFAULT_TRACE = DEFAULT[1]
FILL = _snapped([109, 795, 960, 270], natural=None)
VIDEO2 = _snapped([600, 800, 400, 200], video="vid2")
FREEZE_SKIP = {"taken": 0, "inWrap": 0, "inLeaf": 0, "draws": [], "put": None, "holders": [], "appends": [], "kind": "dissolve"}
FREEZE_ADMIT = {"taken": 1, "inWrap": 1, "inLeaf": 0, "draws": [], "put": None, "holders": [DEFAULT[0]],
                "appends": ["layer13-opacity:fragment:1"], "kind": "dissolve"}
FREEZE_TWO_VIDEOS = dict(FREEZE_ADMIT, taken=2, inWrap=2, draws=[["vid2", 1, *VIDEO2[1][0][2:]]], appends=["layer13-opacity:fragment:2"],
                         holders=[DEFAULT[0], VIDEO2[0]], traces=[VIDEO2[1], DEFAULT_TRACE])
FREEZE_UNATTACHED = dict(FREEZE_ADMIT, inWrap=0, holders=[], appends=[], traces=[DEFAULT_TRACE])
TONE_PIXELS = [[128, 128, 128], [200, 64, 16], [0, 255, 32]]
TONE_ALL = [[v, 255 - v, (7 * v) % 256] for v in range(256)]
CLIP_LEFT_TOP = _snapped([109, 795, 952, 268], [300, 850, 500, 150])
LETTERBOXED = _snapped([109, 700, 952, 500])
CLIPPED_PANEL = _snapped([109, 795, 952, 268], [109, 795, 300, 268])
FILL_ASPECT_CHANGE = _snapped([109, 795, 952, 134], natural=None)
THROWING_NEIGHBOUR = _snapped([1300, 100, 400, 200], video="vid2")
FG2_RECT = [900, 700, 200, 200]
FG_REDRAW = _redraw("fg", FG_RECT)
STAGE_43 = "matrix(1.33333, 0, 0, 1.33333, 0, 0)"
STAGE_075 = "matrix(0.75, 0, 0, 0.75, 0, 0)"
METADATA_UA = {"display": "none"}
SVG_NS = "http://www.w3.org/2000/svg"
WITNESS_CS = {"overflowX": "hidden", "overflowY": "hidden"}
WITNESS = {"cs": WITNESS_CS, "rect": [-140, 0, 130, 1080]}
NAV_TEXT = {"text": True, "rect": [-140, 55, 20, 20]}
DROP_300 = "drop-shadow(rgb(255, 0, 0) 300px 0px 0px)"
DPR15_BOX = [109, 795, 313, 263]
FIXED_PSEUDO = {"content": '""', "position": "fixed"}
ABSOLUTE_PSEUDOS = {"::before": {"content": '""', "position": "absolute"}, "::after": {"content": '""', "position": "absolute"}}


def _hidden_parent(**effects) -> dict:
    return {"cs": {"visibility": "hidden", **effects}, "rect": [-300, 0, 200, 1080]}


FREEZE_ROW_COUNT = 274
# name -> (stub options, expected take/attach count and target, redraws [id, alpha, x, y, w, h], writeback (none on any
# path: identity tone), geometry).
FREEZE_ROWS = {
    "success": ({}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "stageScaledInSmallViewport": ({"scale": 4 / 3, "stageCs": {"transform": STAGE_43}}, FREEZE_SKIP),
    "stage2560": ({"scale": 4 / 3, "viewport": [2560, 1440], "stageCs": {"transform": STAGE_43}}, FREEZE_SKIP),
    "letterbox": ({"scale": 0.75, "off": [240, 135], "stageCs": {"transform": STAGE_075}}, FREEZE_SKIP),
    "uniformScale": ({"layerCs": {"transform": "matrix(0.75, 0, 0, 0.75, 10, 20)"}}, FREEZE_SKIP),
    "realCut": ({"cut": True, "noWrap": True}, dict(FREEZE_ADMIT, inWrap=0, inLeaf=1, appends=["layer13:fragment:1"], kind="cut")),
    "dissolveMissingWrapper": ({"noWrap": True}, FREEZE_UNATTACHED),
    "appendThrows": ({"appendThrows": True}, dict(FREEZE_UNATTACHED, appends=["layer13-opacity:fragment:1"])),
    "appendSecondThrows": ({"video2": True, "throwAt": 2}, FREEZE_TWO_VIDEOS),
    "attachOtherScene": ({"attachScene": 1}, FREEZE_UNATTACHED),
    "attachUnengaged": ({"kind": None}, dict(FREEZE_UNATTACHED, kind=None)),
    "staleAfterSuccess": ({"stale": True, "rs": 1}, dict(FREEZE_SKIP, firstTaken=1, clearedByTake=True)),
    "letterboxedVideo": ({"vrect": [109, 700, 952, 500]}, dict(FREEZE_ADMIT, holders=[LETTERBOXED[0]], traces=[LETTERBOXED[1]])),
    "clippedPanel": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden"}, "clip": [109, 795, 300, 268]},
                     dict(FREEZE_ADMIT, holders=[CLIPPED_PANEL[0]], traces=[CLIPPED_PANEL[1]])),
    "fillSameAspect": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 960, 270], "clip": [109, 795, 960, 270]},
                       dict(FREEZE_ADMIT, holders=[FILL[0]], traces=[FILL[1]])),
    "fillAspectChange": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 952, 134], "clip": [109, 795, 952, 134]},
                         dict(FREEZE_ADMIT, holders=[FILL_ASPECT_CHANGE[0]], traces=[FILL_ASPECT_CHANGE[1]])),
    "fgCanvas": ({"fg": _fg()}, dict(FREEZE_ADMIT, draws=[FG_REDRAW[1:]], traces=[DEFAULT_TRACE + [FG_REDRAW]])),
    "fgTranslucent": ({"fg": _fg(cs={"opacity": "0.2947"})}, dict(FREEZE_ADMIT, draws=[["fg", 0.2947, *FG_REDRAW[3:]]])),
    "fgGroupOpacityAlone": ({"fg": _fg(group={"opacity": "0.5"})}, dict(FREEZE_ADMIT, draws=[["fg", 0.5, *FG_REDRAW[3:]]])),
    "fgGroupOpacityWithSibling": ({"fg": _fg(group={"opacity": "0.5"}, sibling=True)}, FREEZE_SKIP),
    "fgPlacementFill": ({"videoCs": {"objectFit": "fill"}, "vrect": [109, 795, 960, 270], "clip": [109, 795, 960, 270],
                         "fg": _fg(rect=[788, 850, 353, 313])},
                        dict(FREEZE_ADMIT, holders=[FILL[0]], draws=[_redraw("fg", [788, 850, 353, 313])[1:]])),
    "fgNotIntersecting": ({"fg": _fg(rect=[1300, 100, 300, 200])}, FREEZE_ADMIT),
    "fgPlainDiv": ({"fg": _fg(tag="DIV")}, FREEZE_ADMIT),
    "fgImg": ({"fg": _fg(tag="IMG")}, FREEZE_SKIP),
    "fgDivWithBg": ({"fg": _fg(tag="DIV", cs={"backgroundColor": "rgb(0, 0, 0)"})}, FREEZE_SKIP),
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
    "overlappingVideos": ({"video2": True}, FREEZE_TWO_VIDEOS),
    "overlapLaterNotAdmitted": ({"video2": True, "video2rs": 1}, FREEZE_SKIP),
    "gate_laterVideoCover": ({"video2": True, "video2cs": {"objectFit": "cover"}}, FREEZE_SKIP),
    "mixedThrowingCandidate": ({"video2": True, "video2rect": [1300, 100, 400, 200], "drawThrows": True},
                               dict(FREEZE_ADMIT, draws=[["vid2", 1, *THROWING_NEIGHBOUR[1][0][2:]]], holders=[THROWING_NEIGHBOUR[0]],
                                    traces=[THROWING_NEIGHBOUR[1], []])),
    "noDecodedWidth": ({"videoSize": [0, 540]}, FREEZE_SKIP),
    "noDecodedHeight": ({"videoSize": [1920, 0]}, FREEZE_SKIP),
    "videoOutsideStage": ({"videoOutside": True}, FREEZE_SKIP),
    "rejectedEffect": ({"renamed": True}, dict(FREEZE_SKIP, kind=None)),
    "noFirstEffect": ({"event": 3, "noEffect": True}, FREEZE_SKIP),
    "takeAtIndex3": ({"event": 3}, FREEZE_ADMIT),
    "takeAtIndex3OtherScene": ({"event": 3, "attachScene": 0}, FREEZE_UNATTACHED),
    "aboveStage_areaTransform": ({"areaCs": {"transform": "matrix(1, 0, 0, 1, 5, 5)"}}, FREEZE_SKIP),
    "aboveStage_areaRelative": ({"areaCs": {"position": "relative"}}, FREEZE_SKIP),
    "aboveStage_bodyTransform": ({"bodyCs": {"transform": "matrix(1, 0, 0, 1, 0, 0)"}}, FREEZE_SKIP),
    "aboveStage_htmlFixed": ({"htmlCs": {"position": "fixed"}}, FREEZE_SKIP),
    "aboveStage_areaStatic": ({"areaCs": {"position": "static"}}, FREEZE_ADMIT),
    "clipLeftTop": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden"}, "clip": [300, 850, 500, 150]},
                    dict(FREEZE_ADMIT, holders=[CLIP_LEFT_TOP[0]], traces=[CLIP_LEFT_TOP[1]])),
    "baseRectUnequal": ({"baseRect": [0, 0, 1920, 1079.5]}, FREEZE_SKIP),
    "fgTwoCanvases": ({"fg": _fg(), "fg2": FG2_RECT},
                      dict(FREEZE_ADMIT, draws=[FG_REDRAW[1:], _redraw("fg2", FG2_RECT)[1:]],
                           traces=[DEFAULT_TRACE + [FG_REDRAW, _redraw("fg2", FG2_RECT)]])),
    "sparseAlpha": ({"alphaAt": 12345}, FREEZE_SKIP),
    "edgeAlpha": ({"alphaAt": 0, "alphaVal": 0}, FREEZE_SKIP),
    "lowerTransparency": ({"alphaAt": 200 * 952 + 5, "alphaVal": 0}, FREEZE_SKIP),
    "notReady": ({"rs": 1}, FREEZE_SKIP),
    "invisible": ({"visible": False}, FREEZE_SKIP),
    "translucentAncestor": ({"layerCs": {"opacity": "0.5"}}, FREEZE_SKIP),
    "drawThrows": ({"drawThrows": True}, FREEZE_SKIP),
    "noOldBase": ({"noOldBase": True}, FREEZE_SKIP),
    "clippedAway": ({"layerCs": {"overflowX": "hidden", "overflowY": "hidden"}, "clip": [0, 0, 50, 50]}, FREEZE_SKIP),
    "lutGrey128": ({"grey": 128}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "lutTone": ({"pixels": TONE_PIXELS}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "lutAll": ({"pixels": TONE_ALL}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "stageNonUniform": ({"stageCs": {"transform": "matrix(1, 0, 0, 0.99, 0, 0)"}}, FREEZE_SKIP),
    "stageNearUniform": ({"stageCs": {"transform": "matrix(1, 0, 0, 0.9995, 0, 0)"}}, FREEZE_SKIP),
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
    "gate_hiddenOriginVisiblePseudo": (_gate(cs={"visibility": "hidden"}, pseudo={"::before": '"x"'}), FREEZE_SKIP),
    "gate_displayContentsText": (_gate(cs={"display": "contents"}, text=True), FREEZE_SKIP),
    "gate_displayContentsPseudo": (_gate(cs={"display": "contents"}, pseudo={"::after": '"x"'}), FREEZE_SKIP),
    "gate_confinedNonIntersecting": (_gate(), FREEZE_ADMIT),
    "gate_suppressedTextIgnored": (_gate(text=True, hostGroup={"display": "none"}), FREEZE_ADMIT),
    "gate_opacityZeroTextIgnored": (_gate(text=True, hostGroup={"opacity": "0"}), FREEZE_ADMIT),
    "gate_hiddenShadowIgnored": (_gate(cs={"boxShadow": OUT_OF_PROFILE["boxShadow"], "visibility": "hidden"}), FREEZE_ADMIT),
    # Exterior proof (§3.2, r8 1-2): `ext` nests its elements under `body`, each inside the previous one. The navigator
    # shape: failing text under an off-viewport HTML `div` witness disjoint from the visible stage.
    "ext_witness_navigatorShape": ({"ext": [WITNESS, NAV_TEXT]}, FREEZE_ADMIT),
    "ext_hiddenFilterParent": ({"ext": [_hidden_parent(filter=DROP_300), WITNESS, NAV_TEXT]}, FREEZE_SKIP),
    "ext_hiddenUnfilteredParent": ({"ext": [_hidden_parent(), WITNESS, NAV_TEXT]}, FREEZE_ADMIT),
    "ext_hiddenReflectParent": ({"ext": [_hidden_parent(webkitBoxReflect="right 400px"), WITNESS, NAV_TEXT]}, FREEZE_SKIP),
    "ext_topLayer": ({"topLayer": True}, FREEZE_SKIP),
    "ext_svgWitness": ({"ext": [{"tag": "svg", "ns": SVG_NS, "cs": {"visibility": "hidden"}, "rect": [-300, 0, 200, 1080]},
                                {"tag": "g", "ns": SVG_NS, "cs": dict(WITNESS_CS, position="relative"), "rect": WITNESS["rect"]},
                                {"tag": "path", "ns": SVG_NS, "rect": NAV_TEXT["rect"]}]}, FREEZE_SKIP),
    "ext_witnessMeetsStage": ({"ext": [dict(WITNESS, rect=[-140, 0, 150, 1080]), NAV_TEXT]}, FREEZE_SKIP),
    "ext_noWitnessOverflowCaption": ({"ext": [{"text": True, "rect": [-60, 900, 40, 20]}]}, FREEZE_SKIP),
    "ext_witnessStatic": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, position="static")), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessAuto": ({"ext": [dict(WITNESS, cs={"overflowX": "auto", "overflowY": "auto"}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessShadow": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, boxShadow="rgb(0, 0, 0) 400px 0px 0px 0px")), NAV_TEXT]},
                          FREEZE_SKIP),
    "ext_fixedBetween": ({"ext": [WITNESS, {"cs": {"position": "fixed"}, "rect": [-140, 0, 50, 50]}, NAV_TEXT]}, FREEZE_SKIP),
    "ext_clippedTransformedDescendant": (
        {"ext": [WITNESS, {"cs": {"transform": "matrix(1, 0, 0, 1, 500, 0)"}, "rect": [-140, 0, 50, 50]}, NAV_TEXT]}, FREEZE_ADMIT),
    "ext_iframeUnderWitness": ({"ext": [WITNESS, {"tag": "IFRAME", "rect": [-140, 0, 100, 100]}]}, FREEZE_ADMIT),
    "ext_iframeNoWitness": ({"ext": [{"tag": "IFRAME", "rect": [-140, 0, 100, 100]}]}, FREEZE_SKIP),
    # Exterior proof, one witness or walk predicate at a time (impl r1 2): a fixed `::before`/`::after` below or on the
    # witness skips while the same pseudo-elements `absolute` admit; each property the witness needs, broken alone, skips.
    "ext_fixedBeforeBelowWitness": ({"ext": [WITNESS, dict(NAV_TEXT, pseudo={"::before": FIXED_PSEUDO})]}, FREEZE_SKIP),
    "ext_fixedAfterBelowWitness": ({"ext": [WITNESS, dict(NAV_TEXT, pseudo={"::after": FIXED_PSEUDO})]}, FREEZE_SKIP),
    "ext_pseudoBelowWitness": ({"ext": [WITNESS, dict(NAV_TEXT, pseudo=ABSOLUTE_PSEUDOS)]}, FREEZE_ADMIT),
    "ext_fixedBeforeOnWitness": ({"ext": [dict(WITNESS, pseudo={"::before": FIXED_PSEUDO}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_fixedAfterOnWitness": ({"ext": [dict(WITNESS, pseudo={"::after": FIXED_PSEUDO}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_pseudoOnWitness": ({"ext": [dict(WITNESS, pseudo=ABSOLUTE_PSEUDOS), NAV_TEXT]}, FREEZE_ADMIT),
    "ext_witnessSvgNamespaceDiv": ({"ext": [dict(WITNESS, tag="DIV", ns=SVG_NS), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessSection": ({"ext": [dict(WITNESS, tag="SECTION"), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessInline": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, display="inline")), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessFlex": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, display="flex")), NAV_TEXT]}, FREEZE_ADMIT),
    "ext_witnessHiddenXVisibleY": ({"ext": [dict(WITNESS, cs={"overflowX": "hidden"}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessVisibleXHiddenY": ({"ext": [dict(WITNESS, cs={"overflowY": "hidden"}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessOverflowVisible": ({"ext": [dict(WITNESS, cs={}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessOverflowClip": ({"ext": [dict(WITNESS, cs={"overflowX": "clip", "overflowY": "clip"}), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessFilter": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, filter=DROP_300)), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessBackdropFilter": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, backdropFilter="blur(4px)")), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessOutline": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, outlineStyle="solid")), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessBorderImage": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, borderImageSource="linear-gradient(red, red)")), NAV_TEXT]},
                               FREEZE_SKIP),
    "ext_witnessReflect": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, webkitBoxReflect="right 400px")), NAV_TEXT]}, FREEZE_SKIP),
    "ext_witnessFixed": ({"ext": [dict(WITNESS, cs=dict(WITNESS_CS, position="fixed")), NAV_TEXT]}, FREEZE_ADMIT),
    "ext_absoluteDescendant": ({"ext": [WITNESS, {"cs": {"position": "absolute"}, "rect": [-140, 0, 50, 50]}, NAV_TEXT]}, FREEZE_ADMIT),
    "ext_stickyDescendant": ({"ext": [WITNESS, {"cs": {"position": "sticky"}, "rect": [-140, 0, 50, 50]}, NAV_TEXT]}, FREEZE_ADMIT),
    "ext_failingStageAncestor": ({"bodyCs": {"filter": DROP_300}}, FREEZE_SKIP),
    "exteriorVideoMeetsRegion": ({"ext": [{"tag": "VIDEO", "rect": [500, 800, 200, 200]}]}, FREEZE_SKIP),
    # Geometry guard and opaque cover (r8 3-5, rev 13 fix A): edges snap to the device grid, so DPR 1.5 `fill` 313x263
    # backs 469x394 and the P2 box 1428x401, DPR 2 backs 1904x536 (a y 795.25 edge snaps to 795.5); DPR 1.25 and 3
    # (unmeasured), stage scales and a scale below the stage skip; fractional stage origins and a letterbox at scale 1
    # admit; a transparent last backing column, row or pixel skips at every admitted DPR.
    "dpr15_fillOpaque": ({"dpr": 1.5, "videoCs": {"objectFit": "fill"}, "vrect": DPR15_BOX, "clip": DPR15_BOX},
                         dict(FREEZE_ADMIT, holders=[DPR15_FILL[0]], traces=[DPR15_FILL[1]])),
    "dpr15_fillLastColumnTransparent": (
        {"dpr": 1.5, "videoCs": {"objectFit": "fill"}, "vrect": DPR15_BOX, "clip": DPR15_BOX, "alphaAt": 468, "alphaVal": 0}, FREEZE_SKIP),
    "dpr1_lastColumnTransparent": ({"alphaAt": 951, "alphaVal": 0}, dict(FREEZE_SKIP, traces=[DEFAULT_TRACE])),
    "dpr1_lastRowTransparent": ({"alphaAt": 952 * 267, "alphaVal": 0}, dict(FREEZE_SKIP, traces=[DEFAULT_TRACE])),
    "dpr1_lastPixelTransparent": ({"alphaAt": 952 * 268 - 1, "alphaVal": 0}, dict(FREEZE_SKIP, traces=[DEFAULT_TRACE])),
    "dpr2": ({"dpr": 2}, dict(FREEZE_ADMIT, holders=[DPR2[0]], traces=[DPR2[1]])),
    "dpr2_quarterPixelEdge": ({"dpr": 2, "videoCs": {"objectFit": "fill"}, "vrect": QUARTER_BOX, "clip": QUARTER_BOX},
                              dict(FREEZE_ADMIT, holders=[DPR2_QUARTER[0]], traces=[DPR2_QUARTER[1]])),
    "dpr2_lastPixelTransparent": ({"dpr": 2, "alphaAt": 1904 * 536 - 1, "alphaVal": 0}, dict(FREEZE_SKIP, traces=[DPR2[1]])),
    "dpr15_p2Box": ({"dpr": 1.5}, dict(FREEZE_ADMIT, holders=[DPR15[0]], traces=[DPR15[1]])),
    "dpr15_lastPixelTransparent": ({"dpr": 1.5, "alphaAt": 1428 * 401 - 1, "alphaVal": 0}, dict(FREEZE_SKIP, traces=[DPR15[1]])),
    "dpr125": ({"dpr": 1.25}, dict(FREEZE_SKIP, traces=[])),
    "dpr3": ({"dpr": 3}, dict(FREEZE_SKIP, traces=[])),
    "stageScale43": ({"scale": 4 / 3, "viewport": [2560, 1440], "stageCs": {"transform": STAGE_43}}, FREEZE_SKIP),
    "stageScale075": ({"scale": 0.75, "off": [240, 135], "stageCs": {"transform": STAGE_075}}, FREEZE_SKIP),
    "stageLetterboxScale1": ({"off": [0, 60], "viewport": [1920, 1200], "stageCs": {"transform": "matrix(1, 0, 0, 1, 0, 0)"}},
                             FREEZE_ADMIT),
    "stageFractionalOrigin": ({"off": [0, 60.5], "viewport": [1920, 1201]}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "stageFractionalOriginX": ({"off": [0.5, 60], "viewport": [1921, 1200]}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    "scaleBelowStage": ({"layerCs": {"transform": "matrix(1.5, 0, 0, 1.5, 0, 0)"}}, FREEZE_SKIP),
    "fractionalTranslation": ({"layerCs": {"transform": "matrix(1, 0, 0, 1, 0.5, 0.25)"}}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    # r9: no tag is exempt by name (rendering state decides), open author shadow roots skip, `kx` = `ky` = 1.
    "r9_renderedScriptOverflow": ({"ext": [{"tag": "SCRIPT", "text": True, "cs": {"display": "block"}, "rect": [-60, 800, 40, 30]}]},
                                  FREEZE_SKIP),
    "r9_renderedHiddenHeadFilter": ({"ext": [dict(_hidden_parent(filter=DROP_300), tag="HEAD"), WITNESS, NAV_TEXT]}, FREEZE_SKIP),
    "r9_defaultMetadataScript": ({"ext": [{"tag": "SCRIPT", "text": True, "cs": METADATA_UA, "rect": [0, 0, 0, 0]}]}, FREEZE_ADMIT),
    "r9_defaultMetadataHead": ({"ext": [{"tag": "HEAD", "cs": METADATA_UA, "rect": [0, 0, 0, 0]},
                                        {"tag": "STYLE", "text": True, "cs": METADATA_UA, "rect": [0, 0, 0, 0]}]}, FREEZE_ADMIT),
    "r9_openShadowHost": ({"ext": [{"rect": [-200, 0, 10, 10], "shadow": True}]}, FREEZE_SKIP),
    "r9_baseHalfWidth": ({"baseRect": [0, 0, 960, 1080]}, FREEZE_SKIP),
    "r9_baseFractionalHeight": ({"baseRect": [0, 0, 1920, 1079.5]}, FREEZE_SKIP),
    "r9_fullSlide": ({}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
    # Rev 17: the take proceeds only on the host's `snap` grant; an absent getter is the preview/raw page (patch_rendering).
    "gate_grantAbsent": ({"placement": None}, FREEZE_SKIP),
    "gate_grantInvalid": ({"placement": "invalid"}, FREEZE_SKIP),
    "gate_grantFrac": ({"placement": "frac"}, FREEZE_SKIP),
    "gate_grantUpperSnap": ({"placement": "SNAP"}, FREEZE_SKIP),
    # Scene elements need integral computed `left`/`top` in px; sub-pixel offsets come only from transforms.
    "leftFractional": ({"layerCs": {"left": "0.5px"}}, FREEZE_SKIP),
    "topFractional": ({"layerCs": {"top": "10.25px"}}, FREEZE_SKIP),
    "leftAuto": ({"layerCs": {"left": "auto"}}, FREEZE_SKIP),
    "leftNegativeInteger": ({"layerCs": {"left": "-3px"}}, dict(FREEZE_ADMIT, traces=[DEFAULT_TRACE])),
}
for _prop in CHAIN_PROPERTIES:
    FREEZE_ROWS[f"chain_{_prop}"] = ({"layerCs": {_prop: OUT_OF_PROFILE[_prop], **CHAIN_COMPANIONS.get(_prop, {})}}, FREEZE_SKIP)
for _prop in BITMAP_PROPERTIES:
    FREEZE_ROWS[f"video_{_prop}"] = ({"videoCs": {_prop: OUT_OF_PROFILE[_prop]}}, FREEZE_SKIP)
    FREEZE_ROWS[f"fgCanvas_{_prop}"] = ({"fg": _fg(cs={_prop: OUT_OF_PROFILE[_prop]})}, FREEZE_SKIP)
for _prop in GATE_PROPERTIES:
    FREEZE_ROWS[f"gate_{_prop}"] = (_gate(cs={_prop: OUT_OF_PROFILE[_prop]}), FREEZE_SKIP)
for _prop in EDGE_PROPERTIES:
    _clip = {"overflowX": "hidden", "overflowY": "hidden", _prop: OUT_OF_PROFILE[_prop]}
    FREEZE_ROWS[f"chainClip_{_prop}"] = ({"layerCs": _clip}, FREEZE_SKIP)
for _tag in GATE_REFUSED_TAGS:
    FREEZE_ROWS[f"gate_tag{_tag}"] = (_gate(tag=_tag), FREEZE_SKIP)
for _tag in GATE_IGNORED_TAGS:
    FREEZE_ROWS[f"gate_{_tag.lower()}TextIgnored"] = ({"fg": _fg(tag=_tag, rect=[0, 0, 0, 0], text=True, cs=METADATA_UA)}, FREEZE_ADMIT)


# Deck stub DOMs (`node_f3_r12_decks.py`): the live slide shown before each movie slide's outgoing Dissolve, built from
# the export JSON the way `NB.addNode`, `xB.initVideo` and `renderMovie` do (computed style = inline style + UA).
FREEZE_DECKS_JS = r"""
let TB=0;
const RAW=new WeakMap(),rawOf=n=>RAW.get(n)||n;
const detach=c=>{const r=rawOf(c),p=r.parentElement;if(p){const l=rawOf(p).children,i=l.indexOf(c);if(i>=0)l.splice(i,1)}r.parentElement=null};
function adopt(p,c,ref){if(c&&!c.tagName&&c.children){c.children.slice().forEach(k=>adopt(p,k,ref));return c}
  detach(c);const l=rawOf(p).children,i=ref?l.indexOf(ref):-1;i>=0?l.splice(i,0,c):l.push(c);rawOf(c).parentElement=p;return c}
const domMethods=me=>({append(...a){a.forEach(c=>adopt(me(),c))},prepend(...a){const f=rawOf(me()).children[0];a.forEach(c=>adopt(me(),c,f))},
  insertBefore(c,r){return adopt(me(),c,r)},replaceChild(n,o){adopt(me(),n,o);detach(o);return o},removeChild(c){detach(c);return c},remove(){detach(me())},
  before(...a){const p=rawOf(me()).parentElement;a.forEach(c=>adopt(p,c,me()))},after(...a){const p=rawOf(me()).parentElement,l=rawOf(p).children,nx=l[l.indexOf(me())+1];a.forEach(c=>adopt(p,c,nx))},
  replaceWith(...a){const p=rawOf(me()).parentElement;a.forEach(c=>adopt(p,c,me()));detach(me())},replaceChildren(...a){rawOf(me()).children.slice().forEach(detach);a.forEach(c=>adopt(me(),c))}});
function node(tag,extra){const n=Object.assign({tagName:tag,style:{},children:[],parentElement:null},extra||{});
  return Object.assign(n,domMethods(()=>n),{appendChild(c){return adopt(n,c)}},extra||{})}
class P{constructor(si){this.sceneIndex=si}%METHODS%}
globalThis.DOMMatrix=class{constructor(s){const m=/matrix(3d)?\(([^)]*)\)/.exec(s);const v=m[2].split(',').map(Number);this.is2D=!m[1];this.a=v[0];this.b=v[1];this.c=m[1]?v[4]:v[2];this.d=m[1]?v[5]:v[3]}};
const UA={left:'0px',top:'0px',display:'block',contain:'none',contentVisibility:'visible',isolation:'auto',perspective:'none',backfaceVisibility:'visible',willChange:'auto',zoom:'1',imageRendering:'auto',opacity:'1',transform:'none',filter:'none',mixBlendMode:'normal',clipPath:'none',maskImage:'none',zIndex:'auto',overflowX:'visible',overflowY:'visible',position:'static',
 borderTopLeftRadius:'0px',borderTopRightRadius:'0px',borderBottomLeftRadius:'0px',borderBottomRightRadius:'0px',objectPosition:'50% 50%',paddingTop:'0px',paddingLeft:'0px',paddingRight:'0px',paddingBottom:'0px',
 borderTopStyle:'none',borderRightStyle:'none',borderBottomStyle:'none',borderLeftStyle:'none',objectFit:'fill',backgroundColor:'rgba(0, 0, 0, 0)',backgroundImage:'none',boxShadow:'none',outlineStyle:'none',
 transformStyle:'flat',borderImageSource:'none',webkitBoxReflect:'none',content:'normal',columnRuleStyle:'none',scale:'none',rotate:'none',translate:'none',offsetPath:'none',clip:'auto',backdropFilter:'none',objectViewBox:'none',visibility:'visible'};
const mul=(A,B)=>[A[0]*B[0]+A[2]*B[1],A[1]*B[0]+A[3]*B[1],A[0]*B[2]+A[2]*B[3],A[1]*B[2]+A[3]*B[3],A[0]*B[4]+A[2]*B[5]+A[4],A[1]*B[4]+A[3]*B[5]+A[5]];
function run(C){
  const all=[];let vids=[];
  const mk=(tag,id,cs,w,h,parent,M,org)=>{const e={tagName:tag,id,nodeType:1,localName:tag.toLowerCase(),namespaceURI:'http://www.w3.org/1999/xhtml',shadowRoot:null,_cs:Object.assign({},UA,tag==='VIDEO'?{objectFit:'contain',overflowX:'clip',overflowY:'clip'}:{},tag==='CANVAS'?{overflowX:'clip',overflowY:'clip'}:{},cs),childNodes:[],children:[],style:{},parentElement:parent||null,_w:w,_h:h,_M:M||[1,0,0,1,0,0],_o:org||[w/2,h/2],
    contains(x){for(let p=x;p;p=p.parentElement)if(p===this)return true;return false},getElementsByTagName(){const o=[];const w=n=>{n.children.forEach(c=>{o.push(c);w(c)})};w(this);return o},
    checkVisibility(op){for(let p=this;p;p=p.parentElement){if(p._cs.display==='none')return false;if(op&&op.opacityProperty&&+p._cs.opacity===0)return false}if(op&&op.visibilityProperty&&this._cs.visibility!=='visible')return false;return true},
    appendChild(c){return adopt(this,c)},
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
    querySelector:q=>{if(q!==':modal,:popover-open,:fullscreen')throw new Error('query '+q);return null},createDocumentFragment:()=>{const f={children:[]};f.appendChild=c=>adopt(f,c);return f},
    createElement:t=>t==='canvas'?node('CANVAS',{getContext(){const ctx={globalAlpha:1,drawImage:(s,...a)=>{if(s.tagName!=='VIDEO')draws.push([s.id,+ctx.globalAlpha.toFixed(4),...a.map(x=>Math.round(x))])},
      getImageData:(x,y,w,h)=>{const d=new Uint8ClampedArray(w*h*4).fill(255);return {data:d}},putImageData(){}};return ctx}}):node(t.toUpperCase())};
  globalThis.getComputedStyle=(e,p)=>p?{content:'none'}:e._cs;globalThis.devicePixelRatio=1;globalThis.__obedPlacement='snap';globalThis.innerWidth=1920;globalThis.window=globalThis;globalThis.innerHeight=1080;globalThis.VideoFrame=class{constructor(x){this.colorSpace={primaries:'bt709',transfer:'bt709',matrix:'bt709',fullRange:false}}close(){}};
  const U={script:{slideWidth:1920,slideHeight:1080,events:[{effects:[C.effect]}]},playbackController:{kpfEvent:{baseLayer:{layerId:1}}}};globalThis.UC=U;
  all.forEach(e=>Object.assign(e,domMethods(()=>e),{appendChild(c){return adopt(e,c)}}));const PRE=new Set(all),fresh=n=>!PRE.has(n);
  const place=()=>JSON.stringify(all.map(e=>[e.id,e.parentElement&&(e.parentElement.id||'new'),e.parentElement?e.parentElement.children.indexOf(e):-1,e.children.map(c=>fresh(c)?'new':c.id)]));
  const place0=place();P.prototype.__obedFreezeTake(U,0);
  const F=U.__obedFrozen;const badHolders=F?F.holders.filter(h=>h.children.length!==1||!fresh(h.children[0])||h.children[0].tagName!=='CANVAS'||h.children[0].children.length||h.children[0].parentElement!==h).length:0;
  return {placeChanged:place()!==place0,badHolders,videos:vids.length,holders:F?F.holders.map(h=>[h.style.left,h.style.top,h.style.width,h.style.height].map(x=>Math.round(parseFloat(x)))):[],draws};
}
const CASES=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));const out={};for(const C of CASES)out[C.label]=run(C);console.log(JSON.stringify(out));
"""

# §8's deck table: movies, snapped holders (slide px) and redrawn foreground (id, alpha, rect in canvas px from the holder's
# snapped origin; rev 9 gave it in video px, 2x for P2 slide 2 and about 4x for DSK slide 7).
_DSK7_REDRAWS = [["84D61F77", 1, 8, 0, 257, 65], ["7262F462", 1, 315, 2, 4, 266], ["0A370629", 1, 3, -1, 283, 65],
                 ["183D386F", 1, 304, -2, 320, 271], ["054DC953", 1, 307, 1, 4, 265], ["ED5928A0", 1, 315, -1, 208, 65]]
_P2_SLIDE2 = {"videos": 1, "holders": [[105, 794, 960, 270]], "draws": [["3F22E494", 0.2947, 684, -121, 353, 313]]}
FREEZE_DECK_TABLE = {
    "P2 slide 2 event 3": _P2_SLIDE2,
    "P2 slide 4 event 1": {"videos": 1, "holders": [[323, 708, 1274, 358]], "draws": []},
    "DSK slide 2 event 3": _P2_SLIDE2,
    "DSK slide 3 event 1": {"videos": 2, "holders": [[194, 796, 960, 270], [1153, 795, 484, 272]], "draws": []},
    "DSK slide 5 event 1": {"videos": 1, "holders": [[323, 697, 1274, 358]], "draws": []},
    "DSK slide 7 event 1": {"videos": 2, "holders": [[358, 800, 476, 267], [39, 799, 320, 269]], "draws": _DSK7_REDRAWS},
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


_DECK_STATE_FIELDS = (
    "width", "height", "affineTransform", "anchorPoint", "position", "hidden", "opacity", "masksToBounds", "backgroundColor",
)


def _deck_tree(layer: dict) -> dict:
    out = {"initialState": {k: v for k, v in layer["initialState"].items() if k in _DECK_STATE_FIELDS}}
    out.update({k: layer[k] for k in ("objectID", "texture") if layer.get(k)})
    if layer.get("layers"):
        out["layers"] = [_deck_tree(child) for child in layer["layers"]]
    return out


def _freeze_deck_cases() -> list[dict]:
    """The scene shown before each movie slide's outgoing Dissolve: the previous event's tree, its builds applied."""
    cases = []
    for deck, root in FREEZE_DECKS.items():
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
                cases.append({"label": f"{deck} slide {index + 1} event {k}", "tree": _deck_tree(previous["baseLayer"]), "built": built,
                              "movies": {o: [s.get("width"), s.get("height")] for o, s in sizes.items()}, "effect": effect})
    return cases


def _run_node_file(node: str, tmp_path: Path, name: str, script: str, data) -> dict:
    (tmp_path / f"{name}.js").write_text(script)
    (tmp_path / f"{name}.json").write_text(json.dumps(data))
    paths = [str(tmp_path / f"{name}.js"), str(tmp_path / f"{name}.json")]
    result = subprocess.run([node, *paths], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _cut_from(dissolve: dict) -> dict:
    """A full-shape Dissolve re-timed as Keynote exports a `none` cut (the plan's in-memory `p2cut`)."""
    cut = json.loads(json.dumps(dissolve))
    cut.update(CUT_EFFECT)
    cut["baseLayer"]["layers"][0]["layers"][1]["animations"] = [dict(CUT_OUTGOING)]
    return cut


def _method(source: str, head: str) -> str:
    """One method of the player, from `head` to its matching close brace (string literals skipped)."""
    start = source.index(head)
    assert source.count(head) == 1
    depth, quote, i = 0, None, start + len(head) - 1
    while True:
        c = source[i]
        if quote:
            quote = None if c == quote and source[i - 1] != "\\" else quote
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if not depth:
                return source[start : i + 1]
        i += 1


def _full_shape(effect: dict) -> bool:
    layers = (effect.get("baseLayer") or {}).get("layers") or []
    return len(layers) == 1 and len(layers[0].get("layers") or []) == 2


# construction: committed transitions plus one cut, the near-misses, failures and ids (mandatory); census: the 133
# transitions on disk (needs the main checkout's output/fixtures).
DISSOLVE_NODE_CASES = ("construction", "census", "freeze_stub", "freeze_decks")
# The committed exports §8 counts. Qualification and Stage B's repaired Alpha fixture are separate test corpora.
DISSOLVE_COMMITTED_EXPORTS = tuple(
    p for p in sorted(FIXTURE_ROOT.iterdir()) if p.is_dir() and p.name not in {"qual_decks", "alpha_dsk_repaired", "alpha_dsk_repaired_full"}
)


@pytest.mark.parametrize("case", DISSOLVE_NODE_CASES)
@pytest.mark.parametrize("sha", REAL_PLAYERS)
def test_dissolve_real_patched_methods_on_node(tmp_path, sha, case):
    node, player = _node(), _real_player(sha)
    patched = live_runtime.patch_player(player).decode()
    methods = _cut(patched, "__obedShape(C){", "renderEffects(A){")
    assert live_runtime._MM_OPACITY_REPLACEMENTS[DISSOLVE][0][1] == b"return B}" + methods.encode() + b"renderEffects(A){"
    if case in ("construction", "census"):
        classes = _cut(patched, "let TB=0;class yB{", "class bB{")
        d2 = _cut(patched, "const A=new VB(", "objectID:e});") + "objectID:e});"
        script = DISSOLVE_PLAYER_SCOPE + classes + DISSOLVE_CONSTRUCTION_JS.replace("%METHODS%", methods).replace("%D2%", d2)
        committed = _transitions(*DISSOLVE_COMMITTED_EXPORTS)
        assert len(committed) == 16
    if case == "construction":
        # The 16 committed transitions (4 full-shape Dissolves, 2 trimmed, 10 Magic Moves) plus P2 2->3 re-timed as a cut:
        # copies with the mirrored animation, two rules on exactly the ids `VB` then allocates pre-order (root,
        # container, incoming, outgoing = TB .. TB+3), no export mutated. Near-misses and failures mutate copies of
        # the first full-shape Dissolve (P2 2->3) and of that cut.
        transitions = committed + [_cut_from(next(e for e in committed if e["name"] == "apple:dissolve" and _full_shape(e)))]
        failures = {name: options for name, (options, _) in DISSOLVE_CONSTRUCTION_FAILURES.items()}
        data = {"transitions": transitions, "nearMisses": DISSOLVE_NEAR_MISSES, "failures": failures}
        result = _run_node_file(node, tmp_path, case, script, data)
        assert result["summary"] == {"dissolve": 4, "cut": 1, "stock": 12, "mutated": 0, "badCopy": 0, "badIds": 0, "stockTouched": 0}
        # The incoming animation is the outgoing one with its endpoints swapped; altered timing is told apart.
        control = {"mirror": True, "duration": False, "beginTime": False, "fillMode": False}
        assert result["mirrorControls"] == {"dissolve": control, "cut": control}
        assert result["near"] == {name: DISSOLVE_NEAR_MISS_ENGAGED.get(name, "stock") for name in DISSOLVE_NEAR_MISSES}
        misses = [effect for name, (effect, _, _) in DISSOLVE_NEAR_MISSES.items() if name not in DISSOLVE_NEAR_MISS_ENGAGED]
        # §8's 21 Dissolve near-misses plus 18 for the predicate fields the review inventory found unexercised; 10 cut ones.
        assert (misses.count("apple:dissolve"), misses.count("none")) == (39, 10)
        assert result["failures"] == {name: expected for name, (_, expected) in DISSOLVE_CONSTRUCTION_FAILURES.items()}
        # D2's real call site builds `VB` from the copy `__obedDissolveLayer` returns.
        assert result["callSites"] == [["layer", "apple:dissolve"], ["VB", True, "apple:dissolve", "transition", "obj"]]
    elif case == "census":
        # §8: all 133 transitions on disk give 46 Dissolves copied, 8 cuts and 79 stock; every on-disk cut has the
        # timing CUT_OUTGOING models, and the committed deck inputs still match the exports.
        if not OUTPUT_FIXTURES.is_dir():
            pytest.skip("export fixtures under output/ not available")
        transitions = _transitions(OUTPUT_FIXTURES, *DISSOLVE_COMMITTED_EXPORTS)
        assert len(transitions) == 133
        cuts = [e for e in transitions if e["name"] == "none"]
        assert len(cuts) == 8
        for cut in cuts:
            assert {k: cut[k] for k in CUT_EFFECT} == CUT_EFFECT
            assert cut["baseLayer"]["layers"][0]["layers"][1]["animations"] == [CUT_OUTGOING]
        assert json.loads(FREEZE_DECK_FIXTURE.read_text()) == _freeze_deck_cases()
        result = _run_node_file(node, tmp_path, case, script, {"transitions": transitions, "nearMisses": {}, "failures": {}})
        assert result["summary"] == {"dissolve": 46, "cut": 8, "stock": 79, "mutated": 0, "badCopy": 0, "badIds": 0, "stockTouched": 0}
    elif case == "freeze_stub":
        effect = json.loads(FREEZE_EFFECT.read_text())["events"][1]["effects"][0]
        d3 = _cut(patched, "this.cssRenderer.draw(a),", "a.removeChild(w)}") + "a.removeChild(w)}"
        script = (FREEZE_STUB_JS.replace("%METHODS%", methods).replace("%EFF%", json.dumps(effect))
                  .replace("%CUT%", json.dumps(_cut_from(effect))).replace("%D3%", d3).replace("%D4%", _method(patched, "jumpToScene_partFour(A,B){")))
        result = _run_node_file(node, tmp_path, case, script, {name: options for name, (options, _) in FREEZE_ROWS.items()})
        # §8's 134 rows grew with the review controls (viewport, attach, stale slot, append, tone, take index and
        # effect, above-stage, every edge member, refused and ignored tags, decoded size, outside stage, mixed candidates)
        # to 200, then rev 12's 26 r8 rows (exterior proof, top layer, geometry guard, opaque cover) and 8 r9 rows, then
        # impl r1's 26 (one exterior predicate at a time, the last backing pixel, a fractional x origin), then rev 13's 5
        # (DPR 1.25 and 3 skip, DPR 1.5 on the P2 box, the last backing pixel at DPR 1.5 and 2) and a DPR 2 quarter-pixel
        # edge (y 795.25 snaps to 795.5 on the device grid, 795 on the CSS grid), then rev 17's 8 (grant absent or other
        # than `snap`, fractional or `auto` scene `left`/`top`, a negative integer `left`).
        assert len(FREEZE_ROWS) == FREEZE_ROW_COUNT
        assert result.pop("guardControl") == FREEZE_GUARD_CONTROL
        assert result.pop("callSites") == FREEZE_CALL_SITES
        for name, (options, expected) in FREEZE_ROWS.items():
            row = result[name]
            assert {k: row[k] for k in expected} == expected, name
            # The video is only read; the cost is published on every path; the slot is always consumed; every
            # VideoFrame is closed; a gate row is refused before any candidate is read.
            # No stub element is written, called or probed for an unknown member, except D3's one fragment append to its
            # target; the whole document tree (parents, child order, attributes, styles) is unchanged apart from it.
            assert row["touched"] == [] and not row["treeChanged"], name
            # Every pre-existing node keeps its parent and child index (real node-move semantics on every node), and
            # each attached holder holds exactly the product's own canvas.
            assert not row["placeChanged"] and row["badHolders"] == 0, name
            # The cost is the take's whole deterministic work (every style read, frame, draw, readback and redraw).
            assert row["ms"] == row["windowMs"] == row["work"], name
            # Each snapshot canvas runs video draw -> whole-backing readback -> foreground redraws, in that order, and
            # never writes pixels back (identity tone).
            for trace in row["traces"]:
                kinds = "".join({"video": "v", "get": "g", "put": "p", "fg": "f"}[op[0]] for op in trace)
                assert re.fullmatch(r"(v(gf*)?)?", kinds), (name, kinds)
            assert row["put"] is None and row["partialReads"] == 0, name
            assert row["slotCleared"] and row["vfOpened"] == row["vfClosed"], name
            if name.startswith(("gate_", "ext_", "r9_")) and expected == FREEZE_SKIP:
                assert row["vfOpened"] == 0, name
    else:
        cases = json.loads(FREEZE_DECK_FIXTURE.read_text())
        result = _run_node_file(node, tmp_path, case, FREEZE_DECKS_JS.replace("%METHODS%", methods), cases)
        # The videos and every other stub node keep their parents and child order; each holder holds exactly its canvas.
        assert {label: (row.pop("placeChanged"), row.pop("badHolders")) for label, row in result.items()} == {
            label: (False, 0) for label in FREEZE_DECK_TABLE}
        assert result == FREEZE_DECK_TABLE

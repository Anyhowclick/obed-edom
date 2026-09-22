from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

from obed_edom import live_runtime


def test_unknown_player_is_refused():
    with pytest.raises(live_runtime.LiveRuntimeUnsupported):
        live_runtime.patch_player(b"unknown player")


def test_patch_requires_exactly_one_hook(monkeypatch):
    for player in (b"no hook", live_runtime._ANCHOR * 2):
        monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
        with pytest.raises(live_runtime.LiveRuntimeUnsupported):
            live_runtime.patch_player(player)


def test_patch_preserves_surrounding_player(monkeypatch):
    player = b"before;" + live_runtime._ANCHOR + b";after"
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
    patched = live_runtime.patch_player(player)
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

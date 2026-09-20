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
    assert playing["busy"] and not playing["canGoTo"]
    assert chain["busy"] and not chain["ready"]
    assert settled["ready"] and settled["exportedSlideIndex"] == 0
    assert end["exportedSlideIndex"] == 1 and end["sceneId"] == 2
    assert end["ready"] and not end["canAdvance"]
    assert end["revision"] > initial["revision"] and end["buildIndex"] is None
    assert not automatic["ready"] and automatic["refusalReason"]

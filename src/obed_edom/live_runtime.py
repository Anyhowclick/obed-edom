"""Read-only observation of one explicitly supported Keynote HTML player."""

from __future__ import annotations

import hashlib

RUNTIME_VERSION = 1
PLAYER_SHA256 = "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354"
_ANCHOR = b"UC=new Eg,UC.displayManager.showWaitingIndicator()"

_INSTALL = r"""
(function(controller) {
  let revision = 0;
  for (const name of ['changeState', 'setCurrentSceneIndexTo']) {
    const original = controller[name];
    controller[name] = function(...args) {
      const result = original.apply(this, args);
      revision += 1;
      return result;
    };
  }
  Object.defineProperty(window, '__obedLive', {value: Object.freeze({
    snapshot() {
      const script = controller.script;
      const state = controller.state || 'Starting';
      const initial = state === 'IdleAtInitialState';
      const final = state === 'IdleAtFinalState';
      const manual = !!script && script.showMode === 0;
      const next = script && script.events[controller.nextSceneIndex];
      const automaticPending = final && !!next && !!next.automaticPlay;
      const ready = manual && (initial || final) && !automaticPending &&
        !controller.queuedUserAction;
      let slide = controller.currentSlideIndex;
      if (script && (!Number.isInteger(slide) || slide < 0)) {
        slide = script.slideIndexFromSceneIndexLookup[controller.currentSceneIndex];
      }
      return {
        runtimeVersion: 1,
        ready,
        busy: !ready,
        playerState: state,
        sceneId: controller.currentSceneIndex >= 0 ? controller.currentSceneIndex : null,
        nextSceneId: controller.nextSceneIndex >= 0 ? controller.nextSceneIndex : null,
        exportedSlideIndex: Number.isInteger(slide) && slide >= 0 ? slide : null,
        sceneCount: Array.isArray(script && script.events) ? script.events.length : null,
        originalSceneCount: Array.isArray(script && script.originalEvents) ? script.originalEvents.length : null,
        buildIndex: null,
        revision,
        canAdvance: ready && (initial || controller.nextSceneIndex !== -1),
        canGoTo: ready,
        automaticPending,
        queuedAction: !!controller.queuedUserAction,
        goToSemantics: 'restart-at-initial-state',
        refusalReason: script && !manual ? 'Only manual presentation mode is supported.' : null
      };
    }
  })});
})(UC)
""".strip().encode()


class LiveRuntimeUnsupported(ValueError):
    pass


def patch_player(player: bytes) -> bytes:
    """Instrument a known player without changing navigation or rendering."""
    if hashlib.sha256(player).hexdigest() != PLAYER_SHA256:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for live output.")
    if player.count(_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player observation hook is missing or ambiguous.")
    return player.replace(
        _ANCHOR,
        b"UC=new Eg," + _INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )

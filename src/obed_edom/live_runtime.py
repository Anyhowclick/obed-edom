"""Observation hook and Magic Move opacity patch for one explicitly supported Keynote HTML player."""

from __future__ import annotations

import hashlib

RUNTIME_VERSION = 2
PLAYER_SHA256 = "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354"
_ANCHOR = b"UC=new Eg,UC.displayManager.showWaitingIndicator()"

_MM_OPACITY_NODE = (
    b'__obedNodeOpacity(A){try{var B=A.initialState,g=null,C=0,Q=A.animations||[];for(var e=0;e<Q.length;e++)'
    b'for(var t=Q[e].property?[Q[e]]:Q[e].animations||[],i=0;i<t.length;i++)"opacity"===t[i].property?(g=t[i],C++)'
    b':"hidden"===t[i].property&&(C=2);var o=B.hidden||C>1?null:g?g.from.scalar===g.to.scalar&&"both"===g.fillMode'
    b'?g.to.scalar:null:B.opacity;return"number"==typeof o&&isFinite(o)?o:null}catch(E){return null}}'
    b"__obedChainOpacity(X,A){if(null===X)return null;var B=this.__obedNodeOpacity(A);"
    b"return null===B?null:(void 0===X?1:X)*B}"
)
_MM_OPACITY_REPLACEMENTS = (
    (
        b"textureInfoFromEffect(A,B,g,C,Q){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,"
        b"pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,A.textureId){",
        _MM_OPACITY_NODE
        + b"textureInfoFromEffect(A,B,g,C,Q,X){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,"
        b"pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,"
        b"e.obedOpacity=void 0===X?null:this.__obedChainOpacity(X,A),A.textureId){",
    ),
    (
        b"this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q)",
        b"this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q,this.__obedChainOpacity(X,A))",
    ),
    (
        b'd!==U&&(T=d+(U-d)*K),A.setGLFloat(T,"Opacity")',
        b'd!==U&&(T=d+(U-d)*K),null!=e.obedOpacity&&(T=e.obedOpacity),A.setGLFloat(T,"Opacity")',
    ),
    (
        b"var w=e.initialState.hidden?0:this.parentOpacity*e.initialState.opacity;",
        b"var w=e.initialState.hidden?0:null!=e.obedOpacity?e.obedOpacity:this.parentOpacity*e.initialState.opacity;",
    ),
)

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
      const events = script && Array.isArray(script.events) ? script.events : null;
      const next = events && events[controller.nextSceneIndex];
      const automaticPending = final && !!next && !!next.automaticPlay;
      const ready = manual && (initial || final) && !automaticPending &&
        !controller.queuedUserAction;
      let slide = controller.currentSlideIndex;
      if (script && (!Number.isInteger(slide) || slide < 0)) {
        slide = script.slideIndexFromSceneIndexLookup[controller.currentSceneIndex];
      }
      // Mirror the player's next-event index without truncating automatic runs at slide boundaries.
      let autoPlayRunLength = null, autoPlayRunKinds = null;
      if (events) {
        let start = -1;
        if (initial) start = controller.currentSceneIndex;
        else if (final) start = controller.nextSceneIndex;
        if (start === -1 && !final) {
          autoPlayRunLength = null;
        } else if (!Number.isInteger(start) || start < 0 || start >= events.length) {
          autoPlayRunLength = 0;
          autoPlayRunKinds = [];
        } else {
          autoPlayRunLength = 0;
          autoPlayRunKinds = [];
          for (let i = start; i < events.length; i++) {
            const event = events[i];
            if (!event || !event.automaticPlay) break;
            autoPlayRunLength += 1;
            const effects = Array.isArray(event.effects) ? event.effects : null;
            const first = effects && effects[0];
            autoPlayRunKinds.push(first && typeof first.name === 'string' ? first.name : null);
          }
        }
      }
      return {
        runtimeVersion: 2,
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
        slideNumberShowing: !!(controller.slideNumberController && controller.slideNumberController.isShowing),
        autoPlayRunLength,
        autoPlayRunKinds,
        goToSemantics: 'restart-at-initial-state',
        refusalReason: script && !manual ? 'Only manual presentation mode is supported.' : null
      };
    }
  })});
})(UC)
""".strip().encode()


class LiveRuntimeUnsupported(ValueError):
    pass


def patch_player(player: bytes, *, mm_opacity: bool = True) -> bytes:
    """Instrument a known player; with `mm_opacity`, draw Magic Move leaves at their authored chain opacity."""
    if hashlib.sha256(player).hexdigest() != PLAYER_SHA256:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for live output.")
    if player.count(_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player observation hook is missing or ambiguous.")
    patched = player.replace(
        _ANCHOR,
        b"UC=new Eg," + _INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )
    if not mm_opacity:
        return patched
    for before, after in _MM_OPACITY_REPLACEMENTS:
        if patched.count(before) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity anchor is missing or ambiguous.")
        patched = patched.replace(before, after)
        if patched.count(after) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity patch is ambiguous.")
    return patched

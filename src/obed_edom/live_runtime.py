"""Observation hook and Magic Move rendering fidelity patch for one explicitly supported Keynote HTML player."""

from __future__ import annotations

import hashlib

RUNTIME_VERSION = 2
MM_OPACITY_ENV = "OBED_LIVE_MM_OPACITY"
PLAYER_SHA256 = "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354"
_ANCHOR = b"UC=new Eg,UC.displayManager.showWaitingIndicator()"

_MM_OPACITY_NODE = (
    b'__obedNodeOpacity(A){try{var B=A.initialState,g=null,C=0,Q=A.animations||[];for(var e=0;e<Q.length;e++)'
    b'for(var t=Q[e].property?[Q[e]]:Q[e].animations||[],i=0;i<t.length;i++)"opacity"===t[i].property?(g=t[i],C++)'
    b':("hidden"===t[i].property||t[i].animations)&&(C=2);var o=B.hidden||C>1?null:g?'
    b'g.from.scalar===g.to.scalar&&"both"===g.fillMode?g.to.scalar:null:B.opacity;'
    b'return"number"==typeof o&&isFinite(o)?o:null}catch(E){return null}}'
    b"__obedChainOpacity(X,A){if(null===X)return null;var B=this.__obedNodeOpacity(A);"
    b"return null===B?null:(void 0===X?1:X)*B}"
)
_MM_HANDBACK_METHOD = (
    b"__obedHandbackTextures(A,B){try{var s=UC.script,c=UC.textureManager.slideCache,k=null;"
    b"for(var n in c)if(c[n]&&c[n].textureAssets===this.textureAssets){k=+n;break}if(null===k)return;"
    b"var d=k+1<s.slideList.length?k+1:s.loopSlideshow?0:-1,D=d<0?null:c[d],S=d<0?null:s.slides[s.slideList[d]];"
    b"if(!D||!D.textureAssets||!S||!S.events||!S.events.length)return;var L=[];"
    b"(function W(l,x,y){var t=l.initialState,a=t.anchorPoint,"
    b"X=x+Math.round(1e6*(t.position.pointX-a.pointX*t.width))/1e6,Y=y+Math.round(1e6*(t.position.pointY-a.pointY*t.height))/1e6;"
    b"l.texture&&!t.hidden&&L.push({t:l.texture,x:X,y:Y,w:t.width,h:t.height});for(var i=0;i<(l.layers||[]).length;i++)W(l.layers[i],X,Y)})"
    b"(S.events[0].baseLayer,0,0);"
    b"for(var g=0;g<B.length;g++){var e=B[g],J=e.animations&&e.animations[0]&&e.animations[0].animations;"
    b"if(e.toTextureId||!J||1!==e.initialState.scale)continue;var sx=1,sy=1,tx=0,ty=0,ok=!0;"
    b"for(var j=0;j<J.length;j++){var p=J[j],P=p.property;"
    b"\"transform.scale.x\"===P?sx=p.to.scalar:\"transform.scale.y\"===P?sy=p.to.scalar:"
    b"\"transform.translation\"===P?(tx=p.to.pointX,ty=p.to.pointY):\"opacity\"===P&&p.from.scalar===p.to.scalar||(ok=!1)}"
    b"1===sx&&1===sy&&(ok=!1);"
    b"var W=e.initialState.anchorPoint,ax=W.pointX*e.width,ay=W.pointY*e.height,"
    b"qx=e.offset.pointX+tx+ax-sx*ax,qy=e.offset.pointY+ty+ay-sy*ay,qw=sx*e.width,qh=sy*e.height,"
    b"m=L.filter(function(r){return Math.abs(r.x-qx)<=.01&&Math.abs(r.y-qy)<=.01&&Math.abs(r.w-qw)<=.01&&Math.abs(r.h-qh)<=.01});"
    b"ok&&1===m.length&&m[0].t!==e.textureId&&D.textureAssets[m[0].t]&&"
    b"(e.toTexture=R.createTexture(this.gl,D.textureAssets[m[0].t]),e.obedMix=!0)}}catch(E){}}"
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
    (
        b"Q&&setTimeout(this.handleAnimateEffectDidBegin.bind(this,Q),0)",
        b"Q&&this.handleAnimateEffectDidBegin(Q)",
    ),
    (
        b"B[g].toTexture=R.createTexture(this.gl,i)}}return B}",
        b"B[g].toTexture=R.createTexture(this.gl,i)}}"
        b'return"apple:magic-move-implied-motion-path"===A.name&&this.__obedHandbackTextures(A,B),B}'
        + _MM_HANDBACK_METHOD,
    ),
    (
        b'case"contents":C=e.toTexture}}var T=',
        b'case"contents":C=e.toTexture}}e.obedMix&&(C=e.toTexture);var T=',
    ),
    (
        b"this.textureManager.loadScene(B)}unloadTextures(){",
        b"this.textureManager.loadScene(B),B+1<A.numScenes&&this.textureManager.loadScene(B+1)}unloadTextures(){",
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
    """Instrument a known player; with `mm_opacity`, draw Magic Move leaves at their authored chain opacity,
    hide each swapped DOM node in the same task that queues its first GL draw, and crossfade each scaled leaf
    without a `contents` animation to its matched next-slide texture so the settled frame lands on the DOM."""
    if hashlib.sha256(player).hexdigest() != PLAYER_SHA256:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for live output.")
    if player.count(_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player observation hook is missing or ambiguous.")
    patched = player.replace(
        _ANCHOR,
        b"UC=new Eg," + _INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )
    return _apply_mm_opacity(patched) if mm_opacity else patched


def patch_rendering(player: bytes) -> bytes:
    """Apply only the Magic Move rendering fidelity patch of `patch_player`, without the observation hook."""
    if hashlib.sha256(player).hexdigest() != PLAYER_SHA256:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for the preview opacity patch.")
    return _apply_mm_opacity(player)


def _apply_mm_opacity(player: bytes) -> bytes:
    for before, after in _MM_OPACITY_REPLACEMENTS:
        if player.count(before) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity anchor is missing or ambiguous.")
        player = player.replace(before, after)
        if player.count(after) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity patch is ambiguous.")
    return player

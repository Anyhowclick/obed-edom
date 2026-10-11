"""Observation hook and rendering fidelity patch for explicitly supported Keynote HTML players."""

from __future__ import annotations

import hashlib

RUNTIME_VERSION = 2
MM_OPACITY_ENV = "OBED_LIVE_MM_OPACITY"
# Stock player sha256 -> sha256 of its patch_player output with rendering fidelity on, off, and its patch_rendering output.
# 17c0c938 is e9b2fad4 plus two `,isEvalSupported:!1` PDF.js options, outside every anchor.
SUPPORTED_PLAYERS = {
    "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354": (
        "49d56adcfafe90edd1584da2092af78810b5228bfb8dbec61e8b118a00a0c6f3",
        "7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de",
        "117fd39db497a696e71bc9a598287b77aed7021939f0a38c8ae21a096b203df8",
    ),
    "17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91": (
        "7a5e315bae89da6050e21efd0d03fac6537158a5d70fd5ae4c390a8ab1137a68",
        "4f9fbffd95e4649543142b2e95586babd9d75f0a0d9a4974e21d6f33c8389e3b",
        "52d7edb5ff73b2092781a1f32a4ecb6dc0c22247bc2d9d534df5d8115ec51083",
    ),
}
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
_FREEZE_QUALIFIED_TUPLES = b'["bt709/bt709/bt709/false"]'
_FREEZE_TONE_LUT = (
    b"function(){for(var T=new Uint8ClampedArray(256),i=0,l;i<256;i++)l=Math.pow(i/255,1.961),"
    b"T[i]=255*(l<=.0031308?12.92*l:1.055*Math.pow(l,1/2.4)-.055);return T}()"
)
_DISSOLVE_METHODS = (
    b"__obedShape(C){try{var b=C.baseLayer,K=b.layers,k=1===K.length?K[0]:null,P=k&&k.layers,i=P&&2===P.length?P[0]:null,"
    b'o=i&&P[1],x=o&&o.animations&&1===o.animations.length?o.animations[0]:null,u="none"===C.name,f=function(l,'
    b"c){var s=l.initialState,a=s.affineTransform,t=s.sublayerTransform;return!l.isVideoLayer&&!l.isWebVideoPosterLayer&&"
    b"null==l.objectID&&!s.transform&&0===s.rotation&&1===s.scale&&1===s.opacity&&!s.hidden&&!!a&&6===a.length&&"
    b"a.every(function(v,j){return v===(j%3?0:1)})&&(c||!!t&&16===t.length&&t.every(function(v,j){return v===(j%5?0:1)}))};"
    b'return"transition"!==C.type||!u&&"apple:dissolve"!==C.name||!x||b.texture||k.texture||(b.animations||[]).length||'
    b"(k.animations||[]).length||!f(k,1)||!f(i)||!f(o)||!i.texture||!o.texture||(i.layers||[]).length||(o.layers||"
    b'[]).length||(i.animations||[]).length||x.keyTimes||x.path||x.animations||(u?"hidden"!==x.property||'
    b'!1!==x.from.scalar||!0!==x.to.scalar||.001!==x.duration||0!==x.beginTime||"both"!==x.fillMode||x.timingFunction||'
    b'x.timeOffset||x.repeatCount||x.autoreverses:"opacity"!==x.property||1!==x.from.scalar||0!==x.to.scalar)?null:[b,k,i,o,'
    b"x,u]}catch(E){return null}}__obedDissolveLayer(C){var b=C.baseLayer,n=0,z=this.__obedShape(C);if(!z)return b;"
    b"try{var k=z[1],i=z[2],o=z[3],x=z[4],u=z[5];if(!u){var S=UC.animationManager.styleSheet,"
    b'L=function(j){return"#layer"+(TB+j)};S.insertRule(L(1)+"{isolation:isolate}",0),n=1,'
    b'S.insertRule(L(2)+","+L(3)+"{mix-blend-mode:plus-lighter}",0),n=2;if("isolate"!==S.cssRules[1].style.isolation||'
    b'"plus-lighter"!==S.cssRules[0].style.mixBlendMode)throw 0}return C.obedDissolve=u?"cut":"dissolve",Object.assign({},b,'
    b"{layers:[Object.assign({},k,{layers:[Object.assign({},i,{initialState:Object.assign({},i.initialState,u?{hidden:!0}"
    b":{opacity:0}),animations:[Object.assign({},x,{from:{scalar:u?!0:0},to:{scalar:u?!1:1}})]}),o]})]})}catch(E){return n&&"
    b"(TB+=4),b}}__obedFreezeTake(U,A){U.__obedFrozen=null;var t0=performance.now();try{var e=U.script.events[A],y=e&&"
    b'e.effects&&e.effects[0],G=document.getElementById("stage");if(!y||!G||!this.__obedShape(y))return;'
    b'var R=document.getElementById("layer"+U.playbackController.kpfEvent.baseLayer.layerId).getBoundingClientRect(),'
    b'kx=U.script.slideWidth/R.width,ky=U.script.slideHeight/R.height,H=[],N=document.getElementsByTagName("*"),Q='
    + _FREEZE_QUALIFIED_TUPLES
    + b",cs=function(n){return getComputedStyle(n)},dv=function(s,d){return(s||d)===d},"
    b'bd=function(z){return"none"!==z.borderTopStyle||"none"!==z.borderRightStyle||"none"!==z.borderBottomStyle||'
    b'"none"!==z.borderLeftStyle},rd=function(z){return"0px"!==z.borderTopLeftRadius||"0px"!==z.borderTopRightRadius||'
    b'"0px"!==z.borderBottomLeftRadius||"0px"!==z.borderBottomRightRadius},'
    b'deco=function(z){return!/rgba\\(0, 0, 0, 0\\)|transparent/.test(z.backgroundColor)||"none"!==z.backgroundImage||'
    b'"none"!==z.boxShadow||bd(z)||"none"!==z.outlineStyle||!dv(z.backdropFilter,"none")},own=function(n,'
    b"z){return/^(CANVAS|VIDEO|IMG|SVG|IFRAME|OBJECT|EMBED|INPUT|TEXTAREA|SELECT|BUTTON)$/i.test(n.tagName)||deco(z)||"
    b"Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\\S/.test(c.data)})},"
    b'bm=function(z){return!deco(z)&&!rd(z)&&"0px"===z.paddingTop&&"0px"===z.paddingRight&&"0px"===z.paddingBottom&&'
    b'"0px"===z.paddingLeft&&dv(z.objectViewBox,"none")&&dv(z.imageRendering,"auto")},al=function(a){var w=cs(a),s=a===G,'
    b'u=!s&&a.contains(G),m=w.transform,M;if("block"!==w.display||!dv(w.contain,"none")||!dv(w.contentVisibility,'
    b'"visible")||"none"!==w.filter||!dv(w.backdropFilter,"none")||"normal"!==w.mixBlendMode||!dv(w.isolation,"auto")||'
    b'"none"!==w.clipPath||!dv(w.maskImage,"none")||!dv(w.clip,"auto")||"auto"!==w.zIndex||!dv(w.translate,"none")||'
    b'!dv(w.rotate,"none")||!dv(w.scale,"none")||!dv(w.offsetPath,"none")||!dv(w.willChange,"auto")||!dv(w.zoom,"1")||'
    b'"none"!==w.outlineStyle||w.overflowX!==w.overflowY||"visible"!==w.overflowX&&!("clip"===w.overflowX&&'
    b'/^(VIDEO|CANVAS)$/.test(a.tagName))&&("hidden"!==w.overflowX||rd(w)||bd(w)))return!1;'
    b'if(u)return("static"===w.position||"absolute"===w.position)&&"none"===m;if("absolute"!==w.position||!dv(w.perspective,'
    b'"none")||!dv(w.backfaceVisibility,"visible")||(s?"preserve-3d"!==w.transformStyle&&'
    b'"flat"!==w.transformStyle:"flat"!==w.transformStyle&&("preserve-3d"!==w.transformStyle||"none"!==m)||'
    b'"visible"!==w.visibility))return!1;if("none"===m)return!0;M=new DOMMatrix(m);return M.is2D&&!M.b&&!M.c&&M.a>0&&M.d>0&&'
    b"Math.abs(M.a/M.d-1)<=.001},vp=function(a){var h=document.documentElement;return a===h||a===document.body&&"
    b'"visible"===cs(h).overflowX},pc=function(n){var t=n.tagName,w,b,f;'
    b"if(/^(HEAD|SCRIPT|STYLE|LINK|META|TITLE|BASE|TEMPLATE|NOSCRIPT)$/i.test(t))return!0;w=cs(n);"
    b'if("contents"===w.display)return!1;if(!n.checkVisibility({opacityProperty:!0}))return!0;b=getComputedStyle(n,'
    b'"::before").content;f=getComputedStyle(n,"::after").content;if(!/^(normal|none)$/.test(b||"none")||'
    b'!/^(normal|none)$/.test(f||"none")||!/^(normal|none)$/.test(w.content||"normal")||"list-item"===w.display||'
    b"Array.prototype.some.call(n.childNodes,function(c){return 3===c.nodeType&&/\\S/.test(c.data)}))return!1;"
    b'if("visible"!==w.visibility)return!0;if(!/^(HTML|BODY|DIV|CANVAS|VIDEO)$/.test(t)||/^(CANVAS|VIDEO)$/.test(t)&&'
    b'("50% 50%"!==w.objectPosition||!dv(w.objectViewBox,"none")||!/^(fill|contain)$/.test(w.objectFit)))return!1;'
    b'return"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle&&'
    b'dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&dv(w.columnRuleStyle,"none")},L=UC.__obedLut||'
    b"(UC.__obedLut="
    + _FREEZE_TONE_LUT
    + b");if(!(R.width>0&&R.height>0)||!Array.prototype.every.call(N,pc))return;var ad=[];"
    b'Array.prototype.slice.call(document.querySelectorAll("video")).reverse().forEach(function(v){try{if(!G.contains(v)||'
    b"v.readyState<2||!v.videoWidth||!v.videoHeight||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;"
    b'var z=cs(v),fit=z.objectFit,K;if(!bm(z)||"50% 50%"!==z.objectPosition||"fill"!==fit&&"contain"!==fit)return;'
    b'try{var vf=new VideoFrame(v),cc=vf.colorSpace;K=[cc.primaries,cc.transfer,cc.matrix,cc.fullRange].join("/");'
    b"vf.close()}catch(E){return}if(Q.indexOf(K)<0)return;var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,"
    b"r.bottom],a,q,w,b;for(a=v,q=1;a;a=a.parentElement){if(!al(a))return;w=cs(a);q*=+w.opacity;if(a!==v&&"
    b'"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)){b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}'
    b":a.getBoundingClientRect();c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],"
    b'b.bottom)]}}if(q<.999)return;var vw=v.videoWidth,vh=v.videoHeight,f="fill"===fit?0:Math.min(r.width/vw,r.height/vh),'
    b"cw=f?vw*f:r.width,ch2=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch2)/2,sx=vw/cw,sy=vh/ch2;"
    b"if(Math.abs(sx/sy-1)>.001)return;c=[Math.max(c[0],cx),Math.max(c[1],cy),Math.min(c[2],cx+cw),Math.min(c[3],cy+ch2)];"
    b"if(c[2]-c[0]<1||c[3]-c[1]<1)return;for(var I=Array.prototype.indexOf.call(N,v),i=0,n,o,P,T;i<N.length;i++){n=N[i];"
    b"if(i===I||n.contains(v))continue;o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||"
    b"o.top>=c[3]||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;"
    b"for(P=n.parentElement;!P.contains(v);P=P.parentElement);if(P===G||!G.contains(P))return;for(T=n,a=1;T!==P;"
    b'T=T.parentElement){w=cs(T);if(!al(T)||i>I&&T!==n&&"visible"!==w.overflowX)return;a*=+w.opacity;if(T!==n&&'
    b'+w.opacity<1&&Array.prototype.some.call(T.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))a=0}'
    b'if(i<I)continue;if("VIDEO"===n.tagName){if(ad.indexOf(n)<0)return;continue}w=cs(n);if("CANVAS"!==n.tagName||!bm(w)||'
    b'"fill"!==w.objectFit||!a)return;Y.push([n,o,a])}var x=document.createElement("canvas");x.width=vw,x.height=vh;'
    b'var g=x.getContext("2d");g.drawImage(v,0,0);var X0=Math.floor((c[0]-cx)*sx),Y0=Math.floor((c[1]-cy)*sy),'
    b"D=g.getImageData(X0,Y0,Math.max(1,Math.min(vw,Math.ceil((c[2]-cx)*sx))-X0),Math.max(1,Math.min(vh,"
    b"Math.ceil((c[3]-cy)*sy))-Y0)),d=D.data,j;for(j=0;j<d.length;j+=4){if(d[j+3]<255)return;d[j]=L[d[j]],d[j+1]=L[d[j+1]],"
    b"d[j+2]=L[d[j+2]]}g.putImageData(D,X0,Y0);Y.forEach(function(y){g.globalAlpha=y[2],g.drawImage(y[0],(y[1].left-cx)*sx,"
    b'(y[1].top-cy)*sy,y[1].width*sx,y[1].height*sy)}),g.globalAlpha=1;var h=document.createElement("div"),s=h.style,'
    b't=x.style;s.position=t.position="absolute",s.overflow="hidden",s.left=(c[0]-R.left)*kx+"px",'
    b's.top=(c[1]-R.top)*ky+"px",s.width=(c[2]-c[0])*kx+"px",s.height=(c[3]-c[1])*ky+"px",t.left=(cx-c[0])*kx+"px",'
    b't.top=(cy-c[1])*ky+"px",t.width=cw*kx+"px",t.height=ch2*ky+"px",h.appendChild(x),H.push(h),ad.push(v)}catch(E){}}),'
    b"H.length&&(U.__obedFrozen={scene:A,holders:H.reverse()})}catch(E){U.__obedFrozen=null}"
    b"finally{window.__obedTakeMs=U.__obedTakeMs=performance.now()-t0}}__obedFreeze(C,A){var F=UC.__obedFrozen;"
    b"UC.__obedFrozen=null;if(C.obedDissolve&&F&&F.scene===this.sceneIndex)try{var O=A.layers[0].layers[1],"
    b'W=document.getElementById("layer"+O.layerId+("cut"===C.obedDissolve?"":"-opacity"));if(!W)return;'
    b"var Q=document.createDocumentFragment();F.holders.forEach(function(h){Q.appendChild(h)}),W.appendChild(Q)}catch(E){}}"
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
        b"this.textureManager.loadScene(B);var M=A.events[B],N=M&&M.effects&&M.effects[0];"
        b'N&&"apple:magic-move-implied-motion-path"===N.name&&B+1<A.numScenes&&this.textureManager.loadScene(B+1)}'
        b"unloadTextures(){",
    ),
    (b"return B}renderEffects(A){", b"return B}" + _DISSOLVE_METHODS + b"renderEffects(A){"),
    (
        b"const A=new VB(C.baseLayer,{name:C.name,type:C.type,objectID:e});",
        b"const A=new VB(this.__obedDissolveLayer(C),{name:C.name,type:C.type,objectID:e});",
    ),
    (
        b"this.cssRenderer.draw(a),a.removeChild(w)}",
        b"this.cssRenderer.draw(a),this.__obedFreeze(C,A),a.removeChild(w)}",
    ),
    (
        b"jumpToScene_partFour(A,B){if(this.displayScene(A),",
        b"jumpToScene_partFour(A,B){if(B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),",
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
    """Instrument a known player; with `mm_opacity` (rendering fidelity), draw Magic Move leaves at their authored chain
    opacity, hide each swapped DOM node in the same task that queues its first GL draw, crossfade each scaled leaf
    without a `contents` animation to its matched next-slide texture so the settled frame lands on the DOM, cross-fade
    Dissolves and swap cuts without showing both slides, and freeze admitted outgoing movies into the transition."""
    pins = SUPPORTED_PLAYERS.get(hashlib.sha256(player).hexdigest())
    if pins is None:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for live output.")
    if player.count(_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player observation hook is missing or ambiguous.")
    patched = player.replace(
        _ANCHOR,
        b"UC=new Eg," + _INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )
    return _pinned(_apply_mm_opacity(patched), pins[0]) if mm_opacity else _pinned(patched, pins[1])


def patch_rendering(player: bytes) -> bytes:
    """Apply only the rendering fidelity patch of `patch_player`, without the observation hook."""
    pins = SUPPORTED_PLAYERS.get(hashlib.sha256(player).hexdigest())
    if pins is None:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for the preview opacity patch.")
    return _pinned(_apply_mm_opacity(player), pins[2])


def _pinned(patched: bytes, expected: str) -> bytes:
    if hashlib.sha256(patched).hexdigest() != expected:
        raise LiveRuntimeUnsupported("The patched player does not match its pinned digest.")
    return patched


def _apply_mm_opacity(player: bytes) -> bytes:
    for before, after in _MM_OPACITY_REPLACEMENTS:
        if player.count(before) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity anchor is missing or ambiguous.")
        player = player.replace(before, after)
        if player.count(after) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity patch is ambiguous.")
    return player

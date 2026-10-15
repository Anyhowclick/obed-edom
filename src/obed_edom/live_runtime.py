"""Observation hook and rendering fidelity patch for explicitly supported Keynote HTML players."""

from __future__ import annotations

import hashlib

RUNTIME_VERSION = 2
MM_OPACITY_ENV = "OBED_LIVE_MM_OPACITY"
# Stock player sha256 -> sha256 of its patch_player output with rendering fidelity on, off, and its patch_rendering output.
# 17c0c938 is e9b2fad4 plus two `,isEvalSupported:!1` PDF.js options, outside every anchor.
SUPPORTED_PLAYERS = {
    "e9b2fad41bb6f257aa04c31229aa0d7d80ee6a3d7c400c8e33eac0728428f354": (
        "0906c8a0bab229b68e122d6fec884624567c2afe65b7086181f60f612f7d2ef3",
        "aa7d69241c2c4b7b5adbdbca19af36f2ec73bf9fad48eb2c3f6a2aeda66f2243",
        "573d292b39e2d33096dd2e1684f1ea1010496dd382a81f53343685ae3c14df00",
    ),
    "17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91": (
        "896d4007dca04c114557d0bf436f4fe518377b2269b9c49ac473709733f27b98",
        "322d7419c4c3814e67b169ae69c291f671c16e1807ec21760b5160514976ceee",
        "ecff39e1444a0d874ecf7df140f53d3214c1eca0e7fb672911fe82ae1abed071",
    ),
}
_ANCHOR = b"UC=new Eg,UC.displayManager.showWaitingIndicator()"

_MM_OPACITY_NODE = (
    b'__obedNodeOpacity(A){try{var B=A.initialState,g=null,C=0,Q=A.animations||[];for(var e=0;e<Q.length;e++)'
    b'for(var t=Q[e].property?[Q[e]]:Q[e].animations||[],i=0;i<t.length;i++)"opacity"===t[i].property?(g=t[i],C++)'
    b':("hidden"===t[i].property||t[i].animations)&&(C=2);var o=B.hidden||C>1?null:g?'
    b'g.from.scalar===g.to.scalar&&"both"===g.fillMode?g.to.scalar:null:B.opacity;'
    b'return"number"==typeof o&&isFinite(o)?o:null}catch(E){return null}}'
    b'__obedFade(A,C){try{var B=A.initialState,g=A.animations||[],Q=null,e=null,t=0,i=0;'
    b'if(1!==g.length||!Array.isArray(g[0].animations))return!1;for(var o=g[0].animations,E=0;E<o.length;E++){'
    b'var w=o[E];if(w.animations)return!1;"opacity"===w.property?(Q=w,t++):"hidden"===w.property&&(e=w,i++)}'
    b'if(1!==t||i>1)return!1;var a=Q.from.scalar,I=Q.to.scalar,s=Q.fillMode;if("number"!=typeof a||'
    b'"number"!=typeof I||!isFinite(a)||!isFinite(I)||a<0||a>1||I<0||I>1||a===I||'
    b'"both"!==s&&"forwards"!==s||"forwards"===s&&B.opacity!==a||C===1e3*Q.duration&&0!==Q.beginTime)return!1;'
    b'if(!1===B.hidden)return null===e||0===I&&null!==e&&!0===e.from.scalar&&!0===e.to.scalar&&'
    b'"forwards"===e.fillMode&&e.beginTime+1e-9>=Q.beginTime+Q.duration;if(!0===B.hidden)return 0===a&&'
    b'null!==e&&!1===e.from.scalar&&!1===e.to.scalar&&"forwards"===e.fillMode&&'
    b'Math.abs(e.beginTime-Q.beginTime)<=1e-9&&Math.abs(e.duration-Q.duration)<=1e-9;return!1}catch(n){return!1}}'
    b"__obedChainOpacity(X,A){if(null===X)return null;if(0===X)return 0;var B=this.__obedNodeOpacity(A);"
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
_CONTINUITY_TAKE_ANCHOR = b"jumpToScene_partFour(A,B){if(this.displayScene(A),"
_CONTINUITY_TAKE_CALL = (
    b'B&&function(){try{var M=window.__OBED_MM_FEED__;M&&"function"==typeof M.take&&M.take(this,A)}'
    b'catch(E){}}.call(this),'
)
_CONTINUITY_TAKE_REPLACEMENT = b"jumpToScene_partFour(A,B){if(" + _CONTINUITY_TAKE_CALL + b"this.displayScene(A),"
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
    + b",pl=window.__obedPlacement,cs=function(n){return getComputedStyle(n)},dv=function(s,d){return(s||d)===d},"
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
    b'"visible"!==w.visibility))return!1;if(!s&&!(/^-?\\d+px$/.test(w.left)&&/^-?\\d+px$/.test(w.top)))return!1;'
    b'if("none"===m)return!0;M=new DOMMatrix(m);return M.is2D&&!M.b&&!M.c&&1===M.a'
    b"&&1===M.d},xo=function(n){for(var a=n,w,r;!a.contains(G);a=a.parentElement){w=cs(a);"
    b'if("fixed"===getComputedStyle(a,"::before").position||"fixed"===getComputedStyle(a,"::after").position)return!1;'
    b'if("div"===a.localName&&"http://www.w3.org/1999/xhtml"===a.namespaceURI&&"hidden"===w.overflowX'
    b'&&"hidden"===w.overflowY&&"static"!==w.position&&/^(block|flow-root|flex|grid)$/.test(w.display)'
    b'&&"none"===w.boxShadow&&"none"===w.filter&&dv(w.backdropFilter,"none")&&"none"===w.outlineStyle'
    b'&&dv(w.borderImageSource,"none")&&dv(w.webkitBoxReflect,"none")&&(r=a.getBoundingClientRect(),r.right<=V[0]'
    b'||r.left>=V[2]||r.bottom<=V[1]||r.top>=V[3]))return!0;if("fixed"===w.position)return!1}return!1},'
    b'vp=function(a){var h=document.documentElement;return a===h||a===document.body&&"visible"===cs(h).overflowX},'
    b'pc=function(n){var t=n.tagName,w=cs(n),b,f;if("contents"===w.display)return!1;'
    b'if(!n.checkVisibility({opacityProperty:!0}))return!0;b=getComputedStyle(n,"::before").content;f=getComputedStyle(n,'
    b'"::after").content;if(!/^(normal|none)$/.test(b||"none")||!/^(normal|none)$/.test(f||"none")'
    b'||!/^(normal|none)$/.test(w.content||"normal")||"list-item"===w.display||Array.prototype.some.call(n.childNodes,'
    b'function(c){return 3===c.nodeType&&/\\S/.test(c.data)})||"none"!==w.filter||!dv(w.backdropFilter,"none")'
    b'||!dv(w.webkitBoxReflect,"none"))return!1;if("visible"!==w.visibility)return!0;'
    b'if(!/^(HTML|BODY|DIV|CANVAS|VIDEO)$/.test(t)||/^(CANVAS|VIDEO)$/.test(t)&&("50% 50%"!==w.objectPosition'
    b'||!dv(w.objectViewBox,"none")||!/^(fill|contain)$/.test(w.objectFit)))return!1;return"none"===w.boxShadow'
    b'&&"none"===w.outlineStyle&&dv(w.borderImageSource,"none")&&dv(w.columnRuleStyle,"none")};for(var V=[0,0,innerWidth,'
    b'innerHeight],a=G,w,b;a;a=a.parentElement)w=cs(a),"visible"!==w.overflowX&&(vp(a)||"static"!==w.position)'
    b"&&(b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect(),V=[Math.max(V[0],b.left),"
    b"Math.max(V[1],b.top),Math.min(V[2],b.right),Math.min(V[3],b.bottom)]);if(!(R.width>0&&R.height>0)"
    b'||!("snap"===pl&&[1,1.5,2].indexOf(devicePixelRatio)>=0||"frac"===pl&&1===devicePixelRatio&&'
    b'Number.isInteger(R.left)&&Number.isInteger(R.top))||1!==kx||1!==ky||document.querySelector(":modal,:popover-open,'
    b':fullscreen")||!Array.prototype.every.call(N,function(n){return!n.shadowRoot&&(pc(n)||!G.contains(n)'
    b'&&!n.contains(G)&&xo(n))}))return;var ad=[];Array.prototype.slice.call(document.querySelectorAll("video")).reverse('
    b").forEach(function(v){try{if(!G.contains(v)||v.readyState<2||!v.videoWidth||!v.videoHeight"
    b"||!v.checkVisibility({opacityProperty:!0,visibilityProperty:!0}))return;var z=cs(v),fit=z.objectFit,K;if(!bm(z)"
    b'||"50% 50%"!==z.objectPosition||"fill"!==fit&&"contain"!==fit)return;try{var vf=new VideoFrame(v),cc=vf.colorSpace;'
    b'K=[cc.primaries,cc.transfer,cc.matrix,cc.fullRange].join("/");vf.close()}catch(E){return}if(Q.indexOf(K)<0)return;'
    b"var Y=[],r=v.getBoundingClientRect(),c=[r.left,r.top,r.right,r.bottom],a,q,w,b;for(a=v,q=1;a;"
    b'a=a.parentElement){if(!al(a))return;w=cs(a);q*=+w.opacity;if(a!==v&&"visible"!==w.overflowX&&(vp(a)'
    b'||"static"!==w.position)){b=vp(a)?{left:0,top:0,right:innerWidth,bottom:innerHeight}:a.getBoundingClientRect();'
    b"c=[Math.max(c[0],b.left),Math.max(c[1],b.top),Math.min(c[2],b.right),Math.min(c[3],b.bottom)]}}if(q<.999)return;"
    b'var vw=v.videoWidth,vh=v.videoHeight,f="fill"===fit?0:Math.min(r.width/vw,r.height/vh),cw=f?vw*f:r.width,'
    b"ch2=f?vh*f:r.height,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch2)/2;c=[Math.max(c[0],cx),Math.max(c[1],cy),"
    b"Math.min(c[2],cx+cw),Math.min(c[3],cy+ch2)];if(c[2]-c[0]<1||c[3]-c[1]<1)return;"
    b"for(var I=Array.prototype.indexOf.call(N,v),i=0,n,o,P,T;i<N.length;i++){n=N[i];if(i===I||n.contains(v))continue;"
    b"o=n.getBoundingClientRect();if(o.right<=c[0]||o.left>=c[2]||o.bottom<=c[1]||o.top>=c[3]"
    b"||!n.checkVisibility({opacityProperty:!0,visibilityProperty:!0})||!own(n,cs(n)))continue;for(P=n.parentElement;"
    b"!P.contains(v);P=P.parentElement);if(P===G||!G.contains(P))return;for(T=n,a=1;T!==P;T=T.parentElement){w=cs(T);"
    b'if(!al(T)||i>I&&T!==n&&"visible"!==w.overflowX)return;a*=+w.opacity;if(T!==n&&+w.opacity<1'
    b'&&Array.prototype.some.call(T.getElementsByTagName("*"),function(m){return m!==n&&own(m,cs(m))}))a=0}'
    b'if(i<I)continue;if("VIDEO"===n.tagName){if(ad.indexOf(n)<0)return;continue}w=cs(n);if("CANVAS"!==n.tagName||!bm(w)'
    b'||"fill"!==w.objectFit||!a)return;Y.push([n,o,a])}var p=devicePixelRatio||1,sn=function(z,e,'
    b"k){return Math.round((z-e)*k*p)/p},"
    b"u0=sn(cx,R.left,kx),v0=sn(cy,R.top,ky),u1=sn(cx+cw,R.left,kx),v1=sn(cy+ch2,R.top,"
    b"ky),a0=sn(c[0],R.left,kx),b0=sn(c[1],R.top,ky),a1=sn(c[2],R.left,kx),b1=sn(c[3],R.top,ky),"
    b"ww=Math.round((a1-a0)/kx*p),hh=Math.round((b1-b0)/ky*p),dx=(u0-a0)/kx*p,dy=(v0-b0)/ky*p,dw=(u1-u0)/kx*p,"
    b'dh=(v1-v0)/ky*p,x,g,d,j;if(ww<1||hh<1)return;x=document.createElement("canvas");x.width=ww,x.height=hh;'
    b'g=x.getContext("2d");g.drawImage(v,dx,dy,dw,dh);if("frac"===pl){var fx=dx+(r.left-R.left)'
    b'+Math.round(cx-r.left)-u0,fy=dy+(r.top-R.top)+Math.round(cy-r.top)-v0,fw=Math.round(cw),'
    b'fh=Math.round(ch2);if(fx>.5||fy>.5||fx+fw<ww-.5||fy+fh<hh-.5)return;g.drawImage(v,fx,fy,fw,fh)}'
    b'for(d=g.getImageData(0,0,ww,hh).data,j=3;j<d.length;j+=4)if(d[j]<255)return;if("frac"===pl){var ex=[],'
    b'ey=[],ei,ej;for(ei=0;ei<ww;ei++)if(ei<fx||ei+1>fx+fw)ex.push(ei);for(ei=0;ei<hh;ei++)if(ei<fy||'
    b'ei+1>fy+fh)ey.push(ei);var sx=ex.map(function(e){return Math.max(0,Math.min(vw-1,(e+.5-fx)*vw/fw-.5))}),'
    b'sy=ey.map(function(e){return Math.max(0,Math.min(vh-1,(e+.5-fy)*vh/fh-.5))});for(ei=0;ei<ey.length;'
    b'ei++)g.drawImage(v,0,sy[ei],vw,1,fx,ey[ei],fw,1);for(ei=0;ei<ex.length;ei++)g.drawImage(v,sx[ei],0,1,'
    b'vh,ex[ei],fy,1,fh);for(ei=0;ei<ex.length;ei++)for(ej=0;ej<ey.length;ej++)g.drawImage(v,sx[ei],sy[ej],'
    b'1,1,ex[ei],ey[ej],1,1)}Y.forEach(function(y){var l=sn(y[1].left,R.left,kx),m=sn(y[1].top,R.top,ky);'
    b"g.globalAlpha=y[2],g.drawImage(y[0],(l-a0)/kx*p,(m-b0)/ky*p,(sn(y[1].right,R.left,kx)-l)/kx*p,(sn(y[1].bottom,"
    b'R.top,ky)-m)/ky*p)}),g.globalAlpha=1;var h=document.createElement("div"),s=h.style,t=x.style;'
    b's.position=t.position="absolute",s.overflow="hidden",s.left=a0+"px",s.top=b0+"px",s.width=t.width=a1-a0+"px",'
    b's.height=t.height=b1-b0+"px",t.left=t.top="0px",h.appendChild(x),H.push(h),ad.push(v)}catch(E){}}),'
    b"H.length&&(U.__obedFrozen={scene:A,holders:H.reverse()})}catch(E){U.__obedFrozen=null}"
    b"finally{window.__obedTakeMs=U.__obedTakeMs=performance.now()-t0}}__obedFreeze(C,A){var F=UC.__obedFrozen;"
    b"UC.__obedFrozen=null;if(C.obedDissolve&&F&&F.scene===this.sceneIndex)try{var O=A.layers[0].layers[1],"
    b'W=document.getElementById("layer"+O.layerId+("cut"===C.obedDissolve?"":"-opacity"));if(!W)return;'
    b"var Q=document.createDocumentFragment();F.holders.forEach(function(h){Q.appendChild(h)}),W.appendChild(Q)}catch(E){}}"
)
_LINE_DRAW_METHODS = (
    b"__obedLineDrawNode(A,B,C){A.__obedLineCanvas=B,A.__obedLineWrapper=C}"
    b"__obedLineGeometry(A){var B=A[0].points[0],g={x:B[0],y:B[1]},C={x:g.x,y:g.y},Q=[{x:g.x,y:g.y,s:0}],"
    b"e=[],t=0,i=typeof Path2D!==\"undefined\"?new Path2D:null;i&&i.moveTo(g.x,g.y);for(var o=1;o<A.length;o++){var E=A[o],w=E.type;"
    b"if(\"AddLine\"===w){var a=E.points[0],I={x:a[0],y:a[1]},s=Math.hypot(I.x-C.x,I.y-C.y);"
    b"e.push({a:C,b:I,s:t,e:t+s}),t+=s,Q.push({x:I.x,y:I.y,s:t}),i&&i.lineTo(I.x,I.y),C=I}"
    b"else if(\"AddCurve\"===w){var n=E.points,G={x:n[0][0],y:n[0][1]},r={x:n[1][0],y:n[1][1]},D={x:n[2][0],y:n[2][1]},h=C;"
    b"i&&i.bezierCurveTo(G.x,G.y,r.x,r.y,D.x,D.y);for(var l=1;l<=48;l++){var Y=l/48,c=1-Y,M={x:c*c*c*C.x+3*c*c*Y*G.x+3*c*Y*Y*r.x+Y*Y*Y*D.x,y:c*c*c*C.y+3*c*c*Y*G.y+3*c*Y*Y*r.y+Y*Y*Y*D.y},F=Math.hypot(M.x-h.x,M.y-h.y);"
    b"e.push({a:h,b:M,s:t,e:t+F}),t+=F,Q.push({x:M.x,y:M.y,s:t}),h=M}C=D}"
    b"else if(\"CloseSubpath\"===w){var d=Math.hypot(g.x-C.x,g.y-C.y);d&&(e.push({a:C,b:g,s:t,e:t+d}),t+=d,Q.push({x:g.x,y:g.y,s:t})),i&&i.closePath(),C=g}}"
    b"return{path:i,points:Q,segs:e,length:t,start:g,end:C}}"
    b"__obedLineAt(A,B){B=Math.max(0,Math.min(A.length,B));for(var g=0;g<A.segs.length;g++){var C=A.segs[g];if(B<=C.e||g===A.segs.length-1){var Q=C.e>C.s?(B-C.s)/(C.e-C.s):0;return{x:C.a.x+(C.b.x-C.a.x)*Q,y:C.a.y+(C.b.y-C.a.y)*Q,a:Math.atan2(C.b.y-C.a.y,C.b.x-C.a.x)}}}return{x:A.start.x,y:A.start.y,a:0}}"
    b"__obedLineNear(A,B,g){for(var C=1/0,Q=0,e=0;e<A.segs.length;e++){var t=A.segs[e];if(B<Math.min(t.a.x,t.b.x)-C||B>Math.max(t.a.x,t.b.x)+C||g<Math.min(t.a.y,t.b.y)-C||g>Math.max(t.a.y,t.b.y)+C)continue;var i=t.b.x-t.a.x,o=t.b.y-t.a.y,E=i*i+o*o,w=E?Math.max(0,Math.min(1,((B-t.a.x)*i+(g-t.a.y)*o)/E)):0,a=t.a.x+w*i,I=t.a.y+w*o,s=Math.hypot(B-a,g-I);s<C&&(C=s,Q=t.s+w*(t.e-t.s))}return{d:C,s:Q}}"
    b"__obedLineInside(A,B,g){for(var C=!1,Q=0,e=A.length-1;Q<A.length;e=Q++){var t=A[Q],i=A[e];((t.y>g)!==(i.y>g))&&B<(i.x-t.x)*(g-t.y)/(i.y-t.y)+t.x&&(C=!C)}return C}"
    b"__obedLineHull(A){A.sort(function(a,b){return a.x===b.x?a.y-b.y:a.x-b.x});var B=function(a,b,c){return(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)},g=[];for(var C=0;C<A.length;C++){var Q=A[C];if(C&&Q.x===A[C-1].x&&Q.y===A[C-1].y)continue;for(;g.length>1&&B(g[g.length-2],g[g.length-1],Q)<=0;)g.pop();g.push(Q)}var e=g.length+1;for(C=A.length-2;C>=0;C--){Q=A[C];for(;g.length>=e&&B(g[g.length-2],g[g.length-1],Q)<=0;)g.pop();g.push(Q)}return g.pop(),g}"
    b"__obedLinePixels(A,B,g,C,Q,e,t){var i=[],o=new Uint8Array(g*C),E=new Float64Array(g*C);for(var w=0;w<C;w++)for(var a=0;a<g;a++){var I=w*g+a,s=4*I;if(!B[s+3])continue;var n=this.__obedLineNear(A,(a+.5)/Q,(w+.5)/Q);E[I]=n.s,n.d<=e?o[I]=1:i.push([a,w])}return!t&&i.length?null:{wings:i,band:o,arc:E}}"
    b"__obedLineDrawAdmit(A){try{if(!A||\"buildIn\"!==A.type||[\"com.apple.iWork.Keynote.LineDraw\",\"com.apple.iWork.Keynote.LineDrawForLine\"].indexOf(A.name)<0||!(A.duration>0&&isFinite(A.duration))||!A.kpfLayer)return;"
    b"var B=A.attributes||{},g=\"com.apple.iWork.Keynote.LineDrawForLine\"===A.name,C=g?[\"KNBuildCustomAttributesIncludeEndpoints\",\"direction\",\"sfx-action-acceleration\"]:[\"direction\",\"sfx-action-acceleration\"];"
    b"if(Object.keys(B).sort().join(\"|\")!==C.sort().join(\"|\")||3!==B[\"sfx-action-acceleration\"]||B.direction!==(g?51:31)||g&&!0!==B.KNBuildCustomAttributesIncludeEndpoints)return;"
    b"var Q=[],e=!0,t=function l(x){var s=x&&x.initialState,N=x&&x.layers||[];s&&!0!==s.masksToBounds||(e=!1),x&&!x.texturedRectangle&&x.animations&&x.animations.length&&(e=!1),x&&x.texturedRectangle&&Q.push(x),N.length||x&&x.texturedRectangle||(e=!1);for(var n=0;n<N.length;n++)l(N[n])};t(A.kpfLayer);if(!e||1!==Q.length)return;"
    b"var i=Q[0],o=i.initialState,E=i.texturedRectangle,w=E&&E.repGenerationDictionary,a=E&&E.shapePath,I=o&&o.contentsRect,s=function(v,n){return Array.isArray(v)&&v.length===n&&v.every(function(x,j){return x===(j%(n===6?3:5)?0:1)})};"
    b"if(!E||5!==E.textureType||!0!==E.isBackgroundTexture||!I||0!==I.x||0!==I.y||1!==I.width||1!==I.height||!s(o.affineTransform,6)||!s(o.sublayerTransform,16)||1!==o.scale||0!==o.rotation||!i.__obedLineCanvas||i.__obedLineCanvas.parentNode!==i.__obedLineWrapper)return;"
    b"var n=i.animations;if(!Array.isArray(n)||1!==n.length)return;var G=n[0],r=G.animations;if(!isFinite(G.beginTime)||G.beginTime<0||G.beginTime>1e-6||G.duration!==A.duration||0!==G.timeOffset||0!==G.repeatCount||!1!==G.autoreverses||!Array.isArray(r)||2!==r.length)return;"
    b"var D=r.filter(function(x){return\"opacity\"===x.property}),h=r.filter(function(x){return\"hidden\"===x.property});if(1!==D.length||1!==h.length)return;var l=function(x){return 0===x.beginTime&&0===x.timeOffset&&0===x.repeatCount&&!1===x.autoreverses&&!1===x.additive&&null==x.keyTimes&&null==x.path&&!(x.animations&&x.animations.length)&&x.duration===G.duration};"
    b"if(!l(D[0])||0!==D[0].from.scalar||1!==D[0].to.scalar||\"EaseInEaseOut\"!==D[0].timingFunction||!l(h[0])||!1!==h[0].from.scalar||!1!==h[0].to.scalar)return;"
    b"if(!w||!Array.isArray(w.strokePattern)||w.strokePattern.length||!(w.strokeWidth>0&&isFinite(w.strokeWidth))||!a||!Array.isArray(a.elements)||a.elements.length<2)return;var Y=a.elements,c=Y.length,M=Y[0];if(\"MoveToPoint\"!==M.type||!M.points||1!==M.points.length)return;"
    b"var F=!1;\"MoveToPoint\"===Y[c-1].type&&c--;c>1&&\"CloseSubpath\"===Y[c-1].type&&(F=!0,c--);for(var d=1;d<c;d++){var U=Y[d],K=\"AddLine\"===U.type?1:\"AddCurve\"===U.type?3:0;if(!K||!U.points||U.points.length!==K)return}if(c<2)return;"
    b"for(d=0;d<Y.length;d++)for(var k=Y[d].points||[],J=0;J<k.length;J++)if(!Array.isArray(k[J])||2!==k[J].length||!isFinite(k[J][0])||!isFinite(k[J][1]))return;"
    b"var H=w.headLineEndIdentifier,m=w.tailLineEndIdentifier,p=null!=H||null!=m;if(g?H!==\"filled arrow\"||null!=m||!p:null!=H||null!=m||p||null!=B.KNBuildCustomAttributesIncludeEndpoints)return;if(g&&F||!g&&!F)return;"
    b"var S=this.__obedLineGeometry(Y.slice(0,F?c+1:c)),R=0;for(d=1;d<S.points.length;d++)R+=S.points[d-1].x*S.points[d].y-S.points[d].x*S.points[d-1].y;if(!g&&!(R>0))return;A.__obedLineDraw={leaf:i,geo:S,stroke:w.strokeWidth,arrow:g}}catch(x){}}"
    b"__obedLineEase(A){var B=A,g;for(var C=0;C<8;C++){var Q=1-B,e=3*Q*Q*B*.42+3*Q*B*B*.58+B*B*B-A,t=3*Q*Q*.42+6*Q*B*(.58-.42)+3*B*B*(1-.58);if(Math.abs(e)<1e-7||!t)break;B=Math.max(0,Math.min(1,B-e/t))}g=1-B;return 3*g*B*B+B*B*B}"
    b"__obedLineRule(A){for(var B=0;B<document.styleSheets.length;B++)try{for(var g=document.styleSheets[B].cssRules,C=0;C<g.length;C++)if(g[C].name===A)return g[C]}catch(Q){}return null}"
    b"__obedLineMask(A,B,g){var C=A.reveal,Q=C.getContext(\"2d\"),e=A.mask,t=e.getContext(\"2d\");Q.globalCompositeOperation=\"source-over\",Q.clearRect(0,0,C.width,C.height),Q.drawImage(A.body,0,0),t.clearRect(0,0,e.width,e.height);if(g)t.fillStyle=\"#fff\",t.fillRect(0,0,e.width,e.height);else if(B>0){t.save(),t.scale(A.k,A.k),t.strokeStyle=\"#fff\",t.lineWidth=A.band*2,t.lineCap=\"butt\",t.lineJoin=\"round\",t.setLineDash([B,A.geo.length*2+1]),t.stroke(A.geo.path),t.beginPath(),t.arc(A.geo.start.x,A.geo.start.y,A.band,0,2*Math.PI),t.fillStyle=\"#fff\",t.fill(),t.restore()}Q.globalCompositeOperation=\"destination-in\",Q.drawImage(e,0,0),Q.globalCompositeOperation=\"source-over\"}"
    b"__obedLineFrame(A,B){if(A.done)return;var g=A.source;if(!g.isConnected)return void this.__obedLineDrawDrop(A);var C=A.animation.currentTime;if(null==C)return void(A.raf=requestAnimationFrame(A.frame));var Q=Math.max(0,Math.min(1,C/(1e3*A.effect.duration))),e=this.__obedLineEase(Q),t=e*A.geo.length,i=A.arrow?Math.max(t,A.d):t,o=A.arrow?i-A.d:i;this.__obedLineMask(A,o,o>=A.bodyEnd-1e-6);var E=A.overlay.getContext(\"2d\");E.clearRect(0,0,A.overlay.width,A.overlay.height),E.drawImage(A.reveal,-A.minX*A.k,-A.minY*A.k);if(A.arrow){var w=this.__obedLineAt(A.geo,i),a=w.a-A.endAngle;E.save(),E.setTransform(A.k,0,0,A.k,-A.minX*A.k,-A.minY*A.k),E.translate(w.x,w.y),E.rotate(a),E.translate(-A.geo.end.x,-A.geo.end.y),E.drawImage(A.head,0,0,A.width,A.height),E.restore()}A.overlay.__obedLineDraws=(A.overlay.__obedLineDraws||0)+1,A.raf=requestAnimationFrame(A.frame)}"
    b"__obedLineDrawDrop(A){if(!A||A.done)return;A.done=!0,A.raf&&cancelAnimationFrame(A.raf);try{A.animation.removeEventListener(\"finish\",A.finish),A.animation.removeEventListener(\"cancel\",A.cancel),A.animation.cancel()}catch(B){}A.overlay&&A.overlay.remove(),A.source&&(A.source.style.visibility=A.visibility);var g=A.effect;g&&delete g.__obedLineDraw;var C=A.leaf;C&&(delete C.__obedLineCanvas,delete C.__obedLineWrapper);this.__obedLineDrawStates&&(this.__obedLineDrawStates=this.__obedLineDrawStates.filter(function(x){return x!==A}))}"
    b"__obedLineDrawComplete(A){A&&A.__obedLineDraw&&A.__obedLineDraw.state&&this.__obedLineDrawDrop(A.__obedLineDraw.state)}"
    b"__obedLineDrawDestroy(){for(var A=(this.__obedLineDrawStates||[]).slice(),B=0;B<A.length;B++)this.__obedLineDrawDrop(A[B])}"
    b"__obedLineDrawApply(A,B,g,C){var Q=C&&C.__obedLineDraw;if(!Q||Q.leaf!==B)return;var e=null,t=null,i=null,o=null,d,U,K;try{var E=B.__obedLineCanvas,w=B.__obedLineWrapper;if(!E||!w||!E.isConnected||E.parentNode!==w||!Q.geo.path)throw 0;var a=E.width,I=E.height,s=B.bounds.width,n=B.bounds.height,G=a/s;if(!(a>0&&I>0&&s>0&&n>0&&isFinite(G)&&Math.abs(I/n-G)<1e-6))throw 0;"
    b"if(a*I>2e6||Q.geo.segs.length>5e3)throw 0;var r=E.getContext(\"2d\"),D=r.getImageData(0,0,a,I),h=D.data,l=Q.stroke/2+1.5,Y=[],P=this.__obedLinePixels(Q.geo,h,a,I,G,l,Q.arrow),v0=E.style.visibility;if(!P)throw 0;var c=P.wings,M=P.band,F=P.arc;"
    b"var H=null,m=null,p=null,S=null,R=0,u=Q.geo.end,f=Q.geo.segs[Q.geo.segs.length-1],Z=Math.hypot(f.b.x-f.a.x,f.b.y-f.a.y),Lx=(f.b.x-f.a.x)/Z,Ly=(f.b.y-f.a.y)/Z;"
    b"if(Q.arrow){if(c.length<3)throw 0;for(d=0;d<c.length;d++){U=c[d][0],K=c[d][1],Y.push({x:U/G,y:K/G},{x:(U+1)/G,y:K/G},{x:(U+1)/G,y:(K+1)/G},{x:U/G,y:(K+1)/G})}H=this.__obedLineHull(Y);if(H.length<3)throw 0;var x0=!1,ent=0,ex=0,inside=this.__obedLineInside(H,Q.geo.start.x,Q.geo.start.y);for(d=0;d<Q.geo.segs.length;d++){var q=Q.geo.segs[d],inside2=this.__obedLineInside(H,q.b.x,q.b.y);if(!inside&&inside2){ent++;var lo=0,hi=1;for(U=0;U<18;U++){var md=(lo+hi)/2,xx=q.a.x+(q.b.x-q.a.x)*md,yy=q.a.y+(q.b.y-q.a.y)*md;this.__obedLineInside(H,xx,yy)?hi=md:lo=md}R=q.s+(q.e-q.s)*hi,x0=!0}else inside&&!inside2&&ex++;inside=inside2}if(1!==ent||ex||!x0)throw 0;var entry=R;R=Q.geo.length-entry;if(!(R>0&&R<Q.geo.length))throw 0;"
    b"for(d=0;d<I;d++)for(U=0;U<a;U++){K=d*a+U;if(M[K]&&this.__obedLineInside(H,(U+.5)/G,(d+.5)/G)&&F[K]<entry-Q.stroke)throw 0}var nx=-Ly,ny=Lx,ap=H[0],r1=H[0],r2=H[0],apv=-1/0,r1v=1/0,r2v=-1/0;for(d=0;d<H.length;d++){var vx=H[d].x-u.x,vy=H[d].y-u.y,du=vx*Lx+vy*Ly,dn=vx*nx+vy*ny;du>apv&&(apv=du,ap=H[d]),dn<r1v&&(r1v=dn,r1=H[d]),dn>r2v&&(r2v=dn,r2=H[d])}if(!(apv>0&&r1v<0&&r2v>0&&Math.abs((ap.x-u.x)*nx+(ap.y-u.y)*ny)<=1))throw 0;"
    b"const OBED_LINE_DRAW_HEAD_DIFF_MAX=48;var tri=[ap,r1,r2],diff=0;for(d=0;d<I;d++)for(U=0;U<a;U++){K=d*a+U;var px=(U+.5)/G,py=(d+.5)/G;if(!this.__obedLineInside(H,px,py))continue;var src=!!h[4*K+3],ref=this.__obedLineInside(tri,px,py)||this.__obedLineNear(Q.geo,px,py).d<=l;src!==ref&&diff++}if(diff>OBED_LINE_DRAW_HEAD_DIFF_MAX)throw 0;S={hull:H,d:R,endAngle:Math.atan2(Ly,Lx)}}"
    b"var body=document.createElement(\"canvas\"),head=document.createElement(\"canvas\"),bd=body.getContext(\"2d\").createImageData(a,I),hd=head.getContext(\"2d\").createImageData(a,I);body.width=head.width=a,body.height=head.height=I;for(d=0;d<a*I;d++){var inHead=Q.arrow&&this.__obedLineInside(H,(d%a+.5)/G,(Math.floor(d/a)+.5)/G);for(U=0;U<4;U++)(inHead?hd.data:bd.data)[4*d+U]=h[4*d+U]}body.getContext(\"2d\").putImageData(bd,0,0),head.getContext(\"2d\").putImageData(hd,0,0);"
    b"var rec=document.createElement(\"canvas\");rec.width=a,rec.height=I;var rc=rec.getContext(\"2d\");rc.drawImage(body,0,0),rc.drawImage(head,0,0);var rd=rc.getImageData(0,0,a,I).data;for(d=0;d<h.length;d++)if(rd[d]!==h[d])throw 0;"
    b"var minX=0,minY=0,maxX=s,maxY=n;if(Q.arrow)for(d=0;d<Q.geo.segs.length;d++){q=Q.geo.segs[d];if(q.e<R)continue;var ang=Math.atan2(q.b.y-q.a.y,q.b.x-q.a.x)-S.endAngle,co=Math.cos(ang),si=Math.sin(ang);for(var ep=0;ep<2;ep++){var at=ep?q.b:q.a;for(U=0;U<H.length;U++){var hx=H[U].x-u.x,hy=H[U].y-u.y,tx=at.x+co*hx-si*hy,ty=at.y+si*hx+co*hy;minX=Math.min(minX,tx),minY=Math.min(minY,ty),maxX=Math.max(maxX,tx),maxY=Math.max(maxY,ty)}}}minX=Math.floor(minX*G)/G,minY=Math.floor(minY*G)/G,maxX=Math.ceil(maxX*G)/G,maxY=Math.ceil(maxY*G)/G;"
    b"e=document.createElement(\"canvas\"),e.width=Math.round((maxX-minX)*G),e.height=Math.round((maxY-minY)*G),e.dataset.obedLineDraw=C.objectID||\"\",e.__obedLineHeadDiff=Q.arrow?diff:null;var es=e.style;es.position=\"absolute\",es.pointerEvents=\"none\",es.left=minX+\"px\",es.top=minY+\"px\",es.width=maxX-minX+\"px\",es.height=maxY-minY+\"px\";"
    b"t=document.createElement(\"canvas\"),t.width=a,t.height=I,i=document.createElement(\"canvas\"),i.width=a,i.height=I;var state={effect:C,leaf:B,source:E,visibility:v0,overlay:e,body:body,head:head,reveal:t,mask:i,width:s,height:n,k:G,band:l,geo:Q.geo,arrow:Q.arrow,d:Q.arrow?S.d:0,endAngle:Q.arrow?S.endAngle:0,bodyEnd:Q.arrow?Q.geo.length-S.d:Q.geo.length,minX:minX,minY:minY,animation:null,frame:null,raf:0,done:!1};state.frame=this.__obedLineFrame.bind(this,state),this.__obedLineMask(state,state.bodyEnd,!0);var full=t.getContext(\"2d\").getImageData(0,0,a,I).data,bcheck=body.getContext(\"2d\").getImageData(0,0,a,I).data;for(d=0;d<full.length;d++)if(full[d]!==bcheck[d])throw 0;"
    b"var name=\"layer\"+B.layerId+\"-opacity\",el=document.getElementById(name),an=el&&el.getAnimations().filter(function(x){return x.animationName===name});if(!an||1!==an.length)throw 0;state.animation=an[0];o=this.__obedLineRule(name);if(!o)throw 0;var old=[];for(d=0;d<o.cssRules.length;d++)old.push(o.cssRules[d].cssText);for(;o.cssRules.length;)o.deleteRule(o.cssRules[0].keyText);o.appendRule(\"0% { opacity: 1; }\"),o.appendRule(\"100% { opacity: 1; }\");if(2!==o.cssRules.length)throw 0;w.appendChild(e),E.style.visibility=\"hidden\";if(\"hidden\"!==E.style.visibility||e.parentNode!==w)throw 0;state.finish=this.__obedLineDrawDrop.bind(this,state),state.cancel=this.__obedLineDrawDrop.bind(this,state),state.animation.addEventListener(\"finish\",state.finish),state.animation.addEventListener(\"cancel\",state.cancel),(this.__obedLineDrawStates||(this.__obedLineDrawStates=[])).push(state),Q.state=state,state.raf=requestAnimationFrame(state.frame)}catch(err){if(o&&old)try{for(;o.cssRules.length;)o.deleteRule(o.cssRules[0].keyText);for(var z=0;z<old.length;z++)o.appendRule(old[z])}catch(no){}e&&e.remove(),Q&&Q.leaf&&Q.leaf.__obedLineCanvas&&(Q.leaf.__obedLineCanvas.style.visibility=v0||\"\"),C&&delete C.__obedLineDraw}}"
)
_MM_OPACITY_REPLACEMENTS = (
    (
        b"textureInfoFromEffect(A,B,g,C,Q){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,"
        b"pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,A.textureId){",
        _MM_OPACITY_NODE
        + b"textureInfoFromEffect(A,B,g,C,Q,X,D){var e={};if(e.offset={pointX:g.pointX+A.bounds.offset.pointX,"
        b"pointY:g.pointY+A.bounds.offset.pointY},e.parentOpacity=C,"
        b"e.obedOpacity=void 0===X?null:this.__obedChainOpacity(X,A),"
        b"e.obedParentOpacity=A.textureId&&null!=X&&this.__obedFade(A,D)?X:null,A.textureId){",
    ),
    (
        b"this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q)",
        b"this.textureInfoFromEffect(A.layers[E],B,e.offset,e.parentOpacity,Q,this.__obedChainOpacity(X,A),D)",
    ),
    (
        b'd!==U&&(T=d+(U-d)*K),A.setGLFloat(T,"Opacity")',
        b'd!==U&&(T=d+(U-d)*K),null!=e.obedOpacity?T=e.obedOpacity:null!=e.obedParentOpacity&&'
        b'1===e.parentOpacity&&(T*=e.obedParentOpacity),A.setGLFloat(T,"Opacity")',
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
        _CONTINUITY_TAKE_ANCHOR,
        b"jumpToScene_partFour(A,B){if(" + _CONTINUITY_TAKE_CALL
        + b"B&&PB.prototype.__obedFreezeTake(this,A),this.displayScene(A),",
    ),
    (
        b"this.textureInfoFromEffect(A.kpfLayer,A.name,{pointX:0,pointY:0},A.baseLayer.initialState.opacity,B);",
        b"this.textureInfoFromEffect(A.kpfLayer,A.name,{pointX:0,pointY:0},A.baseLayer.initialState.opacity,B,"
        b"void 0,1e3*A.duration);",
    ),
    (
        b"else M.appendChild(Z);L&&(L.isFirstRendered?",
        b"else M.appendChild(Z),this.__obedLineDrawNode(g,Z,M);L&&(L.isFirstRendered?",
    ),
    (
        b"return Q}hideElement(A){",
        b"return Q}" + _LINE_DRAW_METHODS + b"hideElement(A){",
    ),
    (
        b"}}animateContentsWillBegin(A){var B=A.canvasId,",
        b"}this.__obedLineDrawApply(A,B,g,C)}animateContentsWillBegin(A){var B=A.canvasId,",
    ),
    (
        b"animateEffect(A){var B=A.canvasId,g=A.nodeToSwapId;if(B){",
        b"animateEffect(A){this.cssRenderer.__obedLineDrawAdmit(A);var B=A.canvasId,g=A.nodeToSwapId;if(B){",
    ),
    (
        b"handleEffectDidComplete(A){for(var B=this.renderEffects(A.effects),",
        b"handleEffectDidComplete(A){this.cssRenderer.__obedLineDrawComplete(A);for(var B=this.renderEffects(A.effects),",
    ),
    (
        b"destroy(){this.textureId=null,this.nativeWidth=null,this.nativeHeight=null,",
        b"destroy(){this.__obedLineDrawDestroy(),this.textureId=null,this.nativeWidth=null,this.nativeHeight=null,",
    ),
)

_DISSOLVE_RENDERING_METHODS = _DISSOLVE_METHODS[: _DISSOLVE_METHODS.index(b"__obedFreezeTake(U,A){")]
_RENDERING_REPLACEMENTS = (
    *_MM_OPACITY_REPLACEMENTS[:8],
    (b"return B}renderEffects(A){", b"return B}" + _DISSOLVE_RENDERING_METHODS + b"renderEffects(A){"),
    _MM_OPACITY_REPLACEMENTS[9],
    *_MM_OPACITY_REPLACEMENTS[12:],
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
    Dissolves and swap cuts without showing both slides, and freeze admitted outgoing movies into the transition.
    It also draws admitted Line Draw builds along their authored path with a moving filled arrowhead when present.

    A freeze is a snapshot of the decoded frame at identity tone (no pixel writes), drawn first with every edge snapped
    to the device grid (1/DPR px). A `frac` grant at DPR 1 overlays the unsnapped compositor quad, checks opacity, then
    redraws its partially covered boundary cells from the video. The geometry guard requires the base layer to equal
    the slide, translation-only stage and scene transforms, and integer scene `left`/`top`; `frac` additionally requires
    an integer stage origin. The take also
    requires no top-layer element and no open shadow root on the page, and every element must pass the paint
    gate or, outside the stage, is clipped by an HTML `div` proven disjoint from the visible stage. Supported pages
    create no author shadow roots (a checked invariant), since a closed one cannot be detected; anything else keeps
    today's look. Both modes expose the existing pre-teardown call site to an optional MM-feed frame take."""
    pins = SUPPORTED_PLAYERS.get(hashlib.sha256(player).hexdigest())
    if pins is None:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for live output.")
    if player.count(_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player observation hook is missing or ambiguous.")
    patched = player.replace(
        _ANCHOR,
        b"UC=new Eg," + _INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )
    return _pinned(_apply_mm_opacity(patched), pins[0]) if mm_opacity else _pinned(_apply_continuity_take(patched), pins[1])


def patch_rendering(player: bytes) -> bytes:
    """Apply rendering fidelity without observation or the executable movie-freeze lifecycle."""
    pins = SUPPORTED_PLAYERS.get(hashlib.sha256(player).hexdigest())
    if pins is None:
        raise LiveRuntimeUnsupported("This Keynote HTML player version is not supported for the preview opacity patch.")
    return _pinned(_apply_replacements(player, _RENDERING_REPLACEMENTS), pins[2])


def _pinned(patched: bytes, expected: str) -> bytes:
    if hashlib.sha256(patched).hexdigest() != expected:
        raise LiveRuntimeUnsupported("The patched player does not match its pinned digest.")
    return patched


def _apply_mm_opacity(player: bytes) -> bytes:
    player = _apply_continuity_take(player)
    for before, after in _MM_OPACITY_REPLACEMENTS:
        if before == _CONTINUITY_TAKE_ANCHOR:
            before = _CONTINUITY_TAKE_REPLACEMENT
        if player.count(before) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity anchor is missing or ambiguous.")
        player = player.replace(before, after)
        if player.count(before) != 0 or player.count(after) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity patch is ambiguous.")
    return player


def _apply_replacements(player: bytes, replacements: tuple[tuple[bytes, bytes], ...]) -> bytes:
    for before, after in replacements:
        if player.count(before) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity anchor is missing or ambiguous.")
        player = player.replace(before, after)
        if player.count(before) != 0 or player.count(after) != 1:
            raise LiveRuntimeUnsupported("The supported player Magic Move opacity patch is ambiguous.")
    return player


def _apply_continuity_take(player: bytes) -> bytes:
    if player.count(_CONTINUITY_TAKE_ANCHOR) != 1:
        raise LiveRuntimeUnsupported("The supported player continuity-take anchor is missing or ambiguous.")
    player = player.replace(_CONTINUITY_TAKE_ANCHOR, _CONTINUITY_TAKE_REPLACEMENT)
    if player.count(_CONTINUITY_TAKE_REPLACEMENT) != 1:
        raise LiveRuntimeUnsupported("The supported player continuity-take patch is ambiguous.")
    return player

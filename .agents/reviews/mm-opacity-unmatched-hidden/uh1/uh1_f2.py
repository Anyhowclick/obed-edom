#!/usr/bin/env python3
"""Rendered UH-1 instrument for the old F2 slide-3 Magic Move.

The normal mode prepares SHA-pinned stock/base/candidate exports, starts three
headless Chromes serially, retains raw evidence, and scores it.
The dry-run mode performs every preparation and pin check without starting a
browser.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
os.environ["OBED_EDOM_OUTPUT_ROOT"] = str(HERE / "oroot")
RUNS = HERE / "oroot" / ".html-preview" / "uh1-runs"
REPO = Path("/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e")
INPUT = Path.home() / "Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/F2-html-old-stock"
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
sys.path[:0] = [str(SRC), str(SCRIPTS)]

from obed_edom import live_host as live_host_module  # noqa: E402
from obed_edom.live_host import ChromeCdp, LiveOutputHost, OutputDisplay  # noqa: E402

import live_continuity_probe as continuity_probe  # noqa: E402
import live_host_probe  # noqa: E402

VIEWPORT = (1920, 1080)
STOCK_SHA = "17c0c938caa49d5c70bd83bd5b84f57381faa51602932ca733aa965055026d91"
SLIDE3 = "6B05DE14-37DB-4505-B242-8996669A30BD"
SLIDE4 = "2C214651-FBDF-4698-B8D4-A16E2D803A56"
EFFECT_FINGERPRINT = "f2350147870865e13a6a4e588c1d3b06f50ed18204520b4283dc8f67e0717b66"
MAX_HEADLESS = 3
LOAD_LIMIT = 3.0
LOAD_WAIT_S = 60.0
RUN_DEADLINE_S = 540.0
CAPTURE_DEADLINE_S = 6.0
TARGETS = {
    "slot7": {"slot": 7, "asset": "C0C026F1A1C5577B04664882E8B35C5D", "size": [44, 50],
              "authored": [568, 510, 44, 50], "gl": [568, 520, 44, 50]},
    "slot8": {"slot": 8, "asset": "E7CF3AADFEEDA3217255F36836CDA7A8", "size": [88, 59],
              "authored": [652, 506, 88, 59], "gl": [652, 515, 88, 59]},
}
SIBLINGS = {
    "slot1": {"slot": 1, "asset": "68EE6B7757EAE3EBE14400D8B803EC01", "size": [585, 437],
              "authored": [678, 652, 585, 437], "gl": [678, -9, 585, 437]},
    "slot10": {"slot": 10, "asset": "7AF1A2FD289A629D45D84B4F2F8588A9", "size": [39, 27],
               "authored": [972, 844, 39, 27], "gl": [972, 209, 39, 27]},
    "slot11": {"slot": 11, "asset": "54AC5F2D72B23FC14E9B5D9C0111B61C", "size": [21, 24],
               "authored": [938, 846, 21, 24], "gl": [938, 210, 21, 24]},
}
MONITORS = {**TARGETS, **SIBLINGS}
RUN_ORDER = (
    ("stock", "stock", "stock"),
    ("base-preview", "base", "preview"),
    ("cand-preview", "cand", "preview"),
    ("cand2-preview", "cand2", "preview"),
    ("base-live", "base", "live"),
    ("cand-live", "cand", "live"),
    ("cand2-live", "cand2", "live"),
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


LOGGER_JS = r"""
(function(CFG){
  if(window.__OBED_UH1__)return;
  var Ps=[];
  if(window.WebGLRenderingContext)Ps.push(WebGLRenderingContext.prototype);
  if(window.WebGL2RenderingContext)Ps.push(WebGL2RenderingContext.prototype);
  var nativeMap=Ps.map(function(P){var o={};Object.getOwnPropertyNames(P).forEach(function(n){var d=Object.getOwnPropertyDescriptor(P,n);if(d&&typeof d.value==='function')o[n]=d.value});return o});
  function nat(g,n){for(var i=Ps.length-1;i>=0;i--)if(Ps[i].isPrototypeOf(g)&&nativeMap[i][n])return nativeMap[i][n];return null}
  var ids=new WeakMap(), seq={ctx:0,prog:0,tex:0,buf:0,canvas:0};
  function id(x,k){if(!x)return null;if(!ids.has(x))ids.set(x,++seq[k]);return ids.get(x)}
  function now(){return performance.now()}
  function b64(a){var s='',n=8192;for(var i=0;i<a.length;i+=n)s+=String.fromCharCode.apply(null,a.subarray(i,Math.min(a.length,i+n)));return btoa(s)}
  function hash(a){var h=2166136261;for(var i=0;i<a.length;i++)h=Math.imul(h^a[i],16777619);return(h>>>0).toString(16)}
  function summary(a,b){var p=0,c=0,m=0,l=0,lr=0;for(var i=0;i<a.length;i++){var d=Math.abs(a[i]-b[i]);if(d){c++;if((i&3)!==3){p++;lr+=d}if(d>m)m=d;l+=d}}return{equal:c===0,diffBytes:c,diffRgb:p,maxAbs:m,l1:l,l1Rgb:lr,beforeHash:hash(a),afterHash:hash(b)}}
  var states=new WeakMap(),stateList=[],texInfo=new WeakMap(),bufInfo=new WeakMap(),locInfo=new WeakMap(),attrInfo=new WeakMap(),samplerInfo=new WeakMap(),canvasCtx=new WeakMap();
  var M=window.__OBED_UH1__={version:2,armed:false,installedAt:now(),contexts:[],frames:[],glCalls:[],removals:[],scene:[],errors:[],buildStart:null,config:CFG};
  function state(g){var s=states.get(g);if(!s){s={id:id(g,'ctx'),g:g,canvas:g.canvas,prog:null,active:0,units:{},array:null,element:null,attrs:{},uniforms:new WeakMap(),frame:null,viewport:[0,0,g.drawingBufferWidth,g.drawingBufferHeight],monitored:false,seenConnected:!!g.canvas.isConnected,removedAt:null};states.set(g,s);stateList.push(s);canvasCtx.set(g.canvas,s);var R=null;try{var e=nat(g,'getExtension').call(g,'WEBGL_debug_renderer_info');R={renderer:nat(g,'getParameter').call(g,e?e.UNMASKED_RENDERER_WEBGL:g.RENDERER),vendor:nat(g,'getParameter').call(g,e?e.UNMASKED_VENDOR_WEBGL:g.VENDOR),version:nat(g,'getParameter').call(g,g.VERSION)}}catch(x){M.errors.push('renderer:'+x)}M.contexts.push({id:s.id,canvas:id(g.canvas,'canvas'),renderer:R,width:g.drawingBufferWidth,height:g.drawingBufferHeight,createdAt:now(),connectedAtCreate:!!g.canvas.isConnected})}return s}
  function sourceInfo(x){if(!x)return{};var u='';try{u=x.currentSrc||x.src||''}catch(e){}return{width:+(x.videoWidth||x.naturalWidth||x.width||0),height:+(x.videoHeight||x.naturalHeight||x.height||0),source:Object.prototype.toString.call(x),url:String(u).split('/').pop()}}
  function assetOf(t){var q=texInfo.get(t);if(!q)return null;for(var k in CFG.monitors){var m=CFG.monitors[k];if(q.width===m.size[0]&&q.height===m.size[1])return{name:k,id:m.asset}}return null}
  function wrap(name,fn){Ps.forEach(function(P,pi){if(!Object.prototype.hasOwnProperty.call(P,name)||typeof nativeMap[pi][name]!=='function')return;var orig=nativeMap[pi][name];P[name]=function(){var s=state(this),a=arguments,pre=null;if(M.armed)M.glCalls.push([now(),s.id,name]);try{pre=fn&&fn.call(this,s,a,null)}catch(e){M.errors.push(name+':pre:'+e)}var rv=orig.apply(this,a);try{if(fn)fn.call(this,s,a,rv,pre)}catch(e){M.errors.push(name+':post:'+e)}return rv}})}
  wrap('useProgram',function(s,a,rv){if(rv!==null)s.prog=a[0]||null});
  wrap('getUniformLocation',function(s,a,rv){if(rv&&a[0])locInfo.set(rv,{program:a[0],name:String(a[1])})});
  function uset(s,p,n,v){var q=s.uniforms.get(p);if(!q){q={};s.uniforms.set(p,q)}q[n]=v}
  function uget(s,p,n){var q=p&&s.uniforms.get(p);return q?q[n]:null}
  ['uniform1f','uniform1i','uniform2f','uniform3f','uniform4f','uniformMatrix4fv'].forEach(function(n){wrap(n,function(s,a,rv){if(rv!==null){var q=locInfo.get(a[0]);if(q){var v=n==='uniformMatrix4fv'?Array.prototype.slice.call(a[2]):Array.prototype.slice.call(a,1);uset(s,q.program,q.name,v)}}})});
  wrap('getAttribLocation',function(s,a,rv){if(rv!==null&&rv>=0){var q=attrInfo.get(a[0]);if(!q){q={};attrInfo.set(a[0],q)}q[rv]=String(a[1])}});
  wrap('activeTexture',function(s,a,rv){if(rv!==null)s.active=a[0]-s.g.TEXTURE0});
  wrap('bindTexture',function(s,a,rv){if(rv!==null&&a[0]===s.g.TEXTURE_2D)s.units[s.active]=a[1]||null});
  wrap('texImage2D',function(s,a,rv){if(rv!==null){var t=s.units[s.active];if(!t)return;var q=a.length>=9?{width:+a[3],height:+a[4],source:'pixels',url:''}:sourceInfo(a[a.length-1]);q.texture=id(t,'tex');q.uploadAt=now();q.nonempty=q.width>0&&q.height>0;texInfo.set(t,q)}});
  wrap('viewport',function(s,a,rv){if(rv!==null)s.viewport=[+a[0],+a[1],+a[2],+a[3]]});
  wrap('bindBuffer',function(s,a,rv){if(rv!==null){if(a[0]===s.g.ARRAY_BUFFER)s.array=a[1];if(a[0]===s.g.ELEMENT_ARRAY_BUFFER)s.element=a[1]}});
  function bytes(x){if(!ArrayBuffer.isView(x))return null;return new Uint8Array(x.buffer.slice(x.byteOffset,x.byteOffset+x.byteLength))}
  wrap('bufferData',function(s,a,rv){if(rv!==null){var b=a[0]===s.g.ARRAY_BUFFER?s.array:a[0]===s.g.ELEMENT_ARRAY_BUFFER?s.element:null,d=bytes(a[1]);if(b&&d)bufInfo.set(b,d)}});
  wrap('bufferSubData',function(s,a,rv){if(rv!==null){var b=a[0]===s.g.ARRAY_BUFFER?s.array:a[0]===s.g.ELEMENT_ARRAY_BUFFER?s.element:null,d=bytes(a[2]),old=b&&bufInfo.get(b);if(b&&d){if(!old||old.length<a[1]+d.length){var z=new Uint8Array(a[1]+d.length);if(old)z.set(old);old=z}old.set(d,a[1]);bufInfo.set(b,old)}}});
  wrap('vertexAttribPointer',function(s,a,rv){if(rv!==null)s.attrs[a[0]]={buffer:s.array,size:a[1],type:a[2],normalized:a[3],stride:a[4],offset:a[5],enabled:false}});
  wrap('enableVertexAttribArray',function(s,a,rv){if(rv!==null&&s.attrs[a[0]])s.attrs[a[0]].enabled=true});
  wrap('disableVertexAttribArray',function(s,a,rv){if(rv!==null&&s.attrs[a[0]])s.attrs[a[0]].enabled=false});
  function scalar(g,data,type,off){var v=new DataView(data.buffer,data.byteOffset,data.byteLength);if(type===g.FLOAT)return v.getFloat32(off,true);if(type===g.SHORT)return v.getInt16(off,true);if(type===g.UNSIGNED_SHORT)return v.getUint16(off,true);if(type===g.BYTE)return v.getInt8(off);if(type===g.UNSIGNED_BYTE)return v.getUint8(off);return NaN}
  function typeSize(g,t){return t===g.FLOAT?4:(t===g.SHORT||t===g.UNSIGNED_SHORT?2:1)}
  function rectOf(s,first,count){var p=null,names=s.prog&&attrInfo.get(s.prog)||{};for(var k in s.attrs){if(names[k]==='Position'&&s.attrs[k].enabled){p=s.attrs[k];break}}if(!p)return null;var data=bufInfo.get(p.buffer),mv=uget(s,s.prog,'MVPMatrix');if(!data||!mv||mv.length!==16)return null;var step=p.stride||p.size*typeSize(s.g,p.type),pts=[];for(var i=first;i<first+count;i++){var o=p.offset+i*step,x=scalar(s.g,data,p.type,o),y=p.size>1?scalar(s.g,data,p.type,o+typeSize(s.g,p.type)):0,z=p.size>2?scalar(s.g,data,p.type,o+2*typeSize(s.g,p.type)):0,w=p.size>3?scalar(s.g,data,p.type,o+3*typeSize(s.g,p.type)):1;if(!isFinite(x)||!isFinite(y))continue;var X=mv[0]*x+mv[4]*y+mv[8]*z+mv[12]*w,Y=mv[1]*x+mv[5]*y+mv[9]*z+mv[13]*w,W=mv[3]*x+mv[7]*y+mv[11]*z+mv[15]*w;if(!W)continue;pts.push([s.viewport[0]+(X/W+1)*s.viewport[2]/2,s.viewport[1]+(Y/W+1)*s.viewport[3]/2])}if(!pts.length)return null;var xs=pts.map(function(q){return q[0]}),ys=pts.map(function(q){return q[1]}),x0=Math.min.apply(null,xs),x1=Math.max.apply(null,xs),y0=Math.min.apply(null,ys),y1=Math.max.apply(null,ys);return[Math.round(x0),Math.round(y0),Math.round(x1-x0),Math.round(y1-y0)]}
  function read(g,r){var x=Math.max(0,r[0]),y=Math.max(0,r[1]),x1=Math.min(g.drawingBufferWidth,r[0]+r[2]),y1=Math.min(g.drawingBufferHeight,r[1]+r[3]),w=Math.max(0,x1-x),h=Math.max(0,y1-y),a=new Uint8Array(w*h*4);nat(g,'readPixels').call(g,x,y,w,h,g.RGBA,g.UNSIGNED_BYTE,a);return{rect:[x,y,w,h],data:a}}
  function textures(s){var out=[],seen={};try{var list=samplerInfo.get(s.prog);if(!list){list=[];var g=s.g,n=nat(g,'getProgramParameter').call(g,s.prog,g.ACTIVE_UNIFORMS);for(var i=0;i<n;i++){var q=nat(g,'getActiveUniform').call(g,s.prog,i);if(q&&(q.type===g.SAMPLER_2D||q.type===g.SAMPLER_CUBE)){var l=nat(g,'getUniformLocation').call(g,s.prog,q.name);if(l)list.push(l)}}samplerInfo.set(s.prog,list)}list.forEach(function(l){var u=nat(s.g,'getUniform').call(s.g,s.prog,l),t=s.units[u],q=t&&texInfo.get(t),a=t&&assetOf(t);if(t&&!seen[u]){seen[u]=1;out.push({unit:+u,id:id(t,'tex'),asset:a&&a.name,assetId:a&&a.id,info:q||null})}})}catch(e){M.errors.push('samplers:'+e)}if(!out.length){var t=s.units[s.active],q=t&&texInfo.get(t),a=t&&assetOf(t);if(t)out.push({unit:s.active,id:id(t,'tex'),asset:a&&a.name,assetId:a&&a.id,info:q||null})}return out}
  function sampleRect(asset){var m=CFG.monitors[asset];return m&&m.gl?m.gl.slice():null}
  function beginDraw(s,a,name){if(!M.armed)return null;if(!s.frame)s.frame={ctx:s.id,index:M.frames.length,clearAt:null,draws:[],taskEnd:null,terminal:null};var ts=textures(s),asset=null;for(var i=0;i<ts.length;i++)if(ts[i].asset){asset=ts[i].asset;break}var first=name==='drawArrays'?(+a[1]||0):0,count=name==='drawArrays'?(+a[2]||0):Math.min(4,+a[1]||0),rect=rectOf(s,first,count),op=uget(s,s.prog,'Opacity'),d={at:now(),program:id(s.prog,'prog'),textures:ts,asset:asset,rect:rect,opacity:Array.isArray(op)?op[0]:null,kind:name,sample:null};s.frame.draws.push(d);if(asset){s.monitored=true;var rr=sampleRect(asset);if(rr){var B=read(s.g,rr);d._before=B.data;d.sample={rect:B.rect}}}return d}
  function finishDraw(s,d){if(!d)return;if(d._before){var P=read(s.g,d.sample.rect),z=summary(d._before,P.data);d.sample=Object.assign(d.sample,z);if(CFG.monitors[d.asset].target){d.sample.before=b64(d._before);d.sample.after=b64(P.data)}delete d._before}if(!s.frame._queued){s.frame._queued=true;queueMicrotask(function(){var f=s.frame;if(!f)return;f.taskEnd=now();f.terminal={};Object.keys(CFG.monitors).forEach(function(k){if(!CFG.monitors[k].target)return;var q=read(s.g,CFG.monitors[k].gl);f.terminal[k]={rect:q.rect,rgba:b64(q.data),hash:hash(q.data)}});delete f._queued})}}
  function drawWrap(name){wrap(name,function(s,a,rv,pre){if(rv===null)return beginDraw(s,a,name);finishDraw(s,pre)})}
  drawWrap('drawArrays');drawWrap('drawElements');
  wrap('clear',function(s,a,rv){if(rv===null){var f={ctx:s.id,index:M.frames.length,clearAt:now(),draws:[],taskEnd:null,terminal:null};s.frame=f;M.frames.push(f)}});
  var oldGet=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(){var g=oldGet.apply(this,arguments);if(g&&(/webgl/i.test(String(arguments[0]))))state(g);return g};
  function recordRemoval(c,source){var s=canvasCtx.get(c);if(!s||s.removedAt!==null)return;s.removedAt=now();M.removals.push({at:s.removedAt,ctx:s.id,canvas:id(c,'canvas'),connected:!!c.isConnected,source:source})}
  new MutationObserver(function(ms){if(!M.armed)return;ms.forEach(function(mu){Array.prototype.forEach.call(mu.removedNodes,function(n){var cs=[];if(n.nodeType===1){if(n.tagName==='CANVAS')cs.push(n);if(n.querySelectorAll)cs=cs.concat(Array.prototype.slice.call(n.querySelectorAll('canvas')))}cs.forEach(function(c){if(!c.isConnected)recordRemoval(c,'mutation')})})})}).observe(document,{childList:true,subtree:true});
  function scene(){try{var u=window.__uh1UC||null,c=u&&Number.isInteger(u.currentSceneIndex)?u:u&&u.playbackController,s=c&&(c.script||u.script),i=c&&c.currentSlideIndex;if(s&&(!Number.isInteger(i)||i<0)&&s.slideIndexFromSceneIndexLookup)i=s.slideIndexFromSceneIndexLookup[c.currentSceneIndex];var sid=s&&s.slideList&&Number.isInteger(i)?s.slideList[i]:null,k=c&&(c.kpfEvent||(u.playbackController&&u.playbackController.kpfEvent)),e=k&&(k.event||k),f=e&&e.effects&&e.effects[0];return{at:now(),sceneIndex:c&&c.currentSceneIndex,nextSceneIndex:c&&c.nextSceneIndex,slideIndex:i,slideId:sid,state:c&&c.state,queued:!!(c&&c.queuedUserAction),effect:f?{name:f.name,type:f.type,duration:f.duration,automaticPlay:!!e.automaticPlay}:null,focus:document.hasFocus()}}catch(x){return{at:now(),error:String(x),focus:document.hasFocus()}}}
  function canvasContexts(){return stateList.map(function(s){return{ctx:s.id,canvas:id(s.canvas,'canvas'),connected:!!s.canvas.isConnected,monitored:!!s.monitored,seenConnected:!!s.seenConnected,removedAt:s.removedAt,lastTaskEnd:s.frame&&s.frame.taskEnd}})}
  var last='';function tick(){var q=scene(),k=JSON.stringify([q.sceneIndex,q.nextSceneIndex,q.slideIndex,q.slideId,q.state,q.effect&&q.effect.name]);if(k!==last){last=k;M.scene.push(q)}if(M.armed){stateList.forEach(function(s){if(s.canvas.isConnected)s.seenConnected=true;else if(s.seenConnected)recordRemoval(s.canvas,'isConnected-poll')});if(!M.buildStart&&q.slideId===CFG.slide4&&q.effect&&q.effect.type==='buildIn'&&q.effect.automaticPlay)M.buildStart=q}requestAnimationFrame(tick)}requestAnimationFrame(tick);
  M.arm=function(){M.armed=true;M.frames=[];M.glCalls=[];M.removals=[];M.scene=[];M.buildStart=null;M.errors=[];stateList.forEach(function(s){s.frame=null;s.monitored=false;s.seenConnected=!!s.canvas.isConnected;s.removedAt=null});M.armAt=now();return{at:M.armAt,scene:scene(),canvasContexts:canvasContexts()}};
  M.brief=function(){return{at:now(),frames:M.frames.length,removals:M.removals.length,buildStart:M.buildStart,scene:scene(),canvasContexts:canvasContexts()}};
  M.snapshot=function(){M.armed=false;return{version:M.version,installedAt:M.installedAt,armAt:M.armAt,contexts:M.contexts,canvasContexts:canvasContexts(),frames:M.frames,glCalls:M.glCalls,removals:M.removals,scene:M.scene,buildStart:M.buildStart,errors:M.errors,finalScene:scene(),continuity:!!window.__OBED_P2_PRESERVE__,glReplay:!!window.__OBED_GL_REPLAY__}};
})(__CFG__);
"""

SCENE_JS = r"""(function(){try{var u=window.__uh1UC||null,c=u&&Number.isInteger(u.currentSceneIndex)?u:u&&u.playbackController,s=c&&(c.script||u.script),i=c&&c.currentSlideIndex;if(s&&(!Number.isInteger(i)||i<0)&&s.slideIndexFromSceneIndexLookup)i=s.slideIndexFromSceneIndexLookup[c.currentSceneIndex];return{sceneIndex:c&&c.currentSceneIndex,nextSceneIndex:c&&c.nextSceneIndex,slideIndex:i,slideId:s&&s.slideList&&Number.isInteger(i)?s.slideList[i]:null,state:c&&c.state,queued:!!(c&&c.queuedUserAction),focus:document.hasFocus(),stage:(function(){var e=document.getElementById('stage');if(!e)return null;var r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height}})()}}catch(e){return{error:String(e),focus:document.hasFocus()}}})()"""


@dataclass(frozen=True)
class Prepared:
    run_id: str
    arm: str
    mode: str
    root: Path
    sha256: str
    expected_sha256: str


class InconclusivePage(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


UC_ANCHOR = b"UC=new Eg,"


def uc_splice(player: bytes) -> bytes:
    if player.count(UC_ANCHOR) != 1:
        raise RuntimeError("UC instrument anchor missing or ambiguous")
    return player.replace(UC_ANCHOR, b"UC=window.__uh1UC=new Eg,")


class StaticExportServer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> str:
        owner = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(owner.root), **kwargs)

            def log_message(self, *_args: Any) -> None:
                pass

            def do_GET(self) -> None:
                if self.path.split("?")[0] == "/assets/player/main.js":
                    body = uc_splice((owner.root / "assets/player/main.js").read_bytes())
                    self.send_response(200)
                    self.send_header("Content-Type", "application/javascript")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().do_GET()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_port}/index.html"

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError("static export server did not stop")
            self.thread = None


@dataclass(frozen=True)
class PlayerPage:
    transport: ChromeCdp
    context: str | None

    def evaluate(self, expression: str, deadline_s: float | None = None) -> Any:
        if self.context is None:
            return self.transport.evaluate(expression, deadline_s=deadline_s)
        return self.transport.evaluate_in(self.context, expression, deadline_s=deadline_s)

    def call(self, method: str, deadline_s: float | None = None, **params: Any) -> dict[str, Any]:
        return self.transport.call(method, deadline_s=deadline_s, **params)

    def key(self, key: str, code: str, vk: int) -> None:
        self.transport.key(key, code, vk)


def instrumented_transport(source: str) -> type[ChromeCdp]:
    class InstrumentedCdp(ChromeCdp):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.page_events: list[dict[str, Any]] = []

        def start(self) -> None:
            super().start()
            self.call("Page.addScriptToEvaluateOnNewDocument", deadline_s=5, source=source)

        def _route_event(self, message: dict[str, Any]) -> None:
            method = message.get("method")
            params = message.get("params") or {}
            if method == "Runtime.exceptionThrown":
                self.page_events.append({"method": method, "detail": params.get("exceptionDetails")})
            elif method == "Log.entryAdded":
                entry = params.get("entry") or {}
                if entry.get("level") in ("error", "warning"):
                    self.page_events.append({"method": method, "entry": entry})
            elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning"):
                self.page_events.append({"method": method, "type": params.get("type"), "args": params.get("args")})
            if len(self.page_events) > 100:
                del self.page_events[:-100]
            super()._route_event(message)

    return InstrumentedCdp


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def effect_fingerprint(effect: Any) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ("texture", "toTexture", "objectID")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return sha256_bytes(_json(clean(effect)).encode())


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_text(revision: str, relative: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "show", f"{revision}:{relative}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def clone_export(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"destination already exists: {destination}")
    result = subprocess.run(["cp", "-cR", str(source), str(destination)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        shutil.copytree(source, destination)


def validate_input() -> dict[str, Any]:
    player = INPUT / "assets/player/main.js"
    if not INPUT.is_dir() or not player.is_file():
        raise RuntimeError(f"missing input export: {INPUT}")
    stock_sha = sha256_file(player)
    if stock_sha != STOCK_SHA:
        raise RuntimeError(f"stock player SHA mismatch: {stock_sha}")
    header = json.loads((INPUT / "assets/header.json").read_text())
    if header.get("slideWidth") != VIEWPORT[0] or header.get("slideHeight") != VIEWPORT[1]:
        raise RuntimeError("input is not 1920x1080")
    if (header.get("slideList") or [None, None, None, None])[2:4] != [SLIDE3, SLIDE4]:
        raise RuntimeError("input slide 3/4 identity mismatch")
    slide = json.loads((INPUT / "assets" / SLIDE3 / f"{SLIDE3}.json").read_text())
    try:
        effect = slide["events"][1]["effects"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("slide 3 Magic Move is missing") from exc
    fingerprint = effect_fingerprint(effect)
    if fingerprint != EFFECT_FINGERPRINT or effect.get("name") != "apple:magic-move-implied-motion-path":
        raise RuntimeError(f"wrong F2 effect: {fingerprint}")
    leaves: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], parent_x: float = 0, parent_y: float = 0) -> None:
        state = node["initialState"]
        anchor = state.get("anchorPoint") or {"pointX": 0.5, "pointY": 0.5}
        position = state.get("position") or {"pointX": 0, "pointY": 0}
        x = parent_x + position["pointX"] - anchor["pointX"] * state.get("width", 0)
        y = parent_y + position["pointY"] - anchor["pointY"] * state.get("height", 0)
        if node.get("texture"):
            leaves.append({"texture": node["texture"], "rect": [x, y, state["width"], state["height"]]})
        for child in node.get("layers") or []:
            walk(child, x, y)

    walk(effect["baseLayer"])
    for name, spec in MONITORS.items():
        if len(leaves) <= spec["slot"]:
            raise RuntimeError(f"{name} is absent from the F2 Magic Move")
        leaf = leaves[spec["slot"]]
        if leaf["texture"] != spec["asset"] or any(abs(a - b) > 1e-6 for a, b in zip(leaf["rect"], spec["authored"])):
            raise RuntimeError(f"{name} texture/rect identity mismatch: {leaf}")
    sizes = {}
    for leaf in leaves:
        asset = slide["assets"][leaf["texture"]]
        sizes.setdefault((asset["width"], asset["height"]), []).append(leaf["texture"])
    for name, spec in MONITORS.items():
        matches = sizes.get(tuple(spec["size"]), [])
        if matches != [spec["asset"]]:
            raise RuntimeError(f"{name} upload dimensions are not unique in the MM effect: {matches}")
    return {
        "input": str(INPUT),
        "stockSha256": stock_sha,
        "slide3": SLIDE3,
        "slide4": SLIDE4,
        "effectFingerprint": fingerprint,
        "leafCount": len(leaves),
    }


def prepare(stamp_root: Path) -> tuple[list[Prepared], dict[str, Any]]:
    fixture = validate_input()
    modules = stamp_root / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    base_path = modules / "live_runtime_head_minus_1.py"
    cand_path = modules / "live_runtime_head.py"
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    fix_commit = subprocess.run(
        ["git", "-C", str(REPO), "log", "-1", "--format=%H", "-Sif(0===X)return 0", "--", "src/obed_edom/live_runtime.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not fix_commit:
        raise RuntimeError("cannot locate the proved-zero runtime change")
    ancestor = subprocess.run(
        ["git", "-C", str(REPO), "merge-base", "--is-ancestor", fix_commit, head], check=False
    )
    if ancestor.returncode != 0:
        raise RuntimeError(f"runtime fix {fix_commit} is not an ancestor of HEAD {head}")
    base_revision = fix_commit + "^"
    base_path.write_text(git_text(base_revision, "src/obed_edom/live_runtime.py"))
    cand_path.write_text(git_text("HEAD", "src/obed_edom/live_runtime.py"))
    base = load_module(base_path, "uh1_base_runtime")
    cand = load_module(cand_path, "uh1_cand_runtime")
    stock = (INPUT / "assets/player/main.js").read_bytes()
    for label, module in (("base", base), ("cand", cand)):
        if STOCK_SHA not in module.SUPPORTED_PLAYERS:
            raise RuntimeError(f"{label} runtime does not support stock player {STOCK_SHA}")
    outputs: dict[tuple[str, str], bytes] = {
        ("stock", "stock"): stock,
        ("base", "preview"): base.patch_rendering(stock),
        ("base", "live"): base.patch_player(stock),
        ("cand", "preview"): cand.patch_rendering(stock),
        ("cand", "live"): cand.patch_player(stock),
    }
    zero_chain = b"__obedChainOpacity(X,A){if(null===X)return null;if(0===X)return 0;"
    for mode in ("preview", "live"):
        if zero_chain in outputs[("base", mode)] or zero_chain not in outputs[("cand", mode)]:
            raise RuntimeError(f"{mode} base/candidate proved-zero splice identity is wrong")
        if outputs[("base", mode)] == outputs[("cand", mode)]:
            raise RuntimeError(f"{mode} base and candidate bytes are identical")
    expected: dict[tuple[str, str], str] = {
        ("stock", "stock"): STOCK_SHA,
        ("base", "preview"): base.SUPPORTED_PLAYERS[STOCK_SHA][2],
        ("base", "live"): base.SUPPORTED_PLAYERS[STOCK_SHA][0],
        ("cand", "preview"): cand.SUPPORTED_PLAYERS[STOCK_SHA][2],
        ("cand", "live"): cand.SUPPORTED_PLAYERS[STOCK_SHA][0],
    }
    prepared: list[Prepared] = []
    prep_manifest = {
        "fixture": fixture,
        "repo": str(REPO),
        "head": head,
        "fixCommit": fix_commit,
        "base": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", base_revision], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "runs": [],
    }
    for run_id, arm, mode in RUN_ORDER:
        source_arm = "cand" if arm == "cand2" else arm
        key = (source_arm, mode)
        data = outputs[key]
        digest = sha256_bytes(data)
        want = expected[key]
        if digest != want:
            raise RuntimeError(f"{run_id} output pin mismatch: {digest} != {want}")
        destination = stamp_root / "prepared" / run_id
        clone_export(INPUT, destination)
        main_js = destination / "assets/player/main.js"
        main_js.write_bytes(data)
        disk_sha = sha256_file(main_js)
        if disk_sha != want:
            raise RuntimeError(f"{run_id} written main.js pin mismatch: {disk_sha} != {want}")
        item = Prepared(run_id, arm, mode, destination, disk_sha, want)
        prepared.append(item)
        prep_manifest["runs"].append({
            "runId": run_id,
            "arm": arm,
            "mode": mode,
            "export": str(destination),
            "mainJsSha256": disk_sha,
            "expectedSha256": want,
        })
    (stamp_root / "preparation.json").write_text(json.dumps(prep_manifest, indent=2))
    return prepared, prep_manifest


def headless_roots() -> list[dict[str, Any]]:
    result = subprocess.run(["pgrep", "-f", "--", "--headless=new"], capture_output=True, text=True, check=False)
    roots = []
    for raw in result.stdout.split():
        if not raw.isdigit():
            continue
        command = subprocess.run(["ps", "-o", "command=", "-p", raw], capture_output=True, text=True, check=False).stdout.strip()
        if command and "--type=" not in command:
            roots.append({"pid": int(raw), "command": command})
    return roots


def wait_for_load() -> None:
    deadline = time.monotonic() + LOAD_WAIT_S
    while True:
        load = os.getloadavg()[0]
        if load < LOAD_LIMIT:
            return
        if time.monotonic() >= deadline:
            top = subprocess.run("ps -Ao pcpu,pid,comm -r | head", shell=True, capture_output=True, text=True, check=False).stdout
            print(top.rstrip(), flush=True)
            print(f"LOAD-BLOCKED one-minute load {load:.2f} did not fall below {LOAD_LIMIT:.1f}", flush=True)
            raise SystemExit(2)
        time.sleep(2.0)


def frame_entries(tree: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        frame = node.get("frame") or {}
        out.append({"id": frame.get("id"), "url": frame.get("url"), "name": frame.get("name")})
        for child in node.get("childFrames") or []:
            visit(child)

    visit(tree)
    return out


def page_diagnostics(transport: ChromeCdp) -> dict[str, Any]:
    tree = transport.call("Page.getFrameTree", deadline_s=3).get("frameTree") or {}
    frames = frame_entries(tree)
    main_id = ((tree.get("frame") or {}).get("id"))
    reads = []
    expression = (
        "(function(){var s=document.getElementById('stage'),r=s&&s.getBoundingClientRect();"
        "return{location:String(document.location),frameCount:window.frames.length,hasUC:!!window.__uh1UC,"
        "logger:!!window.__OBED_UH1__,stage:r?{x:r.x,y:r.y,width:r.width,height:r.height}:null,scene:"
        + SCENE_JS + "}})()"
    )
    for frame in frames:
        frame_id = frame.get("id")
        context = transport.main_context(frame_id) if isinstance(frame_id, str) else None
        unique = context.get("uniqueId") if context else None
        try:
            if isinstance(unique, str):
                read = transport.evaluate_in(unique, expression, deadline_s=2)
            elif frame_id == main_id:
                read = transport.evaluate(expression, deadline_s=2)
            else:
                read = None
            reads.append({**frame, "context": unique, "read": read})
        except Exception as exc:
            reads.append({**frame, "context": unique, "error": str(exc)})
    return {
        "frameCount": len(frames),
        "frames": reads,
        "consoleExceptions": list(getattr(transport, "page_events", [])),
    }


def diagnostic_summary(diagnostics: dict[str, Any]) -> str:
    locations = [
        (entry.get("read") or {}).get("location") or entry.get("url")
        for entry in diagnostics.get("frames") or []
    ]
    exceptions = diagnostics.get("consoleExceptions") or []
    return (
        f"document.location={locations!r}; frames={diagnostics.get('frameCount')!r}; "
        f"consoleExceptions={exceptions[-10:]!r}"
    )


def locate_player_page(transport: ChromeCdp, timeout_s: float = 5.0) -> tuple[PlayerPage, dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    diagnostics: dict[str, Any] = {}
    while time.monotonic() < deadline:
        diagnostics = page_diagnostics(transport)
        for entry in diagnostics.get("frames") or []:
            read = entry.get("read") or {}
            if read.get("hasUC") and read.get("stage") is not None:
                if read.get("logger") is not True:
                    message = "logger absent from player document before WebGL observation; " + diagnostic_summary(diagnostics)
                    raise InconclusivePage(message, diagnostics)
                return PlayerPage(transport, entry.get("context")), diagnostics
        time.sleep(0.05)
    message = "no UC/#stage in any loaded document; " + diagnostic_summary(diagnostics)
    raise InconclusivePage(message, diagnostics)


def wait_scene(transport: Any, predicate: Any, timeout_s: float, label: str) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        last = transport.evaluate(SCENE_JS, deadline_s=2)
        if isinstance(last, dict) and predicate(last):
            return last
        time.sleep(0.04)
    raise RuntimeError(f"timed out waiting for {label}; last={last!r}")


def capture_focus(transport: Any) -> bool:
    transport.call("Page.captureScreenshot", deadline_s=4, format="png", fromSurface=True)
    return transport.evaluate("document.hasFocus()", deadline_s=2) is True


def screenshot(transport: Any, path: Path, index: int) -> dict[str, Any]:
    before = transport.evaluate("window.__OBED_UH1__.brief()", deadline_s=2)
    encoded = transport.call("Page.captureScreenshot", deadline_s=4, format="png", fromSurface=True)["data"]
    after = transport.evaluate("window.__OBED_UH1__.brief()", deadline_s=2)
    data = base64.b64decode(encoded)
    image = Image.open(io.BytesIO(data))
    if image.size != VIEWPORT:
        raise RuntimeError(f"capture {index} is {image.size}, expected {VIEWPORT}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "index": index,
        "path": str(path),
        "sha256": sha256_bytes(data),
        "before": before,
        "after": after,
        "pageTs": (float(before["at"]) + float(after["at"])) / 2,
    }


def run_one(
    transport: ChromeCdp,
    item: Prepared,
    stamp_root: Path,
    overall_deadline: float,
    *,
    host: LiveOutputHost | None = None,
) -> dict[str, Any]:
    run_dir = stamp_root / item.run_id
    pages = run_dir / "pages"
    run_dir.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {
        "runId": item.run_id,
        "arm": item.arm,
        "mode": item.mode,
        "export": str(item.root),
        "mainJsSha256": item.sha256,
        "expectedSha256": item.expected_sha256,
        "viewport": list(VIEWPORT),
        "deviceScaleFactor": 1,
        "continuityRequested": "off",
        "glReplayRequested": "off",
        "uptime": subprocess.run(["uptime"], capture_output=True, text=True, check=False).stdout.strip(),
        "captures": [],
    }
    page: PlayerPage | None = None
    server: StaticExportServer | None = None
    try:
        if host is None:
            server = StaticExportServer(item.root)
            raw["url"] = server.start() + "#4"
            transport.goto(raw["url"])
            raw["driver"] = "plain-static-index"
        else:
            raw["driver"] = "LiveOutputHost"
            raw["output"] = host.output
            opacity = (host.output.get("mmOpacity") or {}).get("sha256")
            served = sha256_bytes(uc_splice((item.root / "assets/player/main.js").read_bytes()))
            raw["servedSplicedSha256"] = served
            if opacity != served:
                raise RuntimeError(f"LiveOutputHost served SHA mismatch: {opacity} != {served}")
            shown = host.execute("show")
            raw["outputVisible"] = shown.output_visible
            raw["decoded"] = continuity_probe.wait_for_decode(host)
        page, diagnostics = locate_player_page(transport)
        raw["pageDiagnostics"] = diagnostics
        wait_scene(page, lambda s: s.get("stage") == {"x": 0, "y": 0, "width": 1920, "height": 1080}, 5, "full stage")
        raw["loggerInstalled"] = page.evaluate("!!window.__OBED_UH1__", deadline_s=2)
        raw["dpr"] = page.evaluate("window.devicePixelRatio", deadline_s=2)
        raw["browser"] = page.call("Browser.getVersion", deadline_s=3)
        if not capture_focus(page):
            raise RuntimeError("document.hasFocus() is false before go-to")
        raw["focusBeforeGoTo"] = True
        if host is not None:
            host.execute("goTo", slide=3)
        idle = wait_scene(
            page,
            lambda s: s.get("slideIndex") == 2 and s.get("slideId") == SLIDE3 and str(s.get("state", "")).startswith("IdleAt") and not s.get("queued"),
            35,
            "slide 3 idle",
        )
        raw["stimulusScene"] = idle
        raw["armed"] = page.evaluate("window.__OBED_UH1__.arm()", deadline_s=2)
        raw["captures"].append(screenshot(page, pages / "frame-000.png", 0))
        raw["focusBeforeAdvance"] = capture_focus(page)
        if raw["focusBeforeAdvance"] is not True:
            raise RuntimeError("document.hasFocus() is false before advance")
        raw["advanceDispatchedAtWall"] = time.time()
        if host is None:
            page.key(" ", "Space", 32)
        else:
            host.execute("advance")
        started = time.monotonic()
        index = 1
        while True:
            if time.monotonic() >= overall_deadline:
                raise RuntimeError("global run deadline exceeded")
            capture = screenshot(page, pages / f"frame-{index:03d}.png", index)
            raw["captures"].append(capture)
            index += 1
            brief = capture["after"]
            mm_contexts = [c for c in brief.get("canvasContexts") or [] if c.get("monitored")]
            hold_closed = any(
                isinstance(c.get("lastTaskEnd"), (int, float))
                and isinstance(c.get("removedAt"), (int, float))
                and c["removedAt"] > c["lastTaskEnd"]
                for c in mm_contexts
            )
            if brief.get("buildStart") and hold_closed:
                break
            if time.monotonic() - started >= CAPTURE_DEADLINE_S:
                break
        raw["log"] = page.evaluate("window.__OBED_UH1__.snapshot()", deadline_s=60)
        raw["finalScene"] = page.evaluate(SCENE_JS, deadline_s=2)
    except InconclusivePage as exc:
        raw["error"] = f"INCONCLUSIVE: {exc}"
        raw["pageDiagnostics"] = exc.diagnostics
        print(f"{item.run_id}: INCONCLUSIVE {exc}", file=sys.stderr, flush=True)
    except Exception:
        raw["error"] = traceback.format_exc()
        with contextlib.suppress(Exception):
            if page is not None:
                raw["log"] = page.evaluate("window.__OBED_UH1__&&window.__OBED_UH1__.snapshot()", deadline_s=15)
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.stop()
    (run_dir / "raw.json").write_text(json.dumps(raw, separators=(",", ":")))
    return raw


def decode_rgba(encoded: str, rect: list[int]) -> np.ndarray:
    raw = base64.b64decode(encoded)
    return np.frombuffer(raw, dtype=np.uint8).reshape(rect[3], rect[2], 4)


def target_draws(log: dict[str, Any], target: str, context: int | None = None) -> list[dict[str, Any]]:
    out = []
    for frame in log.get("frames") or []:
        if context is not None and frame.get("ctx") != context:
            continue
        for draw in frame.get("draws") or []:
            if draw.get("asset") == target:
                out.append({**draw, "frameIndex": frame.get("index"), "ctx": frame.get("ctx")})
    return out


def context_and_window(raw: dict[str, Any]) -> tuple[int | None, dict[str, Any], list[str]]:
    log = raw.get("log") or {}
    problems: list[str] = []
    contexts = set()
    for name in TARGETS:
        contexts.update(d["ctx"] for d in target_draws(log, name))
    if len(contexts) != 1:
        problems.append(f"target draws span {len(contexts)} MM contexts: {sorted(contexts)}")
        return None, {}, problems
    ctx = next(iter(contexts))
    frames = [f for f in log.get("frames") or [] if f.get("ctx") == ctx and any(d.get("asset") in TARGETS for d in f.get("draws") or [])]
    if not frames:
        return ctx, {}, ["no MM frames"]
    d0 = min(d["at"] for f in frames for d in f.get("draws") or [] if d.get("asset") in TARGETS)
    last = frames[-1]
    dlast = last.get("taskEnd")
    if not isinstance(dlast, (int, float)) or not last.get("terminal"):
        problems.append("final MM draw-task terminal readback is missing")
    removals = [r for r in log.get("removals") or [] if r.get("ctx") == ctx and isinstance(dlast, (int, float)) and r.get("at", -1) > dlast]
    removal_record = min(removals, key=lambda r: r["at"], default=None)
    removal = removal_record["at"] if removal_record else None
    if removal is None:
        problems.append("MM canvas removal R is missing")
    mappings = [m for m in log.get("canvasContexts") or [] if m.get("ctx") == ctx]
    context_records = [c for c in log.get("contexts") or [] if c.get("id") == ctx]
    if len(mappings) != 1 or len(context_records) != 1 or mappings[0].get("canvas") != context_records[0].get("canvas"):
        problems.append("MM canvas/context mapping is missing or inconsistent")
    elif removal_record is not None and removal_record.get("canvas") != mappings[0].get("canvas"):
        problems.append("MM removal does not match the mapped canvas")
    calls = []
    if removal is not None and isinstance(dlast, (int, float)):
        calls = [c for c in log.get("glCalls") or [] if c[1] == ctx and dlast < c[0] < removal]
    captures = [
        c
        for c in raw.get("captures") or []
        if isinstance(dlast, (int, float))
        and removal is not None
        and dlast < ((c.get("before") or {}).get("at", -1))
        and ((c.get("after") or {}).get("at", float("inf"))) < removal
    ]
    if not captures:
        problems.append("no compositor capture strictly inside (Dlast,R)")
    return ctx, {
        "D0": d0,
        "Dlast": dlast,
        "R": removal,
        "removal": removal_record,
        "canvasContext": mappings[0] if len(mappings) == 1 else None,
        "frameCount": len(frames),
        "lastFrame": last,
        "postDlastGlCalls": calls,
        "holdCaptures": captures,
    }, problems


def save_crops(raw: dict[str, Any], window: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    crops: dict[str, Any] = {}
    captures = window.get("holdCaptures") or []
    if not captures:
        return crops
    chosen = min(captures, key=lambda c: abs(c["pageTs"] - (window["Dlast"] + window["R"]) / 2))
    image = Image.open(chosen["path"]).convert("RGBA")
    crop_dir = run_dir / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in TARGETS.items():
        x, y, w, h = spec["authored"]
        crop = image.crop((x, y, x + w, y + h))
        path = crop_dir / f"{name}-hold.png"
        crop.save(path)
        crops[name] = {"path": str(path), "sha256": sha256_file(path), "capture": chosen["index"], "pageTs": chosen["pageTs"]}
    return crops


def base_validity(raw: dict[str, Any]) -> tuple[list[str], int | None, dict[str, Any]]:
    problems: list[str] = []
    if raw.get("error"):
        problems.append("run error: " + str(raw["error"]).strip().splitlines()[-1])
    if raw.get("mainJsSha256") != raw.get("expectedSha256"):
        problems.append("written main.js pin mismatch")
    if raw.get("loggerInstalled") is not True:
        problems.append("logger was not installed")
    if raw.get("dpr") != 1:
        problems.append(f"devicePixelRatio is {raw.get('dpr')!r}, expected 1")
    if raw.get("focusBeforeGoTo") is not True:
        problems.append("document did not have focus at go-to")
    scene = raw.get("stimulusScene") or {}
    if scene.get("slideIndex") != 2 or scene.get("slideId") != SLIDE3:
        problems.append("stimulus is not F2 slide 3")
    if raw.get("focusBeforeAdvance") is not True:
        problems.append("document did not have focus at advance")
    log = raw.get("log") or {}
    if log.get("errors"):
        problems.append(f"logger errors: {log['errors'][:5]}")
    if log.get("continuity") or log.get("glReplay"):
        problems.append("continuity or GL replay unexpectedly attached")
    renderer = " ".join(
        str(((c.get("renderer") or {}).get(k)) or "")
        for c in log.get("contexts") or []
        for k in ("renderer", "vendor")
    )
    if not renderer.strip():
        problems.append("GL renderer string is missing")
    if any(word in renderer.lower() for word in ("swiftshader", "software", "llvmpipe")):
        problems.append(f"software GL renderer: {renderer}")
    ctx, window, window_problems = context_and_window(raw)
    problems += window_problems
    if window.get("postDlastGlCalls"):
        problems.append(f"{len(window['postDlastGlCalls'])} GL calls occurred in (Dlast,R)")
    build = log.get("buildStart")
    if not isinstance(build, dict) or build.get("slideId") != SLIDE4:
        problems.append("slide-4 automatic build onset is missing")
    if window.get("R") is not None and isinstance(build, dict) and build.get("at", -1) < window["R"]:
        problems.append("build onset precedes MM canvas removal")
    return problems, ctx, window


def pair_stats(sample: dict[str, Any]) -> dict[str, Any] | None:
    before, after = sample.get("before"), sample.get("after")
    if not isinstance(before, str) or not isinstance(after, str):
        return None
    a = np.frombuffer(base64.b64decode(before), dtype=np.uint8)
    b = np.frombuffer(base64.b64decode(after), dtype=np.uint8)
    if a.shape != b.shape or a.size % 4:
        return None
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).reshape(-1, 4)[:, :3]
    return {"equal": bool(np.array_equal(a, b)), "diffRgb": int(np.count_nonzero(d)), "l1Rgb": int(d.sum())}


def score_local(raw: dict[str, Any], stamp_root: Path) -> dict[str, Any]:
    problems, ctx, window = base_validity(raw)
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {"context": ctx, "window": window}
    log = raw.get("log") or {}
    candidate = raw.get("arm") in ("cand", "cand2")
    known_bad = raw.get("arm") in ("stock", "base")
    for name, spec in TARGETS.items():
        draws = target_draws(log, name, ctx)
        detail[name] = {
            "draws": len(draws),
            "programs": sorted({str(d.get("program")) for d in draws}),
            "textures": sorted({str(t.get("id")) for d in draws for t in d.get("textures") or [] if t.get("asset") == name}),
            "opacities": sorted({str(d.get("opacity")) for d in draws}),
            "contributionL1Rgb": [((d.get("sample") or {}).get("l1Rgb")) for d in draws],
        }
        if not draws:
            problems.append(f"{name}: no texture-identified draw")
            continue
        pairs = [pair_stats(d.get("sample") or {}) for d in draws]
        matched_textures = [
            t
            for d in draws
            for t in d.get("textures") or []
            if t.get("asset") == name
        ]
        uploads = [t.get("info") or {} for t in matched_textures]
        checks[f"{name}TextureIdentity"] = all(
            any(
                t.get("asset") == name
                and t.get("assetId") == spec["asset"]
                and [(t.get("info") or {}).get("width"), (t.get("info") or {}).get("height")] == spec["size"]
                for t in d.get("textures") or []
            )
            for d in draws
        )
        checks[f"{name}RawPairs"] = all(pair is not None for pair in pairs)
        if not checks[f"{name}TextureIdentity"]:
            problems.append(f"{name}: draw lacks the unique texture asset/upload-size identity {spec['size']}")
        if not checks[f"{name}RawPairs"]:
            problems.append(f"{name}: raw before/after RGBA pair is missing")
        if candidate:
            checks[f"{name}OpacityZero"] = all(d.get("opacity") == 0 for d in draws)
            checks[f"{name}NoContribution"] = all(pair is not None and pair["equal"] for pair in pairs)
        if known_bad:
            checks[f"{name}OpacityOne"] = all(d.get("opacity") == 1 for d in draws)
            checks[f"{name}Contributes"] = all(pair is not None and pair["diffRgb"] > 0 for pair in pairs)
            checks[f"{name}TextureNonempty"] = bool(uploads) and all(u.get("nonempty") is True for u in uploads)
    mm_frames = [f for f in log.get("frames") or [] if f.get("ctx") == ctx and any(d.get("asset") in TARGETS for d in f.get("draws") or [])]
    checks["everyMmDrawIdentified"] = bool(mm_frames) and all(
        d.get("program") is not None and d.get("textures") and d.get("opacity") is not None
        for f in mm_frames for d in f.get("draws") or []
    )
    if not checks["everyMmDrawIdentified"]:
        problems.append("one or more MM draws lacks program, texture, or cached Opacity identity")
    for name, spec in SIBLINGS.items():
        draws = target_draws(log, name, ctx)
        checks[f"{name}Contributes"] = bool(draws) and any((d.get("sample") or {}).get("diffRgb", 0) > 0 for d in draws)
        detail[name] = {
            "draws": len(draws),
            "roi": spec["gl"],
            "sampleRects": sorted({str((d.get("sample") or {}).get("rect")) for d in draws}),
            "maxDiffRgb": max(((d.get("sample") or {}).get("diffRgb", 0) for d in draws), default=0),
        }
    crops = save_crops(raw, window, stamp_root / raw["runId"])
    raw["holdCrops"] = crops
    (stamp_root / raw["runId"] / "raw.json").write_text(json.dumps(raw, separators=(",", ":")))
    detail["holdCrops"] = crops
    verdict = "INCONCLUSIVE" if problems else ("PASS" if checks and all(checks.values()) else "FAIL")
    return {"verdict": verdict, "problems": problems, "checks": checks, "detail": detail}


def crop_array(raw: dict[str, Any], target: str) -> np.ndarray | None:
    entry = (raw.get("holdCrops") or {}).get(target)
    if not entry or not Path(entry["path"]).is_file():
        return None
    return np.asarray(Image.open(entry["path"]).convert("RGBA"), dtype=np.uint8)


def terminal_array(raw: dict[str, Any], target: str) -> np.ndarray | None:
    _, _, window = base_validity(raw)
    entry = ((window.get("lastFrame") or {}).get("terminal") or {}).get(target)
    if not entry:
        return None
    return np.flipud(decode_rgba(entry["rgba"], entry["rect"]))


def delta(a: np.ndarray | None, b: np.ndarray | None) -> dict[str, Any] | None:
    if a is None or b is None or a.shape != b.shape:
        return None
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))[:, :, :3]
    return {"maxAbs": int(d.max(initial=0)), "l1": int(d.sum()), "meanAbs": float(d.mean())}


def terminal_contribution(raw: dict[str, Any], target: str) -> int | None:
    _, ctx, window = base_validity(raw)
    index = (window.get("lastFrame") or {}).get("index")
    draws = [d for d in target_draws(raw.get("log") or {}, target, ctx) if d.get("frameIndex") == index]
    if not draws:
        return None
    stats = pair_stats(draws[-1].get("sample") or {})
    return stats["l1Rgb"] if stats is not None else None


def score_all(stamp_root: Path, raws: dict[str, dict[str, Any]]) -> dict[str, Any]:
    arms = {name: score_local(raw, stamp_root) for name, raw in raws.items()}
    cross_problems: list[str] = []
    cross_checks: dict[str, bool] = {}
    cross_detail: dict[str, Any] = {}
    for mode in ("preview", "live"):
        cand, repeat = raws.get(f"cand-{mode}"), raws.get(f"cand2-{mode}")
        if not cand or not repeat:
            cross_problems.append(f"{mode}: candidate repeat pair missing")
            continue
        for target in TARGETS:
            ch, rh = crop_array(cand, target), crop_array(repeat, target)
            ct, rt = terminal_array(cand, target), terminal_array(repeat, target)
            noise_hold, noise_terminal = delta(ch, rh), delta(ct, rt)
            self_cand, self_repeat = delta(ch, ct), delta(rh, rt)
            key = f"{mode}-{target}"
            cross_detail[key] = {
                "noiseHold": noise_hold,
                "noiseTerminal": noise_terminal,
                "candHoldVsTerminal": self_cand,
                "repeatHoldVsTerminal": self_repeat,
            }
            if None in (noise_hold, noise_terminal, self_cand, self_repeat):
                cross_problems.append(f"{key}: hold/readback comparison unavailable")
                continue
            noise = max(noise_hold["maxAbs"], noise_terminal["maxAbs"])
            cross_checks[f"{key}NoiseBounded"] = noise <= 2
            cross_checks[f"{key}CandMatchesTerminal"] = self_cand["maxAbs"] <= noise
            cross_checks[f"{key}RepeatMatchesTerminal"] = self_repeat["maxAbs"] <= noise
    cand_preview = raws.get("cand-preview")
    for run_id in ("stock", "base-preview", "base-live"):
        bad = raws.get(run_id)
        reference = raws.get("cand-live" if run_id.endswith("live") else "cand-preview") or cand_preview
        if not bad or not reference:
            cross_problems.append(f"{run_id}: known-bad hold comparison unavailable")
            continue
        for target in TARGETS:
            difference = delta(crop_array(bad, target), crop_array(reference, target))
            contribution = terminal_contribution(bad, target)
            key = f"{run_id}-{target}"
            cross_detail[key] = {"holdVsCandidate": difference, "terminalContributionL1": contribution}
            if difference is None or contribution is None:
                cross_problems.append(f"{key}: positive-control comparison unavailable")
                continue
            cross_checks[f"{key}RetainsArtifact"] = difference["l1"] >= contribution and contribution > 0
    candidate_ids = ("cand-preview", "cand2-preview", "cand-live", "cand2-live")
    positive_ids = ("stock", "base-preview", "base-live")
    all_present = len(arms) == len(RUN_ORDER)
    integrity_failed = not all_present or any(v["verdict"] == "INCONCLUSIVE" for v in arms.values())
    positive_failed = any((arms.get(name) or {}).get("verdict") != "PASS" for name in positive_ids)
    calibration_failed = any(not value for key, value in cross_checks.items() if key.endswith("NoiseBounded") or key.endswith("RetainsArtifact"))
    candidate_failed = any((arms.get(name) or {}).get("verdict") == "FAIL" for name in candidate_ids)
    candidate_cross_failed = any(
        not value for key, value in cross_checks.items()
        if key.endswith("CandMatchesTerminal") or key.endswith("RepeatMatchesTerminal")
    )
    if cross_problems or integrity_failed or positive_failed or calibration_failed:
        overall = "INCONCLUSIVE"
    elif candidate_failed or candidate_cross_failed:
        overall = "FAIL"
    else:
        overall = "PASS"
    result = {
        "gate": "UH-1",
        "overall": overall,
        "arms": arms,
        "cross": {"problems": cross_problems, "checks": cross_checks, "detail": cross_detail},
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    (stamp_root / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def stamp_name(prefix: str = "") -> str:
    return prefix + datetime.now().strftime("%Y%m%d-%H%M%S")


def load_raws(stamp_root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in stamp_root.glob("*/raw.json"):
        raw = json.loads(path.read_text())
        out[raw["runId"]] = raw
    return out


@contextlib.contextmanager
def exact_live_player(item: Prepared, log_path: Path) -> Any:
    wanted = (item.root / "assets/player/main.js").read_bytes()
    if sha256_bytes(wanted) != item.expected_sha256:
        raise RuntimeError(f"{item.run_id} live source bytes changed after preparation")
    real_patch = live_host_module.patch_player
    real_log_path = live_host_module._new_log_path
    old_advance = os.environ.get(live_host_module.ADVANCE_ENV)
    old_goto = os.environ.get(live_host_module.GOTO_AUTOPLAY_ENV)

    def patched(player: bytes, *, mm_opacity: bool = True) -> bytes:
        if not mm_opacity:
            raise RuntimeError(f"{item.run_id} requested live player with Magic Move opacity disabled")
        if sha256_bytes(player) != item.expected_sha256:
            raise RuntimeError(f"{item.run_id} host read unexpected main.js bytes")
        return uc_splice(wanted)

    live_host_module.patch_player = patched
    live_host_module._new_log_path = lambda: log_path
    os.environ[live_host_module.ADVANCE_ENV] = "key"
    os.environ.pop(live_host_module.GOTO_AUTOPLAY_ENV, None)
    try:
        yield
    finally:
        live_host_module.patch_player = real_patch
        live_host_module._new_log_path = real_log_path
        if old_advance is None:
            os.environ.pop(live_host_module.ADVANCE_ENV, None)
        else:
            os.environ[live_host_module.ADVANCE_ENV] = old_advance
        if old_goto is None:
            os.environ.pop(live_host_module.GOTO_AUTOPLAY_ENV, None)
        else:
            os.environ[live_host_module.GOTO_AUTOPLAY_ENV] = old_goto


def make_live_host(item: Prepared, stamp_root: Path, source: str) -> LiveOutputHost:
    continuity_probe.force_viewport(*VIEWPORT)
    slides = continuity_probe.load_slides(item.root)
    host = LiveOutputHost(
        item.root,
        slides,
        headless=True,
        continuity="off",
        gl_replay="off",
        mm_opacity="auto",
        attach_endpoint=None,
        transport_factory=instrumented_transport(source),
    )
    with exact_live_player(item, stamp_root / f"{item.run_id}.live-host.jsonl"):
        host.start()
    return host


def probe_page(item: Prepared, stamp_root: Path, source: str) -> dict[str, Any]:
    host: LiveOutputHost | None = None
    transport: ChromeCdp | None = None
    server: StaticExportServer | None = None
    try:
        if item.mode == "live":
            host = make_live_host(item, stamp_root, source)
            transport = host._require_transport()
            host.execute("show")
            continuity_probe.wait_for_decode(host)
        else:
            display = OutputDisplay(
                0, 0, 0, VIEWPORT[0], VIEWPORT[1] + live_host_probe.HEADLESS_CHROME_HEIGHT_PAD, True
            )
            transport = instrumented_transport(source)(
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                stamp_root / "probe-profile",
                display,
                headless=True,
                log_path=stamp_root / f"{item.run_id}.probe.jsonl",
            )
            transport.start()
            server = StaticExportServer(item.root)
            transport.goto(server.start())
        page, diagnostics = locate_player_page(transport)
        diagnostics["scene"] = page.evaluate(SCENE_JS, deadline_s=2)
        diagnostics["selectedLocation"] = page.evaluate("String(document.location)", deadline_s=2)
        diagnostics["selectedFrames"] = page.evaluate("window.frames.length", deadline_s=2)
        diagnostics["loggerInstalled"] = page.evaluate("!!window.__OBED_UH1__", deadline_s=2)
        return diagnostics
    except InconclusivePage as exc:
        return {**exc.diagnostics, "inconclusive": str(exc)}
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.stop()
        if host is not None:
            with contextlib.suppress(Exception):
                host.stop()
        elif transport is not None:
            with contextlib.suppress(Exception):
                transport.stop()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="prepare all arms and check pins without Chrome")
    parser.add_argument("--score", type=Path, help="re-score a retained runs/<stamp> directory")
    parser.add_argument("--probe-page", choices=[run_id for run_id, _arm, _mode in RUN_ORDER], help="load one arm, print page diagnostics, and exit")
    args = parser.parse_args(argv)
    if args.score and (args.dry_run or args.probe_page):
        parser.error("--score cannot be combined with --dry-run or --probe-page")
    if args.dry_run and args.probe_page:
        parser.error("--dry-run cannot be combined with --probe-page")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    RUNS.mkdir(parents=True, exist_ok=True)
    if args.score:
        result = score_all(args.score.resolve(), load_raws(args.score.resolve()))
        print(f"UH-1 {result['overall']}: {args.score.resolve()}")
        return 0 if result["overall"] == "PASS" else 1
    stamp_root = RUNS / stamp_name("dry-" if args.dry_run else "")
    stamp_root.mkdir(parents=True)
    try:
        prepared, manifest = prepare(stamp_root)
    except Exception:
        failure = {"gate": "UH-1", "overall": "INCONCLUSIVE", "phase": "prepare", "error": traceback.format_exc()}
        (stamp_root / "result.json").write_text(json.dumps(failure, indent=2))
        print(f"INCONCLUSIVE preparation: {stamp_root}", file=sys.stderr)
        return 2
    if args.dry_run:
        result = {
            "gate": "UH-1",
            "overall": "DRY-RUN-OK",
            "browserLaunched": False,
            "prepared": len(prepared),
            "head": manifest["head"],
            "base": manifest["base"],
        }
        (stamp_root / "result.json").write_text(json.dumps(result, indent=2))
        print(f"DRY-RUN-OK {len(prepared)} arms: {stamp_root}")
        return 0
    wait_for_load()
    foreign = headless_roots()
    if foreign:
        failure = {"gate": "UH-1", "overall": "INCONCLUSIVE", "phase": "preflight", "foreignHeadless": foreign}
        (stamp_root / "result.json").write_text(json.dumps(failure, indent=2))
        print(f"refusing to start: {len(foreign)} headless Chrome root process(es) not started by this driver", file=sys.stderr)
        return 2
    cfg = {"slide3": SLIDE3, "slide4": SLIDE4, "monitors": {k: {**v, "target": k in TARGETS} for k, v in MONITORS.items()}}
    source = LOGGER_JS.replace("__CFG__", _json(cfg))
    by_id = {item.run_id: item for item in prepared}
    if args.probe_page:
        diagnostics = probe_page(by_id[args.probe_page], stamp_root, source)
        (stamp_root / "probe-page.json").write_text(json.dumps(diagnostics, indent=2, default=str))
        print(json.dumps(diagnostics, indent=2, default=str))
        return 2 if diagnostics.get("inconclusive") else 0
    overall_deadline = time.monotonic() + RUN_DEADLINE_S
    raws: dict[str, dict[str, Any]] = {}
    groups = (
        ("base-live", ("stock", "base-preview")),
        ("cand-live", ("cand-preview",)),
        ("cand2-live", ("cand2-preview",)),
    )
    owners: list[dict[str, Any]] = []
    errors: list[str] = []
    for launch_index, (live_id, static_ids) in enumerate(groups, 1):
        if launch_index > MAX_HEADLESS:
            errors.append("headless Chrome launch limit exceeded")
            break
        if time.monotonic() >= overall_deadline:
            errors.append("global run deadline exceeded")
            break
        running = headless_roots()
        if running:
            errors.append(f"before {live_id}: unexpected headless Chrome roots: {running!r}")
            break
        host: LiveOutputHost | None = None
        group_ids = (live_id, *static_ids)
        try:
            host = make_live_host(by_id[live_id], stamp_root, source)
            transport = host._require_transport()
            if transport.proc is None:
                raise RuntimeError("Chrome process ownership was not established")
            owners.append({"launch": launch_index, "runId": live_id, "pid": transport.proc.pid, "startedAt": time.time()})
            (stamp_root / "chrome-owners.json").write_text(json.dumps(owners, indent=2))
            for run_id in group_ids:
                if time.monotonic() >= overall_deadline:
                    raise RuntimeError("global run deadline exceeded")
                item = by_id[run_id]
                raw = run_one(transport, item, stamp_root, overall_deadline, host=host if run_id == live_id else None)
                raws[run_id] = raw
                print(f"{run_id}: {'INCONCLUSIVE' if raw.get('error') else 'captured'}", flush=True)
        except Exception:
            error = traceback.format_exc()
            errors.append(f"{live_id}\n{error}")
            for run_id in group_ids:
                if run_id in raws:
                    continue
                item = by_id[run_id]
                raw = {
                    "runId": run_id,
                    "arm": item.arm,
                    "mode": item.mode,
                    "mainJsSha256": item.sha256,
                    "expectedSha256": item.expected_sha256,
                    "error": error,
                }
                run_dir = stamp_root / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "raw.json").write_text(json.dumps(raw, separators=(",", ":")))
                raws[run_id] = raw
                print(f"{run_id}: INCONCLUSIVE host startup/drive failure", flush=True)
        finally:
            if host is not None:
                try:
                    host.stop()
                except Exception:
                    errors.append(f"{live_id} stop\n{traceback.format_exc()}")
    if errors:
        (stamp_root / "driver-error.txt").write_text("\n\n".join(errors))
    result = score_all(stamp_root, raws)
    print(f"UH-1 {result['overall']}: {stamp_root}")
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

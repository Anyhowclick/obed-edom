"""Probe-only reader and pure scorers for the Magic Move texture feed."""
from __future__ import annotations

import math
from typing import Any, Iterable

READ_PROGRESS = (0.25, 0.5, 0.75)
ALPHA_POSTER_FLOOR = 6.0
LABEL_SPREAD_FLOOR = 24.0
LABEL_SLOPE_TOLERANCE = 0.02
RIDER_OPACITY_FLOOR = 0.02


INSTRUMENT_JS = r"""
(function(){
  'use strict';
  if(window.__obedMmFeedProbe)return;
  var S={config:null,contexts:[],live:[],frames:[],holds:[],media:[],errors:[],tamper:null,killedOnce:[],forcedDecoders:{}};
  var originalGetContext=HTMLCanvasElement.prototype.getContext;
  var locationName=new WeakMap(),programUniforms=new WeakMap(),textureInfo=new WeakMap();
  var armedDecoders=new WeakSet(),media=HTMLMediaElement.prototype,originalPause=media.pause,originalPlay=media.play;
  function finite(v){return typeof v==='number'&&isFinite(v)}
  function noteError(where,e){if(S.errors.length<50)S.errors.push({where:where,error:String(e&&e.stack||e)})}
  function moduleRead(){
    var api=window.__OBED_MM_FEED__;
    if(!api)return null;
    try{return typeof api.report==='function'?api.report():JSON.parse(JSON.stringify(api));}
    catch(e){return {error:String(e)}}
  }
  function decoderFor(objectId){
    if(S.forcedDecoders[objectId])return S.forcedDecoders[objectId];
    var seam=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed;
    try{return seam&&typeof seam.decoderFor==='function'?seam.decoderFor(objectId):null}catch(e){return null}
  }
  function decoderRead(objectId){
    var v=decoderFor(objectId);
    if(v)armDecoder(v,objectId);
    var r=v&&v.getBoundingClientRect?v.getBoundingClientRect():null;
    return v?{objectId:objectId,elId:v.__obedElId==null?null:v.__obedElId,currentTime:v.currentTime,
      paused:!!v.paused,readyState:v.readyState,presentedFrames:v.__obedPresentedFrames==null?null:v.__obedPresentedFrames,
      mediaTime:v.__obedMediaTime==null?null:v.__obedMediaTime,opacityProduct:opacityProduct(v),visible:visible(v),
      rect:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null}:null;
  }
  function mediaEvent(kind,v,extra){
    if(S.media.length<20000)S.media.push(Object.assign({kind:kind,t:performance.now(),objectId:v.__obedMmFeedObjectId||null,
      elId:v.__obedElId==null?null:v.__obedElId,currentTime:v.currentTime,paused:!!v.paused},extra||{}));
  }
  media.pause=function(){mediaEvent('pause',this);return originalPause.apply(this,arguments)};
  media.play=function(){mediaEvent('play',this);return originalPlay.apply(this,arguments)};
  function armDecoder(v,objectId){
    v.__obedMmFeedObjectId=objectId;if(armedDecoders.has(v))return;armedDecoders.add(v);
    v.addEventListener('seeking',function(){mediaEvent('seeking',v)},true);
    if(typeof v.requestVideoFrameCallback==='function'){
      var callback=function(now,meta){v.__obedPresentedFrames=meta.presentedFrames;v.__obedMediaTime=meta.mediaTime;
        mediaEvent('videoFrame',v,{now:now,presentedFrames:meta.presentedFrames,mediaTime:meta.mediaTime});
        v.requestVideoFrameCallback(callback)};v.requestVideoFrameCallback(callback);
    }
  }
  function opacityProduct(el){var o=1;for(var n=el;n&&n.nodeType===1;n=n.parentElement)o*=+(getComputedStyle(n).opacity||0);return o}
  function visible(el){
    if(!el||!el.isConnected)return false;
    var s=getComputedStyle(el),r=el.getBoundingClientRect();
    return s.display!=='none'&&s.visibility==='visible'&&r.width>0&&r.height>0&&(!el.checkVisibility||el.checkVisibility({opacityProperty:true,visibilityProperty:true}));
  }
  function entries(){return S.config&&Array.isArray(S.config.entries)?S.config.entries:[]}
  function entryForDraw(draw){return entries().filter(function(e){return e.feed&&e.feed.draw===draw})}
  function labelsForDraw(draw){
    var out=[],seen={};entries().forEach(function(e){var table=e.draws&&e.draws.draws;
      (Array.isArray(table)?table:[]).forEach(function(row){if(row.draw===draw&&finite(row.labelBoxOpacity)&&!seen[draw]){seen[draw]=1;out.push(row)}})});return out;
  }
  function project(m,W,H,x,y){
    var cx=m[0]*x+m[4]*y+m[12],cy=m[1]*x+m[5]*y+m[13],cw=m[3]*x+m[7]*y+m[15];
    return [((cx/cw)+1)/2*W,((cy/cw)+1)/2*H];
  }
  function quad(m,W,H,size){return [project(m,W,H,0,0),project(m,W,H,size[0],0),project(m,W,H,size[0],size[1]),project(m,W,H,0,size[1])]}
  function bounds(points,W,H){
    var xs=points.map(function(p){return p[0]}),ys=points.map(function(p){return p[1]});
    var x0=Math.max(0,Math.ceil(Math.min.apply(null,xs)+3)),x1=Math.min(W,Math.floor(Math.max.apply(null,xs)-3));
    var y0=Math.max(0,Math.ceil(Math.min.apply(null,ys)+3)),y1=Math.min(H,Math.floor(Math.max.apply(null,ys)-3));
    return {x:x0,y:y0,w:Math.max(0,x1-x0),h:Math.max(0,y1-y0)};
  }
  function meanPatch(gl,b){
    if(!b||b.w<1||b.h<1)return null;
    var w=Math.min(16,b.w),h=Math.min(16,b.h),x=b.x+Math.floor((b.w-w)/2),y=b.y+Math.floor((b.h-h)/2);
    var px=new Uint8Array(w*h*4);gl.readPixels(x,y,w,h,gl.RGBA,gl.UNSIGNED_BYTE,px);
    var out=[0,0,0,0];for(var i=0;i<px.length;i+=4)for(var c=0;c<4;c++)out[c]+=px[i+c];
    for(var j=0;j<4;j++)out[j]/=w*h;return {rect:{x:x,y:y,w:w,h:h},mean:out};
  }
  function pixelPatch(gl,b){if(!b||b.w<1||b.h<1)return null;var px=new Uint8Array(b.w*b.h*4);
    gl.readPixels(b.x,b.y,b.w,b.h,gl.RGBA,gl.UNSIGNED_BYTE,px);return {rect:b,pixels:px}}
  function labelStats(before,after,opacity){
    if(!before||!after||before.pixels.length!==after.pixels.length)return null;
    var xs=[],ys=[],sx=0,sy=0;for(var i=0;i<before.pixels.length;i+=4)for(var c=0;c<3;c++){
      var x=before.pixels[i+c],y=after.pixels[i+c];xs.push(x);ys.push(y);sx+=x;sy+=y}
    var n=xs.length,mx=sx/n,my=sy/n,cov=0,v=0,lo=255,hi=0;for(var j=0;j<n;j++){
      cov+=(xs[j]-mx)*(ys[j]-my);v+=(xs[j]-mx)*(xs[j]-mx);lo=Math.min(lo,xs[j]);hi=Math.max(hi,xs[j])}
    return {opacity:opacity,spread:hi-lo,slope:v?cov/v:null,rect:before.rect};
  }
  function wrap(gl,canvas){
    if(gl.__obedMmFeedProbe)return;
    gl.__obedMmFeedProbe=true;
    var O={},G={unit:gl.TEXTURE0,bindings:{},program:null,flip:false,premultiply:false,frame:null,serial:S.contexts.length+1,uploads:0};
    ['texImage2D','activeTexture','bindTexture','pixelStorei','useProgram','getUniformLocation','uniform1f','uniformMatrix4fv','clear','drawArrays','drawElements'].forEach(function(n){O[n]=gl[n]});
    var contextRecord={serial:G.serial,id:canvas.id,createdAt:performance.now(),lost:false};
    S.contexts.push(contextRecord);S.live.push([gl,G]);
    gl.activeTexture=function(u){G.unit=u;return O.activeTexture.apply(gl,arguments)};
    gl.bindTexture=function(target,texture){if(target===gl.TEXTURE_2D)G.bindings[G.unit]=texture;return O.bindTexture.apply(gl,arguments)};
    gl.pixelStorei=function(p,v){if(p===gl.UNPACK_FLIP_Y_WEBGL)G.flip=!!v;if(p===gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL)G.premultiply=!!v;return O.pixelStorei.apply(gl,arguments)};
    gl.useProgram=function(p){G.program=p;return O.useProgram.apply(gl,arguments)};
    gl.getUniformLocation=function(p,n){var q=O.getUniformLocation.apply(gl,arguments);if(q)locationName.set(q,n);return q};
    function setUniform(loc,value){if(!G.program||!loc)return;var u=programUniforms.get(G.program)||{};u[locationName.get(loc)||'?']=value;programUniforms.set(G.program,u)}
    gl.uniform1f=function(loc,v){setUniform(loc,v);return O.uniform1f.apply(gl,arguments)};
    gl.uniformMatrix4fv=function(loc,tr,v){setUniform(loc,Array.prototype.slice.call(v,0,16));return O.uniformMatrix4fv.apply(gl,arguments)};
    gl.texImage2D=function(){
      var src=arguments.length<9?arguments[5]:null,w=arguments.length>=9?arguments[3]:src&&(src.videoWidth||src.width||src.naturalWidth),
          h=arguments.length>=9?arguments[4]:src&&(src.videoHeight||src.height||src.naturalHeight),texture=G.bindings[G.unit];
      G.uploads++;if(G.frame)G.frame.uploads++;
      if(texture)textureInfo.set(texture,{serial:G.serial,ordinal:G.uploads,size:[w,h],flip:G.flip,premultiply:G.premultiply,
        video:!!(src&&typeof src.currentTime==='number'),presentedFrames:src&&src.__obedPresentedFrames,mediaTime:src&&src.__obedMediaTime});
      return O.texImage2D.apply(gl,arguments);
    };
    gl.clear=function(){
      if(G.frame)finishFrame(gl,G);
      G.frame={serial:G.serial,n:S.frames.length+1,t:performance.now(),draws:0,uploads:0,rows:[],labels:[],riders:[],module:moduleRead()};
      return O.clear.apply(gl,arguments);
    };
    function draw(name,args){
      if(!G.frame)return O[name].apply(gl,args);
      var F=G.frame,draw=++F.draws,u=G.program?(programUniforms.get(G.program)||{}):{},matches=entryForDraw(draw),labelReads=[];
      labelsForDraw(draw).forEach(function(row){if(!u.MVPMatrix)return;var points=quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,row.layerSize);
        var b=bounds(points,gl.drawingBufferWidth,gl.drawingBufferHeight),under=pixelPatch(gl,b);if(under)labelReads.push({opacity:row.labelBoxOpacity,under:under})});
      var result=O[name].apply(gl,args);
      labelReads.forEach(function(read){F.labels.push(read)});
      matches.forEach(function(e){
        var size=e.feed.from.size,points=u.MVPMatrix?quad(u.MVPMatrix,gl.drawingBufferWidth,gl.drawingBufferHeight,size):null;
        F.rows.push({serial:G.serial,objectId:e.objectId,draw:draw,t:F.t,quad:points,patch:points?meanPatch(gl,bounds(points,gl.drawingBufferWidth,gl.drawingBufferHeight)):null,
          mixFactor:Object.prototype.hasOwnProperty.call(u,'mixFactor')?u.mixFactor:null,decoder:decoderRead(e.objectId),textures:[0,1].map(function(unit){
            var tex=G.bindings[gl.TEXTURE0+unit],info=tex&&textureInfo.get(tex);return info?{unit:unit,ordinal:info.ordinal,size:info.size,
              video:info.video,presentedFrames:info.presentedFrames,mediaTime:info.mediaTime}:null})});
      });
      return result;
    }
    gl.drawArrays=function(){return draw('drawArrays',arguments)};
    gl.drawElements=function(){return draw('drawElements',arguments)};
    canvas.addEventListener('webglcontextlost',function(){contextRecord.lost=true},true);
  }
  function finishFrame(gl,G){
    var F=G.frame;if(!F)return;
    var canvas=gl.canvas,cr=canvas&&canvas.getBoundingClientRect?canvas.getBoundingClientRect():null;
    entries().forEach(function(e){var d=decoderRead(e.objectId);if(d)F.riders.push({objectId:e.objectId,visible:d.visible,opacityProduct:d.opacityProduct,
      intersectsCanvas:!!(cr&&d.rect&&d.visible&&d.rect.x<cr.right&&d.rect.x+d.rect.w>cr.left&&d.rect.y<cr.bottom&&d.rect.y+d.rect.h>cr.top)});});
    F.labels=F.labels.map(function(read){return labelStats(read.under,pixelPatch(gl,read.under.rect),read.opacity)}).filter(Boolean);
    var errors=[],guard=0,code;while((code=gl.getError())!==gl.NO_ERROR&&guard++<8)errors.push(code);F.glErrors=errors;S.frames.push(F);G.frame=null;
  }
  HTMLCanvasElement.prototype.getContext=function(type){
    var gl=originalGetContext.apply(this,arguments);
    try{if(gl&&/^\d+-canvas$/.test(this.id)&&/webgl/.test(String(type)))wrap(gl,this)}catch(e){noteError('getContext',e)}
    return gl;
  };
  function configure(config){
    S.config=config||{};S.tamper=S.config.tamper||null;
    entries().forEach(function(e){var v=decoderFor(e.objectId);if(v)armDecoder(v,e.objectId)});
    if(S.config.killHoldUpload){
      var api=window.__OBED_MM_FEED__;
      if(api&&typeof api.once==='function'&&!api.__obedProbeOnce){var once=api.once;api.__obedProbeOnce=once;api.once=function(id){S.killedOnce.push({objectId:id,t:performance.now()});return false}}
    }
    if(S.tamper==='after-feed')requestAnimationFrame(afterFeedTamper);
    return true;
  }
  function afterFeedTamper(){
    var api=moduleRead(),found=api&&api.entries&&Object.keys(api.entries).find(function(k){var e=api.entries[k];return e&&e.framesFed>0&&!e.stoodDown});
    if(found){
      var v=decoderFor(found),start=v&&v.__obedPresentedFrames;
      if(v&&typeof v.requestVideoFrameCallback==='function')v.requestVideoFrameCallback(function(){
        var seam=window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.feed,original=seam&&seam.decoderFor;
        S.forcedDecoders[found]=v;
        S.tamper.triggerPresented=v.__obedPresentedFrames;S.tamper.triggeredAt=performance.now();
        if(typeof original==='function')seam.decoderFor=function(id){return id===found?null:original.call(seam,id)};
      });
      S.tamper={kind:'after-feed',objectId:found,lastPresented:start,armedAt:performance.now()};return;
    }
    requestAnimationFrame(afterFeedTamper);
  }
  window.__obedMmFeedProbe={version:1,configure:configure,report:function(){S.live.forEach(function(x){finishFrame(x[0],x[1])});return {kind:'mm-feed',version:1,config:S.config,
    contexts:S.contexts,frames:S.frames,holds:S.holds,media:S.media,errors:S.errors,module:moduleRead(),tamper:S.tamper,killedOnce:S.killedOnce}}};
})();
"""


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _verdict(value: bool | None, reason: str | None = None, **detail: Any) -> dict[str, Any]:
    out = {"verdict": value, **detail}
    if reason:
        out["reason"] = ("inconclusive: " if value is None and not reason.startswith("inconclusive:") else "") + reason
    return out


def feed_interval(record: Any) -> dict[str, float] | None:
    if not isinstance(record, dict) or record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return None
    interval = record.get("interval")
    if not isinstance(interval, dict) or not _finite(interval.get("start")) or not _finite(interval.get("end")):
        return None
    if interval["end"] <= interval["start"]:
        return None
    return {"start": float(interval["start"]), "end": float(interval["end"])}


def verdict_records(
    report: Any, entries: Iterable[dict[str, Any]], *, continuous_expected: bool,
) -> dict[str, dict[str, Any]]:
    """Normalize the in-page producer into fail-closed per-carry scorer records."""
    if not isinstance(report, dict):
        return {}
    published = report.get("verdicts")
    if isinstance(published, dict):
        return {str(key): value for key, value in published.items() if isinstance(value, dict)}
    contexts = [row for row in report.get("contexts") or [] if isinstance(row, dict)]
    frames = [row for row in report.get("frames") or [] if isinstance(row, dict)]
    module = report.get("module") if isinstance(report.get("module"), dict) else {}
    module_entries = module.get("entries") if isinstance(module.get("entries"), dict) else {}
    media_rows = [row for row in report.get("media") or [] if isinstance(row, dict)]
    records: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        object_id = entry.get("objectId")
        rows = [
            row for frame in frames for row in frame.get("rows") or []
            if isinstance(row, dict) and row.get("objectId") == object_id
        ]
        serials = {row.get("serial") for row in rows if isinstance(row.get("serial"), int)}
        usable = bool(serials) and any(row.get("serial") in serials and row.get("lost") is False for row in contexts)
        planned = entry.get("feed") if isinstance(entry.get("feed"), dict) else {}
        expected = [planned.get("from"), planned.get("to")]
        expected = [value for value in expected if isinstance(value, dict)]
        bound = bool(rows) and all(any(
            isinstance(texture, dict) and texture.get("ordinal") == wanted.get("upload")
            and texture.get("size") == wanted.get("size")
            for row in rows for texture in row.get("textures") or []
        ) for wanted in expected)
        times = sorted(float(row["t"]) for row in rows if _finite(row.get("t")))
        interval = {"start": times[0], "end": times[-1]} if len(times) > 1 and times[-1] > times[0] else None
        telemetry = module_entries.get(object_id) if isinstance(module_entries.get(object_id), dict) else {}
        mode = telemetry.get("mode")
        state = telemetry.get("state")
        if mode not in ("continuous", "once", "departure", "standDown"):
            mode = "standDown" if state == "stoodDown" else "continuous" if state in ("armed", "fed") else "once"
        riders = [
            rider for frame in frames for rider in frame.get("riders") or []
            if isinstance(rider, dict) and rider.get("objectId") == object_id
        ]
        labels = [label for frame in frames for label in frame.get("labels") or [] if isinstance(label, dict)]
        presented = [
            row["decoder"].get("presentedFrames") for row in rows if isinstance(row.get("decoder"), dict)
            and _finite(row["decoder"].get("presentedFrames"))
        ]
        common = {"usableContext": usable, "boundTextures": bound, "interval": interval}
        feed = {
            **common, "mode": mode, "reads": [], "presentedFrames": presented,
            "advancing": len(set(presented)) > 1, "continuousCoverage": False,
            "maxInterFeedGapMs": telemetry.get("maxInterFeedGapMs"),
            "maxInterFeedGapLimitMs": telemetry.get("maxInterFeedGapLimitMs"),
        }
        hold = telemetry.get("hold") if isinstance(telemetry.get("hold"), dict) else {
            **common, "mode": "standDown" if mode == "standDown" else "departure", "reads": [],
        }
        poster = telemetry.get("posterHold") if isinstance(telemetry.get("posterHold"), dict) else None
        if poster is None:
            media = [row for row in media_rows if row.get("objectId") == object_id]
            pauses = [row for row in media if row.get("kind") == "pause" and _finite(row.get("t"))]
            pause = pauses[-1] if pauses else None
            plays = [row for row in media if row.get("kind") == "play" and pause and row.get("t", -math.inf) > pause["t"]]
            play = plays[0] if plays else None
            before = [row for row in media if row.get("kind") == "videoFrame" and pause and row.get("t", math.inf) <= pause["t"]]
            after = [row for row in media if row.get("kind") == "videoFrame" and play and row.get("t", -math.inf) >= play["t"]]
            if pause and play and before and after:
                last_upload = telemetry.get("lastUploadedFrame", telemetry.get("lastPresentedUploaded"))
                poster = {
                    "mode": "standDown" if mode == "standDown" else "departure",
                    "pauseTime": pause["t"], "settleTime": play["t"],
                    "pauseCurrentTime": pause.get("currentTime"), "settleCurrentTime": play.get("currentTime"),
                    "pauseFrame": before[-1].get("presentedFrames"), "firstAfterFrame": after[0].get("presentedFrames"),
                    "seeked": any(row.get("kind") == "seeking" and pause["t"] <= row.get("t", -math.inf) <= play["t"] for row in media),
                    "resumedFromZero": after[0].get("mediaTime", 1) <= 0,
                    "lastUploadedFrame": last_upload,
                }
            else:
                poster = {"mode": "standDown" if mode == "standDown" else "departure"}
        records[entry["id"]] = {
            "mode": mode, **common, "continuousExpected": continuous_expected,
            "feed": feed, "rider": {"riders": riders}, "labels": {"labels": labels},
            "hold": hold, "poster": poster,
            "artwork": {"reads": []},
        }
    return records


def score_feed_live(record: Any, *, continuous_expected: bool = True, alpha_floor: float = ALPHA_POSTER_FLOOR) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "feed evidence is missing")
    reads = record.get("reads")
    if not isinstance(reads, list):
        return _verdict(None, "feed reads are unreadable")
    wanted = set(READ_PROGRESS)
    got = {float(r.get("progress")) for r in reads if isinstance(r, dict) and _finite(r.get("progress"))}
    if got != wanted:
        return _verdict(None, f"feed reads cover {sorted(got)}, expected {sorted(wanted)}")
    if continuous_expected and record.get("mode") != "continuous":
        return _verdict(False, "continuous feed was expected", mode=record.get("mode"))
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return _verdict(None, "the GL context or bound textures were unavailable")
    checks: list[dict[str, Any]] = []
    ambiguous = False
    for read in sorted(reads, key=lambda r: r["progress"]):
        if read.get("patchInside") is not True or read.get("coveredByLaterDraw") is not False:
            return _verdict(None, "a feed patch is outside the leaf or covered by a later draw", reads=reads)
        kind = read.get("kind")
        if kind == "counter":
            if not _finite(read.get("counter")) or not _finite(read.get("referenceCounter")):
                return _verdict(None, "a counter read is undecodable", reads=reads)
            ok = abs(read["counter"] - read["referenceCounter"]) <= 1
        elif kind == "alpha":
            if not _finite(read.get("dVideo")) or not _finite(read.get("dPoster")):
                return _verdict(None, "an Alpha distance is unreadable", reads=reads)
            if read["dPoster"] < alpha_floor:
                ambiguous = True
                ok = True
            else:
                ok = read["dVideo"] <= read["dPoster"] / 2
        else:
            return _verdict(None, f"unknown feed read kind {kind!r}")
        checks.append({"progress": read["progress"], "ok": ok})
    if not all(row["ok"] for row in checks):
        return _verdict(False, "a sampled GL patch did not match the live decoder", checks=checks)
    if ambiguous:
        return _verdict(None, "the poster/live separation is below the registered floor", checks=checks)
    advancing = record.get("advancing") is True or (
        isinstance(record.get("presentedFrames"), list) and len(set(record["presentedFrames"])) >= 2
    )
    if not advancing:
        return _verdict(False, "decoder frames did not advance", checks=checks)
    if continuous_expected:
        if record.get("continuousCoverage") is not True:
            return _verdict(False, "continuous upload coverage is incomplete", checks=checks)
        gap, limit = record.get("maxInterFeedGapMs"), record.get("maxInterFeedGapLimitMs")
        if not _finite(gap) or not _finite(limit):
            return _verdict(None, "the maximum inter-feed gap is unreadable", checks=checks)
        if gap > limit:
            return _verdict(False, "the maximum inter-feed gap exceeds the paint-coverage limit", gapMs=gap, limitMs=limit)
    return _verdict(True, checks=checks, interval=feed_interval(record))


def score_no_rider_above_canvas(record: Any) -> dict[str, Any]:
    frames = record.get("riders") if isinstance(record, dict) else None
    if not isinstance(frames, list) or not frames:
        return _verdict(None, "no rider census was recorded")
    if not all(isinstance(row, dict) and isinstance(row.get("visible"), bool) and _finite(row.get("opacityProduct"))
               and isinstance(row.get("intersectsCanvas"), bool) for row in frames):
        return _verdict(None, "a rider census row is unreadable")
    offenders = [row for row in frames if row["visible"] and row["intersectsCanvas"] and row["opacityProduct"] > RIDER_OPACITY_FLOOR]
    return _verdict(not offenders, "a carried decoder composited above the GL canvas" if offenders else None,
                    offenders=offenders[:10], sampleCount=len(frames))


def score_labels_over_feed(record: Any) -> dict[str, Any]:
    rows = record.get("labels") if isinstance(record, dict) else None
    if not isinstance(rows, list) or not rows:
        return _verdict(None, "no label-over-feed reads were recorded")
    checks = []
    for row in rows:
        if not isinstance(row, dict) or not all(_finite(row.get(k)) for k in ("opacity", "spread", "slope")):
            return _verdict(None, "a label-over-feed read is unreadable")
        if row["spread"] < LABEL_SPREAD_FLOOR:
            return _verdict(None, "the under-label spread is below 24", labels=rows)
        expected = 1 - row["opacity"]
        checks.append({**row, "expected": expected, "ok": abs(row["slope"] - expected) <= LABEL_SLOPE_TOLERANCE})
    return _verdict(all(row["ok"] for row in checks), "a label did not composite over the feed" if not all(row["ok"] for row in checks) else None,
                    labels=checks)


def score_hold_frame(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "hold-frame evidence is missing")
    if record.get("usableContext") is not True or record.get("boundTextures") is not True:
        return _verdict(None, "the exact-hold rendering path is unavailable")
    mode = record.get("mode")
    if mode not in ("departure", "standDown"):
        return _verdict(None, f"unknown hold mode {mode!r}")
    if mode == "standDown" and not (record.get("successfulFeed") is True and record.get("advancedDecoder") is True):
        return _verdict(None, "post-feed stand-down lacks successful-feed and advanced-decoder evidence")
    if mode == "standDown" and record.get("reuploadAfterStandDown") is not False:
        return _verdict(False, "a texture was uploaded after stand-down")
    target = record.get("lastPresentedBeforeDeparture") if mode == "departure" else record.get("lastUploadedFrame")
    reads = record.get("reads")
    if not isinstance(target, int) or isinstance(target, bool) or not isinstance(reads, list) or len(reads) < 3:
        return _verdict(None, "the held target or its first/middle/last reads are missing")
    if {read.get("phase") for read in reads if isinstance(read, dict)} != {"first", "middle", "last"}:
        return _verdict(None, "the held reads do not cover first, middle, and last draw")
    for read in reads:
        if not isinstance(read, dict) or not isinstance(read.get("bestFrame"), int) or not _finite(read.get("matchMargin")) \
                or not _finite(read.get("requiredMargin")):
            return _verdict(None, "a held-frame match is unreadable", reads=reads)
        if read["matchMargin"] < read["requiredMargin"]:
            return _verdict(None, "a held-frame match is ambiguous", reads=reads)
    matches = [read["bestFrame"] for read in reads]
    return _verdict(all(frame == target for frame in matches), "the GL canvas did not retain the exact target frame" if any(frame != target for frame in matches) else None,
                    mode=mode, targetFrame=target, matchedFrames=matches,
                    interval=feed_interval(record) or record.get("interval"))


def score_poster_hold(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return _verdict(None, "poster-hold evidence is missing")
    required = ("pauseTime", "settleTime", "pauseCurrentTime", "settleCurrentTime")
    if not all(_finite(record.get(k)) for k in required) or not all(
        isinstance(record.get(k), int) and not isinstance(record.get(k), bool)
        for k in ("pauseFrame", "firstAfterFrame")
    ):
        return _verdict(None, "the poster-hold clock or frame record is unreadable")
    if record["settleTime"] < record["pauseTime"]:
        return _verdict(None, "the poster-hold interval is reversed")
    if record.get("seeked") is not False:
        return _verdict(False, "the held decoder sought during the move")
    if abs(record["settleCurrentTime"] - record["pauseCurrentTime"]) > record.get("clockToleranceS", 0.05):
        return _verdict(False, "the decoder clock advanced during the hold")
    if record["firstAfterFrame"] <= 0 or record.get("resumedFromZero") is True:
        return _verdict(False, "the decoder restarted from frame zero")
    mode = record.get("mode", "departure")
    resumed_from_pause = record["firstAfterFrame"] == record["pauseFrame"] + 1
    if not resumed_from_pause:
        return _verdict(False, "the first frame after settle was not held+1", exactHeldPlusOne=False)
    if mode != "standDown" and mode != "departure":
        return _verdict(None, f"unknown poster-hold mode {mode!r}")
    last_upload = record.get("lastUploadedFrame")
    if mode == "standDown" and (not isinstance(last_upload, int) or isinstance(last_upload, bool)):
        return _verdict(None, "the last uploaded frame is unreadable")
    if mode == "standDown" and record["pauseFrame"] < last_upload:
        return _verdict(None, "the pause frame precedes the retained upload")
    discontinuity = mode == "standDown" and record["pauseFrame"] > last_upload
    return _verdict(True, mode=mode, exactHeldPlusOne=resumed_from_pause if not discontinuity else False,
                    resumedFromPausePlusOne=resumed_from_pause,
                    resumptionDiscontinuity=(record["pauseFrame"] - last_upload if discontinuity else 0),
                    resumedFromFrame=record["pauseFrame"])


def score_artwork_above(record: Any) -> dict[str, Any]:
    rows = record.get("reads") if isinstance(record, dict) else None
    if not isinstance(rows, list) or not rows:
        return _verdict(None, "no settled artwork reads were recorded")
    if not all(isinstance(row, dict) and isinstance(row.get("artworkAbove"), bool) for row in rows):
        return _verdict(None, "a settled artwork read is unreadable")
    return _verdict(all(row["artworkAbove"] for row in rows),
                    "authored artwork was not above the settled decoder" if not all(row["artworkAbove"] for row in rows) else None,
                    reads=rows)


def combine(*verdicts: dict[str, Any]) -> bool | None:
    values = [row.get("verdict") for row in verdicts]
    return None if any(value is None for value in values) else all(values)


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(v) for v in values if _finite(v))
    if not ordered:
        return None
    position = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

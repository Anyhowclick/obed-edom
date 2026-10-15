"""Compositor placement probe: pinned assets, probe page and the pure snap/frac classifier (plan keynote_live_cef_placement §11.1)."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image

PATTERN_SHA256 = "7b7d66b582d1b0df0c27c11bd945c1606d11ad4d34f5031b726ee22319d19870"
MOTION_SHA256 = "e4640a667bbbdfca47dbde5942455d262c69a4e80c031b22cada0753763b3bfe"
MANIFEST_SHA256 = "c804288b674507df28c6d165f09634d6483458cb4f40fb74ff73c98ec29d0bcf"

_DATA = Path(__file__).resolve().parent / "data"
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_POSES = ((0.352, 0.036), (0.73, 0.41))
_VIDEO_SIZE = (1920, 540)
_COLOR_TUPLE = ("bt709", "bt709", "bt709", False)
_GPU_TABLE = np.asarray(
    [
        round(
            255
            * (
                12.92 * ((value / 255) ** 1.961)
                if (value / 255) ** 1.961 <= 0.0031308
                else 1.055 * ((value / 255) ** 1.961) ** (1 / 2.4) - 0.055
            )
        )
        for value in range(256)
    ],
    dtype=np.uint8,
)


class ProbeVerdict(str, Enum):
    SNAP = "snap"
    FRAC = "frac"
    UNKNOWN = "unknown"


class ToneMap(str, Enum):
    IDENTITY = "identity"
    GPU_ANALYTIC = "gpu_analytic"


@dataclass(frozen=True)
class ProbeAsset:
    name: str
    sha256: str
    data: bytes


@dataclass(frozen=True)
class ProbeAssets:
    manifest_sha256: str
    pattern: ProbeAsset
    motion: ProbeAsset


@dataclass(frozen=True)
class ProbeSpec:
    run_id: str
    width: int
    height: int
    fps: int
    dpr: float


@dataclass(frozen=True)
class ProbeIdentity:
    run_id: str
    source_uuid: str | None
    target_id: str
    context_id: str
    connection_generation: int
    ua: str
    dpr: float


@dataclass(frozen=True)
class ProbeCapture:
    identity: ProbeIdentity
    sequence: int
    nonce: str
    phase: str
    pose: int | None
    png: bytes
    paint_observed_s: float
    capture_started_s: float
    capture_finished_s: float


@dataclass(frozen=True)
class PoseGeometry:
    pose: int
    rect: tuple[float, float, float, float]
    content_box: tuple[float, float, float, float]
    box: tuple[int, int, int, int]
    snap_dy: int
    frac_dy: int


@dataclass(frozen=True)
class ClassifierInput:
    spec: ProbeSpec
    assets_sha256: tuple[str, str, str]
    identity: ProbeIdentity
    ready_state: int
    video_size: tuple[int, int]
    color_tuple: tuple[str, str, str, bool]
    freshness: tuple[ProbeCapture, ...]
    poses: tuple[PoseGeometry, ...]
    captures: tuple[ProbeCapture, ...]


@dataclass(frozen=True)
class PoseScore:
    pose: int
    tone_map: ToneMap
    snap_share: float
    frac_share: float
    inner_pixels: int


@dataclass(frozen=True)
class ProbeResult:
    verdict: ProbeVerdict
    tone_map: ToneMap | None
    grant_eligible: bool
    reason: str
    scores: tuple[PoseScore, ...]


def load_probe_assets() -> ProbeAssets:
    manifest_path = _DATA / "placement_probe.json"
    manifest_data = manifest_path.read_bytes()
    if _sha256(manifest_data) != MANIFEST_SHA256:
        raise ValueError("placement probe manifest digest mismatch")
    try:
        manifest = json.loads(manifest_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("placement probe manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("placement probe manifest schema mismatch")
    pattern = _load_asset(manifest, "pattern", "placement_probe.mp4", PATTERN_SHA256)
    motion = _load_asset(manifest, "motion", "placement_motion.mp4", MOTION_SHA256)
    generator = manifest.get("generator")
    if not isinstance(generator, dict) or generator.get("repeatSha256") != PATTERN_SHA256:
        raise ValueError("placement probe repeat digest mismatch")
    if (
        manifest["pattern"].get("width"),
        manifest["pattern"].get("height"),
        manifest["pattern"].get("fps"),
        manifest["pattern"].get("durationS"),
        manifest["pattern"].get("frameTimeS"),
        tuple(manifest["pattern"].get("colorTuple", ())),
    ) != (1920, 540, 30, 3, 1, _COLOR_TUPLE):
        raise ValueError("placement probe pattern metadata mismatch")
    if (
        manifest["motion"].get("width"),
        manifest["motion"].get("height"),
        manifest["motion"].get("fps"),
        manifest["motion"].get("durationS"),
    ) != (1920, 540, 30, 3):
        raise ValueError("placement probe motion metadata mismatch")
    return ProbeAssets(MANIFEST_SHA256, pattern, motion)


def render_probe_page(spec: ProbeSpec) -> bytes:
    if _RUN_ID.fullmatch(spec.run_id) is None:
        raise ValueError("probe run_id must be 32 lowercase hexadecimal characters")
    if spec.width != 1920 or spec.height != 1080 or spec.fps <= 0 or not math.isfinite(spec.dpr) or spec.dpr <= 0:
        raise ValueError("invalid probe source specification")
    payload = json.dumps(
        {"runId": spec.run_id, "width": spec.width, "height": spec.height, "fps": spec.fps, "dpr": spec.dpr},
        separators=(",", ":"),
    )
    return _PROBE_PAGE.replace("__OBED_SPEC__", payload).encode()


def classify_probe(data: ClassifierInput) -> ProbeResult:
    if data.spec.dpr != 1 or data.identity.dpr != 1:
        return _unknown("unsupported-dpr")
    try:
        decoded = _validate_input(data)
    except _StaleCapture:
        return _unknown("stale-capture")
    except _UnstableCapture:
        return _unknown("unstable-capture")
    except (ValueError, TypeError, OSError):
        return _unknown("invalid-evidence")

    scores = []
    rules: dict[ToneMap, ProbeVerdict] = {}
    for tone_map in ToneMap:
        pose_rules = []
        for geometry, image in decoded:
            video, snap, frac = _candidate_regions(image, geometry)
            table = None if tone_map is ToneMap.IDENTITY else _GPU_TABLE
            snap_share, inner_pixels = _share(video, snap, table)
            frac_share, _ = _share(video, frac, table)
            scores.append(PoseScore(geometry.pose, tone_map, snap_share, frac_share, inner_pixels))
            pose_rules.append(_pose_rule(snap_share, frac_share))
        if pose_rules[0] is not None and pose_rules[0] is pose_rules[1]:
            rules[tone_map] = pose_rules[0]
    result_scores = tuple(scores)
    if len(rules) != 1:
        return _unknown("ambiguous", result_scores)
    tone_map, verdict = next(iter(rules.items()))
    if tone_map is ToneMap.IDENTITY:
        return ProbeResult(verdict, tone_map, False, "software-map", result_scores)
    return ProbeResult(verdict, tone_map, True, "classified", result_scores)


class _StaleCapture(ValueError):
    pass


class _UnstableCapture(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_asset(manifest: dict[str, object], key: str, filename: str, expected_sha256: str) -> ProbeAsset:
    record = manifest.get(key)
    if not isinstance(record, dict) or record.get("file") != filename or record.get("sha256") != expected_sha256:
        raise ValueError(f"placement probe {key} manifest mismatch")
    data = (_DATA / filename).read_bytes()
    if _sha256(data) != expected_sha256 or record.get("bytes") != len(data):
        raise ValueError(f"placement probe {key} digest mismatch")
    return ProbeAsset(filename, expected_sha256, data)


def _unknown(reason: str, scores: tuple[PoseScore, ...] = ()) -> ProbeResult:
    return ProbeResult(ProbeVerdict.UNKNOWN, None, False, reason, scores)


def _expected_geometry(pose: int) -> PoseGeometry:
    fx, fy = _POSES[pose]
    x = 10 + fx
    y = 10 + fy
    width = 480.53125
    height = 135.140625
    scale = min(width / _VIDEO_SIZE[0], height / _VIDEO_SIZE[1])
    content_width = _VIDEO_SIZE[0] * scale
    content_height = _VIDEO_SIZE[1] * scale
    x0 = math.floor(x)
    y0 = math.floor(y)
    box = (x0, y0, math.ceil(x + width) - x0 + 1, math.ceil(y + height) - y0 + 1)
    content_box = (
        x + (width - content_width) / 2,
        y + (height - content_height) / 2,
        content_width,
        content_height,
    )
    return PoseGeometry(pose, (x, y, width, height), content_box, box, 140, 280)


def _same_geometry(actual: PoseGeometry, expected: PoseGeometry) -> bool:
    return (
        actual.pose == expected.pose
        and len(actual.rect) == 4
        and len(actual.content_box) == 4
        and len(actual.box) == 4
        and actual.box == expected.box
        and actual.snap_dy == expected.snap_dy
        and actual.frac_dy == expected.frac_dy
        and all(abs(left - right) <= 1 / 256 for left, right in zip(actual.rect, expected.rect))
        and all(abs(left - right) <= 1 / 256 for left, right in zip(actual.content_box, expected.content_box))
    )


def _capture_image(capture: ProbeCapture, spec: ProbeSpec) -> np.ndarray:
    if not all(
        math.isfinite(value)
        for value in (capture.paint_observed_s, capture.capture_started_s, capture.capture_finished_s)
    ):
        raise ValueError("capture time is invalid")
    if capture.capture_finished_s < capture.capture_started_s:
        raise ValueError("capture time is reversed")
    if capture.capture_finished_s - capture.capture_started_s > 2:
        raise ValueError("capture exceeded its deadline")
    if capture.capture_started_s - capture.paint_observed_s < 0.3:
        raise ValueError("capture did not settle")
    with Image.open(io.BytesIO(capture.png)) as image:
        rgba = image.convert("RGBA")
    expected = (round(spec.width * spec.dpr), round(spec.height * spec.dpr))
    if rgba.size != expected:
        raise ValueError("capture size mismatch")
    return np.asarray(rgba)


def _validate_capture(capture: ProbeCapture, data: ClassifierInput) -> np.ndarray:
    if capture.identity != data.identity or _NONCE.fullmatch(capture.nonce) is None:
        raise ValueError("capture identity mismatch")
    image = _capture_image(capture, data.spec)
    if _decode_nonce(image) != capture.nonce:
        raise _StaleCapture("capture nonce mismatch")
    return image


def _validate_input(data: ClassifierInput) -> list[tuple[PoseGeometry, np.ndarray]]:
    if (
        data.spec.run_id != data.identity.run_id
        or _RUN_ID.fullmatch(data.spec.run_id) is None
        or not data.identity.target_id
        or not data.identity.context_id
        or not data.identity.ua
        or not isinstance(data.identity.connection_generation, int)
        or data.identity.connection_generation < 0
        or data.spec.width != 1920
        or data.spec.height != 1080
        or data.spec.fps <= 0
        or data.assets_sha256 != (MANIFEST_SHA256, PATTERN_SHA256, MOTION_SHA256)
        or data.ready_state < 2
        or data.video_size != _VIDEO_SIZE
        or data.color_tuple != _COLOR_TUPLE
        or len(data.freshness) < 3
        or len(data.poses) != 2
        or len(data.captures) != 4
    ):
        raise ValueError("probe metadata mismatch")
    expected = tuple(_expected_geometry(index) for index in range(2))
    if any(not _same_geometry(actual, wanted) for actual, wanted in zip(data.poses, expected)):
        raise ValueError("probe geometry mismatch")
    all_captures = (*data.freshness, *data.captures)
    if any(capture.sequence <= 0 for capture in all_captures):
        raise ValueError("capture sequence is invalid")
    if any(right.sequence <= left.sequence for left, right in zip(all_captures, all_captures[1:])):
        raise ValueError("capture sequence is not increasing")
    if len({capture.nonce for capture in all_captures}) != len(all_captures):
        raise _StaleCapture("capture nonce was reused")
    if any(right.capture_started_s - left.capture_started_s < 0.2 for left, right in zip(all_captures, all_captures[1:])):
        raise ValueError("captures were not paced")
    if all_captures[-1].capture_finished_s - all_captures[0].paint_observed_s > 15:
        raise ValueError("measurement exceeded its budget")

    motion_images = []
    for capture in data.freshness:
        if capture.phase != "motion" or capture.pose is not None:
            raise ValueError("invalid freshness capture")
        motion_images.append(_validate_capture(capture, data))
    motion_regions = [_video_region(image, expected[0], include_alpha=True) for image in motion_images]
    if len({_sha256(region.tobytes()) for region in motion_regions}) != len(motion_regions):
        raise _StaleCapture("motion frame repeated")
    if len({_decode_motion_counter(region[:, :, :3]) for region in motion_regions}) != len(motion_regions):
        raise _StaleCapture("motion counter repeated")

    decoded = []
    for index, geometry in enumerate(expected):
        pair = data.captures[index * 2 : index * 2 + 2]
        if any(capture.phase != "pattern" or capture.pose != index for capture in pair):
            raise ValueError("invalid pattern capture")
        images = tuple(_validate_capture(capture, data) for capture in pair)
        for left, right in zip(
            _candidate_regions(images[0], geometry, include_alpha=True),
            _candidate_regions(images[1], geometry, include_alpha=True),
        ):
            if not np.array_equal(left, right):
                raise _UnstableCapture("pattern capture pair changed")
        decoded.append((geometry, images[0]))
    return decoded


def _box_region(
    image: np.ndarray, box: tuple[int, int, int, int], dy: int = 0, *, include_alpha: bool = False
) -> np.ndarray:
    x, y, width, height = box
    region = image[y + dy : y + dy + height, x : x + width]
    if region.shape != (height, width, 4):
        raise ValueError("probe region is outside the capture")
    return region if include_alpha else region[:, :, :3]


def _video_region(image: np.ndarray, geometry: PoseGeometry, *, include_alpha: bool = False) -> np.ndarray:
    return _box_region(image, geometry.box, include_alpha=include_alpha)


def _candidate_regions(
    image: np.ndarray, geometry: PoseGeometry, *, include_alpha: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        _video_region(image, geometry, include_alpha=include_alpha),
        _box_region(image, geometry.box, geometry.snap_dy, include_alpha=include_alpha),
        _box_region(image, geometry.box, geometry.frac_dy, include_alpha=include_alpha),
    )


def _decode_nonce(image: np.ndarray) -> str:
    bits = []
    for index in range(128):
        x = 1600 + (index % 16) * 8
        y = 16 + (index // 16) * 8
        cell = image[y + 3 : y + 5, x + 3 : x + 5]
        if cell.shape != (2, 2, 4) or np.any(cell[:, :, 3] != 255):
            raise _StaleCapture("nonce cell is malformed")
        rgb = cell[:, :, :3]
        if np.all(rgb <= 32):
            bits.append("0")
        elif np.all(rgb >= 223):
            bits.append("1")
        else:
            raise _StaleCapture("nonce cell is undecodable")
    return f"{int(''.join(bits), 2):032x}"


def _decode_motion_counter(region: np.ndarray) -> int:
    bits = []
    height, width, _ = region.shape
    for index in range(16):
        cell = region[height // 2, round((index + 0.5) * width / 16)]
        if np.all(cell <= 32):
            bits.append(0)
        elif np.all(cell >= 223):
            bits.append(1)
        else:
            raise ValueError("motion counter is undecodable")
    value = 0
    for bit in bits:
        value = value * 2 + bit
    return value


def _share(video: np.ndarray, candidate: np.ndarray, table: np.ndarray | None) -> tuple[float, int]:
    if video.shape != candidate.shape or video.shape[0] <= 6 or video.shape[1] <= 6:
        raise ValueError("empty classifier mask")
    mapped = candidate if table is None else table[candidate]
    difference = np.abs(video.astype(np.int16) - mapped.astype(np.int16)).max(axis=2)
    inner = difference[3:-3, 3:-3]
    if inner.size == 0:
        raise ValueError("empty classifier mask")
    return float(np.count_nonzero(inner > 4) / inner.size), int(inner.size)


def _pose_rule(snap_share: float, frac_share: float) -> ProbeVerdict | None:
    if snap_share <= 0.02 and frac_share >= 0.20:
        return ProbeVerdict.SNAP
    if frac_share <= 0.02 and snap_share >= 0.20:
        return ProbeVerdict.FRAC
    return None


_PROBE_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#404040}canvas,video{display:block}</style></head>
<body><script>
(()=>{"use strict";
const spec=__OBED_SPEC__,poses=[[.352,.036],[.73,.41]],state={sequence:0,paintedSequence:0,phase:null,pose:null,error:null,pending:false,geometry:null};
const host=document.createElement("div");host.id="obed-probe";host.style.cssText=`position:fixed;left:0;top:0;width:${spec.width}px;height:${spec.height}px;background:#404040;overflow:hidden`;
const l1=document.createElement("div"),l2=document.createElement("div");l1.style.cssText="position:absolute;left:0;top:0;width:700px;height:200px;transform-style:flat";l2.style.cssText="position:absolute;left:0;top:0;width:600px;height:180px;transform-style:flat";
const video=document.createElement("video");video.id="obed-probe-video";video.muted=true;video.playsInline=true;video.style.cssText="position:absolute;left:0;top:0;width:480.53125px;height:135.140625px";
const snap=document.createElement("canvas"),frac=document.createElement("canvas"),nonce=document.createElement("canvas");nonce.width=128;nonce.height=64;nonce.style.cssText="position:absolute;left:1600px;top:16px;width:128px;height:64px";
l2.appendChild(video);l1.appendChild(l2);host.append(l1,snap,frac,nonce);document.body.appendChild(host);
function raf(){return new Promise(resolve=>requestAnimationFrame(resolve))}
function source(name){return new URL(name,location.href).href}
function loaded(){if(video.readyState>=2)return Promise.resolve();return new Promise((resolve,reject)=>{const done=()=>{clearTimeout(timer);resolve()};const timer=setTimeout(()=>reject(new Error("video load timeout")),2000);video.addEventListener("loadeddata",done,{once:true})})}
async function select(name){const url=source(name);if(video.src!==url){video.pause();video.src=url;video.load()}await loaded()}
function setPose(index){const p=poses[index];l1.style.transform=`matrix(1,0,0,1,${6+p[0]*.5},${4+p[1]*.5})`;l2.style.transform=`matrix(1,0,0,1,${4+p[0]*.5},${6+p[1]*.5})`}
function geometry(index){const r=video.getBoundingClientRect(),vw=video.videoWidth,vh=video.videoHeight,f=Math.min(r.width/vw,r.height/vh),cw=vw*f,ch=vh*f,cx=r.left+(r.width-cw)/2,cy=r.top+(r.height-ch)/2,x0=Math.floor(r.left),y0=Math.floor(r.top),w=Math.ceil(r.right)-x0+1,h=Math.ceil(r.bottom)-y0+1;return{pose:index,rect:[r.left,r.top,r.width,r.height],contentBox:[cx,cy,cw,ch],box:[x0,y0,w,h],snapDy:140,fracDy:280}}
function drawCandidate(canvas,g,mode){const p=devicePixelRatio||1,[x0,y0,w,h]=g.box,[cx,cy,cw,ch]=g.contentBox,r=g.rect;canvas.width=Math.round(w*p);canvas.height=Math.round(h*p);canvas.style.cssText=`position:absolute;left:${x0}px;top:${y0+(mode==="snap"?g.snapDy:g.fracDy)}px;width:${w}px;height:${h}px`;const ctx=canvas.getContext("2d",{alpha:false});ctx.fillStyle="#404040";ctx.fillRect(0,0,canvas.width,canvas.height);const ox=mode==="snap"?Math.round(cx*p)/p:r[0]+Math.round((cx-r[0])*p)/p,oy=mode==="snap"?Math.round(cy*p)/p:r[1]+Math.round((cy-r[1])*p)/p;ctx.drawImage(video,(ox-x0)*p,(oy-y0)*p,Math.round(cw*p),Math.round(ch*p))}
function paintNonce(value){const ctx=nonce.getContext("2d",{alpha:false}),bits=BigInt("0x"+value);for(let i=0;i<128;i++){ctx.fillStyle=((bits>>BigInt(127-i))&1n)?"#fff":"#000";ctx.fillRect((i%16)*8,Math.floor(i/16)*8,8,8)}}
async function seekPattern(){await select("placement_probe.mp4");video.loop=false;video.pause();if(Math.abs(video.currentTime-1)>.0001){await new Promise((resolve,reject)=>{const done=()=>{clearTimeout(timer);resolve()};const timer=setTimeout(()=>reject(new Error("video seek timeout")),2000);video.addEventListener("seeked",done,{once:true});video.currentTime=1})}if(video.requestVideoFrameCallback)await Promise.race([new Promise(resolve=>video.requestVideoFrameCallback(resolve)),new Promise(resolve=>setTimeout(resolve,100))])}
async function run(command){try{state.error=null;paintNonce(command.nonce);if(command.phase==="motion"){setPose(0);state.geometry=null;await select("placement_motion.mp4");video.loop=true;await video.play()}else{setPose(command.pose);await seekPattern();state.geometry=geometry(command.pose);drawCandidate(snap,state.geometry,"snap");drawCandidate(frac,state.geometry,"frac")}for(let i=0;i<6;i++)await raf();await raf();state.paintedSequence=command.sequence}catch(error){state.error=String(error&&error.message||error)}finally{state.pending=false}}
function colorTuple(){try{const frame=new VideoFrame(video),color=frame.colorSpace,result=[color.primaries||null,color.transfer||null,color.matrix||null,typeof color.fullRange==="boolean"?color.fullRange:null];frame.close();return result}catch(_){return[null,null,null,null]}}
const api={command(command){if(!command||command.runId!==spec.runId||!Number.isInteger(command.sequence)||command.sequence<=state.sequence||state.pending||!/^[0-9a-f]{32}$/.test(command.nonce)||!(command.phase==="motion"&&command.pose===null||command.phase==="pattern"&&(command.pose===0||command.pose===1)))return false;state.sequence=command.sequence;state.phase=command.phase;state.pose=command.pose;state.pending=true;void run(command);return true},snapshot(){return{runId:spec.runId,sequence:state.sequence,paintedSequence:state.paintedSequence,phase:state.phase,pose:state.pose,readyState:video.readyState,videoSize:[video.videoWidth,video.videoHeight],colorTuple:colorTuple(),dpr:devicePixelRatio||1,ua:navigator.userAgent,geometry:state.geometry,error:state.error}}};
Object.defineProperty(window,"__obedProbe",{value:api,writable:false,configurable:false,enumerable:false});
})();
</script></body></html>"""

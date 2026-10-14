"""The producer contract (`scripts/live_evidence_contract.py`, plan `keynote_live_continuity_contract.plan.md` §2).

Three checks, each parametrized:
1. every producer-legal shape in `tests/fixtures/live_continuity/contract/legal.json` (excerpts of retained artifacts,
   with their source paths, plus the rare legal shapes no artifact retains, each citing its producer line) is accepted;
2. one violation per clause class per kind is rejected with its clause;
3. real producer output under Node (`SAMPLER_JS` rows and meta, the paint instrument's pre-paint reads, the core's
   notes and snapshot) meets the contract.
The wiring of each ingestion point lives with that point's fixtures (probe, managed, P2).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

REPO = Path(__file__).resolve().parent.parent
for sub in ("scripts", "src"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import live_evidence_contract as contract  # noqa: E402
from obed_edom import p2_verdict  # noqa: E402

LEGAL = {c["name"]: c for c in json.loads((REPO / "tests/fixtures/live_continuity/contract/legal.json").read_text())["cases"]}
#: No retained artifact holds a cleared-src `fromDom` entry (core:185-190 reads `movieKeyFor`, core:455-457). Only
#: `stash` preserves, right after stamping a planned movie (core:918-943); a clear never restamps (core:466-468,
#: 2026-2027); a different asset unpreserves before restamping (core:485-490), its `prev` never empty on a preserved
#: decoder since preserving needs the instance only `reidentify` stamps alongside `__obedAssetKey` (core:470-491).
_CLEARED = copy.deepcopy(LEGAL["refusal-read-pool-and-fromDom-hold-one-decoder"])
_CLEARED.update(name="refusal-read-fromDom-cleared-src-keeps-its-stamp", source="core:185-190")
_CLEARED["record"]["poolSnapshot"][-1]["key"] = ""
LEGAL[_CLEARED["name"]] = _CLEARED


def _load_probe():
    spec = importlib.util.spec_from_file_location("live_continuity_probe", REPO / "scripts" / "live_continuity_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()

CHECKS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "rows": lambda case: contract.sample_rows(case["record"], schema=case.get("schema")),
    "refusalRead": lambda case: contract.refusal_read(case["record"], "read"),
    "evidence": lambda case: contract.evidence(case["record"]),
    "gl": lambda case: contract.gl_read(case["record"], "gl"),
    "handback": lambda case: contract.handback_record(case["record"]),
    "forceWrap": lambda case: contract.force_wrap(case["record"]),
    "carryCover": lambda case: contract.carry_cover(case["record"]["rows"], case["record"]["notes"], case["record"]["stageMap"]),
    "managedRun": lambda case: contract.managed_run(case["record"]),
    "painting": lambda case: contract.painting(case["record"], "painting"),
    "pool": lambda case: contract.pool(case["record"], "pool"),
    "notes:refusal": lambda case: contract.notes(case["record"], "coreEvents", contract.REFUSAL_NOTE_KINDS),
    "nullControl": lambda case: p2_verdict._null_control_problems(case["record"]),
}


def _problems(case: dict[str, Any]) -> list[str]:
    return contract.first_errors(CHECKS[case["kind"]](case), limit=20)


@pytest.mark.parametrize("name", sorted(LEGAL))
def test_producer_shapes_are_legal(name: str) -> None:
    case = LEGAL[name]
    assert _problems(case) == [], case["source"]
    if case["kind"] == "rows" and case.get("schema") == 2:
        converted, _ = probe.convert_samples_to_authored(copy.deepcopy(case["record"]))
        assert contract.first_errors(contract.sample_rows(converted, schema=2), limit=20) == []


def _row(rows: list[dict[str, Any]], index: int = 1) -> dict[str, Any]:
    return rows[index]


def _video(rows: list[dict[str, Any]], index: int = 1) -> dict[str, Any]:
    return rows[index]["videos"][0]


def _pv(rows: list[dict[str, Any]], index: int = 0) -> dict[str, Any]:
    return rows[1]["pp"]["videos"][index]


def _set(target: Callable[[Any], dict[str, Any]], **values: Any) -> Callable[[Any], None]:
    return lambda record: target(record).update(values)


def _drop(target: Callable[[Any], dict[str, Any]], *keys: str) -> Callable[[Any], None]:
    return lambda record: [target(record).pop(key) for key in keys]


def _append_copy(target: Callable[[Any], list[Any]], index: int = 0, **values: Any) -> Callable[[Any], None]:
    return lambda record: target(record).append({**copy.deepcopy(target(record)[index]), **values})


def _release(read: dict[str, Any]) -> dict[str, Any]:
    return next(e for e in read["coreEvents"] if e["kind"] == "glreplay-release")["detail"]


S2, G4 = "rows-S2-raw-rare-shapes", "rows-G4-converted"
POOL, GL, HB = "refusal-read-pool-and-fromDom-hold-one-decoder", "gl-read-release-elId-null-retire-without-instance", "handback-ok"
FW, CC, MANAGED, NC = "force-wrap-take", "carry-cover-trailing-rows-unread", "managed-g2-session", "null-control-40-keys"
VIOLATIONS = [
    ("row-isConnected-false", S2, _set(_video, isConnected=False), "decoder.isConnected"),
    ("row-player-state-not-an-enum", S2, _set(_row, playerState="Paused"), "row.playerState"),
    ("row-busy-null", S2, _set(_row, busy=None), "row.busy"),
    ("row-runtime-partly-absent", S2, _drop(_row, "busy"), "row:runtime state partly absent"),
    ("row-scene-float", S2, _set(_row, scene=1.5), "row.scene"),
    ("row-duplicate-probe-id", S2, _append_copy(lambda r: r[1]["videos"], elId=None), "row:duplicate id"),
    ("row-duplicate-elId", S2, _append_copy(lambda r: r[2]["videos"], id=5), "row:duplicate elId"),
    ("decoder-not-a-generation", S2, _drop(_video, "ended"), "decoder:generation"),
    ("decoder-currentTime-negative", S2, _set(_video, currentTime=-1), "decoder.currentTime"),
    ("decoder-readyState-out-of-range", S2, _set(_video, readyState=5), "decoder.readyState"),
    ("decoder-duration-zero", S2, _set(_video, duration=0), "decoder.duration"),
    ("decoder-domId-empty", S2, _set(_video, domId=""), "decoder.domId"),
    ("decoder-elId-changes", S2, _set(lambda r: r[3]["videos"][0], elId=8), "row:elId changed"),
    ("decoder-elId-untagged-again", S2, _set(lambda r: r[3]["videos"][0], elId=None), "row:elId untagged after tagging"),
    ("decoder-elId-under-another-probe-id", S2, _set(lambda r: r[3]["videos"][0], id=2), "row:elId under another id"),
    ("rows-ts-not-increasing", S2, _set(lambda r: r[2], ts=900.0), "row:ts not increasing"),
    ("rows-t-decreasing", S2, _set(lambda r: r[2], t=1.0), "row:t decreasing"),
    ("rows-mixed-schemas", S2, _drop(lambda r: r[0], "seq", "ts", "hash", "sceneCount"), "rows:mixed sampler schemas"),
    ("rows-mixed-generations", S2, _drop(_video, "instance"), "rows:mixed decoder generations"),
    ("stage-map-width-float", S2, _set(lambda r: r[1]["stageMap"], offsetWidth=1920.5), "stageMap.offsetWidth"),
    ("owner-without-stage-map", S2, _set(_row, stageMap=None), "row:owner without a stage map"),
    ("owner-unresolved-names-a-decoder", S2, _set(lambda r: _video(r)["footprintOwner"], via="none"), "owner:unresolved names a decoder"),
    ("owner-context-type", S2, _set(lambda r: _video(r)["footprintOwner"], contextType="2d"), "owner.contextType"),
    ("owner-elId-zero", S2, _set(lambda r: _video(r)["footprintOwner"], elId=0), "owner.elId"),
    ("pp-of-another-frame", S2, _set(lambda r: r[1]["pp"], seq=1), "pp:frame is not the row's"),
    ("pp-read-before-the-row", S2, _set(lambda r: r[1]["pp"], t=0.0), "pp:read before the row"),
    ("pp-cover-missing", S2, _drop(lambda r: r[1]["pp"], "cover"), "pp.cover:missing"),
    ("pp-duplicate-id", S2, _set(lambda r: _pv(r, 2), id=1), "pp:duplicate id"),
    ("pv-disconnected-with-style", S2, _set(lambda r: _pv(r, 1), opacity=1), "pv:disconnected read carries style"),
    ("pv-visibility-not-css", S2, _set(_pv, visibility="shown"), "pv.visibility"),
    ("pv-hiding-display-not-none", S2, _set(_pv, hiding={"node": "div#a", "prop": "display", "value": 0}), "pv.hiding"),
    ("pv-opacity-above-one", S2, _set(_pv, opacity=1.5), "pv.opacity"),
    ("rows-schema-2-unreported", S2, None, "rows:schema"),
    ("converted-stage-map-valid-wrong", G4, _set(lambda r: r[0], stageMapValid=False), "row.stageMapValid"),
    ("converted-rect-null-on-valid-map", G4, _set(lambda r: r[0]["videos"][0], rect=None), "decoder.rect"),
    ("converted-decoder-stage-map-valid-wrong", G4, _set(lambda r: r[0]["videos"][0], stageMapValid=False),
     "decoder.stageMapValid"),
    ("painting-rect-one-px", POOL, _set(lambda r: r["painting"][0]["rect"], w=1), "painting.rect"),
    ("painting-duplicate-elId", POOL, _append_copy(lambda r: r["painting"]), "painting:duplicate elId"),
    ("painting-not-a-list", POOL, _set(lambda r: r, painting="none"), "painting:list"),
    ("pool-elId-null", POOL, _set(lambda r: r["poolSnapshot"][0], elId=None), "pool.elId"),
    ("pool-empty-key-off-the-dom", POOL, _set(lambda r: r["poolSnapshot"][0], key=""), "pool:empty key off the DOM"),
    ("pool-instance-on-some-entries", POOL, _drop(lambda r: r["poolSnapshot"][0], "instance"), "pool:instance on some entries"),
    ("pool-duplicate-elId", POOL, _append_copy(lambda r: r["poolSnapshot"]), "pool:duplicate elId"),
    ("pool-empty-key-without-its-stamp", POOL, _set(lambda r: r["poolSnapshot"][-1], key="", movieKey=None),
     "pool:empty key without its movie stamp"),
    ("pool-fromDom-false", POOL, _set(lambda r: r["poolSnapshot"][-1], fromDom=False), "pool.fromDom"),
    ("notes-t-decreasing", GL, _set(lambda r: r["coreEvents"][-1], t=-1.0), "note:t decreasing"),
    ("notes-no-scene-hash", GL, _drop(lambda r: r["coreEvents"][0]["detail"], "sceneHash"), "note.sceneHash"),
    ("notes-kind-outside-the-filter", GL, _set(lambda r: r["coreEvents"][0], kind="dom-swap"), "note:kind outside the read's filter"),
    ("notes-envelope", GL, _set(lambda r: r["coreEvents"][0], detail="x"), "note:envelope"),
    ("retire-boundary-elIds-empty", GL, _set(lambda r: next(e for e in r["coreEvents"] if e["kind"] == "retire-boundary")["detail"],
                                              elIds=[]), "note.elIds"),
    ("retire-boundary-instance-null", GL, _set(lambda r: next(e for e in r["coreEvents"] if e["kind"] == "retire-boundary")["detail"],
                                                instance=None), "retire-boundary.instance"),
    ("release-mode-not-an-enum", GL, _set(_release, mode="pin"), "glreplay-release.mode"),
    ("release-handoff-not-ok", HB, _set(lambda r: _release(r["after"]), ok=False), "glreplay-release:handoff without ok and its elId"),
    ("release-handoff-elId-null", HB, _set(lambda r: _release(r["after"]), elId=None),
     "glreplay-release:handoff without ok and its elId"),
    ("zone-from-not-an-enum", GL, _set(lambda r: next(e for e in r["coreEvents"] if e["kind"] == "glreplay-zone")["detail"],
                                        **{"from": "retired"}), "glreplay-zone.from"),
    ("api-state-not-an-enum", GL, _set(lambda r: r["api"], state="DONE"), "api.state"),
    ("api-retired-without-stand-down", GL, _set(lambda r: r["api"], standDowns=[]), "api:retired without a stand-down"),
    ("api-live-with-stand-down", GL, _set(lambda r: r["api"], state="LIVE"), "api:stand-down before STANDDOWN"),
    ("api-stats-float", GL, _set(lambda r: r["api"]["stats"], glErrors=0.5), "api.stats.glErrors"),
    ("gl-facade-elId-zero", GL, _set(lambda r: r, facades=[{"elId": 0, "forElId": 3}]), "gl.facades"),
    ("gl-ready-string", GL, _set(lambda r: r, ready="yes"), "gl.ready"),
    ("handback-status-not-an-enum", HB, _set(lambda r: r, status="pass"), "handback.status"),
    ("handback-ok-without-before", HB, _drop(lambda r: r, "before"), "handback.before:missing"),
    ("armed-reads-not-two", FW, lambda r: r["reads"].pop(), "armed:two reads"),
    ("recorder-frame-times-not-increasing", FW, _set(lambda r: r["recorder"]["frames"][1], now=0.0),
     "recorder:frame times not increasing"),
    ("recorder-presented-frames-decreasing", FW, _set(lambda r: r["recorder"]["frames"][1], presentedFrames=-1),
     "recorder:presentedFrames decreasing"),
    ("recorder-media-time-negative", FW, _set(lambda r: r["recorder"]["frames"][0], mediaTime=-0.1), "frame.mediaTime"),
    ("select-count-negative", FW, _set(lambda r: r["take"]["select"], count=-1), "select.count"),
    ("page-error-note-kind", FW, _set(lambda r: r, pageErrorNotes=[{"kind": "dom-swap", "detail": {"sceneHash": ""}, "t": 1.0}]),
     "note:kind outside the read's filter"),
    ("carry-cover-tick-skips", CC, _set(lambda r: r["rows"][2], tick=5), "carryCover:tick not contiguous"),
    ("carry-cover-read-after-unread-row", CC, _set(lambda r: r["rows"][2], vids=[], readAt=140.0),
     "carryCover:read after an unread row"),
    ("carry-cover-vids-without-read-at", CC, _drop(lambda r: r["rows"][0], "readAt"), "carryCover.readAt"),
    ("carry-cover-duplicate-elId", CC, _append_copy(lambda r: r["rows"][0]["vids"]), "carryCover:duplicate elId"),
    ("carry-cover-opaque-null", CC, _set(lambda r: r["rows"][1]["pre"][0], opaque=None), "vid.opaque"),
    ("carry-cover-src-not-a-string", CC, _set(lambda r: r["rows"][1]["pre"][0], src=None), "vid.src"),
    ("carry-cover-mixed-read-generations", CC, _set(lambda r: r["rows"][1]["pre"][0], src="untitled.mov"),
     "carryCover:mixed read generations (with and without src)"),
    ("bridge-clock-fallback-before-its-wait", CC, _set(lambda r: r, notes=[
        {"kind": "bridge-clock", "detail": {"elId": 3, "via": "fallback", "lagMs": 12.0, "sceneHash": "#7"}, "t": 1.0}]),
     "bridge-clock:fallback before its wait"),
    ("managed-video-ready-state", MANAGED, _set(lambda r: r["sessions"][0]["phases"][0]["videos"][0], rs=None), "managed.video.rs"),
    ("managed-raf", MANAGED, _set(lambda r: r["sessions"][0]["phases"][0], raf=None), "managed.raf"),
    ("managed-handed-back-facade", MANAGED, _set(lambda r: r["sessions"][0], handedBack=[
        {"elId": 3, "loop": True, "isConnected": True, "facade": None, "paused": False, "t": 1.0}]), "managed.handedBack.facade"),
    ("null-control-keys", NC, _drop(lambda r: r, "error"), "nullControl:keys"),
    ("null-control-poll-times-not-increasing", NC, _set(lambda r: r, pollTimes=[2.0, 1.0]), "nullControl.pollTimes"),
    ("null-control-motion-after-trigger", NC, _set(lambda r: r, triggerFramesAfterAdvance=1, motionStartedFrame=2),
     "nullControl:motion started after the trigger"),
    ("null-control-measured-rect-one-px", NC, _set(lambda r: r["rafLog"][0], measuredRect={"x": 0, "y": 0, "w": 1, "h": 1}),
     "nullControl.rafLog.measuredRect"),
]


@pytest.mark.parametrize(("base", "mutate", "clause"), [v[1:] for v in VIOLATIONS], ids=[v[0] for v in VIOLATIONS])
def test_each_clause_rejects_its_violation(base: str, mutate: Callable[[Any], Any] | None, clause: str) -> None:
    case = copy.deepcopy(LEGAL[base])
    if mutate is None:
        case["schema"] = None
    else:
        mutate(case["record"])
    clauses = [problem.split(" at ")[0] for problem in _problems(case)]
    assert clause in clauses, clauses


def _node(script: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


#: `SAMPLER_JS` against an `HTMLMediaElement` stub carrying every property the sampler reads and a `__obedLive`
#: snapshot; three frames: an untagged decoder is tagged, a second decoder arrives without a duration, the runtime
#: snapshot fails once.
SAMPLER_HARNESS = r"""
global.window = global;
var frames = [];
global.requestAnimationFrame = function(cb){ frames.push(cb); return frames.length; };
global.cancelAnimationFrame = function(){};
var now = 1000;
global.performance = {now: function(){ return now; }};
var snapshotFails = false;
window.__obedLive = {snapshot: function(){
  if (snapshotFails) throw new Error('mid-teardown');
  return {sceneId: 2, playerState: 'IdleAtFinalState', busy: false, ready: true, sceneCount: 12};
}};
window.__OBED_CONTINUITY__ = {movies: {movie1: {assetKeys: ['movie-a.mov']}}};
window.__OBED_P2_PRESERVE__ = {footprintOwnerDecoderId: function(q){
  var v = videos[0];
  return q.key ? {elId: v.__obedElId, key: q.key, via: 'footprint-video', contextType: null}
               : {elId: null, key: null, via: 'unknown-key', contextType: null};
}};
function Media(src, rect, duration){
  this.currentSrc = 'http://h/x/' + src; this.src = this.currentSrc; this.id = src.split('.')[0] + '-video';
  this.currentTime = 0.5; this.paused = false; this.ended = false; this.loop = true; this.duration = duration;
  this.readyState = 4; this.videoWidth = 640; this.videoHeight = 360; this.seeking = false; this.isConnected = true;
  this.dataset = {}; this._rect = rect;
}
Media.prototype.getBoundingClientRect = function(){
  var r = this._rect; return {left: r.x, top: r.y, width: r.w, height: r.h};
};
var videos = [new Media('movie-a.mov-0.0000-10.0000.mov', {x: 100, y: 100, w: 400, h: 225}, 10)];
var stage = {offsetWidth: 1920, offsetHeight: 1080,
             getBoundingClientRect: function(){ return {left: 0, top: 0, width: 1920, height: 1080}; }};
global.document = {
  getElementById: function(id){ return id === 'stage' ? stage : null; },
  querySelectorAll: function(){ return videos.slice(); },
  contains: function(v){ return videos.indexOf(v) >= 0; },
  createElement: function(){ return {style: {}, attachShadow: function(){ return {appendChild: function(){}}; }}; },
  documentElement: {appendChild: function(){}},
};
global.location = {hash: '#2'};
global.ResizeObserver = function(){ this.observe = function(){}; };
global.WeakRef = function(v){ this.deref = function(){ return v; }; };
global.Element = function(){};
Element.prototype.checkVisibility = function(){ return true; };
__SAMPLER__
function step(ts){ now = ts + 0.25; var f = frames.splice(0); f.forEach(function(cb){ cb(ts); }); }
step(16);
videos[0].__obedElId = 3; videos[0].__obedInstance = 'A2';
videos.push(new Media('other.mov', {x: 0, y: 0, w: 10, h: 10}, NaN));
step(33);
snapshotFails = true;
step(50);
var p = window.__obedContinuityProbe__;
p.stop();
console.log(JSON.stringify({rows: p.drain(100), meta: JSON.parse(JSON.stringify(p.meta))}));
"""


def test_producer_js_meets_the_contract() -> None:
    from test_live_continuity_js import _CARRY_A1_INTO_A2, _HELD_RETIRE_PLAN, _detach_script, _run_retire
    from test_paint_instrument import _OUT, _control_run, _run_js

    sampled = _node(SAMPLER_HARNESS.replace("__SAMPLER__", probe.SAMPLER_JS))
    rows, schema = sampled["rows"], sampled["meta"]["schema"]
    assert len(rows) == 3 and rows[0]["videos"][0]["elId"] is None and "playerState" not in rows[2]
    assert contract.first_errors(contract.sample_rows(rows, schema=schema), limit=20) == []
    converted, _ = probe.convert_samples_to_authored(rows)
    assert contract.first_errors(contract.sample_rows(converted, schema=schema), limit=20) == []

    painted = _run_js("""
const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225});
act(() => keynoteBody.appendChild(v));
for (let i = 1; i <= 6; i++) { if (i === 4) act(() => keynoteBody.removeChild(v)); runFrame(i * 1000 / 60); }
""" + _OUT)
    controlled, _ = _control_run("settled", 6, "early")
    for out in (painted, controlled):
        for row in out["rows"]:
            assert "pp" in row
            assert contract.first_errors(contract.pp(row["pp"], "pp", row), *(contract.pv(pv, "raf") for pv in row["raf"]),
                                         limit=20) == []
    assert any(pv["connected"] is False for row in painted["rows"] for pv in row["pp"]["videos"])

    script = _CARRY_A1_INTO_A2 + r"""
const held = P.snapshot();
location.hash = '#4';
tick();
console.log(JSON.stringify({held: held, events: P.events, after: P.snapshot()}));
"""
    core = _run_retire(script, plan=_HELD_RETIRE_PLAN)
    refused = _run_retire(_detach_script(scene=1) + "\nconsole.log(JSON.stringify({events: P.events}));")
    kinds = {e["kind"] for e in core["events"] + refused["events"]}
    assert {"reuse-decoder", "retire-boundary", "preserve-refused"} <= kinds
    assert any(entry.get("fromDom") for entry in core["held"])
    assert contract.first_errors(
        contract.pool(core["held"], "held"), contract.pool(core["after"], "after"),
        contract.notes(core["events"], "events"), contract.notes(refused["events"], "events"), limit=20,
    ) == []


def _mm_feed_report() -> dict[str, Any]:
    return {
        "kind": "mm-feed", "version": 1, "config": {}, "media": [], "mediaOverflow": 0, "artwork": [],
        "errors": [], "module": None, "uploads": [], "claims": [], "standDowns": [],
        "departures": [{"t": 1.5, "serial": None, "atScene": 2, "entryId": "carry-a"}],
        "callbackCostP95Ms": None,
        "tamper": None, "killedOnce": [{"objectId": "movie-a", "t": 3.0}],
        "contexts": [{"serial": 1, "id": "0-canvas", "createdAt": 1.0, "atScene": 2,
                      "lost": False, "entryIds": ["carry-a"]}],
        "frames": [{
            "serial": 1, "atScene": 2, "n": 1, "t": 2.0, "draws": 1, "uploads": 2,
            "labels": [], "riders": [], "labelExpected": [],
            "glErrors": [], "module": None,
            "rows": [{"serial": 1, "atScene": 2, "entryId": "carry-a", "objectId": "movie-a",
                      "dstObjectId": "movie-b", "draw": 1, "t": 2.0, "quad": None,
                      "mixFactor": .5, "decoder": None,
                      "textures": [{"unit": 0, "ordinal": 1, "size": [640, 360],
                                    "uploadedSize": [1280, 720], "video": True,
                                    "flip": True}, None],
                      "feedRead": {"patchInside": True, "coveredByLaterDraw": False, "kind": "alpha",
                                   "dVideo": 2.0, "dPoster": 20.0, "dSep": 20.0}}],
        }],
    }


def test_mm_feed_frame_and_poster_feed_note_producers_meet_the_contract() -> None:
    assert contract.first_errors(contract.mm_feed_report(_mm_feed_report()), limit=20) == []
    notes = [
        {"kind": "poster-hold", "detail": {"elId": 3, "objectId": "movie-a", "t": 2.0, "reason": None}, "t": 2.0},
        {"kind": "poster-resume", "detail": {"elId": 3, "t": 3.5}, "t": 3.5},
        {"kind": "mm-feed-stand-down", "detail": {"objectId": "movie-a", "reason": "binding",
                                                       "usableContext": True, "boundTextures": True}, "t": 4.0},
    ]
    assert contract.first_errors(contract.notes(notes, "notes", contract.MM_FEED_NOTE_KINDS, module=True), limit=20) == []


@pytest.mark.parametrize(("mutate", "clause"), [
    (lambda r: r["contexts"][0].pop("lost"), "mmFeed.context.lost:missing"),
    (lambda r: r["frames"][0].update(t="late"), "mmFeed.frame.t"),
    (lambda r: r["frames"][0]["rows"][0]["textures"][0].update(size=[640]), "mmFeed.texture.size"),
    (lambda r: r["frames"][0]["rows"][0]["textures"][0].update(uploadedSize=[1280]),
     "mmFeed.texture.uploadedSize"),
])
def test_mm_feed_contract_rejects_required_field_and_generation_breaks(mutate: Any, clause: str) -> None:
    report = _mm_feed_report()
    mutate(report)
    assert clause in [problem.split(" at ")[0] for problem in contract.mm_feed_report(report)]


def _feed_verdict_record() -> dict[str, Any]:
    return {
        "mode": "continuous", "usableContext": True, "boundTextures": True,
        "interval": {"start": 1.0, "end": 2.0},
        "feed": {"usableContext": True, "boundTextures": True, "reads": [{
            "progress": .25, "patchInside": True, "coveredByLaterDraw": False,
            "kind": "alpha", "dVideo": 2.0, "dPoster": 20.0, "dSep": 20.0,
        }]},
        "rider": {"riders": [], "coverage": True}, "labels": {"labels": [], "coverage": True},
        "artwork": {"reads": []},
    }


def test_feed_verdict_contract_checks_applicable_nested_producer_generation() -> None:
    record = _feed_verdict_record()
    assert list(contract.feed_verdict_record(record)) == []
    record["feed"]["reads"][0].pop("kind")
    assert "feedVerdict.feed.read.kind:missing" in [
        problem.split(" at ")[0] for problem in contract.feed_verdict_record(record)
    ]

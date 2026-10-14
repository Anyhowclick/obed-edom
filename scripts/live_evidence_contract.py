"""Producer contract for the live-continuity evidence (`.agents/plans/keynote_live_continuity_contract.plan.md` §2).

Each validator yields `"<clause> at <path>"` for every way a record departs from what its producer emits (types,
nullability, enums, required keys per generation, per-sample uniqueness, producer-enforced cross-field rules); the
ingestion points turn any message into an INCONCLUSIVE or INVALID outcome. Whether enough evidence is present stays
with the scorers. A change to a `*_JS` producer or a note payload updates this module in the same commit.
"""
from __future__ import annotations

import math
import re
from itertools import islice
from typing import Any, Iterable, Iterator

import paint_instrument

CONTRACT_ERROR_LIMIT = 5

PLAYER_STATES = frozenset({
    "Starting", "DownloadingScipt", "ReadyToJump", "SettingUpScene", "Playing", "WaitingToJump", "Stopped",
    "IdleAtInitialState", "IdleAtFinalState",
})
OWNER_VIAS = frozenset({"footprint-video", "ambiguous", "unknown-key", "none", "no-stage-map"})
GL_STATES = frozenset({"IDLE", "ARM-PRE", "ARM-POST", "LIVE", "STANDDOWN", "RETIRED"})
DECODER_G1 = frozenset({"currentTime", "elId", "footprintOwner", "id", "isConnected", "paused", "readyState", "rect", "src",
                        "videoWidth"})
DECODER_G2 = DECODER_G1 | {"duration", "ended", "loop"}
DECODER_G3 = DECODER_G2 | {"domId", "facade", "preserved", "remounted"}
DECODER_G4 = DECODER_G3 | {"instance"}
DECODER_GENERATIONS = (DECODER_G1, DECODER_G2, DECODER_G3, DECODER_G4)
CONVERSION_KEYS = frozenset({"rectScreen", "stageMapValid"})
RUNTIME_KEYS = ("scene", "playerState", "busy")
S2_ROW_KEYS = ("seq", "ts", "hash", "sceneCount")
PV_CONNECTED_ONLY = ("checkVisibility", "visibility", "displayNone", "opacity", "hiding", "effects", "transform",
                     "visibleRect", "clippedBy")
CSS_VISIBILITY = frozenset({"visible", "hidden", "collapse"})
GL_NOTE_KINDS = re.compile(r"^(glreplay-|remount-|preserve-refused|retire)")
REFUSAL_NOTE_KINDS = re.compile(r"^(remount-|reuse-|dom-swap|facade-|preserve-refused|retire)")
PAGE_ERROR_NOTE_KINDS = re.compile(r"^player-build-error$")
CARRY_COVER_NOTE_KINDS = re.compile(r"^(bridge-motion-start|bridge-clock)$")
MM_FEED_NOTE_KINDS = re.compile(r"^(mm-feed-|feed-|poster-)")
CARRY_COVER_TICKS = 4096
REFUSE_VIAS = frozenset({"stash", "remount", "src-clear", "removeAttribute", "reuse"})
ZONE_FROM = frozenset({"pending", "armed", "released"})
ZONE_TO = frozenset({"armed", "released", "retired"})
BRIDGE_CLOCK_FALLBACK_MIN_MS = 50


def first_errors(*streams: Iterable[str], limit: int = CONTRACT_ERROR_LIMIT) -> list[str]:
    """The first `limit` messages across `streams`, in order."""
    return list(islice((message for stream in streams for message in stream), limit))


def stage_map_valid(stage_map: dict[str, Any] | None) -> bool:
    """Fail-closed: missing `#stage`, a zero box, or a non-uniform scale (`|s -
    sy| / s` over 0.1%) is invalid, never silently treated as identity."""
    if not isinstance(stage_map, dict):
        return False
    s, sy = _finite_or_none(stage_map.get("s")), _finite_or_none(stage_map.get("sy"))
    ow, oh = _finite_or_none(stage_map.get("offsetWidth")), _finite_or_none(stage_map.get("offsetHeight"))
    if not all(v is not None and v > 0 for v in (s, sy, ow, oh)):
        return False
    if _finite_or_none(stage_map.get("ox")) is None or _finite_or_none(stage_map.get("oy")) is None:
        return False
    return abs(s - sy) / s <= 0.001


def _finite_or_none(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _id(value: Any) -> bool:
    return _int(value) and value >= 1


def _id_or_null(value: Any) -> bool:
    return value is None or _id(value)


def _str_or_null(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _ready_state(value: Any) -> bool:
    return _int(value) and 0 <= value <= 4


def _count(value: Any) -> bool:
    return _int(value) and value >= 0


def _box(value: Any, floor: float | None = None) -> bool:
    """x, y finite; w, h finite and >= 0, or > `floor` when given."""
    if not (isinstance(value, dict) and all(_finite(value.get(k)) for k in ("x", "y", "w", "h"))):
        return False
    return value["w"] > floor and value["h"] > floor if floor is not None else value["w"] >= 0 and value["h"] >= 0


def _error_read(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"error"} and isinstance(value["error"], str)


def _fields(value: dict[str, Any], kind: str, path: str, table: dict[str, Any]) -> Iterator[str]:
    for key, valid in table.items():
        if key not in value:
            yield f"{kind}.{key}:missing at {path}"
        elif not valid(value[key]):
            yield f"{kind}.{key} at {path}"


def _unique(values: list[Any], clause: str, path: str) -> Iterator[str]:
    if len(values) != len(set(values)):
        yield f"{clause} at {path}"


STAGE_MAP_FIELDS = {
    "s": lambda v: _finite(v) and v > 0, "sy": lambda v: _finite(v) and v > 0, "ox": _finite, "oy": _finite,
    "offsetWidth": _id, "offsetHeight": _id,
}


def stage_map(value: Any, path: str) -> Iterator[str]:
    """`STAGE_MAP_FN_JS`: null, or `{s, sy}` finite > 0, `{ox, oy}` finite, `{offsetWidth, offsetHeight}` int >= 1."""
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"stageMap:object at {path}"
        return
    yield from _fields(value, "stageMap", path, STAGE_MAP_FIELDS)


def owner(value: Any, path: str) -> Iterator[str]:
    """`footprintOwnerDecoderId`: `{elId, key, via, contextType: null}`; a `footprint-video` owner names a non-empty
    `key` and an `elId` int >= 1, absent when the owner is untagged; every other `via` names neither."""
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"owner:object at {path}"
        return
    if value.get("via") not in OWNER_VIAS:
        yield f"owner.via at {path}"
        return
    if "contextType" not in value or value["contextType"] is not None:
        yield f"owner.contextType at {path}"
    if value["via"] == "footprint-video":
        if not _non_empty_str(value.get("key")):
            yield f"owner.key at {path}"
        if "elId" in value and not _id(value["elId"]):
            yield f"owner.elId at {path}"
    elif "elId" not in value or "key" not in value or value["elId"] is not None or value["key"] is not None:
        yield f"owner:unresolved names a decoder at {path}"


DECODER_FIELDS = {
    "id": _id, "elId": _id_or_null, "src": lambda v: isinstance(v, str),
    "currentTime": lambda v: _finite(v) and v >= 0, "readyState": _ready_state, "videoWidth": _count,
    "isConnected": lambda v: v is True, "paused": lambda v: isinstance(v, bool),
}
DECODER_G2_FIELDS = {"ended": lambda v: isinstance(v, bool), "loop": lambda v: isinstance(v, bool),
                     "duration": lambda v: v is None or _finite(v) and v > 0}
DECODER_G3_FIELDS = {"domId": lambda v: v is None or _non_empty_str(v), "facade": lambda v: isinstance(v, bool),
                     "preserved": lambda v: isinstance(v, bool), "remounted": lambda v: isinstance(v, bool)}


def decoder(value: Any, path: str, converted: bool | None) -> Iterator[str]:
    """One `videos[]` row: exactly one generation's keys (plus the conversion keys on a converted row); `converted` is
    the row's `stageMapValid`, None on a raw row."""
    if not isinstance(value, dict):
        yield f"decoder:object at {path}"
        return
    keys = frozenset(value) - CONVERSION_KEYS
    if keys not in DECODER_GENERATIONS:
        yield f"decoder:generation at {path}"
        return
    yield from _fields(value, "decoder", path, DECODER_FIELDS)
    if "ended" in keys:
        yield from _fields(value, "decoder", path, DECODER_G2_FIELDS)
    if "domId" in keys:
        yield from _fields(value, "decoder", path, DECODER_G3_FIELDS)
    if "instance" in keys and not _str_or_null(value["instance"]):
        yield f"decoder.instance at {path}"
    if converted is None:
        if CONVERSION_KEYS & set(value):
            yield f"decoder:conversion keys on a raw row at {path}"
        if not _box(value["rect"]):
            yield f"decoder.rect at {path}"
    else:
        if value.get("stageMapValid") is not converted:
            yield f"decoder.stageMapValid at {path}"
        if not _box(value.get("rectScreen")):
            yield f"decoder.rectScreen at {path}"
        if not (value["rect"] is None if converted is False else _box(value["rect"])):
            yield f"decoder.rect at {path}"
    yield from owner(value["footprintOwner"], f"{path}.footprintOwner")


def _hiding(value: Any) -> bool:
    if value is None:
        return True
    if not (isinstance(value, dict) and isinstance(value.get("node"), str)):
        return False
    if value.get("prop") == "display":
        return value.get("value") == "none"
    return value.get("prop") == "opacity" and _finite(value.get("value"))


PV_FIELDS = {
    "id": _id_or_null, "elId": _id_or_null, "instance": _str_or_null, "src": lambda v: isinstance(v, str),
    "connected": lambda v: isinstance(v, bool), "facade": lambda v: isinstance(v, bool),
    "suppressed": lambda v: isinstance(v, bool), "seeking": lambda v: isinstance(v, bool),
    "paused": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool),
    "readyState": _ready_state, "videoWidth": _count, "videoHeight": _count,
    "currentTime": lambda v: _finite(v) and v >= 0, "rect": _box, "parent": _str_or_null, "layer": _str_or_null,
}
PV_CONNECTED_FIELDS = {
    "checkVisibility": lambda v: isinstance(v, bool), "visibility": lambda v: v in CSS_VISIBILITY,
    "opacity": lambda v: v is None or _finite(v) and 0 <= v <= 1, "hiding": _hiding,
    "visibleRect": lambda v: v is None or _box(v, 0), "displayNone": _str_or_null, "effects": _str_or_null,
    "transform": _str_or_null, "clippedBy": _str_or_null,
}


def pv(value: Any, path: str) -> Iterator[str]:
    """`paintReadOf`: one pre-paint decoder read (`*Screen` twins after conversion read as their originals)."""
    if not isinstance(value, dict):
        yield f"pv:object at {path}"
        return
    yield from _fields(value, "pv", path, PV_FIELDS)
    if "rectScreen" in value and not _box(value["rectScreen"]):
        yield f"pv.rectScreen at {path}"
    if "visibleRectScreen" in value and not (value["visibleRectScreen"] is None or _box(value["visibleRectScreen"], 0)):
        yield f"pv.visibleRectScreen at {path}"
    if value.get("connected") is False:
        if any(value.get(key, True) is not None for key in PV_CONNECTED_ONLY):
            yield f"pv:disconnected read carries style at {path}"
    elif value.get("connected") is True:
        yield from _fields(value, "pv", path, PV_CONNECTED_FIELDS)


PP_FIELDS = {"seq": _id, "ts": _finite, "t": _finite, "videos": lambda v: isinstance(v, list),
             "cover": lambda v: isinstance(v, bool), "stageBox": lambda v: v is None or _box(v)}


def pp(value: Any, path: str, row: dict[str, Any]) -> Iterator[str]:
    """The ResizeObserver's pre-paint read of `row`'s frame: same `seq` and `ts`, read no earlier than the row."""
    if not isinstance(value, dict):
        yield f"pp:object at {path}"
        return
    yield from _fields(value, "pp", path, PP_FIELDS)
    if "stageMap" not in value:
        yield f"pp.stageMap:missing at {path}"
    else:
        yield from stage_map(value["stageMap"], f"{path}.stageMap")
    if "stageBoxScreen" in value and not (value["stageBoxScreen"] is None or _box(value["stageBoxScreen"])):
        yield f"pp.stageBoxScreen at {path}"
    if value.get("seq") != row.get("seq") or value.get("ts") != row.get("ts"):
        yield f"pp:frame is not the row's at {path}"
    if _finite(value.get("t")) and _finite(row.get("t")) and value["t"] < row["t"]:
        yield f"pp:read before the row at {path}"
    if not isinstance(value.get("videos"), list):
        return
    for index, entry in enumerate(value["videos"]):
        yield from pv(entry, f"{path}.videos[{index}]")
    entries = [e for e in value["videos"] if isinstance(e, dict)]
    yield from _unique([e["id"] for e in entries if _id(e.get("id"))], "pp:duplicate id", path)
    yield from _unique([e["elId"] for e in entries if _id(e.get("elId"))], "pp:duplicate elId", path)


ROW_FIELDS = {"t": _finite, "videos": lambda v: isinstance(v, list)}
ROW_RUNTIME_FIELDS = {"scene": lambda v: v is None or _count(v), "playerState": lambda v: v in PLAYER_STATES,
                      "busy": lambda v: isinstance(v, bool)}
ROW_S2_FIELDS = {"seq": _id, "ts": _finite, "hash": lambda v: isinstance(v, str),
                 "sceneCount": lambda v: v is None or _count(v)}


def sample_rows(rows: Any, *, schema: Any = None, path: str = "samples") -> Iterator[str]:
    """`SAMPLER_JS` rows, raw or after `convert_samples_to_authored`. One sampler schema and one decoder generation
    per stream, schema 2 iff the sampler reported it; `t` non-decreasing and (schema 2) `ts` strictly increasing; a
    probe id's `elId` is null until tagged, then one int that no other probe id carries."""
    if not isinstance(rows, list):
        yield f"rows:list at {path}"
        return
    schemas: set[bool] = set()
    generations: set[frozenset[str]] = set()
    el_ids: dict[Any, Any] = {}
    probe_ids: dict[Any, Any] = {}
    prev_t = prev_ts = None
    for index, row in enumerate(rows):
        where = f"{path}[{index}]"
        if not isinstance(row, dict):
            yield f"row:object at {where}"
            continue
        yield from _fields(row, "row", where, ROW_FIELDS)
        present = [key in row for key in RUNTIME_KEYS]
        if all(present):
            yield from _fields(row, "row", where, ROW_RUNTIME_FIELDS)
        elif any(present):
            yield f"row:runtime state partly absent at {where}"
        if "stageMap" not in row:
            yield f"row.stageMap:missing at {where}"
        else:
            yield from stage_map(row["stageMap"], f"{where}.stageMap")
        v2 = "seq" in row
        schemas.add(v2)
        if v2:
            yield from _fields(row, "row", where, ROW_S2_FIELDS)
            if _finite(row.get("ts")):
                if prev_ts is not None and row["ts"] <= prev_ts:
                    yield f"row:ts not increasing at {where}"
                prev_ts = row["ts"]
            if "pp" in row:
                yield from pp(row["pp"], f"{where}.pp", row)
            if "ppUnreadable" in row:
                yield from pp(row["ppUnreadable"], f"{where}.ppUnreadable", row)
        elif any(key in row for key in (*S2_ROW_KEYS, "pp", "ppUnreadable")):
            yield f"row:schema-2 keys without seq at {where}"
        if "rafTs" in row and row["rafTs"] != row.get("ts"):
            yield f"row.rafTs at {where}"
        if _finite(row.get("t")):
            if prev_t is not None and row["t"] < prev_t:
                yield f"row:t decreasing at {where}"
            prev_t = row["t"]
        converted = None
        if "stageMapValid" in row:
            converted = stage_map_valid(row.get("stageMap"))
            if row["stageMapValid"] is not converted:
                yield f"row.stageMapValid at {where}"
        if not isinstance(row.get("videos"), list):
            continue
        ids, els = [], []
        for vindex, video in enumerate(row["videos"]):
            vwhere = f"{where}.videos[{vindex}]"
            yield from decoder(video, vwhere, converted)
            if not isinstance(video, dict):
                continue
            keys = frozenset(video) - CONVERSION_KEYS
            if keys in DECODER_GENERATIONS:
                generations.add(keys)
            if row.get("stageMap") is None and video.get("footprintOwner") is not None:
                yield f"row:owner without a stage map at {vwhere}"
            vid, el = video.get("id"), video.get("elId")
            if _id(vid):
                ids.append(vid)
                if el is None and _id(el_ids.get(vid)):
                    yield f"row:elId untagged after tagging at {vwhere}"
                elif _id(el):
                    if el_ids.setdefault(vid, el) != el:
                        yield f"row:elId changed at {vwhere}"
                    if probe_ids.setdefault(el, vid) != vid:
                        yield f"row:elId under another id at {vwhere}"
            if _id(el):
                els.append(el)
        yield from _unique(ids, "row:duplicate id", where)
        yield from _unique(els, "row:duplicate elId", where)
    if len(schemas) > 1:
        yield f"rows:mixed sampler schemas at {path}"
    if schemas and (schemas == {True}) != (schema == paint_instrument.SAMPLER_SCHEMA):
        yield f"rows:schema at {path} (sampler schema {schema!r})"
    if len(generations) > 1:
        yield f"rows:mixed decoder generations at {path}"


PAINTING_FIELDS = {"src": lambda v: isinstance(v, str), "elId": _id_or_null, "rect": lambda v: _box(v, 1)}


def painting(value: Any, path: str) -> Iterator[str]:
    """`PAINTING_VIDEOS_JS`: `{error}`, or painting decoders with a rect over 1 px and unique non-null `elId`s."""
    if _error_read(value):
        return
    if not isinstance(value, list):
        yield f"painting:list at {path}"
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            yield f"painting:object at {path}[{index}]"
            continue
        yield from _fields(entry, "painting", f"{path}[{index}]", PAINTING_FIELDS)
    yield from _unique([e["elId"] for e in value if isinstance(e, dict) and _id(e.get("elId"))],
                       "painting:duplicate elId", path)


POOL_FIELDS = {
    "key": lambda v: isinstance(v, str), "movieKey": _str_or_null, "elId": _id, "currentTime": _finite,
    "paused": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool),
    "inDocument": lambda v: isinstance(v, bool), "readyState": _ready_state, "videoWidth": _count,
    "videoHeight": _count,
}


def pool(value: Any, path: str) -> Iterator[str]:
    """The core's `snapshot()`: null, `{error}`, or pool entries then `fromDom` entries. `instance` is on every entry
    or none; an empty `key` only on a `fromDom` entry (a cleared src), which keeps its movie stamp; `elId` unique
    within each half."""
    if value is None or _error_read(value):
        return
    if not isinstance(value, list):
        yield f"pool:list at {path}"
        return
    instances = set()
    for index, entry in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(entry, dict):
            yield f"pool:object at {where}"
            continue
        yield from _fields(entry, "pool", where, POOL_FIELDS)
        instances.add("instance" in entry)
        if "instance" in entry and not (entry["instance"] is None or _non_empty_str(entry["instance"])):
            yield f"pool.instance at {where}"
        if "fromDom" in entry and entry["fromDom"] is not True:
            yield f"pool.fromDom at {where}"
        if entry.get("key") == "" and "fromDom" not in entry:
            yield f"pool:empty key off the DOM at {where}"
        elif entry.get("key") == "" and entry.get("movieKey") is None:
            yield f"pool:empty key without its movie stamp at {where}"
    if len(instances) > 1:
        yield f"pool:instance on some entries at {path}"
    entries = [e for e in value if isinstance(e, dict) and _id(e.get("elId"))]
    for from_dom in (False, True):
        yield from _unique([e["elId"] for e in entries if ("fromDom" in e) is from_dom],
                           f"pool:duplicate elId{' fromDom' if from_dom else ''}", path)


NOTE_IDENTITY = {
    "elId": _id, "newElId": _id, "oldElId": _id,
    "elIds": lambda v: isinstance(v, list) and bool(v) and all(_id(x) for x in v),
    "key": _str_or_null, "movieKey": _str_or_null, "instance": _str_or_null, "src": _str_or_null, "dst": _str_or_null,
}
NOTE_PAYLOADS: dict[str, dict[str, Any]] = {
    "glreplay-carried": {"elId": _id, "delta": lambda v: _finite(v) and 0 <= v <= 1},
    "glreplay-release": {"ok": lambda v: isinstance(v, bool), "mode": lambda v: v in ("retire", "handoff", None),
                         "retired": lambda v: isinstance(v, list) and all(_id(x) for x in v)},
    "glreplay-zone": {"key": lambda v: isinstance(v, str), "from": lambda v: v in ZONE_FROM,
                      "to": lambda v: v in ZONE_TO, "reason": lambda v: isinstance(v, str)},
    "remount-done": {"elId": _id},
    "remount-footprint-rect": {"elId": _id},
    "preserve-refused": {"scene": lambda v: v is None or _int(v), "via": lambda v: v in REFUSE_VIAS},
    "retire-boundary": {"key": lambda v: isinstance(v, str), "elIds": NOTE_IDENTITY["elIds"], "atScene": _int},
    "reuse-decoder": {"key": lambda v: isinstance(v, str), "src": lambda v: isinstance(v, str),
                      "dst": lambda v: isinstance(v, str), "newElId": _id, "oldElId": _id},
    "bridge-motion-start": {"durationSeconds": lambda v: _finite(v) and v > 0, "srcRect": _box, "rect": _box},
    "bridge-clock": {"via": lambda v: v in ("gl", "fallback"), "lagMs": _finite},
    "player-build-error": {"errorType": lambda v: v in ("error", "unhandledrejection"),
                           "message": lambda v: isinstance(v, str)},
    "poster-hold": {"elId": _id, "objectId": _non_empty_str,
                    "t": lambda v: _finite(v) and v >= 0, "reason": _str_or_null},
    "poster-resume": {"elId": _id, "t": lambda v: _finite(v) and v >= 0},
    "mm-feed-claim": {"objectId": _non_empty_str, "mode": lambda v: v == "continuous"},
    "mm-feed-stand-down": {"objectId": _non_empty_str, "reason": _non_empty_str,
                            "usableContext": lambda v: isinstance(v, bool),
                            "boundTextures": lambda v: isinstance(v, bool)},
}
NOTE_PAYLOADS["bridge-3to4"] = NOTE_PAYLOADS["reuse-decoder"]


def _note_detail(kind: str, detail: dict[str, Any], path: str) -> Iterator[str]:
    for key, valid in NOTE_IDENTITY.items():
        if key not in detail:
            continue
        if key == "elId" and kind == "glreplay-release" and detail[key] is None:
            continue
        if not valid(detail[key]):
            yield f"note.{key} at {path}"
    yield from _fields(detail, kind, path, NOTE_PAYLOADS.get(kind, {}))
    if kind == "glreplay-release" and detail.get("mode") == "handoff" \
            and not (detail.get("ok") is True and _id(detail.get("elId"))):
        yield f"glreplay-release:handoff without ok and its elId at {path}"
    if kind == "retire-boundary" and "instance" in detail and not isinstance(detail["instance"], str):
        yield f"retire-boundary.instance at {path}"
    if kind == "bridge-clock" and detail.get("via") == "fallback" and _finite(detail.get("lagMs")) \
            and detail["lagMs"] < BRIDGE_CLOCK_FALLBACK_MIN_MS:
        yield f"bridge-clock:fallback before its wait at {path}"


def notes(value: Any, path: str, kinds: re.Pattern[str] | None = None, *, module: bool = False,
          readable: bool = True) -> Iterator[str]:
    """A note list: `{kind, detail, t}` in non-decreasing `t`, each kind within the read's filter; a core note's
    detail carries its `sceneHash` (a module event's does not). `readable` admits the producers' null and `{error}`."""
    if readable and (value is None or _error_read(value)):
        return
    if not isinstance(value, list):
        yield f"notes:list at {path}"
        return
    prev = None
    for index, note in enumerate(value):
        where = f"{path}[{index}]"
        if not (isinstance(note, dict) and _non_empty_str(note.get("kind")) and isinstance(note.get("detail"), dict)
                and _finite(note.get("t"))):
            yield f"note:envelope at {where}"
            continue
        if kinds is not None and not kinds.search(note["kind"]):
            yield f"note:kind outside the read's filter at {where}"
        if not module and not isinstance(note["detail"].get("sceneHash"), str):
            yield f"note.sceneHash at {where}"
        if prev is not None and note["t"] < prev:
            yield f"note:t decreasing at {where}"
        prev = note["t"]
        yield from _note_detail(note["kind"], note["detail"], f"{where}.detail")


API_STATS_FIELDS = {"epoch": _int, "iter": _int, "uploads": _int, "glErrors": _int}


def api(value: Any, path: str) -> Iterator[str]:
    """`window.__OBED_GL_REPLAY__` as read: null, `{error}`, or version 1 with a known state, its stand-downs (none
    before a stand-down, at least one once RETIRED), its events and its stats."""
    if value is None or _error_read(value):
        return
    if not isinstance(value, dict):
        yield f"api:object at {path}"
        return
    if value.get("version") != 1:
        yield f"api.version at {path}"
    if value.get("state") not in GL_STATES:
        yield f"api.state at {path}"
    downs = value.get("standDowns")
    if not (isinstance(downs, list) and all(isinstance(d, str) for d in downs)):
        yield f"api.standDowns at {path}"
    elif value.get("state") == "RETIRED" and not downs:
        yield f"api:retired without a stand-down at {path}"
    elif value.get("state") in ("IDLE", "ARM-PRE", "ARM-POST", "LIVE") and downs:
        yield f"api:stand-down before STANDDOWN at {path}"
    if "events" not in value:
        yield f"api.events:missing at {path}"
    else:
        yield from notes(value["events"], f"{path}.events", module=True, readable=False)
    if "stats" not in value:
        yield f"api.stats:missing at {path}"
    elif value["stats"] is not None:
        if not isinstance(value["stats"], dict):
            yield f"api.stats at {path}"
        else:
            yield from _fields(value["stats"], "api.stats", f"{path}.stats", API_STATS_FIELDS)


GL_READ_FIELDS = {"t": _finite, "hash": lambda v: isinstance(v, str), "ready": lambda v: v is None or isinstance(v, bool)}


def gl_read(value: Any, path: str) -> Iterator[str]:
    """`GL_REPLAY_READ_JS`."""
    if not isinstance(value, dict):
        yield f"gl:object at {path}"
        return
    yield from _fields(value, "gl", path, GL_READ_FIELDS)
    for key, check in (("api", api), ("pool", pool)):
        if key not in value:
            yield f"gl.{key}:missing at {path}"
        else:
            yield from check(value[key], f"{path}.{key}")
    if "coreEvents" not in value:
        yield f"gl.coreEvents:missing at {path}"
    else:
        yield from notes(value["coreEvents"], f"{path}.coreEvents", GL_NOTE_KINDS)
    facades = value.get("facades")
    if not (isinstance(facades, list) and all(
        isinstance(f, dict) and "elId" in f and "forElId" in f and _id_or_null(f["elId"]) and _id_or_null(f["forElId"])
        for f in facades
    )):
        yield f"gl.facades at {path}"


def _read_parts(value: dict[str, Any], path: str) -> Iterator[str]:
    for key in ("stageMap", "painting"):
        if key not in value:
            yield f"read.{key}:missing at {path}"
    yield from stage_map(value.get("stageMap"), f"{path}.stageMap")
    if "painting" in value:
        yield from painting(value["painting"], f"{path}.painting")
    if "poolSnapshot" in value:
        yield from pool(value["poolSnapshot"], f"{path}.poolSnapshot")


def refusal_read(value: Any, path: str) -> Iterator[str]:
    """`refusal_evidence` plus `CORE_EVENTS_JS` (a census read carries only the stage map and painting)."""
    if not isinstance(value, dict):
        yield f"read:object at {path}"
        return
    yield from _read_parts(value, path)
    if "coreEvents" in value:
        yield from notes(value["coreEvents"], f"{path}.coreEvents", REFUSAL_NOTE_KINDS)


def armed_reads(value: Any, path: str) -> Iterator[str]:
    """`armed_evidence`: exactly two reads with a GL read each, or `{reason}` when the hash never settled."""
    if isinstance(value, dict) and set(value) == {"reason"} and isinstance(value["reason"], str):
        return
    if not (isinstance(value, list) and len(value) == 2):
        yield f"armed:two reads at {path}"
        return
    for index, read in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(read, dict):
            yield f"read:object at {where}"
            continue
        yield from _read_parts(read, where)
        if "poolSnapshot" not in read:
            yield f"read.poolSnapshot:missing at {where}"
        if "glReplay" not in read:
            yield f"read.glReplay:missing at {where}"
        else:
            yield from gl_read(read["glReplay"], f"{where}.glReplay")


def evidence(value: Any, path: str = "evidence") -> Iterator[str]:
    """Every boundary-observer value: armed reads (a list, or `{reason}`) or a refusal read."""
    if not isinstance(value, dict):
        yield f"evidence:object at {path}"
        return
    for key, item in value.items():
        where = f"{path}.{key}"
        if isinstance(item, list) or isinstance(item, dict) and set(item) == {"reason"}:
            yield from armed_reads(item, where)
        else:
            yield from refusal_read(item, where)


MM_FEED_CONTEXT_FIELDS = {
    "serial": _id, "id": _non_empty_str, "createdAt": _finite, "atScene": _count,
    "lost": lambda v: isinstance(v, bool),
    "entryIds": lambda v: isinstance(v, list) and all(_non_empty_str(item) for item in v),
}
MM_FEED_TEXTURE_FIELDS = {
    "unit": lambda v: _int(v) and v in (0, 1), "ordinal": _count,
    "size": lambda v: isinstance(v, list) and len(v) == 2 and all(_count(n) for n in v),
    "video": lambda v: isinstance(v, bool), "flip": lambda v: isinstance(v, bool),
}
MM_FEED_DECODER_FIELDS = {
    "objectId": _non_empty_str, "elId": _id_or_null, "currentTime": lambda v: _finite(v) and v >= 0,
    "paused": lambda v: isinstance(v, bool), "readyState": _ready_state,
    "opacityProduct": lambda v: _finite(v) and v >= 0, "visible": lambda v: isinstance(v, bool),
    "instance": _str_or_null,
}


def _mm_feed_texture(value: Any, path: str) -> Iterator[str]:
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"mmFeed.texture:object at {path}"
        return
    yield from _fields(value, "mmFeed.texture", path, MM_FEED_TEXTURE_FIELDS)
    for key in ("presentedFrames", "mediaTime"):
        if key in value and value[key] is not None and not _finite(value[key]):
            yield f"mmFeed.texture.{key} at {path}"


def _mm_feed_decoder(value: Any, path: str) -> Iterator[str]:
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"mmFeed.decoder:object at {path}"
        return
    yield from _fields(value, "mmFeed.decoder", path, MM_FEED_DECODER_FIELDS)
    for key in ("presentedFrames", "mediaTime"):
        if key in value and value[key] is not None and not _finite(value[key]):
            yield f"mmFeed.decoder.{key} at {path}"


def mm_feed_report(value: Any, path: str = "mmFeedEvidence") -> Iterator[str]:
    """`mm_feed_instrument.INSTRUMENT_JS` report and its decoder/GL frame producers."""
    if not isinstance(value, dict):
        yield f"mmFeed:object at {path}"
        return
    if value.get("kind") != "mm-feed" or value.get("version") != 1:
        yield f"mmFeed:version at {path}"
    for key in ("contexts", "frames", "holds", "media", "artwork", "errors", "killedOnce"):
        if not isinstance(value.get(key), list):
            yield f"mmFeed.{key}:list at {path}"
    for index, context in enumerate(value.get("contexts") or []):
        where = f"{path}.contexts[{index}]"
        if not isinstance(context, dict):
            yield f"mmFeed.context:object at {where}"
        else:
            yield from _fields(context, "mmFeed.context", where, MM_FEED_CONTEXT_FIELDS)
    previous = None
    for index, frame in enumerate(value.get("frames") or []):
        where = f"{path}.frames[{index}]"
        if not isinstance(frame, dict):
            yield f"mmFeed.frame:object at {where}"
            continue
        yield from _fields(frame, "mmFeed.frame", where, {
            "serial": _id, "atScene": _count, "n": _id, "t": _finite, "draws": _count, "uploads": _count,
            "rows": lambda v: isinstance(v, list), "labels": lambda v: isinstance(v, list),
            "riders": lambda v: isinstance(v, list), "glErrors": lambda v: isinstance(v, list) and all(_int(e) for e in v),
        })
        if previous is not None and _finite(frame.get("t")) and frame["t"] < previous:
            yield f"mmFeed.frame:t decreasing at {where}"
        if _finite(frame.get("t")):
            previous = frame["t"]
        for rindex, row in enumerate(frame.get("rows") or []):
            rwhere = f"{where}.rows[{rindex}]"
            if not isinstance(row, dict):
                yield f"mmFeed.row:object at {rwhere}"
                continue
            yield from _fields(row, "mmFeed.row", rwhere, {
                "entryId": _non_empty_str, "objectId": _non_empty_str, "dstObjectId": _non_empty_str,
                "serial": _id, "atScene": _count, "draw": _id, "t": _finite,
                "textures": lambda v: isinstance(v, list) and len(v) == 2,
                "feedRead": lambda v: isinstance(v, dict),
            })
            yield from _mm_feed_decoder(row.get("decoder"), f"{rwhere}.decoder")
            for tindex, texture in enumerate(row.get("textures") or []):
                yield from _mm_feed_texture(texture, f"{rwhere}.textures[{tindex}]")
            read = row.get("feedRead")
            if isinstance(read, dict):
                yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                    "patchInside": lambda v: isinstance(v, bool),
                    "coveredByLaterDraw": lambda v: isinstance(v, bool),
                    "kind": lambda v: v in ("counter", "alpha"),
                })
                fields = ("counter", "referenceCounter") if read.get("kind") == "counter" else (
                    "dVideo", "dPoster"
                )
                yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                    key: lambda v: v is None or _finite(v) for key in fields
                })
            match = row.get("holdMatch")
            if match is not None:
                if not isinstance(match, dict):
                    yield f"mmFeed.holdMatch:object at {rwhere}.holdMatch"
                else:
                    yield from _fields(match, "mmFeed.holdMatch", f"{rwhere}.holdMatch", {
                        "bestFrame": _count, "matchDistance": lambda v: _finite(v) and v >= 0,
                        "matchMargin": _finite, "requiredMargin": lambda v: _finite(v) and v >= 0,
                    })
        for lindex, label in enumerate(frame.get("labels") or []):
            lwhere = f"{where}.labels[{lindex}]"
            if not isinstance(label, dict):
                yield f"mmFeed.label:object at {lwhere}"
            else:
                yield from _fields(label, "mmFeed.label", lwhere, {
                    "entryId": _non_empty_str, "serial": _id, "atScene": _count,
                    "opacity": _finite, "spread": lambda v: _finite(v) and v >= 0,
                    "slope": lambda v: v is None or _finite(v),
                })
        for rindex, rider in enumerate(frame.get("riders") or []):
            rwhere = f"{where}.riders[{rindex}]"
            if not isinstance(rider, dict):
                yield f"mmFeed.rider:object at {rwhere}"
            else:
                yield from _fields(rider, "mmFeed.rider", rwhere, {
                    "entryId": _non_empty_str, "serial": _id, "atScene": _count, "instance": _non_empty_str,
                    "visible": lambda v: isinstance(v, bool), "opacityProduct": lambda v: _finite(v) and v >= 0,
                    "intersectsCanvas": lambda v: isinstance(v, bool),
                })
    for index, entry in enumerate(value.get("killedOnce") or []):
        where = f"{path}.killedOnce[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.killedOnce:object at {where}"
        else:
            yield from _fields(entry, "mmFeed.killedOnce", where, {"objectId": _non_empty_str, "t": _finite})
    for index, entry in enumerate(value.get("media") or []):
        where = f"{path}.media[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.media:object at {where}"
            continue
        yield from _fields(entry, "mmFeed.media", where, {
            "kind": lambda v: v in ("pause", "play", "seeking", "videoFrame"), "t": _finite,
            "serial": _id, "atScene": _count, "entryId": _non_empty_str, "instance": _non_empty_str, "elId": _id_or_null,
            "currentTime": lambda v: _finite(v) and v >= 0, "paused": lambda v: isinstance(v, bool),
        })
        for key in ("presentedFrames", "mediaTime"):
            if key in entry and entry[key] is not None and not _finite(entry[key]):
                yield f"mmFeed.media.{key} at {where}"
        if entry.get("kind") == "videoFrame":
            yield from _fields(entry, "mmFeed.media", where, {
                "presentedFrames": _count, "mediaTime": lambda v: _finite(v) and v >= 0,
            })
    for index, entry in enumerate(value.get("artwork") or []):
        where = f"{path}.artwork[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.artwork:object at {where}"
        else:
            yield from _fields(entry, "mmFeed.artwork", where, {
                "entryId": _non_empty_str, "serial": _id_or_null, "atScene": _count,
                "artworkAbove": lambda v: isinstance(v, bool),
            })


def feed_verdict_record(value: Any, path: str = "feedVerdict") -> Iterator[str]:
    """The scorer-facing feed/hold record assembled from the in-frame producer."""
    if not isinstance(value, dict):
        yield f"feedVerdict:object at {path}"
        return
    if value.get("mode") not in ("continuous", "once", "departure", "standDown"):
        yield f"feedVerdict.mode at {path}"
    for key in ("usableContext", "boundTextures"):
        if not isinstance(value.get(key), bool):
            yield f"feedVerdict.{key} at {path}"
    interval = value.get("interval")
    if interval is not None and not (
        isinstance(interval, dict) and _finite(interval.get("start")) and _finite(interval.get("end"))
        and interval["end"] > interval["start"]
    ):
        yield f"feedVerdict.interval at {path}"
    if "notes" in value:
        yield from notes(value["notes"], f"{path}.notes", MM_FEED_NOTE_KINDS, module=True, readable=False)
    required = ("feed", "rider", "labels", "artwork") if value.get("mode") == "continuous" else (
        "hold", "poster", "rider", "artwork"
    )
    if value.get("continuousExpected") is True and "feed" not in required:
        required = (*required, "feed")
    for key in required:
        if not isinstance(value.get(key), dict):
            yield f"feedVerdict.{key}:object at {path}"
    for key in ("feed", "hold"):
        record = value.get(key)
        if not isinstance(record, dict):
            continue
        for field in ("usableContext", "boundTextures"):
            if not isinstance(record.get(field), bool):
                yield f"feedVerdict.{key}.{field} at {path}"
        if not isinstance(record.get("reads"), list):
            yield f"feedVerdict.{key}.reads:list at {path}"
    feed = value.get("feed")
    for index, read in enumerate(feed.get("reads") or [] if isinstance(feed, dict) else []):
        where = f"{path}.feed.reads[{index}]"
        if not isinstance(read, dict):
            yield f"feedVerdict.feed.read:object at {where}"
            continue
        yield from _fields(read, "feedVerdict.feed.read", where, {
            "progress": _finite, "patchInside": lambda v: isinstance(v, bool),
            "coveredByLaterDraw": lambda v: isinstance(v, bool), "kind": lambda v: v in ("counter", "alpha"),
        })
        fields = ("counter", "referenceCounter") if read.get("kind") == "counter" else ("dVideo", "dPoster")
        yield from _fields(read, "feedVerdict.feed.read", where, {
            key: lambda v: v is None or _finite(v) for key in fields
        })
    hold = value.get("hold")
    for index, read in enumerate(hold.get("reads") or [] if isinstance(hold, dict) else []):
        where = f"{path}.hold.reads[{index}]"
        if not isinstance(read, dict):
            yield f"feedVerdict.hold.read:object at {where}"
            continue
        yield from _fields(read, "feedVerdict.hold.read", where, {
            "phase": lambda v: v in ("first", "middle", "last"), "bestFrame": _count,
            "matchMargin": _finite, "requiredMargin": lambda v: _finite(v) and v >= 0,
        })
    for key, list_key in (("rider", "riders"), ("labels", "labels"), ("artwork", "reads")):
        record = value.get(key)
        if isinstance(record, dict) and not isinstance(record.get(list_key), list):
            yield f"feedVerdict.{key}.{list_key}:list at {path}"


HANDBACK_FIELDS = {"status": lambda v: v in ("ok", "inconclusive"), "reason": _str_or_null, "targetHash": _int,
                   "expectHandoff": lambda v: isinstance(v, bool)}


def handback_record(value: Any, path: str = "handback") -> Iterator[str]:
    """`capture_handback`: the GL reads it took (`before`, `polled`, `after`); an `ok` record also has the settled
    stage map, painting and preserve snapshot."""
    if not isinstance(value, dict):
        yield f"handback:object at {path}"
        return
    yield from _fields(value, "handback", path, HANDBACK_FIELDS)
    required = ("before", "stageMap", "painting", "preserve", "after") if value.get("status") == "ok" else ()
    for key in required:
        if key not in value:
            yield f"handback.{key}:missing at {path}"
    for key in ("before", "polled", "after"):
        if key in value:
            yield from gl_read(value[key], f"{path}.{key}")
    if "stageMap" in value:
        yield from stage_map(value["stageMap"], f"{path}.stageMap")
    if "painting" in value:
        yield from painting(value["painting"], f"{path}.painting")
    if "preserve" in value:
        yield from pool(value["preserve"], f"{path}.preserve")


def _seeked(v: Any) -> bool:
    return v is None or _finite(v)


SELECT_FIELDS = {"domId": lambda v: isinstance(v, str), "count": _count, "t": _finite}
SELECT_SEEK_FIELDS = {"duration": lambda v: v is None or _finite(v) and v > 0, "loop": lambda v: isinstance(v, bool),
                      "playbackRate": _finite, "seekFrom": _finite, "target": _seeked}
FRAME_FIELDS = {"now": _finite, "mediaTime": lambda v: _finite(v) and v >= 0, "presentedFrames": _int}
STATUS_FIELDS = {"t": _finite, "seekedT": _seeked, "framesAfterSeek": _count,
                 "duration": lambda v: v is None or _finite(v) and v > 0, "playbackRate": _finite}
RECORDER_FIELDS = {
    "t": _finite, "seekedT": _seeked, "seekFrom": _finite, "target": _seeked, "frames": lambda v: isinstance(v, list),
    "id": lambda v: isinstance(v, str), "elId": _id_or_null, "probeId": _id_or_null,
    "loop": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool), "paused": lambda v: isinstance(v, bool),
    "isConnected": lambda v: isinstance(v, bool), "duration": lambda v: v is None or _finite(v) and v > 0,
    "playbackRate": _finite,
}


def _frame(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"frame:object at {path}"
    else:
        yield from _fields(value, "frame", path, FRAME_FIELDS)


def force_wrap(result: Any) -> Iterator[str]:
    """One force-wrap take: its rows, the seek (`take.select`, `take.status`), the recorder, the armed reads and the
    page-error notes."""
    if not isinstance(result, dict):
        yield "forceWrap:object at result"
        return
    sampler = result.get("sampler") if isinstance(result.get("sampler"), dict) else {}
    yield from sample_rows(result.get("samples") or [], schema=sampler.get("schema"))
    take = result.get("take") if isinstance(result.get("take"), dict) else {}
    select = take.get("select")
    if "select" in take:
        if not isinstance(select, dict):
            yield "select:object at take.select"
        else:
            yield from _fields(select, "select", "take.select", SELECT_FIELDS)
            if select.get("count") == 1 and "error" not in select:
                yield from _fields(select, "select", "take.select", SELECT_SEEK_FIELDS)
            elif "error" in select and not isinstance(select["error"], str):
                yield "select.error at take.select"
    status = take.get("status")
    if status is not None:
        if not isinstance(status, dict):
            yield "status:object at take.status"
        else:
            yield from _fields(status, "status", "take.status", STATUS_FIELDS)
            if status.get("last") is not None:
                yield from _frame(status["last"], "take.status.last")
    recorder = result.get("recorder")
    if recorder is not None:
        if not isinstance(recorder, dict):
            yield "recorder:object at recorder"
        else:
            yield from _fields(recorder, "recorder", "recorder", RECORDER_FIELDS)
            frames = recorder.get("frames") if isinstance(recorder.get("frames"), list) else []
            for index, frame in enumerate(frames):
                yield from _frame(frame, f"recorder.frames[{index}]")
            good = [f for f in frames if isinstance(f, dict) and _finite(f.get("now")) and _int(f.get("presentedFrames"))]
            if any(b["now"] <= a["now"] for a, b in zip(good, good[1:])):
                yield "recorder:frame times not increasing at recorder.frames"
            if any(b["presentedFrames"] < a["presentedFrames"] for a, b in zip(good, good[1:])):
                yield "recorder:presentedFrames decreasing at recorder.frames"
    if "reads" in result:
        yield from armed_reads(result["reads"], "reads")
    if result.get("pageErrorNotes") is not None:
        yield from notes(result["pageErrorNotes"], "pageErrorNotes", PAGE_ERROR_NOTE_KINDS, readable=False)


VID_FIELDS = {"elId": _id, "x": _finite, "y": _finite, "w": lambda v: _finite(v) and v >= 0,
              "h": lambda v: _finite(v) and v >= 0, "readyState": _ready_state, "opaque": lambda v: isinstance(v, bool)}


def _vids(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, list):
        yield f"carryCover:vids list at {path}"
        return
    for index, vid in enumerate(value):
        if not isinstance(vid, dict):
            yield f"vid:object at {path}[{index}]"
        else:
            yield from _fields(vid, "vid", f"{path}[{index}]", VID_FIELDS)
            if "src" in vid and not isinstance(vid["src"], str):
                yield f"vid.src at {path}[{index}]"
    yield from _unique([v["elId"] for v in value if isinstance(v, dict) and _id(v.get("elId"))],
                       "carryCover:duplicate elId", path)


def carry_cover(rows: Any, notes_read: Any, stage: Any) -> Iterator[str]:
    """`CARRY_COVER_SAMPLER_JS` rows (`ts` increasing, `tick` contiguous mod 4096, `vids` with its `readAt` on every
    row but a trailing run; every read with a string `src`, or none in a legacy record), `CARRY_COVER_READ_JS` notes
    and the capture's stage map."""
    yield from stage_map(stage, "stageMap")
    yield from notes(notes_read, "notes", CARRY_COVER_NOTE_KINDS, readable=False)
    if rows is None:
        return
    if not isinstance(rows, list):
        yield "carryCover:rows list at rows"
        return
    prev = None
    unread = False
    sourced: set[bool] = set()
    for index, row in enumerate(rows):
        where = f"rows[{index}]"
        if not isinstance(row, dict):
            yield f"carryCover:row object at {where}"
            prev = None
            continue
        if not _finite(row.get("ts")):
            yield f"carryCover.ts at {where}"
        if not (_int(row.get("tick")) and 0 <= row["tick"] < CARRY_COVER_TICKS):
            yield f"carryCover.tick at {where}"
        if prev is not None and _finite(row.get("ts")) and _finite(prev.get("ts")) and row["ts"] <= prev["ts"]:
            yield f"carryCover:ts not increasing at {where}"
        if prev is not None and _int(row.get("tick")) and _int(prev.get("tick")) \
                and row["tick"] != (prev["tick"] + 1) % CARRY_COVER_TICKS:
            yield f"carryCover:tick not contiguous at {where}"
        yield from _vids(row.get("pre"), f"{where}.pre")
        sourced.update(
            "src" in v for key in ("pre", "vids") if isinstance(row.get(key), list) for v in row[key] if isinstance(v, dict)
        )
        if "vids" in row:
            if unread:
                yield f"carryCover:read after an unread row at {where}"
            yield from _vids(row["vids"], f"{where}.vids")
            if not _finite(row.get("readAt")):
                yield f"carryCover.readAt at {where}"
        else:
            unread = True
            if "readAt" in row:
                yield f"carryCover:readAt without vids at {where}"
        prev = row
    if len(sourced) > 1:
        yield "carryCover:mixed read generations (with and without src) at rows"


def census(raw: Any, path: str = "censusRaw") -> Iterator[str]:
    """`census_observer`: per slide, a list of `{stageMap, painting}` reads."""
    if not isinstance(raw, dict):
        return
    for key, reads in raw.items():
        if not isinstance(reads, list):
            continue
        for index, read in enumerate(reads):
            yield from refusal_read(read, f"{path}.{key}[{index}]")


MANAGED_VIDEO_FIELDS = {"src": lambda v: isinstance(v, str), "paused": lambda v: isinstance(v, bool),
                        "rs": _ready_state, "t": _finite, "loop": lambda v: isinstance(v, bool)}
MANAGED_HANDED_FIELDS = {"elId": _id, "loop": lambda v: isinstance(v, bool), "isConnected": lambda v: isinstance(v, bool),
                         "facade": lambda v: isinstance(v, bool), "paused": lambda v: isinstance(v, bool), "t": _finite}
MANAGED_SAMPLE_FIELDS = {"t": _finite, "state": lambda v: v is None or v in GL_STATES,
                         "standDowns": lambda v: v is None or isinstance(v, list) and all(isinstance(d, str) for d in v),
                         "videoEnded": lambda v: v is None or isinstance(v, bool),
                         "uploads": lambda v: v is None or _int(v), "carriedT": lambda v: v is None or _finite(v)}


def _managed_list(value: Any, path: str, kind: str, table: dict[str, Any]) -> Iterator[str]:
    if not isinstance(value, list):
        yield f"{kind}:list at {path}"
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            yield f"{kind}:object at {path}[{index}]"
        else:
            yield from _fields(entry, kind, f"{path}[{index}]", table)


def _handed_back(value: Any, path: str) -> Iterator[str]:
    """`HANDED_BACK_JS`: every element with the carried `elId`; the dd9ecc9f generation read the first one alone,
    without `facade`, or `{elId, missing: true}`."""
    if not isinstance(value, dict):
        yield from _managed_list(value, path, "managed.handedBack", MANAGED_HANDED_FIELDS)
    elif value.get("missing") is not True:
        yield from _fields(value, "managed.handedBack", path,
                           {k: v for k, v in MANAGED_HANDED_FIELDS.items() if k != "facade"})


def managed_session(session: Any, path: str) -> Iterator[str]:
    """One `managed_obs_qualify` session: its page reads (`Session.read`), phase records, armed reads, hand-back and
    video reads, context-loss result and precheck samples."""
    if not isinstance(session, dict):
        yield f"managed:session object at {path}"
        return
    for tag, read in (session.get("reads") or {}).items():
        where = f"{path}.reads.{tag}"
        if not isinstance(read, dict):
            yield f"managed:read object at {where}"
            continue
        if not _finite(read.get("wall")):
            yield f"managed.wall at {where}"
        yield from gl_read(read.get("gl"), f"{where}.gl")
        if "painting" not in read:
            yield f"managed.painting:missing at {where}"
        else:
            yield from painting(read["painting"], f"{where}.painting")
        yield from _managed_list(read.get("videos"), f"{where}.videos", "managed.video", MANAGED_VIDEO_FIELDS)
    for index, phase in enumerate(session.get("phases") or []):
        where = f"{path}.phases[{index}]"
        if not isinstance(phase, dict):
            yield f"managed:phase object at {where}"
            continue
        if not isinstance(phase.get("hash"), str):
            yield f"managed.hash at {where}"
        yield from _managed_list(phase.get("videos"), f"{where}.videos", "managed.video", MANAGED_VIDEO_FIELDS)
        raf = phase.get("raf")
        if not (isinstance(raf, list) and len(raf) == 2 and _finite(raf[0]) and _int(raf[1])):
            yield f"managed.raf at {where}"
    if "armed" in session:
        yield from armed_reads(session["armed"], f"{path}.armed")
    for key in ("slide1Videos", "postHandbackVideos"):
        if key in session:
            yield from _managed_list(session[key], f"{path}.{key}", "managed.video", MANAGED_VIDEO_FIELDS)
    if "handedBack" in session:
        yield from _handed_back(session["handedBack"], f"{path}.handedBack")
    if "loseContext" in session and not isinstance(session["loseContext"], dict):
        yield f"managed.loseContext at {path}"
    if "samples" in session:
        yield from _managed_list(session["samples"], f"{path}.samples", "managed.sample", MANAGED_SAMPLE_FIELDS)


def managed_run(run: Any) -> Iterator[str]:
    sessions = run.get("sessions") if isinstance(run, dict) else None
    if not isinstance(sessions, list):
        return
    for index, session in enumerate(sessions):
        name = session.get("session") if isinstance(session, dict) else None
        yield from managed_session(session, f"sessions[{name if isinstance(name, str) else index}]")

"""Derive a movie-continuity plan from a Keynote HTML export, without touching the browser.

A `ContinuityPlan` tells the live host, for every slide boundary in player order, what should
happen to each movie that is present on both sides of the boundary: `pin` (Magic Move, same
on-stage rect on both sides -- the live `<video>` keeps playing untouched), `bridge` (Magic Move,
same asset, the rect changes -- the live `<video>` must be moved/resized in place instead of
Keynote's export restarting it from a fresh decoder), or `restart` (dissolve, no transition, or
an unsupported transition -- Keynote's own fresh-decoder behaviour is correct, do nothing).
Geometry is derived from the export's authored layer tree (`renderMovie` node baseLayer +
`isVideoLayer` sub-layer, centre-anchored), never measured on screen. Anything the export
encodes in a way this module cannot map exactly (rotation, animated geometry, an unknown
transition kind, ambiguous ownership of a continuing asset) fails closed to `Unsupported`
instead of guessing. A boundary that is structurally carryable but whose destination slide
draws something over the movie is refused on its own, as a `retire`: the movie goes back to
the player at that scene and the rest of the deck stays as authored.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from obed_edom.html_preview import safe_export_file
from obed_edom.live_codec import codec_family, movie_codec

_GEOMETRY_TOLERANCE = 0.5
_OVERLAP_MIN_PX = 1.0
_TRIM_SUFFIX_RE = re.compile(r"^(?P<name>.+)-\d+\.\d+-\d+\.\d+(?P<ext>\.[A-Za-z0-9]+)$")

_MOVIE_NODE_KEYS = frozenset(
    {"attributes", "baseLayer", "beginTime", "duration", "effects", "movie", "name", "objectID", "type"}
)
_MOVIE_LAYER_KEYS = frozenset(
    {"animations", "initialState", "isVideoLayer", "layers", "objectID", "texture", "texturedRectangle"}
)
_MOVIE_LAYER_STATE_KEYS = frozenset(
    {
        "affineTransform", "anchorPoint", "contentsRect", "edgeAntialiasingMask", "height", "hidden",
        "masksToBounds", "opacity", "position", "rotation", "scale", "sublayerTransform", "width",
    }
)
"""The complete key vocabulary measured across every movie node of the qualified export. A key
outside it may encode a mask this module cannot map, so it fails closed until a masked deck is
exported and the real encoding is measured."""


class _Refuse(Exception):
    """Internal control-flow only: carries the reason for an `Unsupported` result."""


QUALIFIED_PLAN_SHA256: frozenset[str] = frozenset({"bafe26cad55cf3a390154bce2c0fdcc771b9b1821293b6aec76119d25180e81e"})


def plan_signature(runtime: dict[str, Any]) -> str:
    """The runtime honours only the first restart and first bridge, keeps every decoded
    movie, and picks same-asset instances in DOM order, so a plan is trusted only when
    it is one the P2 gate actually measured."""
    return hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    def close_to(self, other: "Rect", tolerance: float = _GEOMETRY_TOLERANCE) -> bool:
        return (
            abs(self.x - other.x) <= tolerance
            and abs(self.y - other.y) <= tolerance
            and abs(self.w - other.w) <= tolerance
            and abs(self.h - other.h) <= tolerance
        )


@dataclass(frozen=True)
class MovieContinuity:
    asset: str
    action: str
    src_rect: Rect | None
    dst_rect: Rect | None
    refusal: str | None = None
    """Why this boundary cannot carry the movie, when `action` says it structurally could.
    Last field with a default so positional construction keeps working."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "action": self.action,
            "srcRect": self.src_rect.as_dict() if self.src_rect else None,
            "dstRect": self.dst_rect.as_dict() if self.dst_rect else None,
        }


@dataclass(frozen=True)
class SlideBoundary:
    from_player_index: int
    to_player_index: int | None
    movies: tuple[MovieContinuity, ...] = field(default_factory=tuple)
    transition_duration: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "fromPlayerIndex": self.from_player_index,
            "toPlayerIndex": self.to_player_index,
            "movies": [m.as_dict() for m in self.movies],
            "durationSeconds": self.transition_duration,
        }


@dataclass(frozen=True)
class ContinuityPlan:
    canvas: dict[str, int]
    scene_index_by_player: dict[int, int]
    slide_rects: dict[int, dict[str, dict[str, float]]]
    boundaries: tuple[SlideBoundary, ...]
    slide_instances: dict[int, dict[str, list[dict[str, float]]]] = field(default_factory=dict)
    """Every authored movie instance per player index, including multi-instance assets and
    movies no boundary classifies -- ground truth for what should be visibly live on a slide,
    unlike `slide_rects`, which keeps only single-instance assets. Rects are `_movie_rect`'s
    authored-space rects, ordered by (x, y, w, h) ascending. Not part of `to_runtime()`, so
    the runtime plan signature is unaffected."""
    refusals: tuple[dict[str, Any], ...] = ()
    """One entry per boundary a movie structurally continues across but must not be carried
    over. Additive and not part of `to_runtime()`, like `slide_instances`."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "canvas": dict(self.canvas),
            "sceneIndexByPlayer": {str(k): v for k, v in self.scene_index_by_player.items()},
            "slideRects": {str(k): v for k, v in self.slide_rects.items()},
            "boundaries": [b.as_dict() for b in self.boundaries],
            "slideInstances": {str(k): v for k, v in self.slide_instances.items()},
            "refusals": [dict(r) for r in self.refusals],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict())

    def to_runtime(self) -> "dict[str, Any] | Unsupported":
        """Translate this plan into the shape `PRESERVE_CORE_JS` reads as
        `window.__OBED_CONTINUITY__` (see `live_continuity_js` module docstring).
        Fails closed whenever the derived plan says something the runtime cannot
        express today: more than one bridge, a bridge asset with
        no resolvable footprint on the deck's first slide, more than one bridge
        movie at a single boundary, a bridge with no source/destination rect or
        positive export duration, or a `pin`
        action recurring after a `restart` boundary, a bridge before a restart,
        or any actionable boundary after a bridge. A boundary carrying a `refusal` becomes a
        `retire` -- at most one, and only before the first restart and any bridge.
        """
        if not self.boundaries:
            return Unsupported("no boundaries to translate")

        table = _movie_table(self)
        if isinstance(table, Unsupported):
            return table
        movie_keys, movies = table

        runtime_boundaries: list[dict[str, Any]] = []
        emitted_cut = False
        emitted_bridge = False
        emitted_retire = False
        for boundary in self.boundaries:
            if boundary.to_player_index is None:
                continue
            actions = {m.action for m in boundary.movies}
            if emitted_bridge and "bridge" in actions:
                return Unsupported("more than one bridge boundary")
            if emitted_bridge and actions & {"pin", "restart"}:
                return Unsupported("an actionable boundary follows a bridge")
            scene = self.scene_index_by_player.get(boundary.to_player_index)
            if scene is None:
                return Unsupported(f"missing scene index for player index {boundary.to_player_index}")

            refused = [m for m in boundary.movies if m.refusal]
            if refused:
                movie = refused[0]
                if len(refused) > 1 or movie.action != "pin":
                    return Unsupported(f"a refusal the runtime cannot retire: {movie.refusal}")
                if emitted_retire:
                    return Unsupported(f"more than one retire boundary: {movie.refusal}")
                if emitted_cut:
                    return Unsupported(f"a retire boundary follows a restart or bridge cut: {movie.refusal}")
                key = movie_keys.get(movie.asset)
                if key is None:
                    return Unsupported(f"refused asset '{movie.asset}' is not in the movie table")
                runtime_boundaries.append({"atScene": scene, "action": "retire", "movieKey": key})
                emitted_retire = True

            if emitted_cut and "pin" in actions:
                return Unsupported("a pin action follows a restart or bridge boundary")
            if "bridge" in actions:
                if not emitted_cut:
                    return Unsupported("a bridge boundary precedes the first restart")
                bridges = [m for m in boundary.movies if m.action == "bridge"]
                if len(bridges) != 1:
                    return Unsupported("more than one bridge movie at a boundary")
                movie = bridges[0]
                duration = boundary.transition_duration
                if (
                    isinstance(duration, bool)
                    or not isinstance(duration, (int, float))
                    or not math.isfinite(duration)
                    or duration <= 0
                ):
                    return Unsupported("bridge transition has no finite positive export duration")
                if movie.src_rect is None:
                    return Unsupported(f"bridge movie '{movie.asset}' has no source rect")
                if movie.dst_rect is None:
                    return Unsupported(f"bridge movie '{movie.asset}' has no destination rect")
                key = movie_keys.get(movie.asset)
                if key is None:
                    return Unsupported(f"bridging asset '{movie.asset}' is not in the movie table")
                runtime_boundaries.append(
                    {
                        "atScene": scene,
                        "action": "bridge",
                        "movieKey": key,
                        "srcRect": _rect_ints(movie.src_rect.as_dict()),
                        "durationSeconds": duration,
                        "rect": _rect_ints(movie.dst_rect.as_dict()),
                    }
                )
                emitted_cut = True
                emitted_bridge = True
            elif "restart" in actions:
                runtime_boundaries.append({"atScene": scene, "action": "restart"})
                emitted_cut = True
            elif "pin" in actions:
                if emitted_cut:
                    return Unsupported(
                        f"a 'pin' boundary recurs after a restart/bridge cut at player index "
                        f"{boundary.from_player_index}, which the runtime cannot express"
                    )
            else:
                continue

        runtime = {"movies": movies, "boundaries": runtime_boundaries}
        if plan_signature(runtime) not in QUALIFIED_PLAN_SHA256:
            return Unsupported("deck shape is not yet qualified for continuity (only P2-measured plans are)")
        return runtime


@dataclass(frozen=True)
class Unsupported:
    reason: str


def _rect_ints(rect: dict[str, float]) -> dict[str, int]:
    return {k: round(v) for k, v in rect.items()}


def _movie_table(
    plan: ContinuityPlan,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]] | Unsupported:
    """The runtime's `movies` table and the asset -> movie key mapping it implies: the bridging
    asset is `movie1`, the rest follow in asset order."""
    bridge_asset: str | None = None
    for boundary in plan.boundaries:
        for movie in boundary.movies:
            if movie.action != "bridge":
                continue
            if bridge_asset is not None and bridge_asset != movie.asset:
                return Unsupported(
                    f"more than one distinct bridging asset: '{bridge_asset}' and '{movie.asset}'"
                )
            bridge_asset = movie.asset

    first_player = min(plan.slide_rects) if plan.slide_rects else None
    if first_player is None:
        return Unsupported("no slide footprint data to build movie definitions")
    initial_rects: dict[str, dict[str, float]] = dict(plan.slide_rects.get(first_player, {}))

    if plan.boundaries:
        for movie in plan.boundaries[0].movies:
            if movie.action in ("pin", "bridge") and movie.src_rect is not None:
                initial_rects[movie.asset] = movie.src_rect.as_dict()

    if bridge_asset is not None and bridge_asset not in initial_rects:
        return Unsupported(f"bridging asset '{bridge_asset}' has no footprint on the first slide")
    if not initial_rects:
        return Unsupported("no single-instance movie footprints on the first slide")

    ordered_assets = ([bridge_asset] if bridge_asset else []) + sorted(
        asset for asset in initial_rects if asset != bridge_asset
    )
    movie_keys = {asset: f"movie{i + 1}" for i, asset in enumerate(ordered_assets)}
    movies = {
        key: {"assetKeys": [asset.lower()], "footprint": _rect_ints(initial_rects[asset])}
        for asset, key in movie_keys.items()
    }
    return movie_keys, movies


def _identity_transform(state: dict[str, Any]) -> bool:
    transform = list(state.get("affineTransform", [1, 0, 0, 1, 0, 0]))
    return state.get("rotation", 0) == 0 and transform == [1, 0, 0, 1, 0, 0]


def _center_anchor(state: dict[str, Any]) -> bool:
    anchor = state.get("anchorPoint", {})
    return (
        abs(anchor.get("pointX", 0.5) - 0.5) < 1e-6
        and abs(anchor.get("pointY", 0.5) - 0.5) < 1e-6
    )


def _find_movie_nodes(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if "movie" in obj and "baseLayer" in obj:
            found.append(obj)
        for value in obj.values():
            found.extend(_find_movie_nodes(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_movie_nodes(item))
    return found


def _find_video_sublayers(base_layer: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(layer: Any) -> None:
        if not isinstance(layer, dict):
            return
        if layer.get("isVideoLayer") is True:
            found.append(layer)
        for child in layer.get("layers") or []:
            walk(child)

    walk(base_layer)
    return found


def _encoding_refusal(slide_name: str, detail: str) -> _Refuse:
    return _Refuse(
        f"movie on slide {slide_name} carries an unrecognised layer encoding (possible mask): {detail}"
    )


def _contains_key(obj: Any, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_contains_key(value, key) for value in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(item, key) for item in obj)
    return False


def _check_movie_encoding(node: dict[str, Any], slide_name: str) -> None:
    """Interim mask rule: this export family encodes no mask at all, so anything outside the
    measured vocabulary -- or any clipping knob that is not at its neutral value -- may be one."""
    if _contains_key(node, "shapePath"):
        raise _encoding_refusal(slide_name, "shapePath")
    unknown = sorted(set(node) - _MOVIE_NODE_KEYS)
    if unknown:
        raise _encoding_refusal(slide_name, unknown[0])

    def walk(layer: Any) -> None:
        if not isinstance(layer, dict):
            raise _encoding_refusal(slide_name, "a layer that is not an object")
        unknown = sorted(set(layer) - _MOVIE_LAYER_KEYS)
        if unknown:
            raise _encoding_refusal(slide_name, unknown[0])
        state = layer.get("initialState")
        if not isinstance(state, dict):
            raise _encoding_refusal(slide_name, "initialState")
        unknown = sorted(set(state) - _MOVIE_LAYER_STATE_KEYS)
        if unknown:
            raise _encoding_refusal(slide_name, unknown[0])
        if state.get("masksToBounds"):
            raise _encoding_refusal(slide_name, "masksToBounds")
        contents = state.get("contentsRect") or {}
        if any(
            abs(contents.get(name, default) - default) > 1e-6
            for name, default in (("x", 0.0), ("y", 0.0), ("width", 1.0), ("height", 1.0))
        ):
            raise _encoding_refusal(slide_name, "contentsRect")
        for child in layer.get("layers") or []:
            walk(child)

    walk(node["baseLayer"])


def _movie_rect(node: dict[str, Any], slide_name: str) -> Rect:
    _check_movie_encoding(node, slide_name)
    base_layer = node["baseLayer"]
    parent_state = base_layer["initialState"]
    if not _identity_transform(parent_state) or not _center_anchor(parent_state):
        raise _Refuse(
            f"movie layer on slide {slide_name} has a rotated, transformed, or off-center anchor"
        )
    video_layers = _find_video_sublayers(base_layer)
    if len(video_layers) != 1:
        raise _Refuse(
            f"movie node on slide {slide_name} has {len(video_layers)} video sub-layers, expected 1"
        )
    video_layer = video_layers[0]
    if not any(video_layer is child for child in base_layer.get("layers") or []):
        raise _Refuse(f"video sub-layer on slide {slide_name} is not a direct child of its movie layer")
    video_state = video_layer["initialState"]
    if not _identity_transform(video_state) or not _center_anchor(video_state):
        raise _Refuse(
            f"video sub-layer on slide {slide_name} has a rotated, transformed, or off-center anchor"
        )
    if base_layer.get("animations") or video_layer.get("animations"):
        raise _Refuse(f"movie layer on slide {slide_name} has animated geometry")

    parent_x = parent_state["position"]["pointX"] - parent_state["width"] / 2
    parent_y = parent_state["position"]["pointY"] - parent_state["height"] / 2
    child_w, child_h = video_state["width"], video_state["height"]
    abs_center_x = parent_x + video_state["position"]["pointX"]
    abs_center_y = parent_y + video_state["position"]["pointY"]
    rect = Rect(abs_center_x - child_w / 2, abs_center_y - child_h / 2, child_w, child_h)
    base_rect = Rect(parent_x, parent_y, parent_state["width"], parent_state["height"])
    if not _contains(base_rect, rect):
        raise _encoding_refusal(slide_name, "the video sub-layer is not contained in its movie layer")
    return rect


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        inner.x >= outer.x - _GEOMETRY_TOLERANCE
        and inner.y >= outer.y - _GEOMETRY_TOLERANCE
        and inner.x + inner.w <= outer.x + outer.w + _GEOMETRY_TOLERANCE
        and inner.y + inner.h <= outer.y + outer.h + _GEOMETRY_TOLERANCE
    )


def _overlaps(a: Rect, b: Rect) -> bool:
    width = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    height = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return width > _OVERLAP_MIN_PX and height > _OVERLAP_MIN_PX


def _slot_rect(state: dict[str, Any]) -> Rect:
    width, height = state["width"], state["height"]
    return Rect(
        state["position"]["pointX"] - width / 2, state["position"]["pointY"] - height / 2, width, height
    )


def _draw_slots(event: Any, slide_name: str) -> list[Any]:
    base_layer = event.get("baseLayer") if isinstance(event, dict) else None
    slots = base_layer.get("layers") if isinstance(base_layer, dict) else None
    if not isinstance(slots, list):
        raise _Refuse(f"slide {slide_name} declares no readable draw order")
    return slots


def _movie_slot_index(slots: list[Any], object_id: str, slide_name: str) -> int | None:
    found: int | None = None
    for index, slot in enumerate(slots):
        children = slot.get("layers") if isinstance(slot, dict) else None
        if not isinstance(children, list):
            raise _Refuse(f"unrecognised slide layer shape on slide {slide_name} (draw slot {index})")
        if len(children) != 1 or not isinstance(children[0], dict):
            continue
        if children[0].get("objectID") != object_id:
            continue
        if found is not None:
            raise _Refuse(f"slide {slide_name} draws object {object_id} in more than one slot")
        found = index
    return found


def _overlap_refusal(
    events: list[Any], instance: _MovieInstance, asset: str, to_player_index: int, slide_name: str
) -> str | None:
    """Whether any object authored ABOVE the movie's draw slot overlaps its painted rect, on any
    event of the destination slide. Opacity and `hidden` are deliberately ignored: the export does
    not mark a not-yet-built object, so every higher slot counts as artwork."""
    if instance.object_id is None:
        raise _Refuse(f"movie '{asset}' on slide {slide_name} has no object id")
    drawn = False
    for event in events:
        slots = _draw_slots(event, slide_name)
        movie_slot = _movie_slot_index(slots, instance.object_id, slide_name)
        if movie_slot is None:
            continue
        drawn = True
        for index in range(movie_slot + 1, len(slots)):
            children = slots[index]["layers"]
            if len(children) != 1 or not isinstance(children[0], dict):
                raise _Refuse(
                    f"unrecognised slide layer shape on slide {slide_name} (draw slot {index})"
                )
            if _overlaps(_slot_rect(children[0]["initialState"]), instance.rect):
                return (
                    f"later-authored artwork overlaps the carried '{asset}' on the destination "
                    f"slide (player index {to_player_index}, draw slot {index})"
                )
    if not drawn:
        raise _Refuse(f"movie '{asset}' has no draw slot on slide {slide_name}")
    return None


def _normalize_asset_key(assets_table: dict[str, Any], asset_id: str) -> str:
    entry = assets_table.get(asset_id) or {}
    url = entry.get("url") or {}
    filename = (url.get("web") or url.get("native") or asset_id).rsplit("/", 1)[-1]
    match = _TRIM_SUFFIX_RE.match(filename)
    name = match.group("name") if match else filename
    return name.lower()


@dataclass(frozen=True)
class _MovieInstance:
    rect: Rect
    object_id: str | None


def _slide_movie_instances(
    events: list[Any], assets_table: dict[str, Any], slide_name: str
) -> dict[str, list[_MovieInstance]]:
    instances: dict[str, list[_MovieInstance]] = {}
    for node in _find_movie_nodes(events):
        asset_id = node["movie"].get("asset")
        if not isinstance(asset_id, str) or not asset_id:
            raise _Refuse(f"movie node on slide {slide_name} has no asset id")
        object_id = node.get("objectID")
        rect = _movie_rect(node, slide_name)
        key = _normalize_asset_key(assets_table, asset_id)
        instances.setdefault(key, []).append(
            _MovieInstance(rect, object_id if isinstance(object_id, str) and object_id else None)
        )
    return instances


def _boundary_transition(events: list[Any], slide_name: str) -> dict[str, Any] | None:
    transitions: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("type") == "transition":
                transitions.append(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(events)
    if len(transitions) > 1:
        raise _Refuse(f"slide {slide_name} declares more than one transition effect")
    return transitions[0] if transitions else None


def _resolve_continuation(
    asset: str, outgoing: list[_MovieInstance], incoming: list[_MovieInstance], boundary_desc: str
) -> tuple[MovieContinuity, _MovieInstance]:
    if len(outgoing) == 1 and len(incoming) == 1:
        src, dst = outgoing[0], incoming[0]
        action = "pin" if src.rect.close_to(dst.rect) else "bridge"
        return MovieContinuity(asset, action, src.rect, dst.rect), dst
    pin_pairs = [(o, i) for o in outgoing for i in incoming if o.rect.close_to(i.rect)]
    if len(pin_pairs) == 1:
        src, dst = pin_pairs[0]
        return MovieContinuity(asset, "pin", src.rect, dst.rect), dst
    raise _Refuse(
        f"ambiguous '{asset}' ownership at {boundary_desc}: "
        f"{len(outgoing)} instance(s) before, {len(incoming)} after, "
        f"{len(pin_pairs)} geometry-equal pair(s)"
    )


def derive_plan(
    export_root: Path,
    slides: list[dict[str, Any]],
    *,
    resolver: Callable[[Path, str], Path] = safe_export_file,
) -> ContinuityPlan | Unsupported:
    try:
        header = json.loads(resolver(export_root, "assets/header.json").read_text())
        canvas = {"width": int(header["slideWidth"]), "height": int(header["slideHeight"])}
    except Exception as exc:  # noqa: BLE001 - fail closed on any malformed header
        return Unsupported(f"unreadable export header: {exc}")

    ordered: list[tuple[int, str]] = []
    for slide in slides:
        if slide.get("skipped"):
            continue
        player_index = slide.get("playerIndex")
        uuid = slide.get("exportedUuid")
        if not isinstance(player_index, int) or not isinstance(uuid, str) or not uuid:
            return Unsupported("a non-skipped slide is missing playerIndex or exportedUuid")
        ordered.append((player_index, uuid))
    if not ordered:
        return Unsupported("no playable slides")
    ordered.sort(key=lambda pair: pair[0])

    events_by_player: dict[int, list[Any]] = {}
    instances_by_player: dict[int, dict[str, list[_MovieInstance]]] = {}
    scene_index_by_player: dict[int, int] = {}
    cumulative = 0
    for player_index, uuid in ordered:
        try:
            data = json.loads(resolver(export_root, f"assets/{uuid}/{uuid}.json").read_text())
            events = data["events"]
            assets_table = data["assets"]
        except Exception as exc:  # noqa: BLE001 - fail closed on any malformed slide export
            return Unsupported(f"unreadable slide export for player index {player_index}: {exc}")
        if not isinstance(events, list) or not events:
            return Unsupported(f"slide at player index {player_index} has no events")
        scene_index_by_player[player_index] = cumulative
        cumulative += len(events)
        events_by_player[player_index] = events
        try:
            instances_by_player[player_index] = _slide_movie_instances(events, assets_table, uuid)
        except _Refuse as exc:
            return Unsupported(str(exc))

    slide_rects = {
        player_index: {
            asset: found[0].rect.as_dict() for asset, found in instances.items() if len(found) == 1
        }
        for player_index, instances in instances_by_player.items()
    }

    slide_instances = {
        player_index: {
            asset: [
                instance.rect.as_dict()
                for instance in sorted(found, key=lambda i: (i.rect.x, i.rect.y, i.rect.w, i.rect.h))
            ]
            for asset, found in sorted(instances.items())
        }
        for player_index, instances in instances_by_player.items()
    }

    boundaries: list[SlideBoundary] = []
    for index, (player_index, uuid) in enumerate(ordered):
        try:
            transition = _boundary_transition(events_by_player[player_index], uuid)
        except _Refuse as exc:
            return Unsupported(str(exc))

        transition_name = transition.get("name") if transition else None
        transition_duration = transition.get("duration") if transition else None

        to_player_index = ordered[index + 1][0] if index + 1 < len(ordered) else None
        outgoing = instances_by_player[player_index]
        incoming = instances_by_player.get(to_player_index, {}) if to_player_index is not None else {}
        boundary_desc = f"player index {player_index} -> {to_player_index}"

        if to_player_index is None:
            movies = tuple(
                MovieContinuity(
                    asset, "restart", found[0].rect if len(found) == 1 else None, None
                )
                for asset, found in sorted(outgoing.items())
            )
            boundaries.append(SlideBoundary(player_index, None, movies, transition_duration))
            continue

        if transition_name is not None and transition_name.startswith("apple:magic-move"):
            kind = "magic-move"
        elif transition_name in (None, "apple:dissolve"):
            kind = "restart"
        else:
            return Unsupported(f"unsupported transition '{transition_name}' at {boundary_desc}")

        continuing = sorted(set(outgoing) & set(incoming))
        movies = []
        bridge_count = 0
        for asset in continuing:
            out_found, in_found = outgoing[asset], incoming[asset]
            if kind == "restart":
                src = out_found[0].rect if len(out_found) == 1 else None
                dst = in_found[0].rect if len(in_found) == 1 else None
                movies.append(MovieContinuity(asset, "restart", src, dst))
                continue
            try:
                continuity, dst_instance = _resolve_continuation(
                    asset, out_found, in_found, boundary_desc
                )
                refusal = _overlap_refusal(
                    events_by_player[to_player_index],
                    dst_instance,
                    asset,
                    to_player_index,
                    ordered[index + 1][1],
                )
            except _Refuse as exc:
                return Unsupported(str(exc))
            if refusal is not None:
                continuity = replace(continuity, refusal=refusal)
            movies.append(continuity)
            if continuity.action == "bridge":
                bridge_count += 1
        if bridge_count > 1:
            return Unsupported(f"more than one movie changes geometry at {boundary_desc}")
        boundaries.append(SlideBoundary(player_index, to_player_index, tuple(movies), transition_duration))

    plan = ContinuityPlan(
        canvas=canvas,
        scene_index_by_player=scene_index_by_player,
        slide_rects=slide_rects,
        boundaries=tuple(boundaries),
        slide_instances=slide_instances,
    )
    table = _movie_table(plan)
    movie_keys = {} if isinstance(table, Unsupported) else table[0]
    return replace(
        plan,
        refusals=tuple(
            {
                "fromPlayer": boundary.from_player_index,
                "toPlayer": boundary.to_player_index,
                "atScene": scene_index_by_player.get(boundary.to_player_index),
                "asset": movie.asset,
                "movieKey": movie_keys.get(movie.asset),
                "reason": movie.refusal,
            }
            for boundary in plan.boundaries
            for movie in boundary.movies
            if movie.refusal is not None
        ),
    )


def _resolve_movie_path(
    export_root: Path, uuid: str, asset_id: str, assets_table: dict[str, Any], resolver: Callable[[Path, str], Path]
) -> Path | None:
    entry = assets_table.get(asset_id) or {}
    url = (entry.get("url") or {}).get("web") or (entry.get("url") or {}).get("native")
    if not isinstance(url, str) or not url:
        return None
    try:
        return resolver(export_root, f"assets/{uuid}/{url}")
    except Exception:  # noqa: BLE001 - an unresolvable asset reports as unreadable, not fatal
        return None


def _referenced_movies(
    export_root: Path, slides: list[dict[str, Any]], *, resolver: Callable[[Path, str], Path]
) -> dict[str, list[Path | None]]:
    """Every distinct file each logical asset key resolves to: an HTML export stores a
    separate copy of the same movie under each slide's folder, so one key covers several
    files that need not share a codec."""
    found: dict[str, list[Path | None]] = {}
    for slide in slides:
        if slide.get("skipped"):
            continue
        uuid = slide.get("exportedUuid")
        if not isinstance(uuid, str) or not uuid:
            continue
        try:
            data = json.loads(resolver(export_root, f"assets/{uuid}/{uuid}.json").read_text())
            events = data["events"]
            assets_table = data["assets"]
        except Exception:  # noqa: BLE001 - a report entry is best-effort, never fatal
            continue
        if not isinstance(events, list):
            continue
        for node in _find_movie_nodes(events):
            asset_id = node["movie"].get("asset")
            if not isinstance(asset_id, str) or not asset_id:
                continue
            key = _normalize_asset_key(assets_table, asset_id)
            path = _resolve_movie_path(export_root, uuid, asset_id, assets_table, resolver)
            paths = found.setdefault(key, [])
            if path not in paths:
                paths.append(path)
    return found


def codec_report(
    export_root: Path,
    slides: list[dict[str, Any]],
    *,
    resolver: Callable[[Path, str], Path] = safe_export_file,
    probe: Callable[[Path], str | None] = movie_codec,
) -> list[dict[str, Any]]:
    """Codec of every movie asset any non-skipped slide's events reference, independent
    of whether the deck qualifies for continuity (a rotated or ambiguous movie's codec
    is still worth reporting). Unreadable slides or assets are skipped, never raised:
    this report must stay available even when `derive_plan` refuses.

    Each entry covers all `files` the key resolves to: it reports a codec only when they
    all agree, and otherwise fails closed to an unreadable (`codec: None`, family
    `other`) entry, flagged `mixed` when the disagreement is between readable codecs."""
    assets = _referenced_movies(export_root, slides, resolver=resolver)
    report = []
    for asset, paths in sorted(assets.items()):
        fourccs = {probe(path) if path is not None else None for path in paths}
        mixed = len(fourccs) > 1 and None not in fourccs
        fourcc = fourccs.pop() if len(fourccs) == 1 else None
        entry: dict[str, Any] = {
            "asset": asset, "codec": fourcc, "family": codec_family(fourcc), "files": len(paths),
        }
        if mixed:
            entry["mixed"] = True
        report.append(entry)
    return report

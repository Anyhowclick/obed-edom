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
instead of guessing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from obed_edom.html_preview import safe_export_file

_GEOMETRY_TOLERANCE = 0.5
_TRIM_SUFFIX_RE = re.compile(r"^(?P<name>.+)-\d+\.\d+-\d+\.\d+(?P<ext>\.[A-Za-z0-9]+)$")


class _Refuse(Exception):
    """Internal control-flow only: carries the reason for an `Unsupported` result."""


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "fromPlayerIndex": self.from_player_index,
            "toPlayerIndex": self.to_player_index,
            "movies": [m.as_dict() for m in self.movies],
        }


@dataclass(frozen=True)
class ContinuityPlan:
    canvas: dict[str, int]
    scene_index_by_player: dict[int, int]
    slide_rects: dict[int, dict[str, dict[str, float]]]
    boundaries: tuple[SlideBoundary, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "canvas": dict(self.canvas),
            "sceneIndexByPlayer": {str(k): v for k, v in self.scene_index_by_player.items()},
            "slideRects": {str(k): v for k, v in self.slide_rects.items()},
            "boundaries": [b.as_dict() for b in self.boundaries],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict())


@dataclass(frozen=True)
class Unsupported:
    reason: str


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


def _movie_rect(node: dict[str, Any], slide_name: str) -> Rect:
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
    return Rect(abs_center_x - child_w / 2, abs_center_y - child_h / 2, child_w, child_h)


def _normalize_asset_key(assets_table: dict[str, Any], asset_id: str) -> str:
    entry = assets_table.get(asset_id) or {}
    url = entry.get("url") or {}
    filename = (url.get("web") or url.get("native") or asset_id).rsplit("/", 1)[-1]
    match = _TRIM_SUFFIX_RE.match(filename)
    name = match.group("name") if match else filename
    return name.lower()


def _slide_movie_instances(
    events: list[Any], assets_table: dict[str, Any], slide_name: str
) -> dict[str, list[Rect]]:
    instances: dict[str, list[Rect]] = {}
    for node in _find_movie_nodes(events):
        asset_id = node["movie"].get("asset")
        if not isinstance(asset_id, str) or not asset_id:
            raise _Refuse(f"movie node on slide {slide_name} has no asset id")
        rect = _movie_rect(node, slide_name)
        key = _normalize_asset_key(assets_table, asset_id)
        instances.setdefault(key, []).append(rect)
    return instances


def _boundary_transition_name(events: list[Any], slide_name: str) -> str | None:
    names: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if obj.get("type") == "transition":
                names.append(obj.get("name"))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(events)
    if len(names) > 1:
        raise _Refuse(f"slide {slide_name} declares more than one transition effect")
    return names[0] if names else None


def _resolve_continuation(
    asset: str, out_rects: list[Rect], in_rects: list[Rect], boundary_desc: str
) -> MovieContinuity:
    if len(out_rects) == 1 and len(in_rects) == 1:
        src, dst = out_rects[0], in_rects[0]
        action = "pin" if src.close_to(dst) else "bridge"
        return MovieContinuity(asset, action, src, dst)
    pin_pairs = [(o, i) for o in out_rects for i in in_rects if o.close_to(i)]
    if len(pin_pairs) == 1:
        src, dst = pin_pairs[0]
        return MovieContinuity(asset, "pin", src, dst)
    raise _Refuse(
        f"ambiguous '{asset}' ownership at {boundary_desc}: "
        f"{len(out_rects)} instance(s) before, {len(in_rects)} after, "
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
    instances_by_player: dict[int, dict[str, list[Rect]]] = {}
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
            asset: rects[0].as_dict() for asset, rects in instances.items() if len(rects) == 1
        }
        for player_index, instances in instances_by_player.items()
    }

    boundaries: list[SlideBoundary] = []
    for index, (player_index, uuid) in enumerate(ordered):
        try:
            transition_name = _boundary_transition_name(events_by_player[player_index], uuid)
        except _Refuse as exc:
            return Unsupported(str(exc))

        to_player_index = ordered[index + 1][0] if index + 1 < len(ordered) else None
        outgoing = instances_by_player[player_index]
        incoming = instances_by_player.get(to_player_index, {}) if to_player_index is not None else {}
        boundary_desc = f"player index {player_index} -> {to_player_index}"

        if to_player_index is None:
            movies = tuple(
                MovieContinuity(
                    asset, "restart", rects[0] if len(rects) == 1 else None, None
                )
                for asset, rects in sorted(outgoing.items())
            )
            boundaries.append(SlideBoundary(player_index, None, movies))
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
            out_rects, in_rects = outgoing[asset], incoming[asset]
            if kind == "restart":
                src = out_rects[0] if len(out_rects) == 1 else None
                dst = in_rects[0] if len(in_rects) == 1 else None
                movies.append(MovieContinuity(asset, "restart", src, dst))
                continue
            try:
                continuity = _resolve_continuation(asset, out_rects, in_rects, boundary_desc)
            except _Refuse as exc:
                return Unsupported(str(exc))
            movies.append(continuity)
            if continuity.action == "bridge":
                bridge_count += 1
        if bridge_count > 1:
            return Unsupported(f"more than one movie changes geometry at {boundary_desc}")
        boundaries.append(SlideBoundary(player_index, to_player_index, tuple(movies)))

    return ContinuityPlan(
        canvas=canvas,
        scene_index_by_player=scene_index_by_player,
        slide_rects=slide_rects,
        boundaries=tuple(boundaries),
    )

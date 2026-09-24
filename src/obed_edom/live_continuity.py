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
from obed_edom.live_codec import codec_family, movie_codec, movie_fps

_GEOMETRY_TOLERANCE = 0.5
_OVERLAP_MIN_PX = 1.0
_GL_REPLAY_TRANSITIONS: frozenset[str] = frozenset({"apple:magic-move-implied-motion-path"})
_TRIM_SUFFIX_RE = re.compile(r"^(?P<name>.+)-\d+\.\d+-\d+\.\d+(?P<ext>\.[A-Za-z0-9]+)$")

_MOVIE_SUBTREE_KEYS: dict[str, frozenset[str]] = {
    "<movie node>": frozenset(
        {"attributes", "baseLayer", "beginTime", "duration", "effects", "movie", "name", "objectID", "type"}
    ),
    "movie": frozenset({"asset", "endTime", "isAudioOnly", "isStreaming", "startTime", "volume"}),
    "attributes": frozenset({"direction"}),
    "baseLayer": frozenset({"animations", "initialState", "layers", "objectID"}),
    "layers": frozenset(
        {"animations", "initialState", "isVideoLayer", "layers", "texture", "texturedRectangle"}
    ),
    "initialState": frozenset(
        {
            "affineTransform", "anchorPoint", "contentsRect", "edgeAntialiasingMask", "height", "hidden",
            "masksToBounds", "opacity", "position", "rotation", "scale", "sublayerTransform", "width",
        }
    ),
    "position": frozenset({"pointX", "pointY"}),
    "anchorPoint": frozenset({"pointX", "pointY"}),
    "contentsRect": frozenset({"x", "y", "width", "height"}),
    "texturedRectangle": frozenset(
        {
            "isBackgroundTexture", "isVerticalText", "singleTextureOpacity", "textBaseline",
            "textXHeight", "textureType",
        }
    ),
}
"""Every object that occurs anywhere under a movie node of the qualified export, keyed by the
key that holds it, with the complete set of keys measured for it. Keys holding no object at all
(`effects` and `animations` are always empty lists, `texture` is a string, the transforms are
flat number lists) are deliberately absent: an object appearing under one is unmeasured, and an
unmeasured object may be the mask this module cannot map."""

_MASKING_NAME_FRAGMENTS = ("mask", "clip", "shapepath")
_BENIGN_MASK_KEYS = frozenset({"masksToBounds", "edgeAntialiasingMask"})

_EFFECT_FILL_MODES: frozenset[str] = frozenset({"both", "forwards"})
_EFFECT_TIMING_FUNCTIONS: frozenset[str] = frozenset({"EaseInEaseOut"})
_EFFECT_TYPES: frozenset[str] = frozenset({"transition", "buildIn"})
_EFFECT_PROPERTIES: frozenset[str] = frozenset(
    {"contents", "hidden", "opacity", "transform.scale.x", "transform.scale.y",
     "transform.translation", "zPosition"}
)
_EFFECT_LEAF_ONLY_PROPERTIES: frozenset[str] = frozenset(
    {"transform.scale.x", "transform.scale.y", "transform.translation"}
)


def _math_isfinite(value: Any) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _v_finite_number(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not _math_isfinite(value):
        raise _Refuse(f"{path} is not a readable finite number")


def _v_finite_int(value: Any, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not _math_isfinite(value):
        raise _Refuse(f"{path} is not a readable integer")


def _v_bool(value: Any, path: str) -> None:
    if not isinstance(value, bool):
        raise _Refuse(f"{path} is not a readable boolean")


def _v_bool_equals(expected: bool) -> Callable[[Any, str], None]:
    def validator(value: Any, path: str) -> None:
        if not isinstance(value, bool) or value is not expected:
            raise _Refuse(f"{path} is not the measured neutral value {expected!r}")

    return validator


def _v_number_equals(expected: float) -> Callable[[Any, str], None]:
    def validator(value: Any, path: str) -> None:
        _v_finite_number(value, path)
        if value != expected:
            raise _Refuse(f"{path} is not the measured neutral value {expected!r}")

    return validator


def _v_number_range(low: float, high: float) -> Callable[[Any, str], None]:
    def validator(value: Any, path: str) -> None:
        _v_finite_number(value, path)
        if not low <= value <= high:
            raise _Refuse(f"{path} is outside the measured range [{low}, {high}]")

    return validator


def _v_nonneg_number(value: Any, path: str) -> None:
    _v_finite_number(value, path)
    if value < 0:
        raise _Refuse(f"{path} is negative")


def _v_nonempty_str(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        raise _Refuse(f"{path} is not a readable non-empty string")


def _v_one_of(values: frozenset[str]) -> Callable[[Any, str], None]:
    def validator(value: Any, path: str) -> None:
        if not isinstance(value, str) or value not in values:
            raise _Refuse(f"{path} is not one of the measured values {sorted(values)}")

    return validator


def _v_list_of(
    item_validator: Callable[[Any, str], None], length: int | None = None, min_length: int | None = None
) -> Callable[[Any, str], None]:
    def validator(value: Any, path: str) -> None:
        if not isinstance(value, list):
            raise _Refuse(f"{path} is not a readable list")
        if length is not None and len(value) != length:
            raise _Refuse(f"{path} is not a readable list of length {length}")
        if min_length is not None and len(value) < min_length:
            raise _Refuse(f"{path} is not a readable list of at least {min_length} items")
        for index, item in enumerate(value):
            item_validator(item, f"{path}[{index}]")

    return validator


def _v_empty_list(value: Any, path: str) -> None:
    if not isinstance(value, list) or value:
        raise _Refuse(f"{path} must be measured as always empty")


def _v_dict_exact(
    required: dict[str, Callable[[Any, str], None]], optional: dict[str, Callable[[Any, str], None]] | None = None
) -> Callable[[Any, str], None]:
    allowed = {**required, **(optional or {})}

    def validator(value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise _Refuse(f"{path} is not a readable object")
        extra = set(value) - set(allowed)
        if extra:
            raise _Refuse(f"{path} carries unmeasured keys {sorted(extra)}")
        missing = set(required) - set(value)
        if missing:
            raise _Refuse(f"{path} is missing measured keys {sorted(missing)}")
        for key, sub_validator in allowed.items():
            if key in value:
                sub_validator(value[key], f"{path}.{key}")

    return validator


_v_point = _v_dict_exact({"pointX": _v_finite_number, "pointY": _v_finite_number})
_v_pinned_unit_rect = _v_dict_exact(
    {"x": _v_number_equals(0), "y": _v_number_equals(0), "width": _v_number_equals(1), "height": _v_number_equals(1)}
)
_v_value_scalar_number = _v_dict_exact({"scalar": _v_finite_number})
_v_value_scalar_bool = _v_dict_exact({"scalar": _v_bool})
_v_value_scalar_zposition = _v_dict_exact({"scalar": _v_number_range(-1.0, 1.0)})
_v_value_texture = _v_dict_exact({"texture": _v_nonempty_str})

_EFFECT_PROPERTY_ENDPOINT_SCHEMAS: dict[str, Callable[[Any, str], None]] = {
    "contents": _v_value_texture,
    "hidden": _v_value_scalar_bool,
    "opacity": _v_value_scalar_number,
    "transform.scale.x": _v_value_scalar_number,
    "transform.scale.y": _v_value_scalar_number,
    "transform.translation": _v_point,
    "zPosition": _v_value_scalar_zposition,
}
"""Every measured animation `property`'s exact endpoint schema, keyed by the property
(`m3b_anim.log`). `zPosition` is additionally bounded to `|scalar| <= 1.0` (measured <= 0.004):
combined with `sublayerTransform[11]`'s measured range, the worst-case perspective factor stays
within the plan's 1px rect contract on a 1920px layer."""


def _v_animation_leaf(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise _Refuse(f"{path} is not a readable animation")
    property_ = value.get("property")
    if not isinstance(property_, str) or property_ not in _EFFECT_PROPERTY_ENDPOINT_SCHEMAS:
        raise _Refuse(f"{path}.property is not a measured property")
    endpoint = _EFFECT_PROPERTY_ENDPOINT_SCHEMAS[property_]
    required = {
        "additive": _v_bool_equals(False),
        "autoreverses": _v_bool_equals(False),
        "beginTime": _v_nonneg_number,
        "duration": _v_nonneg_number,
        "fillMode": _v_one_of(_EFFECT_FILL_MODES),
        "from": endpoint,
        "property": _v_one_of(_EFFECT_PROPERTIES),
        "removedOnCompletion": _v_bool_equals(True),
        "repeatCount": _v_number_equals(0),
        "timeOffset": _v_number_equals(0),
        "to": endpoint,
    }
    optional = {"timingFunction": _v_one_of(_EFFECT_TIMING_FUNCTIONS)}
    _v_dict_exact(required, optional)(value, path)


def _v_animation_group(value: Any, path: str) -> None:
    required = {
        "additive": _v_bool_equals(False),
        "animations": _v_list_of(_v_animation_leaf),
        "autoreverses": _v_bool_equals(False),
        "beginTime": _v_nonneg_number,
        "duration": _v_nonneg_number,
        "fillMode": _v_one_of(_EFFECT_FILL_MODES),
        "removedOnCompletion": _v_bool_equals(False),
        "repeatCount": _v_number_equals(0),
        "timeOffset": _v_number_equals(0),
    }
    _v_dict_exact(required)(value, path)


_v_point_pair = _v_list_of(_v_finite_number, length=2)
_EFFECT_SHAPE_ELEMENT_SCHEMAS: dict[str, Callable[[Any, str], None]] = {
    "MoveToPoint": _v_dict_exact({"type": _v_one_of(frozenset({"MoveToPoint"})), "points": _v_list_of(_v_point_pair, length=1)}),
    "AddLine": _v_dict_exact({"type": _v_one_of(frozenset({"AddLine"})), "points": _v_list_of(_v_point_pair, length=1)}),
    "CloseSubpath": _v_dict_exact({"type": _v_one_of(frozenset({"CloseSubpath"}))}),
}


def _v_shape_element(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise _Refuse(f"{path} is not a readable shape-path element")
    kind = value.get("type")
    if not isinstance(kind, str) or kind not in _EFFECT_SHAPE_ELEMENT_SCHEMAS:
        raise _Refuse(f"{path}.type is not a measured shape-path element type")
    _EFFECT_SHAPE_ELEMENT_SCHEMAS[kind](value, path)


_v_shape_path = _v_dict_exact(
    {
        "elements": _v_list_of(_v_shape_element),
        "flatness": _v_finite_number,
        "lineCapStyle": _v_finite_int,
        "lineJoinStyle": _v_finite_int,
        "lineWidth": _v_finite_number,
        "miterLimit": _v_finite_number,
        "windingRule": _v_finite_int,
    }
)

_v_textured_rectangle = _v_dict_exact(
    {
        "isBackgroundTexture": _v_bool,
        "isVerticalText": _v_bool,
        "singleTextureOpacity": _v_finite_number,
        "textBaseline": _v_finite_int,
        "textXHeight": _v_finite_int,
        "textureType": _v_finite_int,
    },
    {"shapePath": _v_shape_path},
)

_v_initial_state = _v_dict_exact(
    {
        "affineTransform": _v_list_of(_v_finite_number, length=6),
        "anchorPoint": _v_point,
        "contentsRect": _v_pinned_unit_rect,
        "edgeAntialiasingMask": _v_finite_int,
        "height": _v_finite_number,
        "hidden": _v_bool_equals(False),
        "masksToBounds": _v_bool_equals(False),
        "opacity": _v_finite_number,
        "position": _v_point,
        "rotation": _v_finite_number,
        "scale": _v_finite_number,
        "sublayerTransform": _v_list_of(_v_finite_number, length=16),
        "width": _v_finite_number,
    }
)


def _v_layer_node(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise _Refuse(f"{path} is not a readable object")
    if value.get("layers") == []:
        _v_leaf_node(value, path)
    else:
        _v_wrapper_node(value, path)


_v_leaf_node = _v_dict_exact(
    {
        "animations": _v_list_of(_v_animation_group),
        "initialState": _v_initial_state,
        "layers": _v_empty_list,
        "texture": _v_nonempty_str,
        "texturedRectangle": _v_textured_rectangle,
    }
)
_v_wrapper_node = _v_dict_exact(
    {
        "animations": _v_list_of(_v_animation_group),
        "initialState": _v_initial_state,
        "layers": _v_list_of(_v_layer_node, min_length=1),
    }
)
"""A layer node is discriminated by its own `layers`: an empty list is a terminal, textured leaf
(`texture` + `texturedRectangle` mandatory, neither ever present on a wrapper); anything else is
a non-textured wrapper with at least one child. Top-level slots (`_v_base_layer` below) are
wrappers specifically, never a bare leaf -- every measured slot is a multi-node chain."""

_v_base_layer = _v_dict_exact(
    {
        "animations": _v_empty_list,
        "initialState": _v_initial_state,
        "layers": _v_list_of(_v_wrapper_node),
        "objectID": _v_nonempty_str,
    }
)

_v_transition_effect = _v_dict_exact(
    {
        "attributes": _v_dict_exact({"direction": _v_finite_int}),
        "baseLayer": _v_base_layer,
        "beginTime": _v_nonneg_number,
        "duration": _v_nonneg_number,
        "effects": _v_empty_list,
        "name": _v_nonempty_str,
        "objectID": _v_nonempty_str,
        "type": _v_one_of(_EFFECT_TYPES),
    }
)
"""The recursive schema for a `glReplay` boundary's transition-effect tree (plan section 0,
F-8): every container and primitive reachable from here has an explicit `_v_*` validator, so no
value reaches the arithmetic below unvalidated."""


def _check_effect_encoding(effect: dict[str, Any]) -> None:
    _v_transition_effect(effect, "<transition effect>")


def _effect_leaves(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [leaf for group in node.get("animations") or [] for leaf in group.get("animations") or []]


def _effect_chain(slot: Any, index: int) -> list[dict[str, Any]]:
    """The single-child descent from a top-level slot wrapper to its textured leaf (plan section
    0, `m4_settled.py`): every measured slot is exactly one chain, never a branch."""
    if not isinstance(slot, dict):
        raise _Refuse(f"slot {index} is not a readable object")
    chain = [slot]
    node = slot
    while True:
        kids = node.get("layers")
        if not kids:
            break
        if not isinstance(kids, list) or len(kids) != 1 or not isinstance(kids[0], dict):
            raise _Refuse(f"slot {index} has a branching or unreadable layer chain")
        node = kids[0]
        chain.append(node)
    return chain


_IDENTITY_SUBLAYER_TRANSFORM = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
_EFFECT_SUBLAYER_PERSPECTIVE_INDEX = 11
_EFFECT_SUBLAYER_PERSPECTIVE_RANGE = (-5e-4, 0.0)
_EFFECT_RECT_PIXEL_TOLERANCE = 1.0


def _check_effect_node_geometry(state: dict[str, Any], where: str) -> None:
    """The invariants the settled-leaf-rect formula relies on: no rotation, a unit
    `initialState.scale`, an identity `affineTransform`, positive `width`/`height`, and an
    identity `sublayerTransform` except index 11 (the measured perspective term), bounded to
    `[-5e-4, 0]`. Pixel-error accumulation across the chain is checked separately."""
    rotation = _number(state, "rotation", where=where, slide_name="<effect>")
    if rotation != 0.0:
        raise _Refuse(f"{where} is rotated ({rotation}), outside the measured geometry")
    scale = _number(state, "scale", where=where, slide_name="<effect>")
    if scale != 1.0:
        raise _Refuse(f"{where} has a non-unit initialState.scale ({scale})")
    affine = state["affineTransform"]
    if [float(v) for v in affine] != _IDENTITY_AFFINE:
        raise _Refuse(f"{where} has a non-identity affineTransform")
    if state["width"] <= 0 or state["height"] <= 0:
        raise _Refuse(f"{where} has a non-positive width or height")
    sublayer = state["sublayerTransform"]
    for i, (value, identity) in enumerate(zip(sublayer, _IDENTITY_SUBLAYER_TRANSFORM)):
        v = float(value)
        if i == _EFFECT_SUBLAYER_PERSPECTIVE_INDEX:
            low, high = _EFFECT_SUBLAYER_PERSPECTIVE_RANGE
            if not low <= v <= high:
                raise _Refuse(f"{where} has sublayerTransform[11] outside the measured range")
        elif v != identity:
            raise _Refuse(f"{where} has a non-identity sublayerTransform")


def _root_position_residual_px(root_state: dict[str, Any]) -> tuple[float, float]:
    where = "effect baseLayer"
    position_x = _number(root_state, "position", "pointX", where=where, slide_name="<effect>")
    position_y = _number(root_state, "position", "pointY", where=where, slide_name="<effect>")
    anchor_x = _number(root_state, "anchorPoint", "pointX", where=where, slide_name="<effect>")
    anchor_y = _number(root_state, "anchorPoint", "pointY", where=where, slide_name="<effect>")
    width = _number(root_state, "width", where=where, slide_name="<effect>")
    height = _number(root_state, "height", where=where, slide_name="<effect>")
    return abs(position_x - anchor_x * width), abs(position_y - anchor_y * height)


def _effect_anchor_error_px(state: dict[str, Any], where: str) -> tuple[float, float]:
    anchor_x = _number(state, "anchorPoint", "pointX", where=where, slide_name="<effect>")
    anchor_y = _number(state, "anchorPoint", "pointY", where=where, slide_name="<effect>")
    width = _number(state, "width", where=where, slide_name="<effect>")
    height = _number(state, "height", where=where, slide_name="<effect>")
    return abs(anchor_x - 0.5) * width, abs(anchor_y - 0.5) * height


def _child_center_residual_px(child_state: dict[str, Any], parent_state: dict[str, Any], where: str) -> tuple[float, float]:
    parent_width = _number(parent_state, "width", where=where, slide_name="<effect>")
    parent_height = _number(parent_state, "height", where=where, slide_name="<effect>")
    child_x = _number(child_state, "position", "pointX", where=where, slide_name="<effect>")
    child_y = _number(child_state, "position", "pointY", where=where, slide_name="<effect>")
    return abs(child_x - parent_width / 2), abs(child_y - parent_height / 2)


def effect_opacity_overrides(effect: dict[str, Any]) -> dict[str, Any] | Unsupported:
    """Settled per-slot opacity overrides for a `glReplay` boundary's transition effect (plan
    section 2): `_check_effect_encoding` closes the vocabulary; geometry, opacity-settlement, and
    exclusion rules are applied per slot in `_effect_opacity_overrides`. Any exception this
    module's own validators did not anticipate is converted to `Unsupported` here, as a
    fail-closed net behind them."""
    try:
        return _effect_opacity_overrides(effect)
    except _Refuse as exc:
        return Unsupported(str(exc))
    except Exception as exc:
        return Unsupported(f"unexpected malformed input: {exc!r}")


def _effect_opacity_overrides(effect: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(effect, dict):
        raise _Refuse("effect is not a readable object")
    _check_effect_encoding(effect)
    base_layer = effect["baseLayer"]
    root_state = base_layer["initialState"]
    _check_effect_node_geometry(root_state, "effect baseLayer")
    root_residual_x, root_residual_y = _root_position_residual_px(root_state)
    slots = base_layer["layers"]
    if not slots:
        raise _Refuse("effect declares no readable top-level slots")

    computed: list[dict[str, Any]] = []
    for index, slot in enumerate(slots):
        chain = _effect_chain(slot, index)
        product = 1.0
        fade = False
        hidden = False
        node_settled: list[dict[str, dict[str, Any]]] = []
        anchor_errors: list[tuple[float, float]] = []
        pixel_error_x = root_residual_x
        pixel_error_y = root_residual_y
        for depth, node in enumerate(chain):
            state = node["initialState"]
            where = f"slot {index}"
            _check_effect_node_geometry(state, where)
            anchor_errors.append(_effect_anchor_error_px(state, where))
            if depth > 0:
                child_error_x, child_error_y = _child_center_residual_px(
                    state, chain[depth - 1]["initialState"], where
                )
                pixel_error_x += child_error_x
                pixel_error_y += child_error_y

            is_leaf = depth == len(chain) - 1
            settled: dict[str, dict[str, Any]] = {}
            for anim in _effect_leaves(node):
                property_ = anim["property"]
                if not is_leaf and property_ in _EFFECT_LEAF_ONLY_PROPERTIES:
                    raise _Refuse(f"{where} has a {property_!r} animation on a non-leaf node")
                if property_ == "opacity":
                    to_value = anim["to"]["scalar"]
                    from_value = anim["from"]["scalar"]
                    if from_value != to_value:
                        fade = True
                    if "opacity" in settled:
                        raise _Refuse(f"{where} has more than one settled opacity animation")
                elif property_ == "hidden":
                    hidden = True
                settled[property_] = anim
            node_settled.append(settled)

            if "opacity" in settled:
                product *= settled["opacity"]["to"]["scalar"]
            elif "opacity" in state:
                product *= state["opacity"]
            else:
                raise _Refuse(
                    f"{where} has no settled opacity animation and no readable initialState.opacity"
                )

        wrapper_state = chain[0]["initialState"]
        leaf_state = chain[-1]["initialState"]
        leaf_settled = node_settled[-1]
        leaf = chain[-1]

        width = leaf_state["width"]
        height = leaf_state["height"]
        scale_x = (
            leaf_settled["transform.scale.x"]["to"]["scalar"] if "transform.scale.x" in leaf_settled else 1.0
        )
        scale_y = (
            leaf_settled["transform.scale.y"]["to"]["scalar"] if "transform.scale.y" in leaf_settled else 1.0
        )
        if scale_x <= 0 or scale_y <= 0:
            raise _Refuse(f"slot {index} has a non-positive settled leaf scale")
        if "transform.translation" in leaf_settled:
            translation = leaf_settled["transform.translation"]["to"]
            tx, ty = translation["pointX"], translation["pointY"]
        else:
            tx, ty = 0.0, 0.0
        wrapper_x = wrapper_state["position"]["pointX"]
        wrapper_y = wrapper_state["position"]["pointY"]

        leaf_tr = leaf.get("texturedRectangle")
        if not isinstance(leaf_tr, dict):
            raise _Refuse(f"slot {index} leaf has no readable texturedRectangle")
        sto = leaf_tr["singleTextureOpacity"]

        non_leaf_error_x = sum(err[0] for err in anchor_errors[:-1])
        non_leaf_error_y = sum(err[1] for err in anchor_errors[:-1])
        leaf_error_x, leaf_error_y = anchor_errors[-1]
        pixel_error_x += non_leaf_error_x + leaf_error_x * scale_x
        pixel_error_y += non_leaf_error_y + leaf_error_y * scale_y
        if pixel_error_x > _EFFECT_RECT_PIXEL_TOLERANCE or pixel_error_y > _EFFECT_RECT_PIXEL_TOLERANCE:
            raise _Refuse(
                f"slot {index} accumulated geometry error exceeds the 1px rect contract"
            )

        rect_w = width * scale_x
        rect_h = height * scale_y
        if rect_w <= 0 or rect_h <= 0:
            raise _Refuse(f"slot {index} has a non-positive emitted rect dimension")
        center_x = wrapper_x + tx
        center_y = wrapper_y + ty
        rect = [center_x - rect_w / 2, center_y - rect_h / 2, rect_w, rect_h]
        if not all(math.isfinite(v) for v in rect):
            raise _Refuse(f"slot {index} has a non-finite emitted rect {rect}")

        computed.append(
            {
                "index": index, "width": width, "height": height, "rect": rect,
                "product": product, "sto": sto, "fade": fade, "hidden": hidden,
            }
        )

    excluded: list[dict[str, Any]] = []
    candidates: dict[int, dict[str, Any]] = {}
    for c in computed:
        index = c["index"]
        if c["fade"]:
            excluded.append({"slot": index, "reason": "fade"})
            continue
        if c["hidden"]:
            excluded.append({"slot": index, "reason": "hidden"})
            continue
        if not math.isclose(c["product"], c["sto"], rel_tol=0, abs_tol=1e-6):
            excluded.append({"slot": index, "reason": "product-mismatch"})
            continue
        if c["sto"] < 1 - 1e-6:
            candidates[index] = c

    overrides: list[dict[str, Any]] = []
    for index, c in candidates.items():
        size = (c["width"], c["height"])
        if any((o["width"], o["height"]) == size for o in computed if o["index"] != index):
            excluded.append({"slot": index, "reason": "duplicate-size"})
            continue
        overrides.append({"slot": index, "opacity": c["sto"], "texW": c["width"], "texH": c["height"]})

    excluded.sort(key=lambda e: e["slot"])
    overrides.sort(key=lambda o: o["slot"])
    return {
        "slotSizes": [[c["width"], c["height"]] for c in computed],
        "slotRects": [c["rect"] for c in computed],
        "opacityOverrides": overrides,
        "excluded": excluded,
    }




class _Refuse(Exception):
    """Internal control-flow only: carries the reason for an `Unsupported` result."""


QUALIFIED_PLAN_SHA256: frozenset[str] = frozenset(
    {
        "bafe26cad55cf3a390154bce2c0fdcc771b9b1821293b6aec76119d25180e81e",
        "6a0596da54532493aee74d22fe91b7cbf3628795aca586dd3cf7dc61a37cc635",
    }
)


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
    gl_replay: dict[str, Any] | None = None
    """The full `effect_opacity_overrides` result when this refused pin qualified for `glReplay`
    derivation (arming plan section 11), else `None`."""
    gl_replay_reason: str | None = None
    """Why `gl_replay` derivation was not attempted or did not qualify, else `None`."""
    gl_replay_slot: int | None = None
    """The carried instance's index in the source slide's draw order, captured while that
    slide's events are in hand; the runtime entry's `movieSlot`. Flag-on only."""

    def as_dict(self) -> dict[str, Any]:
        result = {
            "asset": self.asset,
            "action": self.action,
            "srcRect": self.src_rect.as_dict() if self.src_rect else None,
            "dstRect": self.dst_rect.as_dict() if self.dst_rect else None,
        }
        if self.gl_replay is not None or self.gl_replay_reason is not None:
            result["glReplay"] = self.gl_replay is not None
            result["glReplayReason"] = self.gl_replay_reason
        return result


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
        `retire` -- at most one, and only before the first restart and any bridge -- unless the
        movie qualified for `glReplay` derivation, in which case it becomes a `glReplay` boundary
        under the same guards.
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
                if movie.gl_replay is not None:
                    gl = movie.gl_replay
                    slot_sizes = gl.get("slotSizes")
                    slot_rects = gl.get("slotRects")
                    overrides = gl.get("opacityOverrides")
                    if (
                        not isinstance(overrides, list)
                        or not isinstance(slot_sizes, list)
                        or not isinstance(slot_rects, list)
                        or len(slot_sizes) != len(slot_rects)
                    ):
                        return Unsupported("glReplay boundary carries an unreadable override table")
                    slot = movie.gl_replay_slot
                    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < len(slot_sizes):
                        return Unsupported("glReplay boundary has no readable movie slot index")
                    asset = movies[key]["assetKeys"][0]
                    bound = _destination_instance(
                        self.slide_instances.get(boundary.to_player_index, {}).get(asset),
                        movie.dst_rect,
                    )
                    if bound is None:
                        return Unsupported(
                            f"glReplay boundary's destination instance of '{asset}' is not in slide_instances"
                        )
                    instance_index, instance_rect = bound
                    runtime_boundaries.append(
                        {
                            "atScene": scene, "action": "glReplay", "movieKey": key, "fallback": "retire",
                            "slotSizes": slot_sizes, "slotRects": slot_rects, "opacityOverrides": overrides,
                            "instanceId": f"{asset}#{instance_index}",
                            "instanceRect": instance_rect,
                            "movieSlot": slot,
                        }
                    )
                else:
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


def _destination_instance(
    instances: list[dict[str, float]] | None, dst_rect: "Rect | None"
) -> tuple[int, dict[str, float]] | None:
    """The 1-based position of `dst_rect` in the asset's `slide_instances` list -- the same
    list, in the same order and with the same floats, the probe binds `asset#index` and its rect
    to -- plus that stored rect verbatim. `None` when the rect is absent, not four finite floats,
    or matched by other than exactly one instance (two byte-identical rects would make
    `asset#index` a guess)."""
    if not instances or dst_rect is None:
        return None
    wanted = dst_rect.as_dict()
    matches = [
        (index, rect)
        for index, rect in enumerate(instances, start=1)
        if isinstance(rect, dict) and rect == wanted
    ]
    if len(matches) != 1:
        return None
    index, rect = matches[0]
    values = [rect.get(k) for k in ("x", "y", "w", "h")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        return None
    return index, {k: rect[k] for k in ("x", "y", "w", "h")}


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


_IDENTITY_AFFINE = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def _identity_transform(state: dict[str, Any], where: str, slide_name: str) -> bool:
    """Whether the layer is drawn untransformed. `scale` counts: it is part of the same claim,
    and every measured movie layer carries 1."""
    for name, neutral in (("rotation", 0.0), ("scale", 1.0)):
        if name in state and _number(state, name, where=where, slide_name=slide_name) != neutral:
            return False
    if "affineTransform" not in state:
        return True
    transform = state["affineTransform"]
    if not isinstance(transform, list) or len(transform) != len(_IDENTITY_AFFINE):
        raise _Refuse(f"{where} on slide {slide_name} has an unreadable affineTransform")
    return [_finite(v, "affineTransform", where, slide_name) for v in transform] == _IDENTITY_AFFINE


def _center_anchor(state: dict[str, Any], where: str, slide_name: str) -> bool:
    if "anchorPoint" not in state:
        return True
    anchor = state["anchorPoint"]
    if not isinstance(anchor, dict):
        raise _Refuse(f"{where} on slide {slide_name} has an unreadable anchorPoint")
    return (
        abs(_number(anchor, "pointX", where=where, slide_name=slide_name) - 0.5) < 1e-6
        and abs(_number(anchor, "pointY", where=where, slide_name=slide_name) - 0.5) < 1e-6
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


_UNIT_CONTENTS_RECT = (("x", 0.0), ("y", 0.0), ("width", 1.0), ("height", 1.0))


def _check_clipping(state: dict[str, Any], path: str, slide_name: str) -> None:
    if "masksToBounds" in state and state["masksToBounds"] is not False:
        raise _encoding_refusal(slide_name, f"{path}.masksToBounds")
    if "contentsRect" not in state:
        return
    contents = state["contentsRect"]
    if not isinstance(contents, dict) or set(contents) != {name for name, _ in _UNIT_CONTENTS_RECT}:
        raise _encoding_refusal(slide_name, f"{path}.contentsRect")
    for name, unit in _UNIT_CONTENTS_RECT:
        value = contents[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or abs(value - unit) > 1e-6
        ):
            raise _encoding_refusal(slide_name, f"{path}.contentsRect.{name}")


def _check_movie_encoding(node: dict[str, Any], slide_name: str) -> None:
    """Interim mask rule: this export family encodes no mask at all, so the whole movie subtree
    is checked against the measured vocabulary -- an object where none was ever measured, a key
    outside its object's set, a name that reads like clipping, or a clipping knob off its neutral
    value may all BE the mask, and each fails closed until a masked deck is exported."""
    _walk_movie_subtree(node, "<movie node>", "<movie node>", slide_name)


def _walk_movie_subtree(value: Any, kind: str, path: str, slide_name: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_movie_subtree(item, kind, f"{path}[{index}]", slide_name)
        return
    if not isinstance(value, dict):
        return
    allowed = _MOVIE_SUBTREE_KEYS.get(kind)
    if allowed is None:
        raise _encoding_refusal(slide_name, path)
    for key, child in value.items():
        child_path = f"{path}.{key}"
        lowered = key.lower()
        if key not in _BENIGN_MASK_KEYS and any(f in lowered for f in _MASKING_NAME_FRAGMENTS):
            raise _encoding_refusal(slide_name, child_path)
        if key not in allowed:
            raise _encoding_refusal(slide_name, child_path)
        _walk_movie_subtree(child, key, child_path, slide_name)
    if kind == "initialState":
        _check_clipping(value, path, slide_name)


def _object_state(layer: Any, where: str, slide_name: str) -> dict[str, Any]:
    state = layer.get("initialState") if isinstance(layer, dict) else None
    if not isinstance(state, dict):
        raise _Refuse(f"{where} on slide {slide_name} has no readable initialState")
    return state


def _finite(value: Any, name: str, where: str, slide_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _Refuse(f"{where} on slide {slide_name} has a non-numeric '{name}'")
    return float(value)


def _number(state: dict[str, Any], *keys: str, where: str, slide_name: str) -> float:
    value: Any = state
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise _Refuse(f"{where} on slide {slide_name} is missing '{key}'")
        value = value[key]
    return _finite(value, keys[-1], where, slide_name)


def _state_rect(state: dict[str, Any], where: str, slide_name: str) -> Rect:
    """The authored rect of one object: centre-anchored position with its own width/height."""
    width = _number(state, "width", where=where, slide_name=slide_name)
    height = _number(state, "height", where=where, slide_name=slide_name)
    center_x = _number(state, "position", "pointX", where=where, slide_name=slide_name)
    center_y = _number(state, "position", "pointY", where=where, slide_name=slide_name)
    return Rect(center_x - width / 2, center_y - height / 2, width, height)


def _movie_rect(node: dict[str, Any], slide_name: str) -> Rect:
    _check_movie_encoding(node, slide_name)
    base_layer = node["baseLayer"]
    parent_state = _object_state(base_layer, "movie layer", slide_name)
    if not _identity_transform(parent_state, "movie layer", slide_name) or not _center_anchor(
        parent_state, "movie layer", slide_name
    ):
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
    video_state = _object_state(video_layer, "video sub-layer", slide_name)
    if not _identity_transform(video_state, "video sub-layer", slide_name) or not _center_anchor(
        video_state, "video sub-layer", slide_name
    ):
        raise _Refuse(
            f"video sub-layer on slide {slide_name} has a rotated, transformed, or off-center anchor"
        )
    if base_layer.get("animations") or video_layer.get("animations"):
        raise _Refuse(f"movie layer on slide {slide_name} has animated geometry")

    base_rect = _state_rect(parent_state, "movie layer", slide_name)
    relative = _state_rect(video_state, "video sub-layer", slide_name)
    rect = Rect(base_rect.x + relative.x, base_rect.y + relative.y, relative.w, relative.h)
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
            where = f"draw slot {index}"
            children = slots[index]["layers"]
            if len(children) != 1 or not isinstance(children[0], dict):
                raise _Refuse(
                    f"unrecognised slide layer shape on slide {slide_name} ({where})"
                )
            state = _object_state(children[0], where, slide_name)
            if _overlaps(_state_rect(state, where, slide_name), instance.rect):
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
) -> tuple[MovieContinuity, _MovieInstance, _MovieInstance]:
    if len(outgoing) == 1 and len(incoming) == 1:
        src, dst = outgoing[0], incoming[0]
        action = "pin" if src.rect.close_to(dst.rect) else "bridge"
        return MovieContinuity(asset, action, src.rect, dst.rect), src, dst
    pin_pairs = [(o, i) for o in outgoing for i in incoming if o.rect.close_to(i.rect)]
    if len(pin_pairs) == 1:
        src, dst = pin_pairs[0]
        return MovieContinuity(asset, "pin", src.rect, dst.rect), src, dst
    raise _Refuse(
        f"ambiguous '{asset}' ownership at {boundary_desc}: "
        f"{len(outgoing)} instance(s) before, {len(incoming)} after, "
        f"{len(pin_pairs)} geometry-equal pair(s)"
    )


def _gl_replay_attempt(
    movie: MovieContinuity,
    transition: dict[str, Any] | None,
    transition_name: str | None,
    continuing_count: int,
    src_events: list[Any],
    src_instance: "_MovieInstance",
    src_slide_name: str,
    dst_events: list[Any],
) -> MovieContinuity:
    """Rules 1-5 of arming plan section 11, applied to a `pin` that received an overlap refusal.
    The first failing rule is the recorded reason; success attaches the full
    `effect_opacity_overrides` result."""
    if transition_name not in _GL_REPLAY_TRANSITIONS:
        reason = f"transition '{transition_name}' is not in the measured WebGL list"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    if continuing_count != 1:
        reason = f"{continuing_count} movies are carried across the boundary, expected exactly 1"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    if movie.action != "pin":
        reason = "carried movie changes geometry across the boundary"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    first_event = dst_events[0] if dst_events else {}
    automatic_play = first_event.get("automaticPlay") if isinstance(first_event, dict) else None
    if automatic_play is not False:
        reason = f"destination first event is not click-driven (automaticPlay={automatic_play!r})"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    result = effect_opacity_overrides(transition)
    if isinstance(result, Unsupported):
        reason = f"transition effect: {result.reason}"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    try:
        slot = _drawn_slot_index(src_events, src_instance, src_slide_name, len(result["slotSizes"]))
    except _Refuse as exc:
        return replace(movie, gl_replay=None, gl_replay_reason=str(exc))
    if slot is None:
        reason = "carried movie has no draw slot on the source slide"
        return replace(movie, gl_replay=None, gl_replay_reason=reason)
    return replace(movie, gl_replay=result, gl_replay_reason=None, gl_replay_slot=slot)


def _drawn_slot_index(
    events: list[Any], instance: "_MovieInstance", slide_name: str, slot_count: int
) -> int | None:
    """The instance's slot in the source slide's draw order, which `slotSizes`/`slotRects` index
    positionally. The transition effect's own layers carry no `objectID`, so the index cannot be
    read from there; instead every source event that draws the movie must agree on it, and its
    draw order must be as long as the transition's, otherwise the index would address a different
    array and the boundary is refused."""
    if instance.object_id is None:
        return None
    found: int | None = None
    for event in events:
        slots = _draw_slots(event, slide_name)
        index = _movie_slot_index(slots, instance.object_id, slide_name)
        if index is None:
            continue
        if len(slots) != slot_count:
            raise _Refuse(
                f"slide {slide_name} draws {len(slots)} slots where the boundary transition has "
                f"{slot_count}"
            )
        if found is not None and found != index:
            raise _Refuse(
                f"slide {slide_name} draws object {instance.object_id} in slot {found} and slot {index}"
            )
        found = index
    return found


def _refusal_record(
    boundary: SlideBoundary,
    movie: MovieContinuity,
    scene_index_by_player: dict[int, int],
    movie_keys: dict[str, str],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fromPlayer": boundary.from_player_index,
        "toPlayer": boundary.to_player_index,
        "atScene": scene_index_by_player.get(boundary.to_player_index),
        "asset": movie.asset,
        "movieKey": movie_keys.get(movie.asset),
        "reason": movie.refusal,
    }
    if movie.gl_replay is not None or movie.gl_replay_reason is not None:
        record["glReplay"] = movie.gl_replay is not None
        record["glReplayReason"] = movie.gl_replay_reason
        record["opacityExcluded"] = movie.gl_replay.get("excluded", []) if movie.gl_replay else []
    return record


def derive_plan(
    export_root: Path,
    slides: list[dict[str, Any]],
    *,
    resolver: Callable[[Path, str], Path] = safe_export_file,
    gl_replay: bool = False,
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

        if transition_name is not None and not isinstance(transition_name, str):
            return Unsupported(f"unreadable transition name at {boundary_desc}")

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
                continuity, src_instance, dst_instance = _resolve_continuation(
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
                if gl_replay:
                    continuity = _gl_replay_attempt(
                        continuity, transition, transition_name, len(continuing),
                        events_by_player[player_index], src_instance, uuid,
                        events_by_player[to_player_index],
                    )
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
            _refusal_record(boundary, movie, scene_index_by_player, movie_keys)
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
    probe_fps: Callable[[Path], float | None] = movie_fps,
) -> list[dict[str, Any]]:
    """Codec of every movie asset any non-skipped slide's events reference, independent
    of whether the deck qualifies for continuity (a rotated or ambiguous movie's codec
    is still worth reporting). Unreadable slides or assets are skipped, never raised:
    this report must stay available even when `derive_plan` refuses.

    Each entry covers all `files` the key resolves to: it reports a codec only when they
    all agree, and otherwise fails closed to an unreadable (`codec: None`, family
    `other`) entry, flagged `mixed` when the disagreement is between readable codecs.
    `fps` (rounded to 3 decimals) likewise is reported only when every file agrees."""
    assets = _referenced_movies(export_root, slides, resolver=resolver)
    report = []
    for asset, paths in sorted(assets.items()):
        fourccs = {probe(path) if path is not None else None for path in paths}
        mixed = len(fourccs) > 1 and None not in fourccs
        fourcc = fourccs.pop() if len(fourccs) == 1 else None
        rates = {probe_fps(path) if path is not None else None for path in paths}
        fps = rates.pop() if len(rates) == 1 else None
        entry: dict[str, Any] = {
            "asset": asset, "codec": fourcc, "family": codec_family(fourcc), "files": len(paths),
            "fps": round(fps, 3) if fps is not None else None,
        }
        if mixed:
            entry["mixed"] = True
        report.append(entry)
    return report

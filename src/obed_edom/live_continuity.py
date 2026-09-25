"""Derive a movie-continuity plan from a Keynote HTML export, without touching the browser.

A `ContinuityPlan` tells the live host, for every slide boundary in player order, what should
happen to each movie instance on it, named by its export `objectID`: `pin` (Magic Move, same
on-stage rect on both sides -- the live `<video>` keeps playing untouched), `bridge` (Magic Move,
same asset, the rect changes -- the live `<video>` is moved/resized in place instead of
Keynote's export restarting it from a fresh decoder), `restart` (dissolve or no transition --
Keynote's own fresh-decoder behaviour is correct), or `retire` (a carried instance no instance
continues). Repeated instances of one asset pair across a Magic Move by minimum total centre
distance, as Keynote pairs them. Geometry is derived from the export's authored layer tree
(`renderMovie` node baseLayer + `isVideoLayer` sub-layer, centre-anchored), never measured on
screen. Anything the export encodes in a way this module cannot map exactly (rotation, animated
geometry, an unknown transition kind) fails closed to `Unsupported` instead of guessing. A
boundary that is structurally carryable but cannot be carried safely (an ambiguous pairing,
artwork drawn over the movie, a build, a loop or trim mismatch, a movie with no `<video>`) is
refused on its own, as a `retire`, and the rest of the deck stays as authored.
"""

from __future__ import annotations

import hashlib
import itertools
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
_TRIM_SUFFIX_RE = re.compile(r"^(?P<name>.+)(?P<trim>-\d+\.\d+-\d+\.\d+)(?P<ext>\.[A-Za-z0-9]+)$")
_IMAGE_MOVIE_RE = re.compile(r"\.(png|gif|heic\w*)$", re.IGNORECASE)
_MOVIE_START_BUILD = "apple:movie-start"
_CUT_TRANSITIONS: frozenset[str | None] = frozenset({None, "none", "apple:dissolve"})
"""No transition (absent, or exported as `none`) and Dissolve: the player restarts each movie."""
_PAIRING_MARGIN_PX = 16.0
_MAX_ASSIGNMENTS = 5040
"""The pairing search cap, the same as `validate.MM_MAX_ASSIGNMENTS`."""

_MOVIE_SUBTREE_KEYS: dict[str, frozenset[str]] = {
    "<movie node>": frozenset(
        {"attributes", "baseLayer", "beginTime", "duration", "effects", "movie", "name", "objectID", "type"}
    ),
    "movie": frozenset({"asset", "endTime", "isAudioOnly", "isStreaming", "loopMode", "startTime", "volume"}),
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
        "283f5eecd18c3412172e28a40bc716c69173a7c72bcd37379dcd3d7d6a96dd4e",  # P2, glReplay off
        "2fbf977277a5eef1cde701c12bb157905e40ac2b0a5ed85e30bf1056a3e65c18",  # P2, glReplay on
        "866de785864ad19b11ecd8cdfb4ad1729798ccf9f1764aa59718de03034ba7a5",  # p2-loop, glReplay off
        "d860a09f4f6a8e24a81e2ad0c3b37bc8a3f2b4ce3947836ca315671031870131",  # p2-loop, glReplay on
        # S2 branch only: the S0 decks (either flag), until the S2 gate keeps those that pass Q3+Q7.
        "4d466b2f0ee035928486dc3e61f23a5d92e3cc4e76d5d02f367e115331cc0b00",  # D1
        "029a4c427d2f7ebe2cf7410e2010fdc03834f370f5c6d25aeea9e05c2fbc20f7",  # D2 and D2-across
        "01b74c88f4622e5a0650d334d7721a247a2039a1767f232d792e823405a21b1b",  # D3
        "e166c385753364cdc159307b8f7d9092979533b71aee93ea4b8ebbea7a366076",  # D4
        "73d1153f086381996b5490d6f66eae2ee6996eb05b4a1dcd0af0fce70a018f5e",  # D5
        "149e813cfe68b6bac7c5c4ea0b5829f20e017ee1d0ce742ece3444fd1f60eed1",  # D6
    }
)


def plan_signature(runtime: dict[str, Any]) -> str:
    """Until every refusal code is covered by a negative corpus and the S0 decks pass the gates,
    a plan is trusted only when its runtime shape is one the gates actually measured."""
    return hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


RUNTIME_SCHEMA = 2
_CARRY_ACTIONS = frozenset({"pin", "bridge", "glReplay"})


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

    def centre(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass(frozen=True)
class MovieContinuity:
    """One planned movie instance at one boundary. `pin`/`bridge` carry `src` onto `dst`,
    `restart` lets the player restart it, `retire` hands a carried decoder back because no
    instance continues (`refusal` None) or because the pairing itself was refused."""

    asset: str
    action: str
    src_rect: Rect | None
    dst_rect: Rect | None
    refusal: str | None = None
    """Why this boundary cannot carry the movie, when `action` says it structurally could."""
    gl_replay: dict[str, Any] | None = None
    """The full `effect_opacity_overrides` result when this refused pin qualified for `glReplay`
    derivation (arming plan section 11), else `None`."""
    gl_replay_reason: str | None = None
    """Why `gl_replay` derivation was not attempted or did not qualify, else `None`."""
    gl_replay_slot: int | None = None
    """The carried instance's index in the source slide's draw order; the runtime entry's
    `movieSlot`. Flag-on only."""
    src_object_id: str | None = None
    dst_object_id: str | None = None
    loop: bool = False
    """The source instance's loop setting, which a carried decoder keeps."""
    code: str | None = None
    """The refusal's code (`overlap`, `R1`, `R1b`, `R2`, `R4`, `R7`, `R8`) when `refusal` is set."""

    def as_dict(self) -> dict[str, Any]:
        result = {
            "asset": self.asset,
            "action": self.action,
            "srcRect": self.src_rect.as_dict() if self.src_rect else None,
            "dstRect": self.dst_rect.as_dict() if self.dst_rect else None,
            "srcObjectId": self.src_object_id,
            "dstObjectId": self.dst_object_id,
            "loop": self.loop,
        }
        if self.refusal is not None:
            result["code"] = self.code
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
    authored-space rects, ordered by (x, y, w, h) ascending. Not part of `to_runtime()`."""
    refusals: tuple[dict[str, Any], ...] = ()
    """One entry per refused (boundary, instance). Additive and not part of `to_runtime()`."""
    loop_instances: dict[int, dict[str, list[dict[str, float]]]] = field(default_factory=dict)
    """The looping subset of `slide_instances`, same shape and order. Not in `as_dict()` or
    `to_runtime()`: each runtime entry carries its own `loop`."""

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
        """Translate this plan into the schema-2 shape `PRESERVE_CORE_JS` reads as
        `window.__OBED_CONTINUITY__` (plan section 2.1): one entry per (boundary, planned
        instance). A refused movie becomes `retire` (`reason: "refused"`), or `glReplay` when it
        qualified -- at most one per plan; an unrefused `retire` ends a carried decoder
        (`reason: "ends"`). Fails closed when an entry cannot name its instances, a bridge has
        no positive export duration, or the chain invariant (R6) does not hold."""
        if not self.boundaries:
            return Unsupported("no boundaries to translate")
        keys = _movie_keys(self)
        entries: list[dict[str, Any]] = []
        footprints: dict[str, dict[str, int]] = {}
        for boundary in self.boundaries:
            if boundary.to_player_index is None:
                continue
            scene = self.scene_index_by_player.get(boundary.to_player_index)
            if scene is None:
                return Unsupported(f"missing scene index for player index {boundary.to_player_index}")
            for movie in boundary.movies:
                entry = _runtime_entry(self, boundary, movie, scene, keys[movie.asset])
                if isinstance(entry, Unsupported):
                    return entry
                entries.append(entry)
        entries.sort(key=_entry_order)
        for entry in entries:
            footprints.setdefault(entry["movieKey"], entry["src"]["rect"])
        if sum(entry["action"] == "glReplay" for entry in entries) > 1:
            return Unsupported("more than one glReplay boundary (G2 arms exactly one)")
        chain = _chain_refusal(self, entries)
        if chain is not None:
            return Unsupported(chain)
        movies = {
            key: {"assetKeys": [asset.lower()], "footprint": footprints[key]}
            for asset, key in keys.items()
            if key in footprints
        }
        runtime = {"schema": RUNTIME_SCHEMA, "movies": movies, "boundaries": entries}
        if plan_signature(runtime) not in QUALIFIED_PLAN_SHA256:
            return Unsupported("deck shape is not yet qualified for continuity (only gate-measured plans are)")
        return runtime


@dataclass(frozen=True)
class Unsupported:
    reason: str


def _movie_keys(plan: ContinuityPlan) -> dict[str, str]:
    """`movieN` per asset any runtime entry names, in asset order."""
    assets = sorted(
        {movie.asset for b in plan.boundaries if b.to_player_index is not None for movie in b.movies}
    )
    return {asset: f"movie{i + 1}" for i, asset in enumerate(assets)}


def _endpoint(object_id: str | None, rect: Rect | None) -> dict[str, Any] | None:
    if not object_id or rect is None or not all(map(_math_isfinite, rect.as_dict().values())):
        return None
    return {"objectId": object_id, "rect": _rect_ints(rect.as_dict())}


def _positive_duration(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _runtime_entry(
    plan: ContinuityPlan, boundary: SlideBoundary, movie: MovieContinuity, scene: int, key: str
) -> dict[str, Any] | Unsupported:
    where = f"'{movie.asset}' at scene {scene}"
    src = _endpoint(movie.src_object_id, movie.src_rect)
    if src is None:
        return Unsupported(f"{movie.action} of {where} does not name its source instance")
    base = {"atScene": scene, "movieKey": key, "src": src}
    if movie.refusal is not None and movie.gl_replay is None:
        return {**base, "action": "retire", "reason": "refused"}
    if movie.action == "retire":
        return {**base, "action": "retire", "reason": "ends"}
    if movie.action == "restart":
        dst = _endpoint(movie.dst_object_id, movie.dst_rect)
        return {**base, "action": "restart", **({"dst": dst} if dst is not None else {})}
    dst = _endpoint(movie.dst_object_id, movie.dst_rect)
    if dst is None:
        return Unsupported(f"{movie.action} of {where} does not name its destination instance")
    if movie.refusal is not None:
        return _gl_replay_entry(plan, boundary, movie, {**base, "dst": dst, "loop": movie.loop})
    if movie.action == "pin":
        return {**base, "action": "pin", "dst": dst, "loop": movie.loop}
    if movie.action == "bridge":
        if not _positive_duration(boundary.transition_duration):
            return Unsupported("bridge transition has no finite positive export duration")
        return {
            **base, "action": "bridge", "dst": dst, "loop": movie.loop,
            "durationSeconds": boundary.transition_duration,
        }
    return Unsupported(f"unknown action '{movie.action}' for {where}")


def _gl_replay_entry(
    plan: ContinuityPlan, boundary: SlideBoundary, movie: MovieContinuity, base: dict[str, Any]
) -> dict[str, Any] | Unsupported:
    gl = movie.gl_replay or {}
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
    asset = movie.asset.lower()
    bound = _destination_instance(
        plan.slide_instances.get(boundary.to_player_index, {}).get(movie.asset), movie.dst_rect
    )
    if bound is None:
        return Unsupported(f"glReplay boundary's destination instance of '{asset}' is not in slide_instances")
    instance_index, instance_rect = bound
    return {
        **base, "action": "glReplay", "fallback": "retire",
        "slotSizes": slot_sizes, "slotRects": slot_rects, "opacityOverrides": overrides,
        "instanceId": f"{asset}#{instance_index}", "instanceRect": instance_rect, "movieSlot": slot,
    }


def _entry_order(entry: dict[str, Any]) -> tuple[Any, ...]:
    rect = entry["src"]["rect"]
    return entry["atScene"], int(entry["movieKey"][len("movie"):]), rect["x"], rect["y"], entry["src"]["objectId"]


def _chain_refusal(plan: ContinuityPlan, entries: list[dict[str, Any]]) -> str | None:
    """R6: every carried `dst` is the `src` of exactly one entry at the next boundary unless
    the deck ends there, and no instance is the `src` of two entries."""
    sources = [entry["src"]["objectId"] for entry in entries]
    repeated = sorted({object_id for object_id in sources if sources.count(object_id) > 1})
    if repeated:
        return f"R6: instance {repeated[0]} is the source of more than one entry"
    next_scene = {
        plan.scene_index_by_player[b.to_player_index]: plan.scene_index_by_player.get(
            _next_player(plan, b.to_player_index)
        )
        for b in plan.boundaries
        if b.to_player_index is not None
    }
    by_scene_source = {(entry["atScene"], entry["src"]["objectId"]) for entry in entries}
    for entry in entries:
        if entry["action"] not in _CARRY_ACTIONS:
            continue
        following = next_scene.get(entry["atScene"])
        if following is None:
            continue
        if (following, entry["dst"]["objectId"]) not in by_scene_source:
            return (
                f"R6: the {entry['action']} at scene {entry['atScene']} carries "
                f"{entry['dst']['objectId']}, which no entry at scene {following} continues or ends"
            )
    return None


def _next_player(plan: ContinuityPlan, player_index: int) -> int | None:
    for boundary in plan.boundaries:
        if boundary.from_player_index == player_index:
            return boundary.to_player_index
    return None


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


def _asset_url(assets_table: dict[str, Any], asset_id: str) -> str:
    entry = assets_table.get(asset_id) or {}
    url = entry.get("url") or {}
    return url.get("web") or url.get("native") or asset_id


def _normalize_asset_key(assets_table: dict[str, Any], asset_id: str) -> str:
    filename = _asset_url(assets_table, asset_id).rsplit("/", 1)[-1]
    match = _TRIM_SUFFIX_RE.match(filename)
    name = match.group("name") if match else filename
    return name.lower()


def _movie_kind(movie: dict[str, Any], url: str) -> str:
    """`video` when the player builds a `<video>` for it (F1); a web video is an `<iframe>` and
    an image movie an `<img>`, neither of which the runtime can carry (R7)."""
    if movie.get("isStreaming") is not False or re.match(r"^[a-z]+://", url, re.IGNORECASE):
        return "web"
    if _IMAGE_MOVIE_RE.search(url):
        return "image"
    return "video"


def _movie_trim(movie: dict[str, Any], url: str) -> tuple[Any, ...]:
    match = _TRIM_SUFFIX_RE.match(url.rsplit("/", 1)[-1])
    return movie.get("startTime"), movie.get("endTime"), match.group("trim") if match else None


def _movie_opacity(node: dict[str, Any]) -> tuple[Any, ...]:
    base_layer = node["baseLayer"]
    return tuple(
        (layer.get("initialState") or {}).get("opacity")
        for layer in (base_layer, *_find_video_sublayers(base_layer))
    )


@dataclass(frozen=True)
class _MovieInstance:
    rect: Rect
    object_id: str | None
    loop: bool = False
    opacity: tuple[Any, ...] = ()
    kind: str = "video"
    trim: tuple[Any, ...] = ()


def _loops(movie: dict[str, Any], slide_name: str) -> bool:
    if "loopMode" not in movie:
        return False
    value = movie["loopMode"]
    if value == "looping":
        return True
    raise _Refuse(
        f"movie on slide {slide_name} has an unmeasured loopMode {value!r} (only 'looping' is qualified)"
    )


def _slide_movie_instances(
    events: list[Any], assets_table: dict[str, Any], slide_name: str
) -> dict[str, list[_MovieInstance]]:
    instances: dict[str, list[_MovieInstance]] = {}
    for node in _find_movie_nodes(events):
        movie = node["movie"]
        asset_id = movie.get("asset")
        if not isinstance(asset_id, str) or not asset_id:
            raise _Refuse(f"movie node on slide {slide_name} has no asset id")
        object_id = node.get("objectID")
        if not isinstance(object_id, str) or not object_id:
            raise _Refuse(f"movie on slide {slide_name} has no object id")
        rect = _movie_rect(node, slide_name)
        url = _asset_url(assets_table, asset_id)
        instances.setdefault(_normalize_asset_key(assets_table, asset_id), []).append(
            _MovieInstance(
                rect, object_id, _loops(movie, slide_name), _movie_opacity(node),
                _movie_kind(movie, url), _movie_trim(movie, url),
            )
        )
    for found in instances.values():
        found.sort(key=lambda i: (i.rect.x, i.rect.y, i.rect.w, i.rect.h))
    return instances


def _sorted_rects(
    instances: dict[str, list[_MovieInstance]], *, loop_only: bool = False
) -> dict[str, list[dict[str, float]]]:
    projected = {
        asset: [
            instance.rect.as_dict()
            for instance in sorted(found, key=lambda i: (i.rect.x, i.rect.y, i.rect.w, i.rect.h))
            if instance.loop or not loop_only
        ]
        for asset, found in sorted(instances.items())
    }
    return {asset: rects for asset, rects in projected.items() if rects}


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
    if transitions and _boundary_transition_off_last_event(events, transitions[0]):
        raise _Refuse(
            f"R3: slide {slide_name}'s transition is not on its last event, so the runtime's "
            "atScene-1 convention would name the wrong scene"
        )
    return transitions[0] if transitions else None


def _boundary_transition_off_last_event(events: list[Any], transition: dict[str, Any]) -> bool:
    last = events[-1]
    effects = last.get("effects") if isinstance(last, dict) else None
    return not isinstance(effects, list) or not any(effect is transition for effect in effects)


def _build_targets(events: list[Any], build_type: str) -> tuple[set[str], list[str]]:
    """Object ids that build in/out on a slide, ignoring movie-start builds (they do not stop
    Magic Move pairing, F3), plus the names of any such builds that name no object."""
    targets: set[str] = set()
    unattributed: list[str] = []
    for event in events:
        for effect in (event.get("effects") if isinstance(event, dict) else None) or []:
            if not isinstance(effect, dict) or effect.get("type") != build_type:
                continue
            if effect.get("name") == _MOVIE_START_BUILD:
                continue
            object_id = effect.get("objectID")
            if isinstance(object_id, str) and object_id:
                targets.add(object_id)
            else:
                unattributed.append(str(effect.get("name")))
    return targets, unattributed


def _pair_instances(
    outgoing: list[_MovieInstance], incoming: list[_MovieInstance]
) -> tuple[list[tuple[_MovieInstance, _MovieInstance]], None] | tuple[None, tuple[str, str]]:
    """Keynote's Magic Move pairing of one asset's instances (F3, plan section 2.2): the
    assignment of minimum total centre distance. Refused (R1b) when the candidates differ in
    exported opacity, since Keynote's tier-1 preference would then override distance, and (R1)
    when the runner-up assignment is within `_PAIRING_MARGIN_PX` or the search exceeds the cap."""
    if (len(outgoing) > 1 or len(incoming) > 1) and len({i.opacity for i in outgoing + incoming}) > 1:
        return None, ("R1b", "its instances differ in opacity, which Keynote pairs by before distance")
    swapped = len(outgoing) > len(incoming)
    smaller, larger = (incoming, outgoing) if swapped else (outgoing, incoming)
    if math.perm(len(larger), len(smaller)) > _MAX_ASSIGNMENTS:
        return None, ("R1", f"{len(outgoing)} x {len(incoming)} instances exceed the pairing search cap")
    ranked = sorted(
        (sum(math.dist(smaller[i].rect.centre(), larger[j].rect.centre()) for i, j in enumerate(chosen)), chosen)
        for chosen in itertools.permutations(range(len(larger)), len(smaller))
    )
    if len(ranked) > 1 and ranked[1][0] - ranked[0][0] <= _PAIRING_MARGIN_PX:
        return None, (
            "R1",
            f"the best and runner-up pairings differ by {ranked[1][0] - ranked[0][0]:.1f} px "
            f"(margin {_PAIRING_MARGIN_PX:g} px)",
        )
    pairs = [(smaller[i], larger[j]) for i, j in enumerate(ranked[0][1])]
    return [(b, a) if swapped else (a, b) for a, b in pairs], None


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
        "code": movie.code,
        "objectId": movie.src_object_id,
    }
    if movie.gl_replay is not None or movie.gl_replay_reason is not None:
        record["glReplay"] = movie.gl_replay is not None
        record["glReplayReason"] = movie.gl_replay_reason
        record["opacityExcluded"] = movie.gl_replay.get("excluded", []) if movie.gl_replay else []
    return record


@dataclass(frozen=True)
class _Slide:
    player_index: int
    uuid: str
    events: list[Any]
    instances: dict[str, list[_MovieInstance]]


def _carry(asset: str, src: _MovieInstance, dst: _MovieInstance) -> MovieContinuity:
    return MovieContinuity(
        asset, "pin" if src.rect.close_to(dst.rect) else "bridge", src.rect, dst.rect,
        src_object_id=src.object_id, dst_object_id=dst.object_id, loop=src.loop,
    )


def _retire(asset: str, src: _MovieInstance, refusal: tuple[str, str] | None = None) -> MovieContinuity:
    code, reason = refusal or (None, None)
    return MovieContinuity(
        asset, "retire", src.rect, None, refusal=reason, src_object_id=src.object_id, loop=src.loop, code=code
    )


def _carry_refusal(
    asset: str, src: _MovieInstance, dst: _MovieInstance, source: _Slide, destination: _Slide, desc: str
) -> tuple[str, str] | None:
    """The first boundary-level refusal (plan section 2.3) of one paired carry, as (code, reason)."""
    for instance in (src, dst):
        if instance.kind != "video":
            return "R7", f"'{asset}' at {desc} is a {instance.kind} movie, which the player draws without a <video>"
    if src.trim != dst.trim:
        return "R8", f"'{asset}' is trimmed differently on each side of {desc}"
    built_out, out_unattributed = _build_targets(source.events, "buildOut")
    built_in, in_unattributed = _build_targets(destination.events, "buildIn")
    if src.object_id in built_out or dst.object_id in built_in:
        return "R2", f"'{asset}' builds in or out at {desc}, so Magic Move does not pair it"
    for slide, build_type, names in (
        (source, "build-out", out_unattributed), (destination, "build-in", in_unattributed),
    ):
        if names:
            return "R2", (
                f"a {build_type} ({names[0]!r}) on slide {slide.uuid} at {desc} names no object, and the "
                f"export gives no other way to tell whether it builds '{asset}', so the carry is refused "
                "rather than guessed"
            )
    if src.loop != dst.loop:
        return "R4", f"'{asset}' loops on one side of {desc} only; a carried decoder keeps its source's loop setting"
    overlap = _overlap_refusal(destination.events, dst, asset, destination.player_index, destination.uuid)
    return ("overlap", overlap) if overlap is not None else None


def _magic_move_movies(
    source: _Slide,
    destination: _Slide,
    held: set[str],
    desc: str,
    transition: dict[str, Any] | None,
    transition_name: str | None,
    gl_replay: bool,
    gl_replay_used: bool,
) -> list[MovieContinuity]:
    movies: list[MovieContinuity] = []
    carried: list[tuple[MovieContinuity, _MovieInstance, _MovieInstance]] = []
    for asset, outgoing in sorted(source.instances.items()):
        incoming = destination.instances.get(asset)
        pairs, refusal = _pair_instances(outgoing, incoming) if incoming else ([], None)
        if refusal is not None:
            code, reason = refusal
            movies.extend(_retire(asset, src, (code, f"'{asset}' pairing at {desc}: {reason}")) for src in outgoing)
            continue
        paired = {id(src) for src, _ in pairs}
        for src, dst in pairs:
            carried.append((_carry(asset, src, dst), src, dst))
        movies.extend(_retire(asset, src) for src in outgoing if id(src) not in paired and src.object_id in held)
    if sum(movie.action == "bridge" for movie, _, _ in carried) > 1:
        raise _Refuse(f"more than one movie changes geometry at {desc}")
    for movie, src, dst in carried:
        refusal = _carry_refusal(movie.asset, src, dst, source, destination, desc)
        if refusal is not None:
            code, reason = refusal
            movie = replace(movie, refusal=reason, code=code)
            if gl_replay and code != "overlap":
                movie = replace(movie, gl_replay_reason=reason)
            elif gl_replay and gl_replay_used:
                movie = replace(movie, gl_replay_reason="a glReplay boundary is already planned (one per plan)")
            elif gl_replay:
                movie = _gl_replay_attempt(
                    movie, transition, transition_name, len(carried),
                    source.events, src, source.uuid, destination.events,
                )
                gl_replay_used = movie.gl_replay is not None
        movies.append(movie)
    return sorted(movies, key=lambda movie: movie.asset)


def _cut_movies(source: _Slide, destination: _Slide, held: set[str]) -> list[MovieContinuity]:
    """A Dissolve or no transition: the player restarts every `<video>` instance whose asset is on
    the far side; a carried one whose asset is not ends."""
    movies: list[MovieContinuity] = []
    for asset, outgoing in sorted(source.instances.items()):
        incoming = destination.instances.get(asset) or []
        dst = incoming[0] if len(incoming) == 1 else None
        for src in outgoing:
            if incoming and src.kind == "video":
                movies.append(MovieContinuity(
                    asset, "restart", src.rect, dst.rect if dst else None,
                    src_object_id=src.object_id, dst_object_id=dst.object_id if dst else None, loop=src.loop,
                ))
            elif src.object_id in held:
                movies.append(_retire(asset, src))
    return movies


def _held_after(movies: list[MovieContinuity]) -> set[str]:
    return {
        movie.dst_object_id
        for movie in movies
        if movie.action in ("pin", "bridge") and (movie.refusal is None or movie.gl_replay is not None)
        and movie.dst_object_id
    }


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

    parsed: list[_Slide] = []
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
        try:
            parsed.append(_Slide(player_index, uuid, events, _slide_movie_instances(events, assets_table, uuid)))
        except _Refuse as exc:
            return Unsupported(str(exc))

    seen: dict[str, int] = {}
    for slide in parsed:
        for found in slide.instances.values():
            for instance in found:
                if instance.object_id in seen:
                    return Unsupported(
                        f"R5: movie object {instance.object_id} appears on player index "
                        f"{seen[instance.object_id]} and {slide.player_index}"
                    )
                seen[instance.object_id] = slide.player_index

    boundaries: list[SlideBoundary] = []
    held: set[str] = set()
    gl_replay_used = False
    for index, source in enumerate(parsed):
        try:
            transition = _boundary_transition(source.events, source.uuid)
        except _Refuse as exc:
            return Unsupported(str(exc))
        transition_name = transition.get("name") if transition else None
        transition_duration = transition.get("duration") if transition else None
        destination = parsed[index + 1] if index + 1 < len(parsed) else None

        if destination is None:
            movies = tuple(
                MovieContinuity(asset, "restart", found[0].rect if len(found) == 1 else None, None)
                for asset, found in sorted(source.instances.items())
            )
            boundaries.append(SlideBoundary(source.player_index, None, movies, transition_duration))
            continue

        desc = f"player index {source.player_index} -> {destination.player_index}"
        if transition_name is not None and not isinstance(transition_name, str):
            return Unsupported(f"unreadable transition name at {desc}")
        try:
            if transition_name is not None and transition_name.startswith("apple:magic-move"):
                movies_list = _magic_move_movies(
                    source, destination, held, desc, transition, transition_name, gl_replay, gl_replay_used
                )
            elif transition_name in _CUT_TRANSITIONS:
                movies_list = _cut_movies(source, destination, held)
            else:
                return Unsupported(f"unsupported transition '{transition_name}' at {desc}")
        except _Refuse as exc:
            return Unsupported(str(exc))
        gl_replay_used = gl_replay_used or any(movie.gl_replay is not None for movie in movies_list)
        held = _held_after(movies_list)
        boundaries.append(
            SlideBoundary(source.player_index, destination.player_index, tuple(movies_list), transition_duration)
        )

    plan = ContinuityPlan(
        canvas=canvas,
        scene_index_by_player=scene_index_by_player,
        slide_rects={
            slide.player_index: {
                asset: found[0].rect.as_dict() for asset, found in slide.instances.items() if len(found) == 1
            }
            for slide in parsed
        },
        boundaries=tuple(boundaries),
        slide_instances={slide.player_index: _sorted_rects(slide.instances) for slide in parsed},
        loop_instances={
            slide.player_index: _sorted_rects(slide.instances, loop_only=True)
            for slide in parsed
            if any(instance.loop for found in slide.instances.values() for instance in found)
        },
    )
    movie_keys = _movie_keys(plan)
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
    with_fps: bool = False,
) -> list[dict[str, Any]]:
    """Codec of every movie asset any non-skipped slide's events reference, independent
    of whether the deck qualifies for continuity (a rotated or ambiguous movie's codec
    is still worth reporting). Unreadable slides or assets are skipped, never raised:
    this report must stay available even when `derive_plan` refuses.

    Each entry covers all `files` the key resolves to: it reports a codec only when they
    all agree, and otherwise fails closed to an unreadable (`codec: None`, family
    `other`) entry, flagged `mixed` when the disagreement is between readable codecs.
    With `with_fps`, entries also carry `fps` (rounded to 3 decimals), likewise set only
    when every file agrees."""
    assets = _referenced_movies(export_root, slides, resolver=resolver)
    report = []
    for asset, paths in sorted(assets.items()):
        fourccs = {probe(path) if path is not None else None for path in paths}
        mixed = len(fourccs) > 1 and None not in fourccs
        fourcc = fourccs.pop() if len(fourccs) == 1 else None
        entry: dict[str, Any] = {
            "asset": asset, "codec": fourcc, "family": codec_family(fourcc), "files": len(paths),
        }
        if with_fps:
            rates = {probe_fps(path) if path is not None else None for path in paths}
            fps = rates.pop() if len(rates) == 1 else None
            entry["fps"] = round(fps, 3) if fps is not None else None
        if mixed:
            entry["mixed"] = True
        report.append(entry)
    return report

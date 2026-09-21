"""Version 2 DSK composition review contract and offline compiler.

This module deliberately knows nothing about Keynote writes.  It turns inspected
source occurrences into a small, strict review document and turns that document
into the frozen apply boundary consumed by the generator adapter.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from obed_edom.dsk_movie_export import movie_build_order, movie_order
from obed_edom.map_remap import CENTRE_PANEL_RECT, Rect


SCHEMA_VERSION = 2
CANVAS = {"width": 1920, "height": 1080}
SAFE_AREA = {"left": 43, "right": 1877, "bottom": 1065}
DEFAULT_VIEWPORT = {"width": 935, "height": 263, "aspectLocked": True}
ALIGNMENTS = frozenset({"inherit", "left", "centre", "right"})
SOURCES = frozenset({"lw", "fw"})
CONTENT_MODES = frozenset({"full", "video"})
MEDIA_KINDS = frozenset({"movie", "image"})


class ReviewValidationError(ValueError):
    """A review document is malformed or asks for an unsafe operation."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewValidationError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReviewValidationError(f"{name} must be an array")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewValidationError(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReviewValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReviewValidationError(f"{name} must be a finite number")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ReviewValidationError(f"{name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ReviewValidationError(f"{name} must be <= {maximum}")
    return number


def _enum(value: Any, name: str, choices: frozenset[str]) -> str:
    value = _string(value, name)
    if value not in choices:
        raise ReviewValidationError(f"{name} must be one of {sorted(choices)}")
    return value


def _rect(raw: Any, name: str, *, normalised: bool = False) -> dict[str, float]:
    value = _mapping(raw, name)
    required = {"x", "y", "width", "height"}
    if set(value) != required:
        raise ReviewValidationError(f"{name} must contain exactly {sorted(required)}")
    maximum = 1.0 if normalised else None
    out = {key: _number(value[key], f"{name}.{key}", minimum=0, maximum=maximum) for key in required}
    if out["width"] <= 0 or out["height"] <= 0:
        raise ReviewValidationError(f"{name} width and height must be positive")
    if normalised and (out["x"] + out["width"] > 1.0 + 1e-9 or out["y"] + out["height"] > 1.0 + 1e-9):
        raise ReviewValidationError(f"{name} must fit within the normalized composition")
    return out


def _viewport(raw: Any, name: str) -> dict[str, Any]:
    value = _mapping(raw, name)
    if set(value) != {"width", "height", "aspectLocked"}:
        raise ReviewValidationError(f"{name} must contain width, height, and aspectLocked")
    if not isinstance(value["aspectLocked"], bool):
        raise ReviewValidationError(f"{name}.aspectLocked must be a boolean")
    width = _number(value["width"], f"{name}.width", minimum=1)
    height = _number(value["height"], f"{name}.height", minimum=1)
    if width > SAFE_AREA["right"] - SAFE_AREA["left"] or height > SAFE_AREA["bottom"]:
        raise ReviewValidationError(f"{name} exceeds the editor safe area")
    return {
        "width": width,
        "height": height,
        "aspectLocked": value["aspectLocked"],
    }


def _mask(raw: Any, name: str) -> dict[str, float]:
    value = _mapping(raw, name)
    # zoom/pan are the public v2 contract.  The frozen compiled contract calls
    # the same values viewport scale/offset; do not accept either spelling here.
    if set(value) != {"zoom", "panX", "panY"}:
        raise ReviewValidationError(f"{name} must contain zoom, panX, and panY")
    return {
        "zoom": _number(value["zoom"], f"{name}.zoom", minimum=1),
        "panX": _number(value["panX"], f"{name}.panX", minimum=-1, maximum=1),
        "panY": _number(value["panY"], f"{name}.panY", minimum=-1, maximum=1),
    }


def _decision(
    raw: Any,
    name: str,
    occurrence_kinds: Mapping[str, str],
    *,
    video_sources: set[str],
) -> dict[str, Any]:
    value = _mapping(raw, name)
    required = {"include", "alignment", "viewport", "source", "contentMode", "masks"}
    if set(value) != required:
        raise ReviewValidationError(f"{name} must contain exactly {sorted(required)}")
    if not isinstance(value["include"], bool):
        raise ReviewValidationError(f"{name}.include must be a boolean")
    viewport = value["viewport"]
    if viewport is not None:
        viewport = _viewport(viewport, f"{name}.viewport")
    masks = _mapping(value["masks"], f"{name}.masks")
    parsed_masks: dict[str, dict[str, float]] = {}
    for occurrence_id, mask in masks.items():
        if occurrence_id not in occurrence_kinds:
            raise ReviewValidationError(f"{name}.masks has unknown occurrence id {occurrence_id!r}")
        if occurrence_kinds[occurrence_id] != "movie":
            raise ReviewValidationError(f"{name}.masks can only target movie occurrences")
        parsed_masks[_string(occurrence_id, f"{name}.masks key")] = _mask(mask, f"{name}.masks.{occurrence_id}")
    source_mode = _enum(value["source"], f"{name}.source", SOURCES)
    content_mode = _enum(value["contentMode"], f"{name}.contentMode", CONTENT_MODES)
    if content_mode == "video" and source_mode not in video_sources:
        raise ReviewValidationError(f"{name}.contentMode=video is not supported by this composition")
    return {
        "include": value["include"],
        "alignment": _enum(value["alignment"], f"{name}.alignment", ALIGNMENTS),
        "viewport": viewport,
        "source": source_mode,
        "contentMode": content_mode,
        "masks": parsed_masks,
    }


def validate_payload(raw: Any) -> dict[str, Any]:
    """Parse a v2 payload without coercion, defaults, or silently ignored fields."""
    value = _mapping(raw, "review")
    required = {"schemaVersion", "revision", "source", "canvas", "safeArea", "defaults", "compositions"}
    if set(value) != required:
        raise ReviewValidationError(f"review must contain exactly {sorted(required)}")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise ReviewValidationError("review.schemaVersion must be 2")
    source = _mapping(value["source"], "review.source")
    if set(source) != {"path", "fingerprint"}:
        raise ReviewValidationError("review.source must contain path and fingerprint")
    canvas = _mapping(value["canvas"], "review.canvas")
    if canvas != CANVAS:
        raise ReviewValidationError("review.canvas must be 1920x1080")
    safe = _mapping(value["safeArea"], "review.safeArea")
    if safe != SAFE_AREA:
        raise ReviewValidationError("review.safeArea does not match the frozen editor safe area")
    defaults = _mapping(value["defaults"], "review.defaults")
    if set(defaults) != {"viewport", "alignment"}:
        raise ReviewValidationError("review.defaults must contain viewport and alignment")
    parsed_defaults = {
        "viewport": _viewport(defaults["viewport"], "review.defaults.viewport"),
        "alignment": _enum(defaults["alignment"], "review.defaults.alignment", frozenset({"left", "centre", "right"})),
    }
    ids: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for index, raw_composition in enumerate(_list(value["compositions"], "review.compositions")):
        comp = _mapping(raw_composition, f"review.compositions[{index}]")
        required_comp = {"id", "sourceSlides", "layoutSlide", "category", "thumb", "capabilities", "warnings", "media", "previewLayers", "decision"}
        optional_comp = {"mediaLayout", "mediaLayouts"}
        if not required_comp.issubset(comp) or not set(comp).issubset(required_comp | optional_comp):
            raise ReviewValidationError(f"review.compositions[{index}] has unknown or missing fields")
        comp_id = _string(comp["id"], f"review.compositions[{index}].id")
        if comp_id in ids:
            raise ReviewValidationError(f"duplicate composition id {comp_id!r}")
        ids.add(comp_id)
        source_slides = [_integer(n, f"review.compositions[{index}].sourceSlides", minimum=1) for n in _list(comp["sourceSlides"], f"review.compositions[{index}].sourceSlides")]
        if not source_slides or source_slides != sorted(set(source_slides)):
            raise ReviewValidationError(f"review.compositions[{index}].sourceSlides must be unique and ordered")
        layout_slide = _integer(comp["layoutSlide"], f"review.compositions[{index}].layoutSlide", minimum=1)
        if layout_slide not in source_slides:
            raise ReviewValidationError(f"review.compositions[{index}].layoutSlide must be a source slide")
        capabilities = _mapping(comp["capabilities"], f"review.compositions[{index}].capabilities")
        if set(capabilities) != {"videoOnly", "mask"} or not all(isinstance(v, bool) for v in capabilities.values()):
            raise ReviewValidationError(f"review.compositions[{index}].capabilities must contain boolean videoOnly/mask")
        media: list[dict[str, Any]] = []
        occurrence_ids: set[str] = set()
        for media_index, raw_media in enumerate(_list(comp["media"], f"review.compositions[{index}].media")):
            entry = _mapping(raw_media, f"review.compositions[{index}].media[{media_index}]")
            fields = {"occurrenceId", "assetId", "kind", "sourceSlide", "sourceItem", "sourceModes", "slot", "poster"}
            optional_fields = {"sourceCrops"}
            if not fields.issubset(entry) or not set(entry).issubset(fields | optional_fields):
                raise ReviewValidationError(f"review.compositions[{index}].media[{media_index}] has unknown or missing fields")
            occurrence_id = _string(entry["occurrenceId"], "media.occurrenceId")
            if occurrence_id in occurrence_ids:
                raise ReviewValidationError(f"duplicate occurrence id {occurrence_id!r}")
            occurrence_ids.add(occurrence_id)
            source_item = _mapping(entry["sourceItem"], "media.sourceItem")
            if set(source_item) != {"kind", "kindIndex", "archiveId"}:
                raise ReviewValidationError("media.sourceItem must contain kind, kindIndex, archiveId")
            kind = _enum(entry["kind"], "media.kind", MEDIA_KINDS)
            if source_item["kind"] != kind:
                raise ReviewValidationError("media.sourceItem.kind must match media.kind")
            source_slide = _integer(entry["sourceSlide"], "media.sourceSlide", minimum=1)
            if source_slide not in source_slides:
                raise ReviewValidationError("media.sourceSlide must belong to the composition")
            source_modes = [
                _enum(mode, "media.sourceModes", SOURCES)
                for mode in _list(entry["sourceModes"], "media.sourceModes")
            ]
            if not source_modes or source_modes != list(dict.fromkeys(source_modes)):
                raise ReviewValidationError("media.sourceModes must be non-empty and unique")
            source_crops = {
                source: _rect(crop, f"media.sourceCrops.{source}", normalised=True)
                for source, crop in _mapping(entry.get("sourceCrops", {}), "media.sourceCrops").items()
            }
            if not set(source_crops).issubset(source_modes):
                raise ReviewValidationError("media.sourceCrops contains an unavailable source mode")
            media.append({
                "occurrenceId": occurrence_id, "assetId": _string(entry["assetId"], "media.assetId"), "kind": kind,
                "sourceSlide": source_slide,
                "sourceItem": {"kind": kind, "kindIndex": _integer(source_item["kindIndex"], "media.sourceItem.kindIndex"), "archiveId": _string(source_item["archiveId"], "media.sourceItem.archiveId")},
                "sourceModes": source_modes,
                "sourceCrops": source_crops,
                "slot": _rect(entry["slot"], "media.slot", normalised=True), "poster": _string(entry["poster"], "media.poster"),
            })
        layers = _list(comp["previewLayers"], f"review.compositions[{index}].previewLayers")
        layer_ids: list[str] = []
        for layer in layers:
            l = _mapping(layer, "preview layer")
            if set(l) != {"kind", "occurrenceId", "src", "slot"} or l.get("kind") != "media":
                raise ReviewValidationError("preview layer must be a media layer")
            oid = _string(l["occurrenceId"], "preview layer occurrenceId")
            if oid not in occurrence_ids:
                raise ReviewValidationError(f"preview layer has unknown occurrence id {oid!r}")
            _string(l["src"], "preview layer src")
            _rect(l["slot"], "preview layer slot", normalised=True)
            layer_ids.append(oid)
        if layer_ids != [entry["occurrenceId"] for entry in media]:
            raise ReviewValidationError("preview layers must exactly preserve media order")
        media_layout = _enum(comp.get("mediaLayout", "spatial"), "composition.mediaLayout", frozenset({"spatial", "stacked"}))
        raw_media_layouts = _mapping(
            comp.get("mediaLayouts", {"lw": media_layout, "fw": media_layout}),
            "composition.mediaLayouts",
        )
        if set(raw_media_layouts) != {"lw", "fw"}:
            raise ReviewValidationError("composition.mediaLayouts must contain lw and fw")
        media_layouts = {
            source: _enum(
                raw_media_layouts[source],
                f"composition.mediaLayouts.{source}",
                frozenset({"spatial", "stacked"}),
            )
            for source in ("lw", "fw")
        }
        parsed.append({
            "id": comp_id, "sourceSlides": source_slides, "layoutSlide": layout_slide,
            "category": _string(comp["category"], "composition.category"), "thumb": _string(comp["thumb"], "composition.thumb"),
            "capabilities": dict(capabilities), "warnings": [_string(w, "composition.warning") for w in _list(comp["warnings"], "composition.warnings")],
            "mediaLayout": media_layout, "mediaLayouts": media_layouts,
            "media": media, "previewLayers": layers,
            "decision": _decision(
                comp["decision"],
                "composition.decision",
                {entry["occurrenceId"]: entry["kind"] for entry in media},
                video_sources={
                    source
                    for entry in media
                    if entry["kind"] == "movie"
                    for source in entry["sourceModes"]
                } if capabilities["videoOnly"] else set(),
            ),
        })
    return {
        "schemaVersion": SCHEMA_VERSION, "revision": _integer(value["revision"], "review.revision"),
        "source": {"path": _string(source["path"], "review.source.path"), "fingerprint": _string(source["fingerprint"], "review.source.fingerprint")},
        "canvas": dict(CANVAS), "safeArea": dict(SAFE_AREA), "defaults": parsed_defaults, "compositions": parsed,
    }


@dataclass(frozen=True)
class CompiledMedia:
    occurrence_id: str
    source_slide: int
    source_item: tuple[str, int]
    archive_id: str
    asset_id: str
    target_rect: Rect
    viewport: dict[str, float]
    playback: dict[str, Any]
    timing: str
    preserve_stroke: bool


@dataclass(frozen=True)
class CompiledComposition:
    id: str
    source_slides: tuple[int, ...]
    layout_slide: int
    overlay_slide: int
    output_frame: Rect
    source_mode: str
    content_mode: str
    media: tuple[CompiledMedia, ...]
    media_layout: str = "spatial"
    alignment: str = "centre"


def _resolved_frame(decision: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, float]:
    viewport = decision["viewport"] or defaults["viewport"]
    width, height = float(viewport["width"]), float(viewport["height"])
    if width > SAFE_AREA["right"] - SAFE_AREA["left"] or height > SAFE_AREA["bottom"]:
        raise ReviewValidationError("viewport exceeds the editor safe area")
    alignment = defaults["alignment"] if decision["alignment"] == "inherit" else decision["alignment"]
    if alignment == "left":
        x = float(SAFE_AREA["left"])
    elif alignment == "right":
        x = float(SAFE_AREA["right"] - width)
    else:
        x = (CANVAS["width"] - width) / 2
    return {"x": x, "y": float(SAFE_AREA["bottom"] - height), "width": width, "height": height}


def compile_review(raw: Any) -> tuple[CompiledComposition, ...]:
    """Resolve inheritance and mask transforms into the narrow apply boundary."""
    review = validate_payload(raw)
    compiled: list[CompiledComposition] = []
    for comp in review["compositions"]:
        decision = comp["decision"]
        if not decision["include"]:
            continue
        frame = _resolved_frame(decision, review["defaults"])
        folded = len(comp["sourceSlides"]) > 1
        media: list[CompiledMedia] = []
        folded_movie_index = 0
        for entry in comp["media"]:
            if decision["source"] not in entry["sourceModes"]:
                continue
            if decision["contentMode"] == "video" and entry["kind"] != "movie":
                continue
            slot = entry["slot"]
            target = {
                "x": frame["x"] + frame["width"] * slot["x"], "y": frame["y"] + frame["height"] * slot["y"],
                "width": frame["width"] * slot["width"], "height": frame["height"] * slot["height"],
            }
            mask = decision["masks"].get(entry["occurrenceId"], {"zoom": 1.0, "panX": 0.0, "panY": 0.0})
            if folded and entry["kind"] == "movie":
                timing = "after_transition" if folded_movie_index == 0 else "with_build_1"
                folded_movie_index += 1
            else:
                timing = "with_build_1" if folded else "source"
            media.append(CompiledMedia(
                occurrence_id=entry["occurrenceId"], source_slide=entry["sourceSlide"],
                archive_id=entry["sourceItem"]["archiveId"], asset_id=entry["assetId"], target_rect=Rect(target["x"], target["y"], target["width"], target["height"]),
                source_item=(entry["sourceItem"]["kind"], entry["sourceItem"]["kindIndex"]),
                viewport={"zoom": mask["zoom"], "panX": mask["panX"], "panY": mask["panY"]},
                playback={"kind": entry["kind"]}, timing=timing, preserve_stroke=True,
            ))
        compiled.append(CompiledComposition(
            id=comp["id"], source_slides=tuple(comp["sourceSlides"]), layout_slide=comp["layoutSlide"],
            overlay_slide=comp["layoutSlide"], output_frame=Rect(frame["x"], frame["y"], frame["width"], frame["height"]), source_mode=decision["source"],
            content_mode=decision["contentMode"], media=tuple(media),
            media_layout=comp["mediaLayouts"][decision["source"]],
            alignment=review["defaults"]["alignment"] if decision["alignment"] == "inherit" else decision["alignment"],
        ))
    return tuple(compiled)


def compiled_dicts(raw: Any) -> list[dict[str, Any]]:
    """JSON-friendly frozen compiled contract for an adapter or test fixture."""
    return [asdict(value) for value in compile_review(raw)]


def apply_editable_review(stored: Any, envelope: Any) -> dict[str, Any]:
    """Merge the v2 write envelope into immutable proposed metadata.

    The browser never writes source/media/capability metadata back.  Requiring one
    decision for every composition prevents a partial client state from turning a
    selection into an accidental reset.
    """
    review = validate_payload(stored)
    value = _mapping(envelope, "review envelope")
    if set(value) != {"schemaVersion", "sourceFingerprint", "defaults", "decisions"}:
        raise ReviewValidationError("review envelope must contain schemaVersion, sourceFingerprint, defaults, and decisions")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise ReviewValidationError("review envelope.schemaVersion must be 2")
    if _string(value["sourceFingerprint"], "review envelope.sourceFingerprint") != review["source"]["fingerprint"]:
        raise ReviewValidationError("review envelope source fingerprint does not match this proposal")
    defaults = _mapping(value["defaults"], "review envelope.defaults")
    if set(defaults) != {"viewport", "alignment"}:
        raise ReviewValidationError("review envelope.defaults must contain viewport and alignment")
    parsed_defaults = {
        "viewport": _viewport(defaults["viewport"], "review envelope.defaults.viewport"),
        "alignment": _enum(defaults["alignment"], "review envelope.defaults.alignment", frozenset({"left", "centre", "right"})),
    }
    by_id = {comp["id"]: comp for comp in review["compositions"]}
    decision_rows = _list(value["decisions"], "review envelope.decisions")
    incoming: dict[str, dict[str, Any]] = {}
    for raw_decision in decision_rows:
        entry = _mapping(raw_decision, "review envelope decision")
        if set(entry) != {"id", "include", "alignment", "viewport", "source", "contentMode", "masks"}:
            raise ReviewValidationError("review envelope decision has unknown or missing fields")
        comp_id = _string(entry["id"], "review envelope decision.id")
        if comp_id not in by_id:
            raise ReviewValidationError(f"unknown composition id {comp_id!r}")
        if comp_id in incoming:
            raise ReviewValidationError(f"duplicate composition id {comp_id!r}")
        occurrences = {m["occurrenceId"]: m["kind"] for m in by_id[comp_id]["media"]}
        incoming[comp_id] = _decision(
            {k: v for k, v in entry.items() if k != "id"},
            "review envelope decision",
            occurrences,
            video_sources={
                source
                for media in by_id[comp_id]["media"]
                if media["kind"] == "movie"
                for source in media["sourceModes"]
            } if by_id[comp_id]["capabilities"]["videoOnly"] else set(),
        )
    if set(incoming) != set(by_id):
        raise ReviewValidationError("review envelope must include exactly one decision for every composition")
    merged = dict(review)
    merged["defaults"] = parsed_defaults
    merged["compositions"] = [{**comp, "decision": incoming[comp["id"]]} for comp in review["compositions"]]
    return validate_payload(merged)


def _source_item(item: Mapping[str, Any], slide: int, archive_ids: Mapping[tuple[int, str, int], str]) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    kind_index = int(item.get("kindIndex") or 0)
    archive_id = archive_ids.get((slide, kind, kind_index)) or str(item.get("archiveId") or f"unresolved-{slide}-{kind}-{kind_index}")
    return {"kind": kind, "kindIndex": kind_index, "archiveId": archive_id}


def build_review(
    *, path: str, fingerprint: str, payload: Mapping[str, Any], classes: Mapping[int, Any], thumbs: Mapping[int, str],
    selected: Sequence[int], archive_ids: Mapping[tuple[int, str, int], str] = {}, stacked: Mapping[int, bool] = {},
    stacked_fw: Mapping[int, bool] = {},
    transitions: Mapping[int, str | None] = {}, builds: Mapping[int, Mapping[str, Any]] = {},
    side_classes: Mapping[int, Any] | None = None, content_only: bool = True,
) -> dict[str, Any]:
    """Build ordered, conservative v2 compositions from one offline inspection.

    Folding is intentionally fail-closed: an explicit magic-move chain is folded only
    when every terminal asset has a stable asset id and the terminal slide contains the
    union.  Otherwise the affected slides remain separate with a warning.
    """
    slides = {int(s["number"]): s for s in payload.get("slides") or []}

    def media_on(source_slide: int, source_mode: str = "lw") -> list[Mapping[str, Any]]:
        class_map = side_classes if source_mode == "fw" and side_classes is not None else classes
        cls = class_map.get(source_slide)
        kept = getattr(cls, "kept", None)
        kept_set = set(kept) if kept is not None else None
        return [
            item
            for item in slides.get(source_slide, {}).get("items") or []
            if item.get("kind") in MEDIA_KINDS
            and item.get("fileName")
            and (
                kept_set is None
                or (str(item.get("kind")), int(item.get("kindIndex") or 0)) in kept_set
            )
        ]

    def asset_counts(items: Sequence[Mapping[str, Any]]) -> Counter[tuple[str, str]]:
        return Counter((str(item["kind"]), str(item["fileName"])) for item in items)

    selected = list(selected)
    selected_set = set(selected)
    compositions: list[dict[str, Any]] = []
    index = 0
    blocked_fold_through = 0
    while index < len(selected):
        number = selected[index]
        cls = classes.get(number)
        slide = slides.get(number, {})
        if cls is None or getattr(cls, "category", "empty") == "empty":
            index += 1
            continue
        chain = [number]
        cursor = index
        while (
            number > blocked_fold_through
            and cursor + 1 < len(selected)
            and selected[cursor + 1] == selected[cursor] + 1
        ):
            effect = str(transitions.get(selected[cursor]) or "")
            if not effect.startswith("apple:magic-move"):
                break
            chain.append(selected[cursor + 1])
            cursor += 1
        fold = len(chain) > 1 and all(n in selected_set for n in chain)
        if fold:
            previous_counts: Counter[tuple[str, str]] | None = None
            grows_strictly = True
            union_counts: Counter[tuple[str, str]] = Counter()
            for source_slide in chain:
                current_counts = asset_counts(media_on(source_slide, "fw"))
                union_counts |= current_counts
                if previous_counts is not None and not (
                    sum(current_counts.values()) > sum(previous_counts.values())
                    and all(current_counts[key] >= count for key, count in previous_counts.items())
                ):
                    grows_strictly = False
                previous_counts = current_counts
            terminal_items = media_on(chain[-1], "fw")
            if not union_counts or not grows_strictly or asset_counts(terminal_items) != union_counts:
                fold = False
                blocked_fold_through = chain[-1]
        source_slides = chain if fold else [number]
        layout_slide = source_slides[-1]
        if fold:
            media_items = [(layout_slide, item) for item in media_on(layout_slide, "fw")]
        else:
            media_items = [(number, item) for item in media_on(number, "fw")]
        if not fold and (stacked.get(number, False) or stacked_fw.get(number, False)):
            movie_items = {
                (str(item["kind"]), int(item.get("kindIndex") or 0)): item
                for _source_slide, item in media_items
                if item.get("kind") == "movie"
            }
            if len(movie_items) > 1:
                movie_rects = {
                    item_id: Rect(
                        float(item.get("x") or 0),
                        float(item.get("y") or 0),
                        float(item.get("w") or 0),
                        float(item.get("h") or 0),
                    )
                    for item_id, item in movie_items.items()
                }
                ordered_ids = movie_order(
                    movie_rects,
                    movie_build_order((builds.get(number) or {}).get("builds") or (), movie_items),
                    {
                        item_id: int(item["index"]) if item.get("index") is not None else item_id[1]
                        for item_id, item in movie_items.items()
                    },
                    "stacked",
                )
                ordered_movies = iter(movie_items[item_id] for item_id in ordered_ids)
                media_items = [
                    (source_slide, next(ordered_movies) if item.get("kind") == "movie" else item)
                    for source_slide, item in media_items
                ]
        # Source frame slots preserve genuine overlap.  Normalise against the union,
        # never tile layers merely because there is more than one movie.
        if media_items:
            x0 = min(float(i.get("x") or 0) for _, i in media_items); y0 = min(float(i.get("y") or 0) for _, i in media_items)
            x1 = max(float(i.get("x") or 0) + float(i.get("w") or 0) for _, i in media_items); y1 = max(float(i.get("y") or 0) + float(i.get("h") or 0) for _, i in media_items)
            width, height = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        else:
            x0 = y0 = 0.0; width = height = 1.0
        media = []
        source_width = float(payload.get("slideWidth") or 7680)
        source_height = float(payload.get("slideHeight") or 1080)
        lw_ids = {
            (str(item.get("kind")), int(item.get("kindIndex") or 0))
            for item in media_on(layout_slide, "lw")
        }
        for source_slide, item in media_items:
            source_item = _source_item(item, source_slide, archive_ids)
            oid = f"{source_slide}:{source_item['archiveId']}"
            slot = {"x": (float(item.get("x") or 0) - x0) / width, "y": (float(item.get("y") or 0) - y0) / height, "width": float(item.get("w") or 0) / width, "height": float(item.get("h") or 0) / height}
            item_id = (str(item.get("kind")), int(item.get("kindIndex") or 0))
            source_modes = ["lw", "fw"] if item_id in lw_ids else ["fw"]
            raw = Rect(
                float(item.get("x") or 0),
                float(item.get("y") or 0),
                float(item.get("w") or 0),
                float(item.get("h") or 0),
            )
            source_crops: dict[str, dict[str, float]] = {}
            for source_mode in source_modes:
                bounds = CENTRE_PANEL_RECT if source_mode == "lw" else Rect(0, 0, source_width, source_height)
                crop_x0, crop_y0 = max(raw.x, bounds.x), max(raw.y, bounds.y)
                crop_x1 = min(raw.x + raw.w, bounds.x + bounds.w)
                crop_y1 = min(raw.y + raw.h, bounds.y + bounds.h)
                if crop_x1 > crop_x0 and crop_y1 > crop_y0:
                    source_crops[source_mode] = {
                        "x": crop_x0 / source_width,
                        "y": crop_y0 / source_height,
                        "width": (crop_x1 - crop_x0) / source_width,
                        "height": (crop_y1 - crop_y0) / source_height,
                    }
            media.append({"occurrenceId": oid, "assetId": str(item["fileName"]), "kind": item["kind"], "sourceSlide": source_slide, "sourceItem": source_item, "sourceModes": source_modes, "sourceCrops": source_crops, "slot": slot, "poster": thumbs.get(source_slide) or f"slide-{source_slide}.png"})
        layout_cls = classes.get(layout_slide)
        category = str(getattr(layout_cls, "category", "static"))
        video_only = bool(media and any(m["kind"] == "movie" for m in media) and not bool(getattr(layout_cls, "is_text", False)))
        warnings: list[str] = []
        if fold and any(m["kind"] == "image" for m in media):
            movie_count = sum(m["kind"] == "movie" for m in media)
            still_count = sum(m["kind"] == "image" for m in media)
            warnings.append(
                f"Source contains {movie_count} movie(s) and {still_count} still(s); "
                "no missing movie is synthesized."
            )
        if not fold and len(chain) > 1:
            warnings.append("Magic Move sequence was not proven; source slides remain explicit.")
        composition = {
            "id": f"sequence:{source_slides[0]}-{source_slides[-1]}" if fold else f"slide:{number}",
            "sourceSlides": source_slides, "layoutSlide": layout_slide, "category": category,
            "thumb": thumbs.get(layout_slide) or f"slide-{layout_slide}.png",
            "capabilities": {"videoOnly": video_only, "mask": bool(any(m["kind"] == "movie" for m in media))},
            "warnings": warnings,
            "mediaLayout": "stacked" if len(source_slides) == 1 and stacked.get(number, False) else "spatial",
            "mediaLayouts": {
                "lw": "stacked" if len(source_slides) == 1 and stacked.get(number, False) else "spatial",
                "fw": "stacked" if len(source_slides) == 1 and stacked_fw.get(number, False) else "spatial",
            },
            "media": media,
            "previewLayers": [{"kind": "media", "occurrenceId": m["occurrenceId"], "src": m["poster"], "slot": m["slot"]} for m in media],
            "decision": {"include": category != "empty" and not (content_only and bool(getattr(cls, "is_text", False))), "alignment": "inherit", "viewport": None, "source": "lw", "contentMode": "full", "masks": {}},
        }
        compositions.append(composition)
        index = cursor + 1 if fold else index + 1
    review = {"schemaVersion": SCHEMA_VERSION, "revision": 0, "source": {"path": path, "fingerprint": fingerprint}, "canvas": dict(CANVAS), "safeArea": dict(SAFE_AREA), "defaults": {"viewport": dict(DEFAULT_VIEWPORT), "alignment": "centre"}, "compositions": compositions}
    return validate_payload(review)

"""Offline per-run character style from a finalized .key IWA graph.

keynote_parser is imported lazily in _load_deck_full so the module loads without the
optional iwa extra; attach_runs raises ImportError (caller leaves runs=[]).
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from obed_edom.inspect import is_duplicate_item
from obed_edom.iwa_geometry import _path_source
from obed_edom.iwa_kindindex import _is_line

# Keynote inline-object placeholder; strip in _normalize_text (JXA vs IWA differ).
_OBJECT_REPLACEMENT = "￼"
_WHITESPACE = re.compile(r"\s+")


def _normalize_text(text: str | None) -> str:
    """Strip object-replacement and collapse whitespace; JXA objectText() and IWA storage differ."""
    if not text:
        return ""
    cleaned = text.replace(_OBJECT_REPLACEMENT, "").replace("\xa0", " ")
    return _WHITESPACE.sub(" ", cleaned).strip()


def _color_of(font_color: dict | None) -> list[int] | None:
    """IWA fontColor 0-1 floats → [r,g,b] 0-255 for highlight detection. None = not a highlight."""
    if not font_color:
        return None

    def channel(value: Any) -> int:
        return max(0, min(255, round(float(value) * 255)))

    return [
        channel(font_color.get("r", 0.0)),
        channel(font_color.get("g", 0.0)),
        channel(font_color.get("b", 0.0)),
    ]


# First value up the super.parent chain wins.
_INHERITED_PROPS = (
    "fontColor",
    "bold",
    "italic",
    "fontSize",
    "capitalization",
    "fontName",
    "superscript",
    "kerning",  # character tracking (points)
)


def resolve_style(style_id: str, objects: dict[str, dict], cache: dict) -> dict:
    """Effective CharacterStyleArchive style; first value up parent chain wins. styleName is first named ancestor.

    Colour prefers ``charProperties.tsdFill.color`` over ``fontColor`` at whichever
    ancestor first carries either: Keynote treats ``tsdFill.color`` as authoritative and
    resyncs ``fontColor`` from it on save (dsk_style postmortem, 2026-09-15) -- a
    fontColor-only offline write reverts silently, so the reader must see the same field
    a live save would.
    """
    key = str(style_id)
    if key in cache:
        return cache[key]
    props: dict[str, Any] = {}
    name: str | None = None
    cur: str | None = key
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        obj = objects.get(cur)
        if not obj:
            break
        char_props = obj.get("charProperties") or {}
        if "fontColor" not in props:
            tsd_color = (char_props.get("tsdFill") or {}).get("color")
            color_val = tsd_color if tsd_color is not None else char_props.get("fontColor")
            if color_val is not None:
                props["fontColor"] = color_val
        for prop in _INHERITED_PROPS:
            if prop == "fontColor":
                continue
            if prop not in props and prop in char_props:
                props[prop] = char_props[prop]
        sup = obj.get("super") or {}
        if name is None and sup.get("name"):
            name = sup["name"]
        parent = (sup.get("parent") or {}).get("identifier")
        cur = str(parent) if parent else None
    result = {
        "color": _color_of(props.get("fontColor")),
        "bold": bool(props.get("bold", False)),
        "italic": bool(props.get("italic", False)),
        "size": props.get("fontSize"),
        "styleName": name,
        "capitalization": props.get("capitalization"),  # raw IWA enum; "small" in cap.lower()
        "fontName": props.get("fontName"),  # often None — font lives on the paragraph style
        "superscript": props.get("superscript"),
        "tracking": props.get("kerning"),  # IWA kerning (points)
    }
    cache[key] = result
    return result


_EMPTY_STYLE = {
    "color": None,
    "bold": False,
    "italic": False,
    "size": None,
    "styleName": None,
    "capitalization": None,
    "fontName": None,
    "superscript": None,
}


# First value up ParagraphStyleArchive.super.parent wins (same walk as resolve_style).
_INHERITED_PARA_PROPS = (
    "lineSpacing",  # {amount, mode?}; mode unset = relative multiple
    "spaceBefore",
    "spaceAfter",
    "firstLineIndent",
    "leftIndent",
    "rightIndent",
    "alignment",
)


def resolve_para_style(style_id: str | None, objects: dict[str, dict], cache: dict) -> dict:
    """Paragraph metrics; first value up parent chain. Cache key para:<id> (must not collide with resolve_style)."""
    if style_id is None:
        return {}
    key = f"para:{style_id}"
    if key in cache:
        return cache[key]
    props: dict[str, Any] = {}
    cur: str | None = str(style_id)
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        obj = objects.get(cur)
        if not obj:
            break
        para_props = obj.get("paraProperties") or {}
        for prop in _INHERITED_PARA_PROPS:
            if prop not in props and prop in para_props:
                props[prop] = para_props[prop]
        parent = ((obj.get("super") or {}).get("parent") or {}).get("identifier")
        cur = str(parent) if parent else None
    cache[key] = props
    return props


def storage_runs(storage: dict, objects: dict[str, dict], cache: dict) -> list[dict]:
    """Per-run style in text order. tableCharStyle indices span concatenated storage.text."""
    text = "".join(storage.get("text") or [])
    if not text:
        return []
    entries = ((storage.get("tableCharStyle") or {}).get("entries")) or []
    points: list[tuple[int, str | None]] = []
    for entry in entries:
        obj = entry.get("object")
        sid = str(obj["identifier"]) if obj and "identifier" in obj else None
        points.append((int(entry.get("characterIndex", 0)), sid))
    points.sort(key=lambda p: p[0])
    if not points or points[0][0] != 0:
        # No char style at offset 0: fall back to the leading paragraph style.
        para = (storage.get("tableParaStyle") or {}).get("entries") or []
        sid = None
        if para:
            pobj = para[0].get("object")
            sid = str(pobj["identifier"]) if pobj and "identifier" in pobj else None
        points = [(0, sid)] + points
    runs: list[dict] = []
    for i, (start, sid) in enumerate(points):
        end = points[i + 1][0] if i + 1 < len(points) else len(text)
        chunk = text[start:end]
        if not chunk:
            continue
        style = resolve_style(sid, objects, cache) if sid else _EMPTY_STYLE
        runs.append(
            {
                "text": chunk,
                "color": style["color"],
                "bold": style["bold"],
                "italic": style["italic"],
                "size": style["size"],
                "styleName": style["styleName"],
                "capitalization": style["capitalization"],
                "fontName": style["fontName"],
                "superscript": style["superscript"],
            }
        )
    return runs


def slide_order(objects: dict[str, dict]) -> list[tuple[str, bool]]:
    """[(slideArchiveId, isSkipped)] in KN.ShowArchive.slideTree order (matches JXA, skipped included)."""
    shows = [o for o in objects.values() if o.get("_pbtype") == "KN.ShowArchive"]
    if not shows:
        return []
    out: list[tuple[str, bool]] = []
    for ref in shows[0].get("slideTree", {}).get("slides", []):
        node = objects.get(str(ref.get("identifier")))
        if not node:
            continue
        slide_id = str((node.get("slide") or {}).get("identifier"))
        out.append((slide_id, bool(node.get("isSkipped"))))
    return out


class UndecodableIWAMember(Exception):
    """Raised by _load_deck_full(strict=True) when an .iwa member fails to decode."""


def _load_deck_full(
    path: str | Path,
    *,
    strict: bool = False,
    skipped: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, dict], dict[str, str], dict[str, list[str]], set[str]]:
    """(objects, id_to_file, file_ids, header_object_references). keynote_parser imported
    lazily (optional iwa extra). ``strict`` raises UndecodableIWAMember naming the member
    instead of skipping it. When ``skipped`` is given, an undecodable member is appended as
    ``(name, repr(exc))`` instead of silently dropped."""
    from keynote_parser.codec import IWAFile  # noqa: PLC0415 (optional extra)

    objects: dict[str, dict] = {}
    id_to_file: dict[str, str] = {}
    file_ids: dict[str, list[str]] = {}
    header_object_references: set[str] = set()
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.endswith(".iwa"):
                continue
            try:
                decoded = IWAFile.from_buffer(zf.read(name), name).to_dict()
            except Exception as exc:  # noqa: BLE001 — a single bad chunk must not sink the deck
                if strict:
                    raise UndecodableIWAMember(name) from exc
                if skipped is not None:
                    skipped.append((name, repr(exc)))
                continue
            for chunk in decoded["chunks"]:
                for arch in chunk["archives"]:
                    ident = str(arch["header"]["identifier"])
                    objs = arch.get("objects") or []
                    if objs and ident not in objects:
                        objects[ident] = objs[0]
                    id_to_file.setdefault(ident, name)
                    file_ids.setdefault(name, []).append(ident)
                    for mi in arch["header"].get("messageInfos") or []:
                        for ref in mi.get("objectReferences") or []:
                            header_object_references.add(str(ref))
    return objects, id_to_file, file_ids, header_object_references


def _load_deck(
    path: str | Path, *, skipped: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, dict], dict[str, str], dict[str, list[str]]]:
    """(objects, id_to_file, file_ids). When ``skipped`` is given, an undecodable member is
    appended as ``(name, repr(exc))`` instead of silently dropped."""
    return _load_deck_full(path, skipped=skipped)[:3]


def _slide_text_objects(
    file_ids_for_slide: list[str], objects: dict[str, dict], cache: dict
) -> list[dict]:
    text_objects: list[dict] = []
    for ident in file_ids_for_slide:
        obj = objects.get(ident)
        if not obj or obj.get("_pbtype") != "TSWP.StorageArchive":
            continue
        runs = storage_runs(obj, objects, cache)
        if not runs:
            continue
        text_objects.append({"text": "".join(obj.get("text") or []), "runs": runs})
    return text_objects


def _collect_group_text(
    group_id: str,
    objects: dict[str, dict],
    cache: dict,
    seen: set[str],
    out: list[dict],
) -> None:
    """DFS GroupArchive children, text leaves only; seen prevents double-counting nested groups."""
    content: list[tuple[str, str | None, list | None]] = []
    _collect_group_content(group_id, objects, cache, None, seen, content)
    for kind, value, runs in content:
        if kind == "text":
            out.append({"text": value, "runs": runs})


def _slide_grouped_text(
    file_ids_for_slide: list[str], objects: dict[str, dict], cache: dict
) -> list[dict]:
    """Grouped {text, runs} from top-level groups only (nested reached by recursion)."""
    out: list[dict] = []
    seen: set[str] = set()
    for ident in file_ids_for_slide:
        obj = objects.get(ident)
        if not obj or obj.get("_pbtype") != "TSD.GroupArchive":
            continue
        parent = str(((obj.get("super") or {}).get("parent") or {}).get("identifier"))
        if (objects.get(parent) or {}).get("_pbtype") == "TSD.GroupArchive":
            continue  # nested group, walked via its top-level ancestor
        _collect_group_text(str(ident), objects, cache, seen, out)
    return out


def _match_runs_to_items(text_objects: list[dict], items: list[dict]) -> None:
    """Normalized-text match. Identical twins: IWA order → payload order. Unmatched stays runs=[]."""
    queues: dict[str, deque] = defaultdict(deque)
    for text_object in text_objects:
        norm = _normalize_text(text_object["text"])
        if norm:
            queues[norm].append(text_object["runs"])
    for item in items:
        if is_duplicate_item(item):
            continue
        if (item.get("kind") or "text") not in {"text", "shape"}:
            continue
        raw = item.get("text") or ""
        if not raw.strip():
            continue
        norm = _normalize_text(raw)
        queue = queues.get(norm) if norm else None
        item["runs"] = queue.popleft() if queue else []


def attach_runs(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Fill item['runs'] from IWA. ImportError if iwa extra missing. deck= reuse _load_deck tuple."""
    objects, id_to_file, file_ids = deck if deck is not None else _load_deck(key_path)
    order = slide_order(objects)
    cache: dict = {}
    iwa_by_index: dict[int, list[dict]] = {}
    grouped_by_index: dict[int, list[dict]] = {}
    for idx, (slide_id, _skipped) in enumerate(order):
        fname = id_to_file.get(slide_id)
        ids = file_ids.get(fname, [])
        iwa_by_index[idx] = _slide_text_objects(ids, objects, cache)
        grouped_by_index[idx] = _slide_grouped_text(ids, objects, cache)
    for slide in payload.get("slides") or []:
        idx = slide.get("index")
        # JXA childCount-0 grouped copy → slide.groupedText only (never items/geometry).
        grouped = grouped_by_index.get(idx)
        if grouped:
            slide["groupedText"] = grouped
        text_objects = iwa_by_index.get(idx)
        if text_objects:
            _match_runs_to_items(text_objects, slide.get("items") or [])


# Must match keynote._norm_sig_handler / sigOfGroup (linefeed) or reuse dedup misses.
_SIG_JOIN = "\n"

_MEDIA_PBTYPE_KIND = {"TSD.ImageArchive": "image", "TSD.MovieArchive": "movie"}


def _collect_group_content(
    group_id: str,
    objects: dict[str, dict],
    cache: dict,
    data_index: dict[str, str] | None,
    seen: set[str],
    out: list[tuple[str, str | None, list | None]],
) -> None:
    """DFS GroupArchive children: every child as an ordered (kind, value, runs) leaf.
    Callers with ``data_index=None`` keep only ``text`` leaves; ``value=None`` marks unresolved."""
    from obed_edom.offline_inspect import _data_identifier  # noqa: PLC0415

    if group_id in seen:
        return
    seen.add(group_id)
    group = objects.get(group_id)
    if not group:
        return
    for ref in group.get("children") or []:
        child_id = ref.get("identifier")
        if child_id is None:
            if data_index is not None:
                out.append(("unresolved", None, None))
            continue
        child_id = str(child_id)
        child = objects.get(child_id)
        if not child:
            if data_index is not None:
                out.append(("unresolved", None, None))
            continue
        ptype = child.get("_pbtype")
        if ptype == "TSD.GroupArchive":
            _collect_group_content(child_id, objects, cache, data_index, seen, out)
            continue
        media_kind = _MEDIA_PBTYPE_KIND.get(ptype)
        if media_kind is not None:
            if data_index is None:
                continue
            data_id = _data_identifier(child)
            out.append((media_kind, data_index.get(data_id) if data_id else None, None))
            continue
        if ptype != "TSWP.ShapeInfoArchive":
            if data_index is not None:
                out.append(("unknown", None, None))
            continue
        stor_id = (child.get("ownedStorage") or {}).get("identifier")
        storage = objects.get(str(stor_id)) if stor_id is not None else None
        runs = None
        text = None
        if storage and storage.get("_pbtype") == "TSWP.StorageArchive":
            runs = storage_runs(storage, objects, cache)
            if runs:
                text = "".join(storage.get("text") or [])
        if text is not None:
            out.append(("text", text, runs))
            continue
        if data_index is None:
            continue
        found = _path_source(child)
        if not found:
            out.append(("shape", None, None))
            continue
        key, sub = found
        ns = sub.get("naturalSize") or {}
        digest = hashlib.sha1(json.dumps(sub, sort_keys=True, default=str).encode()).hexdigest()[:12]
        shape_id = (
            f"{key}:{sub.get('type', '')}:{round(ns.get('width', 0), 1)}x{round(ns.get('height', 0), 1)}:{digest}"
        )
        out.append(("shape", shape_id, None))


def _group_child_signature(group_id: str, objects: dict[str, dict], cache: dict) -> str:
    """DFS-order join of normalized leaf text (not a sorted multiset; AppleScript has no code-point sort)."""
    leaves: list[dict] = []
    _collect_group_text(str(group_id), objects, cache, set(), leaves)
    parts = [n for n in (_normalize_text(leaf.get("text")) for leaf in leaves) if n]
    return _SIG_JOIN.join(parts)


def _slide_group_child_text(
    slide_archive: dict, objects: dict[str, dict], cache: dict
) -> dict[int, str]:
    """{kindIndex: childSig} for top-level groups via derive_kind_index (nested folded into ancestor)."""
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    out: dict[int, str] = {}
    for rec in derive_kind_index(slide_archive, objects):
        if rec.get("kind") != "group":
            continue
        out[int(rec["kindIndex"])] = _group_child_signature(rec["id"], objects, cache)
    return out


def attach_group_child_text(
    key_path: str | Path, payload: dict, *, deck: Any = None
) -> None:
    """Attach slide['groupChildText']. Read-only (does not touch items/geometry/groupedText)."""
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    cache: dict = {}
    gct_by_index: dict[int, dict[int, str]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        gct = _slide_group_child_text(slide_archive, objects, cache)
        if gct:
            gct_by_index[idx] = gct
    for slide in payload.get("slides") or []:
        gct = gct_by_index.get(slide.get("index"))
        if gct:
            slide["groupChildText"] = gct


def _group_content_signature(
    group_id: str, objects: dict[str, dict], cache: dict, data_index: dict[str, str]
) -> str | None:
    """DFS-order composite of tagged leaves (``text:``, ``shape:``, ``image:``, ...);
    ``None`` if any leaf's identity can't be resolved."""
    leaves: list[tuple[str, str | None, list | None]] = []
    _collect_group_content(str(group_id), objects, cache, data_index, set(), leaves)
    parts: list[str] = []
    for kind, value, _runs in leaves:
        if kind == "text":
            norm = _normalize_text(value)
            if norm:
                parts.append(f"text:{norm}")
            continue
        if value is None:
            return None
        parts.append(f"{kind}:{value}")
    return _SIG_JOIN.join(parts)


def _slide_group_content_signature(
    slide_archive: dict, objects: dict[str, dict], cache: dict, data_index: dict[str, str]
) -> dict[int, str | None]:
    """{kindIndex: contentSig} for top-level groups, complete (text + media) unlike groupChildText."""
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    out: dict[int, str | None] = {}
    for rec in derive_kind_index(slide_archive, objects):
        if rec.get("kind") != "group":
            continue
        out[int(rec["kindIndex"])] = _group_content_signature(rec["id"], objects, cache, data_index)
    return out


def attach_group_content_signature(
    key_path: str | Path, payload: dict, *, deck: Any = None
) -> None:
    """Attach slide['groupChildSignature'] (text + media identity, for mirror dedup). Read-only."""
    from obed_edom.offline_inspect import _build_data_index  # noqa: PLC0415

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    with zipfile.ZipFile(key_path) as zf:
        data_index = _build_data_index(zf.namelist())
    cache: dict = {}
    sig_by_index: dict[int, dict[int, str | None]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        sig = _slide_group_content_signature(slide_archive, objects, cache, data_index)
        if sig:
            sig_by_index[idx] = sig
    for slide in payload.get("slides") or []:
        sig = sig_by_index.get(slide.get("index"))
        if sig:
            slide["groupChildSignature"] = sig


def attach_slide_builds(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['builds'] = [{"effect","animationType","kind","kindIndex"}, ...],
    in deck_builds' record order (the slide's own ``builds`` array order, NOT reveal
    order -- every consumer treats this as a set/multiset). Read-only, mirrors
    attach_group_child_text's shape. Delegates the IWA extraction to
    iwa_builds.deck_builds (single source of truth), converting its
    1-based slide number keying to this payload's 0-based slide index."""
    from obed_edom.iwa_builds import deck_builds  # noqa: PLC0415

    by_number = deck_builds(key_path, deck=deck if deck is not None else _load_deck(key_path))
    for slide in payload.get("slides") or []:
        idx = slide.get("index")
        if idx is None:
            continue
        records = (by_number.get(idx + 1) or {}).get("builds") or []
        if records:
            slide["builds"] = [
                {
                    "effect": b["effect"],
                    "animationType": b["animationType"],
                    "kind": b["kind"],
                    "kindIndex": b["kindIndex"],
                }
                for b in records
            ]


def _is_magic_move_out(transition: dict | None) -> bool:
    """Magic Move delivering text by object; word/character delivery pairs partial strings."""
    from obed_edom.iwa_builds import _transition_effect_duration  # noqa: PLC0415

    found = _transition_effect_duration(transition)
    if not found or "magic-move" not in str(found[0] or ""):
        return False
    delivery = ((transition or {}).get("attributes") or {}).get("customTextDeliveryType")
    return delivery is None or str(delivery).endswith("ByObject")


def _data_digests(objects: dict[str, dict]) -> dict[str, str]:
    """{data id: TSP.PackageMetadata digest}."""
    out: dict[str, str] = {}
    for obj in objects.values():
        if obj.get("_pbtype") != "TSP.PackageMetadata":
            continue
        for data in obj.get("datas") or []:
            ident, digest = data.get("identifier"), data.get("digest")
            if ident is not None and digest:
                out[str(ident)] = str(digest)
    return out


def _mm_media_key(obj: dict, digests: dict[str, str]) -> str | None:
    from obed_edom.offline_inspect import _data_identifier  # noqa: PLC0415

    data_id = _data_identifier(obj)
    if data_id is None:
        return None
    return digests.get(data_id) or f"id:{data_id}"


_ROUNDED_RECT = ("kTSDRoundedRectangle", 0)
_BBOX_SOURCES = ("bezierPathSource", "editableBezierPathSource")
_MM_STYLE_PROPS = ("stroke", "opacity", "headLineEnd", "tailLineEnd")


def _coords(node: Any, axis: str, out: list[float]) -> list[float]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "naturalSize":
                continue
            if key == axis and isinstance(value, (int, float)):
                out.append(value)
            else:
                _coords(value, axis, out)
    elif isinstance(node, list):
        for value in node:
            _coords(value, axis, out)
    return out


def _canonical(node: Any, origin: tuple[float, float] = (0.0, 0.0), extent: tuple[float, float] = (1.0, 1.0)) -> Any:
    """``node`` without ``naturalSize``, x/y mapped through origin/extent, floats rounded to 1e-3."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "naturalSize":
                continue
            axis = ("x", "y").index(key) if key in ("x", "y") and isinstance(value, (int, float)) else None
            if axis is not None:
                value = (value - origin[axis]) / extent[axis]
            out[key] = _canonical(value, origin, extent)
        return out
    if isinstance(node, list):
        return [_canonical(value, origin, extent) for value in node]
    if isinstance(node, float):
        return round(node, 3) + 0.0
    return node


def _digest(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _mm_shape_key(obj: dict) -> str | None:
    """Magic Move shape gate: path-source key + preset type + digest of the path normalised to its own
    bbox (a scalar preset by its scalar, except the rounded rect's radius)."""
    found = _path_source(obj)
    if not found:
        return None
    key, sub = found
    if key == "scalarPathSource":
        shape = {} if sub.get("type") in _ROUNDED_RECT else _canonical({"scalar": sub.get("scalar")})
    elif key in _BBOX_SOURCES:
        xs, ys = _coords(sub, "x", []), _coords(sub, "y", [])
        origin = (min(xs, default=0.0), min(ys, default=0.0))
        extent = ((max(xs, default=0.0) - origin[0]) or 1.0, (max(ys, default=0.0) - origin[1]) or 1.0)
        shape = _canonical(sub, origin, extent)
    else:
        shape = _canonical(sub)
    return f"{key}:{sub.get('type', '')}:{_digest(shape)}"


def _style_id(obj: dict) -> str | None:
    ref = (obj.get("super") or {}).get("style")
    ident = ref.get("identifier") if isinstance(ref, dict) else None
    return str(ident) if ident is not None else None


def _mm_shape_style(obj: dict, objects: dict[str, dict]) -> dict:
    """Stroke (None when empty), opacity and line ends, first value up the ShapeStyleArchive parent chain."""
    found: dict[str, Any] = {}
    cur = _style_id(obj)
    seen: set[str] = set()
    for _ in range(8):
        if cur is None or cur in seen or not objects.get(cur):
            break
        seen.add(cur)
        sup = objects[cur].get("super") or {}
        props = sup.get("shapeProperties") or {}
        for name in _MM_STYLE_PROPS:
            if name not in found and name in props:
                found[name] = props[name]
        parent = ((sup.get("super") or {}).get("parent") or {}).get("identifier")
        cur = str(parent) if parent is not None else None
    stroke = found.get("stroke") or {}
    empty = (stroke.get("pattern") or {}).get("type") in (None, "TSDEmptyPattern")
    opacity = found.get("opacity")
    return {
        "stroke": None if empty else {k: stroke.get(k) for k in ("color", "width", "pattern")},
        "opacity": 1.0 if opacity is None else float(opacity),
        "headLineEnd": found.get("headLineEnd") or None,
        "tailLineEnd": found.get("tailLineEnd") or None,
    }


def _mm_prefs(obj: dict, objects: dict[str, dict]) -> list[str]:
    """[resolved stroke + opacity, raw path source, style id] -- Magic Move's preference tiers."""
    style = _mm_shape_style(obj, objects)
    found = _path_source(obj)
    return [
        _digest(_canonical({"stroke": style["stroke"], "opacity": style["opacity"]})),
        _digest(_canonical(found[1] if found else None)),
        _style_id(obj) or "",
    ]


def _mm_line_key(obj: dict, objects: dict[str, dict]) -> str | None:
    """Magic Move line gate: the shape gate plus the resolved stroke and line ends."""
    gate = _mm_shape_key(obj)
    if gate is None:
        return None
    style = _mm_shape_style(obj, objects)
    ends = {k: style[k] for k in ("stroke", "headLineEnd", "tailLineEnd")}
    return f"line:{gate}:{_digest(_canonical(ends))}"


def _mm_group_leaves(
    group_id: str, objects: dict[str, dict], digests: dict[str, str], seen: set[str], out: list[str]
) -> bool:
    """``_collect_group_content``'s DFS with media by digest, lines by ``_mm_line_key`` and
    shapes by ``_mm_shape_key``. False if any leaf is unresolvable."""
    if group_id in seen:
        return True
    seen.add(group_id)
    group = objects.get(group_id)
    if not group:
        return False
    for ref in group.get("children") or []:
        child_id = ref.get("identifier")
        child = objects.get(str(child_id)) if child_id is not None else None
        if not child:
            return False
        ptype = child.get("_pbtype")
        if ptype == "TSD.GroupArchive":
            if not _mm_group_leaves(str(child_id), objects, digests, seen, out):
                return False
            continue
        media_kind = _MEDIA_PBTYPE_KIND.get(ptype)
        if media_kind is not None:
            media = _mm_media_key(child, digests)
            if media is None:
                return False
            out.append(f"{media_kind}:{media}")
            continue
        if ptype != "TSWP.ShapeInfoArchive":
            return False
        if _is_line(child):
            line = _mm_line_key(child, objects)
            if line is None:
                return False
            out.append(line)
            continue
        stor_id = (child.get("ownedStorage") or {}).get("identifier")
        storage = objects.get(str(stor_id)) if stor_id is not None else None
        text = "".join(storage.get("text") or []) if storage and storage.get("_pbtype") == "TSWP.StorageArchive" else ""
        if text:
            norm = _normalize_text(text)
            if norm:
                out.append(f"text:{norm}")
            continue
        shape = _mm_shape_key(child)
        if shape is None:
            return False
        out.append(f"shape:{shape}")
    return True


def _mm_identity(rec: dict, objects: dict[str, dict], digests: dict[str, str]) -> str | None:
    """Content identity Keynote's Magic Move pairs on; None never matches."""
    kind = rec["kind"]
    obj = objects.get(str(rec["id"])) or {}
    if kind == "text":
        norm = _normalize_text(rec.get("text"))
        return f"text:{norm}" if norm else None
    if kind in ("image", "movie"):
        media = _mm_media_key(obj, digests)
        return f"{kind}:{media}" if media else None
    if kind == "shape":
        if rec.get("duplicateOf"):
            return None
        shape = _mm_shape_key(obj)
        if shape is None:
            return None
        norm = _normalize_text(rec.get("text"))
        return f"shape:{shape}" + (f"{_SIG_JOIN}text:{norm}" if norm else "")
    if kind == "group":
        leaves: list[str] = []
        if not _mm_group_leaves(str(rec["id"]), objects, digests, set(), leaves) or not leaves:
            return None
        return "group:" + _SIG_JOIN.join(leaves)
    if kind == "line":
        return _mm_line_key(obj, objects)
    return None


def attach_magic_move(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['magicMoveOut'] = True when the slide's transition out is a by-object
    Magic Move, and slide['mmKeys'] = {kind: {kindIndex: key}} plus slide['mmOrder'] ([kind, kindIndex]
    addresses back→front, one per keyable drawable) on both slides of each such pair. Keyed shapes and lines
    also get slide['mmPrefs'] = {kind: {kindIndex: [stroke+opacity, raw path, style id]}} (``_mm_prefs``).
    Keyed addresses whose drawable builds in / out (``_appearance_builds``) are listed in slide['mmBuildIn'] /
    slide['mmBuildOut']; Magic Move pairs neither as a destination / source. All-or-nothing: prior fields are
    cleared first and written only after every slide is keyed. Read-only; transitions and builds come from
    iwa_builds.deck_builds."""
    slides = payload.get("slides") or []
    for slide in slides:
        slide.pop("magicMoveOut", None)
        slide.pop("mmKeys", None)
        slide.pop("mmOrder", None)
        slide.pop("mmPrefs", None)
        slide.pop("mmBuildIn", None)
        slide.pop("mmBuildOut", None)
    from obed_edom.iwa_builds import deck_builds  # noqa: PLC0415
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    deck = deck if deck is not None else _load_deck(key_path)
    objects = deck[0]
    by_number = deck_builds(key_path, deck=deck)
    mm_out = {number - 1 for number, rec in by_number.items() if _is_magic_move_out(rec.get("transition"))}
    paired = mm_out | {idx + 1 for idx in mm_out}
    order = slide_order(objects)
    digests = _data_digests(objects)
    staged: list[tuple[dict, bool, dict[str, dict[int, str]], list[list], dict[str, dict[int, list[str]]], dict]] = []
    for slide in slides:
        idx = slide.get("index")
        if idx is None:
            continue
        keys: dict[str, dict[int, str]] = {}
        stacked: dict[int, list] = {}
        prefs: dict[str, dict[int, list[str]]] = {}
        built: dict[str, list[list]] = {}
        slide_archive = objects.get(order[idx][0]) if idx in paired and 0 <= idx < len(order) else None
        if slide_archive is not None:
            z_pos = {
                str(ref.get("identifier")): pos
                for pos, ref in enumerate(slide_archive.get("drawablesZOrder") or [])
            }
            records = derive_kind_index(slide_archive, objects)
            build_ids = _appearance_builds((by_number.get(idx + 1) or {}).get("builds") or [], records)
            for rec in records:
                key = _mm_identity(rec, objects, digests)
                if key is not None:
                    keys.setdefault(rec["kind"], {})[int(rec["kindIndex"])] = key
                    stacked.setdefault(z_pos[rec["id"]], [rec["kind"], int(rec["kindIndex"])])
                    if rec["kind"] in ("shape", "line"):
                        prefs.setdefault(rec["kind"], {})[int(rec["kindIndex"])] = _mm_prefs(
                            objects[str(rec["id"])], objects
                        )
                    for field, ids in build_ids.items():
                        if rec["id"] in ids:
                            built.setdefault(field, []).append([rec["kind"], int(rec["kindIndex"])])
        staged.append((slide, idx in mm_out, keys, [stacked[pos] for pos in sorted(stacked)], prefs, built))
    for slide, out, keys, mm_order, prefs, built in staged:
        if out:
            slide["magicMoveOut"] = True
        if keys:
            slide["mmKeys"] = keys
            slide["mmOrder"] = mm_order
        if prefs:
            slide["mmPrefs"] = prefs
        slide.update(built)


def _appearance_builds(builds: list[dict], records: list[dict]) -> dict[str, set[str]]:
    """Drawable ids with a build-in / build-out, as {"mmBuildIn": ids, "mmBuildOut": ids}. A movie's
    ``apple:movie-start`` only plays it and actions only animate it, so neither counts."""
    ids = {(rec["kind"], int(rec["kindIndex"])): rec["id"] for rec in records}
    out: dict[str, set[str]] = {"mmBuildIn": set(), "mmBuildOut": set()}
    for build in builds:
        field = {"In": "mmBuildIn", "Out": "mmBuildOut"}.get(build.get("animationType"))
        drawable = ids.get((build.get("kind"), int(build.get("kindIndex"))))
        if field is None or drawable is None or build.get("effect") == "apple:movie-start":
            continue
        out[field].add(drawable)
    return out


def attach_magic_move_if_available(key_path: str | Path, payload: dict) -> None:
    """``attach_magic_move`` for validation: an unreadable deck (no iwa extra, not a .key)
    leaves no Magic Move fields, so mm.zorder_flip stays silent."""
    try:
        attach_magic_move(key_path, payload)
    except Exception:  # noqa: BLE001
        pass


def _single_text_leaf(group_id: str, objects: dict[str, dict]) -> dict | None:
    """This group's one non-empty text leaf (direct or nested); None if zero or more than one."""
    found: list[dict] = []
    seen: set[str] = set()

    def walk(gid: str) -> bool:
        if gid in seen:
            return True
        seen.add(gid)
        group = objects.get(gid)
        if not group:
            return True
        for ref in group.get("children") or []:
            child_id = ref.get("identifier")
            if child_id is None:
                continue
            child_id = str(child_id)
            child = objects.get(child_id)
            if not child:
                continue
            ptype = child.get("_pbtype")
            if ptype == "TSD.GroupArchive":
                if not walk(child_id):
                    return False
                continue
            if ptype != "TSWP.ShapeInfoArchive":
                continue
            stor_id = (child.get("ownedStorage") or {}).get("identifier")
            if stor_id is None:
                continue
            storage = objects.get(str(stor_id))
            if not storage or storage.get("_pbtype") != "TSWP.StorageArchive":
                continue
            # _normalize_text (not a bare .strip()) so an object-replacement-only leaf
            # (e.g. an inline image placeholder) counts as empty here exactly like it
            # does in _group_child_signature — otherwise the two sources can disagree
            # on "single leaf" and a real card silently loses its groupCaption record.
            if not _normalize_text("".join(storage.get("text") or [])):
                continue
            found.append(child)
            if len(found) > 1:
                return False
        return True

    if not walk(group_id) or len(found) != 1:
        return None
    return found[0]


def attach_group_captions(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['groupCaption'] = {kindIndex: {text, groupW, boxW, boxH, inset, font,
    size, tracking, bold, italic}} for top-level groups with exactly one non-empty text
    leaf. Read-only, mirrors attach_group_child_text's shape."""
    from obed_edom.iwa_geometry import _geom_dict, _xywha  # noqa: PLC0415
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415
    from obed_edom.iwa_text_shape import shape_padding, shape_style  # noqa: PLC0415

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    cache: dict = {}
    caps_by_index: dict[int, dict[int, dict]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        caps: dict[int, dict] = {}
        for rec in derive_kind_index(slide_archive, objects):
            if rec.get("kind") != "group":
                continue
            group_obj = objects.get(str(rec["id"]))
            if not group_obj:
                continue
            leaf = _single_text_leaf(str(rec["id"]), objects)
            if leaf is None:
                continue
            style = shape_style(leaf, objects, cache)
            if style is None or not style.font_name or not style.size:
                continue
            stor_id = (leaf.get("ownedStorage") or {}).get("identifier")
            storage = objects.get(str(stor_id)) if stor_id is not None else None
            text = "".join((storage or {}).get("text") or [])
            _gx, _gy, group_w, _gh, _ga = _xywha(_geom_dict(group_obj))
            _lx, _ly, box_w, box_h, _la = _xywha(_geom_dict(leaf))
            caps[int(rec["kindIndex"])] = {
                "text": text,
                "groupW": group_w,
                "boxW": box_w,
                "boxH": box_h,
                "inset": shape_padding(leaf, objects, cache),
                "font": style.font_name,
                "size": style.size,
                "tracking": style.tracking,
                "bold": style.bold,
                "italic": style.italic,
            }
        if caps:
            caps_by_index[idx] = caps
    for slide in payload.get("slides") or []:
        caps = caps_by_index.get(slide.get("index"))
        if caps:
            slide["groupCaption"] = caps


def _is_autosize_text_child(pbtype: str | None, kinds: list[str], ch: float) -> bool:
    """Shared with `attach_group_autosize` so the two callers cannot drift.

    ch == 0.0 alone also matches a zero-height LINE child (legitimately h == 0, a
    hairline divider): "text" in kinds is what actually marks an autosize text box.
    """
    return pbtype == "TSWP.ShapeInfoArchive" and ch == 0.0 and "text" in kinds


def _group_child_records(group_obj: dict, objects: dict[str, dict]) -> list[dict] | None:
    """Per-child AppleScript address + SOURCE-deck geometry for a flat group, else None.

    None = "keep today's absolute group write". Only a group holding an autosize text box
    needs this: a Keynote group resize is an aspect-locked uniform scale about the group's
    LIVE frame, and after the canvas resize that frame is the union of a word-wrapped
    autosize child (measured 69x261 for a 278x88 badge). The resize also freezes the child
    wrapped for ever, so the children must be written instead of the group.
    Autosize children carry `cy` (their geometry.y IS the vertical centre) and naturalSize.
    """
    from obed_edom.iwa_geometry import (  # noqa: PLC0415
        _geom_dict, _leaf_bbox, _mask_geom, _masked_rect, _natural_size, _xywha,
    )
    from obed_edom.iwa_kindindex import _memberships  # noqa: PLC0415

    gx, gy, _gw, _gh, gangle = _xywha(_geom_dict(group_obj))
    if gangle % 360.0:
        return None
    counters: dict[str, int] = {}
    out: list[dict] = []
    autosize_seen = False
    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        child = objects.get(str(cid)) if cid is not None else None
        if child is None or child.get("_pbtype") == "TSD.GroupArchive":
            return None  # nested group: same aspect-lock problem one level down
        kinds = _memberships(child)
        if not kinds:
            return None
        assigned: dict[str, int] = {}
        for kind in kinds:  # identical counter rule to derive_kind_index
            assigned[kind] = counters.get(kind, 0)
            counters[kind] = assigned[kind] + 1
        geom = _geom_dict(child)
        cx, cy, cw, ch, ca = _xywha(geom)
        if ca % 360.0:
            return None
        if (child.get("mask") or {}).get("identifier") is not None:
            mask_geom = _mask_geom(child, objects)
            if not mask_geom:
                return None
            _rect, off_axis = _masked_rect(geom, mask_geom)
            if off_axis:
                return None
        if _is_autosize_text_child(child.get("_pbtype"), kinds, ch):
            nw, nh = _natural_size(child)
            if nw <= 0 or nh <= 0:
                return None
            # The frame width (cw) is read from the same pristine source-deck archive;
            # naturalSize is documented stale elsewhere (_autosize_rect) and disagreeing
            # with the live frame width means one of them does not describe this text
            # any more — refuse rather than write a box the wrong width.
            if cw > 0 and abs(cw - nw) > 0.01 * nw:
                return None
            autosize_seen = True
            out.append({
                "kind": "text", "kindIndex": assigned["text"], "autosize": True,
                "x": gx + cx, "cy": gy + cy, "y": gy + cy - nh / 2.0, "w": nw, "h": nh,
            })
            continue
        kind = "shape" if "shape" in assigned else kinds[0]
        x0, y0, x1, y1 = _leaf_bbox(child, gx, gy, objects)
        out.append({
            "kind": kind, "kindIndex": assigned[kind], "autosize": False,
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
        })
    return out if autosize_seen else None


def attach_group_children(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['groupChildren'] = {kindIndex: [child record, ...]} for top-level
    groups holding an autosize text box. Read-only; mirrors attach_group_captions.
    Skips any slide already marked `groupChildrenUnavailable` (a JXA-fallback slide
    merged into an otherwise offline payload) — its group rects are live union
    frames, not archive offsets."""
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    kids_by_index: dict[int, dict[int, list[dict]]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        kids: dict[int, list[dict]] = {}
        for rec in derive_kind_index(slide_archive, objects):
            if rec.get("kind") != "group":
                continue
            group_obj = objects.get(str(rec["id"]))
            if not group_obj:
                continue
            records = _group_child_records(group_obj, objects)
            if records:
                kids[int(rec["kindIndex"])] = records
        if kids:
            kids_by_index[idx] = kids
    for slide in payload.get("slides") or []:
        if slide.get("groupChildrenUnavailable"):
            continue
        kids = kids_by_index.get(slide.get("index"))
        if kids:
            slide["groupChildren"] = kids


def _group_child_runs(group_obj: dict, objects: dict[str, dict], cache: dict) -> dict[int, dict] | None:
    """{child kindIndex: {text, font, size, runs}} for a flat top-level group's
    text-bearing children -- keyed by the SAME per-kind kindIndex counters and
    kind-preference rule (`"shape" if "shape" in assigned else kinds[0]`) as
    `_group_child_records`, so a child's key here always matches its `groupChildren`
    entry, dual shape+text child (a custom-path pill badge) included: it is addressed
    as `"shape"` there and must be keyed by `assigned["shape"]`, not `assigned["text"]`,
    else its caption is invisible to callers keying off the shape's kindIndex. `None`
    for a nested group."""
    from obed_edom.iwa_kindindex import _memberships  # noqa: PLC0415
    from obed_edom.offline_inspect import _item_text_style  # noqa: PLC0415

    counters: dict[str, int] = {}
    out: dict[int, dict] = {}
    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        child = objects.get(str(cid)) if cid is not None else None
        if child is None or child.get("_pbtype") == "TSD.GroupArchive":
            return None
        kinds = _memberships(child)
        if not kinds:
            return None
        assigned: dict[str, int] = {}
        for kind in kinds:
            assigned[kind] = counters.get(kind, 0)
            counters[kind] = assigned[kind] + 1
        kind = "shape" if "shape" in assigned else kinds[0]
        if "text" not in assigned or child.get("_pbtype") != "TSWP.ShapeInfoArchive":
            continue
        stor_id = (child.get("ownedStorage") or {}).get("identifier")
        storage = objects.get(str(stor_id)) if stor_id is not None else None
        if not storage or storage.get("_pbtype") != "TSWP.StorageArchive":
            continue
        runs = storage_runs(storage, objects, cache)
        if not runs:
            continue
        text = "".join(storage.get("text") or [])
        font, size, _color = _item_text_style(child, objects, cache)
        out[assigned[kind]] = {"text": text, "font": font, "size": size, "runs": runs}
    return out or None


def attach_group_child_runs(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['groupChildRuns'] = {group kindIndex: {child kindIndex: {text, font,
    size, runs}}} for top-level groups' text children. Read-only; keyed by kindIndex so
    two identical groups on one slide (GW 50/51) keep separate entries -- never matched
    back by text equality."""
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    cache: dict = {}
    runs_by_index: dict[int, dict[int, dict]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        groups: dict[int, dict] = {}
        for rec in derive_kind_index(slide_archive, objects):
            if rec.get("kind") != "group":
                continue
            group_obj = objects.get(str(rec["id"]))
            if not group_obj:
                continue
            children = _group_child_runs(group_obj, objects, cache)
            if children:
                groups[int(rec["kindIndex"])] = children
        if groups:
            runs_by_index[idx] = groups
    for slide in payload.get("slides") or []:
        groups = runs_by_index.get(slide.get("index"))
        if groups:
            slide["groupChildRuns"] = groups


def _group_has_autosize_descendant(group_obj: dict, objects: dict[str, dict]) -> bool:
    from obed_edom.iwa_geometry import _geom_dict, _xywha  # noqa: PLC0415
    from obed_edom.iwa_kindindex import _memberships  # noqa: PLC0415

    for ref in group_obj.get("children") or []:
        cid = ref.get("identifier")
        child = objects.get(str(cid)) if cid is not None else None
        if child is None:
            continue
        if child.get("_pbtype") == "TSD.GroupArchive":
            if _group_has_autosize_descendant(child, objects):
                return True
            continue
        _cx, _cy, _cw, ch, _ca = _xywha(_geom_dict(child))
        if _is_autosize_text_child(child.get("_pbtype"), _memberships(child), ch):
            return True
    return False


def attach_group_autosize(key_path: str | Path, payload: dict, *, deck: Any = None) -> None:
    """Attach slide['groupAutosize'] = {kindIndex: True, ...} for top-level groups holding
    an autosize text descendant, regardless of nesting or reader. Whether a group holds an
    autosize text box is a property of the archive, not the coordinate space, so it stays
    valid whichever reader produced the payload — unlike `groupChildren`, which needs
    offline geometry. A group `_group_child_records` refuses (nested group, rotation, mask,
    stale naturalSize) is exactly the case that must still be marked here."""
    from obed_edom.iwa_kindindex import derive_kind_index  # noqa: PLC0415

    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(key_path)
    marks_by_index: dict[int, dict[int, bool]] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide_archive = objects.get(slide_id)
        if slide_archive is None:
            continue
        marks: dict[int, bool] = {}
        for rec in derive_kind_index(slide_archive, objects):
            if rec.get("kind") != "group":
                continue
            group_obj = objects.get(str(rec["id"]))
            if not group_obj:
                continue
            if _group_has_autosize_descendant(group_obj, objects):
                marks[int(rec["kindIndex"])] = True
        if marks:
            marks_by_index[idx] = marks
    for slide in payload.get("slides") or []:
        marks = marks_by_index.get(slide.get("index"))
        if marks:
            slide["groupAutosize"] = marks

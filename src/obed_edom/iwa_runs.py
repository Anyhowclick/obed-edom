"""Offline per-run character style from a finalized .key IWA graph.

keynote_parser is imported lazily in _load_deck so the module loads without the
optional iwa extra; attach_runs raises ImportError (caller leaves runs=[]).
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from obed_edom.inspect import is_duplicate_item

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
    """Effective CharacterStyleArchive style; first value up parent chain wins. styleName is first named ancestor."""
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
        for prop in _INHERITED_PROPS:
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


def _load_deck(path: str | Path) -> tuple[dict[str, dict], dict[str, str], dict[str, list[str]]]:
    """(objects, id_to_file, file_ids). keynote_parser imported lazily (optional iwa extra)."""
    from keynote_parser.codec import IWAFile  # noqa: PLC0415 (optional extra)

    objects: dict[str, dict] = {}
    id_to_file: dict[str, str] = {}
    file_ids: dict[str, list[str]] = {}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.endswith(".iwa"):
                continue
            try:
                decoded = IWAFile.from_buffer(zf.read(name), name).to_dict()
            except Exception:  # noqa: BLE001 — a single bad chunk must not sink the deck
                continue
            for chunk in decoded["chunks"]:
                for arch in chunk["archives"]:
                    ident = str(arch["header"]["identifier"])
                    objs = arch.get("objects") or []
                    if objs and ident not in objects:
                        objects[ident] = objs[0]
                    id_to_file.setdefault(ident, name)
                    file_ids.setdefault(name, []).append(ident)
    return objects, id_to_file, file_ids


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
    """DFS GroupArchive children; seen prevents double-counting nested groups."""
    if group_id in seen:
        return
    seen.add(group_id)
    group = objects.get(group_id)
    if not group:
        return
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
            _collect_group_text(child_id, objects, cache, seen, out)
            continue
        if ptype != "TSWP.ShapeInfoArchive":
            continue
        stor_id = (child.get("ownedStorage") or {}).get("identifier")
        if stor_id is None:
            continue
        storage = objects.get(str(stor_id))
        if not storage or storage.get("_pbtype") != "TSWP.StorageArchive":
            continue
        runs = storage_runs(storage, objects, cache)
        if not runs:
            continue
        out.append({"text": "".join(storage.get("text") or []), "runs": runs})


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

"""Offline per-run character style, lifted out of a finalized ``.key``'s IWA graph.

The JXA inspect pass reports each text item's plain string but no per-run style, so
``item["runs"]`` is always ``[]`` and the consumers that read it
(``validate._highlight_punctuation_flags``, ``inspect.highlighted_markup``,
``validate._inspect_item_font_size``, ``diff_keynotes._smallcaps_signature``) stay
dark on finalized decks. This module decodes the deck's ``Index/*.iwa`` objects
(Snappy + Protobuf, no Keynote/JXA involvement), pulls the real per-run colour /
weight / size / small-caps straight out of the character-style graph, and attaches
them to the matching payload items.

Public entry point: :func:`attach_runs`, which mutates ``item["runs"]`` in place.

``keynote_parser`` is imported LAZILY (inside :func:`_load_deck`) so that a base
install without the optional ``iwa`` extra can still import this module — the
pure matcher and style resolver below stay unit-testable with no parser present,
and :func:`attach_runs` simply raises ``ImportError`` (caught by the caller, runs
stay ``[]``) when the extra is absent.
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from obed_edom.inspect import is_duplicate_item

# Object-replacement char Keynote emits for an inline object (e.g. a slide-number
# field); it appears in both IWA and JXA text but is not real copy.
_OBJECT_REPLACEMENT = "￼"  # ￼
_WHITESPACE = re.compile(r"\s+")


def _normalize_text(text: str | None) -> str:
    """Fold the differences between JXA ``objectText()`` and IWA storage text.

    Both sides carry paragraph/soft breaks (``\\n``, ``\\u2028``), non-breaking
    spaces and the ``￼`` inline-object placeholder, but not identically, so text
    equality has to compare after stripping ``￼`` and collapsing every run of
    whitespace (``\\s`` covers ``\\n``, ``\\u2028``, ``\\xa0``, plain spaces) to a
    single space, then trimming the ends.
    """
    if not text:
        return ""
    cleaned = text.replace(_OBJECT_REPLACEMENT, "").replace("\xa0", " ")
    return _WHITESPACE.sub(" ", cleaned).strip()


# --------------------------------------------------------------------------
# Character-style resolution, with inheritance up the super.parent chain.
# --------------------------------------------------------------------------
def _color_of(font_color: dict | None) -> list[int] | None:
    """IWA ``fontColor`` is 0-1 floats; return ``[r, g, b]`` 0-255 ints, or None.

    Normalizing to 0-255 here lets the value drop straight into
    ``inspect._looks_highlight`` (which reads ``color[0..2]`` and picks a 255-vs-
    65535 scale). No ``fontColor`` anywhere up the chain -> None, i.e. an inherited
    / theme colour, which is correctly "not a highlight".
    """
    if not font_color:
        return None

    def channel(value: Any) -> int:
        return max(0, min(255, round(float(value) * 255)))

    return [
        channel(font_color.get("r", 0.0)),
        channel(font_color.get("g", 0.0)),
        channel(font_color.get("b", 0.0)),
    ]


# charProperties keys we inherit; the first value seen up the chain wins.
_INHERITED_PROPS = (
    "fontColor",
    "bold",
    "italic",
    "fontSize",
    "capitalization",
    "fontName",
    "superscript",
)


def resolve_style(style_id: str, objects: dict[str, dict], cache: dict) -> dict:
    """Effective run style for a ``CharacterStyleArchive`` id, following inheritance.

    A run's char style typically carries only its overrides (say bold + fontColor)
    plus a ``super.parent`` pointing at a base style, so we walk the parent chain
    and take the FIRST value seen for each property. ``styleName`` is the first
    named ancestor (``super.name``) — the human label ("Verse Number", "Highlight").
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
        for prop in _INHERITED_PROPS:
            if prop not in props and prop in char_props:
                props[prop] = char_props[prop]
        sup = obj.get("super") or {}
        if name is None and sup.get("name"):
            name = sup["name"]
        parent = (sup.get("parent") or {}).get("identifier")
        cur = str(parent) if parent else None
    result = {
        "color": _color_of(props.get("fontColor")),  # [r,g,b] 0-255 or None
        "bold": bool(props.get("bold", False)),
        "italic": bool(props.get("italic", False)),
        "size": props.get("fontSize"),
        "styleName": name,
        # Raw IWA capitalization enum string (e.g. "kSmallCaps") or None.
        # diff_keynotes._smallcaps_signature reads it via `"small" in cap.lower()`.
        "capitalization": props.get("capitalization"),
        # PostScript font name (charProperties.fontName); OFTEN None because the
        # font usually lives on the paragraph style, not the char style. None =
        # inherited, which is correct and additive — no consumer requires it.
        "fontName": props.get("fontName"),
        # Raw IWA superscript enum string (e.g. "kSuperscript") or None; inherited
        # via the same parent walk (the GW verse-number style resolves directly).
        "superscript": props.get("superscript"),
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


def storage_runs(storage: dict, objects: dict[str, dict], cache: dict) -> list[dict]:
    """Per-run style for one ``TSWP.StorageArchive``, in text order.

    ``storage.text`` is the paragraph string(s); character indices in
    ``tableCharStyle.entries`` run across their concatenation. Each entry
    ``{characterIndex, object:{identifier}}`` starts a run at that offset with that
    char-style id, running until the next entry's offset.
    """
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
        # No char-style coverage from offset 0: fall back to the paragraph style's
        # implied char run for the leading span.
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
                "color": style["color"],  # [r,g,b] 0-255 or None
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


# --------------------------------------------------------------------------
# Slide order + slide->file, straight from the show's slide tree.
# --------------------------------------------------------------------------
def slide_order(objects: dict[str, dict]) -> list[tuple[str, bool]]:
    """Ordered ``[(slideArchiveId, isSkipped)]`` in presentation order.

    ``KN.ShowArchive.slideTree.slides`` is the ordered list of
    ``KN.SlideNodeArchive`` ids; each node's ``slide.identifier`` is the
    ``KN.SlideArchive`` whose text/shape objects live in ``Index/Slide-<id>.iwa``.
    This is exactly the order ``document.slides()`` (hence inspect_keynote.js)
    walks, so position i here == the payload slide's true ``index`` (skipped
    slides included).
    """
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


# --------------------------------------------------------------------------
# Decode every IWA in the deck into a flat id -> object map (lazy parser import).
# --------------------------------------------------------------------------
def _load_deck(path: str | Path) -> tuple[dict[str, dict], dict[str, str], dict[str, list[str]]]:
    """Return ``(objects, id_to_file, file_ids)`` for a ``.key``.

    ``objects[id]`` is the first protobuf object of the archive with that id;
    every archive header carries an ``identifier`` and every cross-reference is
    ``{identifier: N}``, so one flat map across ALL ``Index/*.iwa`` files is the
    whole id-resolution mechanism (a char-style ref in a slide file resolves
    against the same map that holds DocumentStylesheet.iwa's style archives).

    ``keynote_parser`` is imported here, lazily, so the module imports without the
    optional ``iwa`` extra installed.
    """
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
    """Extracted ``{text, runs}`` for every non-empty text storage on one slide,
    in IWA (file) order."""
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


# --------------------------------------------------------------------------
# Grouped text: recurse a slide's group subtrees for copy JXA can't see.
# --------------------------------------------------------------------------
def _collect_group_text(
    group_id: str,
    objects: dict[str, dict],
    cache: dict,
    seen: set[str],
    out: list[dict],
) -> None:
    """Depth-first walk of one ``TSD.GroupArchive`` subtree, collecting text.

    ``GroupArchive.children`` is a list of ``{identifier}`` refs to either nested
    ``TSD.GroupArchive`` (recurse) or ``TSWP.ShapeInfoArchive`` whose
    ``ownedStorage`` points at the ``TSWP.StorageArchive`` holding the copy. ``seen``
    guards against a group reached twice (a nested group is only walked once, from
    its parent) so grouped storages aren't double-counted.
    """
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
    """Grouped ``{text, runs}`` for one slide, from its top-level group subtrees.

    Only TOP-LEVEL groups are seeded (parent is the slide, not another group);
    nested groups are reached by recursion, so each grouped storage is collected
    exactly once. Read-only: it never touches ``items``/``children``/``childCount``
    or any geometry, so the resize plan sees exactly today's payload.
    """
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


# --------------------------------------------------------------------------
# Match IWA text objects -> inspect items and attach runs.
# --------------------------------------------------------------------------
def _match_runs_to_items(text_objects: list[dict], items: list[dict]) -> None:
    """Attach each text object's runs to the payload item with the same text.

    MVP matching is normalized-text equality. For identical-text twins on one
    slide (e.g. two wall boxes with the same copy) the text objects are handed
    out in IWA order to the matching items in payload order — a per-item geometry
    tiebreak (``TSWP.ShapeInfoArchive.ownedStorage`` ->
    ``shape.super.super.geometry`` vs the item's x/y/w/h) is a DEFERRED
    enhancement: that archive path is unverified against a real deck, so shipping
    it unproven would risk mis-assignment. A candidate item with no matching text
    object is left with ``runs = []`` (never crash, never mis-assign).
    """
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


def attach_runs(key_path: str | Path, payload: dict) -> None:
    """Populate ``item["runs"]`` in an inspect payload from the deck's IWA graph.

    Read-only, best-effort. Raises ``ImportError`` if the ``iwa`` extra is absent
    (the caller catches it), and simply leaves ``runs = []`` for any item it can't
    confidently match.
    """
    objects, id_to_file, file_ids = _load_deck(key_path)
    order = slide_order(objects)
    cache: dict = {}
    # Full deck: true slide index -> that slide's text objects. Keyed by position
    # in the show's slide tree so a RANGED inspect (which ships only a subset of
    # slides, each carrying its true `index`) still looks up the right slide.
    iwa_by_index: dict[int, list[dict]] = {}
    grouped_by_index: dict[int, list[dict]] = {}
    for idx, (slide_id, _skipped) in enumerate(order):
        fname = id_to_file.get(slide_id)
        ids = file_ids.get(fname, [])
        iwa_by_index[idx] = _slide_text_objects(ids, objects, cache)
        grouped_by_index[idx] = _slide_grouped_text(ids, objects, cache)
    for slide in payload.get("slides") or []:
        idx = slide.get("index")
        # Grouped copy JXA reports as childCount 0 -> a NEW slide-level field, read
        # ONLY by the checker's text-scoring path. Never mutates items/geometry.
        grouped = grouped_by_index.get(idx)
        if grouped:
            slide["groupedText"] = grouped
        text_objects = iwa_by_index.get(idx)
        if text_objects:
            _match_runs_to_items(text_objects, slide.get("items") or [])

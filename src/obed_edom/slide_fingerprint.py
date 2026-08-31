"""INERT save-churn-immune content key for a finalized ``.key`` deck.

Nothing consumes this module yet. It exists so a *later* incremental lever
(``l5-bulk-cache`` / ``incremental-previews``) can cache bulk-geometry rows and
per-slide previews for slides Keynote did NOT edit, and re-read only the ones that
changed. The whole value here is the keying scheme's correctness — over-inclusion
costs only a cache miss, never a stale serve, so every doubtful input stays IN the
key and the few genuinely-unsafe conditions surface a slide as *uncacheable*.

Raw byte keys are dead: every no-op open+save recompresses and RENUMBERS the object
ids across the deck's ``Index/*.iwa`` files, so a byte hash of a slide's file (or of
the global files) churns on every save. This module instead hashes the DECODED,
id-NORMALIZED object graph:

* **Per-slide key** — a BFS closure from the slide's ``KN.SlideArchive``, following
  only NUMERIC ``{identifier: N}`` refs (a string ``identifier`` is a style *name*,
  kept verbatim as content). Each visited object is emitted in BFS *discovery* order
  with its header id dropped and every numeric ref rewritten to a positional
  ``{"@ref": <discovery-index>}`` token — so a save's id-renumber washes out while an
  actual content edit still moves the key. An asset ref (image/movie ``data``) folds
  in as ``{"@data": "<CRC>:<size>"}`` from the zip central directory, capturing the
  media bytes without ever reading them. The document position and skip flag are
  mixed into the hash so a reorder / show-hide moves the key.

  THE ``TSS.StylesheetArchive`` HARD BOUNDARY (:data:`_CLOSURE_BOUNDARY`). Every
  slide reaches the single ``TSS.StylesheetArchive`` — a mutable name→style-id
  catalog Keynote recompacts on *every* save (``canCullStyles``). Folding it churned
  all 42/42 DSK slide keys per no-op save; skipping it entirely (its content is never
  emitted and its refs are never traversed) gives 0/42 churn with ZERO style-coverage
  loss, because applied styles are stored by id and reached DIRECTLY by the closure —
  the catalog is only a name lookup, not rendering content. The boundary is a
  ``frozenset`` so another recompacted catalog can be added should a future deck's
  acceptance test trip.

* **Global key** — an id-MASKED canonical form of every NON-slide ``Index/*.iwa``
  file (masters/templates/``Document.iwa`` stay IN so a theme/master edit still bumps
  it), minus a tiny, per-file-justified EXCLUSION set (:data:`_GLOBAL_EXCLUDE_EXACT`
  / :data:`_GLOBAL_EXCLUDE_PREFIX`) — THE one staleness door. Excluded:
  ``DocumentStylesheet.iwa`` (its styles are folded per-slide; its catalog churns),
  ``Metadata.iwa`` (preview thumbnails), ``ViewState*.iwa`` (view-only, id-suffixed),
  ``CalculationEngine`` / ``DocumentMetadata`` / ``AnnotationAuthorStorage`` (all
  churn, none affect the rendered slide). The masked form replaces every numeric id
  with a constant token, and files are ordered by their canonical content (not by an
  id-suffixed filename, which would renumber), so a save's renumber leaves the global
  key unchanged. Folded alongside are the FONT ENV (rendering depends on the
  installed fonts, which are absent from the deck) and the OS build. The Keynote app
  version is NOT folded — it already rides ``baseline._app_tag`` on the cache path.

Public entry point: :func:`fingerprint_deck`.

``keynote_parser`` (the optional ``iwa`` extra) is imported LAZILY, and the font
resolution is wrapped so the module imports and runs headless; a decode failure
surfaces as ``ImportError`` for the caller to catch, matching
:func:`obed_edom.iwa_runs.attach_runs`.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import zipfile
from collections import deque
from pathlib import Path
from typing import Any

from obed_edom.offline_inspect import _DATA_MEMBER

# --------------------------------------------------------------------------
# Constants.
# --------------------------------------------------------------------------
# Object types that are a HARD closure boundary: never emitted, never traversed.
# See the module docstring for why ``TSS.StylesheetArchive`` must be bounded out.
_CLOSURE_BOUNDARY = frozenset({"TSS.StylesheetArchive"})

# Non-slide files kept OUT of the global key (the one staleness door). Matched on the
# member's basename: an exact name, or a prefix for the id-suffixed view-state files.
_GLOBAL_EXCLUDE_EXACT = frozenset(
    {
        "DocumentStylesheet.iwa",  # styles folded per-slide; catalog recompacts on save
        "Metadata.iwa",            # preview thumbnails
        "CalculationEngine.iwa",   # churns, no render effect
        "DocumentMetadata.iwa",    # churns, no render effect
        "AnnotationAuthorStorage.iwa",  # churns, no render effect
    }
)
_GLOBAL_EXCLUDE_PREFIX = ("ViewState",)  # ViewState-<id>.iwa — view-only, renumbers

# Float precision the canonical encoder quantizes to, so sub-bit layout noise on a
# stored coordinate can never move a key.
_FLOAT_DP = 6

# Fallback when the font APIs are unavailable (headless / no pyobjc bridge). Tests
# inject ``font_env`` anyway, so this only affects a real headless run.
_FONT_ENV_SENTINEL = "FONT_ENV_UNAVAILABLE"

# Strips the ``-<digits>`` id suffix Keynote embeds in a master/template filename, so
# the global key's per-file identity survives a save-renumber of that id.
_FILE_ID_SUFFIX = re.compile(r"-\d+(?=\.[^./]+$)")


# --------------------------------------------------------------------------
# Canonical encoder.
# --------------------------------------------------------------------------
def _prepare(node: Any) -> Any:
    """Recursively quantize floats so the encoder is stable under sub-bit noise.

    ``-0.0`` is folded to ``0.0`` (``+ 0.0``) so a signed zero can't produce two
    encodings of the same value.
    """
    if isinstance(node, bool):
        return node
    if isinstance(node, float):
        return round(node, _FLOAT_DP) + 0.0
    if isinstance(node, dict):
        return {k: _prepare(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_prepare(v) for v in node]
    return node


def _canon(obj: Any) -> str:
    """Deterministic JSON of a pre-tagged primitive tree (float-quantized, key-sorted).

    Type tags keep the token spaces disjoint under JSON: a positional ``{"@ref": 0}``,
    a ``{"@data": "..."}`` asset token, a ``{"@boundary": "..."}`` boundary token, a
    bare int id and a genuine string style-name each serialize distinctly, so none can
    collide with another. NEVER uses Python ``hash()`` / set-iteration order (which
    honour ``PYTHONHASHSEED``); ``sort_keys`` + ``separators`` make it byte-stable.
    """
    return json.dumps(_prepare(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Numeric-ref detection + structural graph walk (id-independent order).
# --------------------------------------------------------------------------
def _ref_id(node: Any) -> str | None:
    """The referenced id of a ``{"identifier": N}`` ref dict, or ``None``.

    Only a NUMERIC identifier (an int, or an all-digits string as the parser emits)
    is a ref; a string style-name identifier (e.g. ``"motionBackground-9-..."``) is
    ordinary content and returns ``None``. The id is normalized to ``str`` to match
    the ``_load_deck`` maps.
    """
    if not isinstance(node, dict):
        return None
    ident = node.get("identifier")
    if isinstance(ident, bool):
        return None
    if isinstance(ident, int):
        return str(ident)
    if isinstance(ident, str) and ident.isdigit():
        return ident
    return None


def _iter_refs(node: Any):
    """Yield every numeric ref id reachable in ``node``, in STRUCTURAL order.

    Dict fields are iterated in sorted-KEY order (field names, never ids) and lists in
    list order, so the discovery order an object imposes on its refs is independent of
    the ids themselves — which is what makes a save's renumber wash out. A ref dict
    yields its own id first, then descends its sibling fields for any nested refs.
    """
    if isinstance(node, dict):
        rid = _ref_id(node)
        if rid is not None:
            yield rid
            for key in sorted(node):
                if key != "identifier":
                    yield from _iter_refs(node[key])
        else:
            for key in sorted(node):
                yield from _iter_refs(node[key])
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def _transform(node: Any, resolve) -> Any:
    """Serialize an object's content, rewriting each numeric ref via ``resolve``.

    ``resolve(rid)`` returns the type-tagged token dict for a ref (positional /
    asset / boundary). A ref dict's sibling fields are preserved (transformed), so a
    ``{"identifier": N, ...}`` with extra fields keeps them alongside its token.
    """
    if isinstance(node, dict):
        rid = _ref_id(node)
        if rid is not None:
            token = resolve(rid)
            extras = {
                key: _transform(value, resolve)
                for key, value in node.items()
                if key != "identifier"
            }
            return {**token, **extras} if extras else token
        return {key: _transform(value, resolve) for key, value in node.items()}
    if isinstance(node, list):
        return [_transform(item, resolve) for item in node]
    return node


def _mask_transform(node: Any) -> Any:
    """Serialize an object's content with every numeric ref replaced by a CONSTANT.

    The coarse global-key form: a renumber-immune id-mask (``{"@id": "*"}``) is enough
    to gate the theme/master surface, and over-inclusion there only costs cache misses.
    """
    if isinstance(node, dict):
        rid = _ref_id(node)
        if rid is not None:
            extras = {
                key: _mask_transform(value)
                for key, value in node.items()
                if key != "identifier"
            }
            return {"@id": "*", **extras}
        return {key: _mask_transform(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_mask_transform(item) for item in node]
    return node


# --------------------------------------------------------------------------
# Per-slide normalized closure + key.
# --------------------------------------------------------------------------
def _closure(
    slide_id: str,
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    data_map: dict[str, tuple[int, int]],
    pres_files: set[str],
    own_file: str | None,
) -> tuple[list[str] | None, dict[str, int] | None, str | None]:
    """BFS the slide's reachable graph; return ``(order, index_of, reason)``.

    ``order`` is the visited ids in discovery order and ``index_of`` their positions;
    on an uncacheable condition both are ``None`` and ``reason`` is set:

        * ``cross-slide-ref`` — a followed ref lands in ANOTHER presentation slide's
          file (the reachability guard; measured ~0 on the gold decks).
        * ``dangling-ref``    — a numeric ref resolves to neither an object nor a Data
          id (all safe: a miss, never a stale serve).

    The ``TSS.StylesheetArchive`` boundary is skipped (not traversed, not indexed); a
    ref to it is later resolved to a stable boundary token. Cycle-safe via a visited
    set — a shared global style reached from many runs is a DAG and dedups on first
    reach (NEVER an error).
    """
    order: list[str] = []
    index_of: dict[str, int] = {}
    visited: set[str] = {slide_id}
    queue: deque[str] = deque([slide_id])
    while queue:
        cur = queue.popleft()
        index_of[cur] = len(order)
        order.append(cur)
        for rid in _iter_refs(objects[cur]):
            target = objects.get(rid)
            if target is not None:
                tfile = id_to_file.get(rid)
                if tfile in pres_files and tfile != own_file:
                    return None, None, "cross-slide-ref"
                if target.get("_pbtype") in _CLOSURE_BOUNDARY:
                    continue  # hard boundary: don't traverse, don't index
                if rid not in visited:
                    visited.add(rid)
                    queue.append(rid)
            elif rid in data_map:
                continue  # asset data id: folded as an @data token, not traversed
            else:
                return None, None, "dangling-ref"
    return order, index_of, None


def _slide_key(
    slide_id: str,
    pos: int,
    skipped: bool,
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    data_map: dict[str, tuple[int, int]],
    pres_files: set[str],
) -> tuple[str | None, str | None]:
    """``(key, reason)`` for one presentation slide; ``key`` is ``None`` if uncacheable.

    ``key = sha256( canon(normalized_closure) ⊕ "|pos=<i>|skip=<0/1>" )``. The
    position + skip flag close the duplicate-slide / slide-number-field hazard and a
    reorder / show-hide, which the closure alone would not see.
    """
    if slide_id not in objects:
        return None, "undecodable-slide"
    own_file = id_to_file.get(slide_id)
    order, index_of, reason = _closure(
        slide_id, objects, id_to_file, data_map, pres_files, own_file
    )
    if order is None or index_of is None:
        return None, reason

    def resolve(rid: str) -> dict:
        idx = index_of.get(rid)
        if idx is not None:
            return {"@ref": idx}
        target = objects.get(rid)
        if target is not None:  # a boundary object (only remaining object case)
            return {"@boundary": target.get("_pbtype")}
        crc, size = data_map[rid]
        return {"@data": f"{crc:08x}:{size}"}

    closure = [_transform(objects[oid], resolve) for oid in order]
    body = _canon(closure)
    return _sha(f"{body}|pos={pos}|skip={int(skipped)}"), None


# --------------------------------------------------------------------------
# Global key.
# --------------------------------------------------------------------------
def _is_global_excluded(fname: str) -> bool:
    base = fname.rsplit("/", 1)[-1]
    if base in _GLOBAL_EXCLUDE_EXACT:
        return True
    return any(base.startswith(prefix) for prefix in _GLOBAL_EXCLUDE_PREFIX)


def _strip_file_id(fname: str) -> str:
    """Basename with its ``-<id>`` suffix masked, so a renumbered master file matches."""
    return _FILE_ID_SUFFIX.sub("-@", fname.rsplit("/", 1)[-1])


def _global_key(
    objects: dict[str, dict],
    file_ids: dict[str, list[str]],
    pres_files: set[str],
    font_env: str,
    os_build: str,
) -> str:
    """``sha256( canon([ normalized_globals, font_env, os_build ]) )``.

    ``normalized_globals`` is every non-slide, non-excluded ``Index/*.iwa`` file's
    id-masked content, each tagged with its id-stripped basename, ORDERED by canonical
    content (an ordered concatenation, not an xor) so the order survives a renumber.
    The ``TSS.StylesheetArchive`` boundary is skipped here too.
    """
    entries: list[list[Any]] = []
    for fname, ids in file_ids.items():
        if fname in pres_files or _is_global_excluded(fname):
            continue
        masked: list[Any] = []
        for oid in ids:
            obj = objects.get(oid)
            if obj is None or obj.get("_pbtype") in _CLOSURE_BOUNDARY:
                continue
            masked.append(_mask_transform(obj))
        entries.append([_strip_file_id(fname), masked])
    entries.sort(key=_canon)
    return _sha(_canon([entries, font_env, os_build]))


# --------------------------------------------------------------------------
# Font env + OS build.
# --------------------------------------------------------------------------
def _font_names(objects: dict[str, dict]) -> set[str]:
    """Every distinct PostScript ``fontName`` referenced anywhere in the deck.

    Scans all objects (slides AND masters) for string ``fontName`` values — the union
    of names the closures and masters reference, which is what the font env must pin.
    """
    names: set[str] = set()

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            value = node.get("fontName")
            if isinstance(value, str) and value:
                names.add(value)
            for child in node.values():
                scan(child)
        elif isinstance(node, list):
            for child in node:
                scan(child)

    for obj in objects.values():
        scan(obj)
    return names


def _compute_font_env(objects: dict[str, dict]) -> str:
    """A stable string over each referenced font's installed file (URL + mtime + size).

    Rendering depends on the installed fonts, which the deck does not carry, so a
    font install/update/removal must move the global key. Uses ``_ns_font`` to resolve
    the NSFont and ``CTFontDescriptorCopyAttribute(kCTFontURLAttribute)`` for the file;
    a missing font becomes ``MISSING:<name>`` (so a later install changes the key). The
    whole resolution is wrapped so a headless host (no pyobjc / CoreText bridge) falls
    back to :data:`_FONT_ENV_SENTINEL` rather than raising — tests inject ``font_env``.
    """
    names = _font_names(objects)
    try:
        from CoreText import (  # noqa: PLC0415 (optional pyobjc bridge, lazy)
            CTFontDescriptorCopyAttribute,
            kCTFontURLAttribute,
        )

        from obed_edom.iwa_text_shape import _ns_font  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — no bridge -> stable sentinel, never raise
        return _FONT_ENV_SENTINEL

    records: list[str] = []
    for name in sorted(names):
        try:
            font, missing, _trait_bad = _ns_font(name, 12.0)
        except Exception:  # noqa: BLE001 — a single bad font must not sink the env
            records.append(f"ERR:{name}")
            continue
        if missing:
            records.append(f"MISSING:{name}")
            continue
        try:
            url = CTFontDescriptorCopyAttribute(font.fontDescriptor(), kCTFontURLAttribute)
            path = url.path() if url is not None else None
            if path:
                stat = os.stat(path)
                records.append(f"{name}|{path}|{int(stat.st_mtime)}|{stat.st_size}")
            else:
                records.append(f"NOURL:{name}")
        except Exception:  # noqa: BLE001
            records.append(f"ERR:{name}")
    records.sort()
    return "\n".join(records) if records else _FONT_ENV_SENTINEL


def _os_build() -> str:
    """A stable OS-build string (fold it in so an OS/text-engine change moves the key)."""
    return platform.mac_ver()[0] or platform.platform()


# --------------------------------------------------------------------------
# Central-directory data map (media captured by CRC+size, never read).
# --------------------------------------------------------------------------
def _build_data_map(key_path: str | Path) -> dict[str, tuple[int, int]]:
    """``{dataId: (CRC, size)}`` from the zip central directory (no media bytes read).

    Mirrors ``offline_inspect._build_data_index``'s ``Data/<base>-<id>.<ext>`` shape,
    keyed by the same ``<id>`` an image/movie object's ``data``/``movieData`` ref
    resolves to, but keeps ``(CRC, size)`` so the token embeds the media bytes.
    """
    out: dict[str, tuple[int, int]] = {}
    with zipfile.ZipFile(key_path) as zf:
        for info in zf.infolist():
            match = _DATA_MEMBER.match(info.filename)
            if match:
                out[match.group("id")] = (info.CRC & 0xFFFFFFFF, info.file_size)
    return out


# --------------------------------------------------------------------------
# Assembly.
# --------------------------------------------------------------------------
def _fingerprint(
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    file_ids: dict[str, list[str]],
    *,
    data_map: dict[str, tuple[int, int]],
    font_env: str,
    os_build: str,
) -> dict[str, Any]:
    """Pure core: per-slide + global keys over an already-decoded deck (no zip / fonts).

    Split out from :func:`fingerprint_deck` so the whole keying scheme is unit-testable
    from hand-built ``objects``/``id_to_file``/``file_ids`` dicts with an injected
    ``data_map``/``font_env``/``os_build`` — no real deck, fonts or Keynote needed.
    """
    from obed_edom.iwa_runs import slide_order  # noqa: PLC0415 (pure; keep the pattern)

    order = slide_order(objects)
    pres_files = {id_to_file.get(sid) for sid, _ in order}
    pres_files.discard(None)

    slides: list[str | None] = []
    uncacheable: dict[int, str] = {}
    for i, (slide_id, skipped) in enumerate(order):
        key, reason = _slide_key(
            slide_id, i, bool(skipped), objects, id_to_file, data_map, pres_files
        )
        slides.append(key)
        if reason is not None:
            uncacheable[i] = reason

    global_key = _global_key(objects, file_ids, pres_files, font_env, os_build)  # type: ignore[arg-type]
    return {"global": global_key, "slides": slides, "uncacheable": uncacheable}


def fingerprint_deck(
    key_path: str | Path, *, deck: Any = None, font_env: str | bytes | None = None
) -> dict[str, Any]:
    """Save-churn-immune content keys for a finalized ``.key`` deck.

    Returns ``{"global": <hex>, "slides": [<hex>|None, ...], "uncacheable": {i: reason}}``
    where ``slides[i]`` is the per-slide key for the presentation slide at position
    ``i`` in ``slide_order`` (``None`` when that slide is uncacheable, with the reason
    in ``uncacheable[i]``).

    ``deck`` is an already-decoded ``_load_deck`` 3-tuple ``(objects, id_to_file,
    file_ids)``; pass it to share ONE IWA decode with the checker's other offline
    reads. When ``None`` the deck is decoded once here (the ``keynote_parser`` import
    is lazy, so this module imports without the optional ``iwa`` extra; a decode
    failure surfaces as ``ImportError`` for the caller to catch).

    ``font_env`` is an injectable override (``str``/``bytes``) so a test can pin the
    font surface; when ``None`` it is computed from the deck's referenced fonts,
    falling back to a stable sentinel when the font APIs are unavailable.
    """
    if deck is None:
        from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415 (optional extra)

        deck = _load_deck(key_path)
    objects, id_to_file, file_ids = deck
    data_map = _build_data_map(key_path)
    if font_env is None:
        font_env = _compute_font_env(objects)
    resolved_font_env = (
        font_env.decode("utf-8", "replace") if isinstance(font_env, bytes) else str(font_env)
    )
    return _fingerprint(
        objects,
        id_to_file,
        file_ids,
        data_map=data_map,
        font_env=resolved_font_env,
        os_build=_os_build(),
    )

"""Save-churn-immune content keys for a finalized ``.key`` deck.

Byte hashes churn on no-op save (id renumber); hash the decoded id-normalized
graph. ``TSS.StylesheetArchive`` is a hard closure boundary (recompacts every
save). The global exclude set is the staleness door; font env + OS are folded
in, Keynote version is not. Raises ImportError without the ``iwa`` extra.
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

# Never emitted, never traversed. StylesheetArchive recompacts on every save.
_CLOSURE_BOUNDARY = frozenset({"TSS.StylesheetArchive"})

# Non-slide files kept OUT of the global key (the one staleness door).
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

# Quantize so sub-bit layout noise cannot move a key.
_FLOAT_DP = 6

# Headless / no pyobjc. Tests inject ``font_env``.
_FONT_ENV_SENTINEL = "FONT_ENV_UNAVAILABLE"

# Strip ``-<digits>`` so a master/template filename survives save-renumber.
_FILE_ID_SUFFIX = re.compile(r"-\d+(?=\.[^./]+$)")


def _prepare(node: Any) -> Any:
    """Quantize floats; fold ``-0.0`` to ``0.0`` so signed zero cannot split a key."""
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
    """Byte-stable JSON (sort_keys). Never Python ``hash()`` / set order (PYTHONHASHSEED)."""
    return json.dumps(_prepare(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ref_id(node: Any) -> str | None:
    """Numeric ``{"identifier": N}`` only. A string style-name identifier is content, not a ref."""
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
    """Yield numeric ref ids in structural order (sorted keys, list order) so a renumber washes out."""
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
    """Replace every numeric ref with ``{"@id": "*"}`` so a global-key renumber cannot move the hash."""
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


def _closure(
    slide_id: str,
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    data_map: dict[str, tuple[int, int]],
    pres_files: set[str],
    own_file: str | None,
) -> tuple[list[str] | None, dict[str, int] | None, str | None]:
    """BFS reachable graph. Uncacheable: ``cross-slide-ref``, ``dangling-ref``. Boundary skipped, not indexed."""
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
    """``(key, reason)``. Mix pos+skip so a reorder / show-hide / duplicate-slide moves the key."""
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


def _is_global_excluded(fname: str) -> bool:
    base = fname.rsplit("/", 1)[-1]
    if base in _GLOBAL_EXCLUDE_EXACT:
        return True
    return any(base.startswith(prefix) for prefix in _GLOBAL_EXCLUDE_PREFIX)


def _strip_file_id(fname: str) -> str:
    return _FILE_ID_SUFFIX.sub("-@", fname.rsplit("/", 1)[-1])


def _global_key(
    objects: dict[str, dict],
    file_ids: dict[str, list[str]],
    pres_files: set[str],
    font_env: str,
    os_build: str,
) -> str:
    """Id-masked non-slide Index files + font env + OS. Ordered by content so a filename renumber is inert."""
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


def _font_names(objects: dict[str, dict]) -> set[str]:
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
    """Installed font URL+mtime+size per referenced name. Missing → ``MISSING:<name>``. Headless → sentinel."""
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
    return platform.mac_ver()[0] or platform.platform()


def _build_data_map(key_path: str | Path) -> dict[str, tuple[int, int]]:
    """``{dataId: (CRC, size)}`` from the zip central directory (media bytes never read)."""
    out: dict[str, tuple[int, int]] = {}
    with zipfile.ZipFile(key_path) as zf:
        for info in zf.infolist():
            match = _DATA_MEMBER.match(info.filename)
            if match:
                out[match.group("id")] = (info.CRC & 0xFFFFFFFF, info.file_size)
    return out


def _fingerprint(
    objects: dict[str, dict],
    id_to_file: dict[str, str],
    file_ids: dict[str, list[str]],
    *,
    data_map: dict[str, tuple[int, int]],
    font_env: str,
    os_build: str,
) -> dict[str, Any]:
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
    """``{global, slides, uncacheable}``. ``deck`` shares one IWA decode; ``font_env`` is injectable."""
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

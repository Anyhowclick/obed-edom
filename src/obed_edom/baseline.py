"""Content identity and pairing reuse across checker runs.

Jobs are keyed by id, so matching the same two decks again used to start from
scratch. This module keys a pairing baseline to the input paths, then remaps
saved slots onto the current slides by content digest. Unchanged pairings carry
over; only the gaps are re-aligned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from obed_edom import keynote_app
from obed_edom.paths import find_repo_root

PAIRING_VERSION = 1
HASH_CACHE_VERSION = 1
# Bump whenever the payload shape changes — whether the change is in
# inspect_keynote.js or in Python post-processing. (v3 came from Python:
# iwa_runs.attach_runs now populates per-run character style in item["runs"],
# which the JS never touched.) The cache is keyed by deck digest, which says
# nothing about the reader that produced it, so without this a deck inspected by
# an older build is reused forever — a payload captured before duplicate-shape
# marking existed would never gain it.
#
# Our own build is only half of "the reader". Keynote's version is the other, and
# it moves without us: a digest-keyed hit would otherwise hand a payload from one
# Keynote build to a run of another, and an upgrade would look like it changed
# nothing. Hence the `.k<version>` tag below, which partitions the cache per app
# version instead.
#
# Untagged payloads predate the tag, were produced by Keynote 14.5, and are no
# longer read at all now that the tool is 15.x only.
INSPECT_VERSION = 3
# Bump when the shape of the cached template stat-size map changes. Keyed per
# Keynote version too (via the `.k<version>` tag), since the sizes are read out
# of the template by AppleScript and a different build could read them differently.
TEMPLATE_STAT_VERSION = 1
DIGEST_LEN = 16


CACHE_DIR_ENV = "OBED_EDOM_CACHE_DIR"


def cache_root(root: Path | None = None) -> Path:
    """Where inspect payloads, previews and pairings live.

    Deliberately outside `output/`. Reading a wall deck costs minutes — 63 for the
    six gold decks — and it used to sit in `output/.cache`, so a tidy-up of the
    output folder threw away an hour of Keynote time. `OBED_EDOM_CACHE_DIR` moves
    it, e.g. onto an external disk.
    """
    if root is not None:
        return Path(root) / ".cache"
    override = (os.environ.get(CACHE_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return find_repo_root() / ".cache"


def pairings_dir(root: Path | None = None) -> Path:
    return cache_root(root) / "pairings"


def _app_tag(app_version: str | None = None) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", app_version or keynote_app.app_version())


def inspect_cache_path(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Where a payload produced by this Keynote version is read and written."""
    name = f"{digest}.v{INSPECT_VERSION}.k{_app_tag(app_version)}.json"
    return cache_root(root) / "inspect" / name


def preview_cache_dir(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Where previews exported by this Keynote version are read and written."""
    return cache_root(root) / "previews" / f"{digest}.k{_app_tag(app_version)}"


def template_stat_cache_path(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Where a template's ``{number: font size}`` map is cached, per Keynote version.

    ``read_template_stat_sizes`` opens the (invariant) CG template on every remap
    just to read grouped stat sizes; keying that read by the template's content
    digest lets a repeat run return the map without opening Keynote at all.
    """
    name = f"{digest}.v{TEMPLATE_STAT_VERSION}.k{_app_tag(app_version)}.json"
    return cache_root(root) / "template_stat" / name


def wall_thumb_dir(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Downscaled wall previews, for showing a framing in the browser.

    A wall preview is 7680x1080 and about 9 MB, so ten of them on one page is
    ~90 MB. These are the same images at a size a row can display.
    """
    return cache_root(root) / "wallthumbs" / f"{digest}.k{_app_tag(app_version)}"


def _hash_file(hasher: hashlib._Hash, path: Path, chunk: int = 1024 * 1024) -> None:
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk)
            if not data:
                return
            hasher.update(data)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    _hash_file(hasher, Path(path))
    return hasher.hexdigest()


def deck_digest(path: Path | str) -> str:
    """SHA-256 of a .key file, or of a package directory walked in sorted order."""
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    hasher = hashlib.sha256()
    if path.is_file():
        _hash_file(hasher, path)
        return hasher.hexdigest()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = child.relative_to(path).as_posix().encode()
        hasher.update(rel)
        hasher.update(b"\0")
        _hash_file(hasher, child)
    return hasher.hexdigest()


def _file_hash_cache_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha.json")


def _cached_file_digest(path: Path) -> str:
    """SHA-256 of one preview, remembered beside the file by size and mtime."""
    try:
        stat = path.stat()
    except OSError:
        return sha256_file(path)
    key = {
        "version": HASH_CACHE_VERSION,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
    }
    sidecar = _file_hash_cache_path(path)
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            if data.get("key") == key and data.get("sha256"):
                return str(data["sha256"])
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    digest = sha256_file(path)
    try:
        sidecar.write_text(json.dumps({"key": key, "sha256": digest}), encoding="utf-8")
    except OSError:
        pass
    return digest


def folder_digests(folder: Path | str) -> list[str]:
    """Per-preview SHA-256, in the same order Visual Checker lists the folder."""
    from obed_edom.inspect import preview_media  # noqa: PLC0415

    folder = Path(folder)
    return [_cached_file_digest(path) for path in preview_media(folder)]


def _walk_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        yield item
        yield from _walk_items(item)


def deck_slide_digests(payload: dict) -> list[str]:
    """Per-slide fingerprint from inspect JSON: copy plus image identity."""
    from obed_edom.inspect import slide_plain_text  # noqa: PLC0415
    from obed_edom.text_diff import fingerprint  # noqa: PLC0415

    out: list[str] = []
    for slide in payload.get("slides") or []:
        text = fingerprint(slide_plain_text(slide))
        images: list[str] = []
        for item in _walk_items(slide):
            if (item.get("kind") or "") != "image":
                continue
            images.append(
                ":".join(
                    [
                        str(item.get("fileName") or ""),
                        f"{float(item.get('x') or 0):.1f}",
                        f"{float(item.get('y') or 0):.1f}",
                        f"{float(item.get('w') or 0):.1f}",
                        f"{float(item.get('h') or 0):.1f}",
                        f"{float(item.get('rotation') or 0):.1f}",
                    ]
                )
            )
        images.sort()
        skipped = "1" if slide.get("skipped") else "0"
        blob = f"{skipped}|{text}|{'|'.join(images)}"
        out.append(hashlib.sha256(blob.encode("utf-8")).hexdigest()[:DIGEST_LEN])
    return out


def pairing_key(kind: str, left: Path | str, right: Path | str) -> str:
    left_s = str(Path(left).expanduser().resolve())
    right_s = str(Path(right).expanduser().resolve())
    blob = f"{kind}|{left_s}|{right_s}".encode()
    return hashlib.sha256(blob).hexdigest()


def pairing_path(kind: str, left: Path | str, right: Path | str, root: Path | None = None) -> Path:
    return pairings_dir(root) / f"{pairing_key(kind, left, right)}.json"


def load_pairing(
    kind: str, left: Path | str, right: Path | str, root: Path | None = None
) -> dict | None:
    path = pairing_path(kind, left, right, root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("slots"):
        return None
    return data


def save_pairing(
    kind: str,
    left: Path | str,
    right: Path | str,
    left_digests: list[str],
    right_digests: list[str],
    slots: list[dict],
    *,
    source: str = "auto",
    job_id: str = "",
    root: Path | None = None,
    force: bool = False,
) -> dict:
    """Write the pairing baseline. An operator record is not overwritten by auto."""
    path = pairing_path(kind, left, right, root)
    if not force and source != "operator":
        existing = load_pairing(kind, left, right, root)
        if existing and existing.get("source") == "operator":
            return existing
    rec = {
        "version": PAIRING_VERSION,
        "kind": kind,
        "leftPath": str(Path(left).expanduser().resolve()) if Path(left).exists() else str(left),
        "rightPath": str(Path(right).expanduser().resolve()) if Path(right).exists() else str(right),
        "leftDigests": list(left_digests),
        "rightDigests": list(right_digests),
        "slots": [dict(slot) for slot in slots],
        "source": source,
        "jobId": job_id,
        "savedAt": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def delete_pairing(
    kind: str, left: Path | str, right: Path | str, root: Path | None = None
) -> None:
    pairing_path(kind, left, right, root).unlink(missing_ok=True)


def slot_dict(
    left_index: int | None,
    right_indexes: list[int] | None = None,
    score: float = 0.0,
) -> dict:
    rights = [int(x) for x in (right_indexes or []) if x is not None]
    return {
        "leftIndex": None if left_index is None else int(left_index),
        "rightIndex": rights[0] if rights else None,
        "rightIndexes": rights,
        "score": float(score),
    }


def normalize_slot(slot: dict) -> dict:
    rights = slot.get("rightIndexes")
    if rights is None:
        ri = slot.get("rightIndex")
        rights = [] if ri is None else [ri]
    return slot_dict(slot.get("leftIndex"), list(rights), float(slot.get("score") or 0.0))


def index_map(old: list[str], new: list[str]) -> dict[int, int]:
    """Map old indices onto new ones.

    Equal runs from SequenceMatcher cover insertions, deletions and in-place
    edits. Digests that appear exactly once on each leftover side cover a
    reorder of unique slides.
    """
    import difflib  # noqa: PLC0415

    mapping: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            mapping[i1 + offset] = j1 + offset
    used_new = set(mapping.values())
    old_left = [i for i in range(len(old)) if i not in mapping]
    new_left = [j for j in range(len(new)) if j not in used_new]
    old_by: dict[str, list[int]] = {}
    new_by: dict[str, list[int]] = {}
    for i in old_left:
        old_by.setdefault(old[i], []).append(i)
    for j in new_left:
        new_by.setdefault(new[j], []).append(j)
    for digest, old_idxs in old_by.items():
        new_idxs = new_by.get(digest) or []
        if len(old_idxs) == 1 and len(new_idxs) == 1:
            mapping[old_idxs[0]] = new_idxs[0]
    return mapping


def remap_slots(
    slots: list[dict], left_map: dict[int, int], right_map: dict[int, int]
) -> list[dict]:
    out: list[dict] = []
    for slot in slots:
        rec = normalize_slot(slot)
        li = rec["leftIndex"]
        new_li = left_map.get(int(li)) if li is not None else None
        new_rights = [
            right_map[int(r)] for r in rec["rightIndexes"] if int(r) in right_map
        ]
        if new_li is None and not new_rights:
            continue
        out.append(slot_dict(new_li, new_rights, rec["score"]))
    return out


def insert_unpaired(slots: list[dict], n_left: int, n_right: int) -> list[dict]:
    """Put leftover slides into the playlist in deck order, as unpaired rows."""
    used_left = {int(s["leftIndex"]) for s in slots if s.get("leftIndex") is not None}
    used_right: set[int] = set()
    for slot in slots:
        used_right.update(int(r) for r in (slot.get("rightIndexes") or []))
    missing_left = [i for i in range(n_left) if i not in used_left]
    missing_right = [j for j in range(n_right) if j not in used_right]
    out: list[dict] = []
    mi = mj = 0

    def flush(left_limit: int, right_limit: int) -> None:
        nonlocal mi, mj
        while True:
            take_l = mi < len(missing_left) and missing_left[mi] < left_limit
            take_r = mj < len(missing_right) and missing_right[mj] < right_limit
            if not take_l and not take_r:
                return
            if take_l:
                out.append(slot_dict(missing_left[mi], []))
                mi += 1
            if take_r:
                out.append(slot_dict(None, [missing_right[mj]]))
                mj += 1

    for slot in slots:
        rec = normalize_slot(slot)
        left_limit = rec["leftIndex"] if rec["leftIndex"] is not None else n_left
        right_limit = min(rec["rightIndexes"]) if rec["rightIndexes"] else n_right
        flush(left_limit, right_limit)
        out.append(rec)
    flush(n_left, n_right)
    return out


def unpaired_gaps(slots: list[dict]) -> list[tuple[int, int, list[int], list[int]]]:
    """Runs of one-sided rows that still have leftover slides on both decks."""
    gaps: list[tuple[int, int, list[int], list[int]]] = []
    i = 0
    while i < len(slots):
        rec = normalize_slot(slots[i])
        both = rec["leftIndex"] is not None and rec["rightIndexes"]
        if both:
            i += 1
            continue
        j = i
        lefts: list[int] = []
        rights: list[int] = []
        while j < len(slots):
            nxt = normalize_slot(slots[j])
            if nxt["leftIndex"] is not None and nxt["rightIndexes"]:
                break
            if nxt["leftIndex"] is not None:
                lefts.append(int(nxt["leftIndex"]))
            rights.extend(int(r) for r in nxt["rightIndexes"])
            j += 1
        if lefts and rights:
            gaps.append((i, j, lefts, rights))
        i = j if j > i else i + 1
    return gaps


def pair_index_gaps(slots: list[dict]) -> list[dict]:
    """Zip leftover lefts and rights 1:1 inside each gap (Visual Checker)."""
    gaps = unpaired_gaps(slots)
    if not gaps:
        return slots
    out: list[dict] = []
    cursor = 0
    for start, end, lefts, rights in gaps:
        out.extend(normalize_slot(s) for s in slots[cursor:start])
        n = min(len(lefts), len(rights))
        for k in range(n):
            out.append(slot_dict(lefts[k], [rights[k]], 1.0))
        for li in lefts[n:]:
            out.append(slot_dict(li, []))
        for ri in rights[n:]:
            out.append(slot_dict(None, [ri]))
        cursor = end
    out.extend(normalize_slot(s) for s in slots[cursor:])
    return out


@dataclass
class ReuseResult:
    slots: list[dict]
    carried: int
    changed: int
    added: int
    removed: int
    source: str = "auto"
    used: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def _opcode_changed(old: list[str], new: list[str]) -> int:
    import difflib  # noqa: PLC0415

    n = 0
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            n += max(i2 - i1, j2 - j1)
    return n


def reuse_slots(
    baseline: dict,
    new_left: list[str],
    new_right: list[str],
    threshold: float = 0.6,
) -> ReuseResult | None:
    """Remap saved slots onto the current digests, or None below the threshold."""
    old_left = list(baseline.get("leftDigests") or [])
    old_right = list(baseline.get("rightDigests") or [])
    if not old_left and not old_right:
        return None
    left_map = index_map(old_left, new_left)
    right_map = index_map(old_right, new_right)
    mapped_new = len(set(left_map.values())) + len(set(right_map.values()))
    total_new = len(new_left) + len(new_right)
    if total_new == 0:
        return None
    carry = mapped_new / total_new
    if carry < threshold:
        return None
    remapped = remap_slots(list(baseline.get("slots") or []), left_map, right_map)
    slots = insert_unpaired(remapped, len(new_left), len(new_right))
    mapped_old = len(left_map) + len(right_map)
    total_old = len(old_left) + len(old_right)
    added = total_new - mapped_new
    removed = total_old - mapped_old
    changed = _opcode_changed(old_left, new_left) + _opcode_changed(old_right, new_right)
    both = sum(
        1
        for slot in remapped
        if slot.get("leftIndex") is not None and slot.get("rightIndexes")
    )
    return ReuseResult(
        slots=slots,
        carried=both,
        changed=changed,
        added=added,
        removed=removed,
        source=str(baseline.get("source") or "auto"),
    )

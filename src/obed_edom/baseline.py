"""Content identity and pairing reuse across checker runs.

Pairings are keyed to input paths, then remapped onto current slides by content
digest. Unchanged pairings carry over; only the gaps are re-aligned.
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
# Bump on payload-shape change. Digest-keyed cache; `.k<version>` partitions Keynote builds. Untagged = 14.5, unread.
INSPECT_VERSION = 4
# Bump on template stat-size map shape change. Also `.k<version>` (AppleScript read).
TEMPLATE_STAT_VERSION = 1
DIGEST_LEN = 16


CACHE_DIR_ENV = "OBED_EDOM_CACHE_DIR"


def cache_root(root: Path | None = None) -> Path:
    """Inspect payloads, previews, pairings. Outside ``output/`` so a tidy-up cannot throw away Keynote time."""
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
    """Payload produced by this Keynote version."""
    name = f"{digest}.v{INSPECT_VERSION}.k{_app_tag(app_version)}.json"
    return cache_root(root) / "inspect" / name


def preview_cache_dir(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Previews exported by this Keynote version."""
    return cache_root(root) / "previews" / f"{digest}.k{_app_tag(app_version)}"


def template_stat_cache_path(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Cached ``{number: font size}`` map for the CG template, per Keynote version."""
    name = f"{digest}.v{TEMPLATE_STAT_VERSION}.k{_app_tag(app_version)}.json"
    return cache_root(root) / "template_stat" / name


def wall_thumb_dir(
    digest: str, root: Path | None = None, app_version: str | None = None
) -> Path:
    """Downscaled wall previews for the framing UI. Full wall PNGs are 7680×1080."""
    return cache_root(root) / "wallthumbs" / f"{digest}.k{_app_tag(app_version)}"


def _hash_file(hasher: hashlib._Hash, path: Path, chunk: int = 1024 * 1024) -> None:
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk)
            if not data:
                return
            hasher.update(data)


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
            # Identity only: no geometry. Offline vs JXA frames would churn pairing of unedited slides.
            images.append(str(item.get("fileName") or ""))
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
    """Map old indices onto new ones. Equal runs plus unique leftover digests cover insert/delete/reorder."""
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
    """Insert leftover slides in deck order. A one-sided row flushes only the side it anchors."""
    used_left = {int(s["leftIndex"]) for s in slots if s.get("leftIndex") is not None}
    used_right: set[int] = set()
    for slot in slots:
        used_right.update(int(r) for r in (slot.get("rightIndexes") or []))
    missing_left = [i for i in range(n_left) if i not in used_left]
    missing_right = [j for j in range(n_right) if j not in used_right]
    out: list[dict] = []
    mi = mj = 0

    def flush_left(limit: int) -> None:
        nonlocal mi
        while mi < len(missing_left) and missing_left[mi] < limit:
            out.append(slot_dict(missing_left[mi], []))
            mi += 1

    def flush_right(limit: int) -> None:
        nonlocal mj
        while mj < len(missing_right) and missing_right[mj] < limit:
            out.append(slot_dict(None, [missing_right[mj]]))
            mj += 1

    for slot in slots:
        rec = normalize_slot(slot)
        if rec["leftIndex"] is not None:
            flush_left(int(rec["leftIndex"]))
        if rec["rightIndexes"]:
            flush_right(min(int(r) for r in rec["rightIndexes"]))
        out.append(rec)
    flush_left(n_left)
    flush_right(n_right)
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

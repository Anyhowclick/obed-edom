from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from obed_edom import keynote_app
from obed_edom.map_remap import slides_for_plan
from obed_edom.paths import output_root

INSPECT_JS = Path(__file__).resolve().parent / "inspect_keynote.js"
BULK_GEOMETRY_JS = Path(__file__).resolve().parent / "bulk_geometry.js"


def bulk_read_enabled() -> bool:
    """Whether the JXA inspect uses bulk (whole-collection) property reads — default ON.

    Bulk reads fetch one property for a whole collection in a single Apple Event
    (``slide.shapes.position()``) instead of one event per object, ~2.4x on flat
    slides. inspect_keynote.js guards every bulk array with a length check and
    falls back to the per-object read on any drift, so the payload is byte-
    identical either way. Set ``OBED_BULK_READ=0`` (or ``false``/``no``/``off``)
    to force the legacy per-object path — for A/B validation and as an escape
    hatch. Mirrors ``OBED_AS_GEOMETRY``.
    """
    return os.environ.get("OBED_BULK_READ", "").strip().lower() not in {"0", "false", "no", "off"}


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def export_applescript(key_path: Path, export_dir: Path) -> str:
    """Same export shape generate uses: POSIX file + slide images PNG."""
    key = _as_escape(str(Path(key_path).resolve()))
    dest = _as_escape(str(Path(export_dir).resolve()))
    app = keynote_app.bundle_id()
    return "\n".join(
        [
            f'tell application id "{app}"',
            f'  using terms from application id "{app}"',
            f'    set theDoc to open POSIX file "{key}"',
            f'    set exportFolder to POSIX file "{dest}"',
            "    export theDoc to exportFolder as slide images with properties {image format:PNG, skipped slides:false}",
            "    try",
            "      close theDoc saving no",
            "    end try",
            "  end using terms from",
            "end tell",
        ]
    )


def export_slide_images(key_path: Path, export_dir: Path) -> str | None:
    """Export PNG previews. Returns an error string, or None on success."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    script = export_applescript(key_path, export_dir)
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if preview_pngs(export_dir):
        return None
    err = (proc.stderr or proc.stdout or "").strip() or "Keynote did not write PNG previews."
    if proc.returncode != 0:
        return f"Preview export failed: {err}"
    return err


def _truthy_cache(use_cache: bool | None, slide_range) -> bool:
    if slide_range:
        return False
    if use_cache is not None:
        return bool(use_cache)
    from obed_edom.settings import load_settings  # noqa: PLC0415

    return bool(load_settings()["reusePreviews"])


def inspect_keynote(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    use_cache: bool | None = None,
) -> dict[str, Any]:
    """Open a .key read-only, dump text/bounds, optionally export PNGs, close without saving."""
    key_path = Path(key_path).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"Keynote not found: {key_path}")
    timing: dict[str, float] = {}
    digest = ""
    want_cache = _truthy_cache(use_cache, slide_range)
    dest = Path(export_dir) if export_dir else None
    if dest:
        dest.mkdir(parents=True, exist_ok=True)

    if want_cache:
        from obed_edom.baseline import (  # noqa: PLC0415
            deck_digest,
            inspect_cache_path,
            preview_cache_dir,
        )

        t_hash = time.perf_counter()
        digest = deck_digest(key_path)
        timing["digest"] = time.perf_counter() - t_hash
        # Keyed per Keynote version, so a payload read by one build is never handed
        # to another.
        json_path = inspect_cache_path(digest)
        png_dir = preview_cache_dir(digest)
        pngs_ok = dest is None or bool(preview_pngs(png_dir))
        if json_path.is_file() and pngs_ok:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            payload["_cached"] = True
            payload["_digest"] = digest
            payload["_timing"] = timing
            if dest is not None:
                payload["previewDir"] = str(png_dir)
                payload["exported"] = bool(preview_pngs(png_dir))
            return payload
        if dest is not None:
            dest = png_dir
            dest.mkdir(parents=True, exist_ok=True)

    plan: dict[str, Any] = {
        "path": str(key_path),
        "close": True,
        "save": False,
        "bundleId": keynote_app.bundle_id(),
        "bulkRead": bulk_read_enabled(),
    }
    if dest:
        plan["exportDir"] = str(dest.resolve())
    wanted = slides_for_plan(slide_range)
    if wanted:
        plan["slides"] = wanted
        plan["range"] = [wanted[0], wanted[-1]]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        t_jxa = time.perf_counter()
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(INSPECT_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
        timing["jxa"] = time.perf_counter() - t_jxa
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Keynote inspect failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("Keynote inspect returned no JSON.")
    payload = json.loads(raw)
    # Best-effort per-run character style from the deck's offline IWA graph. On
    # when the optional `iwa` extra imports, gracefully off (runs stay []) when it
    # doesn't or the decode fails. Must run before the cache write below so runs
    # persist with the payload.
    try:
        from obed_edom.iwa_runs import attach_runs  # noqa: PLC0415

        attach_runs(key_path, payload)
    except Exception:  # noqa: BLE001 — missing extra / non-zip / decode error -> runs stay []
        pass
    # Persisted, so a payload can always say which Keynote read the deck.
    payload["keynoteBundleId"] = keynote_app.bundle_id()
    payload["keynoteVersion"] = keynote_app.app_version()
    # Provenance tag (persists past the cache-write underscore strip). CORRECTION: a
    # JXA payload is NOT runs-less — attach_runs ran above (line ~184) and sets runs[]
    # + groupedText. So inspect_keynote_checker's reject guards provenance CONSISTENCY
    # (don't diff an offline-composed deck against a JXA-geometry one), NOT a runs
    # under-report. Trade-off: a ~62s rebuild on a rare JXA(single-inspect)→checker
    # cache hit. Whether to keep this or narrow it (JXA payloads are valid + exact) is
    # a user design call — see the v2 plan handover.
    payload["reader"] = "jxa"
    if dest:
        t_export = time.perf_counter()
        pngs = preview_pngs(dest)
        if pngs:
            payload["exported"] = True
        else:
            fallback_err = export_slide_images(key_path, dest)
            payload["exported"] = bool(preview_pngs(dest))
            if not payload["exported"]:
                payload["exportError"] = fallback_err or payload.get("exportError") or ""
        timing["export"] = time.perf_counter() - t_export
        payload["previewDir"] = str(dest.resolve())
    payload["_timing"] = timing
    payload["_cached"] = False
    payload["_digest"] = digest
    if want_cache and digest and not slide_range:
        from obed_edom.baseline import inspect_cache_path  # noqa: PLC0415

        stored = {key: value for key, value in payload.items() if not str(key).startswith("_")}
        json_path = inspect_cache_path(digest)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(stored), encoding="utf-8")
    return payload


def bulk_geometry(
    key_path: Path | str,
    slides: list[int] | None = None,
) -> dict[int, dict[str, list[list[float]]]]:
    """Bulk-read Keynote's laid-out geometry for the three offline-soft classes.

    The "second tier" of the two-tier remap read (see
    :func:`obed_edom.offline_inspect.two_tier_wall_payload`): opens the deck once
    and, per slide, bulk-reads ONLY ``position``/``width``/``height`` of
    ``textItems``/``images``/``movies``/``groups`` — the collections whose geometry
    the offline IWA read cannot reproduce exactly. Runs ``bulk_geometry.js``, which
    is O(slides) in Apple Events (<= 12 per slide, none per object on the fast path).

    Returns ``{slideIndex: {kind: [[x, y, w, h], … by kindIndex]}}`` with the
    0-based DOCUMENT index as the key, matching ``offline_wall_payload``'s
    ``slides[].index``. A ``(slide, kind)`` the read could not evaluate is simply
    absent, so the caller can fall back for just that slide/kind rather than the
    whole deck. ``slides`` scopes the read to those 1-based document numbers (the
    ``slides_for_plan`` shape); ``None`` reads every slide.

    Raises ``RuntimeError`` on any osascript failure or unparseable output — the
    caller catches it and drops to the legacy read, so a broken bulk tier can never
    ship wrong geometry.
    """
    key_path = Path(key_path).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"Keynote not found: {key_path}")
    plan: dict[str, Any] = {
        "path": str(key_path),
        "bundleId": keynote_app.bundle_id(),
    }
    if slides:
        wanted = sorted({int(n) for n in slides})
        plan["slides"] = wanted
        plan["range"] = [wanted[0], wanted[-1]]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(BULK_GEOMETRY_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Bulk geometry read failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("Bulk geometry read returned no JSON.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Bulk geometry read returned invalid JSON: {exc}") from exc
    geometry = parsed.get("geometry") or {}
    # JSON object keys are strings; normalise back to the int slide index the
    # splice addresses by, and coerce every row to plain floats.
    out: dict[int, dict[str, list[list[float]]]] = {}
    for slide_key, kinds in geometry.items():
        rows_by_kind: dict[str, list[list[float]]] = {}
        for kind, rows in (kinds or {}).items():
            rows_by_kind[str(kind)] = [
                [float(v) for v in row] for row in (rows or [])
            ]
        out[int(slide_key)] = rows_by_kind
    return out


# --------------------------------------------------------------------------
# Item-scoped Keynote read (checker L4 item-level fallback).
#
# When the two-tier checker read leaves a handful of items unconfirmed (a soft
# frame the bulk read did not return, or a content guard the bulk read cannot
# touch — font-size-unresolved / filename-dirty), re-read ONLY those items rather
# than the whole slide. Reuses inspect_keynote.js's additive `plan.items` mode so
# every record is field-identical to a full inspect; the count guard there falls a
# whole slide back to the slide-level merge on any collection-count drift.
# --------------------------------------------------------------------------
def inspect_items(
    key_path: Path | str,
    items: list[dict[str, Any]],
    counts: dict[int, dict[str, int]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Describe ONLY ``items`` with a single scoped ``inspect_keynote.js`` pass.

    ``items`` is a list of ``{slide, kind, kindIndex}`` (1-based document
    ``slide``). Mirrors :func:`bulk_geometry`'s osascript invocation — builds a plan
    with ``path``/``bundleId``/``items`` (+ ``counts`` and ``textPlaceholderSlack``
    for the DSK17 count guard) and runs the SAME ``inspect_keynote.js`` in its
    additive ``plan.items`` mode, so each returned record is field-identical to a
    full inspect's ``describeItem``.

    ``counts`` is ``{slideNumber: {kind: expectedCount}}`` — the per-(slide, kind)
    item counts the offline payload expects, against which the JXA side reconciles
    the live collection size before addressing by ``kindIndex``.

    Returns ``{slideIndex0based: {"unreadable": bool, "records": {(kind, kindIndex):
    record}}}``. A slide the read could not address safely (count drift or an
    out-of-range kindIndex) comes back ``unreadable=True`` with no records, so the
    caller falls that whole slide back to the slide-level legacy merge. Raises
    ``RuntimeError`` on any osascript failure or unparseable output — the caller
    catches nothing extra here (the slide-level path can raise identically).
    """
    key_path = Path(key_path).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"Keynote not found: {key_path}")
    if not items:
        return {}
    from obed_edom.iwa_kindindex import TEXT_PLACEHOLDER_SLACK  # noqa: PLC0415

    plan: dict[str, Any] = {
        "path": str(key_path),
        "bundleId": keynote_app.bundle_id(),
        "items": [
            {
                "slide": int(it["slide"]),
                "kind": str(it["kind"]),
                "kindIndex": int(it["kindIndex"]),
            }
            for it in items
        ],
        "textPlaceholderSlack": int(TEXT_PLACEHOLDER_SLACK),
    }
    if counts:
        plan["counts"] = {
            str(int(slide)): {str(k): int(v) for k, v in kinds.items()}
            for slide, kinds in counts.items()
        }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(INSPECT_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Item-scoped inspect failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("Item-scoped inspect returned no JSON.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Item-scoped inspect returned invalid JSON: {exc}") from exc
    items_by_slide = parsed.get("itemsBySlide") or {}
    out: dict[int, dict[str, Any]] = {}
    for slide_key, result in items_by_slide.items():
        records: dict[tuple[str, int], dict[str, Any]] = {}
        for rec in (result or {}).get("items") or []:
            records[(str(rec.get("kind")), int(rec.get("kindIndex", -1)))] = rec
        out[int(slide_key)] = {
            "unreadable": bool((result or {}).get("unreadable")),
            "records": records,
        }
    return out


def _partition_fallback(
    fallback: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Split per-item fallback entries into item-scoped reads vs slide-level reads.

    Groups ``fallback`` (each ``{slide, kind, kindIndex, reason}``) by document
    number. A slide whose entries are ALL item-addressable — no ``count-mismatch``
    reason and every ``kindIndex >= 0`` — is read item-scoped (its entries go in the
    first list). Any slide carrying a ``count-mismatch`` entry (or a ``kindIndex <
    0``) goes whole-slide (its number in the second list), preserving the DSK17
    count-drift safety net.
    """
    from collections import defaultdict  # noqa: PLC0415

    by_slide: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for flag in fallback:
        by_slide[int(flag["slide"])].append(flag)
    item_entries: list[dict[str, Any]] = []
    slide_numbers: list[int] = []
    for number, entries in by_slide.items():
        addressable = all(
            entry.get("reason") != "count-mismatch"
            and int(entry.get("kindIndex", -1)) >= 0
            for entry in entries
        )
        if addressable:
            item_entries.extend(
                {
                    "slide": number,
                    "kind": entry["kind"],
                    "kindIndex": int(entry["kindIndex"]),
                }
                for entry in entries
            )
        else:
            slide_numbers.append(number)
    return item_entries, sorted(slide_numbers)


# The item addressing keys the splice must KEEP from the offline item (never let a
# JXA record's own index clobber them): the payload's item order and (kind,kindIndex)
# address are authoritative and identical across both reads.
_ITEM_ADDRESS_KEYS = ("index", "kindIndex")


def _splice_item_record(item: dict[str, Any], rec: dict[str, Any]) -> None:
    """Overwrite ``item`` with the JXA ``rec``'s fields, keeping offline addressing.

    ``rec`` is a full ``describeItem`` record, so this replaces exactly the fields a
    whole-slide :func:`obed_edom.remap_keynote._merge_legacy_slides` would (it swaps
    the entire item for the JXA one). Offline-only fields the JXA record does not
    carry — ``runs`` (attach_runs) and a ``duplicateOf`` the offline read set — are
    left in place, matching what the slide-level path lands after its own attach_runs.
    """
    saved = {key: item.get(key) for key in _ITEM_ADDRESS_KEYS}
    item.update(rec)
    for key, value in saved.items():
        if value is not None:
            item[key] = value


def _merge_legacy_items(
    payload: dict[str, Any], source: Path, item_entries: list[dict[str, Any]]
) -> list[int]:
    """Splice item-scoped Keynote reads over the matching payload items, in place.

    ``item_entries`` is the item-addressable fallback set (``{slide, kind,
    kindIndex}``). Each referenced item is re-read with one scoped
    :func:`inspect_items` pass and spliced over the offline item of the same
    ``(slide, kind, kindIndex)`` (:func:`_splice_item_record`). Any slide the item
    read could not address safely (count drift / out-of-range) is routed through the
    whole-slide :func:`obed_edom.remap_keynote._merge_legacy_slides` instead — the
    DSK17 net — and returned in the list so the caller can log it.
    """
    if not item_entries:
        return []
    # Expected per-(slide, kind) counts from the offline payload: the count guard's
    # reference. A live collection whose size drifted from these forces the slide to
    # the slide-level merge rather than a mis-addressed splice.
    referenced = {int(entry["slide"]) for entry in item_entries}
    by_number = {
        int(slide.get("number") or (int(slide.get("index") or 0) + 1)): slide
        for slide in payload.get("slides") or []
    }
    counts: dict[int, dict[str, int]] = {}
    for number in referenced:
        slide = by_number.get(number)
        if slide is None:
            continue
        per_kind: dict[str, int] = {}
        for item in slide.get("items") or []:
            kind = item.get("kind")
            per_kind[kind] = per_kind.get(kind, 0) + 1
        counts[number] = per_kind
    reads = inspect_items(source, item_entries, counts=counts)
    unreadable_numbers: list[int] = []
    for slide in payload.get("slides") or []:
        index0 = int(slide.get("index") or 0)
        number = int(slide.get("number") or (index0 + 1))
        result = reads.get(index0)
        if result is None:
            continue
        if result.get("unreadable"):
            unreadable_numbers.append(number)
            continue
        records = result.get("records") or {}
        for item in slide.get("items") or []:
            rec = records.get((str(item.get("kind")), int(item.get("kindIndex", -1))))
            if rec is not None:
                _splice_item_record(item, rec)
    if unreadable_numbers:
        from obed_edom.remap_keynote import _merge_legacy_slides  # noqa: PLC0415

        _merge_legacy_slides(payload, source, sorted(unreadable_numbers))
    return sorted(unreadable_numbers)


# --------------------------------------------------------------------------
# Checker-scoped offline inspect (Sermon Checker cold read).
#
# The two Sermon Checker call sites (web.app._run_diff) switch from the ~5-min
# per-slide JXA inspect_keynote to the validated offline IWA read + a slim
# O(slides) bulk-geometry pass — measured ~3.25x faster, overflow-flag-identical.
# Checker-SCOPED: inspect_keynote's other callers (framing, single-inspect, remap
# template/readback) stay on the JXA path. The payload is a byte-shape drop-in, so
# compare_inspects / deck_slide_digests / validate_inspect are untouched.
#
# CACHE-SCOPE CAVEAT: this writes the SAME digest-keyed cache inspect_keynote reads,
# so a later inspect_keynote(same deck) — e.g. single-inspect (web.app:_run_inspect) —
# would serve this OFFLINE payload (no group childCount/children, composed rotation)
# rather than a fresh JXA read. Harmless today: no inspect_keynote consumer reads
# childCount on a sermon deck, and rotation is drop-in for them. Revisit if a future
# consumer of a checker deck's cache needs JXA-native childCount or exact rotation.
# --------------------------------------------------------------------------
def _build_checker_offline(key_path: Path, bulk_geometry_fn: Any) -> dict[str, Any]:
    """The offline IWA + bulk-geometry checker payload, before export/cache.

    ``two_tier_wall_payload`` (offline addressing/style/shapes/lines + a bulk
    Keynote read overwriting the three offline-soft classes' geometry) with per-run
    character style and grouped text attached (``iwa_runs.attach_runs`` sets both
    ``item["runs"]`` and ``slide["groupedText"]``), and a ``master`` default so the
    slide shape matches JXA's. Split out from :func:`inspect_keynote_checker` so the
    offline assembly can be A/B-validated against a cached JXA payload with a
    test-double ``bulk_geometry_fn``, no Keynote. Raises ``ImportError`` when the
    ``iwa`` extra is absent (the caller drops the whole deck to the JXA inspect).
    """
    from obed_edom.iwa_runs import _load_deck, attach_runs  # noqa: PLC0415
    from obed_edom.offline_inspect import two_tier_wall_payload  # noqa: PLC0415

    # Decode the IWA graph ONCE and share it across both readers (the offline
    # addressing/geometry pass and the per-run/grouped-text pass) — each used to
    # decode the deck independently (~0.4-1s/deck). A missing `iwa` extra raises
    # ImportError here, which the caller drops to the legacy JXA inspect.
    deck = _load_deck(key_path)
    payload = two_tier_wall_payload(key_path, bulk_geometry_fn=bulk_geometry_fn, deck=deck)
    try:
        attach_runs(key_path, payload, deck=deck)
    except Exception:  # noqa: BLE001 — run-matching error leaves runs=[] / no groupedText
        pass
    # JXA emits `master` on every slide; the offline read does not consult it (the
    # checker never reads it either), so default it for shape parity.
    for slide in payload.get("slides") or []:
        slide.setdefault("master", "")
    return payload


def inspect_keynote_checker(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    use_cache: bool | None = None,
) -> dict[str, Any]:
    """A drop-in for :func:`inspect_keynote` at the two Sermon Checker call sites.

    Builds the payload from the deck's IWA graph (text/runs/style/addressing/shapes/
    lines) instead of the per-slide JXA read, overwrites the three offline-soft
    classes' geometry (groups, masked/rotated images, autosize text) with a slim
    O(slides) bulk Keynote read (:func:`bulk_geometry`), attaches per-run character
    style and grouped text, and exports the PNG previews the checker shows.

    Fallback is fail-safe to today's behaviour:
      * missing ``iwa`` extra / decode error / bulk read raises entirely -> the whole
        deck drops to the legacy :func:`inspect_keynote` (JXA);
      * any slide the bulk read could not confirm, or that carries a content guard
        flag the bulk read cannot touch (font-size-unresolved / filename-dirty), is
        re-read with one scoped JXA :func:`inspect_keynote` and spliced back
        (:func:`obed_edom.remap_keynote._merge_legacy_slides`).

    The payload is a byte-shape drop-in (same top-level and per-slide/per-item fields
    as :func:`inspect_keynote`), and is cached under the same digest-keyed path so a
    warm rerun skips Keynote entirely.
    """
    key_path = Path(key_path).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"Keynote not found: {key_path}")
    timing: dict[str, float] = {}
    want_cache = _truthy_cache(use_cache, None)
    dest = Path(export_dir) if export_dir else None

    from obed_edom.baseline import (  # noqa: PLC0415
        deck_digest,
        inspect_cache_path,
        preview_cache_dir,
    )

    digest = ""
    png_dir: Path | None = None
    if want_cache:
        t_hash = time.perf_counter()
        digest = deck_digest(key_path)
        timing["digest"] = time.perf_counter() - t_hash
        json_path = inspect_cache_path(digest)
        png_dir = preview_cache_dir(digest)
        if json_path.is_file():
            cached = json.loads(json_path.read_text(encoding="utf-8"))
            # REVERSE CROSS-SERVE GUARD: only serve a payload this checker built
            # (offline IWA + attach_runs). A JXA / single-inspect payload cached
            # under the SHARED digest carries NO runs[] (inspect_keynote.js emits
            # none), so serving it to a diff would skip attach_runs and silently
            # under-report highlight/small-caps/style diffs. A missing `reader`
            # (legacy pre-provenance payload) is rejected too — fall through and
            # rebuild the offline payload.
            if cached.get("reader") == "offline":
                slide_count = int(
                    cached.get("slideCount") or len(cached.get("slides") or [])
                )
                have = 0 if png_dir is None else len(preview_pngs(png_dir))
                # HARDENED HIT: require the FULL preview set (export uses skipped
                # slides:false, so a complete run has exactly slideCount PNGs), else
                # a partial export would be served forever from the digest-keyed dir.
                if dest is None or have == slide_count:
                    cached["_cached"] = True
                    cached["_digest"] = digest
                    cached["_timing"] = timing
                    if dest is not None:
                        cached["previewDir"] = str(png_dir)
                        cached["exported"] = bool(preview_pngs(png_dir))
                    return cached
                # JSON cached but previews evicted/partial and an export is wanted:
                # run ONLY the export (~32s the checker needs), never the ~62s
                # offline+bulk rebuild.
                png_dir.mkdir(parents=True, exist_ok=True)
                t_export = time.perf_counter()
                err = export_slide_images(key_path, png_dir)
                cached["_cached"] = True
                cached["_digest"] = digest
                cached["exported"] = bool(preview_pngs(png_dir))
                if not cached["exported"]:
                    cached["exportError"] = err or cached.get("exportError") or ""
                cached["previewDir"] = str(png_dir)
                timing["export"] = time.perf_counter() - t_export
                cached["_timing"] = timing
                return cached

    # Build the offline+bulk payload; a hard failure drops the whole deck to legacy.
    t_read = time.perf_counter()
    try:
        payload = _build_checker_offline(key_path, bulk_geometry)
    except Exception:  # noqa: BLE001 — missing iwa extra / decode error -> legacy JXA
        return inspect_keynote(key_path, export_dir=export_dir, use_cache=use_cache)
    sidecar = payload.get("_offline") or {}
    fallback = sidecar.get("fallback") or []
    fallback_slides = sidecar.get("fallback_slides") or []
    # Bulk tier entirely unavailable AND soft classes unconfirmed: the offline
    # geometry alone cannot be trusted, so read the whole deck the legacy way.
    if not sidecar.get("bulk_ok") and fallback_slides:
        return inspect_keynote(key_path, export_dir=export_dir, use_cache=use_cache)
    # Granular fallback, per item where possible (L4). A slide whose unconfirmed
    # items are ALL item-addressable (no count-mismatch, kindIndex >= 0) is re-read
    # item-scoped — only those objects, not the whole slide. A slide with a
    # count-mismatch entry (kindIndex desync, the DSK17 class) falls back whole via
    # the slide-level merge. Both land the SAME payload the old slide-level path did,
    # read more cheaply. The resizer caller (acquire_wall_payload) is unchanged.
    if fallback:
        item_entries, slide_numbers = _partition_fallback(fallback)
        if item_entries:
            _merge_legacy_items(payload, key_path, item_entries)
        if slide_numbers:
            from obed_edom.remap_keynote import _merge_legacy_slides  # noqa: PLC0415

            _merge_legacy_slides(payload, key_path, slide_numbers)
    timing["read"] = time.perf_counter() - t_read

    payload["path"] = str(key_path)
    payload["keynoteBundleId"] = keynote_app.bundle_id()
    payload["keynoteVersion"] = keynote_app.app_version()
    # Provenance: the offline IWA reader (runs[] attached). Persists past the
    # cache-write underscore strip; the cache-read above serves ONLY this reader.
    payload["reader"] = "offline"
    payload.setdefault("exported", False)

    export_target = dest
    if want_cache and dest is not None and png_dir is not None:
        export_target = png_dir
    if export_target is not None:
        export_target = Path(export_target)
        export_target.mkdir(parents=True, exist_ok=True)
        t_export = time.perf_counter()
        err: str | None = None
        if not preview_pngs(export_target):
            err = export_slide_images(key_path, export_target)
        payload["exported"] = bool(preview_pngs(export_target))
        if not payload["exported"]:
            payload["exportError"] = err or payload.get("exportError") or ""
        timing["export"] = time.perf_counter() - t_export
        payload["previewDir"] = str(export_target.resolve())

    payload["_timing"] = timing
    payload["_cached"] = False
    payload["_digest"] = digest
    if want_cache and digest:
        json_path = inspect_cache_path(digest)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        stored = {key: value for key, value in payload.items() if not str(key).startswith("_")}
        json_path.write_text(json.dumps(stored), encoding="utf-8")
    return payload


PREVIEW_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PREVIEW_VIDEO_SUFFIXES = {".mov"}
PREVIEW_MEDIA_SUFFIXES = PREVIEW_IMAGE_SUFFIXES | PREVIEW_VIDEO_SUFFIXES

_PREVIEW_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mov": "video/quicktime",
}


def cached_payload(key_path: Path | str) -> dict[str, Any] | None:
    """A previously inspected payload, or None. Never opens Keynote.

    For callers that want the deck's contents but must not cost a pass: a cache
    miss is a normal answer, not a reason to go and read 158 slides.
    """
    from obed_edom.baseline import deck_digest, inspect_cache_path  # noqa: PLC0415

    key_path = Path(key_path).expanduser()
    if not key_path.exists():
        return None
    try:
        json_path = inspect_cache_path(deck_digest(key_path))
        if not json_path.is_file():
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["_cached"] = True
    return payload


def preview_media_type(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    return _PREVIEW_MEDIA_TYPES.get(ext, "application/octet-stream")


def preview_media(folder: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """Preview stills and QuickTime movies in a folder (JPEG/PNG/.mov)."""
    allowed = {s.lower() for s in (suffixes or PREVIEW_MEDIA_SUFFIXES)}
    if not folder.is_dir():
        return []

    def collect(paths: list[Path]) -> list[Path]:
        seen: set[str] = set()
        out: list[Path] = []
        for path in sorted(paths, key=lambda p: p.name.lower()):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
        return out

    files = collect(list(folder.iterdir()))
    if files:
        return files
    return collect([p for p in folder.rglob("*") if p.is_file()])


def preview_pngs(folder: Path) -> list[Path]:
    return preview_media(folder, suffixes={".png"})


_PREVIEW_NUM = re.compile(r"(\d+)")


def preview_slide_number(name: str, index: int) -> int:
    found = _PREVIEW_NUM.findall(Path(name).stem)
    return int(found[-1]) if found else index + 1


def preview_inspect(folder: Path | str) -> dict[str, Any]:
    """Synthetic inspect payload from a folder of stills (and skipped movies)."""
    folder = Path(folder)
    files = preview_media(folder)
    width, height = 1920.0, 1080.0
    for path in files:
        if path.suffix.lower() in PREVIEW_VIDEO_SUFFIXES:
            continue
        try:
            from obed_edom.images import image_size  # noqa: PLC0415

            size = image_size(path)
        except Exception:  # noqa: BLE001
            size = None
        if size:
            width, height = float(size[0]), float(size[1])
            break
    slides: list[dict[str, Any]] = []
    for i, path in enumerate(files):
        slides.append(
            {
                "index": i,
                "number": preview_slide_number(path.name, i),
                "skipped": False,
                "items": [],
            }
        )
    return {
        "path": str(folder),
        "slideWidth": width,
        "slideHeight": height,
        "slideCount": len(slides),
        "slides": slides,
    }


def is_duplicate_item(item: dict) -> bool:
    """A text-bearing shape that Keynote also listed under textItems.

    Both records point at one object, so acting on both moves it twice and
    counts its text twice. inspect_keynote.js marks the shape copy; the text
    copy is the one to keep, since it carries the font and size.
    """
    return bool(item.get("duplicateOf"))


def _walk_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        if is_duplicate_item(item):
            continue
        yield item
        yield from _walk_items(item)


def slide_plain_text(slide: dict, *, include_grouped: bool = False) -> str:
    """Plain text of a slide's visible items.

    ``include_grouped`` opts in the slide-level ``groupedText`` (copy inside a
    group, which JXA reports as ``childCount 0`` so it never reaches ``items``).
    It is OFF by default so the reuse fingerprint (``baseline.deck_slide_digests``)
    stays byte-identical; only the checker's text-SCORING path turns it on.
    """
    parts: list[str] = []
    for item in _walk_items(slide):
        text = (item.get("text") or "").strip()
        if text:
            parts.append(text)
    if include_grouped:
        for grouped in slide.get("groupedText") or []:
            text = (grouped.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def all_plain_text(payload: dict) -> str:
    return "\n\n".join(slide_plain_text(s) for s in payload.get("slides") or [])


def highlighted_markup(slide: dict) -> str:
    """Approximate *highlighted* wrapping from colour runs when available."""
    chunks: list[str] = []
    for item in slide.get("items") or []:
        runs = item.get("runs") or []
        if not runs:
            text = item.get("text") or ""
            if text:
                chunks.append(text)
            continue
        buf: list[str] = []
        for run in runs:
            text = run.get("text") or ""
            if _looks_highlight(run.get("color")):
                buf.append(f"*{text}*")
            else:
                buf.append(text)
        chunks.append("".join(buf))
    return "\n".join(chunks)


def _looks_highlight(color: list | None) -> bool:
    if not color or len(color) < 3:
        return False
    r, g, b = color[0], color[1], color[2]
    # Keynote RGB is often 0–65535. Yellow/gold highlight is high R+G, low B.
    scale = 65535 if max(r, g, b) > 255 else 255
    rn, gn, bn = r / scale, g / scale, b / scale
    return rn > 0.7 and gn > 0.45 and bn < 0.45


def diff_work_dir(job_id: str) -> Path:
    root = output_root() / ".diff" / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root

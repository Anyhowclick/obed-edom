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
    """``OBED_BULK_READ=0`` forces per-object; JS falls back on length drift."""
    return os.environ.get("OBED_BULK_READ", "").strip().lower() not in {"0", "false", "no", "off"}


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def export_applescript(key_path: Path, export_dir: Path) -> str:
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
    try:
        from obed_edom.iwa_runs import attach_runs  # noqa: PLC0415

        attach_runs(key_path, payload)
    except Exception:  # noqa: BLE001 — missing extra / non-zip / decode error -> runs stay []
        pass
    payload["keynoteBundleId"] = keynote_app.bundle_id()
    payload["keynoteVersion"] = keynote_app.app_version()
    payload["reader"] = "jxa"  # persists past the cache-write underscore strip
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


LAST_BULK_ERRORS: list[dict[str, Any]] = []
LAST_BULK_NOTES: list[dict[str, Any]] = []


def _log_bulk_errors(errors: list[dict[str, Any]], error_count: int, log: Any) -> None:
    if not errors or log is None:
        return
    total = error_count if error_count else len(errors)
    log(f"Bulk geometry: {len(errors)} of {total} per-collection/item error(s) (first 5 shown):")
    for e in errors[:5]:
        log(f"  slide={e.get('slide')} kind={e.get('kind')} where={e.get('where')}: {e.get('error')}")


def _log_bulk_notes(notes: list[dict[str, Any]], note_count: int, log: Any) -> None:
    if not notes or log is None:
        return
    total = note_count if note_count else len(notes)
    log(f"Bulk geometry: {total} note(s) (informational, e.g. a bulk-array length drift).")


def bulk_geometry(
    key_path: Path | str,
    slides: list[int] | None = None,
    *,
    log: Any = None,
) -> dict[int, dict[str, list[list[float]]]]:
    """{slide (0-based): {kind: [[x, y, w, h], ...]}}. bulk_geometry.js's own per-
    collection/bulk-property/item FAILURES (otherwise invisible -- that kind just gets
    omitted) land in `LAST_BULK_ERRORS` (replaced every call); informational drift NOTES
    (e.g. a bulk array whose length didn't match, harmlessly covered by the per-item
    fallback) land separately in `LAST_BULK_NOTES`. Both are stamped with this call's own
    `path` (a caller snapshotting them must never accidentally pick up a DIFFERENT
    key_path's leftovers). Logged here (first 5 errors + total; notes just a count) via
    `log` -- default `None` (library code never prints on its own; pass `log=print` or an
    operator `say` explicitly)."""
    global LAST_BULK_ERRORS, LAST_BULK_NOTES
    LAST_BULK_ERRORS = []
    LAST_BULK_NOTES = []
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
    if parsed.get("error"):
        # bulk_geometry.js's own Keynote.open/doc.slides() guard: an open/slides
        # failure must be LOUD, never a silent empty-geometry "bulk-missing" fallback.
        raise RuntimeError(f"Bulk geometry read failed: {parsed['error']}")
    path_str = str(key_path)
    LAST_BULK_ERRORS = [{**e, "path": path_str} for e in (parsed.get("errors") or [])]
    LAST_BULK_NOTES = [{**n, "path": path_str} for n in (parsed.get("notes") or [])]
    _log_bulk_errors(LAST_BULK_ERRORS, int(parsed.get("errorCount") or 0), log)
    _log_bulk_notes(LAST_BULK_NOTES, int(parsed.get("noteCount") or 0), log)
    geometry = parsed.get("geometry") or {}
    out: dict[int, dict[str, list[list[float]]]] = {}
    for slide_key, kinds in geometry.items():
        rows_by_kind: dict[str, list[list[float]]] = {}
        for kind, rows in (kinds or {}).items():
            rows_by_kind[str(kind)] = [
                [float(v) for v in row] for row in (rows or [])
            ]
        out[int(slide_key)] = rows_by_kind
    return out


def inspect_items(
    key_path: Path | str,
    items: list[dict[str, Any]],
    counts: dict[int, dict[str, int]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Count drift / OOR kindIndex → ``unreadable`` (whole-slide fallback)."""
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
    """``count-mismatch`` or ``kindIndex < 0`` stays whole-slide (kindIndex desync)."""
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


# Offline addressing wins: never let a JXA record's own index clobber kindIndex/order.
_ITEM_ADDRESS_KEYS = ("index", "kindIndex")


def _splice_item_record(item: dict[str, Any], rec: dict[str, Any]) -> None:
    saved = {key: item.get(key) for key in _ITEM_ADDRESS_KEYS}
    item.update(rec)
    for key, value in saved.items():
        if value is not None:
            item[key] = value


def _merge_legacy_items(
    payload: dict[str, Any], source: Path, item_entries: list[dict[str, Any]]
) -> list[int]:
    """Unreadable slides go whole-slide (kindIndex desync)."""
    if not item_entries:
        return []
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


def _build_checker_offline(key_path: Path, bulk_geometry_fn: Any, *, log: Any = None) -> dict[str, Any]:
    """Two-tier IWA + attach_runs; one decode. Raises ImportError without ``iwa``."""
    from obed_edom.iwa_runs import _load_deck, attach_runs  # noqa: PLC0415
    from obed_edom.offline_inspect import two_tier_wall_payload  # noqa: PLC0415

    deck = _load_deck(key_path)
    payload = two_tier_wall_payload(key_path, bulk_geometry_fn=bulk_geometry_fn, deck=deck, log=log)
    try:
        attach_runs(key_path, payload, deck=deck)
    except Exception:  # noqa: BLE001 — run-matching error leaves runs=[] / no groupedText
        pass
    for slide in payload.get("slides") or []:
        slide.setdefault("master", "")  # JXA shape parity; checker never reads master
    return payload


def inspect_keynote_checker(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    use_cache: bool | None = None,
    log: Any = None,
) -> dict[str, Any]:
    """Shares digest cache; serve only ``reader==offline`` hits. ``log`` defaults to
    ``None`` (library code never prints on its own) -- pass ``log=print`` or an operator
    ``say`` explicitly to see the cache-hit ``bulkErrors`` WARN."""
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
            # Shared digest cache: a JXA hit has no runs[]; serving it would skip attach_runs.
            if cached.get("reader") == "offline":
                bulk_errors = cached.get("bulkErrors") or []
                if bulk_errors and log is not None:
                    log(f"WARN: cached offline read for {key_path.name} carries "
                        f"{len(bulk_errors)} bulk-geometry error(s) from when it was built "
                        "(see bulkErrors) -- the cache may be serving a silent-partial read.")
                slides = cached.get("slides") or []
                slide_count = int(cached.get("slideCount") or len(slides))
                # Export skips skipped slides; expected PNGs = slideCount − skipped, else a skip-deck never hits.
                skipped = sum(1 for slide in slides if slide.get("skipped"))
                expected_pngs = slide_count - skipped
                have = 0 if png_dir is None else len(preview_pngs(png_dir))
                if dest is None or have == expected_pngs:
                    cached["_cached"] = True
                    cached["_digest"] = digest
                    cached["_timing"] = timing
                    if dest is not None:
                        cached["previewDir"] = str(png_dir)
                        cached["exported"] = bool(preview_pngs(png_dir))
                    return cached
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

    t_read = time.perf_counter()
    try:
        payload = _build_checker_offline(key_path, bulk_geometry, log=log)
    except Exception:  # noqa: BLE001 — missing iwa extra / decode error -> legacy JXA
        return inspect_keynote(key_path, export_dir=export_dir, use_cache=use_cache)
    sidecar = payload.get("_offline") or {}
    fallback = sidecar.get("fallback") or []
    fallback_slides = sidecar.get("fallback_slides") or []
    if not sidecar.get("bulk_ok") and fallback_slides:
        return inspect_keynote(key_path, export_dir=export_dir, use_cache=use_cache)
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
    payload["reader"] = "offline"  # persists past the cache-write underscore strip
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
    """Never opens Keynote."""
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
    """Shape copy of a textItems object; acting on both moves it twice."""
    return bool(item.get("duplicateOf"))


def _walk_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        if is_duplicate_item(item):
            continue
        yield item
        yield from _walk_items(item)


def slide_plain_text(slide: dict, *, include_grouped: bool = False) -> str:
    """``include_grouped`` opts in group copy (JXA childCount 0). Off for reuse fingerprints."""
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

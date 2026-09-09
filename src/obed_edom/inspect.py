from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from obed_edom import keynote_app
from obed_edom.map_remap import slides_for_plan
from obed_edom.paths import output_root

INSPECT_JS = Path(__file__).resolve().parent / "inspect_keynote.js"
BULK_GEOMETRY_JS = Path(__file__).resolve().parent / "bulk_geometry.js"

# In-process only; one dashboard process drives one Keynote instance.
_KEYNOTE_LOCK = threading.RLock()


def bulk_read_enabled() -> bool:
    """``OBED_BULK_READ=0`` forces per-object; JS falls back on length drift."""
    return os.environ.get("OBED_BULK_READ", "").strip().lower() not in {"0", "false", "no", "off"}


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _bind_and_export_lines(stem: str, dest: str) -> list[str]:
    """Exact-name bind + export; closes by name and re-raises on failure. Shared by
    the standalone and already-open script forms."""
    return [
        "    try",
        f'      set theDocs to (every document whose name is "{stem}" or name is "{stem}.key")',
        f'      if (count of theDocs) is 0 then error '
        f'"export: no open document named \\"{stem}\\" or \\"{stem}.key\\""',
        "      set theDoc to item 1 of theDocs",
        f'      set exportFolder to POSIX file "{dest}"',
        "      export theDoc to exportFolder as slide images with properties "
        "{image format:PNG, skipped slides:false}",
        "    on error errMsg number errNum",
        "      try",
        f'        close (every document whose name is "{stem}") saving no',
        f'        close (every document whose name is "{stem}.key") saving no',
        "      end try",
        "      error errMsg number errNum",
        "    end try",
        "    try",
        "      close theDoc saving no",
        "    end try",
    ]


def export_applescript(key_path: Path, export_dir: Path) -> str:
    """Close-by-name -> open -> exact-name bind -> export -> close saving no."""
    key = _as_escape(str(Path(key_path).resolve()))
    dest = _as_escape(str(Path(export_dir).resolve()))
    app = keynote_app.bundle_id()
    stem = _as_escape(Path(key_path).stem)
    return "\n".join(
        [
            f'using terms from application id "{app}"',
            f'tell application id "{app}"',
            "  activate",
            "  with timeout of 3600 seconds",
            "    try",
            f'      close (every document whose name is "{stem}") saving no',
            f'      close (every document whose name is "{stem}.key") saving no',
            "      delay 0.3",
            "    end try",
            f'    set theFile to POSIX file "{key}"',
            "    open theFile",
            "    delay 0.4",
            *_bind_and_export_lines(stem, dest),
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def _export_open_applescript(key_path: Path, export_dir: Path) -> str:
    """Already-open handoff form: no close-by-name, no ``open``. Never leaves the
    document open."""
    dest = _as_escape(str(Path(export_dir).resolve()))
    app = keynote_app.bundle_id()
    stem = _as_escape(Path(key_path).stem)
    return "\n".join(
        [
            f'using terms from application id "{app}"',
            f'tell application id "{app}"',
            "  activate",
            "  with timeout of 3600 seconds",
            *_bind_and_export_lines(stem, dest),
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def _close_document_by_name(key_path: Path) -> None:
    """Best-effort cleanup for a document left open by a failed handoff. Never launches Keynote."""
    stem = _as_escape(Path(key_path).stem)
    app = keynote_app.bundle_id()
    script = "\n".join(
        [
            f'using terms from application id "{app}"',
            f'tell application id "{app}"',
            f'  if application id "{app}" is running then',
            f'    close (every document whose name is "{stem}" or name is "{stem}.key") saving no',
            "  end if",
            "end tell",
            "end using terms from",
        ]
    )
    with _KEYNOTE_LOCK:
        with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
            handle.write(script)
            script_path = Path(handle.name)
        try:
            subprocess.run(["osascript", str(script_path)], capture_output=True, text=True, check=False)
        except Exception:  # noqa: BLE001 — best-effort cleanup must never mask the original failure
            pass
        finally:
            script_path.unlink(missing_ok=True)


def _run_applescript_export(
    script: str, export_dir: Path, *, expected: int | None = None
) -> str | None:
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
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
    err = (proc.stderr or proc.stdout or "").strip() or "Keynote did not write PNG previews."
    if proc.returncode != 0:
        return f"Preview export failed: {err}"
    pngs = preview_pngs(export_dir)
    if expected is not None:
        if len(pngs) != expected:
            return f"Preview export wrote {len(pngs)} of {expected} PNGs"
        return None
    if pngs:
        return None
    return err


def export_slide_images(
    key_path: Path, export_dir: Path, *, expected: int | None = None
) -> str | None:
    with _KEYNOTE_LOCK:
        script = export_applescript(key_path, export_dir)
        subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
        time.sleep(0.4)
        return _run_applescript_export(script, export_dir, expected=expected)


def _export_open_slide_images(
    key_path: Path, export_dir: Path, *, expected: int | None = None
) -> str | None:
    """The keep-open handoff's exporter: the doc is already open, so no ``open -b`` /
    activation delay is needed."""
    with _KEYNOTE_LOCK:
        script = _export_open_applescript(key_path, export_dir)
        return _run_applescript_export(script, export_dir, expected=expected)


def _expected_pngs(payload: dict[str, Any]) -> int:
    slides = payload.get("slides") or []
    slide_count = int(payload.get("slideCount") or len(slides))
    skipped = sum(1 for slide in slides if slide.get("skipped"))
    return slide_count - skipped


def _set_export_state(
    payload: dict[str, Any],
    export_dir: Path,
    error: str | None = None,
    *,
    failed: bool = False,
    expected: int | None = None,
) -> bool:
    if failed and error:
        payload["exported"] = False
        payload["exportError"] = error
        return False
    pngs = preview_pngs(export_dir)
    exported = len(pngs) == expected if expected is not None else bool(pngs)
    payload["exported"] = exported
    if exported:
        payload.pop("exportError", None)
    elif failed:
        payload["exportError"] = error or payload.get("exportError") or ""
    return exported


def _truthy_cache(use_cache: bool | None, slide_range) -> bool:
    if slide_range:
        return False
    if use_cache is not None:
        return bool(use_cache)
    from obed_edom.settings import load_settings  # noqa: PLC0415

    return bool(load_settings()["reusePreviews"])


class LegacyInspectFailed(RuntimeError):
    """Legacy JXA inspect already ran and failed inside the checker; a caller's own legacy
    fallback must not retry it (a second ~12min Keynote session buys nothing)."""


def _raise_if_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled and is_cancelled():
        raise RuntimeError("Export cancelled.")


def _run_jxa_inspect(
    args: list[str], is_cancelled: Callable[[], bool] | None
) -> subprocess.CompletedProcess[str]:
    _raise_if_cancelled(is_cancelled)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = subprocess.Popen(args, stdout=stdout, stderr=stderr)
        while proc.poll() is None:
            if is_cancelled and is_cancelled():
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise RuntimeError("Export cancelled.")
            time.sleep(0.05)
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            proc.args,
            proc.returncode,
            stdout.read().decode("utf-8", "replace"),
            stderr.read().decode("utf-8", "replace"),
        )


def inspect_keynote(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    use_cache: bool | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    _raise_if_cancelled(is_cancelled)
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
        if json_path.is_file():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            expected_pngs = _expected_pngs(payload)
            have = 0 if png_dir is None else len(preview_pngs(png_dir))
            if dest is None or have == expected_pngs:
                payload["_cached"] = True
                payload["_digest"] = digest
                payload["_timing"] = timing
                if dest is not None:
                    payload["previewDir"] = str(png_dir)
                    _set_export_state(payload, png_dir, expected=expected_pngs)
                return payload
            png_dir.mkdir(parents=True, exist_ok=True)
            t_export = time.perf_counter()
            err = export_slide_images(key_path, png_dir, expected=expected_pngs)
            payload["_cached"] = True
            payload["_digest"] = digest
            _set_export_state(payload, png_dir, err, failed=True, expected=expected_pngs)
            payload["previewDir"] = str(png_dir)
            timing["export"] = time.perf_counter() - t_export
            payload["_timing"] = timing
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
    wanted = slides_for_plan(slide_range)
    if wanted:
        plan["slides"] = wanted
        plan["range"] = [wanted[0], wanted[-1]]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    with _KEYNOTE_LOCK:
        try:
            t_jxa = time.perf_counter()
            proc = _run_jxa_inspect(
                ["osascript", "-l", "JavaScript", str(INSPECT_JS), plan_path], is_cancelled
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
            expected_pngs = _expected_pngs(payload)
            if len(preview_pngs(dest)) == expected_pngs:
                _set_export_state(payload, dest, expected=expected_pngs)
            else:
                fallback_err = export_slide_images(key_path, dest, expected=expected_pngs)
                _set_export_state(payload, dest, fallback_err, failed=True, expected=expected_pngs)
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
LAST_BULK_KEPT_OPEN: str | None = None


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
    keep_open: bool = False,
    log: Any = None,
) -> dict[int, dict[str, list[list[float]]]]:
    """{slide (0-based): {kind: [[x, y, w, h], ...]}}; `keep_open` stamps `LAST_BULK_KEPT_OPEN`."""
    global LAST_BULK_ERRORS, LAST_BULK_NOTES, LAST_BULK_KEPT_OPEN
    with _KEYNOTE_LOCK:
        LAST_BULK_ERRORS = []
        LAST_BULK_NOTES = []
        LAST_BULK_KEPT_OPEN = None
        key_path = Path(key_path).expanduser().resolve()
        path_str = str(key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"Keynote not found: {key_path}")
        plan: dict[str, Any] = {
            "path": path_str,
            "bundleId": keynote_app.bundle_id(),
        }
        if keep_open:
            plan["keepOpen"] = True
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
            if keep_open:
                _close_document_by_name(key_path)
            raise RuntimeError(
                "Bulk geometry read failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
            )
        raw = (proc.stdout or "").strip()
        if not raw:
            if keep_open:
                _close_document_by_name(key_path)
            raise RuntimeError("Bulk geometry read returned no JSON.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            if keep_open:
                _close_document_by_name(key_path)
            raise RuntimeError(f"Bulk geometry read returned invalid JSON: {exc}") from exc
        if parsed.get("error"):
            # An open/slides failure must be loud, never a silent empty-geometry fallback.
            if keep_open:
                _close_document_by_name(key_path)
            raise RuntimeError(f"Bulk geometry read failed: {parsed['error']}")
        try:
            LAST_BULK_ERRORS = [{**e, "path": path_str} for e in (parsed.get("errors") or [])]
            LAST_BULK_NOTES = [{**n, "path": path_str} for n in (parsed.get("notes") or [])]
            LAST_BULK_KEPT_OPEN = path_str if parsed.get("keptOpen") else None
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
        except Exception:
            if keep_open:
                _close_document_by_name(key_path)
                LAST_BULK_KEPT_OPEN = None
            raise
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
    with _KEYNOTE_LOCK:
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


def _payload_has_runs(payload: dict[str, Any]) -> bool:
    """True when every eligible text item -- mirroring iwa_runs.attach_runs'
    ``_match_runs_to_items`` matching criteria -- carries a ``runs`` key
    (checker-shaped). A payload with no eligible text items counts as covered."""
    for slide in payload.get("slides") or []:
        for item in slide.get("items") or []:
            if is_duplicate_item(item):
                continue
            if (item.get("kind") or "text") not in {"text", "shape"}:
                continue
            if not (item.get("text") or "").strip():
                continue
            if "runs" not in item:
                return False
    return True


def _build_checker_offline(
    key_path: Path,
    bulk_geometry_fn: Any,
    *,
    slide_range: Any = None,
    keep_open: bool = False,
    log: Any = None,
) -> dict[str, Any]:
    """Two-tier IWA + attach_runs; one decode. Raises ImportError without ``iwa``.
    ``keep_open`` binds ``bulk_geometry_fn`` to leave the deck open for an immediate
    already-open export (the checker fold); every other caller leaves it ``False``."""
    from obed_edom.iwa_runs import _load_deck, attach_runs  # noqa: PLC0415
    from obed_edom.offline_inspect import two_tier_wall_payload  # noqa: PLC0415

    if keep_open:
        bulk_geometry_fn = functools.partial(bulk_geometry_fn, keep_open=True)
    deck = _load_deck(key_path)
    payload = two_tier_wall_payload(
        key_path, bulk_geometry_fn=bulk_geometry_fn, slide_range=slide_range, deck=deck, log=log
    )
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
    slide_range: tuple[int, int] | frozenset[int] | None = None,
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
    want_cache = _truthy_cache(use_cache, slide_range)
    dest = Path(export_dir) if export_dir else None

    from obed_edom.baseline import (  # noqa: PLC0415
        deck_digest,
        inspect_cache_path,
        preview_cache_dir,
    )

    digest = ""
    png_dir: Path | None = None
    rejected_cache = False
    if want_cache:
        t_hash = time.perf_counter()
        digest = deck_digest(key_path)
        timing["digest"] = time.perf_counter() - t_hash
        json_path = inspect_cache_path(digest)
        png_dir = preview_cache_dir(digest)
        if json_path.is_file():
            cached = json.loads(json_path.read_text(encoding="utf-8"))
            rejected_cache = True
            # Shared digest cache: a JXA hit has no runs[]; serving it would skip attach_runs.
            # A runs-less offline entry (e.g. from two_tier_wall_payload, which never
            # attaches runs) is not checker-shaped either -- fall through and rebuild.
            if cached.get("reader") == "offline" and _payload_has_runs(cached):
                bulk_errors = cached.get("bulkErrors") or []
                if bulk_errors and log is not None:
                    log(f"WARN: cached offline read for {key_path.name} carries "
                        f"{len(bulk_errors)} bulk-geometry error(s) from when it was built "
                        "(see bulkErrors) -- the cache may be serving a silent-partial read.")
                expected_pngs = _expected_pngs(cached)
                have = 0 if png_dir is None else len(preview_pngs(png_dir))
                if dest is None or have == expected_pngs:
                    cached["_cached"] = True
                    cached["_digest"] = digest
                    cached["_timing"] = timing
                    if dest is not None:
                        cached["previewDir"] = str(png_dir)
                        _set_export_state(cached, png_dir, expected=expected_pngs)
                    return cached
                png_dir.mkdir(parents=True, exist_ok=True)
                t_export = time.perf_counter()
                err = export_slide_images(key_path, png_dir, expected=expected_pngs)
                cached["_cached"] = True
                cached["_digest"] = digest
                _set_export_state(cached, png_dir, err, failed=True, expected=expected_pngs)
                cached["previewDir"] = str(png_dir)
                timing["export"] = time.perf_counter() - t_export
                cached["_timing"] = timing
                return cached

    export_target = dest
    if want_cache and dest is not None and png_dir is not None:
        export_target = png_dir
    if export_target is not None:
        export_target = Path(export_target)
        export_target.mkdir(parents=True, exist_ok=True)

    global LAST_BULK_KEPT_OPEN
    key_str = str(key_path)

    def _kept_open() -> bool:
        return LAST_BULK_KEPT_OPEN == key_str

    with _KEYNOTE_LOCK:
        LAST_BULK_KEPT_OPEN = None
        t_read = time.perf_counter()
        try:
            payload = _build_checker_offline(
                key_path, bulk_geometry, slide_range=slide_range,
                keep_open=export_target is not None, log=log,
            )
        except Exception as exc:  # noqa: BLE001 — missing iwa extra / decode error -> legacy JXA
            if log is not None:
                log(f"WARN: offline checker build failed for {key_path.name} ({exc!r}) -- falling back to legacy JXA.")
            try:
                return inspect_keynote(
                    key_path, export_dir=export_dir, slide_range=slide_range,
                    use_cache=False if rejected_cache else use_cache,
                )
            except Exception as legacy_exc:
                raise LegacyInspectFailed(str(legacy_exc)) from legacy_exc
            finally:
                if _kept_open():
                    _close_document_by_name(key_path)

        try:
            sidecar = payload.get("_offline") or {}
            fallback = sidecar.get("fallback") or []
            fallback_slides = sidecar.get("fallback_slides") or []
            if not sidecar.get("bulk_ok") and fallback_slides:
                try:
                    return inspect_keynote(
                        key_path, export_dir=export_dir, slide_range=slide_range,
                        use_cache=False if rejected_cache else use_cache,
                    )
                except Exception as legacy_exc:
                    raise LegacyInspectFailed(str(legacy_exc)) from legacy_exc
            if fallback:
                item_entries, slide_numbers = _partition_fallback(fallback)
                # Narrow reads, not the whole-deck legacy read; let failures fall through plain.
                if item_entries:
                    _merge_legacy_items(payload, key_path, item_entries)
                if slide_numbers:
                    from obed_edom.remap_keynote import _merge_legacy_slides  # noqa: PLC0415

                    _merge_legacy_slides(payload, key_path, slide_numbers)
            # Full-deck export: compute expected count before slide_range narrows payload["slides"].
            full_expected = _expected_pngs(payload)
            if slide_range is not None:
                from obed_edom.map_remap import wants_slide  # noqa: PLC0415

                # Legacy ranged JXA returns only the wanted slides.
                payload["slides"] = [
                    s
                    for s in (payload.get("slides") or [])
                    if wants_slide(int(s.get("number") or (int(s.get("index") or 0) + 1)), slide_range)
                ]
            timing["read"] = time.perf_counter() - t_read

            payload["path"] = str(key_path)
            payload["keynoteBundleId"] = keynote_app.bundle_id()
            payload["keynoteVersion"] = keynote_app.app_version()
            payload["reader"] = "offline"  # persists past the cache-write underscore strip
            payload.setdefault("exported", False)

            if export_target is not None:
                t_export = time.perf_counter()
                expected = full_expected
                if _kept_open():
                    try:
                        err = _export_open_slide_images(key_path, export_target, expected=expected)
                    except Exception as exc:  # noqa: BLE001 — export failure must not fail geometry
                        err = str(exc)
                    else:
                        if err is None:
                            LAST_BULK_KEPT_OPEN = None
                else:
                    err = None
                    if len(preview_pngs(export_target)) != expected:
                        err = export_slide_images(key_path, export_target, expected=expected)
                _set_export_state(payload, export_target, err, failed=True, expected=expected)
                timing["export"] = time.perf_counter() - t_export
                payload["previewDir"] = str(export_target.resolve())

            payload["_timing"] = timing
            payload["_cached"] = False
            payload["_digest"] = digest
            if want_cache and digest and not slide_range:
                json_path = inspect_cache_path(digest)
                json_path.parent.mkdir(parents=True, exist_ok=True)
                stored = {key: value for key, value in payload.items() if not str(key).startswith("_")}
                json_path.write_text(json.dumps(stored), encoding="utf-8")
            return payload
        finally:
            if _kept_open():
                _close_document_by_name(key_path)


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


def store_inspect_payload(key_path: Path | str, payload: dict[str, Any], digest: str = "") -> None:
    """Write a full-deck payload to the shared digest cache, minus `_`-prefixed keys."""
    from obed_edom.baseline import deck_digest, inspect_cache_path  # noqa: PLC0415

    if not digest:
        digest = deck_digest(key_path)
    stored = {key: value for key, value in payload.items() if not str(key).startswith("_")}
    json_path = inspect_cache_path(digest)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(stored), encoding="utf-8")


def complete_cached_wall_payload(payload: dict[str, Any] | None) -> bool:
    """Whether a digest-current cache safely represents every document slide."""
    if not isinstance(payload, dict) or payload.get("reader") not in {"jxa", "offline"}:
        return False
    slides = payload.get("slides")
    if not isinstance(slides, list):
        return False
    slide_count = payload.get("slideCount")
    if type(slide_count) is not int or slide_count != len(slides):
        return False
    for position, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            return False
        if type(slide.get("number")) is not int or type(slide.get("index")) is not int:
            return False
        if slide["number"] != position or slide["index"] != position - 1:
            return False
    return True


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

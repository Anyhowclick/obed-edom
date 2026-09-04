"""Offline geometry-write opt-in (``w-offline-write-optin``): pass-1 slide selection,
surgical IWA patch + AppleScript fallback + verify — all gated behind
``remap_keynote.offline_write_mode() != "off"``.

Every function here is pure (no Keynote) EXCEPT ``_patch_offline_slides``,
``_run_fallback_scripts`` and ``_composed_frames``, which touch the deck on disk (the
patch/fallback/re-decode) or Keynote (the AppleScript fallback session) — those are
exercised only via monkeypatched stand-ins in tests, never for real here. The
``iwa_write``/``iwa_geometry``/``iwa_runs``/``inspect.bulk_geometry`` functions this
module eventually calls are imported LAZILY inside the few functions that need them, so
importing this module never requires the ``iwa`` extra. Likewise ``remap_keynote``'s own
helpers (``_build_as_geometry``, ``_build_slide_geometry_script``,
``_spec_bears_geometry``) are imported lazily here — ``remap_keynote`` imports this
module at its own top level, so a module-level import back would cycle.
"""
from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from obed_edom import keynote_app
from obed_edom.keynote import _as_escape, _keynote_tell, _keynote_terms

_OFFLINE_EXACT_KINDS = frozenset({"shape", "line"})
_OFFLINE_MEDIA_KINDS = frozenset({"image", "movie"})
# Masked image/movie omitted: `iwa_write._slide_edits` only falls back to the `reported`
# bulk seed for a masked image's x/y (never w/h — those read the mask geometry), and only
# when the spec's x/y is None; `ItemTransform.as_dict()` always emits x/y, so a masked
# image spec never actually needs a live seed in practice.
_OFFLINE_SOFT_SEED_KINDS = frozenset({"group", "text"})

# Live-verify tolerance per kind (px), consumed by `_say_verify_report`'s per-kind lookup;
# "_default" covers any kind not listed. Text is now a real (if loose) bar — see
# `verify_live_frames` — not merely reported.
LIVE_VERIFY_TOL: dict[str, float] = {"text": 4.0, "_default": 2.0}
OFFLINE_VERIFY_TOL = 0.5


def probe_iwa_extra(mode: str, say: Callable[[str], None] | None) -> str:
    """Downgrade `mode` to "off" when the `iwa` extra isn't actually importable.

    Checked once, right after `offline_write_mode()` and BEFORE `offline_slides` is
    computed, so pass 1 runs unflagged rather than discovering the gap mid-patch.
    """
    if mode == "off":
        return mode
    try:
        import keynote_parser  # noqa: F401
        import obed_edom.iwa_write  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — any import failure forces off
        if say:
            say(
                f"Offline-write needs the `iwa` extra ({type(exc).__name__}: {exc}); "
                "forcing offline write off."
            )
        return "off"
    return mode


def _offline_write_slides(
    transform_dicts: list[dict[str, Any]],
    reuses: list[dict[str, Any]],
    reuse_slides: set[int],
    wanted: list[int] | None,
) -> set[int]:
    """Non-reuse, non-donor, AS-addressable slides eligible for the offline pass-1 write.

    Donors stay on the AS path: `plan_slide_reuses` records the donor's PLANNED output rect
    for JXA `deleteRefs`, and `applyReuse` duplicates the donor at target time — a
    suppressed donor would strand every removal and copy wall geometry into the target.
    """
    from obed_edom.remap_keynote import _build_as_geometry  # noqa: PLC0415 (avoid a module cycle)

    as_all = _build_as_geometry(transform_dicts, suppress=frozenset())
    planned = {int(k) for k in as_all}
    donors = {int(r["from"]) for r in reuses if r.get("from") is not None}
    offline = planned - set(reuse_slides) - donors
    if wanted:
        offline &= set(wanted)
    return offline


def counts_from_payload(wall: dict[str, Any]) -> dict[int, dict[str, int]]:
    """Per-slide per-kind item counts straight from the wall payload — no second IWA decode."""
    out: dict[int, dict[str, int]] = {}
    for i, slide in enumerate(wall.get("slides") or []):
        number = int(slide.get("number") or i + 1)
        counts: dict[str, int] = {}
        for item in slide.get("items") or []:
            kind = str(item.get("kind") or "item")
            counts[kind] = counts.get(kind, 0) + 1
        out[number] = counts
    return out


def _soft_seed_slides(
    offline_slides: set[int], specs_by_slide: dict[int, list[dict[str, Any]]]
) -> set[int]:
    """Offline slides carrying a non-hide, geometry-bearing group/text spec — the only
    kinds whose write needs a live bulk-geometry seed (`reported`)."""
    from obed_edom.remap_keynote import _spec_bears_geometry  # noqa: PLC0415 (avoid a module cycle)

    out: set[int] = set()
    for n in offline_slides:
        for spec in specs_by_slide.get(n, []):
            if spec.get("role") == "hide":
                continue
            if str(spec.get("kind") or "") in _OFFLINE_SOFT_SEED_KINDS and _spec_bears_geometry(spec):
                out.add(n)
                break
    return out


def _reported_from_bulk_rows(
    bulk: dict[int, dict[str, list[list[float]]]],
) -> dict[int, dict[tuple[str, int], list[float]]]:
    """`inspect.bulk_geometry` 0-based slide keys → 1-based; row index == saved kindIndex."""
    out: dict[int, dict[tuple[str, int], list[float]]] = {}
    for slide_key0, kinds in bulk.items():
        reported: dict[tuple[str, int], list[float]] = {}
        for kind, rows in (kinds or {}).items():
            for i, row in enumerate(rows):
                reported[(str(kind), i)] = list(row)
        out[int(slide_key0) + 1] = reported
    return out


def _fallback_specs_by_slide(
    offline_slides: set[int],
    specs_by_slide: dict[int, list[dict[str, Any]]],
    results: dict[int, Any],
) -> dict[int, list[dict[str, Any]]]:
    """Refused slides fall back whole; patched slides contribute only their `missed_specs`."""
    out: dict[int, list[dict[str, Any]]] = {}
    for n in offline_slides:
        res = results.get(n)
        if res is None or getattr(res, "refused", False):
            specs = list(specs_by_slide.get(n) or [])
        else:
            specs = list(getattr(res, "missed_specs", None) or [])
        if specs:
            out[n] = specs
    return out


def _fallback_bodies(fallback_by_slide: dict[int, list[dict[str, Any]]]) -> dict[int, str]:
    """Per-slide AppleScript geometry bodies for the offline-write fallback, bridged from
    wall to saved (post-deleteHides) kindIndex — the same bridge the patcher uses."""
    from obed_edom.iwa_write import bridge_specs_kindindex  # noqa: PLC0415 (optional iwa extra)
    from obed_edom.remap_keynote import _build_slide_geometry_script  # noqa: PLC0415 (avoid a module cycle)

    bodies: dict[int, str] = {}
    for n, specs in fallback_by_slide.items():
        body = _build_slide_geometry_script(bridge_specs_kindindex(specs), n)
        if body:
            bodies[n] = body
    return bodies


def build_fallback_scripts(
    dest: Path | str, bodies_by_slide: dict[int, str], *, limit: int = 300_000
) -> list[str]:
    """One-or-more full osascript sessions (stat-finalize bind) applying every slide's
    fallback geometry body, chunked at `limit` bytes of script text per session — each
    chunk is its own full open/apply/save/close session.

    The chunk accounting sums only body text; the surrounding session envelope (`using
    terms from`/`tell`/`activate`/`with timeout`/close-open/save-close, ~600 bytes) is NOT
    counted, so an actual session's script file can exceed `limit` by that constant.
    """
    dest = Path(dest)
    escaped = _as_escape(str(dest))
    stem = _as_escape(dest.stem)
    doc_name = _as_escape(dest.name)

    def _session(bodies: list[str]) -> str:
        return "\n".join(
            [
                _keynote_terms(),
                _keynote_tell(),
                "  activate",
                "  with timeout of 3600 seconds",
                "  try",
                f'    close (every document whose name is "{doc_name}" or name is "{stem}") saving no',
                "    delay 0.3",
                "  end try",
                f'  set theFile to POSIX file "{escaped}"',
                "  open theFile",
                "  delay 0.4",
                "  set theDoc to document 1",
                f'  if name of theDoc does not start with "{stem}" then error '
                '"offline-write fallback bound the wrong document: " & (name of theDoc)',
                "  tell theDoc",
                *bodies,
                "  end tell",
                "  save theDoc",
                "  try",
                "    close theDoc saving yes",
                "  end try",
                "  end timeout",
                "end tell",
                "end using terms from",
            ]
        )

    sessions: list[str] = []
    chunk: list[str] = []
    chunk_size = 0
    for n in sorted(bodies_by_slide):
        body = bodies_by_slide[n]
        if chunk and chunk_size + len(body) > limit:
            sessions.append(_session(chunk))
            chunk = []
            chunk_size = 0
        chunk.append(body)
        chunk_size += len(body)
    if chunk:
        sessions.append(_session(chunk))
    return sessions


def _run_fallback_scripts(
    dest: Path, scripts: list[str], say: Callable[[str], None]
) -> tuple[bool, list[Path]]:
    """Run each `build_fallback_scripts` session via osascript; dump + say on failure.

    Returns `(ok, failed_dumps)` — `ok` is False if any session failed; `failed_dumps`
    lists the `.applescript` file(s) kept beside `dest` for inspection.
    """
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    ok = True
    failed_dumps: list[Path] = []
    for i, script in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
            handle.write(script)
            script_path = Path(handle.name)
        try:
            proc = subprocess.run(
                ["osascript", str(script_path)], capture_output=True, text=True, check=False
            )
        finally:
            script_path.unlink(missing_ok=True)
        if proc.returncode != 0:
            ok = False
            suffix = (
                ".offline-fallback.applescript"
                if len(scripts) == 1
                else f".offline-fallback-{i + 1}.applescript"
            )
            debug = dest.with_suffix(suffix)
            debug.write_text(script, encoding="utf-8")
            failed_dumps.append(debug)
            say(
                f"Offline-write AppleScript fallback session {i + 1}/{len(scripts)} failed "
                f"(script kept: {debug}): {proc.stderr or proc.stdout}"
            )
    return ok, failed_dumps


def _patch_offline_slides(
    dest: Path,
    offline_slides: set[int],
    specs_by_slide: dict[int, list[dict[str, Any]]],
    wall: dict[str, Any],
    say: Callable[[str], None],
) -> dict[int, Any]:
    """Patch every offline slide in ONE zip rewrite. Empty result ⇒ caller falls the whole
    run back to AppleScript (never patch group/text without a live seed).

    `iwa_write.OfflineWriteCorrupted` means the in-place copy-back itself failed: the deck
    IS truncated and the temp `.<name>.obedwrite.tmp` beside it holds the full rewrite.
    That must never be treated as a soft failure — no fallback, no continuing — so it is
    the one exception NOT swallowed here; it propagates after saying the recovery step.
    """
    if not offline_slides:
        return {}
    counts = counts_from_payload(wall)
    soft_slides = _soft_seed_slides(offline_slides, specs_by_slide)
    reported_by_slide: dict[int, dict] | None = None
    if soft_slides:
        try:
            from obed_edom.inspect import bulk_geometry  # noqa: PLC0415

            bulk = bulk_geometry(dest, slides=sorted(soft_slides), log=say)
            reported_by_slide = _reported_from_bulk_rows(bulk)
        except Exception as exc:  # noqa: BLE001 — never patch soft classes blind
            say(
                f"Offline-write soft seed unavailable ({type(exc).__name__}: {exc}); "
                f"falling back to AppleScript for all {len(offline_slides)} offline slide(s)."
            )
            return {}
    try:
        from obed_edom.iwa_write import (  # noqa: PLC0415 (optional iwa extra)
            OfflineWriteCorrupted,
            patch_deck_geometry,
        )
    except Exception as exc:  # noqa: BLE001 — offline write is opt-in; never break the run
        say(
            f"Offline-write patch unavailable ({type(exc).__name__}: {exc}); "
            f"falling back to AppleScript for all {len(offline_slides)} offline slide(s)."
        )
        return {}
    try:
        results = patch_deck_geometry(
            dest,
            specs_by_slide,
            reported_by_slide=reported_by_slide,
            source_counts_by_slide=counts,
            require_reconcile=True,
        )
    except OfflineWriteCorrupted as exc:
        tmp_path = Path(dest).parent / f".{Path(dest).name}.obedwrite.tmp"
        say(
            f"OFFLINE-WRITE CORRUPTED: {exc} — {dest} may be TRUNCATED. RECOVERY: copy "
            f'{tmp_path} back over {dest} (e.g. `cp "{tmp_path}" "{dest}"`), then re-run. '
            "NOT falling back to AppleScript — the deck cannot be safely opened like this."
        )
        raise
    except Exception as exc:  # noqa: BLE001 — offline write is opt-in; never break the run
        say(
            f"Offline-write patch unavailable ({type(exc).__name__}: {exc}); "
            f"falling back to AppleScript for all {len(offline_slides)} offline slide(s)."
        )
        return {}
    for n in sorted(results):
        res = results[n]
        if getattr(res, "refused", False):
            say(f"Offline-write slide {n}: REFUSED ({res.reason}) — falling back to AppleScript.")
        else:
            extra = f" soft_fallbacks={res.soft_fallbacks}" if getattr(res, "soft_fallbacks", 0) else ""
            say(
                f"Offline-write slide {n}: applied={res.applied} missed={res.missed} "
                f"value_clean={res.value_clean}{extra}."
            )
    return results


def _composed_frames(dest: Path, slides: set[int]) -> dict[int, list[dict[str, Any]]]:
    """Fresh offline read of each slide's composed (JXA-equivalent) frame, post-patch."""
    from obed_edom.iwa_geometry import compose_geometry  # noqa: PLC0415 (optional iwa extra)
    from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: PLC0415 (optional iwa extra)

    objects, _id_to_file, _file_ids = _load_deck(dest)
    order = slide_order(objects)
    out: dict[int, list[dict[str, Any]]] = {}
    for n in slides:
        if not (1 <= n <= len(order)):
            continue
        slide_id = order[n - 1][0]
        slide = objects.get(slide_id)
        if slide is None:
            continue
        out[n] = compose_geometry(slide, objects)
    return out


def _spec_box(
    spec: dict[str, Any], rec: dict[str, Any]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Comparable (planned, actual) tuples for one verify pair.

    Lines compare POSITION only, never length: no planner call site currently sets
    `ItemTransform.role == "line"` (the length/0 branch in `ItemTransform.as_dict` is
    presently unreached), so a real line spec's `w`/`h` are an ordinary bbox via the
    `role in {"map","list","pin","title","other"}` branch — not necessarily comparable to
    a composed line's bbox the way a shape's is. Length is deliberately left UNVERIFIED by
    this compare rather than risk comparing the wrong thing.
    """
    if str(spec.get("kind") or "") == "line":
        return (
            (float(spec.get("x", rec.get("x", 0.0))), float(spec.get("y", rec.get("y", 0.0)))),
            (float(rec.get("x", 0.0)), float(rec.get("y", 0.0))),
        )
    return (
        (
            float(spec.get("x", rec.get("x", 0.0))),
            float(spec.get("y", rec.get("y", 0.0))),
            float(spec.get("w", rec.get("w", 0.0))),
            float(spec.get("h", rec.get("h", 0.0))),
        ),
        (
            float(rec.get("x", 0.0)),
            float(rec.get("y", 0.0)),
            float(rec.get("w", 0.0)),
            float(rec.get("h", 0.0)),
        ),
    )


def _summarize_verify(
    per_kind: dict[str, list[dict[str, Any]]],
) -> dict[str, tuple[float, int, list[dict[str, Any]]]]:
    out: dict[str, tuple[float, int, list[dict[str, Any]]]] = {}
    for kind, rows in per_kind.items():
        rows.sort(key=lambda r: -r["delta"])
        out[kind] = (rows[0]["delta"], len(rows), rows[:5])
    return out


def verify_offline_frames(
    planned_specs_by_slide: dict[int, list[dict[str, Any]]],
    composed_by_slide: dict[int, list[dict[str, Any]]],
) -> dict[str, tuple[float, int, list[dict[str, Any]]]]:
    """Planned vs offline-composed frame for the exact classes only: shape, line, and
    UNMASKED image/movie (`geom_source == "iwa"`; masked/group/text need a live seed and
    are excluded here). `composed_by_slide` is keyed by SAVED (post-deleteHides)
    kindIndex, so each slide's specs are bridged (wall → saved) before the lookup — the
    same bridge the patcher and the AppleScript fallback both use. Returns
    `{kind: (max_delta, n, worst5)}`."""
    from obed_edom.iwa_write import bridge_specs_kindindex  # noqa: PLC0415 (optional iwa extra)

    per_kind: dict[str, list[dict[str, Any]]] = {}
    for n, specs in planned_specs_by_slide.items():
        bridged = bridge_specs_kindindex(specs)
        comp = {(r["kind"], r["kindIndex"]): r for r in composed_by_slide.get(n, [])}
        for spec in bridged:
            if spec.get("role") == "hide":
                continue
            kind = str(spec.get("kind") or "")
            if kind not in _OFFLINE_EXACT_KINDS and kind not in _OFFLINE_MEDIA_KINDS:
                continue
            ki = spec.get("kindIndex")
            if ki is None:
                continue
            rec = comp.get((kind, int(ki)))
            if rec is None:
                continue
            if kind in _OFFLINE_MEDIA_KINDS and rec.get("geom_source") != "iwa":
                continue  # masked: needs a live seed, not this compare
            planned, actual = _spec_box(spec, rec)
            delta = max(abs(a - b) for a, b in zip(planned, actual))
            per_kind.setdefault(kind, []).append({"slide": n, "kindIndex": int(ki), "delta": delta})
    return _summarize_verify(per_kind)


def verify_live_frames(
    planned_specs_by_slide: dict[int, list[dict[str, Any]]],
    payload: dict[str, Any],
    *,
    exclude_slides: frozenset[int] = frozenset(),
) -> dict[str, tuple[float, int, list[dict[str, Any]]]]:
    """Planned vs the live Keynote-reported frame.

    `exclude_slides` drops the WHOLE slide, every kind — not just group: Bring to Front
    moves the raised item to the END of its per-kind collection, so on a stat-finalize
    slide EVERY kind's kindIndex may be wrong post-raise, not only the group's, and even a
    bridged index is then meaningless. The reported payload is keyed by SAVED kindIndex,
    so each slide's specs are bridged (wall → saved) before the lookup, same as
    `verify_offline_frames`.

    Text is now a real (if loose) bar, not merely reported: `y` is a centre delta and `x`
    is approximate, so both are compared but callers should apply a loose per-kind
    tolerance (see `LIVE_VERIFY_TOL`) rather than the tighter shape/image bar.
    """
    from obed_edom.iwa_write import bridge_specs_kindindex  # noqa: PLC0415 (optional iwa extra)

    reported: dict[int, dict[tuple[str, int], dict[str, Any]]] = {}
    for i, slide in enumerate(payload.get("slides") or []):
        number = int(slide.get("number") or i + 1)
        by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for item in slide.get("items") or []:
            ki = item.get("kindIndex")
            if ki is None:
                continue
            by_key[(str(item.get("kind") or ""), int(ki))] = item
        reported[number] = by_key

    per_kind: dict[str, list[dict[str, Any]]] = {}
    for n, specs in planned_specs_by_slide.items():
        if n in exclude_slides:
            continue
        bridged = bridge_specs_kindindex(specs)
        by_key = reported.get(n, {})
        for spec in bridged:
            if spec.get("role") == "hide":
                continue
            kind = str(spec.get("kind") or "")
            ki = spec.get("kindIndex")
            if ki is None:
                continue
            item = by_key.get((kind, int(ki)))
            if item is None:
                continue
            if kind == "text":
                # Text y is a centre delta, x is approximate — compare both, loosely.
                dx = abs(float(spec.get("x", item.get("x") or 0.0)) - float(item.get("x") or 0.0))
                dy = abs(float(spec.get("y", item.get("y") or 0.0)) - float(item.get("y") or 0.0))
                delta = max(dx, dy)
            else:
                planned, actual = _spec_box(spec, item)
                delta = max(abs(a - b) for a, b in zip(planned, actual))
            per_kind.setdefault(kind, []).append({"slide": n, "kindIndex": int(ki), "delta": delta})
    return _summarize_verify(per_kind)


def _tol_for_kind(tol: float | dict[str, float], kind: str) -> float:
    if isinstance(tol, dict):
        return tol.get(kind, tol.get("_default", 2.0))
    return tol


def _say_verify_report(
    title: str,
    report: dict[str, tuple[float, int, list[dict[str, Any]]]],
    tol: float | dict[str, float],
    say: Callable[[str], None] | None,
) -> bool:
    """`tol` is either a single px float for every kind, or a `{kind: px}` dict (with an
    optional `"_default"` fallback) — see `LIVE_VERIFY_TOL`."""
    if not report:
        if say:
            say(f"{title}: no comparable objects.")
        return True
    overall = True
    for kind, (max_delta, n, _worst5) in sorted(report.items()):
        kind_tol = _tol_for_kind(tol, kind)
        status = "PASS" if max_delta <= kind_tol else "FAIL"
        overall = overall and status == "PASS"
        if say:
            say(f"{title}: {kind} max Δ{max_delta:.2f}px (n={n}) {status} @ {kind_tol}px")
    if say:
        say(f"{title}: overall {'PASS' if overall else 'FAIL'}.")
    return overall


def run_offline_write(
    dest: Path,
    mode: str,
    offline_slides: set[int],
    transform_dicts: list[dict[str, Any]],
    wall: dict[str, Any],
    child_resize: list[dict[str, Any]],
    say: Callable[[str], None],
) -> dict[str, Any] | None:
    """The whole offline-write execution phase for one remap: patch every offline slide,
    AppleScript-fallback whatever was refused or individually missed, verify (offline,
    `mode == "verify"` only — a second full deck decode is a diagnostic, not production),
    and return the `info["offlineWrite"]` payload (`None` when `offline_slides` is empty).

    Raises `RuntimeError` if the AppleScript fallback fails: those slides had their pass-1
    geometry suppressed, so the fallback is their only remaining writer — silently moving
    on would ship them at wall geometry.
    """
    if not offline_slides:
        return None
    specs_by_slide = {
        n: [t for t in transform_dicts if int(t.get("slide", -1)) == n] for n in offline_slides
    }
    say(f"Offline-write ({mode}): patching {len(offline_slides)} slide(s) in place…")
    patch_results = _patch_offline_slides(dest, offline_slides, specs_by_slide, wall, say)
    fallback_by_slide = _fallback_specs_by_slide(offline_slides, specs_by_slide, patch_results)
    fallback_ok = True
    if fallback_by_slide:
        fallback_specs_n = sum(len(v) for v in fallback_by_slide.values())
        say(
            f"Offline-write fallback: {len(fallback_by_slide)} slide(s) "
            f"({fallback_specs_n} spec(s)) via AppleScript."
        )
        bodies = _fallback_bodies(fallback_by_slide)
        scripts = build_fallback_scripts(dest, bodies)
        fallback_ok, failed_dumps = _run_fallback_scripts(dest, scripts, say)
        if not fallback_ok:
            raise RuntimeError(
                "offline-write fallback failed; see "
                f"{[str(p) for p in failed_dumps]} — those slide(s) still carry wall "
                "geometry, nothing else will write them."
            )
    offline_verify_pass: bool | None = None
    if mode == "verify":
        composed = _composed_frames(dest, offline_slides)
        offline_report = verify_offline_frames(specs_by_slide, composed)
        offline_verify_pass = _say_verify_report(
            "offline-write verify", offline_report, OFFLINE_VERIFY_TOL, say
        )
    result: dict[str, Any] = {
        "mode": mode,
        "slides": sorted(offline_slides),
        "refused": sorted(n for n, r in patch_results.items() if getattr(r, "refused", False)),
        "fallbackSpecs": {str(n): len(v) for n, v in fallback_by_slide.items()},
        "applied": sum(getattr(r, "applied", 0) for r in patch_results.values()),
        "missedSpecs": sum(
            len(getattr(r, "missed_specs", None) or []) for r in patch_results.values()
        ),
        "softFallbacks": sum(getattr(r, "soft_fallbacks", 0) for r in patch_results.values()),
        "valueClean": all(
            getattr(r, "value_clean", False)
            for r in patch_results.values()
            if not getattr(r, "refused", False)
        ),
        "specs": specs_by_slide,
        "statSlides": sorted({int(cr.get("slide", -1)) for cr in child_resize}),
    }
    if offline_verify_pass is not None:
        result["offlineVerifyPass"] = offline_verify_pass
    return result

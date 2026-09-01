from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from obed_edom import keynote_app
from obed_edom.inspect import export_slide_images, inspect_keynote, preview_pngs
from obed_edom.keynote import _run_stat_finalize, read_template_stat_sizes
from obed_edom.map_remap import (
    adjust_child_resize_for_deleted_hides,
    navigator_numbering,
    CG_HEIGHT,
    CG_WIDTH,
    format_slide_range,
    learn_recipe,
    plan_payload_transforms,
    plan_slide_reuses,
    score_against_gold,
    slides_for_plan,
    summarize_plan,
)

REMAP_JS = Path(__file__).resolve().parent / "remap_keynote.js"

# AppleScript element names for the kinds the plan carries. The AppleScript index
# is the JXA 0-based collection index plus one (same sdef collection, same order).
_AS_KIND_NAMES = {
    "text": "text item",
    "image": "image",
    "shape": "shape",
    "movie": "movie",
    "group": "group",
    "line": "line",
}


def as_geometry_enabled() -> bool:
    """Whether the batched-AppleScript geometry path is used — default ON.

    AS-geometry is the validated default: no JXA (0,0) yank, ~30% faster on the
    constellation slide (it drops setPos's readback-verify and the second
    position pass), placement/z-order/groups confirmed correct. Set
    ``OBED_AS_GEOMETRY=0`` (or ``false``/``no``/``off``) to force the legacy JXA
    geometry path — kept for A/B debugging and as the per-slide fallback for
    slides carrying an object of a kind AppleScript can't address.
    """
    return os.environ.get("OBED_AS_GEOMETRY", "").strip().lower() not in {"0", "false", "no", "off"}


def suppress_geometry_slides() -> set[int]:
    """1-based slide numbers whose pass-1 write must place attrs but NO geometry.

    Reads ``OBED_SUPPRESS_GEOMETRY`` (default empty) as a comma/space-separated list
    of slide numbers. A listed NON-reuse slide gets ``applyTransforms(…, "attrs")``
    only — its width/height/position are left exactly as pass 1 found them, taking
    neither the batched-AppleScript geometry branch nor the JXA full-geometry branch
    (``deleteHides`` still runs). This is the pass-1-only baseline the offline
    surgical patcher (:mod:`obed_edom.iwa_write`) writes onto: without it an
    empty-``asGeom`` slide silently falls through to the JXA full path and gets its
    geometry written anyway. Non-numeric tokens are ignored, so a typo degrades to
    "suppress nothing" rather than raising mid-remap.
    """
    raw = os.environ.get("OBED_SUPPRESS_GEOMETRY", "")
    slides: set[int] = set()
    for token in raw.replace(",", " ").split():
        try:
            slides.add(int(token))
        except ValueError:
            continue
    return slides


# --------------------------------------------------------------------------
# Offline source-wall read (OBED_OFFLINE_READ) — reconstruct the ~12-min JXA
# `inspect_keynote(source)` from the deck's IWA graph, with the legacy read as
# an AUTOMATIC total fallback. See obed_edom.offline_inspect + the reviewed plan.
# --------------------------------------------------------------------------
def offline_read_mode(explicit: str | None = None) -> str:
    """Resolve the offline-read mode: ``on`` (default) or ``off``.

    ``explicit`` (the ``remap()`` param) wins; otherwise ``OBED_OFFLINE_READ``;
    otherwise the default. Unknown values fall to the default. DEFAULT is ``on``
    (Session 15): the gold-deck plan gate is green on both decks with the real bulk
    read, and one real end-to-end ``on`` remap wrote a deck placement-identical to a
    legacy-read run. ``OBED_OFFLINE_READ=off`` forces the legacy ~12-min JXA inspect.

    (The old ``verify`` mode — build both reads and diff at runtime — was removed:
    its check was stricter than the validated write-affecting gate, so a re-derived
    autoshrink ``fontSize`` that never lands on write made it always fall back on
    real decks. The granular per-slide fallback inside the ``on`` path is the safety
    net; force ``off`` for a full legacy read.)
    """
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_READ", "")).strip().lower()
    return raw if raw in {"on", "off"} else "on"


def _spec_addr(spec: dict[str, Any]) -> tuple:
    return (int(spec.get("slide", -1)), str(spec.get("kind")), int(spec.get("kindIndex", -1)))


def _spec_fields_equal(a: dict[str, Any], b: dict[str, Any], tol: float = 2.0) -> bool:
    for key in (set(a) | set(b)) - {"itemIndex"}:
        av, bv = a.get(key), b.get(key)
        if key in ("x", "y", "w", "h"):
            try:
                if abs(float(av) - float(bv)) > tol:
                    return False
            except (TypeError, ValueError):
                if av != bv:
                    return False
        elif key in ("start", "end"):
            if not (isinstance(av, (list, tuple)) and isinstance(bv, (list, tuple))
                    and len(av) >= 2 and len(bv) >= 2
                    and abs(float(av[0]) - float(bv[0])) <= tol
                    and abs(float(av[1]) - float(bv[1])) <= tol):
                if av != bv:
                    return False
        elif av != bv:
            return False
    return True


def _specs_equivalent(off: list[dict], jxa: list[dict]) -> bool:
    off_map = {_spec_addr(s): s for s in off}
    jxa_map = {_spec_addr(s): s for s in jxa}
    if set(off_map) != set(jxa_map):
        return False
    return all(_spec_fields_equal(off_map[k], jxa_map[k]) for k in off_map)


def _merge_legacy_slides(
    payload: dict[str, Any], source: Path, slide_numbers: list[int]
) -> None:
    """Replace the given slides' items in ``payload`` with a scoped legacy read, in place.

    The granular-fallback merge: only ``slide_numbers`` (document numbers) are
    re-read, in a SINGLE ``inspect_keynote`` scoped to them, and each returned
    slide's item-bearing fields overwrite the offline+bulk slide of the same
    number. Addressing (index/number) and every other slide are left untouched, so
    the payload stays a drop-in for the planner. A legacy read that comes back
    without a wanted slide leaves that slide's offline data in place (best effort).
    """
    if not slide_numbers:
        return
    legacy = inspect_keynote(source, slide_range=frozenset(int(n) for n in slide_numbers))
    by_number = {
        int(s.get("number") or (int(s.get("index") or 0) + 1)): s
        for s in legacy.get("slides") or []
    }
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        repl = by_number.get(number)
        if repl is None:
            continue
        # Overwrite the content the legacy read authoritatively supplies; keep the
        # offline index/number so downstream addressing is unchanged.
        for key in ("items", "groupedText", "master", "skipped"):
            if key in repl:
                slide[key] = repl[key]


def acquire_wall_payload(
    source: Path,
    *,
    slide_range: Any,
    mode: str,
    say: Callable[[str], None],
) -> dict[str, Any]:
    """The source-wall inspect payload, honouring ``OBED_OFFLINE_READ`` ``mode``.

    * ``off`` — the legacy ``inspect_keynote(source)`` (the ~12-min JXA read).
    * ``on`` (default) — the TWO-TIER read is the source of truth: the offline IWA
      payload (tier 1, exact for shapes/lines/plain frames) with a slim bulk Keynote
      read (tier 2) overwriting the geometry of the three offline-soft classes
      (groups, masked/rotated images, autosize text). Fallback is GRANULAR — the
      unit is the object CLASS or SLIDE, never the whole deck: only slides whose
      soft items the bulk read did not confirm, or that carry a content guard flag
      (font/fileName the bulk read cannot touch), are re-read with one scoped
      legacy ``inspect_keynote`` and merged back. The whole deck drops to legacy
      only when tier 1 itself raises (missing ``iwa`` extra, decode error) or the
      bulk tier is entirely unavailable AND something still needs confirming.

    A ``say(...)`` line always records which path actually supplied the payload.
    """
    if mode == "off":
        return inspect_keynote(source, slide_range=slide_range)

    try:
        from obed_edom.inspect import bulk_geometry  # noqa: PLC0415
        from obed_edom.offline_inspect import (  # noqa: PLC0415 (optional iwa extra)
            two_tier_wall_payload,
        )

        offline = two_tier_wall_payload(
            source, bulk_geometry_fn=bulk_geometry, slide_range=slide_range
        )
    except Exception as exc:  # noqa: BLE001 — any tier-1 failure drops to legacy
        say(f"Offline source read unavailable ({type(exc).__name__}: {exc}); "
            f"using Keynote inspect of {source.name}.")
        return inspect_keynote(source, slide_range=slide_range)

    sidecar = offline.get("_offline") or {}
    fallback_slides = sidecar.get("fallback_slides") or []

    # Tier 2 (bulk geometry) unavailable AND something still needs confirming:
    # the offline geometry alone cannot be trusted for the soft classes, so drop
    # the whole deck to legacy — the pre-two-tier safe behaviour.
    if not sidecar.get("bulk_ok") and fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Bulk geometry read of {source.name} unavailable and "
            f"{len(fallback_slides)} slide(s) need it {reasons}; "
            f"using Keynote inspect for the whole deck.")
        return inspect_keynote(source, slide_range=slide_range)

    # Granular per-slide fallback: re-read only the flagged slides (one scoped
    # legacy pass) and splice their items back over the offline payload.
    if fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Two-tier read of {source.name}: {sidecar.get('spliced', 0)} item(s) "
            f"bulk-confirmed; {len(fallback_slides)} slide(s) fall back to Keynote "
            f"inspect {reasons}: {fallback_slides}.")
        _merge_legacy_slides(offline, source, fallback_slides)

    # mode == "on": the two-tier read is the source of truth.
    confirmed = "" if not fallback_slides else f" ({len(fallback_slides)} slide(s) via Keynote)"
    say(f"Read {source.name} two-tier (offline IWA + bulk geometry){confirmed} — "
        f"skipped the full Keynote source inspect.")
    return offline


def write_timing_enabled() -> bool:
    """Diagnostic: when ON, the JXA write pass records per-slide/per-phase elapsed
    and the individual objects slower than a threshold, and remap prints a summary
    — so one run shows exactly which slide, phase, and objects eat the geometry-write
    time. Default OFF (zero cost). Set ``OBED_WRITE_TIMING=1`` to enable.
    """
    return os.environ.get("OBED_WRITE_TIMING", "").strip().lower() in {"1", "true", "yes", "on"}


def geom_props_enabled() -> bool:
    """Whether the AS-geometry block folds each object's SIZE writes into one
    ``set properties {width, height}`` command (position stays a separate LAST write
    so the height re-anchor is still corrected; a line's endpoints fold into one
    atomic set) instead of writing every property separately — default ON.

    Fewer AppleScript commands is the only lever on a heavy slide: each command
    carries a fixed ~100ms per-object cost there, and there is no cross-object bulk
    write. Measured ~1.25× on the real report deck (slide 8 124s→101s, slide 3
    67s→54s), and validated placement-identical against the pipeline's own
    run-to-run noise floor (Keynote's canvas-shrink already jitters the map ~8px per
    run). Set ``OBED_GEOM_PROPS=0`` (or ``false``/``no``/``off``) to force the legacy
    per-property writes for A/B.
    """
    return os.environ.get("OBED_GEOM_PROPS", "").strip().lower() not in {"0", "false", "no", "off"}


def _say_write_timing(timing: dict[str, Any], say: Callable[[str], None]) -> None:
    """Print the write-path timing: phases by total elapsed, then the slowest objects."""
    buckets: dict[str, Any] = timing.get("buckets") or {}
    rows = sorted(buckets.items(), key=lambda kv: -(kv[1].get("ms") or 0))
    say("── write timing: phases by total elapsed (ms) ──")
    for name, b in rows:
        ms = int(b.get("ms") or 0)
        n = int(b.get("n") or 0)
        avg = ms / n if n else 0
        say(f"    {name:32} {ms:>7} ms   {n:>4} ×   {avg:5.1f} ms/ea")
    slow = sorted(timing.get("slow") or [], key=lambda d: -(d.get("ms") or 0))
    if slow:
        say(f"── slowest objects (≥{int(timing.get('slowMs') or 0)} ms), top 25 ──")
        for d in slow[:25]:
            say(
                f"    {int(d.get('ms') or 0):>5} ms  {d.get('op',''):16} "
                f"slide {d.get('slide')} {d.get('kind','')}[{d.get('kindIndex')}] "
                f"role={d.get('role','') or '-'} @({d.get('x')},{d.get('y')})"
            )
        say(f"    ({len(slow)} object(s) over threshold total)")


def _as_num(value: Any) -> str:
    """AppleScript numeric literal: an integer when whole, else a 2dp decimal."""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return repr(round(number, 2))


def _build_slide_geometry_script(specs: list[dict[str, Any]], slide_no: int) -> str:
    """One `tell slide N` block setting geometry for each object on that slide.

    Written in Python (not JXA) so a pytest can lock the exact string, and safe to
    address by slide number because non-reuse slide numbering is stable through
    the JXA loop (a reuse duplicate is deleted before the next slide, restoring
    the count). Objects are addressed ``<kind> (kindIndex + 1)`` — the 1-based
    AppleScript twin of the JXA 0-based collection index.

    Width/height are written before position because an AppleScript height write
    re-anchors ~18px about the object centre, which the final position write
    corrects; unlike JXA, AppleScript does not yank an object to (0,0) on a size
    write, so no position-only restore pass follows. A line's geometry is its
    endpoints (``start point``/``end point``), which AppleScript can set even
    though JXA cannot. A group gets full geometry (width, height, position) like
    any other object: there is no separate child-resize pass on this branch, so
    the JXA full pass this replaces was the only writer of a group's size — and a
    role=="other" group is deliberately framed at wall size to keep wall-sized
    children (a logo, a date) from clipping (see map_remap.py). Setting a group's
    width in AppleScript neither yanks it nor scales its children, so it matches
    that JXA frame write. Every object's writes sit inside their own ``try`` so an
    unsupported property never abandons the rest of the slide, and a locked object
    is unlocked before the writes and relocked after.
    """
    body: list[str] = []
    for spec in specs:
        if spec.get("role") == "hide":
            continue
        kind = str(spec.get("kind") or "")
        name = _AS_KIND_NAMES.get(kind)
        if not name:
            continue
        kind_index = spec.get("kindIndex")
        if kind_index is None:
            kind_index = spec.get("itemIndex")
        if kind_index is None:
            continue
        addr = f"{name} {int(kind_index) + 1}"
        lines = [
            "  try",
            f"    set theObj to {addr}",
            "    set wasLocked to false",
            "    try",
            "      if locked of theObj then",
            "        set locked of theObj to false",
            "        set wasLocked to true",
            "      end if",
            "    end try",
        ]
        start = spec.get("start")
        end = spec.get("end")
        x = spec.get("x")
        y = spec.get("y")
        if geom_props_enabled():
            # Fewer AppleScript commands per object (each carries a fixed per-object cost
            # on a heavy slide) — but position MUST stay a separate, LAST write. Setting
            # height re-anchors ~18px about the object centre, and only a trailing
            # position write corrects it; folding position into an atomic `properties`
            # record loses that ordering and drifts the object (verified on a real deck).
            # So: size keys combined into one `set properties`, then position on its own.
            # A line has no re-anchor, so its endpoints stay a single atomic set.
            # (Trade-off vs the legacy per-property form: a throw on the combined size
            # record loses BOTH width and height rather than one — acceptable because both
            # are universally settable on every _AS_KIND_NAMES kind, and the whole write is
            # still wrapped in its own try so it never abandons the rest of the slide.)
            if kind == "line" and start and end:
                lines += [
                    "    try",
                    "      set properties of theObj to "
                    f"{{start point:{{{_as_num(start[0])}, {_as_num(start[1])}}}, "
                    f"end point:{{{_as_num(end[0])}, {_as_num(end[1])}}}}}",
                    "    end try",
                ]
            else:
                size_props: list[str] = []
                if spec.get("w") is not None:
                    size_props.append(f"width:{_as_num(spec['w'])}")
                if spec.get("h") is not None:
                    size_props.append(f"height:{_as_num(spec['h'])}")
                if size_props:
                    lines += [
                        "    try",
                        f"      set properties of theObj to {{{', '.join(size_props)}}}",
                        "    end try",
                    ]
                if x is not None and y is not None:
                    lines += [
                        "    try",
                        f"      set position of theObj to {{{_as_num(x)}, {_as_num(y)}}}",
                        "    end try",
                    ]
        elif kind == "line" and start and end:
            lines += [
                "    try",
                f"      set start point of theObj to {{{_as_num(start[0])}, {_as_num(start[1])}}}",
                "    end try",
                "    try",
                f"      set end point of theObj to {{{_as_num(end[0])}, {_as_num(end[1])}}}",
                "    end try",
            ]
        else:
            if spec.get("w") is not None:
                lines += [
                    "    try",
                    f"      set width of theObj to {_as_num(spec['w'])}",
                    "    end try",
                ]
            if spec.get("h") is not None:
                lines += [
                    "    try",
                    f"      set height of theObj to {_as_num(spec['h'])}",
                    "    end try",
                ]
            if x is not None and y is not None:
                lines += [
                    "    try",
                    f"      set position of theObj to {{{_as_num(x)}, {_as_num(y)}}}",
                    "    end try",
                ]
        lines += [
            "    try",
            "      if wasLocked then set locked of theObj to true",
            "    end try",
            "  end try",
        ]
        body += lines
    if not body:
        return ""
    # A large deck's geometry can run well past osascript's 120s default.
    return "\n".join(
        ["with timeout of 3600 seconds", f"tell slide {int(slide_no)}"]
        + body
        + ["end tell", "end timeout"]
    )


def _spec_bears_geometry(spec: dict[str, Any]) -> bool:
    """Whether this transform carries geometry the JXA full pass would place."""
    if spec.get("w") is not None or spec.get("h") is not None:
        return True
    if spec.get("x") is not None and spec.get("y") is not None:
        return True
    if spec.get("start") is not None and spec.get("end") is not None:
        return True
    return False


def _slide_geometry_addressable(specs: list[dict[str, Any]]) -> bool:
    """Whether every geometry-bearing object on the slide has an AppleScript address.

    The AppleScript block can only address the kinds in ``_AS_KIND_NAMES``. JXA's
    ``getItem`` also resolves a ``table``/``chart``/unknown kind through its
    iWorkItems fallback and the full pass positions it, but the AppleScript block
    has no such fallback — so a slide carrying any geometry-bearing unaddressable
    object is kept OFF the AppleScript path entirely and left to the JXA full pass.
    Correctness (that object still gets moved) beats removing the flick on that one
    edge-case slide.
    """
    for spec in specs:
        if spec.get("role") == "hide":
            continue
        if not _spec_bears_geometry(spec):
            continue
        if str(spec.get("kind") or "") not in _AS_KIND_NAMES:
            return False
    return True


def _build_as_geometry(
    transform_dicts: list[dict[str, Any]],
    suppress: set[int] | frozenset[int] = frozenset(),
) -> dict[str, str]:
    """Per-slide AppleScript geometry bodies, keyed by slide number as a string.

    Built from the same transform dicts sent to JXA so the addressing matches
    object for object. A slide is included ONLY when every geometry-bearing object
    on it is AppleScript-addressable (see ``_slide_geometry_addressable``); an
    excluded slide has no key here, and the JXA loop then runs its full geometry
    path. The reuse path ignores this map regardless.

    A slide in ``suppress`` (see :func:`suppress_geometry_slides`) is omitted here
    too, so it carries no geometry body at all; ``applyNonReuseSlide`` then writes
    its attrs only and skips geometry entirely rather than falling through to the
    JXA full path.
    """
    by_slide: dict[int, list[dict[str, Any]]] = {}
    order: list[int] = []
    for spec in transform_dicts:
        slide_no = int(spec.get("slide") or 0)
        if slide_no < 1:
            continue
        if slide_no not in by_slide:
            by_slide[slide_no] = []
            order.append(slide_no)
        by_slide[slide_no].append(spec)
    out: dict[str, str] = {}
    for slide_no in order:
        if slide_no in suppress:
            continue
        specs = by_slide[slide_no]
        if not _slide_geometry_addressable(specs):
            continue
        body = _build_slide_geometry_script(specs, slide_no)
        if body:
            out[str(slide_no)] = body
    return out


def _run_jxa(plan: dict[str, Any]) -> dict[str, Any]:
    plan = {**plan, "bundleId": keynote_app.bundle_id()}
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(REMAP_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Keynote remap failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("Keynote remap returned no JSON.")
    return json.loads(raw)


def copy_keynote(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    subprocess.run(["ditto", str(source), str(dest)], check=True)
    return dest


def recipe_for(wall: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    return learn_recipe(wall, template)


def resolve_source_previews(
    source: Path,
    wall: dict[str, Any],
    *,
    folder: Path | str | None = None,
    wanted: list[int] | None = None,
) -> tuple[dict[int, Any], str]:
    """Rendered wall slides, keyed by slide number, for measuring empty space.

    Placing loose text needs to know where the CG is actually empty, which needs
    a picture of the slide. Rather than render one, this reuses an export that
    already exists: an explicit folder if given, otherwise the preview cache that
    any earlier inspect of this deck filled in. Both are free. When neither is
    available the caller falls back to blind packing.

    Returns the images plus a short label naming the source, because a stale
    preview folder produces a plausible-looking but wrong mask and the log is
    where that gets noticed.
    """
    from PIL import Image  # noqa: PLC0415

    from obed_edom.baseline import deck_digest, preview_cache_dir  # noqa: PLC0415
    from obed_edom.diff_keynotes import map_preview_pngs  # noqa: PLC0415
    from obed_edom.inspect import preview_media  # noqa: PLC0415

    candidates: list[tuple[Path, str]] = []
    if folder:
        candidates.append((Path(folder).expanduser(), "supplied folder"))
    if wall.get("previewDir"):
        candidates.append((Path(str(wall["previewDir"])), "this run's export"))
    try:
        candidates.append((preview_cache_dir(deck_digest(source)), "preview cache"))
    except (OSError, FileNotFoundError):
        pass

    slides = wall.get("slides") or []
    for path, label in candidates:
        if not path.is_dir():
            continue
        images = [p for p in preview_media(path) if p.suffix.lower() != ".mov"]
        if not images:
            continue
        by_index = map_preview_pngs(slides, images)
        out: dict[int, Any] = {}
        for index, png in by_index.items():
            if index >= len(slides):
                continue
            number = int(slides[index].get("number") or index + 1)
            if wanted and number not in wanted:
                continue
            try:
                out[number] = Image.open(png).convert("RGB")
            except OSError:
                continue
        if out:
            detail = f"{label} ({len(images)} image(s) for {len(slides)} slide(s))"
            if len(images) != len(slides):
                detail += " — count differs, check the export is current"
            return out, detail
    return {}, ""


def remap_keynote(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    include_lists: bool = False,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    framing_overrides: dict[int, int] | None = None,
    side_content_slides: set[int] | None = None,
    source_previews: Path | str | None = None,
    export_dir: Path | str | None = None,
    offline_read: str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy wall `source` to `dest`, remap map+pins in place using the CG template crop.

    `framing_overrides` maps a wall slide number to the template slide the operator
    confirmed, for the pages where the automatic choice was wrong.

    `side_content_slides` is the per-slide side-panel whitelist (wall slide numbers):
    side content is dropped everywhere else and kept on these pages.

    `export_dir`, when given, folds the PNG preview export into the stat-finalize
    session (it runs against the already-open deck before it closes), so the dest is
    not reopened a third time just to render previews. The result reports `exported`;
    a run with no stat-group jobs never opens that session, so the caller still exports
    those previews itself. Left unset (e.g. the validate=True read-back path), no
    export is folded and behaviour is unchanged.
    """
    def say(message: str) -> None:
        if log:
            log(message)

    source = Path(source).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    template_path = Path(template).expanduser().resolve()
    if not template_path.exists():
        raise FileNotFoundError(template_path)

    if wall_payload is not None:
        wall = wall_payload
    else:
        wall = acquire_wall_payload(
            source,
            slide_range=slide_range,
            mode=offline_read_mode(offline_read),
            say=say,
        )
    if wall_payload is None:
        if slide_range:
            label = format_slide_range(slide_range)
            say(
                f"Inspected {source.name} slide {label}: "
                f"canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}."
            )
        else:
            say(
                f"Inspected {source.name}: canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}, "
                f"{wall.get('slideCount')} slides."
            )
        note = navigator_numbering(wall)
        if note:
            say(note)
    if template_payload is not None:
        template_data = template_payload
    else:
        say(f"Inspecting CG template {template_path.name}…")
        template_data = inspect_keynote(template_path)

    recipe = recipe_for(wall, template_data)
    previews: dict[int, Any] = {}
    preview_note = ""
    # A rendered wall image lets loose text land on measured empty space rather than
    # blind right-to-left packing. Needed wherever side content is kept — globally or
    # on a whitelisted slide — so a whitelisted page packs its columns as well as the
    # old global flag did.
    if include_lists or side_content_slides:
        previews, preview_note = resolve_source_previews(
            source, wall, folder=source_previews, wanted=slides_for_plan(slide_range)
        )
    placements: list[dict[str, Any]] = []
    hidden: list[int] = []
    fitted: list[int] = []
    offframe: list[dict[str, Any]] = []
    framing_rows: list[dict[str, Any]] = []
    child_resize: list[dict[str, Any]] = []
    transforms = plan_payload_transforms(
        wall,
        recipe,
        slide_range=slide_range,
        include_lists=include_lists,
        template=template_data,
        previews=previews or None,
        placement_report=placements,
        skipped_slides=hidden,
        fitted_slides=fitted,
        offframe_report=offframe,
        framing_overrides=framing_overrides,
        framing_report=framing_rows,
        side_content_slides=side_content_slides,
        child_resize_report=child_resize,
    )
    confirmed = [r for r in framing_rows if r.get("confirmed")]
    if confirmed:
        overruled = [r for r in confirmed if r.get("fitted")]
        say(
            f"Used your confirmed framing on {len(confirmed)} slide(s)."
            + (
                f" {len(overruled)} of them still had to fall back to fitting content: "
                + ", ".join(str(r["slide"]) for r in overruled[:8])
                + " — that template slide cannot frame those pages."
                if overruled
                else ""
            )
        )
    reused = [r for r in framing_rows if r.get("reusedSibling")]
    if reused:
        say(
            f"Kept {len(reused)} slide(s) 1:1 with the page before them by reusing "
            "that framing's transform: "
            + ", ".join(str(r["slide"]) for r in reused[:10])
            + ("…" if len(reused) > 10 else "")
            + " (their own art paired to a sliver, but they share the pin and are "
            "adjacent, so the magic-move map stays put)."
        )
    overridden = [r for r in framing_rows if r.get("pinOverridden")]
    if overridden:
        say(
            f"Your pinned framing could not frame {len(overridden)} slide(s) "
            + ", ".join(str(r["slide"]) for r in overridden[:10])
            + ("…" if len(overridden) > 10 else "")
            + " — it would have shrunk them to a sliver, so their own best framing "
            "was used instead."
        )
    if fitted:
        say(
            f"No template framing matched {len(fitted)} slide(s) "
            + ", ".join(str(n) for n in fitted[:10])
            + ("…" if len(fitted) > 10 else "")
            + "; scaled their content to fit instead. Add a template slide for that layout."
        )
    if offframe:
        by_slide: dict[int, int] = {}
        for row in offframe:
            by_slide[int(row["slide"])] = by_slide.get(int(row["slide"]), 0) + 1
        detail = ", ".join(f"slide {n}: {c}" for n, c in sorted(by_slide.items())[:8])
        say(
            f"{len(offframe)} object(s) visible on the wall land outside the CG frame "
            f"({detail}). They are still in the deck — drag them back or adjust the template."
        )
    if hidden:
        say(
            f"Left {len(hidden)} skipped slide(s) alone: "
            + ", ".join(str(n) for n in hidden[:10])
            + ("…" if len(hidden) > 10 else "")
            + ". Un-skip in Keynote and re-run to include them."
        )
    reuses = plan_slide_reuses(wall, transforms, slide_range=slide_range)
    reuse_slides = {int(r["slide"]) for r in reuses}
    stat_adjustments = adjust_child_resize_for_deleted_hides(child_resize, transforms, reuse_slides)
    if stat_adjustments:
        say(
            f"Adjusted {len(stat_adjustments)} stat-group index(es) for deleted group hides on "
            "non-reuse slide(s): "
            + ", ".join(f"slide {a['slide']} {a['from']}→{a['to']}" for a in stat_adjustments[:8])
            + "."
        )
    counts = summarize_plan(transforms)
    say(
        f"Recipe {recipe.get('source')}: map {recipe.get('mapSrc')} → {recipe.get('mapDst')}; "
        f"{counts.get('map', 0)} map, {counts.get('pin', 0)} pin, {counts.get('list', 0)} list, "
        f"{counts.get('hide', 0)} hidden names"
        f"{'' if (include_lists or side_content_slides) else ' (side content dropped; whitelist a slide in the framing review to keep it)'}."
    )
    if include_lists and recipe.get("listFontSize"):
        if placements:
            crowded = [row for row in placements if row.get("overlap")]
            detail = f"{len(placements)} moved into empty space"
            if crowded:
                worst = max(row["overlap"] for row in crowded)
                detail += (
                    f", {len(crowded)} had to overlap artwork (worst {worst:.0%}) "
                    "— break those up by hand"
                )
            say(f"Church names → {recipe.get('listFontSize')}pt, {detail}. Measured from {preview_note}.")
        else:
            reason = "no wall previews found" if not previews else "nothing free to move"
            say(
                f"Church names → {recipe.get('listFontSize')}pt, packed from the right "
                f"(gutter first; extras may overlap the map) — {reason}."
            )
    styles = recipe.get("characterStyles") or []
    if styles:
        bits = []
        for s in styles:
            bit = f"{s.get('font') or 'sample'} {s.get('size')}pt"
            rgb = s.get("color")
            if rgb and len(rgb) >= 3:
                bit += f" rgb({int(rgb[0]*255)},{int(rgb[1]*255)},{int(rgb[2]*255)})"
            bits.append(bit)
        say("Unpaired text picks the closest CG character style: " + "; ".join(bits) + ".")
    if reuses:
        bits = []
        for job in reuses:
            extra = []
            if job.get("remove"):
                extra.append(f"drop {len(job['remove'])}")
            if job.get("add"):
                extra.append(f"add {len(job['add'])}")
            if job.get("mutate"):
                extra.append(f"tweak {len(job['mutate'])}")
            bits.append(
                f"slide {job['slide']}←{job['from']}"
                + (f" ({', '.join(extra)})" if extra else " (identical map/dots)")
            )
        say("Duplicating remapped slides for unchanged map/dots: " + "; ".join(bits) + ".")
    origin_pins = [
        t for t in transforms if t.role == "pin" and abs(t.x) < 2 and abs(t.y) < 2
    ]
    if len(origin_pins) > 10:
        raise RuntimeError(
            f"Planner put {len(origin_pins)} pins at (0,0); refusing to apply. "
            f"Wall canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}. "
            f"mapSrc={recipe.get('mapSrc')} mapDst={recipe.get('mapDst')}. "
            "Use the original 7680 wall .key, not a previous CG output."
        )
    say(f"Copying {source.name} → {dest.name}…")
    copy_keynote(source, dest)
    layout_dir = Path(tempfile.mkdtemp(prefix="obed-layouts-"))
    layout_src = layout_dir / template_path.name
    try:
        say(f"Copying 16:9 slide layouts from {template_path.name} onto the wall copy…")
        copy_keynote(template_path, layout_src)
        say("Setting 16:9 canvas, applying CG layouts, then map/pin positions…")
        transform_dicts = [t.as_dict() for t in transforms]
        suppressed = suppress_geometry_slides()
        plan: dict[str, Any] = {
            "dest": str(dest),
            "template": str(layout_src),
            "width": int(recipe.get("destWidth") or CG_WIDTH),
            "height": int(recipe.get("destHeight") or CG_HEIGHT),
            "transforms": transform_dicts,
            "reuses": reuses,
            # Non-reuse slides listed here write attrs but NO geometry (the offline
            # patcher's pass-1-only baseline). Read in applyNonReuseSlide alongside
            # asGeom; empty by default so behaviour is unchanged.
            "suppressGeometry": sorted(suppressed),
        }
        if suppressed:
            say(
                "OBED_SUPPRESS_GEOMETRY on: attrs-only (no geometry) for non-reuse "
                f"slide(s) {sorted(suppressed)}."
            )
        if as_geometry_enabled():
            # Non-reuse slides get their w/h/position written by a batched
            # AppleScript block (no JXA (0,0) flick); reuse slides stay on JXA.
            # A suppressed slide is omitted from the map so it stays attrs-only.
            plan["asGeometry"] = True
            plan["asGeom"] = _build_as_geometry(transform_dicts, suppress=suppressed)
            say(
                "OBED_AS_GEOMETRY on: non-reuse geometry via batched AppleScript "
                f"for {len(plan['asGeom'])} slide(s); reuse slides stay on JXA."
            )
        wanted = slides_for_plan(slide_range)
        if wanted:
            plan["slides"] = wanted
            plan["range"] = [wanted[0], wanted[-1]]
        if write_timing_enabled():
            plan["timing"] = {"slowMs": 120}
            say("OBED_WRITE_TIMING on: recording per-slide/per-phase write timing.")
        jxa = _run_jxa(plan)
    finally:
        shutil.rmtree(layout_dir, ignore_errors=True)
    if jxa.get("timing"):
        _say_write_timing(jxa["timing"], say)
    applied = int(jxa.get("applied") or 0)
    missed = int(jxa.get("missed") or 0)
    if jxa.get("collections"):
        say(f"Keynote collections: {jxa.get('collections')}")
    if applied == 0:
        detail = ""
        if jxa.get("collections"):
            detail += f" collections={jxa.get('collections')}"
        if jxa.get("missReasons"):
            detail += f" misses={jxa.get('missReasons')}"
        raise RuntimeError(
            "Keynote remap moved 0 objects; the copy was left at the wall canvas size."
            f" Planned {len(transforms)} transform(s), missed {missed}.{detail}"
        )
    say(f"Applied {applied}, missed {missed}.")
    if jxa.get("cloned"):
        say(f"Duplicated {jxa.get('cloned')} remapped slide(s) instead of re-placing the map and dots.")
    layouts = jxa.get("layouts") or {}
    if layouts.get("imported"):
        say(f"Imported 16:9 layouts: {', '.join(str(n) for n in layouts['imported'])}.")
    applied_layouts = layouts.get("applied") or []
    if applied_layouts:
        sample = applied_layouts[0]
        say(
            f"Applied {sample.get('to') or 'CG layout'} to "
            f"{len(applied_layouts)} slide(s)."
        )
    if jxa.get("mapReadback"):
        say(f"Map object after apply: {jxa.get('mapReadback')}")
    actual_w = jxa.get("width")
    actual_h = jxa.get("height")
    if actual_w and actual_h:
        say(f"Canvas after remap: {actual_w}×{actual_h}.")
    if jxa.get("skippedSlides"):
        say(f"Skipped {jxa.get('skippedSlides')} other slide(s) so the preview is this slide only.")
    # The wall crop keeps the 1080 frame height, so a wall-authored stat number is
    # already correctly sized relative to the frame — the JXA placement is fine. Two
    # things JXA can't do: give each number the exact point size the template teaches
    # (a group is opaque to JXA), and lift the stat text + Global Missions badge in
    # front of the map they were authored behind. An AppleScript pass does both. No-op
    # when the plan emitted no stat-group jobs.
    export_path = Path(export_dir).expanduser().resolve() if export_dir else None
    child_resize_result: dict[str, Any] | None = None
    if child_resize:
        stat_sizes = read_template_stat_sizes(template_path)
        say(
            f"Finalizing {len(child_resize)} stat group(s): template sizes "
            f"({', '.join(f'{k}→{int(v)}pt' for k, v in sorted(stat_sizes.items())) or 'none found'}) "
            "+ bring to front."
            + (" Exporting previews in the same session." if export_path else "")
        )
        child_resize_result = _run_stat_finalize(
            dest, child_resize, stat_sizes, export_dir=export_path
        )
        done = child_resize_result.get("done") or 0
        skipped = child_resize_result.get("skipped") or 0
        sized = child_resize_result.get("sized") or 0
        front = child_resize_result.get("front") or 0
        if child_resize_result.get("ok"):
            say(
                f"Stat-finalize pass: {done} group(s) done, {sized} number(s) sized to "
                f"the template, {front} object(s) brought to front"
                + (f", {skipped} skipped" if skipped else "")
                + "."
            )
        else:
            say(
                "Stat-finalize pass did not complete; stat groups stay at the JXA "
                "placement/size. See the .stat-finalize.applescript dump."
            )
    result: dict[str, Any] = {
        "source": str(source),
        "dest": str(dest),
        "template": str(template_path),
        "recipe": recipe,
        "counts": counts,
        "applied": applied,
        "missed": missed,
        "width": jxa.get("width"),
        "height": jxa.get("height"),
        "collections": jxa.get("collections"),
        "slideRange": slides_for_plan(slide_range),
        "skippedSlides": jxa.get("skippedSlides"),
        "layouts": jxa.get("layouts"),
        # Against the template this is a self-consistency check, not a quality
        # score: the recipe was learned from that same template, so a non-zero
        # figure means the planner did not apply the affine it derived. Use
        # scripts/score_resize.py against a finished CG deck to judge output.
        "templateScore": score_against_gold(transforms, template_data, wall=wall),
        "placements": placements,
        "placementSource": preview_note,
        "skippedSlidesLeftAlone": hidden,
        "fittedSlides": fitted,
        "offFrame": offframe,
        "framingReport": framing_rows,
        "childResize": child_resize_result,
        # True only when the stat-finalize session actually rendered the previews;
        # the caller falls back to a standalone export otherwise.
        "exported": bool(child_resize_result and child_resize_result.get("exported")),
        "previewFiles": list(
            (child_resize_result or {}).get("previewFiles") or []
        ),
    }
    return result


def remap_and_inspect(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    include_lists: bool = False,
    export_dir: Path | str | None = None,
    source_previews: Path | str | None = None,
    framing_overrides: dict[int, int] | None = None,
    side_content_slides: set[int] | None = None,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    validate: bool = True,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    info = remap_keynote(
        source,
        dest,
        template=template,
        slide_range=slide_range,
        include_lists=include_lists,
        source_previews=source_previews,
        framing_overrides=framing_overrides,
        side_content_slides=side_content_slides,
        wall_payload=wall_payload,
        template_payload=template_payload,
        # Fold the export into the stat-finalize session on the no-read-back path
        # only. The validate=True path reads the deck back with inspect_keynote,
        # which does its own export, so it must stay unchanged (export_dir unset).
        export_dir=export_dir if not validate else None,
        log=log,
    )
    # Reading the deck back dumps every object, which is what the validation
    # flags are built from. A run whose wall content has already been checked
    # only wants the pictures, and those come from a Keynote pass that does not
    # walk the objects at all.
    if not validate:
        # The stat-finalize session already exported when it ran; only fall back to a
        # standalone export when it didn't (no stat-group jobs, or its export failed).
        if export_dir and not info.get("exported"):
            if log:
                log("Exporting previews (validation off, so the deck is not read back)…")
            error = export_slide_images(Path(dest), Path(export_dir))
            if error and log:
                log(error)
        info["inspect"] = {"exported": bool(export_dir), "exportError": ""}
        if export_dir:
            info["previewFiles"] = [p.name for p in preview_pngs(Path(export_dir))]
        return info
    if log:
        log("Inspecting remapped deck…")
    # use_cache=False on the readback. `dest` is a freshly-written output deck with a
    # unique digest every run, so a digest-keyed cache entry never hits again — caching
    # it only hashes the just-written (multi-GB) deck for nothing and pollutes
    # .cache/inspect + .cache/previews with a never-reused full preview set. It also
    # fixes the served-previews bug: with want_cache on, inspect_keynote redirects the
    # export into preview_cache_dir(digest) (inspect.py:138-140), but remap_and_inspect
    # and _run_resize build previewFiles/previewDir from the ORIGINAL export_dir, which
    # is then empty ⇒ the dashboard shows nothing. use_cache=False keeps the export in
    # export_dir where the web layer serves it from.
    payload = inspect_keynote(
        dest, export_dir=export_dir, slide_range=slide_range, use_cache=False
    )
    info["inspect"] = {
        "slideWidth": payload.get("slideWidth"),
        "slideHeight": payload.get("slideHeight"),
        "slideCount": payload.get("slideCount"),
        "exported": payload.get("exported"),
        "exportError": payload.get("exportError") or "",
    }
    info["payload"] = payload
    if export_dir:
        info["previewFiles"] = [p.name for p in preview_pngs(Path(export_dir))]
    return info

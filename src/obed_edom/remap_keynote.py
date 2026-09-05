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

from obed_edom import keynote_app, offline_write
from obed_edom.inspect import export_slide_images, inspect_keynote, preview_pngs
from obed_edom.keynote import _run_stat_finalize, read_template_stat_sizes
from obed_edom.map_remap import (
    adjust_child_resize_indexes,
    navigator_numbering,
    CG_HEIGHT,
    CG_WIDTH,
    DEFAULT_CARD_STROKE,
    GRID_MIN_CLEAR,
    format_slide_range,
    learn_recipe,
    plan_payload_transforms,
    plan_slide_reuses,
    score_against_gold,
    slides_for_plan,
    summarize_plan,
)

REMAP_JS = Path(__file__).resolve().parent / "remap_keynote.js"

# AppleScript index is JXA kindIndex + 1 (same sdef collection, same order).
_AS_KIND_NAMES = {
    "text": "text item",
    "image": "image",
    "shape": "shape",
    "movie": "movie",
    "group": "group",
    "line": "line",
}


def as_geometry_enabled() -> bool:
    """Batched-AppleScript geometry path (default ON). `OBED_AS_GEOMETRY=0` forces legacy JXA."""
    return os.environ.get("OBED_AS_GEOMETRY", "").strip().lower() not in {"0", "false", "no", "off"}


def suppress_geometry_slides() -> set[int]:
    """1-based slides whose pass-1 write is attrs-only. Without `OBED_SUPPRESS_GEOMETRY`, empty-asGeom falls through to JXA full path."""
    raw = os.environ.get("OBED_SUPPRESS_GEOMETRY", "")
    slides: set[int] = set()
    for token in raw.replace(",", " ").split():
        try:
            slides.add(int(token))
        except ValueError:
            continue
    return slides


def offline_read_mode(explicit: str | None = None) -> str:
    """`on` (default two-tier IWA+bulk) or `off` (legacy JXA inspect). `explicit` wins over `OBED_OFFLINE_READ`."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_READ", "")).strip().lower()
    return raw if raw in {"on", "off"} else "on"


def offline_write_mode(explicit: str | None = None, *, say: Callable[[str], None] | None = None) -> str:
    """`off` (default), `on` (surgical offline IWA patch), or `verify` (patch + live
    verify). Env `OBED_OFFLINE_WRITE`. Forced `off` when `as_geometry_enabled()` is False:
    the offline write's AppleScript fallback is the same batched-geometry body that flag disables."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_WRITE", "")).strip().lower()
    mode = raw if raw in {"on", "verify"} else "off"
    if mode != "off" and not as_geometry_enabled():
        if say:
            say(
                f"OBED_OFFLINE_WRITE={mode!r} needs OBED_AS_GEOMETRY on (its AppleScript "
                "fallback is the batched-geometry body); forcing offline write off."
            )
        return "off"
    return mode


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
    """Replace the given slides' items in `payload` with one scoped legacy inspect."""
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
    """Source-wall inspect honouring offline-read mode.

    `on`: IWA + bulk geometry, with per-slide legacy fallback — never drop the whole deck unless tier 1 fails.
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

    if not sidecar.get("bulk_ok") and fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Bulk geometry read of {source.name} unavailable and "
            f"{len(fallback_slides)} slide(s) need it {reasons}; "
            f"using Keynote inspect for the whole deck.")
        return inspect_keynote(source, slide_range=slide_range)

    if fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Two-tier read of {source.name}: {sidecar.get('spliced', 0)} item(s) "
            f"bulk-confirmed; {len(fallback_slides)} slide(s) fall back to Keynote "
            f"inspect {reasons}: {fallback_slides}.")
        _merge_legacy_slides(offline, source, fallback_slides)

    confirmed = "" if not fallback_slides else f" ({len(fallback_slides)} slide(s) via Keynote)"
    omitted = int(sidecar.get("skipped") or 0)
    skipped_note = "" if not omitted else f"; {omitted} Keynote-skipped slide(s) left to the offline tier"
    say(f"Read {source.name} two-tier (offline IWA + bulk geometry){confirmed}{skipped_note} — "
        f"skipped the full Keynote source inspect.")
    return offline


def write_timing_enabled() -> bool:
    """When ON (`OBED_WRITE_TIMING=1`), record per-slide/per-phase JXA write timing."""
    return os.environ.get("OBED_WRITE_TIMING", "").strip().lower() in {"1", "true", "yes", "on"}


def geom_props_enabled() -> bool:
    """Fold size into one `set properties {width, height}`; position stays a separate last write.

    Height re-anchors ~18px about centre; folding position into the same record drifts the object.
    """
    return os.environ.get("OBED_GEOM_PROPS", "").strip().lower() not in {"0", "false", "no", "off"}


def _say_write_timing(timing: dict[str, Any], say: Callable[[str], None]) -> None:
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
    number = float(value)
    if number == int(number):
        return str(int(number))
    return repr(round(number, 2))


def _child_ops_lines(children: list[dict[str, Any]]) -> list[str]:
    """Absolute per-child writes for a group holding an autosize text box.

    The group itself is NEVER written. A Keynote 15.3.1 group resize is an aspect-locked
    uniform scale about the group's LIVE frame and it freezes autosize text children at
    their wrapped height for ever (no later width or font write re-flows them). Children
    take exact absolute writes in slide coordinates and the group's frame follows as the
    union. An autosize child gets a WIDTH only — a height write is ignored AND re-anchors
    the box — then a position centred on its mapped vertical centre using the height
    Keynote has just derived from the new width.
    """
    lines: list[str] = []
    for child in children:
        name = _AS_KIND_NAMES.get(str(child.get("kind") or ""))
        index = child.get("kindIndex")
        if not name or index is None:
            continue
        lines += ["    try", f"      set _c to {name} {int(index) + 1} of theObj"]
        if child.get("autosize"):
            lines += [
                f"      set width of _c to {_as_num(child['w'])}",
                "      set _ch to height of _c",
                "      if _ch > 0 then",
                f"        set position of _c to {{{_as_num(child['x'])}, "
                f"({_as_num(child['cy'])} - (_ch / 2))}}",
                "      else",
                f"        set position of _c to {{{_as_num(child['x'])}, {_as_num(child['y'])}}}",
                "      end if",
            ]
        else:
            lines += [
                f"      set properties of _c to {{width:{_as_num(child['w'])}, "
                f"height:{_as_num(child['h'])}}}",
                f"      set position of _c to {{{_as_num(child['x'])}, {_as_num(child['y'])}}}",
            ]
        lines += ["    end try"]
    return lines


def _build_slide_geometry_script(specs: list[dict[str, Any]], slide_no: int) -> str:
    """One `tell slide N` block setting geometry.

    Width/height before position (height re-anchors ~18px). Lines use endpoints; AppleScript does not yank to (0,0).
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
        children = spec.get("children") if kind == "group" else None
        if children:
            # No group-level size or position write on this path — either one would
            # aspect-lock-scale the group about its wrapped live frame and freeze the
            # autosize child (Gold slide 2: 278x88 -> 23x88, name renders as "P").
            lines += _child_ops_lines(children)
        elif geom_props_enabled():
            # Position MUST stay a separate last write: height re-anchors ~18px about centre.
            # Lines have no re-anchor; fold endpoints into one atomic set.
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
    # Geometry can run past osascript's 120s default.
    return "\n".join(
        ["with timeout of 3600 seconds", f"tell slide {int(slide_no)}"]
        + body
        + ["end tell", "end timeout"]
    )


def _spec_bears_geometry(spec: dict[str, Any]) -> bool:
    if spec.get("w") is not None or spec.get("h") is not None:
        return True
    if spec.get("x") is not None and spec.get("y") is not None:
        return True
    if spec.get("start") is not None and spec.get("end") is not None:
        return True
    return False


def _slide_geometry_addressable(specs: list[dict[str, Any]]) -> bool:
    """False if any geometry-bearing object is outside `_AS_KIND_NAMES` — keep that slide on JXA."""
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
    """Per-slide AppleScript geometry bodies. Suppressed slides omitted so they stay attrs-only (no JXA fallback)."""
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


def _resolve_template_card_sample(card_samples: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Same resolution `plan_slide_transforms` does per wall match (dominant same-size
    cluster + `_card_pitch`), computed once here purely for the operator summary line —
    `recipe["cardSamples"]` is deck-wide and does not depend on which wall group matched."""
    if not card_samples:
        return None
    from collections import defaultdict  # noqa: PLC0415

    from obed_edom.map_remap import _card_pitch, _rect_from_dict  # noqa: PLC0415

    clusters: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for s in card_samples:
        clusters[(round(s["rect"]["w"], 1), round(s["rect"]["h"], 1))].append(s)
    _key, members = max(clusters.items(), key=lambda kv: len(kv[1]))
    w = sum(m["rect"]["w"] for m in members) / len(members)
    h = sum(m["rect"]["h"] for m in members) / len(members)
    raw = [
        {"rect": _rect_from_dict(s["rect"]), "aspect": s["aspect"], "caption": s["caption"]}
        for s in card_samples
    ]
    pitch = _card_pitch(raw, w, h)
    return {"w": w, "h": h, "gutterX": pitch["gutterX"], "gutterY": pitch["gutterY"]}


def resolve_source_previews(
    source: Path,
    wall: dict[str, Any],
    *,
    folder: Path | str | None = None,
    wanted: list[int] | None = None,
) -> tuple[dict[int, Any], str]:
    """Rendered wall slides keyed by number, for measuring empty space for loose text."""
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


def restore_card_stroke_widths(
    dest: Path, source: Path, wall: dict[str, Any], say: Callable[[str], None]
) -> dict[str, Any]:
    """Canvas shrink divides every image-card stroke width along with the geometry;
    restore each canvas-shrunk card border to its source width, unconditional (not
    gated by OBED_OFFLINE_WRITE), before the stat-finalize pass. Deck untouched on
    any refusal/pairing miss for a given style; a resolved style is patched alone."""
    try:
        from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415
        from obed_edom.iwa_write import (  # noqa: PLC0415
            card_styles,
            match_card_stroke_styles,
            patch_stroke_widths,
        )
    except Exception as exc:  # noqa: BLE001 — optional iwa extra; never break the run
        say(f"Card-border stroke patch unavailable ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    try:
        out_objects, out_id_to_file, _out_fi = _load_deck(dest)
        src_objects, src_id_to_file, _src_fi = _load_deck(source)
    except Exception as exc:  # noqa: BLE001 — offline read is opt-in; never break the run
        say(f"Card-border stroke patch could not read the deck(s) ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    wall_w = float(wall.get("slideWidth") or CG_WIDTH)
    canvas_scale = (CG_WIDTH / wall_w) if wall_w > 0 else 1.0

    match = match_card_stroke_styles(
        card_styles(out_objects, out_id_to_file),
        card_styles(src_objects, src_id_to_file),
        canvas_scale=canvas_scale,
        min_refs=10,
    )
    if not match["out_selected"]:
        return {"skipped": True, "reason": "no card styles selected in the output"}
    for note in match["notes"]:
        say(note)
    if not match["widths"]:
        return {"skipped": True, "reason": "no card style pair passed the guard"}

    for c in match["chosen"]:
        say(f"Card-border stroke: {c['id']} {c['old']} → {c['new']} ({c['refs']} refs).")

    result = patch_stroke_widths(dest, match["widths"])
    if result.get("refused"):
        say(f"Card-border stroke patch REFUSED: {result.get('reason')}")
    return result


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
    plan_out: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy wall `source` to `dest` and remap in place from the CG template crop."""
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

    try:
        from obed_edom.iwa_runs import attach_group_captions  # noqa: PLC0415

        attach_group_captions(template_path, template_data)
    except Exception as exc:  # noqa: BLE001 — card samples stay unavailable, cards keep the affine size
        say(
            f"Template caption geometry unavailable ({type(exc).__name__}: {exc}); "
            "photo cards will keep today's affine size instead of the template's."
        )

    card_stroke = DEFAULT_CARD_STROKE
    deck = None
    try:
        from obed_edom.iwa_runs import (  # noqa: PLC0415
            _load_deck, attach_group_captions, attach_group_child_text, attach_group_children,
        )

        deck = _load_deck(source)
        attach_group_child_text(source, wall, deck=deck)
        attach_group_captions(source, wall, deck=deck)
        attach_group_children(source, wall, deck=deck)
    except Exception as exc:  # noqa: BLE001 — no group signatures/captions on any failure
        say(
            f"Wall IWA decode unavailable ({type(exc).__name__}: {exc}); reuse group dedup "
            "will report a shortfall instead of deduping, and photo cards will not be "
            "recognised as cards at all (no groupChildText signature to match on) — they "
            "keep today's affine-mapped size, same as any other unmatched group; groups "
            "holding an autosize text box keep today's group-level resize (which collapses "
            "them)."
        )

    try:
        from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415
        from obed_edom.iwa_write import card_styles, select_card_styles  # noqa: PLC0415

        objects, id_to_file, _file_ids = deck if deck is not None else _load_deck(source)
        selected = [
            s
            for s in select_card_styles(card_styles(objects, id_to_file), min_refs=10)
            if not s.get("inherited")
        ]
        widths = sorted(s["width"] for s in selected if s.get("width") is not None)
        if widths:
            card_stroke = widths[len(widths) // 2]
    except Exception as exc:  # noqa: BLE001 — fall back to the measured default
        say(
            f"Card-border stroke read unavailable ({type(exc).__name__}: {exc}); "
            f"the card grid's fallback-pitch floor uses {card_stroke}pt instead."
        )

    recipe = recipe_for(wall, template_data)
    previews: dict[int, Any] = {}
    preview_note = ""
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
    badge_raises: list[dict[str, Any]] = []
    card_grid: list[dict[str, Any]] = []
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
        badge_raise_report=badge_raises,
        card_stroke=card_stroke,
        card_grid_report=card_grid,
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
    card_rows = [r for r in child_resize if r.get("captionPt")]
    if recipe.get("cardSamples"):
        resolved = _resolve_template_card_sample(recipe.get("cardSamples"))
        card_slides = sorted({int(r["slide"]) for r in card_rows})
        if resolved is not None:
            gx, gy = resolved.get("gutterX"), resolved.get("gutterY")
            pitch_source = "template" if gx is not None and gy is not None else "wall fallback"
            gutter_txt = f"{gx:.2f}/{gy:.2f}" if gx is not None and gy is not None else "n/a"
            say(
                f"Template card sample: {len(recipe['cardSamples'])} copies at "
                f"{resolved['w']:.1f}×{resolved['h']:.1f}, gutters {gutter_txt} ({pitch_source}); "
                f"{len(card_rows)} wall card(s) matched"
                + (f" on slides {card_slides}" if card_slides else " (none)")
                + "."
            )
        else:
            say(
                f"Template card sample: {len(recipe['cardSamples'])} copies found; "
                f"{len(card_rows)} wall card(s) matched"
                + (f" on slides {card_slides}" if card_slides else " (none)")
                + "."
            )
    if card_grid:
        for row in card_grid:
            overlaps = row.get("overlaps") or []
            clear_x, clear_y = row.get("clearX"), row.get("clearY")
            below = (
                " (below 7pt)"
                if (clear_x is not None and clear_x < GRID_MIN_CLEAR)
                or (clear_y is not None and clear_y < GRID_MIN_CLEAR)
                else ""
            )
            say(
                f"Slide {row['slide']}: {row['n']} card(s) reflowed to {row['cols']}×{row['rows']}, "
                f"pitch {row['pitchX']}/{row['pitchY']} (gutter {row['gutterX']}/{row['gutterY']}, "
                f"clear {clear_x}/{clear_y} at {card_stroke}pt stroke{below}), "
                f"origin ({row['x0']}, {row['y0']}), {row['offCanvas']} off-canvas"
                + (f", {len(overlaps)} overlapping a stat group" if overlaps else "")
                + "."
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
    # Group removes skip JXA deleteRefs (duplicate re-derives the frame). Dedup by child-text in stat-finalize.
    group_removes: list[dict[str, Any]] = []
    for r in reuses:
        for gr in r.get("groupRemove") or []:
            group_removes.append(
                {
                    "slide": int(r["slide"]),
                    "childSig": gr.get("childSig"),
                    "expectedKeep": gr.get("expectedKeep"),
                }
            )
    stat_adjustments = adjust_child_resize_indexes(child_resize, transforms, reuse_slides)
    if stat_adjustments:
        say(
            f"Adjusted {len(stat_adjustments)} stat-group index(es) for deleted group hides or "
            "voided on reuse slide(s): "
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
        child_written = sum(1 for t in transform_dicts if t.get("children"))
        if child_written:
            say(
                f"Group child geometry: {child_written} group(s) hold an autosize text box "
                "and are written child-by-child (a group-level resize would freeze the text "
                "wrapped); all other groups keep the absolute group write."
            )
        wanted = slides_for_plan(slide_range)
        env_suppressed = suppress_geometry_slides()
        offline_mode = offline_write_mode(say=say)
        offline_mode = offline_write.probe_iwa_extra(offline_mode, say)
        offline_slides: set[int] = set()
        if offline_mode != "off":
            offline_slides = offline_write._offline_write_slides(
                transform_dicts, reuses, reuse_slides, wanted
            )
            donors = {int(r["from"]) for r in reuses if r.get("from") is not None}
            say(
                f"OBED_OFFLINE_WRITE={offline_mode}: {len(offline_slides)} slide(s) go "
                f"offline (surgical IWA patch); {len(reuse_slides)} reuse-target + "
                f"{len(donors)} donor slide(s) stay on the AppleScript path."
            )
        suppressed = env_suppressed | offline_slides
        plan: dict[str, Any] = {
            "dest": str(dest),
            "template": str(layout_src),
            "width": int(recipe.get("destWidth") or CG_WIDTH),
            "height": int(recipe.get("destHeight") or CG_HEIGHT),
            "transforms": transform_dicts,
            "reuses": reuses,
            "suppressGeometry": sorted(suppressed),
        }
        if env_suppressed:
            say(
                "OBED_SUPPRESS_GEOMETRY on: attrs-only (no geometry) for non-reuse "
                f"slide(s) {sorted(env_suppressed)}."
            )
        if as_geometry_enabled():
            plan["asGeometry"] = True
            plan["asGeom"] = _build_as_geometry(transform_dicts, suppress=suppressed)
            say(
                "OBED_AS_GEOMETRY on: non-reuse geometry via batched AppleScript "
                f"for {len(plan['asGeom'])} slide(s); reuse slides stay on JXA."
            )
        if wanted:
            plan["slides"] = wanted
            plan["range"] = [wanted[0], wanted[-1]]
        if write_timing_enabled():
            plan["timing"] = {"slowMs": 120}
            say("OBED_WRITE_TIMING on: recording per-slide/per-phase write timing.")
        if plan_out is not None:
            plan_out["transforms"] = transform_dicts
            plan_out["reuses"] = reuses
            plan_out["suppressGeometry"] = plan.get("suppressGeometry")
            plan_out["asGeom"] = plan.get("asGeom")
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
    for entry in jxa.get("removeShortfalls") or []:
        slide_no = entry.get("slide")
        short = {
            kind: rec
            for kind, rec in (entry.get("byKind") or {}).items()
            if int((rec or {}).get("shortfall") or 0) > 0
        }
        if short:
            detail = ", ".join(
                f"{rec['removed']} of {rec['expected']} {kind}"
                for kind, rec in sorted(short.items())
            )
            say(
                f"WARNING reuse slide {slide_no}: only removed {detail} on the donor "
                "copy — a stranded donor object survived (doubling) until it is deduped."
            )
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
    offline_write_info = offline_write.run_offline_write(
        dest, offline_mode, offline_slides, transform_dicts, wall, child_resize, say
    )
    # Card border stroke widths shrink with the canvas; restore them before the stat-finalize
    # pass. Always runs — not gated by OBED_OFFLINE_WRITE.
    card_stroke_result = restore_card_stroke_widths(dest, source, wall, say)
    map_slide = next((int(t.slide_number) for t in transforms if t.role == "map"), None)
    if jxa.get("mapReadback") and map_slide not in offline_slides:
        say(f"Map object after apply: {jxa.get('mapReadback')}")
    actual_w = jxa.get("width")
    actual_h = jxa.get("height")
    if actual_w and actual_h:
        say(f"Canvas after remap: {actual_w}×{actual_h}.")
    if jxa.get("skippedSlides"):
        say(f"Skipped {jxa.get('skippedSlides')} other slide(s) so the preview is this slide only.")
    if card_rows:
        swatch = max(r["captionPt"] for r in card_rows)
        downs = sorted(
            (r for r in card_rows if r["captionPt"] < swatch),
            key=lambda r: (-r["captionPt"], r.get("childSig") or ""),
        )
        detail = ", ".join(f"{r.get('childSig')} {int(r['captionPt'])}" for r in downs[:10])
        say(
            f"Card captions: {len(card_rows)} at the template swatch {int(swatch)}pt"
            + (
                f"; {len(downs)} stepped down to fit ({detail}"
                + ("…" if len(downs) > 10 else "")
                + ")"
                if downs
                else ""
            )
            + "."
        )
        refusals = [r for r in card_rows if r.get("captionRefusal")]
        if refusals:
            say(
                f"WARNING: {len(refusals)} card caption(s) could not be measured "
                f"({refusals[0].get('captionRefusal')}) — kept at the template swatch size."
            )
    # JXA cannot size grouped stat numbers or restack them; AppleScript sets template point size and Bring to Front.
    export_path = Path(export_dir).expanduser().resolve() if export_dir else None
    child_resize_result: dict[str, Any] | None = None
    if child_resize or group_removes or badge_raises:
        stat_sizes = read_template_stat_sizes(template_path) if child_resize else {}
        say(
            f"Finalizing {len(child_resize)} stat group(s): template sizes "
            f"({', '.join(f'{k}→{int(v)}pt' for k, v in sorted(stat_sizes.items())) or 'none found'}) "
            "+ bring to front"
            + (
                f"; deduping {len(group_removes)} stranded donor-copy group(s)"
                if group_removes
                else ""
            )
            + (f"; raising {len(badge_raises)} badge object(s)" if badge_raises else "")
            + "."
            + (" Exporting previews in the same session." if export_path else "")
        )
        child_resize_result = _run_stat_finalize(
            dest,
            child_resize,
            stat_sizes,
            export_dir=export_path,
            group_removes=group_removes,
            badge_raises=badge_raises,
        )
        done = child_resize_result.get("done") or 0
        skipped = child_resize_result.get("skipped") or 0
        sized = child_resize_result.get("sized") or 0
        front = child_resize_result.get("front") or 0
        dedup_deleted = child_resize_result.get("dedupDeleted") or 0
        dedup_shortfall = child_resize_result.get("dedupShortfall") or 0
        sig_fallback = child_resize_result.get("sigFallback") or 0
        unresolved = child_resize_result.get("unresolved") or 0
        badge_fallback = child_resize_result.get("badgeFallback") or 0
        badge_unresolved = child_resize_result.get("badgeUnresolved") or 0
        if child_resize_result.get("ok"):
            say(
                f"Stat-finalize pass: {done} group(s) done, {sized} number(s) sized to "
                f"the template, {front} object(s) brought to front"
                + (f", {dedup_deleted} donor-copy group(s) deduped" if group_removes else "")
                + (f", {skipped} skipped" if skipped else "")
                + (f", {sig_fallback} sig-fallback(s)" if sig_fallback else "")
                + (f", {badge_fallback} badge-fallback(s)" if badge_fallback else "")
                + "."
            )
            if dedup_shortfall:
                say(
                    f"WARNING stat-finalize: {dedup_shortfall} donor-copy group(s) could "
                    "NOT be safely deduped (live count did not equal expectedKeep + "
                    "deleteCount, or the signature did not match) — kept, not guessed; "
                    "doubling may persist."
                )
            if unresolved:
                say(
                    f"WARNING stat-finalize: {unresolved} stat group(s) could NOT be "
                    "unambiguously resolved — kept, not guessed — those stat groups keep "
                    "their wall font size and stay buried."
                )
            if badge_unresolved:
                say(
                    f"WARNING stat-finalize: {badge_unresolved} badge object(s) could NOT be "
                    "unambiguously resolved — kept, not guessed — those badge objects stay "
                    "buried under the map."
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
        "removeShortfalls": jxa.get("removeShortfalls") or [],
        "slideRange": slides_for_plan(slide_range),
        "skippedSlides": jxa.get("skippedSlides"),
        "layouts": jxa.get("layouts"),
        "templateScore": score_against_gold(transforms, template_data, wall=wall),
        "placements": placements,
        "placementSource": preview_note,
        "skippedSlidesLeftAlone": hidden,
        "fittedSlides": fitted,
        "offFrame": offframe,
        "framingReport": framing_rows,
        "childResize": child_resize_result,
        "exported": bool(child_resize_result and child_resize_result.get("exported")),
        "previewFiles": list(
            (child_resize_result or {}).get("previewFiles") or []
        ),
    }
    if offline_write_info is not None:
        result["offlineWrite"] = offline_write_info
    result["cardStroke"] = card_stroke_result
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
    plan_out: dict[str, Any] | None = None,
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
        plan_out=plan_out,
        export_dir=export_dir if not validate else None,
        log=log,
    )
    if not validate:
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
    ow = info.get("offlineWrite")
    if ow and ow.get("mode") == "verify":
        planned = {int(n): specs for n, specs in (ow.get("specs") or {}).items()}
        stat_slides = frozenset(ow.get("statSlides") or [])
        live_report = offline_write.verify_live_frames(
            planned, payload, exclude_slides=stat_slides
        )
        ow["liveVerifyPass"] = offline_write._say_verify_report(
            "offline-write live verify", live_report, offline_write.LIVE_VERIFY_TOL, log
        )
    if export_dir:
        info["previewFiles"] = [p.name for p in preview_pngs(Path(export_dir))]
    return info

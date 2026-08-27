from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from obed_edom import keynote_app
from obed_edom.inspect import export_slide_images, inspect_keynote, preview_pngs
from obed_edom.keynote import _run_group_child_resize
from obed_edom.map_remap import (
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
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy wall `source` to `dest`, remap map+pins in place using the CG template crop.

    `framing_overrides` maps a wall slide number to the template slide the operator
    confirmed, for the pages where the automatic choice was wrong.

    `side_content_slides` is the per-slide side-panel whitelist (wall slide numbers):
    side content is dropped everywhere else and kept on these pages.
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

    wall = wall_payload if wall_payload is not None else inspect_keynote(source, slide_range=slide_range)
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
        plan: dict[str, Any] = {
            "dest": str(dest),
            "template": str(layout_src),
            "width": int(recipe.get("destWidth") or CG_WIDTH),
            "height": int(recipe.get("destHeight") or CG_HEIGHT),
            "transforms": [t.as_dict() for t in transforms],
            "reuses": reuses,
        }
        wanted = slides_for_plan(slide_range)
        if wanted:
            plan["slides"] = wanted
            plan["range"] = [wanted[0], wanted[-1]]
        jxa = _run_jxa(plan)
    finally:
        shutil.rmtree(layout_dir, ignore_errors=True)
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
    # JXA parked each stat group at wall size (it cannot scale a group or reach its
    # children), so an AppleScript pass now shrinks each group's leaves in place to
    # CG size. No-op when the plan emitted no stat-group jobs; the JXA whole-group
    # move stays as the fallback for any group this pass reports it could not resolve.
    child_resize_result: dict[str, Any] | None = None
    if child_resize:
        say(f"Resizing children of {len(child_resize)} stat group(s) to CG size…")
        child_resize_result = _run_group_child_resize(dest, child_resize)
        done = child_resize_result.get("done") or 0
        skipped = child_resize_result.get("skipped") or 0
        leaves = child_resize_result.get("leaves") or 0
        if child_resize_result.get("ok"):
            say(
                f"Child-resize pass: {done} group(s) done, {leaves} leaf/leaves scaled"
                + (f", {skipped} group(s) skipped (fell back to the whole-group move)" if skipped else "")
                + "."
            )
        else:
            say(
                "Child-resize pass did not complete; stat groups stay at the JXA "
                "whole-group placement. See the .group-resize.applescript dump."
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
        log=log,
    )
    # Reading the deck back dumps every object, which is what the validation
    # flags are built from. A run whose wall content has already been checked
    # only wants the pictures, and those come from a Keynote pass that does not
    # walk the objects at all.
    if not validate:
        if export_dir:
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
    payload = inspect_keynote(dest, export_dir=export_dir, slide_range=slide_range)
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

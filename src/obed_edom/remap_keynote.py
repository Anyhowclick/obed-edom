from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from obed_edom.inspect import inspect_keynote, preview_pngs
from obed_edom.map_remap import (
    CG_HEIGHT,
    CG_WIDTH,
    learn_recipe,
    plan_payload_transforms,
    plan_slide_reuses,
    score_against_gold,
    summarize_plan,
)

REMAP_JS = Path(__file__).resolve().parent / "remap_keynote.js"


def _run_jxa(plan: dict[str, Any]) -> dict[str, Any]:
    subprocess.run(["open", "-a", "Keynote"], check=False)
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


def remap_keynote(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | None = None,
    include_lists: bool = False,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy wall `source` to `dest`, remap map+pins in place using the CG template crop."""
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
            if slide_range[0] == slide_range[1]:
                say(f"Inspected {source.name} slide {slide_range[0]}: canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}.")
            else:
                say(
                    f"Inspected {source.name} slides {slide_range[0]}–{slide_range[1]}: "
                    f"canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}."
                )
        else:
            say(f"Inspected {source.name}: canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}, {wall.get('slideCount')} slides.")
    if template_payload is not None:
        template_data = template_payload
    else:
        say(f"Inspecting CG template {template_path.name}…")
        template_data = inspect_keynote(template_path)

    recipe = recipe_for(wall, template_data)
    transforms = plan_payload_transforms(
        wall,
        recipe,
        slide_range=slide_range,
        include_lists=include_lists,
        template=template_data,
    )
    reuses = plan_slide_reuses(wall, transforms, slide_range=slide_range)
    counts = summarize_plan(transforms)
    say(
        f"Recipe {recipe.get('source')}: map {recipe.get('mapSrc')} → {recipe.get('mapDst')}; "
        f"{counts.get('map', 0)} map, {counts.get('pin', 0)} pin, {counts.get('list', 0)} list, "
        f"{counts.get('hide', 0)} hidden names"
        f"{'' if include_lists else ' (church names hidden; tick the list checkbox to pack them)'}."
    )
    if include_lists and recipe.get("listFontSize"):
        say(
            f"Church names → {recipe.get('listFontSize')}pt, packed from the right "
            f"(gutter first; extras may overlap the map)."
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
        if slide_range:
            plan["range"] = [slide_range[0], slide_range[1]]
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
        "slideRange": list(slide_range) if slide_range else None,
        "skippedSlides": jxa.get("skippedSlides"),
        "layouts": jxa.get("layouts"),
        "templateScore": score_against_gold(transforms, template_data),
    }
    return result


def remap_and_inspect(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | None = None,
    include_lists: bool = False,
    export_dir: Path | str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    info = remap_keynote(
        source,
        dest,
        template=template,
        slide_range=slide_range,
        include_lists=include_lists,
        log=log,
    )
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

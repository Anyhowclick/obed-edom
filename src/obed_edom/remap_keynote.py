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
    Rect,
    learn_recipe,
    map_rect_from_slide,
    plan_payload_transforms,
    recipe_from_cover,
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


def recipe_for(
    wall: dict[str, Any],
    gold: dict[str, Any] | None,
) -> dict[str, Any]:
    if gold:
        return learn_recipe(wall, gold)
    map_src = None
    for slide in wall.get("slides") or []:
        map_src = map_rect_from_slide(slide)
        if map_src:
            break
    if map_src is None:
        map_src = Rect(
            0,
            0,
            float(wall.get("slideWidth") or 7680),
            float(wall.get("slideHeight") or 1080),
        )
    return recipe_from_cover(map_src)


def remap_keynote(
    source: Path | str,
    dest: Path | str,
    *,
    gold: Path | str | None = None,
    slide_range: tuple[int, int] | None = None,
    wall_payload: dict[str, Any] | None = None,
    gold_payload: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Copy `source` to `dest`, remap map+pins in place, set canvas to 1920×1080."""
    def say(message: str) -> None:
        if log:
            log(message)

    source = Path(source).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    gold_path = Path(gold).expanduser().resolve() if gold else None
    if gold_path and not gold_path.exists():
        raise FileNotFoundError(gold_path)

    wall = wall_payload if wall_payload is not None else inspect_keynote(source, slide_range=slide_range)
    if wall_payload is None:
        say(f"Inspected {source.name}: canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}, {wall.get('slideCount')} slides.")
    gold_data = None
    if gold_payload is not None:
        gold_data = gold_payload
    elif gold_path:
        say(f"Inspecting gold {gold_path.name}…")
        gold_data = inspect_keynote(gold_path, slide_range=slide_range)

    recipe = recipe_for(wall, gold_data)
    transforms = plan_payload_transforms(wall, recipe, slide_range=slide_range)
    counts = summarize_plan(transforms)
    say(
        f"Recipe {recipe.get('source')}: {counts.get('map', 0)} map, "
        f"{counts.get('pin', 0)} pin, {counts.get('list', 0)} list objects."
    )
    say(f"Copying {source.name} → {dest.name}…")
    copy_keynote(source, dest)
    say("Applying positions in Keynote (object identity kept)…")
    jxa = _run_jxa(
        {
            "dest": str(dest),
            "width": int(recipe.get("destWidth") or CG_WIDTH),
            "height": int(recipe.get("destHeight") or CG_HEIGHT),
            "transforms": [t.as_dict() for t in transforms],
        }
    )
    result: dict[str, Any] = {
        "source": str(source),
        "dest": str(dest),
        "recipe": recipe,
        "counts": summarize_plan(transforms),
        "applied": jxa.get("applied"),
        "missed": jxa.get("missed"),
        "width": jxa.get("width"),
        "height": jxa.get("height"),
    }
    if gold_data:
        result["goldScore"] = score_against_gold(transforms, gold_data)
    return result


def remap_and_inspect(
    source: Path | str,
    dest: Path | str,
    *,
    gold: Path | str | None = None,
    slide_range: tuple[int, int] | None = None,
    export_dir: Path | str | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    info = remap_keynote(source, dest, gold=gold, slide_range=slide_range, log=log)
    if log:
        log("Inspecting remapped deck…")
    payload = inspect_keynote(dest, export_dir=export_dir)
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

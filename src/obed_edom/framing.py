"""Remembered framing decisions for the CG resizer.

States: auto (planner picks), pinned (operator template slide), deferred (no
crop yet; re-offered when the template digest changes). ``keep_side_content``
is orthogonal. Auto rows are omitted unless they whitelist side content.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from obed_edom.baseline import index_map, pairing_path

FRAMING_VERSION = 1
FRAMING_KIND = "framing"

AUTO = "auto"
PINNED = "pinned"
DEFERRED = "deferred"
STATES = (AUTO, PINNED, DEFERRED)


@dataclass
class Decision:
    """One page. ``template_slide`` only when pinned. ``keep_side_content`` is orthogonal to state."""

    wall_index: int
    state: str = AUTO
    template_slide: int | None = None
    keep_side_content: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "wallIndex": int(self.wall_index),
            "state": self.state,
            "templateSlide": None if self.template_slide is None else int(self.template_slide),
        }
        if self.keep_side_content:
            out["keepSideContent"] = True
        return out


@dataclass
class FramingReuse:
    """What survived a re-run, and what needs the operator's attention again."""

    decisions: dict[int, Decision] = field(default_factory=dict)
    template_changed: bool = False
    resurfaced: list[int] = field(default_factory=list)
    carried: int = 0
    dropped: int = 0

    def overrides(self) -> dict[int, int]:
        """Pinned wall-number → template-number. Auto/deferred do not pin."""
        return {
            index + 1: decision.template_slide
            for index, decision in sorted(self.decisions.items())
            if decision.state == PINNED and decision.template_slide is not None
        }

    def side_content_slides(self) -> set[int]:
        """Wall numbers whose side-panel content is kept, independent of framing state."""
        return {
            index + 1
            for index, decision in self.decisions.items()
            if decision.keep_side_content
        }


def normalize_decision(raw: dict[str, Any]) -> Decision | None:
    try:
        wall_index = int(raw["wallIndex"])
    except (KeyError, TypeError, ValueError):
        return None
    state = str(raw.get("state") or AUTO)
    if state not in STATES:
        return None
    slide = raw.get("templateSlide")
    try:
        template_slide = None if slide is None else int(slide)
    except (TypeError, ValueError):
        template_slide = None
    keep_side_content = bool(raw.get("keepSideContent"))
    if state == PINNED and template_slide is None:
        return None  # unanswered, not silently pin slide 0
    if state != PINNED:
        template_slide = None
    return Decision(
        wall_index=wall_index,
        state=state,
        template_slide=template_slide,
        keep_side_content=keep_side_content,
    )


def framing_path(wall: Path | str, template: Path | str, root: Path | None = None) -> Path:
    return pairing_path(FRAMING_KIND, wall, template, root)


def load_framings(
    wall: Path | str, template: Path | str, root: Path | None = None
) -> dict | None:
    path = framing_path(wall, template, root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("decisions"):
        return None
    return data


def save_framings(
    wall: Path | str,
    template: Path | str,
    wall_digests: list[str],
    template_digest: str,
    decisions: list[Decision] | list[dict[str, Any]],
    *,
    job_id: str = "",
    root: Path | None = None,
) -> dict:
    """Write the framing record. Drop auto pages unless they whitelist side content."""
    rows: list[dict[str, Any]] = []
    for entry in decisions:
        decision = entry if isinstance(entry, Decision) else normalize_decision(entry)
        if decision is None or (decision.state == AUTO and not decision.keep_side_content):
            continue
        rows.append(decision.as_dict())
    record = {
        "version": FRAMING_VERSION,
        "kind": FRAMING_KIND,
        "wallPath": str(Path(wall).expanduser()),
        "templatePath": str(Path(template).expanduser()),
        "wallDigests": list(wall_digests),
        "templateDigest": str(template_digest),
        "decisions": rows,
        "jobId": job_id,
        "savedAt": time.time(),
    }
    path = framing_path(wall, template, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def reuse_framings(
    record: dict | None,
    wall_digests: list[str],
    template_digest: str,
) -> FramingReuse:
    """Carry saved decisions by wall digest. Content change drops the decision."""
    out = FramingReuse()
    if not record:
        return out
    out.template_changed = str(record.get("templateDigest") or "") != str(template_digest)
    mapping = index_map(list(record.get("wallDigests") or []), list(wall_digests))
    for raw in record.get("decisions") or []:
        decision = normalize_decision(raw)
        if decision is None:
            continue
        new_index = mapping.get(decision.wall_index)
        if new_index is None:
            out.dropped += 1
            continue
        out.decisions[new_index] = Decision(
            wall_index=new_index,
            state=decision.state,
            template_slide=decision.template_slide,
            keep_side_content=decision.keep_side_content,
        )
        out.carried += 1
    if out.template_changed:
        # Deferred pages were waiting for this template change; keep the answer and re-offer.
        out.resurfaced = sorted(
            index for index, d in out.decisions.items() if d.state == DEFERRED
        )
    return out


THUMB_WIDTH = 1920
THUMB_QUALITY = 82


def _transform_of(recipe: dict[str, Any]) -> dict[str, float] | None:
    """Uniform scale+offset. Same precedence as the planner: first group affine, else mapSrc/mapDst."""
    groups = recipe.get("groups") or []
    if groups:
        first = groups[0] or {}
        try:
            s = float(first.get("s") or 0)
            if s > 0:
                return {
                    "s": round(s, 6),
                    "tx": round(float(first.get("tx") or 0), 2),
                    "ty": round(float(first.get("ty") or 0), 2),
                }
        except (TypeError, ValueError):
            pass
    src = recipe.get("mapSrc") or {}
    dst = recipe.get("mapDst") or {}
    try:
        sw = float(src.get("w") or 0)
        sh = float(src.get("h") or 0)
        if sw <= 0 or sh <= 0:
            return None
        s = float(dst.get("w") or 0) / sw
        if s <= 0:
            return None
        return {
            "s": round(s, 6),
            "tx": round(float(dst.get("x") or 0) - float(src.get("x") or 0) * s, 2),
            "ty": round(float(dst.get("y") or 0) - float(src.get("y") or 0) * s, 2),
        }
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def build_preview_thumbs(
    deck: Path | str,
    payload: dict[str, Any],
    *,
    log: Callable[[str], None] | None = None,
) -> dict[int, str]:
    """Downscale cached previews. Returns slide number → thumbnail file name."""
    from PIL import Image  # noqa: PLC0415

    from obed_edom.baseline import deck_digest, preview_cache_dir, wall_thumb_dir  # noqa: PLC0415
    from obed_edom.diff_keynotes import map_preview_pngs  # noqa: PLC0415
    from obed_edom.inspect import (  # noqa: PLC0415
        export_slide_images,
        preview_media,
        preview_pngs,
    )

    deck = Path(deck)
    digest = deck_digest(deck)
    source = preview_cache_dir(digest)
    dest = wall_thumb_dir(digest)
    slides = payload.get("slides") or []
    # Templates are often inspected without export_dir; export now so the list isn't bare numbers.
    if not preview_pngs(source):
        if log:
            log(f"Exporting previews for {deck.name}\u2026")
        error = export_slide_images(deck, source)
        if error:
            if log:
                log(f"No previews for {deck.name}: {error}")
            return {}
    images = [p for p in preview_media(source) if p.suffix.lower() != ".mov"]
    mapped = map_preview_pngs(slides, images)
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[int, str] = {}
    made = 0
    for index, png in mapped.items():
        if index >= len(slides):
            continue
        number = int(slides[index].get("number") or index + 1)
        name = f"{number:04d}.jpg"
        target = dest / name
        out[number] = name
        if target.is_file():
            continue
        try:
            with Image.open(png) as im:
                im = im.convert("RGB")
                if im.width > THUMB_WIDTH:
                    height = max(1, round(im.height * THUMB_WIDTH / im.width))
                    im = im.resize((THUMB_WIDTH, height), Image.LANCZOS)
                im.save(target, "JPEG", quality=THUMB_QUALITY)
            made += 1
        except (OSError, ValueError):
            out.pop(number, None)
    if made and log:
        log(f"Made {made} thumbnail(s) from {deck.name} previews.")
    return out


def planned_rects(
    slide: dict[str, Any],
    recipe: dict[str, Any],
    *,
    wall_size: tuple[float, float],
    include_lists: bool = False,
    side_content_slides: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Planned dest rects for this recipe. Do not pass a template (that re-learns the automatic pick)."""
    from obed_edom.map_remap import plan_payload_transforms  # noqa: PLC0415

    wall_w, wall_h = wall_size
    payload = {"slideWidth": wall_w, "slideHeight": wall_h, "slides": [slide]}
    out: list[dict[str, Any]] = []
    for spec in plan_payload_transforms(
        payload,
        recipe,
        include_lists=include_lists,
        side_content_slides=side_content_slides,
    ):
        dropped = spec.role == "hide" or (spec.opacity is not None and spec.opacity <= 0.0)
        rect = {
            "role": spec.role,
            "kind": spec.kind,
            "x": round(spec.x),
            "y": round(spec.y),
            "w": round(spec.w),
            "h": round(spec.h),
            "willBeInOutput": not dropped,
        }
        if spec.match_text:
            rect["text"] = spec.match_text[:40]
        if spec.src is not None and spec.src.w > 0 and spec.src.h > 0:
            rect["sx"] = round(spec.src.x)
            rect["sy"] = round(spec.src.y)
            rect["sw"] = round(spec.src.w)
            rect["sh"] = round(spec.src.h)
        out.append(rect)
    return out


def propose_framings(
    wall: Path | str,
    template: Path | str,
    *,
    slide_range: Any = None,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    include_lists: bool = False,
    side_content_slides: set[int] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Propose framings over cached inspect payloads. Nothing is copied or written."""
    from obed_edom.baseline import deck_digest, deck_slide_digests  # noqa: PLC0415
    from obed_edom.inspect import inspect_keynote  # noqa: PLC0415
    from obed_edom.map_remap import (  # noqa: PLC0415
        CG_HEIGHT,
        CG_WIDTH,
        MIN_ON_CANVAS_FRACTION,
        fit_to_frame_recipe,
        is_degenerate_scale,
        learn_recipe,
        navigator_numbering,
        on_canvas_fraction,
        plan_payload_transforms,
        rank_framing_candidates,
        skipped_positions,
    )

    def say(message: str) -> None:
        if log:
            log(message)

    wall_path = Path(wall).expanduser().resolve()
    template_path = Path(template).expanduser().resolve()
    wall_data = wall_payload if wall_payload is not None else inspect_keynote(wall_path)
    template_data = (
        template_payload if template_payload is not None else inspect_keynote(template_path)
    )

    wall_w = float(wall_data.get("slideWidth") or 7680)
    wall_h = float(wall_data.get("slideHeight") or 1080)
    dest = (
        float(template_data.get("slideWidth") or 1920),
        float(template_data.get("slideHeight") or 1080),
    )
    template_slides = template_data.get("slides") or []

    report: list[dict[str, Any]] = []
    recipe = learn_recipe(wall_data, template_data)
    plan_payload_transforms(
        wall_data,
        recipe,
        slide_range=slide_range,
        template=template_data,
        framing_report=report,
    )
    thumbs = build_preview_thumbs(wall_path, wall_data, log=log)
    template_thumbs = build_preview_thumbs(template_path, template_data, log=log)

    by_number = {
        int(s.get("number") or (int(s.get("index") or 0) + 1)): s
        for s in wall_data.get("slides") or []
    }
    pages: list[dict[str, Any]] = []
    for row in report:
        number = int(row["slide"])
        slide = by_number.get(number)
        if slide is None:
            continue
        auto_fell_back = bool(row.get("fitted"))
        candidates = rank_framing_candidates(
            slide, template_slides, wall_size=(wall_w, wall_h), dest_size=dest
        )
        for candidate in candidates:
            trial = learn_recipe(
                {"slideWidth": wall_w, "slideHeight": wall_h, "slides": [slide]},
                template_data,
                template_slide=candidate["templateSlide"],
            )
            falls_back = (
                on_canvas_fraction(slide, trial, wall_w, wall_h) < MIN_ON_CANVAS_FRACTION
                or is_degenerate_scale(trial, wall_w, wall_h)
            )
            candidate["wouldFallBack"] = falls_back
            # Fallback is planned as fit-to-frame; showing the template crop would lie.
            shown = trial
            if falls_back:
                fitted = fit_to_frame_recipe(
                    slide,
                    wall_w,
                    wall_h,
                    float(trial.get("destWidth") or CG_WIDTH),
                    float(trial.get("destHeight") or CG_HEIGHT),
                )
                if fitted:
                    shown = fitted
            candidate["transform"] = _transform_of(shown)
            candidate["rects"] = planned_rects(
                slide,
                shown,
                wall_size=(wall_w, wall_h),
                include_lists=include_lists,
                side_content_slides=side_content_slides,
            )
        usable = [c for c in candidates if not c.get("wouldFallBack", False)]
        auto_slide = row.get("templateSlide")
        auto_candidate = next(
            (c for c in candidates if c["templateSlide"] == auto_slide), None
        )
        pages.append(
            {
                "slide": number,
                "index": number - 1,
                "thumb": thumbs.get(number),
                "autoTransform": (auto_candidate or {}).get("transform"),
                "autoRects": (auto_candidate or {}).get("rects") or [],
                "autoTemplateSlide": auto_slide,
                "autoFellBack": auto_fell_back,
                "needsAttention": auto_fell_back,
                "noUsableFraming": auto_fell_back and not usable,
                "candidates": candidates,
            }
        )

    attention = [p["slide"] for p in pages if p["needsAttention"]]
    stuck = [p["slide"] for p in pages if p["noUsableFraming"]]
    say(
        f"{len(pages)} page(s) take a framing; {len(pages) - len(attention)} matched a template "
        f"framing, {len(attention)} need a look, {len(stuck)} have none that fits."
    )
    if stuck:
        say(
            "Add a template slide for "
            + ", ".join(str(n) for n in stuck[:10])
            + ("…" if len(stuck) > 10 else "")
            + " — no existing framing can be used for those."
        )
    from obed_edom.baseline import wall_thumb_dir  # noqa: PLC0415

    return {
        "wallPath": str(wall_path),
        "templatePath": str(template_path),
        "wallDigests": deck_slide_digests(wall_data),
        "templateDigest": deck_digest(template_path),
        "wallThumbDir": str(wall_thumb_dir(deck_digest(wall_path))),
        "templateThumbDir": str(wall_thumb_dir(deck_digest(template_path))),
        "templateThumbs": {str(k): v for k, v in sorted(template_thumbs.items())},
        "destWidth": int(dest[0]),
        "destHeight": int(dest[1]),
        "wallWidth": int(wall_w),
        "wallHeight": int(wall_h),
        "pages": pages,
        "needAttention": attention,
        "noUsableFraming": stuck,
        # Document position ≠ navigator number when any slide is skipped.
        "skippedSlides": skipped_positions(wall_data),
        "numberingNote": navigator_numbering(wall_data),
    }

"""Remembered framing decisions for the CG resizer.

States: auto (planner picks), pinned (operator template slide), deferred (no
crop yet; re-offered when the template digest changes). ``keep_side_content``
is orthogonal. Auto rows are omitted unless they whitelist side content.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from obed_edom.baseline import DIGEST_LEN, index_map, pairing_path
from obed_edom.map_remap import DEFAULT_CARD_STROKE, frame_affine, item_rect
from obed_edom.text_diff import fingerprint

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
    unpinned: int = 0

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


def _item_token(item: dict[str, Any]) -> tuple[str, float, float, float, float, str, str]:
    """One top-level item's identity: kind, half-pixel-rounded frame, its own
    (unfolded, not recursive) text and media filename. A sortable, None-safe key."""
    rect = item_rect(item)
    return (
        str(item.get("kind") or ""),
        round(rect.x * 2) / 2,
        round(rect.y * 2) / 2,
        round(rect.w * 2) / 2,
        round(rect.h * 2) / 2,
        fingerprint(str(item.get("text") or "")),
        str(item.get("fileName") or ""),
    )


def template_framing_digests(payload: dict[str, Any]) -> list[str]:
    """Per-slide fingerprint for template slides: each top-level item's kind, frame,
    own text and own media filename, hashed together with the slide's ``skipped``
    flag -- the geometry IS the framing on the template side, unlike ``slide_digest``.
    Content and position are tokenized per item, not as separate multisets, so two
    items swapping positions changes the digest (a materially different framing, since
    recipe learning pairs images before deriving a transform). Tokens are sorted
    (deterministic, not payload order) because Keynote can reorder items within a kind
    on save with no other change (see ``iwa_zorder.py``). Recursion into group
    children is skipped -- template group-child inspection is best-effort and can drop
    to an empty list between runs with nothing in the group itself having changed; a
    group's own frame already reflects its children. The 0.5px rounding means jitter
    right at a bucket edge can refuse a match on an untouched slide; that is the safe
    direction (a re-offered pin, never a mis-pinned one)."""
    out: list[str] = []
    for slide in payload.get("slides") or []:
        skipped = "1" if slide.get("skipped") else "0"
        tokens = sorted(_item_token(item) for item in slide.get("items") or [])
        items = "|".join(f"{k}:{x}:{y}:{w}:{h}:{t}:{i}" for k, x, y, w, h, t, i in tokens)
        blob = f"{skipped}|{items}"
        out.append(hashlib.sha256(blob.encode("utf-8")).hexdigest()[:DIGEST_LEN])
    return out


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
    template_digests: list[str] | None = None,
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
        "templateDigests": list(template_digests) if template_digests is not None else [],
        "decisions": rows,
        "jobId": job_id,
        "savedAt": time.time(),
    }
    path = framing_path(wall, template, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _matched_template_slide(
    saved_digests: list[str], current_digests: list[str], template_slide: int
) -> int | None:
    """1-based old slide -> 1-based new slide, by digest identity only (never by position):
    the saved slide's digest must be unique in both lists, or the match is refused."""
    old_index = template_slide - 1
    if old_index < 0 or old_index >= len(saved_digests):
        return None
    digest = saved_digests[old_index]
    if saved_digests.count(digest) != 1 or current_digests.count(digest) != 1:
        return None
    return current_digests.index(digest) + 1


def reuse_framings(
    record: dict | None,
    wall_digests: list[str],
    template_digest: str,
    template_digests: list[str] | None = None,
) -> FramingReuse:
    """Carry saved decisions by wall digest. Content change drops the decision.

    When the template changed, a pinned ``template_slide`` is matched by the
    template's own per-slide framing digest, by identity only -- an ambiguous
    (repeated) digest, a missing one, or a legacy record with no
    ``templateDigests`` all refuse the match. A refused pin that also keeps
    side content survives unpinned so that answer is not lost; otherwise it
    is dropped and the page is re-offered.
    """
    out = FramingReuse()
    if not record:
        return out
    out.template_changed = str(record.get("templateDigest") or "") != str(template_digest)
    mapping = index_map(list(record.get("wallDigests") or []), list(wall_digests))
    saved_template_digests = list(record.get("templateDigests") or [])
    current_template_digests = list(template_digests or [])
    for raw in record.get("decisions") or []:
        decision = normalize_decision(raw)
        if decision is None:
            continue
        new_index = mapping.get(decision.wall_index)
        if new_index is None:
            out.dropped += 1
            continue
        template_slide = decision.template_slide
        state = decision.state
        if out.template_changed and template_slide is not None:
            new_template_slide = (
                _matched_template_slide(
                    saved_template_digests, current_template_digests, template_slide
                )
                if saved_template_digests
                else None
            )
            if new_template_slide is None:
                if not decision.keep_side_content:
                    out.dropped += 1
                    continue
                template_slide, state = None, AUTO
                out.unpinned += 1
                out.decisions[new_index] = Decision(
                    wall_index=new_index,
                    state=state,
                    template_slide=template_slide,
                    keep_side_content=decision.keep_side_content,
                )
                continue
            template_slide = new_template_slide
        out.decisions[new_index] = Decision(
            wall_index=new_index,
            state=state,
            template_slide=template_slide,
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
    """Uniform scale+offset shown in the propose overlay. Precedence is the planner's own
    (`map_remap.frame_affine`): mapSrc/mapDst first, else groups[0] -- not the reverse."""
    aff = frame_affine(recipe)
    if aff is None:
        return None
    return {"s": round(aff.s, 6), "tx": round(aff.tx, 2), "ty": round(aff.ty, 2)}


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
    keep_side_panels: bool = False,
    side_content_slides: set[int] | None = None,
    card_stroke: float = DEFAULT_CARD_STROKE,
) -> list[dict[str, Any]]:
    """Planned dest rects for this recipe. Do not pass a template (that re-learns the automatic pick)."""
    from obed_edom.map_remap import plan_payload  # noqa: PLC0415

    wall_w, wall_h = wall_size
    payload = {"slideWidth": wall_w, "slideHeight": wall_h, "slides": [slide]}
    out: list[dict[str, Any]] = []
    for spec in plan_payload(
        payload,
        recipe,
        keep_side_panels=keep_side_panels,
        side_content_slides=side_content_slides,
        card_stroke=card_stroke,
    ).transforms:
        dropped = spec.role == "hide" or (spec.opacity is not None and spec.opacity <= 0.0)
        # Round the same 2-decimal values apply serializes (as_dict), not the raw floats,
        # so parity holds under banker's rounding at .5 boundaries. as_dict writes a
        # "line" role's h as 0 (Keynote ignores it, geometry comes from start/end) and
        # omits w/h entirely for a refused group -- fall back to the raw transform for
        # both (the refused size falls back to the source size).
        applied = spec.as_dict()
        has_wh = spec.role != "line" and "w" in applied
        rect = {
            "role": spec.role,
            "kind": spec.kind,
            "x": round(applied["x"]),
            "y": round(applied["y"]),
            "w": round(applied["w"]) if has_wh else round(spec.src.w if spec.size_refused and spec.src else spec.w),
            "h": round(applied["h"]) if has_wh else round(spec.src.h if spec.size_refused and spec.src else spec.h),
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
    full_wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    keep_side_panels: bool = False,
    side_content_slides: set[int] | None = None,
    card_stroke: float = DEFAULT_CARD_STROKE,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Propose framings over cached inspect payloads. Nothing is copied or written."""
    from obed_edom.baseline import deck_digest, deck_slide_digests  # noqa: PLC0415
    from obed_edom.inspect import inspect_keynote  # noqa: PLC0415
    from obed_edom.map_remap import (  # noqa: PLC0415
        frame_slide,
        learn_recipe,
        navigator_numbering,
        plan_payload,
        rank_framing_candidates,
        skipped_positions,
    )

    def say(message: str) -> None:
        if log:
            log(message)

    from obed_edom.remap_keynote import prepare_wall_payload  # noqa: PLC0415

    wall_path = Path(wall).expanduser().resolve()
    template_path = Path(template).expanduser().resolve()
    wall_data = wall_payload if wall_payload is not None else inspect_keynote(wall_path)
    full_wall_data = full_wall_payload if full_wall_payload is not None else wall_data
    template_data = (
        template_payload if template_payload is not None else inspect_keynote(template_path)
    )
    card_stroke = prepare_wall_payload(wall_path, wall_data, template_path, template_data, say)

    wall_w = float(wall_data.get("slideWidth") or 7680)
    wall_h = float(wall_data.get("slideHeight") or 1080)
    dest = (
        float(template_data.get("slideWidth") or 1920),
        float(template_data.get("slideHeight") or 1080),
    )
    template_slides = template_data.get("slides") or []

    recipe = learn_recipe(wall_data, template_data)
    plan = plan_payload(
        wall_data,
        recipe,
        slide_range=slide_range,
        template=template_data,
        card_stroke=card_stroke,
    )
    thumbs = build_preview_thumbs(wall_path, full_wall_data, log=log)
    template_thumbs = build_preview_thumbs(template_path, template_data, log=log)

    by_number = {
        int(s.get("number") or (int(s.get("index") or 0) + 1)): s
        for s in wall_data.get("slides") or []
    }

    def rects_of(slide: dict[str, Any], shown: dict[str, Any]) -> list[dict[str, Any]]:
        return planned_rects(
            slide,
            shown,
            wall_size=(wall_w, wall_h),
            keep_side_panels=keep_side_panels,
            side_content_slides=side_content_slides,
            card_stroke=card_stroke,
        )

    pages: list[dict[str, Any]] = []
    for row in plan.framing:
        number = int(row["slide"])
        slide = by_number.get(number)
        if slide is None:
            continue
        auto_fell_back = bool(row.get("fitted"))
        prev = plan.framing_context[number]
        candidates = rank_framing_candidates(
            slide, template_slides, wall_size=(wall_w, wall_h), dest_size=dest
        )
        for candidate in candidates:
            shown, pinned_row = frame_slide(
                slide, wall_data, template_data, wanted=candidate["templateSlide"], prev=prev
            )
            candidate["wouldFallBack"] = bool(pinned_row["fitted"])
            candidate["pinOverridden"] = bool(pinned_row["pinOverridden"])
            candidate["transform"] = _transform_of(shown)
            candidate["rects"] = rects_of(slide, shown)
        usable = [c for c in candidates if not c.get("wouldFallBack", False)]
        auto_slide = row.get("templateSlide")
        auto_recipe = plan.framing_recipes[number]
        pages.append(
            {
                "slide": number,
                "index": number - 1,
                "thumb": thumbs.get(number),
                "autoTransform": _transform_of(auto_recipe),
                "autoRects": rects_of(slide, auto_recipe),
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
        "wallDigests": deck_slide_digests(full_wall_data),
        "templateDigest": deck_digest(template_path),
        "templateDigests": template_framing_digests(template_data),
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
        "skippedSlides": skipped_positions(full_wall_data),
        "numberingNote": navigator_numbering(full_wall_data),
    }

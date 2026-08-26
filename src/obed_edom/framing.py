"""Remembered framing decisions for the CG resizer.

Which crop of a map the operator wants is an editorial choice, so it has to be
asked and then not asked again. This is the Sermon Checker's pattern — propose,
let the operator correct, remember by content digest, carry across runs — reusing
its primitives (`pairing_key` for the file key, `index_map` for remapping onto an
edited deck, `deck_slide_digests` for identity).

The record shape differs from a pairing on purpose. A pairing answers "which
slides go together"; a framing answers one of three things per page, and only one
of them names a template slide:

``auto``
    No operator input. Use whatever the planner picks.
``pinned``
    The operator chose this template slide's framing.
``deferred``
    "No framing here is right; I will add a template slide and re-run." The page
    plans automatically meanwhile, which in practice means fit-to-frame — the
    honest outcome, since a deferred page is one where no crop applies yet.

Squeezing three states into `leftIndex`/`rightIndexes` would make `deferred`
indistinguishable from an unpaired row, so the states are explicit instead.

A deferred page is re-offered when the *template* changes, because that is
exactly when new framings may have appeared. That is why the template's deck
digest is stored alongside the per-slide wall digests.
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
    """One page's answer. `template_slide` is set only when `state` is `pinned`.

    `keep_side_content` is orthogonal to `state`: side-panel content is dropped by
    default and kept only on the pages the operator whitelists, whatever framing
    they end up with. So a page can be `auto` and still carry `keep_side_content`.
    """

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
        # Emitted only when set, so a plain answer stays lean — the same reason an
        # auto row is dropped from the record entirely.
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
        """Wall slide *number* to template slide number, for the planner.

        Only pinned decisions become overrides. Auto and deferred both mean
        "let the planner choose", so neither pins anything.
        """
        return {
            index + 1: decision.template_slide
            for index, decision in sorted(self.decisions.items())
            if decision.state == PINNED and decision.template_slide is not None
        }

    def side_content_slides(self) -> set[int]:
        """Wall slide *numbers* whose side-panel content is kept, for the planner.

        Independent of framing state — whitelisting a page keeps its side content
        whether its crop is pinned, deferred or automatic.
        """
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
        # A pin with nothing pinned is not a decision; treat it as unanswered
        # rather than silently pinning slide 0.
        return None
    if state != PINNED:
        template_slide = None
    # keep_side_content is kept for every state — a whitelisted page left on auto
    # is still a decision, unlike template_slide which only pinned pages carry.
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
    """Write the framing record, dropping pages left on auto.

    Auto is the absence of a decision, so storing it would grow the file with
    rows that mean nothing and would make "already answered" untrue. A page kept on
    auto but whitelisted for side content is a real decision, though, so it stays.
    """
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
    """Carry saved decisions onto the current deck.

    Pages are matched by content digest, so inserting or reordering wall slides
    keeps their answers. A page whose content changed loses its decision, because
    the crop was chosen for the old content.
    """
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
        # The one case worth re-asking: a deferred page was waiting for exactly
        # this. Its answer is kept so nothing is lost if the new template still
        # has no framing for it.
        out.resurfaced = sorted(
            index for index, d in out.decisions.items() if d.state == DEFERRED
        )
    return out


THUMB_WIDTH = 1920
THUMB_QUALITY = 82


def _transform_of(recipe: dict[str, Any]) -> dict[str, float] | None:
    """The uniform scale and offset that puts wall coordinates into the CG frame.

    `(x, y) -> (s*x + tx, s*y + ty)`, which is what the browser needs to place a
    wall image inside a 16:9 box: width becomes `wallWidth * s`, offset `tx, ty`.

    Must follow the same precedence as `_groups_from_recipe`, which is what the
    planner actually places objects with: the first group affine when there is
    one, and only mapSrc/mapDst when there is not. Deriving it from mapSrc/mapDst
    unconditionally made the preview lie — on a real page the group affine was
    s=0.871 while mapSrc/mapDst implied 1.412, so the operator was shown a crop
    62% larger than the deck would get.
    """
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
    """Downscale a deck's cached previews once, so the browser can show artwork.

    Returns slide number to thumbnail file name. Used for both sides: wall slides,
    whose previews are 7680x1080 and 9 MB each, and the template slides, so a
    group header can show what "template slide 4" actually looks like instead of
    asking the operator to hold it in their head.
    """
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
    # A template is usually inspected without an export_dir, so it reaches here
    # with no previews and the operator gets a framing list of bare slide numbers.
    # Export them now: it is the same Keynote pass the wall already paid for, and
    # the cache means it happens once per template revision.
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
) -> list[dict[str, Any]]:
    """Where every object on this page ends up, for drawing over the crop.

    The crop alone only ever shows one affine, so it cannot show what the run
    actually does to the badge, the lists, or the 200-odd objects it hides. The
    planner already works this out in about 10ms a page and it costs no Keynote
    pass, so the operator may as well see it before committing.

    Compact on purpose: a page can plan 1500 objects and every candidate framing
    carries its own set.

    The template is deliberately not handed on. `plan_payload_transforms` re-learns
    a recipe per slide when given one, from whichever framing it would pick
    automatically — which threw away the recipe passed here and drew every
    candidate, and every saved recipe, as the automatic choice. The caller has
    already settled which recipe it wants shown.
    """
    from obed_edom.map_remap import plan_payload_transforms  # noqa: PLC0415

    wall_w, wall_h = wall_size
    payload = {"slideWidth": wall_w, "slideHeight": wall_h, "slides": [slide]}
    out: list[dict[str, Any]] = []
    for spec in plan_payload_transforms(payload, recipe):
        rect = {
            "role": spec.role,
            "kind": spec.kind,
            "x": round(spec.x),
            "y": round(spec.y),
            "w": round(spec.w),
            "h": round(spec.h),
        }
        if spec.match_text:
            rect["text"] = spec.match_text[:40]
        # The part of the wall this object occupies, so a preview can cut it out
        # and draw it where it lands instead of only outlining the destination.
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
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """What the operator is asked, without touching the deck.

    Planning is pure Python over cached inspect payloads, so this costs no Keynote
    pass beyond the inspect that a resize needed anyway. Nothing is copied and
    nothing is written.

    Candidate fallback is evaluated only for pages whose automatic pick already
    falls back. Doing it for every candidate on every page means a `learn_recipe`
    per pair — about 7s on a 158-slide deck against 13 candidates — and it only
    tells the operator something on the pages they are being asked about.
    """
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

    # A dry plan is what knows which pages take a framing decision at all, and
    # which of them the automatic choice cannot serve.
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
        # Every candidate needs its transform, because the row renders the crop in
        # the browser and the dropdown has to re-render instantly. Learning the
        # recipe per candidate also settles whether it would fall back, so both
        # answers come from the same pass.
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
            # Preview what the deck will get, not what was asked for. A framing
            # that falls back is planned with fit-to-frame instead, so showing the
            # template's crop would promise a result the run cannot produce.
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
            # The crop shows one affine; these show what the run does to every
            # object on the page, which is where it actually goes wrong.
            candidate["rects"] = planned_rects(slide, shown, wall_size=(wall_w, wall_h))
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
                # What the automatic choice does to this page, so a row can render
                # before the operator touches anything.
                "autoTransform": (auto_candidate or {}).get("transform"),
                "autoRects": (auto_candidate or {}).get("rects") or [],
                "autoTemplateSlide": auto_slide,
                "autoFellBack": auto_fell_back,
                "needsAttention": auto_fell_back,
                # No framing here is worth picking, so the honest default is
                # "add a template slide and re-run" rather than a dropdown of
                # options that all degrade to the same fit-to-frame.
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
        # Kept so serving a thumbnail does not re-hash the deck. Digesting a
        # 6.8 GB deck took 6.8s per request, which made 150 rows unusable.
        "wallThumbDir": str(wall_thumb_dir(deck_digest(wall_path))),
        "templateThumbDir": str(wall_thumb_dir(deck_digest(template_path))),
        # Template slide number to thumbnail, so a group can show the framing
        # itself rather than only naming it.
        "templateThumbs": {str(k): v for k, v in sorted(template_thumbs.items())},
        "destWidth": int(dest[0]),
        "destHeight": int(dest[1]),
        "wallWidth": int(wall_w),
        "wallHeight": int(wall_h),
        "pages": pages,
        "needAttention": attention,
        "noUsableFraming": stuck,
        # Ranges are written in document positions and Keynote's navigator numbers
        # only the slides that will play, so a deck with anything set to Skip
        # reads differently in the two places. Surfaced here because this is the
        # last screen before anything is remapped.
        "skippedSlides": skipped_positions(wall_data),
        "numberingNote": navigator_numbering(wall_data),
    }

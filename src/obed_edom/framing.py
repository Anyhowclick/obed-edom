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
    """One page's answer. `template_slide` is set only when `state` is `pinned`."""

    wall_index: int
    state: str = AUTO
    template_slide: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "wallIndex": int(self.wall_index),
            "state": self.state,
            "templateSlide": None if self.template_slide is None else int(self.template_slide),
        }


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
    if state == PINNED and template_slide is None:
        # A pin with nothing pinned is not a decision; treat it as unanswered
        # rather than silently pinning slide 0.
        return None
    if state != PINNED:
        template_slide = None
    return Decision(wall_index=wall_index, state=state, template_slide=template_slide)


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
    rows that mean nothing and would make "already answered" untrue.
    """
    rows: list[dict[str, Any]] = []
    for entry in decisions:
        decision = entry if isinstance(entry, Decision) else normalize_decision(entry)
        if decision is None or decision.state == AUTO:
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
        MIN_ON_CANVAS_FRACTION,
        is_degenerate_scale,
        learn_recipe,
        on_canvas_fraction,
        plan_payload_transforms,
        rank_framing_candidates,
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
        if auto_fell_back:
            for candidate in candidates:
                trial = learn_recipe(
                    {"slideWidth": wall_w, "slideHeight": wall_h, "slides": [slide]},
                    template_data,
                    template_slide=candidate["templateSlide"],
                )
                candidate["wouldFallBack"] = (
                    on_canvas_fraction(slide, trial, wall_w, wall_h) < MIN_ON_CANVAS_FRACTION
                    or is_degenerate_scale(trial, wall_w, wall_h)
                )
        usable = [c for c in candidates if not c.get("wouldFallBack", False)]
        pages.append(
            {
                "slide": number,
                "index": number - 1,
                "autoTemplateSlide": row.get("templateSlide"),
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
    return {
        "wallPath": str(wall_path),
        "templatePath": str(template_path),
        "wallDigests": deck_slide_digests(wall_data),
        "templateDigest": deck_digest(template_path),
        "destWidth": int(dest[0]),
        "destHeight": int(dest[1]),
        "wallWidth": int(wall_w),
        "wallHeight": int(wall_h),
        "pages": pages,
        "needAttention": attention,
        "noUsableFraming": stuck,
    }

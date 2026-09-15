"""Pure z-order raise primitives (``w-zorder-patch`` piece 1). No zip writes.

Reproduces the GUI raise contract (``keynote.py`` ``obedRaiseSlide``/``obedBadgeSlide``)
offline: stat groups raised ascending by their pre-raise z position, then badge rows raised
in planner row order, both blocks landing at the END of ``drawablesZOrder`` (= front).
"""
from __future__ import annotations

from collections import Counter

from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_write import bridge_kind_index


def raise_to_front(order: list[str], targets: list[str]) -> list[str]:
    """Remove `targets` from `order` and append them, in `targets` order, at the front
    (= END of drawablesZOrder). Pure. Ids not in `order` raise ValueError; a duplicate id
    in `targets` (e.g. stat/badge block overlap) raises ValueError naming it."""
    missing = [t for t in targets if t not in order]
    if missing:
        raise ValueError(f"unknown id(s) not in order: {missing}")
    dupes = sorted({t for t, count in Counter(targets).items() if count > 1})
    if dupes:
        raise ValueError(f"duplicate id(s) in targets: {dupes}")
    target_set = set(targets)
    remainder = [i for i in order if i not in target_set]
    return remainder + list(targets)


def resolve_raise_targets(
    slide: dict, objects: dict[str, dict],
    stat_jobs: list[dict],
    badge_rows: list[dict],
    hide_specs: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    """-> (stat_ids ascending by z-position, badge_ids in row order, unresolved tokens).

    A stat job with a falsy `childSig` is skipped (neither a target nor unresolved),
    matching the live raise path's filter at keynote.py:1411."""
    z = [str(ref["identifier"]) for ref in slide.get("drawablesZOrder") or []]
    records = derive_kind_index(slide, objects)
    by_key = {(r["kind"], r["kindIndex"]): r["id"] for r in records}

    unresolved: list[str] = []
    ambiguous_sigs = {
        sig for sig, count in Counter(
            j.get("childSig") for j in stat_jobs if j.get("childSig")
        ).items() if count > 1
    }

    stat_ids: list[str] = []
    for job in stat_jobs:
        sig = job.get("childSig")
        if not sig:
            # Matches keynote.py's `font_jobs = [j for j in jobs if j.get("childSig")]`
            # (keynote.py:1411) — a falsy childSig means no obedStatJob call is emitted,
            # so the row is neither a target nor unresolved.
            continue
        if sig in ambiguous_sigs:
            unresolved.append(f"stat:s={job.get('slide')},sig={sig}(ambiguous)")
            continue
        wall_gi = int(job["groupIndex"])
        ki = wall_gi - 1
        drawable_id = by_key.get(("group", ki))
        if drawable_id is None:
            unresolved.append(f"stat:s={job.get('slide')},gi={wall_gi}")
            continue
        stat_ids.append(drawable_id)
    stat_ids = sorted(stat_ids, key=z.index)

    badge_ids: list[str] = []
    for row in badge_rows:
        kind = str(row.get("kind"))
        wall_index = int(row["index"])
        ki = bridge_kind_index(kind, wall_index - 1, hide_specs)
        drawable_id = by_key.get((kind, ki))
        if drawable_id is None:
            unresolved.append(f"badge:k={kind},i={wall_index}")
            continue
        badge_ids.append(drawable_id)

    return stat_ids, badge_ids, unresolved


def plan_slide_order(
    slide: dict, objects: dict[str, dict], stat_ids: list[str], badge_ids: list[str]
) -> list[str]:
    """The Contract formula. Sorts `stat_ids` ascending by current z-position itself (does
    not trust caller order); `badge_ids` stays in the given row order. Stat block then
    badge block, both at the front. Raises ValueError on an unknown or duplicate id,
    including overlap between the two blocks."""
    del objects
    z = [str(ref["identifier"]) for ref in slide.get("drawablesZOrder") or []]
    sorted_stat_ids = sorted(stat_ids, key=z.index)
    return raise_to_front(z, sorted_stat_ids + list(badge_ids))

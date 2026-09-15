"""Pure z-order raise primitives (``w-zorder-patch`` piece 1). No zip writes.

Reproduces the GUI raise contract (``keynote.py`` ``obedRaiseSlide``/``obedBadgeSlide``)
offline: stat groups raised ascending by their pre-raise z position, then badge rows raised
in planner row order, both blocks landing at the END of ``drawablesZOrder`` (= front).
"""
from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path

from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _group_child_signature, _load_deck, slide_order
from obed_edom.iwa_write import (
    OfflineWriteCorrupted,
    PatchResult,
    _patch_zorder_member,
    _rewrite_members,
    bridge_kind_index,
    read_slide_zorder,
)


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
    matching the live raise path's filter at keynote.py:1411. A resolved job is also
    verified: the saved-deck group's own child signature (computed offline via
    `_group_child_signature`, the same normalisation the planner used to mint
    `childSig`) must equal the job's `childSig` — a hint pointing at the wrong group
    (stale `groupIndex`) is caught here rather than silently raising the wrong object."""
    z = [str(ref["identifier"]) for ref in slide.get("drawablesZOrder") or []]
    records = derive_kind_index(slide, objects)
    by_key = {(r["kind"], r["kindIndex"]): r["id"] for r in records}
    sig_cache: dict = {}

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
        actual_sig = _group_child_signature(drawable_id, objects, sig_cache)
        if actual_sig != sig:
            unresolved.append(f"stat:s={job.get('slide')},gi={wall_gi},sig={sig}(mismatch)")
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


def _zorder_slide_edit(
    slide_number: int, new_order: list[str], objects: dict[str, dict],
    id_to_file: dict[str, str], order: list[tuple[str, bool]],
) -> tuple[str | None, str | None, str | None]:
    """Pure, no-I/O resolution of one slide's z-order edit. Returns (target_member,
    slide_id, refuse_reason); ``refuse_reason`` set => the other two describe what
    was rejected (``target_member`` may still be usable for the caller's diagnostics)."""
    if not (1 <= slide_number <= len(order)):
        return None, None, f"slide {slide_number} out of range (deck has {len(order)} slides)"
    slide_id = order[slide_number - 1][0]
    slide = objects.get(slide_id)
    if not slide:
        return None, None, f"slide archive {slide_id} not decoded"

    target_member = id_to_file.get(slide_id)
    current = [str(r["identifier"]) for r in slide.get("drawablesZOrder") or []]
    unresolved = [i for i in current if i not in id_to_file]
    drawable_members = {id_to_file[i] for i in current if i in id_to_file}
    if target_member is None or unresolved or drawable_members != {target_member}:
        return target_member, slide_id, (
            f"slide member {target_member!r} does not contain its drawables' order "
            f"(members {sorted(drawable_members)}, unresolved {unresolved})"
        )

    owned = [str(r["identifier"]) for r in slide.get("ownedDrawables") or []]
    if Counter(owned) != Counter(current):
        return target_member, slide_id, "ownedDrawables is not a permutation of drawablesZOrder"

    if Counter(new_order) != Counter(current):
        return target_member, slide_id, "requested order id set/length mismatch with drawablesZOrder"

    return target_member, slide_id, None


def validate_slide_order(
    slide_number: int, new_order: list[str], objects: dict[str, dict],
    id_to_file: dict[str, str], order: list[tuple[str, bool]],
) -> tuple[str | None, str | None]:
    """Dry-run, no-I/O, of everything `patch_deck_zorder` would refuse a slide on:
    member resolution, `ownedDrawables` permutation, and the requested order's id-set
    permutation against the slide's current `drawablesZOrder`. Returns
    `(target_member, refuse_reason)` -- `refuse_reason` is None iff the slide would be
    patched cleanly in isolation. Cross-slide member collision is NOT checked here (it
    needs the whole candidate set); see `patch_deck_zorder`'s own grouping, which callers
    computing eligibility ahead of a real patch must replicate over their candidates'
    `target_member`s."""
    target_member, _slide_id, refuse_reason = _zorder_slide_edit(
        slide_number, new_order, objects, id_to_file, order)
    return target_member, refuse_reason


def patch_deck_zorder(deck: Path | str, orders_by_slide: dict[int, list[str]]) -> dict[int, PatchResult]:
    """Patch every slide in ``orders_by_slide`` with exactly ONE zip rewrite, writing
    ``drawablesZOrder`` AND ``ownedDrawables`` identically to the requested order.

    Refusal is per slide (that slide's member left byte-identical) on: the slide's
    member not containing its drawables' order (located via ``id_to_file``, never a
    guessed filename, and never partially resolved); id multiset mismatch between the
    requested order and the current ``drawablesZOrder``; ``ownedDrawables`` not a
    permutation of ``drawablesZOrder`` (refuse rather than guess a redistribution); a
    member shared with another patched slide -- UNLIKE ``patch_deck_geometry``'s
    earlier-slide-wins rule, every slide sharing that member is refused, since editing
    one would silently change the bytes of a slide reported as refused-and-untouched.
    Collision detection registers every slide whose ``target_member`` resolved, even
    one already refused for another reason (which is kept); a slide that could not
    resolve a member at all is not registered. Reuses ``iwa_write``'s ``_patch_zorder_member`` /
    ``_rewrite_members`` / ``PatchResult`` and their ``value_clean`` /
    ``OfflineWriteCorrupted`` semantics exactly.

    Read-back verify runs always, after the rewrite: each patched slide is re-read via
    ``read_slide_zorder`` and checked for (a) an unchanged id multiset, (b)
    ``ownedDrawables == drawablesZOrder``, (c) the order matching what was requested. A
    mismatch raises ``ValueError`` naming the slide -- the deck is already written at
    that point.
    """
    if 0 in orders_by_slide:
        raise ValueError("slide numbers are 1-based")
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    order = slide_order(objects)

    slide_state: dict[int, tuple[str | None, str | None, str | None]] = {}
    member_slides: dict[str, list[int]] = {}
    for n in sorted(orders_by_slide):
        target_member, slide_id, refuse_reason = _zorder_slide_edit(
            n, orders_by_slide[n], objects, id_to_file, order)
        if target_member is not None:
            member_slides.setdefault(target_member, []).append(n)
        slide_state[n] = (target_member, slide_id, refuse_reason)

    member_owner: dict[str, int] = {}
    for member, slides in member_slides.items():
        if len(slides) > 1:
            for n in slides:
                target_member, slide_id, reason = slide_state[n]
                if reason is None:
                    reason = f"member shared with slide(s) {sorted(set(slides) - {n})}"
                slide_state[n] = (target_member, slide_id, reason)
        else:
            n = slides[0]
            if slide_state[n][2] is None:
                member_owner[member] = n

    member_edits: dict[str, bytes] = {}
    member_diag: dict[str, tuple[int, int, int]] = {}  # applied, obj_diffs, header_diffs
    if member_owner:
        with zipfile.ZipFile(deck) as zf:  # one handle shared across every member patch
            for member, n in member_owner.items():
                _tm, slide_id, _reason = slide_state[n]
                new_bytes, applied, obj_diffs, header_diffs = _patch_zorder_member(
                    zf, member, slide_id, orders_by_slide[n])
                if applied != 1:
                    slide_state[n] = (_tm, slide_id, f"expected 1 archive write, got {applied}")
                    continue
                member_edits[member] = new_bytes
                member_diag[member] = (applied, obj_diffs, header_diffs)

    results: dict[int, PatchResult] = {}
    for n, (target_member, slide_id, refuse_reason) in slide_state.items():
        if refuse_reason:
            results[n] = PatchResult(refused=True, reason=refuse_reason, target_member=target_member)
        else:
            applied, obj_diffs, header_diffs = member_diag[target_member]
            value_clean = obj_diffs <= 1 and header_diffs == 0
            results[n] = PatchResult(
                applied=applied, target_member=target_member, value_clean=value_clean,
                obj_diffs=obj_diffs, header_diffs=header_diffs, edited_ids=[slide_id],
            )

    if member_edits:
        try:
            _rewrite_members(deck, member_edits)
        except OfflineWriteCorrupted:
            raise  # deck IS truncated: must reach the caller, never a refused result
        except Exception as exc:  # noqa: BLE001 — every result refuses, deck left untouched
            for n, prev in results.items():
                if not prev.refused:
                    results[n] = PatchResult(refused=True, reason=f"rewrite failed: {exc}",
                                             target_member=prev.target_member)
            return results

    for n, result in results.items():
        if result.refused:
            continue
        want = orders_by_slide[n]
        z, owned = read_slide_zorder(deck, n)
        if Counter(z) != Counter(want):
            raise ValueError(f"zorder read-back id-set mismatch on slide {n}: got {z}, want {want}")
        if owned != z:
            raise ValueError(
                f"zorder read-back ownedDrawables != drawablesZOrder on slide {n}: owned={owned} z={z}")
        if z != want:
            raise ValueError(f"zorder read-back order mismatch on slide {n}: got {z}, want {want}")

    return results

"""Pure-logic tests for ``obed_edom.iwa_zorder`` (``w-zorder-patch`` piece 1).

Keynote-free. Deck builders reuse ``_arch``/``_member``/``_shape_super`` from
``tests/test_iwa_write.py``, the way ``tests/test_probe_zorder_patch.py`` does.
"""
from __future__ import annotations

import io
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: E402
from obed_edom.iwa_zorder import (  # noqa: E402
    _coincident_group_rects,
    plan_slide_order,
    raise_to_front,
    resolve_raise_targets,
)

from test_iwa_write import _arch, _member, _shape_super  # noqa: E402


# ==========================================================================
# raise_to_front — pure list logic, no deck needed.
# ==========================================================================
def test_raise_to_front_noop_when_already_frontmost():
    assert raise_to_front(["a", "b", "c"], ["c"]) == ["a", "b", "c"]
    assert raise_to_front(["a", "b", "c"], ["b", "c"]) == ["a", "b", "c"]


def test_raise_to_front_interleaved():
    assert raise_to_front(["a", "b", "c", "d"], ["a", "c"]) == ["b", "d", "a", "c"]


def test_raise_to_front_spans_whole_array():
    assert raise_to_front(["a", "b", "c"], ["b", "a", "c"]) == ["b", "a", "c"]


def test_raise_to_front_single_target():
    assert raise_to_front(["a", "b", "c"], ["a"]) == ["b", "c", "a"]


def test_raise_to_front_empty_targets():
    assert raise_to_front(["a", "b", "c"], []) == ["a", "b", "c"]


def test_raise_to_front_unknown_id_raises():
    with pytest.raises(ValueError):
        raise_to_front(["a", "b", "c"], ["z"])


def test_raise_to_front_duplicate_target_raises():
    with pytest.raises(ValueError, match="a"):
        raise_to_front(["a", "b", "c"], ["a", "b", "a"])


def test_raise_to_front_does_not_mutate_input():
    order = ["a", "b", "c"]
    raise_to_front(order, ["a"])
    assert order == ["a", "b", "c"]


# ==========================================================================
# Deck builders.
# ==========================================================================
def _group(gid, child_id, text=None, rect=(0, 0, 0, 0)):
    """`text=None` leaves the child textless (`_group_child_signature` == ""), fine for
    any test that doesn't verify a stat job's `childSig` against it. A test resolving a
    stat job that must succeed needs `text` set to that job's `childSig`, since
    `resolve_raise_targets` now checks the two match. `rect` is the group's own (x, y, w,
    h) — defaults to all-zero, which makes every default-built group coincident with every
    other; pass distinct rects to build non-coincident twins."""
    child = {"isTextBox": False, "super": _shape_super(0, 0, 30, 30)}
    members = []
    if text is not None:
        storage_id = child_id * 100
        child["ownedStorage"] = {"identifier": storage_id}
        members.append(_arch(storage_id, "TSWP.StorageArchive", {"text": [text]}))
    return [
        _arch(child_id, "TSWP.ShapeInfoArchive", child),
        *members,
        _arch(gid, "TSD.GroupArchive", {"super": _shape_super(*rect)["super"], "children": [{"identifier": child_id}]}),
    ]


def _write_deck(path, slide_member, zorder_ids):
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": i} for i in zorder_ids]})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *slide_member]))
    path.write_bytes(buf.getvalue())
    return path


def _slide_and_objects(deck):
    objects, _id_to_file, _file_ids = _load_deck(deck)
    slide = objects[slide_order(objects)[0][0]]
    return slide, objects


# ==========================================================================
# resolve_raise_targets.
# ==========================================================================
def test_resolve_stat_targets_ascending_by_z_regardless_of_job_order(tmp_path):
    # Two groups: A (children 301) at z-slot 0, B (children 303) at z-slot 1.
    members = [*_group(300, 301, "a"), *_group(302, 303, "b")]
    deck = _write_deck(tmp_path / "stat.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    # 1-based, already hide-bridged groupIndex: A=1, B=2. Jobs given out of order.
    stat_jobs = [
        {"slide": 1, "groupIndex": 2, "childSig": "b"},
        {"slide": 1, "groupIndex": 1, "childSig": "a"},
    ]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == ["300", "302"]
    assert badge_ids == []
    assert unresolved == []


def test_resolve_stat_group_index_is_not_bridged_again_when_hides_exist(tmp_path):
    # Three wall groups A, B, C (children 301, 303, 305). A (wall kindIndex 0) is hidden,
    # so the saved deck's drawablesZOrder only contains B, C post-hide — B lands at
    # kindIndex 0, C at kindIndex 1.
    members = [*_group(300, 301), *_group(302, 303), *_group(304, 305, "c")]
    deck = _write_deck(tmp_path / "stat_hide.key", members, [302, 304])
    slide, objects = _slide_and_objects(deck)
    hide_specs = [{"kind": "group", "kindIndex": 0}]  # A deleted

    # Stat groupIndex values come from map_remap.adjust_child_resize_indexes, which has
    # already hide-bridged them upstream: wall B/C (1-based, ignoring the hidden A) map to
    # groupIndex 1/2. Unlike badge rows (wall-based, bridged in resolve_raise_targets via
    # bridge_kind_index), a stat job's groupIndex must only be decremented to a 0-based
    # kindIndex here — bridging it again would double-shift past the hidden group and hit
    # the wrong drawable. groupIndex=2 should resolve to C, not B.
    stat_jobs = [{"slide": 1, "groupIndex": 2, "childSig": "c"}]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], hide_specs)

    assert unresolved == []
    assert badge_ids == []
    assert stat_ids == ["304"]


def test_resolve_stat_targets_shared_sig_matching_cardinality_resolves_all(tmp_path):
    # Both candidates carry the same saved signature "dup" and both jobs are flagged
    # `twin` (count-matched, 2 jobs / 2 candidates) — but B sits at a different rect from
    # A, non-coincident, so the twin arm's geometry check fails and the sig falls to the
    # shared-sig bijection arm instead: G("dup") = {300, 302}, J("dup") has 2 jobs, the
    # cardinalities match, so both are claimed.
    members = [*_group(300, 301, "dup", rect=(0, 0, 10, 10)), *_group(302, 303, "dup", rect=(200, 0, 10, 10))]
    deck = _write_deck(tmp_path / "ambig.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "childSig": "dup", "twin": True},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert unresolved == []
    assert stat_ids == ["300", "302"]


def test_coincident_group_rects_all_pairs_not_just_first():
    # x=0, -4, +4 with tol=4: 0 vs -4 and 0 vs +4 are each within tolerance, but -4 vs
    # +4 are 8 apart — comparing only against the first rect would wrongly pass this.
    assert not _coincident_group_rects([(0, 0, 0, 0), (-4, 0, 0, 0), (4, 0, 0, 0)])
    assert _coincident_group_rects([(0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0)])


def test_resolve_stat_targets_coincident_twin_sig_resolves_both_in_z_order(tmp_path):
    # A and B share childSig "dup" and the same rect (both default to (0,0,0,0)) — a
    # coincident twin pair, count 2 == 2 jobs, and BOTH jobs carry the planner's `twin`
    # proof, so both resolve instead of refusing.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "dup")]
    deck = _write_deck(tmp_path / "twin.key", members, [302, 300])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "groupIndex": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "groupIndex": 2, "childSig": "dup", "twin": True},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert unresolved == []
    assert stat_ids == ["302", "300"]  # ascending by z-position (302 is z-slot 0)


def test_resolve_stat_targets_extra_same_sig_candidate_at_end_refuses(tmp_path):
    # Codex regression: a third group C also carries "dup" but sits elsewhere, so the
    # twin arm's coincidence check fails and the sig falls to the shared-sig bijection
    # arm. G("dup") = {300, 302, 304} (3) != J("dup") (2) — the whole slide must refuse
    # with an ambiguous-cardinality token, NOT silently resolve 2 of the 3 candidates
    # (the bug the positional arm's index-hint verification could not catch).
    members = [
        *_group(300, 301, "dup"),
        *_group(302, 303, "dup"),
        *_group(304, 305, "dup", rect=(500, 500, 10, 10)),
    ]
    deck = _write_deck(tmp_path / "twin3_end.key", members, [300, 302, 304])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "childSig": "dup", "twin": True},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == []
    assert unresolved == [
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=3)",
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=3)",
    ]


def test_resolve_stat_targets_extra_same_sig_candidate_at_start_refuses(tmp_path):
    # Same regression, mirrored: the extra non-coincident "dup" candidate sits FIRST in
    # saved z order (this is the shape of the banked Gold slide-19 scramble — a group
    # moved from LAST to FIRST in its kind on save) rather than last. Cardinality still
    # governs: 3 candidates, 2 jobs, refuse.
    members = [
        *_group(304, 305, "dup", rect=(500, 500, 10, 10)),
        *_group(300, 301, "dup"),
        *_group(302, 303, "dup"),
    ]
    deck = _write_deck(tmp_path / "twin3_start.key", members, [304, 300, 302])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "childSig": "dup", "twin": True},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == []
    assert unresolved == [
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=3)",
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=3)",
    ]


def test_resolve_stat_targets_fewer_groups_than_jobs_refuses(tmp_path):
    # Two jobs claim sig "dup" (ambiguous by job count), both flagged `twin`, but only
    # ONE saved-deck group actually carries it (B's real signature is "other") —
    # candidate count (1) != job count (2), so neither the twin rule nor the bijection
    # rule applies: both jobs refuse with ambiguous-cardinality, none resolve.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "other")]
    deck = _write_deck(tmp_path / "twin_mismatch.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "childSig": "dup", "twin": True},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == []
    assert unresolved == [
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=1)",
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=2 groups=1)",
    ]


def test_resolve_stat_targets_coincident_sigs_neither_flagged_twin_resolves_via_bijection(tmp_path):
    # Same coincident twin geometry as the positive twin case, but the planner never
    # proved a twin (`twin` absent on both jobs) — the twin arm never applies (job count
    # of `twin`-flagged jobs is 0), so this falls to the shared-sig bijection arm, where
    # cardinality matches (2 == 2) and both resolve.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "dup")]
    deck = _write_deck(tmp_path / "twin_noflag.key", members, [302, 300])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup"},
        {"slide": 1, "childSig": "dup"},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert unresolved == []
    assert stat_ids == ["302", "300"]  # ascending by z-position (302 is z-slot 0)


def test_resolve_stat_targets_coincident_sigs_one_flagged_twin_resolves_via_bijection(tmp_path):
    # Same coincident twin geometry, but only ONE of the two jobs sharing the sig is
    # flagged `twin` — mirrors keynote.py's `allow_fallback = 2 only if ALL jobs sharing
    # the sig are twin`; a partial flag must not resolve via the twin arm, so this falls
    # to the shared-sig bijection arm instead, where cardinality matches and both resolve.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "dup")]
    deck = _write_deck(tmp_path / "twin_partial.key", members, [302, 300])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup", "twin": True},
        {"slide": 1, "childSig": "dup"},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert unresolved == []
    assert stat_ids == ["302", "300"]


def test_resolve_badge_rows_of_each_kind(tmp_path):
    members = [
        _arch(210, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 140, 0, nw=140, nh=0, line=True)}),
        _arch(221, "TSWP.StorageArchive", {"text": ["Hi"]}),
        _arch(220, "TSWP.ShapeInfoArchive", {"isTextBox": True, "ownedStorage": {"identifier": 221}, "super": _shape_super(0, 0, 200, 60, nw=200, nh=60)}),
        _arch(231, "TSD.MaskArchive", {"pathsource": {"bezierPathSource": {"naturalSize": {"width": 60, "height": 60}}}, "super": {"geometry": {"position": {"x": 0, "y": 0}, "size": {"width": 60, "height": 60}, "angle": 0.0}}}),
        _arch(230, "TSD.ImageArchive", {"mask": {"identifier": 231}, "super": {"geometry": {"position": {"x": 0, "y": 0}, "size": {"width": 60, "height": 60}, "angle": 0.0}}, "originalSize": {"width": 60.0, "height": 60.0}}),
        _arch(200, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)}),
        *_group(250, 251),
    ]
    deck = _write_deck(tmp_path / "kinds.key", members, [210, 220, 230, 200, 250])
    slide, objects = _slide_and_objects(deck)

    badge_rows = [
        {"kind": "line", "index": 1},
        {"kind": "text", "index": 1},
        {"kind": "image", "index": 1},
        {"kind": "shape", "index": 1},
        {"kind": "group", "index": 1},
    ]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, [], badge_rows, [])

    assert unresolved == []
    assert stat_ids == []
    assert badge_ids == ["210", "220", "230", "200", "250"]


def test_resolve_badge_row_bridged_below_target(tmp_path):
    # Saved deck (post-hide): only groups B, C survive (wall indices 1, 2).
    members = [*_group(300, 301), *_group(302, 303)]
    deck = _write_deck(tmp_path / "hide_below.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)
    hide_specs = [{"kind": "group", "kindIndex": 0}]  # A (wall index 0) deleted

    badge_rows = [{"kind": "group", "index": 2}, {"kind": "group", "index": 3}]  # wall B, C (1-based)
    _stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, [], badge_rows, hide_specs)

    assert unresolved == []
    assert badge_ids == ["300", "302"]


def test_resolve_badge_row_hide_above_target_is_unaffected(tmp_path):
    # Saved deck (post-hide): only groups A, B survive; C (wall index 2) deleted.
    members = [*_group(300, 301), *_group(302, 303)]
    deck = _write_deck(tmp_path / "hide_above.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)
    hide_specs = [{"kind": "group", "kindIndex": 2}]  # C (wall index 2) deleted, above targets

    badge_rows = [{"kind": "group", "index": 1}]  # wall A (1-based)
    _stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, [], badge_rows, hide_specs)

    assert unresolved == []
    assert badge_ids == ["300"]


def test_resolve_shape_text_dual(tmp_path):
    # isTextBox + editable custom path: registers as BOTH "text" and "shape" (duplicateOf).
    members = [
        _arch(221, "TSWP.StorageArchive", {"text": ["Dual"]}),
        _arch(220, "TSWP.ShapeInfoArchive",
              {"isTextBox": True, "ownedStorage": {"identifier": 221},
               "super": _shape_super(0, 0, 100, 50, kind="editable")}),
    ]
    deck = _write_deck(tmp_path / "dual.key", members, [220])
    slide, objects = _slide_and_objects(deck)

    badge_rows = [{"kind": "text", "index": 1}, {"kind": "shape", "index": 1}]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, [], badge_rows, [])

    assert unresolved == []
    assert badge_ids == ["220", "220"]

    # A dual row resolving to the same id in both slots must be refused, not duplicated.
    with pytest.raises(ValueError, match="220"):
        plan_slide_order(slide, objects, stat_ids, badge_ids)


def test_resolve_stat_job_with_falsy_child_sig_yields_no_target(tmp_path):
    members = [*_group(300, 301)]
    deck = _write_deck(tmp_path / "no_sig.key", members, [300])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [{"slide": 1, "groupIndex": 1, "childSig": None}]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == []
    assert badge_ids == []
    assert unresolved == []


def test_resolve_stat_targets_extra_job_beyond_matching_candidates_refuses(tmp_path):
    # Three jobs share sig "dup" but only two saved-deck groups carry it — cardinality
    # mismatch (3 jobs vs 2 groups) refuses the whole signature, all three jobs unresolved.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "dup")]
    deck = _write_deck(tmp_path / "positional_range.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup"},
        {"slide": 1, "childSig": "dup"},
        {"slide": 1, "childSig": "dup"},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert stat_ids == []
    assert unresolved == [
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=3 groups=2)",
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=3 groups=2)",
        "stat:s=1,sig=dup(ambiguous-cardinality jobs=3 groups=2)",
    ]


def test_resolve_mixed_slide_twin_shared_and_unique_all_resolve_disjoint(tmp_path):
    # One proven-twin pair (sig "t"), one shared-non-twin pair resolved via the bijection
    # arm (sig "p"), and one unique sig ("u") on the same slide — all three arms in play,
    # all ids disjoint, front block ascending by z regardless of job order.
    members = [
        *_group(300, 301, "t"), *_group(302, 303, "t"),
        *_group(304, 305, "p"), *_group(306, 307, "p"),
        *_group(308, 309, "u"),
    ]
    deck = _write_deck(tmp_path / "mixed.key", members, [300, 302, 304, 306, 308])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "groupIndex": 5, "childSig": "u"},
        {"slide": 1, "childSig": "t", "twin": True},
        {"slide": 1, "childSig": "p"},
        {"slide": 1, "childSig": "t", "twin": True},
        {"slide": 1, "childSig": "p"},
    ]
    stat_ids, _badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])

    assert unresolved == []
    assert len(stat_ids) == len(set(stat_ids)) == 5
    assert stat_ids == sorted(stat_ids, key=["300", "302", "304", "306", "308"].index)

    order = plan_slide_order(slide, objects, stat_ids, [])
    assert order[-5:] == ["300", "302", "304", "306", "308"]


def test_resolve_mixed_slide_order_independent(tmp_path):
    # Same mixed slide as above, jobs shuffled — resolve_raise_targets and
    # plan_slide_order must produce identical output regardless of job order.
    members = [
        *_group(300, 301, "t"), *_group(302, 303, "t"),
        *_group(304, 305, "p"), *_group(306, 307, "p"),
        *_group(308, 309, "u"),
    ]
    deck = _write_deck(tmp_path / "mixed_shuffled.key", members, [300, 302, 304, 306, 308])
    slide, objects = _slide_and_objects(deck)

    base_jobs = [
        {"slide": 1, "groupIndex": 5, "childSig": "u"},
        {"slide": 1, "childSig": "t", "twin": True},
        {"slide": 1, "childSig": "p"},
        {"slide": 1, "childSig": "t", "twin": True},
        {"slide": 1, "childSig": "p"},
    ]
    shuffled_jobs = list(reversed(base_jobs))

    stat_ids_a, _b1, unresolved_a = resolve_raise_targets(slide, objects, base_jobs, [], [])
    stat_ids_b, _b2, unresolved_b = resolve_raise_targets(slide, objects, shuffled_jobs, [], [])

    assert unresolved_a == unresolved_b == []
    assert sorted(stat_ids_a) == sorted(stat_ids_b)
    order_a = plan_slide_order(slide, objects, stat_ids_a, [])
    order_b = plan_slide_order(slide, objects, stat_ids_b, [])
    assert order_a == order_b


def test_resolve_badge_and_shared_stat_collision_refused(tmp_path):
    # A badge row and a bijection-resolved stat job land on the same id — must refuse,
    # not silently drop one (which raise_to_front would otherwise explode on later).
    # badge_rows wall index 1 below resolves to id 300, which the stat block claims first.
    members = [*_group(300, 301, "dup"), *_group(302, 303, "dup")]
    deck = _write_deck(tmp_path / "badge_stat_collision.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "childSig": "dup"},
        {"slide": 1, "childSig": "dup"},
    ]
    badge_rows = [{"kind": "group", "index": 1}]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, badge_rows, [])

    assert stat_ids == ["300", "302"]
    assert badge_ids == []
    assert unresolved == ["badge:k=group,i=1(collision)"]


def test_resolve_unresolvable_badge_row(tmp_path):
    members = [_arch(200, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)})]
    deck = _write_deck(tmp_path / "unresolvable.key", members, [200])
    slide, objects = _slide_and_objects(deck)

    badge_rows = [{"kind": "shape", "index": 5}]  # no shape at wall kindIndex 4
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, [], badge_rows, [])

    assert stat_ids == []
    assert badge_ids == []
    assert unresolved == ["badge:k=shape,i=5"]


# ==========================================================================
# plan_slide_order.
# ==========================================================================
def test_plan_slide_order_badge_block_ends_above_stat_block(tmp_path):
    members = [
        _arch(200, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)}),
        *_group(300, 301),
        *_group(302, 303),
    ]
    deck = _write_deck(tmp_path / "order.key", members, [200, 300, 302])
    slide, objects = _slide_and_objects(deck)

    order = plan_slide_order(slide, objects, stat_ids=["300", "302"], badge_ids=["200"])
    assert order == ["300", "302", "200"]


def test_plan_slide_order_stat_block_ascending_by_z_regardless_of_job_order(tmp_path):
    members = [*_group(300, 301, "a"), *_group(302, 303, "b"), *_group(304, 305, "c")]
    deck = _write_deck(tmp_path / "order2.key", members, [300, 302, 304])
    slide, objects = _slide_and_objects(deck)

    stat_jobs = [
        {"slide": 1, "groupIndex": 3, "childSig": "c"},
        {"slide": 1, "groupIndex": 1, "childSig": "a"},
        {"slide": 1, "groupIndex": 2, "childSig": "b"},
    ]
    stat_ids, badge_ids, unresolved = resolve_raise_targets(slide, objects, stat_jobs, [], [])
    assert unresolved == []

    order = plan_slide_order(slide, objects, stat_ids, badge_ids)
    assert order == ["300", "302", "304"]


def test_plan_slide_order_sorts_stat_ids_itself_given_reverse_z_order(tmp_path):
    members = [*_group(300, 301), *_group(302, 303), *_group(304, 305)]
    deck = _write_deck(tmp_path / "order3.key", members, [300, 302, 304])
    slide, objects = _slide_and_objects(deck)

    # stat_ids passed directly, in reverse z order, bypassing resolve_raise_targets.
    order = plan_slide_order(slide, objects, stat_ids=["304", "302", "300"], badge_ids=[])
    assert order == ["300", "302", "304"]


def test_plan_slide_order_overlap_between_stat_and_badge_raises(tmp_path):
    members = [*_group(300, 301), *_group(302, 303)]
    deck = _write_deck(tmp_path / "overlap.key", members, [300, 302])
    slide, objects = _slide_and_objects(deck)

    with pytest.raises(ValueError, match="300"):
        plan_slide_order(slide, objects, stat_ids=["300"], badge_ids=["300"])

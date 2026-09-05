"""Content identity and pairing reuse (obed_edom.baseline).

Jobs are keyed by id; this module remaps saved slots onto current slides by
content digest so unchanged pairings carry over.

INSPECT_VERSION is the payload-shape cache partition (v4 = offline IWA + bulk
geometry). The cache is keyed by deck digest, which says nothing about the
reader, so without the bump a deck inspected by an older build is reused
forever. Rotation-value consistency is the v4 reason: JXA reports whole-degree
rotation, the offline read composes frame+mask angle and carries a sub-degree
residual on masked images — mixing v3 JXA with a fresh offline payload churns
deck_slide_digests and fires photo-tilt. Keynote's app version is the other half
of "the reader" (.k<version> tag). Untagged payloads were 14.5 and are no longer
read.
"""
from pathlib import Path

from obed_edom.baseline import (
    deck_digest,
    deck_slide_digests,
    index_map,
    insert_unpaired,
    load_pairing,
    remap_slots,
    reuse_slots,
    save_pairing,
    slot_dict,
)


def test_deck_digest_file_and_package(tmp_path: Path):
    file_key = tmp_path / "deck.key"
    file_key.write_bytes(b"alpha")
    assert deck_digest(file_key) == deck_digest(file_key)
    other = tmp_path / "other.key"
    other.write_bytes(b"beta")
    assert deck_digest(file_key) != deck_digest(other)

    pkg = tmp_path / "pack.key"
    (pkg / "Data").mkdir(parents=True)
    (pkg / "Index").mkdir()
    (pkg / "Data" / "a.png").write_bytes(b"img")
    (pkg / "Index" / "doc").write_bytes(b"idx")
    first = deck_digest(pkg)
    (pkg / "Data" / "a.png").write_bytes(b"img")
    assert deck_digest(pkg) == first
    (pkg / "Data" / "a.png").write_bytes(b"IMG")
    assert deck_digest(pkg) != first


def test_deck_slide_digests_change_with_copy():
    payload = {
        "slides": [
            {"number": 1, "items": [{"kind": "text", "text": "Faith"}]},
            {
                "number": 2,
                "items": [{"kind": "image", "text": "", "fileName": "a.jpg", "x": 0, "y": 0, "w": 10, "h": 10}],
            },
        ]
    }
    a = deck_slide_digests(payload)
    payload["slides"][0]["items"][0]["text"] = "Your Faith"
    b = deck_slide_digests(payload)
    assert a[0] != b[0]
    assert a[1] == b[1]


def test_index_map_insert_delete_edit_reorder():
    old = ["a", "b", "c", "d"]
    assert index_map(old, ["a", "x", "b", "c", "d"]) == {0: 0, 1: 2, 2: 3, 3: 4}
    assert index_map(old, ["a", "c", "d"]) == {0: 0, 2: 1, 3: 2}
    assert index_map(old, ["a", "B", "c", "d"]) == {0: 0, 2: 2, 3: 3}
    # Unique leftovers still map across a swap.
    assert index_map(["a", "b", "c"], ["a", "c", "b"]) == {0: 0, 1: 2, 2: 1}


def _baseline(left, right, slots):
    return {"leftDigests": left, "rightDigests": right, "slots": slots, "source": "operator"}


def _paired(*n):
    return [slot_dict(i, [i], 1.0) for i in n]


def test_reuse_insert_keeps_neighbours():
    result = reuse_slots(
        _baseline(["a", "b", "c"], ["A", "B", "C"], _paired(0, 1, 2)),
        ["a", "x", "b", "c"],
        ["A", "B", "C"],
        threshold=0.6,
    )
    assert result is not None
    by_left = {s["leftIndex"]: s["rightIndexes"] for s in result.slots if s["leftIndex"] is not None}
    assert by_left[0] == [0]
    assert by_left[2] == [1]
    assert by_left[3] == [2]
    assert by_left[1] == []
    assert result.added >= 1
    assert result.carried == 3


def test_reuse_delete_drops_vanished_end():
    result = reuse_slots(
        _baseline(["a", "b", "c"], ["A", "B", "C"], _paired(0, 1, 2)),
        ["a", "c"],
        ["A", "B", "C"],
        threshold=0.4,
    )
    assert result is not None
    by_left = {s["leftIndex"]: s["rightIndexes"] for s in result.slots if s["leftIndex"] is not None}
    assert by_left[0] == [0]
    assert by_left[1] == [2]
    rights = [r for s in result.slots for r in s["rightIndexes"]]
    assert 1 in rights or any(s["rightIndexes"] == [1] and s["leftIndex"] is None for s in result.slots)


def test_reuse_edit_keeps_unchanged():
    result = reuse_slots(
        _baseline(["a", "b", "c"], ["A", "B", "C"], _paired(0, 1, 2)),
        ["a", "X", "c"],
        ["A", "B", "C"],
        threshold=0.6,
    )
    assert result is not None
    by_left = {s["leftIndex"]: s["rightIndexes"] for s in result.slots if s["leftIndex"] is not None}
    assert by_left[0] == [0]
    assert by_left[2] == [2]
    assert by_left[1] == []
    assert result.changed >= 1


def test_reuse_reorder_unique_slides():
    result = reuse_slots(
        _baseline(["a", "b", "c"], ["A", "B", "C"], _paired(0, 1, 2)),
        ["a", "c", "b"],
        ["A", "C", "B"],
        threshold=0.6,
    )
    assert result is not None
    by_left = {s["leftIndex"]: s["rightIndexes"] for s in result.slots if s["leftIndex"] is not None}
    assert by_left[0] == [0]
    assert by_left[1] == [1]
    assert by_left[2] == [2]


def test_reuse_wholesale_returns_none():
    assert (
        reuse_slots(
            _baseline(["a", "b", "c"], ["A", "B", "C"], _paired(0, 1, 2)),
            ["x", "y", "z"],
            ["X", "Y", "Z"],
            threshold=0.6,
        )
        is None
    )


def test_reuse_below_threshold_is_fresh():
    old = [f"s{i}" for i in range(10)]
    new = ["s0"] + [f"n{i}" for i in range(9)]
    assert (
        reuse_slots(
            _baseline(old, old, _paired(*range(10))),
            new,
            old,
            threshold=0.6,
        )
        is None
    )


def test_insert_unpaired_places_new_index_in_order():
    slots = [slot_dict(0, [0]), slot_dict(2, [1])]
    out = insert_unpaired(slots, 3, 2)
    lefts = [s["leftIndex"] for s in out]
    assert 1 in lefts
    assert lefts.index(1) < lefts.index(2)


def test_insert_unpaired_one_sided_row_is_not_a_barrier():
    # An early LW-only row must not drag a later leftover DSK slide to the top:
    # the edited DSK3's pair was dropped (LW4 now left-only), and DSK3 must land
    # next to LW4 for realign to re-pair them, not before the early LW1-only row.
    slots = [
        slot_dict(0, [0]),
        slot_dict(1, []),   # early LW-only row
        slot_dict(2, [1]),
        slot_dict(3, [2]),
        slot_dict(4, []),   # was paired to the edited DSK3, now LW-only
    ]
    out = insert_unpaired(slots, n_left=5, n_right=4)
    dsk3 = next(i for i, s in enumerate(out) if s["rightIndexes"] == [3])
    lw1 = next(i for i, s in enumerate(out) if s["leftIndex"] == 1 and not s["rightIndexes"])
    lw4 = next(i for i, s in enumerate(out) if s["leftIndex"] == 4 and not s["rightIndexes"])
    assert dsk3 > lw1          # not teleported above the early one-sided row
    assert abs(dsk3 - lw4) == 1  # sits beside its true neighbour


def test_reuse_edit_right_slide_keeps_order():
    # Editing one DSK slide (its digest changes) must not float it to the top.
    result = reuse_slots(
        _baseline(
            ["a", "b", "c", "d", "e"],
            ["A", "B", "C", "D"],
            [slot_dict(0, [0]), slot_dict(1, []), slot_dict(2, [1]),
             slot_dict(3, [2]), slot_dict(4, [3])],
        ),
        ["a", "b", "c", "d", "e"],
        ["A", "B", "C", "D2"],  # DSK index 3 edited
        threshold=0.4,
    )
    assert result is not None
    order = [s["rightIndexes"] for s in result.slots]
    dsk3 = order.index([3])
    # DSK3 stays after the earlier DSK pairs, not at the top.
    assert dsk3 > order.index([1])
    assert dsk3 > order.index([2])


def test_pairing_store_roundtrip(tmp_path: Path):
    left = tmp_path / "lw.key"
    right = tmp_path / "dsk.key"
    left.write_text("a")
    right.write_text("b")
    rec = save_pairing(
        "diff",
        left,
        right,
        ["aa"],
        ["bb"],
        [slot_dict(0, [0])],
        source="operator",
        job_id="abc",
        root=tmp_path,
    )
    loaded = load_pairing("diff", left, right, root=tmp_path)
    assert loaded is not None
    assert loaded["slots"][0]["leftIndex"] == 0
    assert loaded["source"] == "operator"
    save_pairing(
        "diff",
        left,
        right,
        ["aa"],
        ["bb"],
        [slot_dict(1, [1])],
        source="auto",
        root=tmp_path,
    )
    kept = load_pairing("diff", left, right, root=tmp_path)
    assert kept is not None
    assert kept["slots"][0]["leftIndex"] == 0
    assert rec["jobId"] == "abc"

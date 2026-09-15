"""Content identity and pairing reuse (obed_edom.baseline).

Jobs are keyed by id; this module remaps saved slots onto current slides by
content digest so unchanged pairings carry over.

INSPECT_VERSION is the payload-shape cache partition (v5 = offline IWA + bulk
geometry + per-item aspect). The cache is keyed by deck digest, which says
nothing about the reader, so without the bump a deck inspected by an older
build is reused forever. Rotation-value consistency is the v4 reason: JXA
reports whole-degree rotation, the offline read composes frame+mask angle and
carries a sub-degree residual on masked images — mixing v3 JXA with a fresh
offline payload churns deck_slide_digests and fires photo-tilt. v5 adds an
unrounded composed-aspect float per item so the planner can snap
aspect-locked kinds to it. Keynote's app version is the other half of "the
reader" (.k<version> tag). Untagged payloads were 14.5 and are no longer
read.
"""
import hashlib
import json
import os
import stat
import threading
from pathlib import Path

import pytest

import obed_edom.baseline as baseline_mod

from obed_edom.baseline import (
    CACHE_DIR_ENV,
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


def _digest_sidecar(cache: Path, deck: Path) -> Path:
    key = hashlib.sha256(os.fsencode(str(deck.resolve()))).hexdigest()
    return cache / "deck_digest" / f"{key}.json"


def _cache_root(monkeypatch, tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setenv(CACHE_DIR_ENV, str(cache))
    return cache


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


def test_deck_digest_file_sidecar_is_exact_warm_and_private(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = hashlib.sha256(b"alpha").hexdigest()

    assert deck_digest(deck) == expected
    sidecar = _digest_sidecar(cache, deck)
    record = json.loads(sidecar.read_text())
    assert record["digest"] == expected
    assert record["path"] == str(deck.resolve())
    assert all(
        isinstance(record[key], int) and not isinstance(record[key], bool)
        for key in ("size", "mtimeNs", "device", "inode", "ctimeNs")
    )
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600

    monkeypatch.setattr(
        baseline_mod,
        "_hash_regular_file",
        lambda *_args: (_ for _ in ()).throw(AssertionError("warm hash")),
    )
    assert deck_digest(deck) == expected


def test_deck_digest_sidecar_rejects_atomic_replacement_with_preserved_size_and_mtime(
    tmp_path: Path, monkeypatch
):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    before = deck.stat()
    assert deck_digest(deck) == hashlib.sha256(b"alpha").hexdigest()
    before_record = json.loads(_digest_sidecar(cache, deck).read_text())

    replacement = tmp_path / "replacement.key"
    replacement.write_bytes(b"bravo")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, deck)
    after = deck.stat()

    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ino != before.st_ino
    assert deck_digest(deck) == hashlib.sha256(b"bravo").hexdigest()
    after_record = json.loads(_digest_sidecar(cache, deck).read_text())
    assert after_record["device"] == after.st_dev
    assert after_record["inode"] == after.st_ino
    assert after_record["ctimeNs"] == after.st_ctime_ns
    assert after_record["inode"] != before_record["inode"]


def test_deck_digest_sidecar_validates_every_identity_guard(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = deck_digest(deck)
    sidecar = _digest_sidecar(cache, deck)
    original = json.loads(sidecar.read_text())

    for key in ("device", "inode", "ctimeNs"):
        corrupt = dict(original)
        corrupt[key] += 1
        sidecar.write_text(json.dumps(corrupt))
        assert deck_digest(deck) == expected
        assert json.loads(sidecar.read_text())[key] == original[key]


def test_deck_digest_sidecar_is_per_resolved_path_and_symlink_converges(
    tmp_path: Path, monkeypatch
):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    copied = tmp_path / "copy.key"
    deck.write_bytes(b"alpha")
    copied.write_bytes(b"alpha")
    link = tmp_path / "alias.key"
    link.symlink_to(deck)

    assert deck_digest(deck) == deck_digest(copied) == deck_digest(link)
    assert _digest_sidecar(cache, deck).is_file()
    assert _digest_sidecar(cache, copied).is_file()
    assert len(list((cache / "deck_digest").glob("*.json"))) == 2


def test_deck_digest_package_never_uses_sidecar(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    package = tmp_path / "deck.key"
    package.mkdir()
    (package / "Index").write_bytes(b"index")

    assert deck_digest(package) == hashlib.sha256(b"Index\0index").hexdigest()
    assert not (cache / "deck_digest").exists()


def test_deck_digest_replaces_corrupt_sidecar_atomically(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    sidecar = _digest_sidecar(cache, deck)
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text('{"digest":"BAD"}')

    expected = hashlib.sha256(b"alpha").hexdigest()
    original_replace = baseline_mod.os.replace
    replacements: list[tuple[Path, Path]] = []

    def observe_replace(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        replacements.append((source_path, destination_path))
        assert source_path.parent == destination_path.parent
        assert stat.S_IMODE(source_path.stat().st_mode) == 0o600
        return original_replace(source, destination)

    monkeypatch.setattr(baseline_mod.os, "replace", observe_replace)
    assert deck_digest(deck) == expected
    assert json.loads(sidecar.read_text())["digest"] == expected
    assert len(replacements) == 1
    assert replacements[0][1] == sidecar
    assert not list(sidecar.parent.glob(f".{sidecar.name}.*.tmp"))


def test_deck_digest_rejects_non_strict_metadata_and_uppercase_digest(
    tmp_path: Path, monkeypatch
):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = deck_digest(deck)
    sidecar = _digest_sidecar(cache, deck)
    record = json.loads(sidecar.read_text())
    record["size"] = True
    record["digest"] = expected.upper()
    sidecar.write_text(json.dumps(record))

    assert deck_digest(deck) == expected
    refreshed = json.loads(sidecar.read_text())
    assert refreshed["size"] == len(b"alpha")
    assert refreshed["digest"] == expected


def test_deck_digest_does_not_cache_mid_hash_change(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    original = baseline_mod._hash_handle

    def change_after_read(hasher, handle, chunk=1024 * 1024):
        original(hasher, handle, chunk)
        deck.write_bytes(b"bravo")

    monkeypatch.setattr(baseline_mod, "_hash_handle", change_after_read)
    deck_digest(deck)
    assert not _digest_sidecar(cache, deck).exists()


def test_deck_digest_returns_uncached_digest_when_path_disappears_after_hash(
    tmp_path: Path, monkeypatch
):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = hashlib.sha256(b"alpha").hexdigest()
    original = baseline_mod._hash_handle

    def remove_after_read(hasher, handle, chunk=1024 * 1024):
        original(hasher, handle, chunk)
        deck.unlink()

    monkeypatch.setattr(baseline_mod, "_hash_handle", remove_after_read)
    assert deck_digest(deck) == expected
    assert not _digest_sidecar(cache, deck).exists()


def test_deck_digest_propagates_final_stat_errors_other_than_disappearance(
    tmp_path: Path, monkeypatch
):
    _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    original_hash = baseline_mod._hash_handle
    original_stat = Path.stat

    def deny_after_read(hasher, handle, chunk=1024 * 1024):
        original_hash(hasher, handle, chunk)

        def denied_stat(self, *args, **kwargs):
            if self == deck:
                raise PermissionError("denied")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", denied_stat)

    monkeypatch.setattr(baseline_mod, "_hash_handle", deny_after_read)
    with pytest.raises(PermissionError, match="denied"):
        deck_digest(deck)


def test_deck_digest_cache_write_failure_is_harmless(tmp_path: Path, monkeypatch):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = hashlib.sha256(b"alpha").hexdigest()

    with monkeypatch.context() as cache_error:
        cache_error.setattr(
            baseline_mod.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(PermissionError("denied")),
        )
        assert deck_digest(deck) == expected
    assert not _digest_sidecar(cache, deck).exists()


def test_deck_digest_concurrent_cold_writers_leave_one_valid_sidecar(
    tmp_path: Path, monkeypatch
):
    cache = _cache_root(monkeypatch, tmp_path)
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    expected = hashlib.sha256(b"alpha").hexdigest()
    workers = 8
    barrier = threading.Barrier(workers)
    original_hash = baseline_mod._hash_regular_file

    def overlap_hash(path, initial_stat):
        barrier.wait(timeout=5)
        return original_hash(path, initial_stat)

    monkeypatch.setattr(baseline_mod, "_hash_regular_file", overlap_hash)
    values: list[str] = []
    errors: list[BaseException] = []

    def worker():
        try:
            values.append(deck_digest(deck))
        except BaseException as exc:  # pragma: no cover - assertion reports the captured error
            errors.append(exc)

    threads = [
        threading.Thread(target=worker) for _ in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert values == [expected] * len(threads)
    sidecar = _digest_sidecar(cache, deck)
    assert json.loads(sidecar.read_text())["digest"] == expected
    assert not list(sidecar.parent.glob(f".{sidecar.name}.*.tmp"))


def test_deck_digest_sidecar_cache_roots_are_isolated(tmp_path: Path, monkeypatch):
    root_a = tmp_path / "cache-a"
    root_b = tmp_path / "cache-b"
    deck = tmp_path / "deck.key"
    deck.write_bytes(b"alpha")
    monkeypatch.setenv(CACHE_DIR_ENV, str(root_a))
    expected = deck_digest(deck)
    sidecar_a = _digest_sidecar(root_a, deck)
    assert sidecar_a.is_file()

    calls = 0
    original_hash = baseline_mod._hash_regular_file

    def count_hash(path, initial_stat):
        nonlocal calls
        calls += 1
        return original_hash(path, initial_stat)

    monkeypatch.setattr(baseline_mod, "_hash_regular_file", count_hash)
    monkeypatch.setenv(CACHE_DIR_ENV, str(root_b))
    assert deck_digest(deck) == expected
    assert calls == 1
    sidecar_b = _digest_sidecar(root_b, deck)
    assert sidecar_b.is_file()
    assert sidecar_a != sidecar_b
    assert len(list((root_a / "deck_digest").glob("*.json"))) == 1
    assert len(list((root_b / "deck_digest").glob("*.json"))) == 1

    monkeypatch.setenv(CACHE_DIR_ENV, str(root_a))
    assert deck_digest(deck) == expected
    assert calls == 1


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

"""Pure-logic tests for the z-order patch probe (``scripts.probe_zorder_patch``).

Keynote-free. Builders (``_arch``/``_member``/``_geom``/``_shape_super``) come from
``tests/test_iwa_write.py`` — ``tests/`` is on ``sys.path`` under pytest, so a plain
module import works with no path hacking.
"""
from __future__ import annotations

import io
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_kindindex import derive_kind_index  # noqa: E402
from obed_edom.iwa_runs import _load_deck  # noqa: E402

from scripts.probe_zorder_patch import (  # noqa: E402
    permute_front,
    read_zorder,
    reorder_slide_zorder,
)
from scripts.write_gate_ab import changed_members  # noqa: E402

from test_iwa_write import _arch, _member, _shape_super  # noqa: E402

SHAPE_IDS = (200, 201, 202)


def _build_deck(path):
    """One slide (id 100), three bare shapes in z-order; ``ownedDrawables`` set equal to
    ``drawablesZOrder`` (element-identical on every A' slide, per the spec)."""
    slide_member = [
        _arch(sid, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)})
        for sid in SHAPE_IDS
    ]
    zorder = [{"identifier": i} for i in SHAPE_IDS]
    slide = _arch(100, "KN.SlideArchive",
                  {"drawablesZOrder": list(zorder), "ownedDrawables": list(zorder)})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *slide_member]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "synth.key")


def test_permute_front_rotates_back_to_front():
    assert permute_front(["a", "b", "c"]) == ["b", "c", "a"]
    assert permute_front([]) == []
    assert permute_front(["a"]) == ["a"]
    ids = ["a", "b", "c"]
    permute_front(ids)
    assert ids == ["a", "b", "c"]  # input not mutated


def test_reorder_is_value_clean_and_writes_both_lists(deck):
    z, owned = read_zorder(deck, 1)
    assert z == owned == ["200", "201", "202"]
    new_order = permute_front(z)

    result = reorder_slide_zorder(deck, 1, new_order)
    assert result["value_clean"] is True
    assert result["obj_diffs"] == 1
    assert result["header_diffs"] == 0
    assert result["member"] == "Index/Slide-100.iwa"

    assert read_zorder(deck, 1) == (new_order, new_order)


def test_reorder_moves_kind_index_to_last(deck):
    z, _owned = read_zorder(deck, 1)
    new_order = permute_front(z)
    moved_id = z[0]  # back-most, rotated to front by permute_front

    reorder_slide_zorder(deck, 1, new_order)

    objects, _idf, _fi = _load_deck(deck)
    records = derive_kind_index(objects["100"], objects)
    shapes = [r for r in records if r["kind"] == "shape"]
    max_index = max(r["kindIndex"] for r in shapes)
    moved = next(r for r in shapes if r["id"] == moved_id)
    assert moved["kindIndex"] == max_index


def test_reorder_touches_only_the_slide_member(deck, tmp_path):
    before_copy = tmp_path / "before.key"
    before_copy.write_bytes(deck.read_bytes())
    inode_before = deck.stat().st_ino

    z, _owned = read_zorder(deck, 1)
    new_order = permute_front(z)
    result = reorder_slide_zorder(deck, 1, new_order)

    assert result["value_clean"] is True
    assert deck.stat().st_ino == inode_before  # in-place O_TRUNC, not a new file
    assert changed_members(before_copy, deck) == {"Index/Slide-100.iwa"}


def test_reorder_refuses_on_id_set_mismatch(deck):
    before = deck.read_bytes()
    result = reorder_slide_zorder(deck, 1, ["200", "201", "999"])  # dropped 202, added 999
    assert result["refused"] is True
    assert deck.read_bytes() == before


def _build_spanning_deck(path):
    """Drawable 202 relocated to a second member, so slide 100's drawables span two
    files — the member-mismatch refusal path (``target_member_for_slide`` returns None,
    disagreeing with the slide archive's own member)."""
    slide_member = [
        _arch(sid, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)})
        for sid in (200, 201)
    ]
    extra_member = [
        _arch(202, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _shape_super(0, 0, 100, 50)}),
    ]
    zorder = [{"identifier": i} for i in SHAPE_IDS]
    slide = _arch(100, "KN.SlideArchive",
                  {"drawablesZOrder": list(zorder), "ownedDrawables": list(zorder)})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *slide_member]))
        z.writestr("Index/Slide-100-extra.iwa", _member(extra_member))
    path.write_bytes(buf.getvalue())
    return path


def test_reorder_refuses_on_spanning_member(tmp_path):
    deck = _build_spanning_deck(tmp_path / "spanning.key")
    before = deck.read_bytes()

    result = reorder_slide_zorder(deck, 1, ["201", "200", "202"])

    assert result["refused"] is True
    assert deck.read_bytes() == before

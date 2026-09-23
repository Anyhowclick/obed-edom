"""``patch_deck_zorder`` + read-back verify (``w-zorder-patch`` piece 2). Keynote-free."""
from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck, slide_order  # noqa: E402
from obed_edom.iwa_write import OfflineWriteCorrupted, read_slide_zorder  # noqa: E402
from obed_edom.iwa_zorder import patch_deck_zorder  # noqa: E402

from test_iwa_write import _arch, _member  # noqa: E402


def _slide(sid, zorder_ids, owned_ids=None):
    owned_ids = zorder_ids if owned_ids is None else owned_ids
    return _arch(sid, "KN.SlideArchive", {
        "drawablesZOrder": [{"identifier": i} for i in zorder_ids],
        "ownedDrawables": [{"identifier": i} for i in owned_ids],
    })


def _shape(sid):
    return _arch(sid, "TSWP.ShapeInfoArchive", {"isTextBox": False,
                 "super": {"geometry": {"position": {"x": 0, "y": 0},
                                        "size": {"width": 10, "height": 10}, "angle": 0.0},
                          "pathsource": {"bezierPathSource": {"naturalSize": {"width": 10, "height": 10}}}}})


def _build_deck(path, slides):
    """``slides``: list of (slide_id, zorder_ids, member_name); one node per slide, all
    in slide-id order. Every id referenced in a slide's zorder gets its own shape
    archive, written into the SAME member as that slide."""
    show_slides = [{"identifier": sid + 1} for sid, _ids, _m in slides]
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": show_slides}})
    nodes = [_arch(sid + 1, "KN.SlideNodeArchive", {"slide": {"identifier": sid}, "isSkipped": False})
             for sid, _ids, _m in slides]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, *nodes]))
        by_member: dict[str, list] = {}
        for sid, ids, member in slides:
            by_member.setdefault(member, []).extend([_slide(sid, ids), *[_shape(i) for i in ids]])
        for member, archives in by_member.items():
            z.writestr(member, _member(archives))
    path.write_bytes(buf.getvalue())
    return path


def test_single_slide_patch_honoured_on_reread_value_clean(tmp_path):
    deck = _build_deck(tmp_path / "one.key", [(100, [300, 301, 302], "Index/Slide-100.iwa")])
    with zipfile.ZipFile(deck) as z:
        doc_before = z.read("Index/Document.iwa")

    results = patch_deck_zorder(deck, {1: ["302", "300", "301"]})
    assert not results[1].refused
    assert results[1].applied == 1 and results[1].value_clean

    z, owned = read_slide_zorder(deck, 1)
    assert z == ["302", "300", "301"]
    assert owned == z
    with zipfile.ZipFile(deck) as zf:
        assert zf.read("Index/Document.iwa") == doc_before


def test_two_slides_patched_in_one_rewrite(tmp_path):
    deck = _build_deck(tmp_path / "two.key", [
        (100, [300, 301], "Index/Slide-100.iwa"),
        (110, [400, 401], "Index/Slide-110.iwa"),
    ])
    results = patch_deck_zorder(deck, {1: ["301", "300"], 2: ["401", "400"]})
    assert not results[1].refused and not results[2].refused
    assert read_slide_zorder(deck, 1)[0] == ["301", "300"]
    assert read_slide_zorder(deck, 2)[0] == ["401", "400"]


def test_two_slides_sharing_a_member_both_refuse_byte_identical(tmp_path):
    deck = _build_deck(tmp_path / "shared.key", [
        (100, [300, 301], "Index/Slide-shared.iwa"),
        (110, [400, 401], "Index/Slide-shared.iwa"),
    ])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["301", "300"], 2: ["401", "400"]})
    assert results[1].refused and "member shared with slide" in (results[1].reason or "")
    assert results[2].refused and "member shared with slide" in (results[2].reason or "")
    assert read_slide_zorder(deck, 1)[0] == ["300", "301"]  # untouched, original order
    assert read_slide_zorder(deck, 2)[0] == ["400", "401"]  # untouched, original order
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before  # shared member byte-identical


def test_shared_member_one_valid_one_multiset_mismatch_both_refuse_byte_identical(tmp_path):
    deck = _build_deck(tmp_path / "shared-mixed.key", [
        (100, [300, 301], "Index/Slide-shared.iwa"),
        (110, [400, 401], "Index/Slide-shared.iwa"),
    ])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["301", "300"], 2: ["400", "400"]})
    assert results[1].refused and "member shared with slide" in (results[1].reason or "")
    assert results[2].refused and "mismatch" in (results[2].reason or "")
    assert read_slide_zorder(deck, 1)[0] == ["300", "301"]  # untouched, original order
    assert read_slide_zorder(deck, 2)[0] == ["400", "401"]  # untouched, original order
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before  # shared member byte-identical


def test_multiplicity_mismatch_refuses_deck_byte_identical(tmp_path):
    deck = _build_deck(tmp_path / "multiplicity.key", [(100, [300, 300, 301], "Index/Slide-100.iwa")])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["300", "301", "301"]})
    assert results[1].refused
    assert "mismatch" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_drawable_in_another_member_refuses(tmp_path):
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 101}]}})
    node = _arch(101, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    slide = _slide(100, [300, 301])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, _shape(300)]))
        z.writestr("Index/Slide-other.iwa", _member([_shape(301)]))  # 301 lives elsewhere
    deck = tmp_path / "split.key"
    deck.write_bytes(buf.getvalue())
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["301", "300"]})
    assert results[1].refused
    assert "does not contain its drawables" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_unresolvable_drawable_id_refuses(tmp_path):
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 101}]}})
    node = _arch(101, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    slide = _slide(100, [300, 301])  # 301 has no archive anywhere
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, _shape(300)]))
    deck = tmp_path / "unresolved.key"
    deck.write_bytes(buf.getvalue())
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["301", "300"]})
    assert results[1].refused
    assert "unresolved" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_id_set_mismatch_refuses_deck_byte_identical(tmp_path):
    deck = _build_deck(tmp_path / "mismatch.key", [(100, [300, 301], "Index/Slide-100.iwa")])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["300", "999"]})
    assert results[1].refused
    assert "mismatch" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_id_length_mismatch_refuses(tmp_path):
    deck = _build_deck(tmp_path / "shortlist.key", [(100, [300, 301, 302], "Index/Slide-100.iwa")])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["300", "301"]})
    assert results[1].refused
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_owned_drawables_diverging_from_zorder_refuses(tmp_path):
    deck = _build_deck(tmp_path / "diverge.key", [])
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 101}]}})
    node = _arch(101, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    slide = _slide(100, [300, 301], owned_ids=[300])  # owned is missing 301: not a permutation
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, _shape(300), _shape(301)]))
    deck.write_bytes(buf.getvalue())
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    results = patch_deck_zorder(deck, {1: ["301", "300"]})
    assert results[1].refused
    assert "ownedDrawables" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_readback_failure_raises(tmp_path, monkeypatch):
    deck = _build_deck(tmp_path / "badread.key", [(100, [300, 301], "Index/Slide-100.iwa")])

    def _fake_read_deck_zorders(deck_arg, slide_numbers):
        objects, _id_to_file, _file_ids = _load_deck(deck_arg)
        order = slide_order(objects)
        assert list(slide_numbers) == [1]
        slide = objects[order[0][0]]
        on_disk = [str(r["identifier"]) for r in slide.get("drawablesZOrder") or []]
        assert on_disk == ["301", "300"]  # the rewrite already landed on disk
        return {1: (["300", "301"], ["300", "301"])}  # deliberately wrong order vs. what was requested

    monkeypatch.setattr("obed_edom.iwa_zorder.read_deck_zorders", _fake_read_deck_zorders)
    with pytest.raises(ValueError, match="order mismatch"):
        patch_deck_zorder(deck, {1: ["301", "300"]})


def test_rewrite_exception_leaves_deck_untouched(tmp_path, monkeypatch):
    deck = _build_deck(tmp_path / "boom.key", [(100, [300, 301], "Index/Slide-100.iwa")])
    before = hashlib.sha256(deck.read_bytes()).hexdigest()

    def _boom(_deck, _edits):
        raise RuntimeError("simulated rewrite failure")

    monkeypatch.setattr("obed_edom.iwa_zorder._rewrite_members", _boom)
    results = patch_deck_zorder(deck, {1: ["301", "300"]})
    assert results[1].refused and "rewrite failed" in (results[1].reason or "")
    assert hashlib.sha256(deck.read_bytes()).hexdigest() == before


def test_rewrite_corrupted_propagates(tmp_path, monkeypatch):
    deck = _build_deck(tmp_path / "corrupt.key", [(100, [300, 301], "Index/Slide-100.iwa")])

    def _corrupt(_deck, _edits):
        raise OfflineWriteCorrupted("simulated truncation")

    monkeypatch.setattr("obed_edom.iwa_zorder._rewrite_members", _corrupt)
    with pytest.raises(OfflineWriteCorrupted):
        patch_deck_zorder(deck, {1: ["301", "300"]})


def test_readback_loads_deck_once_for_many_slides(tmp_path, monkeypatch):
    """The read-back decodes the whole deck; it must happen once per patch, not once per slide."""
    from obed_edom import iwa_write

    deck = _build_deck(tmp_path / "three.key", [
        (100, [300, 301], "Index/Slide-100.iwa"),
        (110, [400, 401], "Index/Slide-110.iwa"),
        (120, [500, 501], "Index/Slide-120.iwa"),
    ])
    calls = []
    real_load = iwa_write._load_deck

    def counting_load(path, *args, **kwargs):
        calls.append(path)
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr(iwa_write, "_load_deck", counting_load)
    results = patch_deck_zorder(deck, {1: ["301", "300"], 2: ["401", "400"], 3: ["501", "500"]})
    assert not any(r.refused for r in results.values())
    assert len(calls) == 1


def test_read_deck_zorders_reads_each_slide_and_rejects_out_of_range(tmp_path):
    from obed_edom.iwa_write import read_deck_zorders

    deck = tmp_path / "distinct.key"
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 101}, {"identifier": 111}]}})
    nodes = [_arch(sid + 1, "KN.SlideNodeArchive", {"slide": {"identifier": sid}, "isSkipped": False})
             for sid in (100, 110)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, *nodes]))
        z.writestr("Index/Slide-100.iwa", _member([_slide(100, [300, 301], owned_ids=[301, 300]),
                                                   _shape(300), _shape(301)]))
        z.writestr("Index/Slide-110.iwa", _member([_slide(110, [400, 401, 402], owned_ids=[402, 400]),
                                                   _shape(400), _shape(401), _shape(402)]))
    deck.write_bytes(buf.getvalue())

    assert read_deck_zorders(deck, [2, 1]) == {
        1: (["300", "301"], ["301", "300"]),
        2: (["400", "401", "402"], ["402", "400"]),
    }
    assert read_slide_zorder(deck, 2) == (["400", "401", "402"], ["402", "400"])
    with pytest.raises(ValueError, match="slide 3 out of range"):
        read_deck_zorders(deck, [1, 3])


def test_read_deck_zorders_load_failure_raises_runtime_error_with_hint(tmp_path, monkeypatch):
    from obed_edom import iwa_write

    deck = tmp_path / "broken.key"

    def boom(_path):
        raise KeyError("undecodable member")

    monkeypatch.setattr(iwa_write, "_load_deck", boom)
    with pytest.raises(RuntimeError) as info:
        iwa_write.read_deck_zorders(deck, [1])
    msg = str(info.value)
    assert f"_load_deck failed on {deck}" in msg
    assert "keynote_parser" in msg and "check the installed keynote_parser version" in msg
    assert isinstance(info.value.__cause__, KeyError)


def test_all_refused_patch_skips_readback(tmp_path, monkeypatch):
    deck = _build_deck(tmp_path / "shared.key", [
        (100, [300, 301], "Index/Slide-shared.iwa"),
        (110, [400, 401], "Index/Slide-shared.iwa"),
    ])

    def must_not_read(*_a, **_k):
        raise AssertionError("read-back must not run when every slide is refused")

    monkeypatch.setattr("obed_edom.iwa_zorder.read_deck_zorders", must_not_read)
    results = patch_deck_zorder(deck, {1: ["301", "300"], 2: ["401", "400"]})
    assert results[1].refused and results[2].refused

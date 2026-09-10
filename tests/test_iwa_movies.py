"""Offline poster-frame patch tests (obed_edom.iwa_movies). Everything here runs
WITHOUT Keynote, against a tiny but REAL ``.key`` built the same way as
``tests/test_iwa_write.py`` (synthetic IWA members serialized through
``keynote_parser.codec.IWAFile``).
"""
from __future__ import annotations

import copy
import io
import re
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from keynote_parser.codec import IWAFile, import_version  # noqa: E402

from obed_edom.iwa_movies import movie_archives, patch_movie_posters, plan_movie_posters  # noqa: E402
from obed_edom.iwa_runs import _load_deck  # noqa: E402

_ID_NAME_MAP, _, _ = import_version()
_INV_ID = {c.DESCRIPTOR.full_name: t for t, c in _ID_NAME_MAP.items()}
_INV_CLS = {c.DESCRIPTOR.full_name: c for t, c in _ID_NAME_MAP.items()}
_ARCHIVE_INFO = "TSP.ArchiveInfo"
_MESSAGE_INFO = "TSP.MessageInfo"


def _scalar_default(field):
    ct = field.cpp_type
    if ct in (1, 2, 3, 4):
        return 0
    if ct in (5, 6):
        return 0.0
    if ct == 7:
        return False
    if ct == 8:
        return field.enum_type.values[0].number
    if ct == 9:
        return ""
    return {}


def _fill_path(d, msg_cls, dotted):
    parts = dotted.split(".")
    desc = msg_cls.DESCRIPTOR
    for i, part in enumerate(parts):
        field = desc.fields_by_name[part]
        if i == len(parts) - 1:
            if field.message_type is not None:
                d[part] = d.get(part) or {}
            else:
                d.setdefault(part, _scalar_default(field))
        else:
            d = d.setdefault(part, {})
            desc = field.message_type


def _archive_dict(ident, pbtype, obj):
    o = dict(obj)
    o["_pbtype"] = pbtype
    return {
        "header": {
            "_pbtype": _ARCHIVE_INFO,
            "identifier": ident,
            "messageInfos": [{"_pbtype": _MESSAGE_INFO, "type": _INV_ID[pbtype], "identifier": ident}],
        },
        "objects": [o],
    }


def _complete(pbtype, obj):
    cls = _INV_CLS[pbtype]
    obj = copy.deepcopy(obj)
    for _ in range(60):
        try:
            IWAFile.from_dict({"chunks": [{"archives": [_archive_dict(1, pbtype, obj)]}]}).to_buffer()
            return obj
        except Exception as exc:  # noqa: BLE001 — the message names the missing fields
            match = re.search(r"missing required fields: ([^\n']+)", str(exc))
            if not match:
                raise
            for name in match.group(1).split(","):
                _fill_path(obj, cls, name.strip())
    raise RuntimeError("too many required fields to fill")


def _arch(ident, pbtype, obj):
    return _archive_dict(ident, pbtype, _complete(pbtype, obj))


def _member(archives):
    return IWAFile.from_dict({"chunks": [{"archives": archives}]}).to_buffer()


def _geom(x, y, w, h, angle=0.0):
    return {"geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}, "angle": angle}}


# Landmark-sized reveal movie (matches a `_place_churches` item), a full-width
# background fly movie (`map:True`, first-frame poster already correct), plus an
# unrelated image archive.
_LANDMARK_FRAME = (400.0, 300.0, 60.0, 80.0)
_BG_FRAME = (0.0, 0.0, 7680.0, 1080.0)


def _build_movies_deck(path, *, extra_movie_same_frame=False):
    x, y, w, h = _LANDMARK_FRAME
    landmark = _arch(
        300, "TSD.MovieArchive",
        {"super": _geom(x, y, w, h), "posterTime": 0.0, "startTime": 0.0, "endTime": 2.0,
         "naturalSize": {"width": w, "height": h}},
    )
    bx, by, bw, bh = _BG_FRAME
    background = _arch(
        310, "TSD.MovieArchive",
        {"super": _geom(bx, by, bw, bh), "posterTime": 0.0, "startTime": 0.0, "endTime": 30.0,
         "naturalSize": {"width": bw, "height": bh}},
    )
    image = _arch(
        320, "TSD.ImageArchive",
        {"super": _geom(10, 10, 40, 40), "originalSize": {"width": 40.0, "height": 40.0}},
    )
    zorder = [{"identifier": 300}, {"identifier": 310}, {"identifier": 320}]
    archives = [landmark, background, image]
    if extra_movie_same_frame:
        dup = _arch(
            301, "TSD.MovieArchive",
            {"super": _geom(x, y, w, h), "posterTime": 0.0, "startTime": 0.0, "endTime": 2.0,
             "naturalSize": {"width": w, "height": h}},
        )
        archives.append(dup)
        zorder.append({"identifier": 301})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": zorder})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *archives]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_movies_deck(tmp_path / "movies.key")


def _target(frame, poster_time, name="reveal"):
    x, y, w, h = frame
    return {"x": x, "y": y, "w": w, "h": h, "posterTime": poster_time, "name": name}


def test_movie_archives_reports_both_with_composed_frames(deck):
    archives = movie_archives(deck)
    assert len(archives) == 2
    by_id = {a["id"]: a for a in archives}
    assert (by_id["300"]["x"], by_id["300"]["y"], by_id["300"]["w"], by_id["300"]["h"]) == _LANDMARK_FRAME
    assert (by_id["310"]["x"], by_id["310"]["y"], by_id["310"]["w"], by_id["310"]["h"]) == _BG_FRAME
    assert by_id["300"]["posterTime"] == 0.0


def test_plan_picks_only_the_landmark_sized_movie(deck):
    plan = plan_movie_posters(deck, [_target(_LANDMARK_FRAME, 1.5)])
    assert plan["refused"] is False
    assert plan["posters"] == {"300": 1.5}


def test_plan_refuses_a_target_matching_no_archive(deck):
    plan = plan_movie_posters(deck, [_target((999, 999, 10, 10), 1.5)])
    assert plan["refused"] is True


def test_plan_refuses_an_ambiguous_target(tmp_path):
    deck = _build_movies_deck(tmp_path / "movies.key", extra_movie_same_frame=True)
    plan = plan_movie_posters(deck, [_target(_LANDMARK_FRAME, 1.5)])
    assert plan["refused"] is True
    assert "matched 2" in plan["reason"]


def test_plan_refuses_two_targets_claiming_the_same_archive(deck):
    # Two distinct reveal items whose planned frames both land within tolerance of
    # the sole landmark-sized archive must not silently let the second overwrite
    # the first in `posters` -- one-to-one or refuse.
    x, y, w, h = _LANDMARK_FRAME
    targets = [
        _target((x, y, w, h), 1.5, name="a"),
        _target((x + 0.2, y, w, h), 2.5, name="b"),
    ]
    plan = plan_movie_posters(deck, targets)
    assert plan["refused"] is True
    assert plan["posters"] == {}
    assert "300" in plan["reason"]


def test_patch_writes_posterTime_and_reread_matches(deck):
    before = deck.read_bytes()
    result = patch_movie_posters(deck, {"300": 1.5})
    assert result["refused"] is False
    assert result["applied"] == 1
    archives = {a["id"]: a for a in movie_archives(deck)}
    assert archives["300"]["posterTime"] == 1.5
    assert archives["310"]["posterTime"] == 0.0
    assert deck.read_bytes() != before


def test_patch_leaves_other_members_and_archives_byte_identical(deck):
    objects_before, _, _ = _load_deck(deck)
    image_before = objects_before["320"]
    bg_before = objects_before["310"]
    with zipfile.ZipFile(deck) as zf:
        names_before = set(zf.namelist())
        doc_before = zf.read("Index/Document.iwa")

    patch_movie_posters(deck, {"300": 2.0})

    objects_after, _, _ = _load_deck(deck)
    assert objects_after["320"] == image_before
    assert objects_after["310"] == bg_before
    with zipfile.ZipFile(deck) as zf:
        assert set(zf.namelist()) == names_before
        assert zf.read("Index/Document.iwa") == doc_before


def test_patch_preserves_inode(deck):
    inode_before = deck.stat().st_ino
    patch_movie_posters(deck, {"300": 1.5})
    assert deck.stat().st_ino == inode_before


def test_patch_refuses_a_target_id_pointing_at_a_non_movie_archive(deck):
    before = deck.read_bytes()
    result = patch_movie_posters(deck, {"320": 1.5})
    assert result["refused"] is True
    assert deck.read_bytes() == before


def test_patch_empty_posters_is_a_noop(deck):
    result = patch_movie_posters(deck, {})
    assert result == {"refused": False, "reason": None, "touched": [], "applied": 0}

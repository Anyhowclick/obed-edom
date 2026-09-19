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

from obed_edom.iwa_movies import (  # noqa: E402
    ClipTiming,
    _patch_archive_fields,
    bare_source_build_ins,
    movie_archives,
    movie_autoplay_state,
    patch_clip_start_timing,
    patch_movie_autoplay,
    patch_movie_posters,
    plan_movie_autoplay,
    plan_movie_posters,
)
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


def _build_effect(effect, animation_type="In"):
    return {
        "animationAttributes": {
            "animationType": animation_type,
            "effect": effect,
            "duration": 0.5,
            "direction": 0,
            "delay": 0.0,
            "randomNumberSeed": 1,
            "writingDirectionIsRtl": False,
        },
    }


# Landmark-sized reveal movie (matches a `_place_churches` item), a full-width
# background fly movie (`map:True`, first-frame poster already correct), plus an
# unrelated image archive. The landmark movie carries a single apple:movie-start
# build/chunk, same shape as a real reveal slide; the background movie has none.
_LANDMARK_FRAME = (400.0, 300.0, 60.0, 80.0)
_BG_FRAME = (0.0, 0.0, 7680.0, 1080.0)


def _build_movies_deck(
    path,
    *,
    extra_movie_same_frame=False,
    extra_build_for_landmark=False,
    orphan_chunk_for_landmark=False,
    chunk_in_other_member=False,
):
    x, y, w, h = _LANDMARK_FRAME
    landmark = _arch(
        300, "TSD.MovieArchive",
        {"super": _geom(x, y, w, h), "posterTime": 0.0, "startTime": 0.0, "endTime": 2.0,
         "naturalSize": {"width": w, "height": h}, "playsAcrossSlides": True},
    )
    bx, by, bw, bh = _BG_FRAME
    background = _arch(
        310, "TSD.MovieArchive",
        {"super": _geom(bx, by, bw, bh), "posterTime": 0.0, "startTime": 0.0, "endTime": 30.0,
         "naturalSize": {"width": bw, "height": bh}, "playsAcrossSlides": True},
    )
    image = _arch(
        320, "TSD.ImageArchive",
        {"super": _geom(10, 10, 40, 40), "originalSize": {"width": 40.0, "height": 40.0}},
    )
    zorder = [{"identifier": 300}, {"identifier": 310}, {"identifier": 320}]
    archives = [landmark, background, image]
    build900 = _arch(
        900, "KN.BuildArchive",
        {"drawable": {"identifier": 300}, "delivery": "All at Once", "duration": 0.0,
         "attributes": _build_effect("apple:movie-start"), "chunkIdSeed": 1},
    )
    chunk910 = _arch(
        910, "KN.BuildChunkArchive",
        {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": False, "referent": True,
         "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 1},
         "buildId": {"lower": "1", "upper": "1"}},
    )
    archives.extend([build900])
    chunk_archives = [chunk910]
    build_refs = [{"identifier": 900}]
    chunk_refs = [{"identifier": 910}]
    if orphan_chunk_for_landmark:
        # Same apple:movie-start build, but absent from the slide's buildChunks: an
        # inactive archive this repo deliberately leaves in place, never the patch target.
        chunk_archives.append(
            _arch(
                912, "KN.BuildChunkArchive",
                {"build": {"identifier": 900}, "delay": 0.0, "duration": 0.5, "automatic": False, "referent": True,
                 "buildChunkIdentifier": {"buildId": {"lower": "1", "upper": "1"}, "buildChunkId": 2},
                 "buildId": {"lower": "1", "upper": "1"}},
            )
        )
    if extra_build_for_landmark:
        build901 = _arch(
            901, "KN.BuildArchive",
            {"drawable": {"identifier": 300}, "delivery": "All at Once", "duration": 0.0,
             "attributes": _build_effect("apple:movie-start"), "chunkIdSeed": 1},
        )
        chunk911 = _arch(
            911, "KN.BuildChunkArchive",
            {"build": {"identifier": 901}, "delay": 0.0, "duration": 0.5, "automatic": False, "referent": True,
             "buildChunkIdentifier": {"buildId": {"lower": "2", "upper": "1"}, "buildChunkId": 1},
             "buildId": {"lower": "2", "upper": "1"}},
        )
        archives.append(build901)
        chunk_archives.append(chunk911)
        build_refs.append({"identifier": 901})
        chunk_refs.append({"identifier": 911})
    if extra_movie_same_frame:
        dup = _arch(
            301, "TSD.MovieArchive",
            {"super": _geom(x, y, w, h), "posterTime": 0.0, "startTime": 0.0, "endTime": 2.0,
             "naturalSize": {"width": w, "height": h}},
        )
        archives.append(dup)
        zorder.append({"identifier": 301})
    slide = _arch(
        100, "KN.SlideArchive",
        {"drawablesZOrder": zorder, "builds": build_refs, "buildChunks": chunk_refs},
    )
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        if chunk_in_other_member:
            z.writestr("Index/Slide-100.iwa", _member([slide, *archives]))
            z.writestr("Index/Slide-101.iwa", _member(chunk_archives))
        else:
            z.writestr("Index/Slide-100.iwa", _member([slide, *archives, *chunk_archives]))
    path.write_bytes(buf.getvalue())
    return path


@pytest.fixture()
def deck(tmp_path):
    return _build_movies_deck(tmp_path / "movies.key")


def _target(frame, poster_time, name="reveal", slide_index=1):
    x, y, w, h = frame
    return {"x": x, "y": y, "w": w, "h": h, "posterTime": poster_time, "name": name, "slideIndex": slide_index}


def test_movie_archives_reports_both_with_composed_frames(deck):
    archives = movie_archives(deck)
    assert len(archives) == 2
    by_id = {a["id"]: a for a in archives}
    assert (by_id["300"]["x"], by_id["300"]["y"], by_id["300"]["w"], by_id["300"]["h"]) == _LANDMARK_FRAME
    assert (by_id["310"]["x"], by_id["310"]["y"], by_id["310"]["w"], by_id["310"]["h"]) == _BG_FRAME
    assert by_id["300"]["posterTime"] == 0.0
    assert by_id["300"]["slideIndex"] == 1
    assert by_id["300"]["slideId"] == "100"
    assert by_id["310"]["slideIndex"] == 1
    assert by_id["310"]["slideId"] == "100"


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


def test_patch_archive_fields_refuses_two_patches_for_one_archive(deck):
    # The docstring's "the same archive id may not appear twice" is enforced: a second
    # patch for the same id would otherwise silently replace the first one's fields.
    before = deck.read_bytes()
    result = _patch_archive_fields(
        deck,
        [
            ("300", "TSD.MovieArchive", {"posterTime": 1.5}),
            ("300", "TSD.MovieArchive", {"startTime": 2.5}),
        ],
    )
    assert result == {
        "refused": True, "reason": "300 appears in more than one patch", "touched": [], "applied": 0,
    }
    assert deck.read_bytes() == before


def _autoplay_target(frame, name="reveal", slide_index=1):
    x, y, w, h = frame
    return {"x": x, "y": y, "w": w, "h": h, "name": name, "slideIndex": slide_index}


def test_plan_autoplay_picks_only_the_landmark_sized_movie(deck):
    plan = plan_movie_autoplay(deck, [_autoplay_target(_LANDMARK_FRAME)])
    assert plan["refused"] is False
    assert plan["ids"] == ["300"]


def test_plan_autoplay_refuses_a_target_matching_no_archive(deck):
    plan = plan_movie_autoplay(deck, [_autoplay_target((999, 999, 10, 10))])
    assert plan["refused"] is True


def test_plan_autoplay_refuses_an_ambiguous_target(tmp_path):
    deck = _build_movies_deck(tmp_path / "movies.key", extra_movie_same_frame=True)
    plan = plan_movie_autoplay(deck, [_autoplay_target(_LANDMARK_FRAME)])
    assert plan["refused"] is True
    assert "matched 2" in plan["reason"]


def test_patch_autoplay_flips_chunk_automatic_and_clears_plays_across_slides(deck):
    before = deck.read_bytes()
    result = patch_movie_autoplay(deck, ["300"])
    assert result["refused"] is False
    assert result["applied"] == 1
    objects, _, _ = _load_deck(deck)
    assert objects["910"]["automatic"] is True
    assert objects["300"]["playsAcrossSlides"] is False
    archives = {a["id"]: a for a in movie_archives(deck)}
    assert archives["310"]["playsAcrossSlides"] is True
    assert deck.read_bytes() != before


def test_patch_autoplay_leaves_other_members_and_archives_byte_identical(deck):
    objects_before, _, _ = _load_deck(deck)
    image_before = objects_before["320"]
    bg_before = objects_before["310"]
    build_before = objects_before["900"]
    with zipfile.ZipFile(deck) as zf:
        names_before = set(zf.namelist())
        doc_before = zf.read("Index/Document.iwa")

    patch_movie_autoplay(deck, ["300"])

    objects_after, _, _ = _load_deck(deck)
    assert objects_after["320"] == image_before
    assert objects_after["310"] == bg_before
    assert objects_after["900"] == build_before
    with zipfile.ZipFile(deck) as zf:
        assert set(zf.namelist()) == names_before
        assert zf.read("Index/Document.iwa") == doc_before


def test_patch_autoplay_refuses_a_movie_with_no_build_chunk(deck):
    before = deck.read_bytes()
    result = patch_movie_autoplay(deck, ["310"])
    assert result["refused"] is True
    assert "0 listed apple:movie-start build chunk" in result["reason"]
    assert deck.read_bytes() == before


def test_patch_autoplay_refuses_a_movie_with_ambiguous_build_chunks(tmp_path):
    deck = _build_movies_deck(tmp_path / "movies.key", extra_build_for_landmark=True)
    before = deck.read_bytes()
    result = patch_movie_autoplay(deck, ["300"])
    assert result["refused"] is True
    assert "2 listed apple:movie-start build chunk" in result["reason"]
    assert deck.read_bytes() == before


def test_patch_autoplay_refuses_a_target_id_pointing_at_a_non_movie_archive(deck):
    before = deck.read_bytes()
    result = patch_movie_autoplay(deck, ["320"])
    assert result["refused"] is True
    assert deck.read_bytes() == before


def test_patch_autoplay_empty_ids_is_a_noop(deck):
    result = patch_movie_autoplay(deck, [])
    assert result == {"refused": False, "reason": None, "touched": [], "applied": 0}


def test_patch_autoplay_ignores_an_orphan_chunk_on_the_same_build(tmp_path):
    deck = _build_movies_deck(tmp_path / "movies.key", orphan_chunk_for_landmark=True)
    result = patch_movie_autoplay(deck, ["300"])
    assert result["refused"] is False
    objects, _, _ = _load_deck(deck)
    assert objects["910"]["automatic"] is True
    assert objects["912"]["automatic"] is False


def test_patch_autoplay_refuses_a_chunk_in_another_member(tmp_path):
    deck = _build_movies_deck(tmp_path / "movies.key", chunk_in_other_member=True)
    before = deck.read_bytes()
    result = patch_movie_autoplay(deck, ["300"])
    assert result["refused"] is True
    assert "another member" in result["reason"]
    assert deck.read_bytes() == before


def test_movie_autoplay_state_reads_the_listed_chunk(deck):
    patch_movie_autoplay(deck, ["300"])
    state = movie_autoplay_state(deck, ["300"])
    assert state["300"] == {
        "playsAcrossSlides": False,
        "automatic": True,
        "referent": True,
        "delay": 0.0,
        "chunkPos": 0,
    }


def _timing_movie(ident, frame, *, plays_across_slides):
    x, y, w, h = frame
    return _arch(
        ident, "TSD.MovieArchive",
        {"super": _geom(x, y, w, h), "posterTime": 0.0, "startTime": 0.0, "endTime": 2.0,
         "naturalSize": {"width": w, "height": h}, "playsAcrossSlides": plays_across_slides},
    )


def _timing_build_chunk(
    movie_ident, build_ident, chunk_ident, *, automatic, referent,
    effect="apple:movie-start", animation_type="In", chunk_duration=0.5,
):
    build = _arch(
        build_ident, "KN.BuildArchive",
        {"drawable": {"identifier": movie_ident}, "delivery": "All at Once", "duration": 0.0,
         "attributes": _build_effect(effect, animation_type), "chunkIdSeed": 1},
    )
    chunk = _arch(
        chunk_ident, "KN.BuildChunkArchive",
        {"build": {"identifier": build_ident}, "delay": 0.0, "duration": chunk_duration,
         "automatic": automatic, "referent": referent,
         "buildChunkIdentifier": {"buildId": {"lower": str(build_ident), "upper": "1"}, "buildChunkId": 1},
         "buildId": {"lower": str(build_ident), "upper": "1"}},
    )
    return build, chunk


def _build_timing_deck(
    path, n_clips, *, initial_chunk_order=None, no_chunk_for=None, dup_chunk_for=None,
    animation_types=None, extra_build_for=None, chunk_durations=None, effects=None,
    chunk_delays=None,
):
    """``n_clips`` inserted DSK clips (300, 301, ...), each with its own not-yet-timed
    ``apple:movie-start`` build/chunk (initial flags ``automatic False, referent True``,
    same as Keynote's own non-deterministic auto-add). ``initial_chunk_order`` -- indices
    into range(n_clips) -- scrambles the slide's starting ``buildChunks`` order so a
    reorder test can prove `patch_clip_start_timing` actually moves them.
    ``animation_types`` (index -> e.g. ``"Out"``) overrides a clip build's
    ``animationType``; ``extra_build_for`` lists a SECOND, chunkless build for that clip
    on the slide; ``chunk_durations`` (index -> seconds) overrides a clip chunk's own
    ``duration`` (Keynote auto-creates it at 0.0 even when the build carries 0.5)."""
    frame = (400.0, 300.0, 60.0, 80.0)
    archives = []
    zorder = []
    build_refs = []
    chunk_refs_by_index = {}
    extra_chunk_refs = []
    movie_ids = []
    for i in range(n_clips):
        movie_ident = 300 + i
        movie_ids.append(str(movie_ident))
        archives.append(_timing_movie(movie_ident, frame, plays_across_slides=True))
        zorder.append({"identifier": movie_ident})
        if no_chunk_for == i:
            continue
        build_ident = 900 + i * 20
        chunk_ident = 910 + i * 20
        build, chunk = _timing_build_chunk(
            movie_ident, build_ident, chunk_ident, automatic=False, referent=True,
            effect=(effects or {}).get(i, "apple:movie-start"),
            animation_type=(animation_types or {}).get(i, "In"),
            chunk_duration=(chunk_durations or {}).get(i, 0.5),
        )
        chunk["objects"][0]["delay"] = (chunk_delays or {}).get(i, 0.0)
        archives.append(build)
        archives.append(chunk)
        build_refs.append({"identifier": build_ident})
        chunk_refs_by_index[i] = chunk_ident
        if extra_build_for == i:
            extra_build = _arch(
                build_ident + 5, "KN.BuildArchive",
                {"drawable": {"identifier": movie_ident}, "delivery": "All at Once", "duration": 0.0,
                 "attributes": _build_effect("apple:dissolve"), "chunkIdSeed": 1},
            )
            archives.append(extra_build)
            build_refs.append({"identifier": build_ident + 5})
        if dup_chunk_for == i:
            dup_chunk_ident = chunk_ident + 1
            dup_chunk = _arch(
                dup_chunk_ident, "KN.BuildChunkArchive",
                {"build": {"identifier": build_ident}, "delay": 0.0, "duration": 0.5,
                 "automatic": False, "referent": True,
                 "buildChunkIdentifier": {"buildId": {"lower": str(build_ident), "upper": "1"}, "buildChunkId": 2},
                 "buildId": {"lower": str(build_ident), "upper": "1"}},
            )
            archives.append(dup_chunk)
            extra_chunk_refs.append({"identifier": dup_chunk_ident})

    order = initial_chunk_order if initial_chunk_order is not None else list(range(n_clips))
    chunk_refs = [{"identifier": chunk_refs_by_index[i]} for i in order if i in chunk_refs_by_index]
    chunk_refs.extend(extra_chunk_refs)

    image = _arch(320, "TSD.ImageArchive", {"super": _geom(10, 10, 40, 40), "originalSize": {"width": 40.0, "height": 40.0}})
    archives.append(image)
    zorder.append({"identifier": 320})

    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": zorder, "builds": build_refs, "buildChunks": chunk_refs})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *archives]))
    path.write_bytes(buf.getvalue())
    return path, movie_ids


def test_clip_timing_single_movie_after_transition(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 1)
    before = deck.read_bytes()
    state = patch_clip_start_timing(deck, {"100": [ClipTiming(movie_ids[0], "after_transition")]})
    assert state == {
        "100": {
            movie_ids[0]: {"playsAcrossSlides": False, "automatic": True, "referent": True, "delay": 0.0, "chunkPos": 0}
        }
    }
    assert deck.read_bytes() != before


def test_clip_timing_continuity_reorders_with_build_1_after_chunk_0(tmp_path):
    # Two continuity clips, chunk 0 initially belongs to the SECOND clip -- proves the
    # reorder actually runs (leftmost/after_transition clip must land at position 0).
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2, initial_chunk_order=[1, 0])
    plan = [ClipTiming(movie_ids[0], "after_transition"), ClipTiming(movie_ids[1], "with_build_1")]
    state = patch_clip_start_timing(deck, {"100": plan})
    assert state["100"][movie_ids[0]] == {
        "playsAcrossSlides": False, "automatic": True, "referent": True, "delay": 0.0, "chunkPos": 0,
    }
    assert state["100"][movie_ids[1]] == {
        "playsAcrossSlides": False, "automatic": True, "referent": False, "delay": 0.0, "chunkPos": 1,
    }
    objects, _, _ = _load_deck(deck)
    chunk_refs = [str((r or {}).get("identifier")) for r in objects["100"].get("buildChunks") or []]
    assert chunk_refs == ["910", "930"]
    # duration is Keynote's own and must never be touched
    assert objects["910"]["duration"] == 0.5
    assert objects["930"]["duration"] == 0.5


def test_clip_timing_cascade_after_previous(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 3, initial_chunk_order=[2, 0, 1])
    plan = [
        ClipTiming(movie_ids[0], "after_transition"),
        ClipTiming(movie_ids[1], "after_previous"),
        ClipTiming(movie_ids[2], "after_previous"),
    ]
    state = patch_clip_start_timing(deck, {"100": plan})
    assert [state["100"][m]["chunkPos"] for m in movie_ids] == [0, 1, 2]
    assert [state["100"][m]["automatic"] for m in movie_ids] == [True, True, True]
    assert [state["100"][m]["referent"] for m in movie_ids] == [True, True, True]
    objects, _, _ = _load_deck(deck)
    chunk_refs = [str((r or {}).get("identifier")) for r in objects["100"].get("buildChunks") or []]
    assert chunk_refs == ["910", "930", "950"]


def test_clip_timing_sets_plays_across_slides_false_on_every_listed_movie(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    plan = [ClipTiming(movie_ids[0], "after_transition"), ClipTiming(movie_ids[1], "with_build_1")]
    patch_clip_start_timing(deck, {"100": plan})
    objects, _, _ = _load_deck(deck)
    assert objects[movie_ids[0]]["playsAcrossSlides"] is False
    assert objects[movie_ids[1]]["playsAcrossSlides"] is False


def test_clip_timing_refuses_a_movie_with_no_build_chunk(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 1, no_chunk_for=0)
    before = deck.read_bytes()
    with pytest.raises(ValueError, match="0 listed apple:movie-start build chunk"):
        patch_clip_start_timing(deck, {"100": [ClipTiming(movie_ids[0], "after_transition")]})
    assert deck.read_bytes() == before


def test_clip_timing_refuses_a_movie_with_ambiguous_build_chunks(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 1, dup_chunk_for=0)
    before = deck.read_bytes()
    with pytest.raises(ValueError, match="2 listed apple:movie-start build chunk"):
        patch_clip_start_timing(deck, {"100": [ClipTiming(movie_ids[0], "after_transition")]})
    assert deck.read_bytes() == before


def test_clip_timing_leaves_duration_and_ids_untouched(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2, initial_chunk_order=[1, 0])
    objects_before, _, _ = _load_deck(deck)
    plan = [ClipTiming(movie_ids[0], "after_transition"), ClipTiming(movie_ids[1], "with_build_1")]
    patch_clip_start_timing(deck, {"100": plan})
    objects_after, _, _ = _load_deck(deck)
    for oid in ("910", "930", "900", "920"):
        assert objects_after[oid]["_pbtype"] == objects_before[oid]["_pbtype"]
    assert objects_after["910"]["duration"] == objects_before["910"]["duration"] == 0.5
    assert objects_after["930"]["duration"] == objects_before["930"]["duration"] == 0.5
    assert objects_after["900"]["delivery"] == objects_before["900"]["delivery"]


def test_clip_timing_refuses_non_movie_build_chunks(tmp_path):
    # A clip slide is expected to carry only movie-start chunks (gold overlays are
    # static). A non-movie build chunk (810 before, 811 between the movie chunks) makes
    # the retiming undefined -- front-loading the clips would silently shift 810/811 to
    # later positions and change their meaning -- so the write is refused, deck untouched.
    frame = (400.0, 300.0, 60.0, 80.0)
    movie300 = _timing_movie(300, frame, plays_across_slides=True)
    movie301 = _timing_movie(301, frame, plays_across_slides=True)
    build900, chunk910 = _timing_build_chunk(300, 900, 910, automatic=False, referent=True)
    build920, chunk930 = _timing_build_chunk(301, 920, 930, automatic=False, referent=True)
    image = _arch(320, "TSD.ImageArchive", {"super": _geom(10, 10, 40, 40), "originalSize": {"width": 40.0, "height": 40.0}})
    build800 = _arch(
        800, "KN.BuildArchive",
        {"drawable": {"identifier": 320}, "delivery": "All at Once", "duration": 0.0,
         "attributes": _build_effect("apple:shape-appear"), "chunkIdSeed": 1},
    )
    chunk810 = _arch(
        810, "KN.BuildChunkArchive",
        {"build": {"identifier": 800}, "delay": 0.0, "duration": 0.3, "automatic": True, "referent": True,
         "buildChunkIdentifier": {"buildId": {"lower": "800", "upper": "1"}, "buildChunkId": 1},
         "buildId": {"lower": "800", "upper": "1"}},
    )
    build801 = _arch(
        801, "KN.BuildArchive",
        {"drawable": {"identifier": 320}, "delivery": "All at Once", "duration": 0.0,
         "attributes": _build_effect("apple:shape-appear"), "chunkIdSeed": 1},
    )
    chunk811 = _arch(
        811, "KN.BuildChunkArchive",
        {"build": {"identifier": 801}, "delay": 0.0, "duration": 0.3, "automatic": True, "referent": True,
         "buildChunkIdentifier": {"buildId": {"lower": "801", "upper": "1"}, "buildChunkId": 1},
         "buildId": {"lower": "801", "upper": "1"}},
    )
    zorder = [{"identifier": 300}, {"identifier": 301}, {"identifier": 320}]
    build_refs = [{"identifier": 900}, {"identifier": 800}, {"identifier": 920}, {"identifier": 801}]
    chunk_refs = [{"identifier": 810}, {"identifier": 930}, {"identifier": 811}, {"identifier": 910}]
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": zorder, "builds": build_refs, "buildChunks": chunk_refs})
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    archives = [movie300, movie301, build900, chunk910, build920, chunk930, image, build800, chunk810, build801, chunk811]
    deck = tmp_path / "timing.key"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node]))
        z.writestr("Index/Slide-100.iwa", _member([slide, *archives]))
    deck.write_bytes(buf.getvalue())

    before = deck.read_bytes()
    plan = [ClipTiming("300", "after_transition"), ClipTiming("301", "with_build_1")]
    with pytest.raises(ValueError, match="non-clip build chunk"):
        patch_clip_start_timing(deck, {"100": plan})
    assert deck.read_bytes() == before


def test_clip_timing_refuses_two_after_transition(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    before = deck.read_bytes()
    plan = [ClipTiming(movie_ids[0], "after_transition"), ClipTiming(movie_ids[1], "after_transition")]
    with pytest.raises(ValueError, match="exactly one after_transition"):
        patch_clip_start_timing(deck, {"100": plan})
    assert deck.read_bytes() == before


def test_clip_timing_refuses_unknown_mode(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 1)
    before = deck.read_bytes()
    plan = [ClipTiming(movie_ids[0], "sideways")]
    with pytest.raises(ValueError, match="unknown clip timing mode"):
        patch_clip_start_timing(deck, {"100": plan})
    assert deck.read_bytes() == before


# --------------------------------------------------------------------------
# Stacked upper clip: the SOURCE build-in rewritten onto its movie-start build
# (plan §4 item 28; FRC Wall slide 50 = apple:dissolve In 0.5s, With Build 1 + 8s)
# --------------------------------------------------------------------------
def _frc50_plan(movie_ids, *, duration=0.5):
    return [
        ClipTiming(movie_ids[0], "after_transition"),
        ClipTiming(
            movie_ids[1], "with_previous", delay=8.0, build_in="apple:dissolve", build_in_duration=duration
        ),
    ]


def test_clip_timing_writes_the_source_build_in_on_the_upper_clip(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    state = patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids)})

    assert state["100"][movie_ids[0]] == {
        "playsAcrossSlides": False, "automatic": True, "referent": True, "delay": 0.0, "chunkPos": 0,
    }
    assert state["100"][movie_ids[1]] == {
        "playsAcrossSlides": False, "automatic": True, "referent": False, "delay": 8.0, "chunkPos": 1,
    }
    objects, _, _ = _load_deck(deck)
    anim = objects["920"]["attributes"]["animationAttributes"]
    assert anim["effect"] == "apple:dissolve"
    assert anim["animationType"] == "In"
    # source duration == the archive's own, so neither duration was written
    assert anim["duration"] == 0.5
    assert objects["930"]["duration"] == 0.5
    # the lower clip's own build is left a plain movie-start
    assert objects["900"]["attributes"]["animationAttributes"]["effect"] == "apple:movie-start"


def test_clip_timing_build_in_writes_both_durations_when_the_source_differs(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids, duration=1.25)})

    objects, _, _ = _load_deck(deck)
    assert objects["920"]["attributes"]["animationAttributes"]["duration"] == 1.25
    assert objects["930"]["duration"] == 1.25
    # the untouched clip keeps Keynote's own chunk duration
    assert objects["910"]["duration"] == 0.5


def test_clip_timing_build_in_writes_the_chunk_duration_the_build_already_matches(tmp_path):
    # Keynote auto-creates the upper clip's chunk at duration 0.0 while its build already
    # carries 0.5. The source build-in is 0.5 too, so ONLY the chunk differs: comparing
    # the build alone would leave the chunk at 0.0 and verify that wrong value.
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2, chunk_durations={1: 0.0})
    objects_before, _, _ = _load_deck(deck)
    assert objects_before["920"]["attributes"]["animationAttributes"]["duration"] == 0.5
    assert objects_before["930"]["duration"] == 0.0

    patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids, duration=0.5)})

    objects, _, _ = _load_deck(deck)
    assert objects["920"]["attributes"]["animationAttributes"]["duration"] == 0.5
    assert objects["930"]["duration"] == 0.5
    # the lower clip's chunk keeps Keynote's own duration
    assert objects["910"]["duration"] == 0.5


def test_clip_timing_build_in_slide_keeps_the_plan_chunk_order(tmp_path):
    # Plan order IS the source build order on a stacked slide. The mode ranking would
    # sort the with_previous clip before the after_previous one; it must not.
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 3, initial_chunk_order=[2, 1, 0])
    plan = [
        ClipTiming(movie_ids[0], "after_transition"),
        ClipTiming(movie_ids[1], "after_previous"),
        ClipTiming(
            movie_ids[2], "with_previous", delay=8.0, build_in="apple:dissolve", build_in_duration=0.5
        ),
    ]
    state = patch_clip_start_timing(deck, {"100": plan})

    assert [state["100"][m]["chunkPos"] for m in movie_ids] == [0, 1, 2]
    objects, _, _ = _load_deck(deck)
    chunk_refs = [str((r or {}).get("identifier")) for r in objects["100"].get("buildChunks") or []]
    assert chunk_refs == ["910", "930", "950"]


def test_clip_timing_build_in_is_idempotent(tmp_path):
    # The second run resolves the clip's chunk through a build that is no longer an
    # apple:movie-start -- it must still be found, and rewritten to the same effect.
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    first = patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids)})
    second = patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids)})

    assert second == first
    objects, _, _ = _load_deck(deck)
    assert objects["920"]["attributes"]["animationAttributes"]["effect"] == "apple:dissolve"
    assert objects["930"]["duration"] == 0.5


def test_clip_timing_refuses_an_unsupported_build_in_effect(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2)
    before = deck.read_bytes()
    plan = [
        ClipTiming(movie_ids[0], "after_transition"),
        ClipTiming(movie_ids[1], "with_previous", build_in="apple:move-in", build_in_duration=0.5),
    ]
    with pytest.raises(ValueError, match="is not supported"):
        patch_clip_start_timing(deck, {"100": plan})
    assert deck.read_bytes() == before


def test_clip_timing_refuses_a_build_in_on_a_build_that_is_not_an_in(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2, animation_types={1: "Out"})
    before = deck.read_bytes()
    with pytest.raises(ValueError, match="animationType 'Out', expected In"):
        patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids)})
    assert deck.read_bytes() == before


def test_clip_timing_refuses_a_build_in_when_a_second_build_targets_the_clip(tmp_path):
    deck, movie_ids = _build_timing_deck(tmp_path / "timing.key", 2, extra_build_for=1)
    before = deck.read_bytes()
    with pytest.raises(ValueError, match="has 2 listed build"):
        patch_clip_start_timing(deck, {"100": _frc50_plan(movie_ids)})
    assert deck.read_bytes() == before


def test_clip_timing_empty_plans_is_a_noop(deck):
    assert patch_clip_start_timing(deck, {}) == {}


def test_plan_autoplay_refuses_a_target_with_no_slide_identity(deck):
    x, y, w, h = _LANDMARK_FRAME
    plan = plan_movie_autoplay(deck, [{"x": x, "y": y, "w": w, "h": h, "name": "reveal"}])
    assert plan["refused"] is True
    assert "no slide identity" in plan["reason"]


def test_plan_autoplay_refuses_a_target_on_the_wrong_slide(deck):
    plan = plan_movie_autoplay(deck, [_autoplay_target(_LANDMARK_FRAME, slide_index=2)])
    assert plan["refused"] is True
    assert "matched 0" in plan["reason"]


def _build_two_full_frame_slides_deck(path):
    """Two slides, each with one identical full-frame fly movie and its own start build."""
    bx, by, bw, bh = _BG_FRAME
    rows = []
    nodes = []
    for movie_id, build_id, chunk_id, slide_id, node_id in (
        (310, 900, 910, 100, 10),
        (311, 901, 911, 101, 11),
    ):
        rows.append(
            (
                slide_id,
                _arch(
                    movie_id,
                    "TSD.MovieArchive",
                    {
                        "super": _geom(bx, by, bw, bh),
                        "posterTime": 0.0,
                        "startTime": 0.0,
                        "endTime": 30.0,
                        "naturalSize": {"width": bw, "height": bh},
                        "playsAcrossSlides": True,
                    },
                ),
                _arch(
                    build_id,
                    "KN.BuildArchive",
                    {
                        "drawable": {"identifier": movie_id},
                        "delivery": "All at Once",
                        "duration": 0.0,
                        "attributes": _build_effect("apple:movie-start"),
                        "chunkIdSeed": 1,
                    },
                ),
                _arch(
                    chunk_id,
                    "KN.BuildChunkArchive",
                    {
                        "build": {"identifier": build_id},
                        "delay": 0.0,
                        "duration": 0.5,
                        "automatic": False,
                        "referent": True,
                        "buildChunkIdentifier": {
                            "buildId": {"lower": str(movie_id), "upper": "1"},
                            "buildChunkId": 1,
                        },
                        "buildId": {"lower": str(movie_id), "upper": "1"},
                    },
                ),
                _arch(
                    slide_id,
                    "KN.SlideArchive",
                    {
                        "drawablesZOrder": [{"identifier": movie_id}],
                        "builds": [{"identifier": build_id}],
                        "buildChunks": [{"identifier": chunk_id}],
                    },
                ),
            )
        )
        nodes.append(
            _arch(node_id, "KN.SlideNodeArchive", {"slide": {"identifier": slide_id}, "isSkipped": False})
        )
    show = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}, {"identifier": 11}]}})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Index/Document.iwa", _member([show, *nodes]))
        for slide_id, movie, build, chunk, slide in rows:
            zf.writestr(f"Index/Slide-{slide_id}.iwa", _member([slide, movie, build, chunk]))
    path.write_bytes(buf.getvalue())
    return path


def test_plan_autoplay_matches_identical_full_frame_movies_per_slide(tmp_path):
    deck = _build_two_full_frame_slides_deck(tmp_path / "two-flies.key")
    archives = movie_archives(deck)
    assert {(a["id"], a["slideIndex"]) for a in archives} == {("310", 1), ("311", 2)}
    plan = plan_movie_autoplay(
        deck,
        [
            _autoplay_target(_BG_FRAME, name="s1-fly", slide_index=1),
            _autoplay_target(_BG_FRAME, name="s2-fly", slide_index=2),
        ],
    )
    assert plan["refused"] is False
    assert plan["ids"] == ["310", "311"]
    patched = patch_movie_autoplay(deck, plan["ids"])
    assert patched["refused"] is False
    assert patched["applied"] == 2
    objects, _, _ = _load_deck(deck)
    assert objects["910"]["automatic"] is True
    assert objects["911"]["automatic"] is True
    assert objects["310"]["playsAcrossSlides"] is False
    assert objects["311"]["playsAcrossSlides"] is False


def test_plan_autoplay_identical_full_frames_collide_without_per_slide_match(tmp_path):
    """Geometry-only matching is what the old deck-wide scan did: two flies, one refusal."""
    deck = _build_two_full_frame_slides_deck(tmp_path / "two-flies.key")
    x, y, w, h = _BG_FRAME
    plan = plan_movie_autoplay(deck, [{"x": x, "y": y, "w": w, "h": h, "name": "fly"}])
    assert plan["refused"] is True
    assert "no slide identity" in plan["reason"]


# --------------------------------------------------------------------------
# bare_source_build_ins: the pure-video INTERMEDIATE must carry no source
# build-in, or the DSK deck's own build-in would apply the delay twice
# (Codex r2 BLOCKER; plan §4 item 28).
# --------------------------------------------------------------------------
def test_bare_source_build_ins_rewrites_a_dissolve_into_a_bare_movie_start(tmp_path):
    deck, _movie_ids = _build_timing_deck(
        tmp_path / "frc50.key", 2,
        effects={1: "apple:dissolve"}, chunk_delays={1: 8.0},
    )
    result = bare_source_build_ins(deck, {1: [("movie", 1)]})

    assert result["refused"] is False
    assert result["applied"] == 1
    assert result["touched"] == [(1, ("movie", 1))]
    objects, _, _ = _load_deck(deck)
    anim = objects["920"]["attributes"]["animationAttributes"]
    assert anim["effect"] == "apple:movie-start"
    assert anim["animationType"] == "In"
    chunk = objects["930"]
    assert (bool(chunk["automatic"]), bool(chunk["referent"]), float(chunk["delay"])) == (True, True, 0.0)
    # the lower movie's own movie-start build is untouched
    assert objects["900"]["attributes"]["animationAttributes"]["effect"] == "apple:movie-start"
    assert bool(objects["910"]["automatic"]) is False


def test_bare_source_build_ins_leaves_an_ordinary_movie_start_clip_byte_identical(tmp_path):
    deck, _movie_ids = _build_timing_deck(tmp_path / "plain.key", 2)
    before = deck.read_bytes()
    result = bare_source_build_ins(deck, {1: [("movie", 0), ("movie", 1)]})
    assert result == {"refused": False, "reason": None, "touched": [], "applied": 0}
    assert deck.read_bytes() == before


def test_bare_source_build_ins_ignores_a_movie_with_no_build(tmp_path):
    deck, _movie_ids = _build_timing_deck(tmp_path / "nobuild.key", 2, no_chunk_for=1)
    before = deck.read_bytes()
    result = bare_source_build_ins(deck, {1: [("movie", 1)]})
    assert result["applied"] == 0
    assert deck.read_bytes() == before


def test_bare_source_build_ins_leaves_a_movie_with_two_movie_start_builds_untouched(tmp_path):
    """Byte-neutrality for the ordinary clip path: the "exactly one build" refusal only
    applies to a movie that actually carries a source build-in."""
    deck = _build_movies_deck(tmp_path / "twostarts.key", extra_build_for_landmark=True)
    before = deck.read_bytes()
    result = bare_source_build_ins(deck, {1: [("movie", 0)]})
    assert result["applied"] == 0
    assert deck.read_bytes() == before


def test_bare_source_build_ins_refuses_an_out_build(tmp_path):
    deck, _movie_ids = _build_timing_deck(
        tmp_path / "out.key", 2, effects={1: "apple:dissolve"}, animation_types={1: "Out"},
    )
    before = deck.read_bytes()
    result = bare_source_build_ins(deck, {1: [("movie", 1)]})
    assert result["refused"] is True
    assert "expected In" in result["reason"]
    assert deck.read_bytes() == before


def test_bare_source_build_ins_refuses_a_movie_carrying_two_builds(tmp_path):
    deck, _movie_ids = _build_timing_deck(
        tmp_path / "two.key", 2, effects={1: "apple:dissolve"}, extra_build_for=1,
    )
    before = deck.read_bytes()
    result = bare_source_build_ins(deck, {1: [("movie", 1)]})
    assert result["refused"] is True
    assert "expected exactly one" in result["reason"]
    assert deck.read_bytes() == before

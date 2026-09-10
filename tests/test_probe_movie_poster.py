"""scripts/probe_movie_poster.py: script-generation and --poster resolution tests.
No Keynote, no live probe -- these only exercise pure-Python helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.probe_movie_poster import _resolve_poster, reopen_applescript, select_archives_to_patch


def _archive(**extra) -> dict:
    base = {"id": "300", "startTime": 0.0, "endTime": 0.0, "w": 640.0, "h": 360.0}
    base.update(extra)
    return base


def test_select_default_keeps_landmark_sized_archives():
    landmark = _archive(id="1", w=640.0, h=360.0)
    selected, skipped = select_archives_to_patch([landmark])
    assert selected == [landmark]
    assert skipped == []


def test_select_default_skips_full_width_background_movie():
    wall = _archive(id="2", w=3840.0, h=1080.0)
    selected, skipped = select_archives_to_patch([wall])
    assert selected == []
    assert skipped == [("2", "width 3840.0 >= 3840 (WALL centre band)")]


def test_select_default_skips_full_slide_height_movie_even_if_narrower():
    tall = _archive(id="3", w=1920.0, h=1080.0)
    selected, skipped = select_archives_to_patch([tall])
    assert selected == []
    assert skipped == [("3", "height 1080.0 spans full slide height 1080")]


def test_select_all_opts_back_into_full_width_archives():
    wall = _archive(id="4", w=3840.0, h=1080.0)
    selected, skipped = select_archives_to_patch([wall], all_archives=True)
    assert selected == [wall]
    assert skipped == []


def test_select_id_overrides_size_based_skip():
    wall = _archive(id="5", w=3840.0, h=1080.0)
    landmark = _archive(id="6", w=640.0, h=360.0)
    selected, skipped = select_archives_to_patch([wall, landmark], only_id="5")
    assert selected == [wall]
    assert skipped == []


def test_resolve_poster_last_refuses_without_explicit_positive_end_time():
    with pytest.raises(SystemExit, match="no explicit positive endTime"):
        _resolve_poster(_archive(startTime=0.0, endTime=0.0), "last")


def test_resolve_poster_last_accepts_explicit_positive_end_time():
    assert _resolve_poster(_archive(startTime=0.0, endTime=2.5), "last") == 2.5


def test_resolve_poster_seconds_bypasses_last_frame_logic():
    assert _resolve_poster(_archive(startTime=0.0, endTime=0.0), "1.25") == 1.25


def test_reopen_applescript_compares_exact_posix_path_not_prefix(tmp_path: Path):
    deck = tmp_path / "movies_reopen.key"
    deck.write_bytes(b"x")
    script = reopen_applescript(deck, doc_name=deck.stem)

    # Exact-path guard: the coerced `file` POSIX path must be compared for full
    # equality against the scratch-copy path, not a `starts with` prefix check
    # that a same-prefix sibling deck could also satisfy.
    assert "POSIX path of (file of theDoc as alias)" in script
    assert "starts with" not in script
    assert f'if gotPath is not "{str(deck.resolve())}"' in script

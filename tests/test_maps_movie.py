import json
from pathlib import Path

import pytest

from obed_edom.maps_keynote import ensure_png
from obed_edom.maps_movie import (
    encode_fly_movie,
    encode_pending,
    ffmpeg_exe,
    frames_dir,
    movie_path,
    require_contiguous_frames,
    safe_slide_id,
)


def _make_frames(tmp_path: Path, slide_id: str, count: int = 6) -> Path:
    folder = frames_dir(tmp_path, slide_id)
    for i in range(count):
        ensure_png(folder / f"{i:05d}.png", 128, 64)
    return folder


def test_safe_slide_id():
    assert safe_slide_id("s1") == "s1"
    assert safe_slide_id("s 1/../x") == "s_1_._.x" or "/" not in safe_slide_id("s 1/../x")


def test_cg_movie_and_frame_paths_are_isolated(tmp_path):
    from obed_edom.maps_movie import frames_dir, movie_filename, write_frame

    assert movie_filename("s1") != movie_filename("s1", "cg")
    assert frames_dir(tmp_path, "s1") != frames_dir(tmp_path, "s1", "cg")
    lw = write_frame(tmp_path, "s1", 0, b"lw", "image/jpeg")
    cg = write_frame(tmp_path, "s1", 0, b"cg", "image/jpeg", "cg")
    assert lw.read_bytes() == b"lw"
    assert cg.read_bytes() == b"cg"


def test_encode_fly_movie(tmp_path):
    if ffmpeg_exe() is None:
        pytest.skip("ffmpeg not available")
    frames = _make_frames(tmp_path, "s1")
    dest = movie_path(tmp_path, "s1")
    result = encode_fly_movie(frames, dest, fps=6)
    assert result == dest
    assert dest.exists()
    assert dest.stat().st_size > 0
    assert dest.name.endswith(".mov")


def test_encode_pending_sets_movie_fields(tmp_path):
    if ffmpeg_exe() is None:
        pytest.skip("ffmpeg not available")
    frames = _make_frames(tmp_path, "s1")
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 6, "duration": 1.0}))
    slides = [{"id": "s1"}, {"id": "s2"}]
    updated = encode_pending(tmp_path, slides)
    s1 = next(s for s in updated if s["id"] == "s1")
    s2 = next(s for s in updated if s["id"] == "s2")
    assert s1["movieMov"] == "Map BG_s1.mov"
    assert s1["movieDuration"] == 1.0
    assert movie_path(tmp_path, "s1").exists()
    assert "movieMov" not in s2
    assert "movieDuration" not in s2


def test_encode_pending_passes_cancellation_to_encoder(tmp_path, monkeypatch):
    frames = _make_frames(tmp_path, "s1", count=2)
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 2}))

    def cancelled_encoder(*_a, is_cancelled, **_k):
        assert is_cancelled()
        raise RuntimeError("Export cancelled.")

    monkeypatch.setattr("obed_edom.maps_movie.encode_fly_movie", cancelled_encoder)
    checks = iter((False, False, True))
    with pytest.raises(RuntimeError, match="Export cancelled"):
        encode_pending(tmp_path, [{"id": "s1"}], is_cancelled=lambda: next(checks))


def test_encode_pending_skips_when_movie_newer_than_meta(tmp_path, monkeypatch):
    if ffmpeg_exe() is None:
        pytest.skip("ffmpeg not available")
    frames = _make_frames(tmp_path, "s1")
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 6, "duration": 1.0}))
    slides = [{"id": "s1"}]
    encode_pending(tmp_path, slides)

    def boom(*_a, **_k):
        raise AssertionError("should not re-encode")

    monkeypatch.setattr("obed_edom.maps_movie.encode_fly_movie", boom)
    encode_pending(tmp_path, slides)


def test_require_contiguous_frames_rejects_gap(tmp_path):
    folder = _make_frames(tmp_path, "s1", count=4)
    (folder / "00002.png").unlink()
    with pytest.raises(ValueError, match="Frame gap"):
        require_contiguous_frames(folder)


def test_encode_pending_duration_uses_frame_count_not_meta(tmp_path):
    if ffmpeg_exe() is None:
        pytest.skip("ffmpeg not available")
    frames = _make_frames(tmp_path, "s1", count=6)
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 6, "duration": 99.0}))
    updated = encode_pending(tmp_path, [{"id": "s1"}])
    assert updated[0]["movieDuration"] == 1.0


def test_encode_pending_raises_on_gap(tmp_path):
    frames = _make_frames(tmp_path, "s1", count=4)
    (frames / "00002.png").unlink()
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 4, "duration": 0.66}))
    with pytest.raises(ValueError, match="Frame gap"):
        encode_pending(tmp_path, [{"id": "s1"}])


def test_encode_pending_raises_when_meta_and_too_few_frames(tmp_path):
    frames = frames_dir(tmp_path, "s1")
    frames.mkdir(parents=True)
    (frames / "meta.json").write_text(json.dumps({"fps": 30, "count": 60, "duration": 2.0}))
    ensure_png(frames / "00000.png", 128, 64)
    with pytest.raises(ValueError, match="at least 2"):
        encode_pending(tmp_path, [{"id": "s1"}])


def test_encode_pending_skips_without_meta(tmp_path):
    updated = encode_pending(tmp_path, [{"id": "s1", "movieMov": "Map BG_s1.mov"}])
    assert "movieMov" not in updated[0]


def test_encode_pending_drops_frames_when_hop_not_movie(tmp_path):
    frames = _make_frames(tmp_path, "s1")
    (frames / "meta.json").write_text(json.dumps({"fps": 6, "count": 6, "duration": 1.0}))
    slides = [{"id": "s1", "movieMov": "Map BG_s1.mov", "movieDuration": 1.0}, {"id": "s2"}]
    links = [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 1.0}]
    updated = encode_pending(tmp_path, slides, links=links)
    assert not frames.exists()
    assert "movieMov" not in updated[0]
    assert "movieDuration" not in updated[0]


@pytest.mark.parametrize(("audience", "other_audience"), [("lw", "cg"), ("cg", "lw")])
def test_encode_pending_preserves_other_audience_frames(tmp_path, audience, other_audience):
    current = frames_dir(tmp_path, "s1", audience)
    current.mkdir(parents=True)
    other = frames_dir(tmp_path, "s1", other_audience)
    other.mkdir(parents=True)
    (other / "sentinel").write_text("keep")

    slides = [{"id": "s1"}, {"id": "s2"}]
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0}]
    encode_pending(tmp_path, slides, links=links, audience=audience)

    assert other.exists()
    assert (other / "sentinel").read_text() == "keep"

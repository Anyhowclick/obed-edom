from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from obed_edom.maps_movie import ffmpeg_exe
from obed_edom.maps_reveal import (
    _run_ffmpeg_stdin,
    render_reveal,
    render_slide_reveal_movie,
    reveal_fingerprint,
    reveal_frames,
    reveal_path,
    reveal_seed,
    reveal_stale,
)


def _rgba(w: int = 40, h: int = 30) -> np.ndarray:
    arr = np.zeros((h, w, 4), np.uint8)
    arr[:, :, 0] = 200
    arr[:, :, 3] = 255
    return arr


def test_frame_zero_is_empty_and_last_frame_matches_source():
    rgba = _rgba()
    frames = list(reveal_frames(rgba, count=12, seed=reveal_seed("church-1")))
    assert frames[0][:, :, 3].max() == 0
    assert np.array_equal(frames[-1][:, :, 3], rgba[:, :, 3])


def test_alpha_is_non_decreasing_per_pixel():
    rgba = _rgba()
    frames = list(reveal_frames(rgba, count=15, seed=reveal_seed("church-1")))
    for prev, nxt in zip(frames, frames[1:]):
        assert (nxt[:, :, 3].astype(int) >= prev[:, :, 3].astype(int)).all()


def test_same_seed_is_deterministic_different_church_differs():
    rgba = _rgba()
    seed = reveal_seed("church-1")
    a = list(reveal_frames(rgba, count=8, seed=seed))
    b = list(reveal_frames(rgba, count=8, seed=seed))
    for fa, fb in zip(a, b):
        assert np.array_equal(fa, fb)
    other = list(reveal_frames(rgba, count=8, seed=reveal_seed("church-2")))
    assert not all(np.array_equal(fa, fo) for fa, fo in zip(a, other))


def test_bottom_strokes_land_before_top():
    rgba = _rgba(w=200, h=200)
    frames = list(reveal_frames(rgba, count=45, seed=reveal_seed("church-1")))
    frame = frames[round(0.4 * (len(frames) - 1))]
    bottom_third = frame[130:200, :, 3].astype(float).mean()
    top_third = frame[0:70, :, 3].astype(float).mean()
    assert bottom_third > top_third


def test_half_time_is_roughly_half_covered():
    rgba = _rgba(w=200, h=200)
    frames = list(reveal_frames(rgba, count=45, seed=reveal_seed("church-1")))
    frame = frames[round(0.5 * (len(frames) - 1))]
    coverage = frame[:, :, 3].astype(float).mean() / 255
    assert 0.3 <= coverage <= 0.7


def test_coverage_has_stroke_structure():
    rgba = _rgba(w=200, h=200)
    frames = list(reveal_frames(rgba, count=45, seed=reveal_seed("church-1")))
    frame = frames[round(0.25 * (len(frames) - 1))]
    row_means = frame[:, :, 3].astype(float).mean(axis=1)
    assert (row_means < 5).any()
    assert (row_means > 128).any()


def test_long_side_downscaled_to_1600(tmp_path: Path, monkeypatch):
    asset = tmp_path / "big.png"
    Image.new("RGBA", (3000, 1500), (10, 20, 30, 255)).save(asset)
    captured: dict = {}

    def fake_run(cmd, frames, is_cancelled):
        first = next(frames)
        captured["w"] = int(cmd[cmd.index("-s") + 1].split("x")[0])
        captured["h"] = int(cmd[cmd.index("-s") + 1].split("x")[1])
        captured["shape"] = first.shape

    monkeypatch.setattr("obed_edom.maps_reveal._run_ffmpeg_stdin", fake_run)
    dest = tmp_path / "out.mov"
    (tmp_path / f".{dest.stem}.tmp{dest.suffix}").touch()
    render_reveal(asset, dest, duration=1.0, seed=1)
    assert max(captured["w"], captured["h"]) == 1600
    assert captured["shape"][1] == captured["w"]
    assert captured["shape"][0] == captured["h"]


def test_render_reveal_argv_uses_prores_alpha(tmp_path: Path, monkeypatch):
    asset = tmp_path / "a.png"
    Image.new("RGBA", (20, 10), (10, 20, 30, 255)).save(asset)
    dest = tmp_path / "reveal" / "out.mov"
    captured: dict = {}

    def fake_run(cmd, frames, is_cancelled):
        captured["cmd"] = cmd
        list(frames)

    monkeypatch.setattr("obed_edom.maps_reveal._run_ffmpeg_stdin", fake_run)
    tmp_dest = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    tmp_dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest.touch()
    result = render_reveal(asset, dest, duration=1.0, seed=1)
    cmd = captured["cmd"]
    assert "prores_ks" in cmd
    assert "yuva444p10le" in cmd
    assert "-vendor" in cmd
    assert str(tmp_dest) == cmd[-1]
    assert result == dest


def test_reveal_path_layout(tmp_path: Path):
    path = reveal_path(tmp_path, "slide 1", "church/1")
    assert path.parent == tmp_path / "reveal"
    assert path.suffix == ".mov"


def test_reveal_path_separates_lw_and_cg():
    lw = reveal_path(Path("/out"), "s1", "c1", "lw")
    cg = reveal_path(Path("/out"), "s1", "c1", "cg")
    assert lw != cg
    assert cg.name.endswith("-cg.mov")


def test_reveal_fingerprint_changes_with_duration_and_opacity(tmp_path: Path):
    asset = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 255)).save(asset)
    base = reveal_fingerprint(asset, duration=1.0, opacity=1.0, seed=1, width=10, height=10)
    assert base != reveal_fingerprint(asset, duration=2.0, opacity=1.0, seed=1, width=10, height=10)
    assert base != reveal_fingerprint(asset, duration=1.0, opacity=0.5, seed=1, width=10, height=10)
    assert base != reveal_fingerprint(asset, duration=1.0, opacity=1.0, seed=2, width=10, height=10)


def test_reveal_stale_true_without_dest_or_sidecar_true_on_mismatch_false_on_match(tmp_path: Path):
    dest = tmp_path / "out.mov"
    assert reveal_stale(dest, "fp-a") is True
    dest.write_bytes(b"movie")
    assert reveal_stale(dest, "fp-a") is True
    dest.with_suffix(".mov.fp").write_text("fp-a")
    assert reveal_stale(dest, "fp-a") is False
    assert reveal_stale(dest, "fp-b") is True


def test_render_reveal_writes_fingerprint_sidecar(tmp_path: Path, monkeypatch):
    asset = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 255)).save(asset)
    dest = tmp_path / "reveal" / "out.mov"

    def fake_run(cmd, frames, is_cancelled):
        list(frames)
        Path(cmd[-1]).write_bytes(b"movie")

    monkeypatch.setattr("obed_edom.maps_reveal._run_ffmpeg_stdin", fake_run)
    render_reveal(asset, dest, duration=1.0, seed=1, fingerprint="abc123")
    assert dest.with_suffix(".mov.fp").read_text() == "abc123"


def test_render_reveal_cleans_up_tmp_movie_on_failure(tmp_path: Path, monkeypatch):
    asset = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 255)).save(asset)
    dest = tmp_path / "reveal" / "out.mov"

    def failing_run(cmd, frames, is_cancelled):
        list(frames)
        Path(cmd[-1]).write_bytes(b"partial")
        raise RuntimeError("ffmpeg failed: boom")

    monkeypatch.setattr("obed_edom.maps_reveal._run_ffmpeg_stdin", failing_run)
    with pytest.raises(RuntimeError, match="boom"):
        render_reveal(asset, dest, duration=1.0, seed=1)
    tmp_dest = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    assert not tmp_dest.exists()
    assert not dest.exists()


def test_encoder_does_not_deadlock_on_large_stderr_and_can_be_cancelled(tmp_path: Path):
    """A fake ffmpeg that floods stderr past the OS pipe buffer must not hang the frame-writing loop."""
    if ffmpeg_exe() is None:
        pytest.skip("no shell available for the fake ffmpeg script")
    script = tmp_path / "fake_ffmpeg.py"
    script.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('x' * 2_000_000)\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n"
    )
    cmd = [__import__("sys").executable, str(script)]

    def frames():
        for _ in range(3):
            yield np.zeros((4, 4, 4), np.uint8)

    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        _run_ffmpeg_stdin(cmd, frames(), None)


def test_encoder_cancellation_terminates_child_process():
    script_cmd = [
        __import__("sys").executable,
        "-c",
        "import sys, time; sys.stdin.read(); time.sleep(30)",
    ]
    calls = {"n": 0}

    def is_cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    def frames():
        for _ in range(1):
            yield np.zeros((4, 4, 4), np.uint8)

    with pytest.raises(RuntimeError, match="cancelled"):
        _run_ffmpeg_stdin(script_cmd, frames(), is_cancelled)


def test_slide_reveal_movie_composites_landmark_at_frame(tmp_path: Path, monkeypatch):
    captured: dict = {}

    def fake_encode(frames, dest, *, fps, log=None, is_cancelled=None):
        captured["last"] = sorted(frames.glob("*.png"))[-1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mov")
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.encode_fly_movie", fake_encode)
    base = tmp_path / "base.png"
    Image.new("RGBA", (200, 100), (10, 20, 30, 255)).save(base)
    asset = tmp_path / "lm.png"
    Image.new("RGBA", (30, 30), (200, 50, 50, 255)).save(asset)
    dest = tmp_path / "out" / "movies" / "Map BG_s1-reveal.mov"
    landmarks = [dict(asset=asset, x=40, y=20, w=30, h=30, duration=0.3, seed=1, opacity=1.0)]

    render_slide_reveal_movie(
        base, None, landmarks, dest, output_dir=tmp_path / "out", slide_id="s1", size=(200, 100), fps=10
    )

    last = np.array(Image.open(captured["last"]).convert("RGB"))
    assert tuple(int(v) for v in last[35, 55]) == (200, 50, 50)
    assert tuple(int(v) for v in last[10, 10]) == (10, 20, 30)


def test_render_reveal_encodes_real_movie(tmp_path: Path):
    if ffmpeg_exe() is None:
        pytest.skip("ffmpeg not available")
    asset = tmp_path / "a.png"
    Image.new("RGBA", (24, 16), (200, 30, 30, 255)).save(asset)
    dest = tmp_path / "reveal" / "a.mov"
    result = render_reveal(asset, dest, duration=0.4, seed=42, fps=12)
    assert result == dest
    assert dest.exists()
    assert dest.stat().st_size > 0

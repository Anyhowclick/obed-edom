from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from obed_edom.maps_movie import ffmpeg_exe
from obed_edom.maps_reveal import render_reveal, reveal_frames, reveal_path, reveal_seed


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


def test_sweep_is_ground_up_bottom_left_to_top_right():
    rgba = _rgba(w=40, h=40)
    frames = list(reveal_frames(rgba, count=21, seed=reveal_seed("church-1")))
    mid = frames[10]
    bottom_left = mid[30:40, 0:10, 3].astype(float).mean()
    top_right = mid[0:10, 30:40, 3].astype(float).mean()
    assert bottom_left > top_right
    bottom_row_alpha = mid[-1, :, 3].astype(float).mean()
    top_row_alpha = mid[0, :, 3].astype(float).mean()
    assert bottom_row_alpha > top_row_alpha


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

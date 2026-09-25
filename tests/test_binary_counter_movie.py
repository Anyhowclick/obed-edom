"""Offline tests for `scripts/binary_counter_movie.py`: the encoded movie decodes back to its own frame index on every
frame through `obs_cadence_decode.read_strip` (the harness's binary decoder), and the fixture builder swaps only the
test-pattern movies. ffmpeg only; no browser, OBS or Keynote.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie as movie  # noqa: E402
import obs_cadence_decode as decode  # noqa: E402

GREEN_SLOT_SOURCE_X = (788.7 - 109.35) / (951.54 / 1920)


@pytest.fixture(scope="module")
def full_movie(tmp_path_factory) -> dict:
    """The full-length P2-duration movie, every frame decoded at source scale; frames 0, 1 and 1380 kept."""
    info = movie.write_movie(tmp_path_factory.mktemp("movie") / "Untitled.mov-0.0000-46.0333.mov")
    reader = imageio_ffmpeg.read_frames(info["path"], pix_fmt="rgb24")
    meta = next(reader)
    width, height = meta["size"]
    reads, kept = [], {}
    for index, raw in enumerate(reader):
        frame = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
        reads.append(decode.read_strip(frame, (0.0, 0.0), 1.0))
        if index in (0, 1, 1380):
            kept[index] = frame.copy()
    return {"info": info, "meta": meta, "reads": reads, "frames": kept}


def test_movie_matches_the_p2_pattern_container(full_movie):
    info, meta = full_movie["info"], full_movie["meta"]
    assert tuple(meta["size"]) == (1920, 540) and meta["fps"] == 30.0 and meta["codec"] == "h264"
    assert info["frames"] == 1381 and len(full_movie["reads"]) == 1381
    assert imageio_ffmpeg.count_frames_and_secs(info["path"]) == (1381, pytest.approx(46.0333, abs=0.01))


def test_every_encoded_frame_decodes_to_its_own_index(full_movie):
    reads = full_movie["reads"]
    assert [value for value, _ in reads] == list(range(1381))
    assert {reason for _, reason in reads} == {"ok"}


@pytest.mark.parametrize("index", [0, 1, 1380])
def test_selected_frames_round_trip_and_blocks_sit_near_0_and_255(full_movie, index):
    frame = full_movie["frames"][index]
    assert decode.read_strip(frame, (0.0, 0.0), 1.0) == (index, "ok")
    for bit, (x, y, w, h) in zip(movie.strip_bits(index), movie.BLOCK_RECTS):
        level = frame[y + 8:y + h - 8, x + 8:x + w - 8].mean()
        assert (level > 250) if bit else (level < 5), (index, x, level)


def test_a_parity_flip_on_an_encoded_frame_reads_none(full_movie):
    frame = full_movie["frames"][1380].copy()
    x, y, w, h = movie.BLOCK_RECTS[len(movie.START) + movie.DATA_BITS]
    frame[y:y + h, x:x + w] = 255 - frame[y:y + h, x:x + w]
    assert decode.read_strip(frame, (0.0, 0.0), 1.0) == (None, "parity")


def test_strip_bits_layout_and_even_parity():
    bits = movie.strip_bits(1380)
    assert bits[:2] == [1, 0] and bits[-2:] == [0, 1]
    assert bits[2:14] == [int(b) for b in f"{1380:012b}"]
    assert sum(bits[2:15]) % 2 == 0
    with pytest.raises(ValueError):
        movie.strip_bits(1 << movie.DATA_BITS)


def test_strip_and_digits_stay_clear_of_each_other_and_of_the_slide2_green_slot():
    sx, sy, sw, sh = movie.STRIP_RECT
    dx, dy, dw, dh = movie.DIGITS_RECT
    assert sy + sh <= dy
    assert sx + sw < GREEN_SLOT_SOURCE_X and dx + dw < GREEN_SLOT_SOURCE_X
    assert movie.BLOCK >= 16 and all(x + w <= sx + sw for x, _, w, _ in movie.BLOCK_RECTS)


def fake_p2_tree(root: Path) -> None:
    for tree in ("html-player", "html-disposable", "html-unmodified"):
        mov = root / tree / "assets/A/assets/Untitled.mov-0.0000-1.0000.mov"
        mov.parent.mkdir(parents=True)
        mov.write_bytes(b"old " + tree.encode())
    (root / "html-unmodified/index.html").write_text("<html></html>")
    (root / "runs").mkdir()
    (root / "runs/big.json").write_text("{}")
    (root / "report.json").write_text("{}")


def test_build_fixture_swaps_test_pattern_movies_and_writes_the_manifest(tmp_path):
    source, dest = tmp_path / "p2", tmp_path / "p2-binary"
    fake_p2_tree(source)
    manifest = movie.build_fixture(dest, source)
    on_disk = json.loads((dest / movie.MANIFEST).read_text())
    assert on_disk == manifest and movie.read_manifest(dest)["counter"] == "binary"
    assert manifest["base"] == movie.FIXTURE_BASE and manifest["generatorVersion"] == movie.GENERATOR_VERSION
    assert [m["frames"] for m in manifest["movies"]] == [30]
    sha = manifest["movies"][0]["sha256"]
    for tree in ("html-player", "html-disposable"):
        assert movie.sha256_file(dest / tree / "assets/A/assets/Untitled.mov-0.0000-1.0000.mov") == sha
    assert (dest / "html-unmodified/assets/A/assets/Untitled.mov-0.0000-1.0000.mov").read_bytes() == b"old html-unmodified"
    assert (dest / "report.json").exists() and not (dest / "runs").exists()
    assert not list(dest.glob(".movie-*"))
    assert (source / "html-player/assets/A/assets/Untitled.mov-0.0000-1.0000.mov").read_bytes() == b"old html-player"


def test_build_fixture_refuses_to_write_under_p2_recovery(tmp_path):
    source = tmp_path / "p2"
    fake_p2_tree(source)
    with pytest.raises(SystemExit):
        movie.build_fixture(tmp_path / "p2-recovery" / "copy", source)
    assert not (tmp_path / "p2-recovery").exists()


def test_read_manifest_is_empty_for_the_grey_p2_fixture(tmp_path):
    assert movie.read_manifest(tmp_path) == {}

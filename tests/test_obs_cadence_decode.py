"""Synthetic tests for `scripts/obs_cadence_decode.py` (plan keynote_live_gl_replay_managed_obs §3); no OBS.

The backward-step pair is M2's only known-bad for its `backwardSteps == 0` check, and the
wrap/non-wrap pair is M6's wrap known-bad (plan §5).
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import obs_cadence_decode as decode  # noqa: E402

SOAK_LOOP_FRAMES = 1381


def greys_for(counter: list[int], c: float = 0.52) -> list[int | None]:
    return [int(round(n * decode.STEP + c)) for n in counter]


def stats(counter: list[int], loop_frames: int | None = None) -> dict:
    padded = [counter[0]] * decode.EDGE_TRIM + counter + [counter[-1]] * decode.EDGE_TRIM
    return decode.phase_stats(greys_for(padded), 0.52, 25.0, loop_frames)


def test_monotonic_run_has_no_backward_steps():
    result = stats([n % decode.MOD for n in range(100, 400)])
    assert result["backwardSteps"] == 0
    assert result["wrapSteps"] == 0
    assert result["repeatFrac"] == 0.0


def test_mod_220_rollover_is_forward_not_backward():
    result = stats([n % decode.MOD for n in range(210, 230)])
    assert result["backwardSteps"] == 0


def test_backward_step_is_counted():
    counter = list(range(50, 80)) + list(range(60, 90))
    assert stats(counter)["backwardSteps"] == 1


def test_loop_wrap_counts_as_wrap_not_backward():
    end = (SOAK_LOOP_FRAMES - 1) % decode.MOD
    counter = list(range(end - 20, end + 1)) + list(range(0, 20))
    result = stats(counter, SOAK_LOOP_FRAMES)
    assert result["wrapSteps"] == 1
    assert result["backwardSteps"] == 0


def test_loop_wrap_tolerates_two_frames_either_side():
    end = (SOAK_LOOP_FRAMES - 1) % decode.MOD
    counter = list(range(end - 20, end - 1)) + list(range(2, 20))
    result = stats(counter, SOAK_LOOP_FRAMES)
    assert (result["wrapSteps"], result["backwardSteps"]) == (1, 0)


def test_mid_run_backward_step_is_not_a_wrap():
    counter = list(range(100, 140)) + list(range(110, 150))
    result = stats(counter, SOAK_LOOP_FRAMES)
    assert result["wrapSteps"] == 0
    assert result["backwardSteps"] == 1


def test_wrap_signature_needs_loop_frames():
    end = (SOAK_LOOP_FRAMES - 1) % decode.MOD
    counter = list(range(end - 20, end + 1)) + list(range(0, 20))
    result = stats(counter)
    assert (result["wrapSteps"], result["backwardSteps"]) == (0, 1)


RECT = (100.0, 200.0, 50.0, 30.0)


def blank() -> np.ndarray:
    return np.full((400, 400, 3), 40, np.uint8)


def test_ring_max_delta_is_zero_on_identical_frames():
    frame = blank()
    assert decode.ring_max_delta(frame, frame.copy(), RECT) == 0


@pytest.mark.parametrize("dx", [2, 5, 7])
def test_ring_max_delta_fires_on_a_one_pixel_poke_inside_the_ring(dx):
    reference, poked = blank(), blank()
    poked[215, 100 + 50 + dx] = (240, 40, 40)
    assert decode.ring_max_delta(reference, poked, RECT) == 200


@pytest.mark.parametrize("xy", [(125, 215), (151, 215), (159, 215), (100 - 9, 215), (125, 200 - 9)])
def test_ring_max_delta_ignores_a_poke_outside_the_ring(xy):
    reference, poked = blank(), blank()
    poked[xy[1], xy[0]] = (240, 40, 40)
    assert decode.ring_max_delta(reference, poked, RECT) == 0


def test_phase_marker_colours_are_pairwise_separable():
    for (a, rgb_a), (b, rgb_b) in itertools.combinations(decode.PHASES.items(), 2):
        dist = np.abs(np.array(rgb_a) - np.array(rgb_b)).max()
        assert dist > 2 * decode.MARK_MAX_DIST, (a, b, dist)


def test_unmeasured_grey_marker_reads_as_no_phase():
    frame = np.full((32, 32, 3), 128, np.uint8)
    assert decode.phase_of(frame)[0] is None


def test_lossless_guard_rejects_a_non_allowlisted_codec():
    with pytest.raises(decode.NotLossless):
        decode.check_lossless({"codec": "h264", "pix_fmt": "yuv420p"})
    with pytest.raises(decode.NotLossless):
        decode.check_lossless({})


def test_lossless_guard_accepts_an_allowlisted_codec():
    for codec in decode.LOSSLESS_CODECS:
        decode.check_lossless({"codec": codec, "pix_fmt": "gbrp"})


def test_decode_recording_refuses_before_reading_frames(monkeypatch):
    consumed = []

    def frames():
        consumed.append(True)
        yield np.zeros((4, 4, 3), np.uint8)

    monkeypatch.setattr(decode, "read_frames", lambda _path: ({"codec": "h264", "pix_fmt": "yuv420p", "fps": 25.0, "size": (4, 4)}, frames()))
    with pytest.raises(decode.NotLossless):
        decode.decode_recording(Path("x.mov"))
    assert consumed == []


def synthetic_frame(phase: str, counter: int | None, poke: bool = False) -> np.ndarray:
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[: 24, : 24] = decode.PHASES[phase]
    if counter is not None:
        x, y, w, h = decode.INDEX_PATCH_ROI
        frame[y:y + h, x:x + w] = greys_for([counter])[0]
    if poke:
        frame[int(RING_RECT[1]) - 4, int(RING_RECT[0]) + 10] = 255
    return frame


RING_RECT = (109.0, 795.0, 952.0, 268.0)


def test_decode_recording_reports_phases_endpoints_rings_and_skips_hidden(monkeypatch):
    frames = ([synthetic_frame("slide2-live", n) for n in range(0, 30)]
              + [synthetic_frame("slide2-hidden", None) for _ in range(5)]
              + [synthetic_frame("slide2-handback", n, poke=n == 50) for n in range(40, 60)])
    meta = {"codec": sorted(decode.LOSSLESS_CODECS)[0], "pix_fmt": "gbrp", "fps": 25.0, "size": (1920, 1080)}
    monkeypatch.setattr(decode, "read_frames", lambda _path: (meta, iter(frames)))
    result = decode.decode_recording(Path("x.avi"), rings=[RING_RECT])
    assert result["phaseFrames"]["slide2-hidden"] == 5
    assert "slide2-hidden" not in result["phases"]
    live, handback = result["phases"]["slide2-live"], result["phases"]["slide2-handback"]
    assert live["decodableFrac"] == 1.0 and live["repeatFrac"] == 0.0 and live["backwardSteps"] == 0
    assert handback["backwardSteps"] == 0
    assert result["endpoints"]["slide2-live"] == {"first": [2, 2], "last": [27, 27]}
    assert result["endpoints"]["slide2-handback"]["first"] == [37, 42]
    assert result["ringMaxDelta"] == {"slide2-live": 0, "slide2-handback": 255}
    assert result["handbackCounters"] == list(range(40, 60))
    assert result["codec"] == meta["codec"]


def test_static_check_passes_a_still_movie_rect_and_fails_a_moving_counter(monkeypatch):
    still = [synthetic_frame("slide2-live", None) for _ in range(10)]
    for frame in still:
        frame[800:1000, 200:900] = (90, 120, 60)
    moving = [synthetic_frame("slide2-live", n) for n in range(10)]
    meta = {"codec": sorted(decode.LOSSLESS_CODECS)[0], "pix_fmt": "yuv420p", "fps": 25.0, "size": (1920, 1080)}
    rect = (float(decode.INDEX_PATCH_ROI[0] - 20), float(decode.INDEX_PATCH_ROI[1] - 20), 400.0, 200.0)
    for frames, expect in ((still, 0), (moving, None)):
        monkeypatch.setattr(decode, "read_frames", lambda _path, frames=frames: (meta, iter(frames)))
        value = decode.decode_recording(Path("x.avi"), statics=[rect])["staticMaxDelta"]["slide2-live"]
        if expect is None:
            assert value > 4
        else:
            assert value == expect


def test_static_mask_is_the_rect_eroded_four_px():
    mask = decode.static_mask((400, 400, 3), RECT)
    ys, xs = np.nonzero(mask)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (104, 145, 204, 225)


def test_ring_diag_locates_the_worst_frame_and_saves_crops(monkeypatch, tmp_path):
    frames = [synthetic_frame("slide2-live", n) for n in range(6)] + [
        synthetic_frame("slide2-handback", n, poke=n == 9) for n in range(6, 12)]
    meta = {"codec": sorted(decode.LOSSLESS_CODECS)[0], "pix_fmt": "yuv420p", "fps": 25.0, "size": (1920, 1080)}
    monkeypatch.setattr(decode, "read_frames", lambda _path: (meta, iter(frames)))
    result = decode.decode_recording(Path("x.avi"), rings=[RING_RECT], crops_dir=tmp_path)
    diag = result["ringDiag"]["slide2-handback"]
    x, y = int(RING_RECT[0]) + 10, int(RING_RECT[1]) - 4
    assert diag["worstFrame"] == 9 and diag["firstFrame"] == 6 and diag["worstSinceFirstS"] == 0.12
    assert diag["overTau"] == {"tau": 0, "count": 1, "bbox": [x, y, x + 1, y + 1]}
    assert len(diag["crops"]) == 3 and all(Path(p).exists() for p in diag["crops"])


def test_ring_exclude_masks_a_band_around_another_slot_edge(monkeypatch):
    poke_x, poke_y = int(RING_RECT[0]) + 10, int(RING_RECT[1]) - 4
    frames = [synthetic_frame("slide2-handback", n) for n in range(4)]
    frames[-1][poke_y, poke_x] = 255
    meta = {"codec": sorted(decode.LOSSLESS_CODECS)[0], "pix_fmt": "yuv420p", "fps": 25.0, "size": (1920, 1080)}
    slot_edge_at_poke = (float(poke_x - 2), 700.0, 100.0, 200.0)
    far_slot = (1500.0, 100.0, 50.0, 50.0)
    for exclude, expect in (([slot_edge_at_poke], 0), ([far_slot], 255)):
        monkeypatch.setattr(decode, "read_frames", lambda _path: (meta, iter(frames)))
        result = decode.decode_recording(Path("x.avi"), rings=[RING_RECT], ring_exclude=exclude)
        assert result["ringMaxDelta"]["slide2-handback"] == expect

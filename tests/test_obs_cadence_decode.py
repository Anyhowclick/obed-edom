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

import managed_obs_qualify  # noqa: E402
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


def test_loop_wrap_allows_a_normal_step_plus_the_browser_loop_seek_skip():
    """L5 soak 2026-09-25, window 1: 1380 -> 3 (4 frames across the loop point) is a wrap: a 2-frame capture step plus
    the 0-2 frames Chrome's own `video.loop` seek skips (measured on the element's clock, 40 headless wraps)."""
    end = (SOAK_LOOP_FRAMES - 1) % decode.MOD
    for pre_end, post_start, advanced in ((end, 3, 4), (end - 1, 2, 4), (end - 2, 1, 4), (end, 0, 1)):
        counter = list(range(end - 20, pre_end + 1)) + list(range(post_start, 20))
        result = stats(counter, SOAK_LOOP_FRAMES)
        assert (result["wrapSteps"], result["backwardSteps"], result["maxWrapStep"]) == (1, 0, advanced), (pre_end, post_start)


def test_known_bad_a_wrap_skipping_more_than_the_measured_seek_is_backward():
    end = (SOAK_LOOP_FRAMES - 1) % decode.MOD
    for pre_end, post_start in ((end, 4), (end - 2, 2), (end - 3, 0)):
        counter = list(range(end - 20, pre_end + 1)) + list(range(post_start, 20))
        result = stats(counter, SOAK_LOOP_FRAMES)
        assert (result["wrapSteps"], result["backwardSteps"], result["maxWrapStep"]) == (0, 1, None), (pre_end, post_start)


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


def test_lossless_guard_accepts_the_allowlisted_pair_with_ffmpeg_colour_suffix():
    decode.check_lossless({"codec": "utvideo", "pix_fmt": "yuv420p(bt709/unknown/unknown)"})
    decode.check_lossless({"codec": "utvideo", "pix_fmt": "yuv420p"})


def test_lossless_guard_rejects_utvideo_in_a_pix_fmt_outside_the_allowlist():
    with pytest.raises(decode.NotLossless, match=r"lossless codec \(4:2:0\)"):
        decode.check_lossless({"codec": "utvideo", "pix_fmt": "gbrp"})


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
META = {"codec": "utvideo", "pix_fmt": "yuv420p(bt709/unknown/unknown)", "fps": 25.0, "size": (1920, 1080)}


def test_decode_recording_reports_phases_endpoints_rings_and_skips_hidden(monkeypatch):
    frames = ([synthetic_frame("slide2-live", n) for n in range(0, 30)]
              + [synthetic_frame("slide2-hidden", None) for _ in range(5)]
              + [synthetic_frame("slide2-handback", n, poke=n == 50) for n in range(40, 60)])
    meta = dict(META)
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
    meta = dict(META)
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
    meta = dict(META)
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
    meta = dict(META)
    slot_edge_at_poke = (float(poke_x - 2), 700.0, 100.0, 200.0)
    far_slot = (1500.0, 100.0, 50.0, 50.0)
    for exclude, expect in (([slot_edge_at_poke], 0), ([far_slot], 255)):
        monkeypatch.setattr(decode, "read_frames", lambda _path: (meta, iter(frames)))
        result = decode.decode_recording(Path("x.avi"), rings=[RING_RECT], ring_exclude=exclude)
        assert result["ringMaxDelta"]["slide2-handback"] == expect


def test_over20_count_is_the_max_per_frame_count_not_the_count_on_the_max_delta_frame(monkeypatch):
    frames = [synthetic_frame("slide2-handback", n) for n in range(6)]
    y = int(RING_RECT[1]) - 4
    frames[2][y, int(RING_RECT[0]) + 10] = 255
    for dx in range(5):
        frames[4][y, int(RING_RECT[0]) + 100 + dx] = 30
    monkeypatch.setattr(decode, "read_frames", lambda _path: (dict(META), iter(frames)))
    diag = decode.decode_recording(Path("x.avi"), rings=[RING_RECT])["ringDiag"]["slide2-handback"]
    assert diag["worstFrame"] == 2 and diag["overTau"]["count"] == 1
    assert diag["over20"]["count"] == 5 and diag["over20"]["frame"] == 4


# Binary counter (p2-binary fixture). Synthetic frames are the generator's own luma frames (tv-range Y -> full-range RGB,
# the conversion a <video> decode applies), resized to the harness's slide-2 movie rect and pasted into a 1080p output
# frame, optionally shifted and passed through a midtone curve like Chromium's native video layer applies.

import binary_counter_movie as movie  # noqa: E402
from PIL import Image, ImageFont  # noqa: E402

FONT = ImageFont.load_default(size=movie.DIGITS_SIZE)
SCALE = 952 / 1920


def movie_rgb(index: int) -> np.ndarray:
    y = movie.luma_frame(index, FONT).astype(np.float32)
    grey = np.clip(np.round((y - 16) * 255 / 219), 0, 255).astype(np.uint8)
    return np.repeat(grey[..., None], 3, axis=2)


def tone_curve(rgb: np.ndarray, lift: float = 11.0) -> np.ndarray:
    x = rgb.astype(np.float32) / 255
    return np.clip(np.round(rgb + lift * 4 * x * (1 - x)), 0, 255).astype(np.uint8)


def binary_frame(phase: str, index: int | None, offset: tuple[int, int] = (0, 0), curve: bool = False) -> np.ndarray:
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:24, :24] = decode.PHASES[phase]
    if index is not None:
        src = movie_rgb(index)
        if curve:
            src = tone_curve(src)
        scaled = np.asarray(Image.fromarray(src).resize((952, 268), Image.BILINEAR))
        x, y = 109 + offset[0], 795 + offset[1]
        frame[y:y + 268, x:x + 952] = scaled
    return frame


@pytest.mark.parametrize("index", [0, 1, 1380, 4095])
def test_read_strip_round_trips_at_source_scale(index):
    assert decode.read_strip(movie_rgb(index), (0.0, 0.0), 1.0) == (index, "ok")


@pytest.mark.parametrize("offset", [(0, 0), (-3, -3), (3, 3), (3, -3), (-1, 3)])
@pytest.mark.parametrize("index", [0, 1, 1380])
def test_read_strip_window_finds_the_scaled_strip_under_a_shift(index, offset):
    frame = binary_frame("slide2-live", index, offset)
    window = decode.strip_window(frame)
    assert decode.read_strip_window(window, offset) == (index, "ok")


def test_a_midtone_tone_curve_does_not_move_the_binary_counter():
    for index in (0, 1, 682, 1380):
        window = decode.strip_window(binary_frame("slide2-live", index, curve=True))
        assert decode.read_strip_window(window, (0, 0)) == (index, "ok")


def flip_block(rgb: np.ndarray, block: int) -> np.ndarray:
    out = rgb.copy()
    bx, by, bw, bh = movie.BLOCK_RECTS[block]
    out[by:by + bh, bx:bx + bw] = 255 - out[by:by + bh, bx:bx + bw]
    return out


def test_a_flipped_parity_or_data_bit_reads_none_parity():
    parity = len(movie.START) + movie.DATA_BITS
    assert decode.read_strip(flip_block(movie_rgb(1380), parity), (0.0, 0.0), 1.0) == (None, "parity")
    assert decode.read_strip(flip_block(movie_rgb(1380), len(movie.START)), (0.0, 0.0), 1.0) == (None, "parity")


def test_a_broken_marker_or_a_mid_grey_block_reads_none():
    assert decode.read_strip(flip_block(movie_rgb(5), 0), (0.0, 0.0), 1.0) == (None, "marker")
    grey = movie_rgb(5)
    bx, by, bw, bh = movie.BLOCK_RECTS[4]
    grey[by:by + bh, bx:bx + bw] = 128
    assert decode.read_strip(grey, (0.0, 0.0), 1.0) == (None, "ambiguous")
    assert decode.read_strip(np.zeros((40, 40, 3), np.uint8), (0.0, 0.0), 1.0) == (None, "bounds")


def test_decode_recording_auto_selects_binary_and_reports_indices_without_wrap(monkeypatch):
    frames = ([binary_frame("slide1-native", n, (-1, 3)) for n in range(200, 230)]
              + [binary_frame("slide2-live", n) for n in range(300, 330)]
              + [binary_frame("slide2-handback", n) for n in range(330, 340)])
    frames[45] = frames[45].copy()
    frames[45][795:1063, 109:1061] = 255 - frames[45][795:1063, 109:1061]
    monkeypatch.setattr(decode, "read_frames", lambda _path: (dict(META), iter(frames)))
    result = decode.decode_recording(Path("x.avi"))
    assert result["counter"] == "binary" and result["roi"] is None and result["maxResidual"] is None
    native_offset, live_offset = (result["roiOffsets"][name]["offset"] for name in ("slide1-native", "slide2-live"))
    assert abs(native_offset[0] + 1) <= 1 and abs(native_offset[1] - 3) <= 1, native_offset
    assert abs(live_offset[0]) <= 1 and abs(live_offset[1]) <= 1, live_offset
    assert result["roiOffsets"]["slide2-live"]["fails"] == {"marker": 1}
    native = result["phases"]["slide1-native"]
    assert native["decodableFrac"] == 1.0 and native["backwardSteps"] == 0 and native["maxForwardStep"] == 1
    assert result["endpoints"]["slide1-native"] == {"first": [2, 202], "last": [27, 227]}
    assert result["endpoints"]["slide2-live"]["first"] == [32, 302]
    assert result["handbackCounters"] == list(range(330, 340))


def test_decode_recording_explicit_grey_ignores_a_binary_strip(monkeypatch):
    frames = [binary_frame("slide2-live", n) for n in range(10)]
    monkeypatch.setattr(decode, "read_frames", lambda _path: (dict(META), iter(frames)))
    assert decode.decode_recording(Path("x.avi"), counter="grey")["counter"] == "grey"


def test_decode_recording_auto_keeps_grey_on_the_p2_index_patch(monkeypatch):
    frames = [synthetic_frame("slide2-live", n) for n in range(10)]
    monkeypatch.setattr(decode, "read_frames", lambda _path: (dict(META), iter(frames)))
    result = decode.decode_recording(Path("x.avi"))
    assert result["counter"] == "grey" and result["phases"]["slide2-live"]["decodableFrac"] == 1.0


def binary_stats(values: list[int], loop_frames: int | None = None) -> dict:
    padded = [values[0]] * decode.EDGE_TRIM + values + [values[-1]] * decode.EDGE_TRIM
    return decode.phase_stats(padded, 0.0, 25.0, loop_frames, "binary")


def test_binary_forward_skip_sets_max_forward_step():
    result = binary_stats(list(range(60, 63)) + list(range(73, 90)))
    assert result["maxForwardStep"] == 11 and result["backwardSteps"] == 0 and result["gapsGE3"] == 1


def test_binary_counts_past_220_without_rollover():
    result = binary_stats(list(range(200, 260)))
    assert result["backwardSteps"] == 0 and result["maxForwardStep"] == 1 and result["deltaHist"] == {"1": 59}


def test_binary_backward_step_and_loop_wrap():
    assert binary_stats(list(range(50, 80)) + list(range(60, 90)))["backwardSteps"] == 1
    wrap = binary_stats(list(range(SOAK_LOOP_FRAMES - 20, SOAK_LOOP_FRAMES)) + list(range(0, 20)), SOAK_LOOP_FRAMES)
    assert (wrap["wrapSteps"], wrap["backwardSteps"]) == (1, 0)
    soak = binary_stats(list(range(SOAK_LOOP_FRAMES - 20, SOAK_LOOP_FRAMES)) + list(range(3, 20)), SOAK_LOOP_FRAMES)
    assert (soak["wrapSteps"], soak["backwardSteps"], soak["maxWrapStep"]) == (1, 0, 4)
    over = binary_stats(list(range(SOAK_LOOP_FRAMES - 20, SOAK_LOOP_FRAMES)) + list(range(4, 20)), SOAK_LOOP_FRAMES)
    assert (over["wrapSteps"], over["backwardSteps"]) == (0, 1)
    mid = binary_stats(list(range(500, 540)) + list(range(0, 20)), SOAK_LOOP_FRAMES)
    assert (mid["wrapSteps"], mid["backwardSteps"]) == (0, 1)


def test_binary_jump_across_an_undecodable_frame_is_not_hidden():
    result = binary_stats([60, 61, 62, None, 73, 74, 75])
    assert result["maxForwardStep"] == 11 and result["maxStepPerFrame"] == 5.5
    assert result["maxStepWindow"] == [2, 4] and result["undecodableNearMaxStep"] == 1
    assert result["deltaHist"] == {"1": 4} and result["decodable"] == 6


def test_binary_steady_run_across_an_undecodable_frame_is_one_per_frame():
    result = binary_stats([60, 61, 62, None, 64, 65, 66])
    assert result["maxForwardStep"] == 2 and result["maxStepPerFrame"] == 1.0 and result["backwardSteps"] == 0


def test_binary_backward_step_across_an_undecodable_frame_is_counted():
    result = binary_stats([60, 61, 62, None, 50, 51, 52])
    assert result["backwardSteps"] == 1 and result["maxStepPerFrame"] == 1.0


def test_binary_advance_excludes_backward_and_wrap_steps():
    assert binary_stats(list(range(50, 80)) + list(range(60, 90)))["advancePerS"] == round(58 / (60 / 25.0), 2)


def test_grey_jump_across_an_undecodable_frame_is_not_hidden():
    padded = [60, 60, 60, 61, 62] + [None] + [73, 74, 75, 75, 75]
    greys = [None if n is None else int(round(n * decode.STEP + 0.52)) for n in padded]
    result = decode.phase_stats(greys, 0.52, 25.0)
    assert result["maxForwardStep"] == 11 and result["maxStepPerFrame"] == 5.5 and result["undecodableNearMaxStep"] == 1


def test_soak_schedule_refuses_a_soak_without_a_minute_after_the_context_loss():
    with pytest.raises(ValueError):
        managed_obs_qualify.soak_schedule(3)


@pytest.mark.parametrize("minutes,lose_at,windows", [(4, 3, (1, 2)), (5, 3, (1, 2)), (20, 11, (1, 10))])
def test_soak_schedule_records_two_wrap_windows_before_context_loss_at_any_length(minutes, lose_at, windows):
    assert managed_obs_qualify.soak_schedule(minutes) == (lose_at, windows)
    assert all(w < lose_at < minutes for w in windows)

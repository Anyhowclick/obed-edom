"""Offline P2 probe tests. Do not launch Keynote or a browser."""

from __future__ import annotations

import numpy as np
import pytest

from obed_edom.html_alpha_probe import (
    LINEDRAW,
    LINEDRAW_FOR_LINE,
    PLAYER_RAF_ASSIGN,
    ProbeStructureError,
    analyze_rgba,
    black_content_ok,
    capability_row,
    color_key_near_black,
    decoded_alpha_report,
    iwa_click_groups,
    kpf_operator_events,
    leftover_object_layers,
    make_black_content_fixture,
    merge_linedraw_companions,
    page_websocket_url,
    current_slide_query_url,
    painted_identity,
    patch_index_html,
    progress_metric,
    source_has_genuine_alpha,
    timing_repeatability,
)


def test_linedraw_companion_is_one_click():
    groups = [
        [{"effect": LINEDRAW, "automatic": False, "referent": True}],
        [{"effect": LINEDRAW_FOR_LINE, "automatic": True, "referent": True}],
    ]
    merged = merge_linedraw_companions(groups)
    assert len(merged) == 1
    assert [item["effect"] for item in merged[0]] == [LINEDRAW, LINEDRAW_FOR_LINE]


def test_iwa_click_groups_folds_automatic_companions():
    objects = {
        "c1": {
            "_pbtype": "KN.BuildChunkArchive",
            "referent": True,
            "automatic": False,
            "delay": 0,
            "build": {"identifier": "b1"},
        },
        "c2": {
            "_pbtype": "KN.BuildChunkArchive",
            "referent": True,
            "automatic": True,
            "delay": 0,
            "build": {"identifier": "b2"},
        },
        "c3": {
            "_pbtype": "KN.BuildChunkArchive",
            "referent": True,
            "automatic": True,
            "delay": 0,
            "build": {"identifier": "b3"},
        },
        "b1": {"attributes": {"animationAttributes": {"effect": LINEDRAW, "animationType": "In"}}},
        "b2": {"attributes": {"animationAttributes": {"effect": LINEDRAW_FOR_LINE, "animationType": "In"}}},
        "b3": {"attributes": {"animationAttributes": {"effect": "apple:dissolve", "animationType": "In"}}},
    }
    slide = {
        "buildChunks": [
            {"identifier": "c1"},
            {"identifier": "c2"},
            {"identifier": "c3"},
        ]
    }
    groups = iwa_click_groups(objects, slide)
    assert groups["operatorClickCount"] == 1
    assert groups["settledStateCount"] == 2
    assert [item["effect"] for item in groups["operatorClicks"][0]] == [
        LINEDRAW,
        LINEDRAW_FOR_LINE,
        "apple:dissolve",
    ]
    assert groups["automaticOnShow"] == []


def test_kpf_nested_linedraw_is_one_event():
    payload = {
        "events": [
            {
                "automaticPlay": False,
                "effects": [
                    {
                        "type": "buildIn",
                        "name": LINEDRAW,
                        "effects": [
                            {"type": "buildIn", "name": LINEDRAW_FOR_LINE, "effects": [
                                {"type": "buildIn", "name": "apple:dissolve", "effects": []}
                            ]}
                        ],
                    }
                ],
            },
            {"automaticPlay": False, "effects": [{"type": "transition", "name": "none", "effects": []}]},
        ]
    }
    clicks = kpf_operator_events(payload)
    assert len(clicks) == 1
    names = [item["name"] for item in clicks[0]["effects"]]
    assert names == [LINEDRAW, LINEDRAW_FOR_LINE, "apple:dissolve"]


def test_black_content_rejects_color_key():
    fixture = make_black_content_fixture(size=(1920, 1080))
    assert black_content_ok(fixture)
    report = analyze_rgba(fixture, content_rects=[{"x": 200, "y": 200, "width": 600, "height": 200}])
    assert report["pass"]
    assert report["transparentFrac"] >= 0.05
    keyed = color_key_near_black(fixture)
    assert not black_content_ok(keyed)
    # A global alpha_min==0 check would still "pass" after colour-keying.
    assert int(keyed[:, :, 3].min()) == 0


def test_alpha_min_zero_alone_is_not_a_pass():
    arr = np.full((1080, 1920, 4), 255, dtype=np.uint8)
    arr[0, 0, 3] = 0
    report = analyze_rgba(arr)
    assert report["alphaMin"] == 0
    assert not report["pass"]
    assert any("alpha_min==0" in reason or "transparent_frac" in reason for reason in report["failReasons"])


def test_patch_refuses_unknown_player():
    html = (
        '<html><body id="body" bgcolor="black">'
        '<div id="stageArea"></div><div id="stage"></div>'
        '<script src="assets/player/main.js"></script></body></html>'
    )
    with pytest.raises(ProbeStructureError, match="requestAnimFrame"):
        patch_index_html(html, "function unrelated(){}")


def test_patch_injects_versioned_probe():
    html = (
        '<html><body id="body" bgcolor="black">'
        '<div id="stageArea"></div><div id="stage"></div>'
        '<script src="assets/player/main.js"></script></body></html>'
    )
    js = f"prefix;{PLAYER_RAF_ASSIGN};suffix"
    patched = patch_index_html(html, js)
    assert 'bgcolor="black"' not in patched
    assert 'data-obed-p2-probe="4"' in patched
    assert "window.requestAnimationFrame" in patched
    assert "jumpToSlide(" not in patched
    assert 'src="assets/player/main.js"' in patched


def test_capability_refuses_magic_move_and_skipped():
    skipped = capability_row(
        ordinal=2,
        skipped=True,
        magic_move=False,
        has_character=False,
        has_build_out=False,
        has_movie=False,
        has_line_draw=False,
        iwa_clicks=0,
        kpf_clicks=None,
        capture=None,
        alpha=None,
    )
    assert skipped["refusals"]
    assert not skipped["supportedStaticAlpha"]
    magic = capability_row(
        ordinal=11,
        skipped=False,
        magic_move=True,
        has_character=False,
        has_build_out=False,
        has_movie=True,
        has_line_draw=False,
        iwa_clicks=0,
        kpf_clicks=None,
        capture=None,
        alpha=None,
        canvas=(7680.0, 1080.0),
    )
    assert any("Magic Move" in item for item in magic["refusals"])
    assert any("7680" in item for item in magic["refusals"])
    assert not magic["supportedAnimatedAlpha"]


def test_timing_repeatability_uses_declared_tolerance():
    frame = make_black_content_fixture(size=(64, 64))
    run_a = [(i / 30, frame) for i in range(4)]
    run_b = [(i / 30, frame) for i in range(4)]
    holds = timing_repeatability(run_a, run_b)
    assert not holds["pass"]
    assert holds["motionSampled"] is False
    assert holds["declaredMaeMax"] == 0.02
    other = np.zeros_like(frame)
    other[10:20, 10:20] = (255, 255, 255, 255)
    motion_a = [(0.0, frame), (1 / 30, other), (2 / 30, other), (3 / 30, other)]
    motion_b = [(0.0, frame), (1 / 30, other), (2 / 30, other), (3 / 30, other)]
    report = timing_repeatability(motion_a, motion_b)
    assert report["motionSampled"]
    assert report["pass"]
    drifted_b = [(i / 30, other) for i in range(4)]
    assert progress_metric(frame) != progress_metric(other)
    assert not timing_repeatability(motion_a, drifted_b)["pass"]


def test_page_websocket_url_ignores_browser_target():
    browser = {"type": "browser", "webSocketDebuggerUrl": "ws://127.0.0.1:1/browser"}
    page = {"type": "page", "url": "about:blank", "webSocketDebuggerUrl": "ws://127.0.0.1:1/page"}
    assert page_websocket_url([browser]) is None
    assert page_websocket_url([browser, page]) == "ws://127.0.0.1:1/page"

def _solid_plate(rgb, size=(64, 48)):
    arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    arr[:, :, :3] = rgb
    arr[:, :, 3] = 255
    return arr


def test_painted_identity_rejects_leftover_matthew_as_genesis():
    matthew = _solid_plate((40, 20, 80))
    genesis = _solid_plate((10, 90, 30))
    photo = _solid_plate((200, 120, 90))
    rasters = {1: [matthew], 3: [genesis], 4: [photo]}
    leftover = painted_identity(
        matthew,
        ordinal=3,
        expected_hash="#1",
        live_hash="#1",
        rasters_by_ordinal=rasters,
        previous_plates={1: matthew},
    )
    assert not leftover["pass"]
    assert any("near-duplicate of slide 1" in r for r in leftover["reasons"])

    genuine = painted_identity(
        genesis,
        ordinal=3,
        expected_hash="#1",
        live_hash="#1",
        rasters_by_ordinal=rasters,
        previous_plates={1: matthew},
    )
    assert genuine["pass"]


def test_painted_identity_empty_slide_must_match_own_raster():
    genesis = _solid_plate((10, 90, 30))
    photo = _solid_plate((200, 120, 90))
    rasters = {3: [genesis], 4: [photo]}
    stale = painted_identity(
        genesis,
        ordinal=4,
        expected_hash="#2",
        live_hash="#2",
        rasters_by_ordinal=rasters,
        previous_plates={3: genesis},
    )
    assert not stale["pass"]
    own = painted_identity(
        photo,
        ordinal=4,
        expected_hash="#2",
        live_hash="#2",
        rasters_by_ordinal=rasters,
        previous_plates={3: genesis},
    )
    assert own["pass"]


def test_painted_identity_hash_mismatch():
    plate = _solid_plate((1, 2, 3))
    landed = painted_identity(
        plate,
        ordinal=1,
        live_hash="#1",
        rasters_by_ordinal={1: [plate]},
        previous_plates={},
        expected_starting_scene=0,
        require_starting_scene=True,
    )
    assert not landed["pass"]
    assert any("starting scene" in r for r in landed["reasons"])
    same_slide_next_scene = painted_identity(
        plate,
        ordinal=1,
        live_hash="#1",
        rasters_by_ordinal={1: [plate]},
        previous_plates={},
        expected_starting_scene=0,
        require_starting_scene=False,
    )
    assert same_slide_next_scene["pass"]



def test_painted_identity_fails_when_own_raster_evidence_weak():
    """Own MAE above useful max must fail — must not skip near-dup checks."""
    plate = _solid_plate((10, 90, 30))
    weak_own = _solid_plate((200, 10, 10))  # far from plate
    other = _solid_plate((40, 20, 80))
    got = painted_identity(
        plate,
        ordinal=3,
        live_hash="#1",
        rasters_by_ordinal={3: [weak_own], 1: [other]},
        previous_plates={1: other},
    )
    assert not got["pass"]
    assert any("exceeds useful max" in r or "insufficient" in r for r in got["reasons"])

def test_current_slide_query_strips_hash():
    url = current_slide_query_url("http://127.0.0.1:9/index.html#1", 3)
    assert url == "http://127.0.0.1:9/index.html?currentSlide=3"
    assert "#" not in url


def test_leftover_object_layers_match_previous_slide():
    layers = [{"used": True, "w": 400, "h": 80, "x": 10.0, "y": 900.0}]
    assert leftover_object_layers(layers, {3: layers}) == "object layers match leftover slide 3"
    assert leftover_object_layers(layers, {3: [{"used": True, "w": 10, "h": 10, "x": 0, "y": 0}]}) is None


def test_capability_refuses_identity_miss_and_object_composite():
    miss = capability_row(
        ordinal=3,
        skipped=False,
        magic_move=False,
        has_character=False,
        has_build_out=False,
        has_movie=False,
        has_line_draw=True,
        iwa_clicks=1,
        kpf_clicks=1,
        capture={"identity": {"pass": False, "reasons": ["near-duplicate of slide 1"]}},
        alpha={"pass": True, "source": "page-screenshot"},
    )
    assert miss["identity"] is False
    assert not miss["supportedStaticAlpha"]
    assert any("identity:" in item for item in miss["refusals"])
    obj = capability_row(
        ordinal=4,
        skipped=False,
        magic_move=False,
        has_character=False,
        has_build_out=False,
        has_movie=False,
        has_line_draw=False,
        iwa_clicks=0,
        kpf_clicks=0,
        capture={"identity": {"pass": True, "reasons": []}},
        alpha={"pass": True, "source": "object-canvases"},
    )
    assert any("object-composite" in item for item in obj["refusals"])
    assert not obj["supportedStaticAlpha"]


def test_decoded_alpha_opaque_source_is_not_a_pass(tmp_path):
    opaque = np.full((8, 8, 4), 255, dtype=np.uint8)
    opaque[:, :, :3] = 10
    assert not source_has_genuine_alpha([opaque, opaque])
    from PIL import Image

    paths = []
    for i in range(2):
        path = tmp_path / f"f{i}.png"
        Image.fromarray(opaque, "RGBA").save(path)
        paths.append(path)
    report = decoded_alpha_report([opaque, opaque], paths)
    assert report["maxAlphaMae"] == 0
    assert report["sourceHasGenuineAlpha"] is False
    assert report["pass"] is False


def test_frozen_clock_does_not_continue_through_dissolve():
    from obed_edom.html_alpha_probe import score_playback_continuity

    # Review counterexample: 44 identical timestamps at 3.0s after a matching handoff.
    times = [3.0] + [3.0] * 43
    scored = score_playback_continuity(times, click_i=0, dissolve_s=1.5)
    assert scored["positionContinuous"] is True
    assert scored["frozenClock"] is True
    assert scored["mediaProgressing"] is False
    assert scored["continuesThroughDissolve"] is False
    assert scored["advancingPairs"] == 0
    assert scored["dissolveAdvanceS"] == 0.0


def test_advancing_handoff_continues_through_dissolve():
    from obed_edom.html_alpha_probe import score_playback_continuity

    # Pre at 3.0; post-click samples advance ~1 media-second across dissolve.
    times = [3.0] + [3.0 + i * 0.05 for i in range(1, 31)]
    caps = [None] + [i * 0.05 for i in range(1, 31)]
    scored = score_playback_continuity(
        times, click_i=0, capture_offsets=caps, dissolve_s=1.5, min_advance_ratio=0.35
    )
    assert scored["positionContinuous"] is True
    assert scored["frozenClock"] is False
    assert scored["mediaProgressing"] is True
    assert scored["continuesThroughDissolve"] is True
    assert scored["remountRestart"] is False


def test_presented_all_none_falls_back_to_current_time():
    from obed_edom.html_alpha_probe import score_playback_continuity

    times = [3.0] + [3.0 + i * 0.05 for i in range(1, 31)]
    presented = [None] * len(times)
    scored = score_playback_continuity(
        times, click_i=0, presented_times=presented, dissolve_s=1.5
    )
    assert scored["continuesThroughDissolve"] is True


def test_strip_pdf_page_bg_fill_solo_and_inline():
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    from obed_edom.html_alpha_probe import strip_pdf_page_bg_fill

    solo = b"q Q q /Cs1 cs 0 0 0 sc 0 1080 m 1920 1080 l 1920 0 l 0 0 l h f Q"
    inline = (
        b"q Q q /Cs1 cs 0 0 0 sc 0 1080 m 1920 1080 l 1920 0 l 0 0 l h f "
        b"/Perceptual\nri q 1 0 0 1 0 0 cm /Im1 Do Q Q"
    )
    other = b"q Q q /Perceptual ri q 1 0 0 1 0 0 cm /Im1 Do Q Q"

    def page_with(raw: bytes):
        w = PdfWriter()
        w.add_blank_page(width=1920, height=1080)
        stream = DecodedStreamObject()
        stream.set_data(raw)
        w.pages[0][NameObject("/Contents")] = stream
        import io

        buf = io.BytesIO()
        w.write(buf)
        return PdfReader(io.BytesIO(buf.getvalue())).pages[0]

    s = strip_pdf_page_bg_fill(page_with(solo))
    assert s["stripped"] is True and s["kind"] == "solo"
    i = strip_pdf_page_bg_fill(page_with(inline))
    assert i["stripped"] is True and i["kind"] == "inline"
    n = strip_pdf_page_bg_fill(page_with(other))
    assert n["stripped"] is False


def test_remount_at_zero_fails_continuity():
    from obed_edom.html_alpha_probe import score_playback_continuity

    times = [4.5] + [0.01 + i * 0.05 for i in range(30)]
    scored = score_playback_continuity(times, click_i=0, dissolve_s=1.5)
    assert scored["remountRestart"] is True
    assert scored["positionContinuous"] is False
    assert scored["continuesThroughDissolve"] is False


def test_mid_transition_jump_fails_continuity():
    """Review counterexample: smooth start then a seek jump must not pass."""
    from obed_edom.html_alpha_probe import score_playback_continuity

    # 3.0, 3.05, 3.10, 5.0, 5.05, ...
    times = [3.0, 3.05, 3.10] + [5.0 + i * 0.05 for i in range(28)]
    caps = [i * 0.05 for i in range(len(times))]
    scored = score_playback_continuity(
        times, click_i=0, capture_offsets=caps, dissolve_s=1.5
    )
    assert scored["noJump"] is False
    assert scored["rateInconsistentPairs"] >= 1
    assert scored["continuesThroughDissolve"] is False


def test_sparse_capture_wall_paced_not_jump():
    """Large media Δ with matching capture Δ is undersampling, not a seek."""
    from obed_edom.html_alpha_probe import score_playback_continuity

    times = [3.0]
    caps: list[float | None] = [None]
    t = 3.0
    c = 0.0
    # ~20fps intent, but a few 1.0s capture stalls where media keeps pace.
    for i in range(30):
        if i in (4, 8, 12):
            t += 1.0
            c += 1.0
        else:
            t += 0.05
            c += 0.05
        times.append(t)
        caps.append(c)
    scored = score_playback_continuity(
        times, click_i=0, capture_offsets=caps, dissolve_s=1.5
    )
    assert scored["jumpsAfterClick"] == 0
    assert scored["rateInconsistentPairs"] == 0
    assert scored["noJump"] is True
    assert scored["mediaProgressing"] is True
    assert scored["continuesThroughDissolve"] is True


def test_visible_movie_motion_rejects_single_mid_window_cut():
    """22 stills with one change halfway must fail — not continuous playback."""
    from obed_edom.html_alpha_probe import score_visible_movie_motion

    a = np.zeros((80, 160, 3), dtype=np.uint8)
    b = np.full((80, 160, 3), 80, dtype=np.uint8)
    frames = [a.copy() for _ in range(11)] + [b.copy() for _ in range(11)]
    scored = score_visible_movie_motion(frames)
    assert scored["identicalPairFrac"] >= 20 / 21
    assert scored["changingPairs"] == 1
    assert scored["ok"] is False


def test_visible_movie_motion_requires_early_and_late_change():
    from obed_edom.html_alpha_probe import score_visible_movie_motion

    frames = []
    for i in range(12):
        arr = np.zeros((40, 80, 3), dtype=np.uint8)
        arr[:, :] = (i * 20) % 200
        frames.append(arr)
    scored = score_visible_movie_motion(frames, min_changing_frac=0.45)
    assert scored["ok"] is True
    assert scored["earlyMaxPairMae"] >= 2.0
    assert scored["lateMaxPairMae"] >= 2.0


def test_visible_movie_motion_rejects_frozen_sequence():
    from obed_edom.html_alpha_probe import score_visible_movie_motion

    frames = [np.zeros((40, 80, 3), dtype=np.uint8) for _ in range(10)]
    scored = score_visible_movie_motion(frames)
    assert scored["ok"] is False
    assert scored["changingPairs"] == 0


def test_visible_movie_motion_rejects_empty_crops():
    """Empty / zero-sized crops must not pass via infinite MAE."""
    from obed_edom.html_alpha_probe import score_visible_movie_motion

    empty = np.zeros((0, 80, 3), dtype=np.uint8)
    frames = [empty for _ in range(22)]
    scored = score_visible_movie_motion(frames)
    assert scored["ok"] is False
    assert scored["reason"] == "empty crop"

    # Mismatched shapes previously yielded inf MAE → false motion.
    a = np.zeros((40, 80, 3), dtype=np.uint8)
    b = np.zeros((0, 80, 3), dtype=np.uint8)
    scored2 = score_visible_movie_motion([a, b, a, b, a, b])
    assert scored2["ok"] is False
    assert scored2["reason"] in ("empty crop", "mismatched crop shapes")


def test_restart_boundary_rejects_preboundary_only():
    """Restart during drain without slide-3 media must not pass."""
    from obed_edom.html_alpha_probe import score_restart_at_slide_boundary

    # Reached slide 3 but no observations for the intended movie.
    scored = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=["untitled.mov"],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 0,
                "earliest": None,
                "nearZeroAtBoundary": False,
                "progressedAfterRestart": False,
                "decodedWidthAtBoundary": False,
                "ok": False,
            }
        },
        canvas_all_identical=False,
    )
    assert scored["ok"] is False
    assert scored["verdict"] == "inconclusive"
    assert scored["missingSlide3Media"] == ["untitled.mov"]

    # Expected key absent from per_movie entirely.
    scored_missing = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=["untitled.mov", "other.mov"],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 4,
                "earliest": {"t": 0.05, "w": 1920},
                "nearZeroAtBoundary": True,
                "progressedAfterRestart": True,
                "decodedWidthAtBoundary": True,
                "ok": True,
            }
        },
        canvas_all_identical=False,
    )
    assert scored_missing["ok"] is False
    assert "other.mov" in scored_missing["missingSlide3Media"]

    # Audio-only (no decoded width) must not pass.
    scored_audio = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=["untitled.mov"],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 4,
                "earliest": {"t": 0.05, "w": 0},
                "nearZeroAtBoundary": True,
                "progressedAfterRestart": True,
                "decodedWidthAtBoundary": False,
                "ok": True,  # even if caller set ok, width gate catches it
            }
        },
        canvas_all_identical=False,
    )
    assert scored_audio["ok"] is False
    assert scored_audio["missingDecodedWidth"] == ["untitled.mov"]

    # Drain-time restart signal alone (empty expected) must fail.
    scored2 = score_restart_at_slide_boundary(
        reached_slide=True, expected_keys=[], per_movie={}, canvas_all_identical=False
    )
    assert scored2["ok"] is False
    assert scored2["verdict"] == "fail"

    # Observed-key fallback is gone — empty expected cannot pass via per_movie keys.
    scored_obs = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=[],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 4,
                "earliest": {"t": 0.05, "w": 1920},
                "nearZeroAtBoundary": True,
                "progressedAfterRestart": True,
                "decodedWidthAtBoundary": True,
                "ok": True,
            }
        },
        canvas_all_identical=False,
    )
    assert scored_obs["ok"] is False
    assert scored_obs["expectedKeys"] == []

    # Proper boundary: near-zero + progression + decoded width + presented motion.
    scored3 = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=["untitled.mov"],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 4,
                "earliest": {"t": 0.05, "w": 1920},
                "nearZeroAtBoundary": True,
                "progressedAfterRestart": True,
                "decodedWidthAtBoundary": True,
                "presentedMotionOk": True,
                "ok": True,
            }
        },
        canvas_all_identical=False,
    )
    assert scored3["ok"] is True
    assert scored3["verdict"] == "pass"

    # currentTime + width progression alone (no presented-frame motion attested)
    # must not pass — another movie could satisfy whole-canvas non-identity.
    scored_no_presented_motion = score_restart_at_slide_boundary(
        reached_slide=True,
        expected_keys=["untitled.mov"],
        per_movie={
            "untitled.mov": {
                "slide3ObsN": 4,
                "earliest": {"t": 0.05, "w": 1920},
                "nearZeroAtBoundary": True,
                "progressedAfterRestart": True,
                "decodedWidthAtBoundary": True,
                "presentedMotionOk": False,
                "ok": True,
            }
        },
        canvas_all_identical=False,
    )
    assert scored_no_presented_motion["ok"] is False
    assert scored_no_presented_motion["missingPresentedMotion"] == ["untitled.mov"]


def test_restart_movie_rejects_preboundary_near_zero_that_continues():
    """A decoder near-zero at an earlier scene that merely continues onto the
    target slide (clock already far past near_zero_max_s once on-slide) is a
    continue-clock, not a restart — it must not masquerade as one (null control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        # Continued remount overlays from slide 1/2.
        {"t": 14.0, "w": 1920, "captureOffsetS": 4.0, "sceneHash": "#4", "decoderId": 1},
        {"t": 14.5, "w": 1920, "captureOffsetS": 4.5, "sceneHash": "#5", "decoderId": 1},
        {"t": 15.0, "w": 1920, "captureOffsetS": 5.0, "sceneHash": "#6", "decoderId": 1},
        # Decoder near-zero at an earlier scene (#4/#5), not the target slide (#6):
        # it merely continues onto #6 with a clock already past near_zero_max_s.
        {"t": 0.02, "w": 1920, "captureOffsetS": 4.1, "sceneHash": "#4", "decoderId": 3},
        {"t": 0.30, "w": 1920, "captureOffsetS": 4.4, "sceneHash": "#5", "decoderId": 3},
        {"t": 1.90, "w": 1920, "captureOffsetS": 6.1, "sceneHash": "#6", "decoderId": 3},
        # Null-width duplicate of the pre-boundary near-zero sample.
        {"t": 0.02, "w": None, "captureOffsetS": 4.1, "sceneHash": "#4", "decoderId": 3},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["nearZeroAtBoundary"] is False
    assert scored["ok"] is False

    # Sub-ms duplicate samples do not count as progression.
    scored_fast = score_restart_movie_from_observations(
        [
            {"t": 0.02, "w": 1920, "captureOffsetS": 1.0, "sceneHash": "#6", "decoderId": 1},
            {"t": 0.25, "w": 1920, "captureOffsetS": 1.0005, "sceneHash": "#6", "decoderId": 1},
        ],
        slide_min_hash=6,
    )
    assert scored_fast["nearZeroAtBoundary"] is True
    assert scored_fast["progressedAfterRestart"] is False
    assert scored_fast["ok"] is False


def test_restart_movie_accepts_near_zero_observed_on_boundary_slide():
    """A decoder whose near-zero clock is observed while already on the target
    slide, then progresses, is a genuine restart (positive control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        # Continued remount overlays from slide 1/2 — must not be picked.
        {"t": 14.0, "w": 1920, "captureOffsetS": 4.0, "sceneHash": "#4", "decoderId": 1},
        {"t": 14.5, "w": 1920, "captureOffsetS": 4.5, "sceneHash": "#5", "decoderId": 1},
        {"t": 15.0, "w": 1920, "captureOffsetS": 5.0, "sceneHash": "#6", "decoderId": 1},
        # Fresh decoder: near-zero clock observed already on the target slide.
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 3},
        {"t": 0.30, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 3},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["restartDecoderId"] == 3
    assert scored["nearZeroAtBoundary"] is True
    assert scored["progressedAfterRestart"] is True
    assert scored["decodedWidthAtBoundary"] is True
    assert scored["ok"] is True
    assert scored["slide3ObsN"] >= 1


def test_restart_movie_prefers_progressing_decoder_over_stalled_first():
    """A stalled boundary decoder listed first must not mask a genuine restart in
    another decoder that near-zeros and progresses (competing-candidate control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        # Decoder 1: near-zero on the boundary but stalls (single sample, no progression).
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 1},
        # Decoder 2: near-zero on the boundary and progresses with wall/media spacing.
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 2},
        {"t": 0.30, "w": 1920, "captureOffsetS": 6.4, "sceneHash": "#6", "decoderId": 2},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["restartDecoderId"] == 2
    assert scored["progressedAfterRestart"] is True
    assert scored["ok"] is True


def test_restart_movie_idless_rows_do_not_mix_into_a_pass():
    """Without decoderId, a stalled near-zero row and a different continued row must
    not be stitched into a single restart+progression (id-less null control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 0.02, "w": 1920, "captureOffsetS": 1.0, "sceneHash": "#6"},
        {"t": 12.0, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6"},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["nearZeroAtBoundary"] is True
    assert scored["progressedAfterRestart"] is False
    assert scored["ok"] is False


def test_restart_movie_rejects_preexisting_decoder_continuing_near_zero():
    """A decoder observed just before the boundary (not reset from a high
    clock) that happens to read near-zero right at the flip and then
    progresses is a continuing clock, not a restart (Codex repro).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 0.01, "w": 1920, "captureOffsetS": 5.9, "sceneHash": "#5", "decoderId": 7},
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 7},
        {"t": 0.35, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 7},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["restartDecoderId"] == 7
    assert scored["nearZeroAtBoundary"] is True
    assert scored["progressedAfterRestart"] is True
    assert scored["firstSeenAtBoundary"] is False
    assert scored["backwardReset"] is False
    assert scored["ok"] is False


def test_restart_movie_accepts_genuine_fresh_decoder_first_seen_at_boundary():
    """A decoder with no observations before the boundary that near-zeros and
    progresses is a genuine restart (positive control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 9},
        {"t": 0.30, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 9},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["firstSeenAtBoundary"] is True
    assert scored["backwardReset"] is False
    assert scored["ok"] is True


def test_restart_movie_accepts_genuine_backward_reset_decoder():
    """A decoder seen well before the boundary with a clock clearly above
    near_zero_max_s, then near-zero at the boundary and progressing, proves an
    actual reset rather than a coincidental near-zero read (positive control).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 12.0, "w": 1920, "captureOffsetS": 5.0, "sceneHash": "#5", "decoderId": 11},
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 11},
        {"t": 0.30, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 11},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["firstSeenAtBoundary"] is False
    assert scored["backwardReset"] is True
    assert scored["ok"] is True


def test_restart_movie_rejects_backward_reset_that_was_already_near_zero():
    """A decoder seen far from zero at some earlier point does not get a free
    pass on backwardReset if it was ALSO already near-zero before the
    boundary — that pre-boundary near-zero read is the real continuing clock,
    and the later high-t sample does not erase it (Codex repro:
    12@#4 -> 0.01@#5 -> 0.02@#6 -> 0.35@#6).
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 12.0, "w": 1920, "captureOffsetS": 4.0, "sceneHash": "#4", "decoderId": 12},
        {"t": 0.01, "w": 1920, "captureOffsetS": 5.9, "sceneHash": "#5", "decoderId": 12},
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 12},
        {"t": 0.35, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 12},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["restartDecoderId"] == 12
    assert scored["firstSeenAtBoundary"] is False
    assert scored["backwardReset"] is False
    assert scored["ok"] is False


def test_restart_movie_accepts_backward_reset_that_leads_directly_in():
    """A genuine backward reset with no pre-boundary near-zero read leads
    directly into the boundary candidate and must still pass.
    """
    from obed_edom.html_alpha_probe import score_restart_movie_from_observations

    obs = [
        {"t": 12.0, "w": 1920, "captureOffsetS": 5.0, "sceneHash": "#5", "decoderId": 13},
        {"t": 0.02, "w": 1920, "captureOffsetS": 6.0, "sceneHash": "#6", "decoderId": 13},
        {"t": 0.30, "w": 1920, "captureOffsetS": 6.3, "sceneHash": "#6", "decoderId": 13},
    ]
    scored = score_restart_movie_from_observations(obs, slide_min_hash=6)
    assert scored["firstSeenAtBoundary"] is False
    assert scored["backwardReset"] is True
    assert scored["ok"] is True


def _motion_sample(
    value: int,
    scene_hash: str,
    offset: float,
    w: int = 1920,
    decoder_id=1,
    movie_key="movie1.mov",
):
    roi = np.full((20, 20, 3), value % 256, dtype=np.uint8)
    return {
        "roi": roi,
        "sceneHash": scene_hash,
        "captureOffsetS": offset,
        "decoderId": decoder_id,
        "w": w,
        "movieKey": movie_key,
    }


def test_motion_across_flip_accepts_motion_before_across_and_after():
    """Positive control: motion in all three segments, flip mid-window."""
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(40, "#5", 0.2),
        _motion_sample(60, "#6", 0.3),
        _motion_sample(80, "#6", 0.4),
        _motion_sample(100, "#6", 0.5),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["ok"] is True
    assert scored["flipIndex"] == 3
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["crossingDecoded"] is True
    assert scored["crossingDecoderStable"] is True


def test_motion_across_flip_accepts_matching_expected_key_at_crossing():
    """A stable decoder feeding the expected movie's footprint across the
    crossing passes when expected_key is given (positive control).
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, movie_key="movie1.mov"),
        _motion_sample(80, "#6", 0.4, movie_key="movie1.mov"),
        _motion_sample(100, "#6", 0.5, movie_key="movie1.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["ok"] is True
    assert scored["crossingKeyOk"] is True
    assert scored["crossingMovieKeys"] == ["movie1.mov", "movie1.mov"]


def test_motion_across_flip_rejects_wrong_movie_key_at_crossing():
    """A stable decoder can still be feeding the WRONG movie's footprint
    across the crossing (e.g. two same-file decoders) — movieKey must match
    expected_key or the crossing must not pass.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, decoder_id=1, movie_key="movie2.mov"),
        _motion_sample(80, "#6", 0.4, decoder_id=1, movie_key="movie2.mov"),
        _motion_sample(100, "#6", 0.5, decoder_id=1, movie_key="movie2.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["crossingDecoded"] is True
    assert scored["crossingDecoderStable"] is True
    assert scored["crossingKeyOk"] is False
    assert scored["crossingMovieKeys"] == ["movie1.mov", "movie2.mov"]
    assert scored["ok"] is False
    assert scored["reason"] == "crossing movie key mismatch"


def test_motion_across_flip_rejects_decoder_switch_at_crossing():
    """A decoder handoff exactly at the flip (1 -> 2) must not pass as the
    target movie progressing — decoderId across the crossing must be stable.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1),
        _motion_sample(20, "#5", 0.1, decoder_id=1),
        _motion_sample(40, "#5", 0.2, decoder_id=1),
        _motion_sample(60, "#6", 0.3, decoder_id=2),
        _motion_sample(80, "#6", 0.4, decoder_id=2),
        _motion_sample(100, "#6", 0.5, decoder_id=2),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["crossingDecoded"] is True
    assert scored["crossingDecoderStable"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "crossing decoder switched"


def test_motion_across_flip_rejects_frozen_crossing():
    """Frozen-crossing control: before and after both move, but the single
    frame-pair straddling the flip itself is frozen — must not pass via the
    first post-flip pair moving instead.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(20, "#6", 0.2),
        _motion_sample(40, "#6", 0.3),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["flipIndex"] == 2
    assert scored["beforeOk"] is True
    assert scored["afterOk"] is True
    assert scored["acrossOk"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "frozen crossing"


def test_motion_across_flip_rejects_poster_frame_at_crossing():
    """Poster-frame control: the crossing pair moves (bars swap in) but the
    post-flip frame has no decoded movie width — must not pass on MAE alone.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(200, "#6", 0.2, w=0),
        _motion_sample(220, "#6", 0.3),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["crossingDecoded"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "crossing frame not decoded"


def test_motion_across_flip_rejects_flip_at_first_sample():
    """No pre-flip frame exists to prove before-motion."""
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#6", 0.0),
        _motion_sample(20, "#6", 0.1),
        _motion_sample(40, "#6", 0.2),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["ok"] is False
    assert scored["reason"] == "flip at first sample"
    assert scored["flipIndex"] == 0


def test_motion_across_flip_rejects_late_navigation():
    """Late-navigation control: motion only before the flip, frozen after — a
    continuously-playing movie plus a late navigation must not pass.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(40, "#5", 0.2),
        _motion_sample(60, "#6", 0.3),
        _motion_sample(60, "#6", 0.4),
        _motion_sample(60, "#6", 0.5),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["ok"] is False
    assert scored["afterOk"] is False


def test_motion_across_flip_rejects_mid_transition_disappearance():
    """Disappearance control: before/across/after each contain one moving
    pair, but frames freeze for a run longer than max_still_run spanning the
    flip — must fail on the still-run gate even though the per-segment motion
    checks alone would pass.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(20, "#5", 0.2),
        _motion_sample(40, "#6", 0.3),
        _motion_sample(40, "#6", 0.4),
        _motion_sample(40, "#6", 0.5),
        _motion_sample(40, "#6", 0.6),
        _motion_sample(40, "#6", 0.7),
        _motion_sample(40, "#6", 0.8),
        _motion_sample(60, "#6", 0.9),
        _motion_sample(80, "#6", 1.0),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", max_still_run=4)
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["maxStillRun"] > 4
    assert scored["ok"] is False
    assert scored["reason"] == "still run exceeds max across flip"


def test_motion_across_flip_no_flip_observed():
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [_motion_sample(i * 20, "#5", i * 0.1) for i in range(5)]
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["ok"] is False
    assert scored["reason"] == "no flip observed"


def test_motion_across_flip_rejects_empty_crop():
    """Empty crops are hard rejects — must not count as motion via infinite MAE."""
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0),
        _motion_sample(20, "#5", 0.1),
        _motion_sample(40, "#6", 0.2),
    ]
    samples[1]["roi"] = np.zeros((0, 20, 3), dtype=np.uint8)
    scored = score_motion_across_flip(samples, start_hash="#5")
    assert scored["ok"] is False
    assert scored["reason"] == "empty crop"


def test_visible_movie_motion_max_still_run_gate():
    """Documents the old gap: unset max_still_run passes a long mid-window
    stall; setting it small rejects the same sequence.
    """
    from obed_edom.html_alpha_probe import score_visible_movie_motion

    frames = []
    for i in range(6):
        frames.append(np.full((20, 20, 3), i * 30, dtype=np.uint8))
    still = np.full((20, 20, 3), frames[-1][0, 0, 0], dtype=np.uint8)
    frames += [still.copy() for _ in range(6)]
    for i in range(6):
        frames.append(np.full((20, 20, 3), 200 - i * 30, dtype=np.uint8))

    scored_unset = score_visible_movie_motion(frames, min_changing_frac=0.3)
    assert scored_unset["ok"] is True

    scored_gated = score_visible_movie_motion(
        frames, min_changing_frac=0.3, max_still_run=4
    )
    assert scored_gated["ok"] is False
    assert scored_gated["maxStillRun"] > 4



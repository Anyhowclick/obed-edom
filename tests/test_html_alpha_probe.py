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


def test_frozen_bound_clock_fails_despite_sibling_higher_clock():
    """Stream-C binding guard: the scorer must see ONLY the bound decoder's
    own clock. A max-of-same-key reduction would have merged a sibling
    decoder's higher clock over this frozen sequence and read it as progress;
    because the bound clock is the sole input, a stall on it cannot be masked.

    Here the bound decoder is frozen at 3.0s through the whole window (both the
    ``currentTime`` samples and the presented-frame samples). No sibling clock
    is passed — that is the point: the public signature admits one movie's
    times, so a sibling advancing elsewhere is structurally excluded and can
    never rescue this verdict.
    """
    from obed_edom.html_alpha_probe import score_playback_continuity

    frozen = [3.0] * 32
    caps = [i * 0.05 for i in range(len(frozen))]
    scored = score_playback_continuity(
        frozen,
        click_i=0,
        capture_offsets=caps,
        presented_times=list(frozen),
        dissolve_s=1.5,
    )
    assert scored["frozenClock"] is True
    assert scored["advancingPairs"] == 0
    assert scored["dissolveAdvanceS"] == 0.0
    assert scored["mediaProgressing"] is False
    assert scored["continuesThroughDissolve"] is False


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
    assert scored["windowKeyOk"] is True
    assert scored["afterDecoderStable"] is True


def test_motion_across_flip_rejects_decoder_handoff_later_in_after_window():
    """The crossing itself is a stable, correctly-keyed decoder, but it hands
    off to a different decoder later within the after-window (same movieKey
    throughout) — this must not pass as continuous target-decoder motion
    (Round-4 Codex repro: decoderId sequence [1,1,1,1,2,2] around the flip).
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(80, "#6", 0.4, decoder_id=2, movie_key="movie1.mov"),
        _motion_sample(100, "#6", 0.5, decoder_id=2, movie_key="movie1.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["beforeOk"] is True
    assert scored["acrossOk"] is True
    assert scored["afterOk"] is True
    assert scored["crossingDecoderStable"] is True
    assert scored["crossingKeyOk"] is True
    assert scored["windowKeyOk"] is True
    assert scored["afterDecoderIds"] == [1, 2, 2]
    assert scored["afterDecoderStable"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "after-flip decoder switched"


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


def test_motion_across_flip_rejects_same_key_handoff_at_flip():
    """Stream-C (a), at-the-flip half: a handoff exactly at the flip where both
    decoders carry the SAME movieKey must not pass. Identity is bound to one
    decoder across the crossing, so a same-key swap at the boundary is caught by
    the crossing-decoder check even though every movieKey matches expected_key.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, decoder_id=2, movie_key="movie1.mov"),
        _motion_sample(80, "#6", 0.4, decoder_id=2, movie_key="movie1.mov"),
        _motion_sample(100, "#6", 0.5, decoder_id=2, movie_key="movie1.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["windowKeyOk"] is True
    assert scored["crossingKeyOk"] is True
    assert scored["crossingDecoderStable"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "crossing decoder switched"


def test_motion_across_flip_rejects_single_late_restart_in_after_window():
    """Stream-C (a), restart-later half: a lone fresh decoder appearing only on
    the FINAL after-window sample (decoderId [1,1,1,1,1,2], one movieKey) must
    fail. The binding is unanimous, not a majority vote — a single late restart
    breaks the shared-decoder requirement even though the crossing and every
    movieKey are clean.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(80, "#6", 0.4, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(100, "#6", 0.5, decoder_id=2, movie_key="movie1.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["crossingDecoderStable"] is True
    assert scored["crossingKeyOk"] is True
    assert scored["windowKeyOk"] is True
    assert scored["afterDecoderIds"] == [1, 1, 2]
    assert scored["afterDecoderStable"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "after-flip decoder switched"


def test_motion_across_flip_rejects_frozen_bound_decoder_despite_stable_identity():
    """Stream-C (b): the bound decoder is frozen after the flip (its ROI does
    not change) while its identity stays perfectly stable — one decoderId, one
    movieKey. A max-of-same-key clock would let a sibling decoder's progress
    stand in for this stall; the scorer, bound to this decoder's own crop, must
    report no motion after the flip. Intact identity does not rescue a frozen
    bound decoder.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    samples = [
        _motion_sample(0, "#5", 0.0, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(20, "#5", 0.1, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(40, "#5", 0.2, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.3, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.4, decoder_id=1, movie_key="movie1.mov"),
        _motion_sample(60, "#6", 0.5, decoder_id=1, movie_key="movie1.mov"),
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["afterDecoderStable"] is True
    assert scored["windowKeyOk"] is True
    assert scored["afterOk"] is False
    assert scored["ok"] is False
    assert scored["reason"] == "no motion after flip"


def test_motion_across_flip_accepts_continuous_single_decoder_long_window():
    """Stream-C (c) regression guard: a legitimately continuous single decoder,
    one movieKey, motion before/across/after over a longer window, still passes
    with expected_key bound — the tightened identity gate must not reject the
    honest positive case.
    """
    from obed_edom.html_alpha_probe import score_motion_across_flip

    hashes = ["#5", "#5", "#5", "#6", "#6", "#6", "#6", "#6"]
    samples = [
        _motion_sample(i * 20, h, i * 0.1, decoder_id=7, movie_key="movie1.mov")
        for i, h in enumerate(hashes)
    ]
    scored = score_motion_across_flip(samples, start_hash="#5", expected_key="movie1.mov")
    assert scored["ok"] is True
    assert scored["flipIndex"] == 3
    assert scored["windowKeyOk"] is True
    assert scored["afterDecoderStable"] is True
    assert scored["afterDecoderIds"] == [7, 7, 7, 7, 7]
    assert scored["reason"] is None


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


def _index_sample(index, scene_hash: str, offset: float = 0.0):
    return {"index": index, "sceneHash": scene_hash, "captureOffsetS": offset}


def test_composited_index_run_accepts_monotonic_advance_across_flip():
    """Positive control: decoded index advances steadily through the cut."""
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(10, "#5", 0.0),
        _index_sample(11, "#5", 0.1),
        _index_sample(12, "#5", 0.2),
        _index_sample(13, "#6", 0.3),
        _index_sample(14, "#6", 0.4),
        _index_sample(15, "#6", 0.5),
    ]
    scored = score_composited_index_run(samples, flip_index=3)
    assert scored["ok"] is True
    assert scored["freezeRunAtCut"] <= 2
    assert scored["negativeAnomaly"] is False


def test_composited_index_run_rejects_freeze_at_cut():
    """A poster freeze straddling the cut must fail even though the sequence
    advances cleanly before and after it.
    """
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(18, "#5", 0.0),
        _index_sample(19, "#5", 0.1),
        _index_sample(20, "#5", 0.2),
        _index_sample(21, "#5", 0.3),
        _index_sample(21, "#6", 0.4),
        _index_sample(21, "#6", 0.5),
        _index_sample(21, "#6", 0.6),
        _index_sample(22, "#6", 0.7),
        _index_sample(23, "#6", 0.8),
    ]
    scored = score_composited_index_run(samples, flip_index=4)
    assert scored["ok"] is False
    assert scored["freezeRunAtCut"] > 2
    assert scored["reason"] == "freeze run at cut"


def test_composited_index_run_accepts_wraparound():
    """A mod-``modulo`` wrap is forward progress, not a negative anomaly."""
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(252, "#5", 0.0),
        _index_sample(253, "#5", 0.1),
        _index_sample(254, "#5", 0.2),
        _index_sample(255, "#5", 0.3),
        _index_sample(0, "#6", 0.4),
        _index_sample(1, "#6", 0.5),
    ]
    scored = score_composited_index_run(samples, flip_index=4)
    assert scored["ok"] is True
    assert scored["negativeAnomaly"] is False


def test_composited_index_run_rejects_negative_anomaly():
    """A drop beyond half the modulo is a restart/poster-swap, not a wrap."""
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(38, "#5", 0.0),
        _index_sample(39, "#5", 0.1),
        _index_sample(40, "#5", 0.2),
        _index_sample(41, "#5", 0.3),
        _index_sample(5, "#6", 0.4),
        _index_sample(6, "#6", 0.5),
        _index_sample(7, "#6", 0.6),
        _index_sample(8, "#6", 0.7),
    ]
    scored = score_composited_index_run(samples, flip_index=2)
    assert scored["ok"] is False
    assert scored["negativeAnomaly"] is True
    assert scored["reason"] == "negative delta anomaly"


def test_composited_index_run_rejects_none_in_flip_window():
    """An undecodable sample inside the flip window must fail closed."""
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(10, "#5", 0.0),
        _index_sample(11, "#5", 0.1),
        _index_sample(None, "#6", 0.2),
        _index_sample(13, "#6", 0.3),
        _index_sample(14, "#6", 0.4),
        _index_sample(15, "#6", 0.5),
    ]
    scored = score_composited_index_run(samples, flip_index=2)
    assert scored["ok"] is False
    assert scored["reason"] == "undecodable in flip window"


def test_composited_index_run_baseline_freeze_does_not_gate_clean_cut():
    """Only the cut window gates: a freeze elsewhere in the run must not fail
    a sequence that is clean across the flip itself.
    """
    from obed_edom.html_alpha_probe import score_composited_index_run

    samples = [
        _index_sample(5, "#5", 0.0),
        _index_sample(5, "#5", 0.1),
        _index_sample(5, "#5", 0.2),
        _index_sample(5, "#5", 0.3),
        _index_sample(5, "#5", 0.4),
        _index_sample(6, "#5", 0.5),
        _index_sample(7, "#5", 0.6),
        _index_sample(8, "#5", 0.7),
        _index_sample(9, "#6", 0.8),
        _index_sample(10, "#6", 0.9),
        _index_sample(11, "#6", 1.0),
    ]
    scored = score_composited_index_run(samples, flip_index=8)
    assert scored["ok"] is True
    assert scored["freezeRunBaseline"] > 2
    assert scored["freezeRunAtCut"] <= 2


def test_composited_index_run_injected_stale_freeze_has_strong_margin():
    """The Phase-2 composited-freeze control (Arm A) holds a stale cover from the
    flip through the whole capture, so the decoded counter FREEZES for the entire
    after-window. The gate must go RED with reason 'freeze run at cut' AND a strong
    margin (freezeRunAtCut >= 6), so the RED is unmistakably the injected freeze,
    not coarse-capture jitter (which the gate's max_freeze_run==2 already tolerates).
    """
    from obed_edom.html_alpha_probe import score_composited_index_run

    # Advancing before the flip, then a stale hold at index 40 for 8 samples.
    samples = [
        _index_sample(37, "#1", 0.0),
        _index_sample(38, "#1", 0.05),
        _index_sample(39, "#1", 0.1),
        _index_sample(40, "#2", 0.15),
    ] + [_index_sample(40, "#2", 0.2 + 0.05 * i) for i in range(8)]
    scored = score_composited_index_run(samples, flip_index=3)
    assert scored["ok"] is False
    assert scored["reason"] == "freeze run at cut"
    assert scored["freezeRunAtCut"] >= 6
    assert scored["negativeAnomaly"] is False


# --------------------------------------------------------------------------- #
# score_index_progression — parity-immune restart corroboration (2->3 flake fix)
# --------------------------------------------------------------------------- #
def test_index_progression_accepts_real_slide3_counter():
    """The real slide-3 burnt-in counter (measured from the restart frames)
    marches forward with 1-4 steps and passes — this is what a MAE motion check
    aliased to a ~1/3 coin flip under the two-state grating."""
    from obed_edom.html_alpha_probe import score_index_progression

    real = [None, 2, 6, 8, 12, 13, 16, 20, 22, 25, 28, 30, 34, 36, 39, 42, 45, 47, 50, 54, 55, 59]
    scored = score_index_progression(real)
    assert scored["ok"] is True
    assert scored["nDecodable"] == 21 and scored["nDistinct"] == 21


def test_index_progression_rejects_frozen_counter():
    """A stuck poster (counter frozen) has a long stall run => fail closed."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([5, 5, 5, 5, 5, 5, 5, 5])
    assert scored["ok"] is False
    assert scored["reason"] in ("stall run too long", "too few distinct indices")


def test_index_progression_rejects_insufficient_decodable():
    """A wrong/occluded ROI decodes few flat patches => fail closed, never a
    false pass from absence of data."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([1, None, None, 4, None, None])
    assert scored["ok"] is False
    assert scored["reason"] == "insufficient decodable samples"


def test_index_progression_rejects_backward_jump():
    """A drop beyond half the modulo (restart/glitch) within the window fails."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([2, 6, 10, 200, 14, 18, 22, 26])
    assert scored["ok"] is False
    assert scored["reason"] == "implausible index jump (reset/occlusion)"


def test_index_progression_rejects_sparse_tail():
    """Advances briefly then loses the ROI for the rest of the window => fail
    closed on coverage; None-drop must not let a short good prefix carry it
    (Codex flake-review F1)."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([2, 6, 10, 14, 18, 22] + [None] * 16)
    assert scored["ok"] is False
    assert scored["reason"] == "sparse decodable coverage"


def test_index_progression_rejects_large_raw_drop_as_forward():
    """A raw 200->14 read (modular +70) is not a plausible single-capture step
    and must be rejected, not counted as forward progress (Codex flake-review F3);
    real per-capture steps are 1-4."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([200, 14, 18, 22, 26, 30, 34, 38])
    assert scored["ok"] is False
    assert scored["reason"] == "implausible index jump (reset/occlusion)"


def test_index_progression_accepts_modulo_wraparound():
    """Forward wraparound past the modulo is normal progress, not a backward jump."""
    from obed_edom.html_alpha_probe import score_index_progression

    assert score_index_progression([250, 254, 2, 6, 10, 14, 18, 22])["ok"] is True


def test_index_progression_tolerates_short_stall():
    """A short stall (<=max_stall_run repeats, e.g. 30fps sampled faster) still
    passes as long as the counter overall advances."""
    from obed_edom.html_alpha_probe import score_index_progression

    scored = score_index_progression([2, 2, 6, 10, 10, 14, 18, 22, 26])
    assert scored["ok"] is True
    assert scored["longestStallRun"] <= 2


# ---------------------------------------------------------------------------
# footprint_at / index_patch_roi_for — moving-footprint helpers (3->4 MM)
# ---------------------------------------------------------------------------
def test_footprint_at_endpoints_and_midpoint():
    from obed_edom.html_alpha_probe import footprint_at

    s = (198.0, 795.0, 952.0, 268.0)
    d = (327.0, 709.0, 1266.0, 356.0)
    assert footprint_at(0.0, s, d) == s
    assert footprint_at(1.0, s, d) == d
    mid = footprint_at(0.5, s, d)
    assert mid == (262.5, 752.0, 1109.0, 312.0)


def test_footprint_at_clamps_progress():
    from obed_edom.html_alpha_probe import footprint_at

    s = (0.0, 0.0, 100.0, 100.0)
    d = (10.0, 10.0, 200.0, 200.0)
    assert footprint_at(-5.0, s, d) == s
    assert footprint_at(9.0, s, d) == d


def test_footprint_at_static_boundary_is_constant():
    """When src == dst (a static boundary like 1->2) it returns the constant rect
    at any progress, so callers can wire it uniformly."""
    from obed_edom.html_alpha_probe import footprint_at

    r = (109.0, 795.0, 952.0, 268.0)
    assert footprint_at(0.0, r, r) == r
    assert footprint_at(0.37, r, r) == r
    assert footprint_at(1.0, r, r) == r


def test_index_patch_roi_for_backcompat_with_movie_roi():
    """Back-compat: mapping MOVIE_ROI must reproduce the adversarial probe's
    INDEX_PATCH_ROI exactly."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    movie_roi = (109, 795, 952, 268)
    expected = (
        movie_roi[0] + 2,
        movie_roi[1],
        max(1, round(movie_roi[2] * 120 / 1920) - 18),
        max(1, round(movie_roi[3] * 48 / 540) - 10),
    )
    assert index_patch_roi_for(movie_roi) == expected == (111, 795, 42, 14)


def test_index_patch_roi_for_scales_with_footprint():
    """A larger (slide-4) footprint yields a proportionally larger patch ROI whose
    inset stays inside the mapped patch (w<=round(w*120/1920), positive dims)."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    s4 = (327.0, 709.0, 1266.0, 356.0)
    x, y, w, h = index_patch_roi_for(s4)
    assert (x, y) == (329, 709)
    assert 0 < w <= round(s4[2] * 120 / 1920)
    assert 0 < h <= round(s4[3] * 48 / 540)
    # larger footprint -> wider ROI than the slide-1/2 one
    assert w > index_patch_roi_for((109, 795, 952, 268))[2]


def test_index_patch_roi_for_clamps_to_min_one():
    """A tiny footprint never yields a zero/negative ROI dimension."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    x, y, w, h = index_patch_roi_for((10.0, 20.0, 30.0, 12.0))
    assert w >= 1 and h >= 1


def test_index_patch_roi_for_accepts_measured_footprint_dict():
    """A measured footprint (e.g. a live getBoundingClientRect() reading, carrying
    extra keys like `source`) maps to the same ROI as the equivalent tuple."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    tup = (324.3, 706.0, 1274.0, 364.0)
    measured = {"x": 324.3, "y": 706.0, "w": 1274.0, "h": 364.0, "source": "measured"}
    assert index_patch_roi_for(measured) == index_patch_roi_for(tup)


def test_index_patch_roi_for_slide4_stays_inside_flat_patch_no_scale_guard_needed():
    """Numeric spill check for plan Step.1.3: the scaled (x1.32) slide-4 ROI must
    stay inside the flat-neutral counter patch, else a `scale_guard` inset would be
    required. Measured: ROI (326, 706)-(388, 728) vs flat patch bounds
    (324.3, 706.0)-(403.9, 738.4) -- fully inside on both axes. No spill observed,
    so no `scale_guard` parameter is added."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    s4 = (324.3, 706.0, 1274.0, 364.0)
    x, y, w, h = index_patch_roi_for(s4)
    patch_x0, patch_y0 = s4[0], s4[1]
    patch_x1 = patch_x0 + s4[2] * 120 / 1920
    patch_y1 = patch_y0 + s4[3] * 48 / 540
    assert patch_x0 <= x and x + w <= patch_x1
    assert patch_y0 <= y and y + h <= patch_y1


# ---------------------------------------------------------------------------
# Top-edge guard (round-6 measurement). The scale spill the plan suspected is
# refuted above; what actually made mid-move samples decode None is the y
# mapping's MISSING inset meeting a half-pixel, badge-quantised rect.
# ---------------------------------------------------------------------------

# The exact failing sample measured on the round-5 bracket (output/scratch-b3,
# run4 arm b, sample i=8): badge rect, the movie's painted top edge row, and the
# flat counter value its neighbours decoded.
_GUARD_BADGE_RECT = (274.75, 744.5, 1139.0, 320.5)
_GUARD_EDGE_ROW = 744
_GUARD_TRUE_VALUE = 33


def test_index_patch_roi_for_top_guard_is_a_subset_and_default_is_unchanged():
    """The guard may only SHRINK the ROI from the top: same x/width, same bottom
    edge, strictly fewer rows. Default 0 keeps every existing caller byte-identical
    (the static slide-1/2 back-compat identity above still holds)."""
    from obed_edom.html_alpha_probe import INDEX_PATCH_TOP_GUARD_PX, index_patch_roi_for

    fp = _GUARD_BADGE_RECT
    bx, by, bw, bh = index_patch_roi_for(fp)
    gx, gy, gw, gh = index_patch_roi_for(fp, top_guard=INDEX_PATCH_TOP_GUARD_PX)

    assert index_patch_roi_for(fp, top_guard=0) == (bx, by, bw, bh)
    assert (gx, gw) == (bx, bw)
    assert gy == by + INDEX_PATCH_TOP_GUARD_PX
    assert gy + gh == by + bh  # bottom edge pinned
    assert gh < bh


def test_index_patch_roi_for_top_guard_holds_the_subset_property_on_tiny_footprints():
    """Review r4 MINOR 1. The subset property must hold for EVERY footprint, not
    just the 3->4 one: when the unguarded ROI is no taller than the guard, the
    old `max(1, h - guard)` pushed the bottom edge DOWN, outside the unguarded
    ROI. The guard is clamped to `height - 1` instead, so the ROI always keeps at
    least one row and its bottom edge never moves."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    for h in range(1, 400):
        for guard in (0, 1, 2, 5, 50):
            fp = (100.0, 200.0, 1920.0, float(h))
            bx, by, bw, bh = index_patch_roi_for(fp)
            gx, gy, gw, gh = index_patch_roi_for(fp, top_guard=guard)
            assert (gx, gw) == (bx, bw)
            assert gy >= by, (h, guard)
            assert gy + gh == by + bh, (h, guard)   # bottom edge pinned
            assert 1 <= gh <= bh, (h, guard)


def test_index_patch_roi_for_top_guard_recovers_the_measured_none_sample():
    """Reproduces the measured cause on a synthetic frame built to the round-5
    geometry: the badge reports y=744.5, `round()` sends that exact .5 DOWN to the
    even 744, and row 744 is the movie's antialiased top edge -- so the unguarded
    ROI is not flat and fails closed. The guarded ROI clears the edge row and
    decodes the value the neighbouring samples read."""
    from obed_edom.html_alpha_probe import INDEX_PATCH_TOP_GUARD_PX, index_patch_roi_for

    frame = np.zeros((900, 1600, 4), dtype=np.uint8)
    frame[:, :, 3] = 255
    x, y, w, h = _GUARD_BADGE_RECT
    patch_w = int(round(w * 120 / 1920))
    patch_h = int(round(h * 48 / 540))
    px = int(round(x))
    # Flat counter patch from the row BELOW the edge; the edge row itself is the
    # bright, non-flat boundary the compositor draws at floor(y).
    frame[_GUARD_EDGE_ROW + 1 : _GUARD_EDGE_ROW + patch_h, px : px + patch_w, :3] = (
        _GUARD_TRUE_VALUE
    )
    frame[_GUARD_EDGE_ROW, px : px + patch_w, :3] = 255

    unguarded = index_patch_roi_for(_GUARD_BADGE_RECT)
    guarded = index_patch_roi_for(_GUARD_BADGE_RECT, top_guard=INDEX_PATCH_TOP_GUARD_PX)

    assert unguarded[1] == _GUARD_EDGE_ROW  # the round-half-to-even landing
    assert _null_control_decode(frame, unguarded) is None
    assert _null_control_decode(frame, guarded) == _GUARD_TRUE_VALUE


def test_index_patch_roi_for_top_guard_still_fails_closed_on_a_wrong_roi():
    """Null control for the guard: it must not manufacture a plausible digit. A
    deliberately mislocated ROI (the same guard applied to a rect that is nowhere
    near the painted patch) still decodes None, and so does a guarded ROI over a
    non-flat region."""
    from obed_edom.html_alpha_probe import INDEX_PATCH_TOP_GUARD_PX, index_patch_roi_for

    frame = np.zeros((900, 1600, 4), dtype=np.uint8)
    frame[:, :, 3] = 255
    x, y, w, h = _GUARD_BADGE_RECT
    patch_w = int(round(w * 120 / 1920))
    patch_h = int(round(h * 48 / 540))
    px = int(round(x))
    frame[_GUARD_EDGE_ROW + 1 : _GUARD_EDGE_ROW + patch_h, px : px + patch_w, :3] = (
        _GUARD_TRUE_VALUE
    )
    frame[_GUARD_EDGE_ROW, px : px + patch_w, :3] = 255
    # Everything outside the patch is a high-contrast grating.
    frame[:_GUARD_EDGE_ROW, :, :3] = (np.indices((_GUARD_EDGE_ROW, 1600))[1] % 2 * 255)[..., None]

    wrong_rect = (x, y - 300.0, w, h)  # patch is 300 px below this ROI
    wrong = index_patch_roi_for(wrong_rect, top_guard=INDEX_PATCH_TOP_GUARD_PX)
    assert _null_control_decode(frame, wrong) is None

    # And the guard does not rescue a genuinely non-flat patch: with the counter
    # region overpainted by the grating, the correctly-located guarded ROI still
    # decodes None rather than the grating's mean.
    frame[_GUARD_EDGE_ROW : _GUARD_EDGE_ROW + patch_h, px : px + patch_w, :3] = (
        (np.indices((patch_h, patch_w))[1] % 2 * 255)[..., None]
    )
    right = index_patch_roi_for(_GUARD_BADGE_RECT, top_guard=INDEX_PATCH_TOP_GUARD_PX)
    assert _null_control_decode(frame, right) is None


# ---------------------------------------------------------------------------
# Scorer-side NULL CONTROL (plan Step.1.4): a counter patch that TRANSLATES and
# SCALES across frames on a high-contrast grating background, mirroring the
# 3->4 fixture geometry (slide-3 rect -> slide-4 rect). Proves that decoding
# through a STATIC patch ROI fails closed on a moving movie, while decoding
# through the per-frame MEASURED footprint (index_patch_roi_for(footprint_at(...)))
# recovers the true index sequence -- i.e. the tracking is load-bearing.
# ---------------------------------------------------------------------------
_NULL_CONTROL_SLIDE3_RECT = (195.5, 794.6, 960.0, 276.0)
_NULL_CONTROL_SLIDE4_RECT = (324.3, 706.0, 1274.0, 364.0)


def _null_control_grating(height=1080, width=1920, cell=40, lo=30, hi=220):
    """A high-contrast checkerboard background: anything decoded off it (std of
    the crop is high) is unambiguously NOT the flat counter patch."""
    yy, xx = np.mgrid[0:height, 0:width]
    checker = (((xx // cell) + (yy // cell)) % 2).astype(np.uint8)
    plane = np.where(checker == 1, hi, lo).astype(np.uint8)
    return np.stack([plane, plane, plane], axis=-1)


def _null_control_crop(arr, roi):
    x, y, w, h = roi
    height, width = arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    return arr[y0:y1, x0:x1]


def _null_control_decode(arr, roi):
    """Mirrors the adversarial probe's `_decode_index_patch`: None on a
    non-flat/occluded crop, else the flat patch's rounded mean gray value."""
    patch = _null_control_crop(arr, roi)
    if patch.size == 0:
        return None
    rgb = patch[:, :, :3].astype(np.float64)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    if max(float(r.std()), float(g.std()), float(b.std())) > 8:
        return None
    if max(float(np.abs(r - g).max()), float(np.abs(g - b).max())) > 12:
        return None
    return int(round(float(rgb.mean())))


def _null_control_paint_rect(footprint):
    """The counter's OWN geometry: the burnt-in patch is authored at the movie
    SOURCE's top-left 120x48 (of a 1920x540 source), scaled into the CURRENT
    footprint -- independent of `index_patch_roi_for`'s own (smaller, inset)
    decode ROI, so painting and decoding are not the same computation (review
    MAJOR 6d: the old fixture painted and decoded through the identical
    `index_patch_roi_for(footprint)` call, which could not distinguish "the
    tracking is load-bearing" from "the paint and decode ROIs always agree by
    construction")."""
    x, y, w, h = footprint
    pw = max(1, int(round(w * 120.0 / 1920.0)))
    ph = max(1, int(round(h * 48.0 / 540.0)))
    return (int(round(x)), int(round(y)), pw, ph)


def _null_control_frames_and_tracked_rois(true_indices):
    """Synthesise one frame per index: the flat counter patch is painted at the
    footprint's OWN mapped geometry (`_null_control_paint_rect`, independent of
    the decode ROI), everything else is the high-contrast grating. Returns
    (frames, tracked_rois) where `tracked_rois` are the DECODE ROIs
    (`index_patch_roi_for(footprint)`, the plan/runtime's real function) -- a
    strict subset of the painted rect on both axes (see
    `test_index_patch_roi_for_slide4_stays_inside_flat_patch_no_scale_guard_needed`),
    so a genuine tracking failure (paint and decode ROIs diverging) is still
    caught, not concealed by reusing one rect for both."""
    from obed_edom.html_alpha_probe import footprint_at, index_patch_roi_for

    n = len(true_indices)
    frames = []
    tracked_rois = []
    for i, value in enumerate(true_indices):
        progress = i / (n - 1)
        footprint = footprint_at(progress, _NULL_CONTROL_SLIDE3_RECT, _NULL_CONTROL_SLIDE4_RECT)
        paint_rect = _null_control_paint_rect(footprint)
        roi = index_patch_roi_for(footprint)
        tracked_rois.append(roi)
        frame = _null_control_grating()
        x, y, w, h = paint_rect
        frame[y : y + h, x : x + w] = value
        frames.append(frame)
    return frames, tracked_rois


def test_null_control_static_roi_fails_closed_on_translating_scaling_movie():
    """The moving-footprint null control, part (a): decoding through the STATIC
    slide-3 patch ROI (never updated as the movie translates+scales to slide 4)
    fails closed -- almost every frame's patch has moved off, so the static crop
    lands on the grating and decodes to None."""
    from obed_edom.html_alpha_probe import index_patch_roi_for, score_index_progression

    true_indices = [20 + i * 15 for i in range(12)]
    frames, _tracked_rois = _null_control_frames_and_tracked_rois(true_indices)
    static_roi = index_patch_roi_for(_NULL_CONTROL_SLIDE3_RECT)

    static_decoded = [_null_control_decode(f, static_roi) for f in frames]
    scored = score_index_progression(static_decoded)

    assert scored["ok"] is False
    assert scored["reason"] == "insufficient decodable samples"
    assert scored["nDecodable"] < 6


def test_null_control_tracked_roi_recovers_true_index_sequence():
    """The moving-footprint null control, part (b): the patch is painted at the
    movie's OWN mapped geometry (`_null_control_paint_rect`, independent of the
    decode path) and decoded through `index_patch_roi_for(<per-frame measured
    footprint>)` -- a DIFFERENT computation that happens to land inside the
    painted rect. Recovering the true index sequence exactly PASSES, proving the
    tracking (not merely reusing one ROI for paint+decode) is what makes the
    3->4 counter readable. This is a synthetic-frame unit test; whether the
    REAL x1.32 slide-4 ROI stays decodable on actual captured frames is verified
    by the live gate, not here (review MAJOR 6d)."""
    from obed_edom.html_alpha_probe import score_index_progression

    true_indices = [20 + i * 15 for i in range(12)]
    frames, tracked_rois = _null_control_frames_and_tracked_rois(true_indices)

    tracked_decoded = [
        _null_control_decode(f, roi) for f, roi in zip(frames, tracked_rois)
    ]
    scored = score_index_progression(tracked_decoded)

    assert tracked_decoded == true_indices
    assert scored["ok"] is True
    assert scored["reason"] is None
    assert scored["nDecodable"] == len(true_indices)


# --- visible-content gate: liveness mask, band coverage, strays, noise floor ---
#
# Geometry mirrors the measured fixture: the big movie's screen rect on slide 2 is
# 952x268 at (109, 795) in a 1920x1080 stage, and today's defect paints only a
# 663x186 copy at its top-left.
BIG_RECT = {"x": 109, "y": 795, "w": 952, "h": 268}
DEFECT_OVERLAY = (109, 795, 663, 186)
CONTROL_RECT = {"x": 0, "y": 0, "w": 40, "h": 40}


def _static_burst(n=5, height=1080, width=1920, channels=3, value=40):
    """A burst of identical frames — nothing in it is live."""
    return [np.full((height, width, channels), value, dtype=np.uint8) for _ in range(n)]


def _paint_live(frames, box, base=10, step=40):
    """Make a box move across the burst (delta = step * (n-1) >> DELTA_MIN)."""
    x, y, w, h = (int(round(v)) for v in box)
    for i, frame in enumerate(frames):
        frame[y : y + h, x : x + w, :3] = base + i * step


def _paint_static(frames, box, value=200):
    """An opaque, unmoving occluder."""
    x, y, w, h = (int(round(v)) for v in box)
    for frame in frames:
        frame[y : y + h, x : x + w, :3] = value


def _rect_box(rect):
    return (rect["x"], rect["y"], rect["w"], rect["h"])


def test_liveness_mask_flags_only_the_moving_box():
    """A pixel is live iff max-min over the burst, maximised over RGB, >= delta_min."""
    from obed_edom.html_alpha_probe import liveness_mask

    frames = _static_burst(height=100, width=200)
    _paint_live(frames, (20, 10, 50, 30))
    mask = liveness_mask(frames)
    assert mask.dtype == np.bool_ and mask.shape == (100, 200)
    assert mask[10:40, 20:70].all()
    assert not mask[0:10, :].any()
    assert float(mask.mean()) == pytest.approx(50 * 30 / (100 * 200))


def test_liveness_mask_ignores_low_amplitude_noise():
    """Compression/dither noise of delta 3 everywhere is not motion."""
    from obed_edom.html_alpha_probe import liveness_mask

    frames = _static_burst(height=60, width=80)
    for i, frame in enumerate(frames):
        frame[:, :, :3] = 40 + (i % 2) * 3
    assert not liveness_mask(frames).any()


def test_liveness_mask_ignores_alpha_channel():
    """RGBA input is accepted; a moving alpha with static RGB is not live."""
    from obed_edom.html_alpha_probe import liveness_mask

    frames = _static_burst(height=40, width=40, channels=4)
    for i, frame in enumerate(frames):
        frame[:, :, 3] = 10 + i * 50
    assert not liveness_mask(frames).any()
    _paint_live(frames, (5, 5, 10, 10))
    assert liveness_mask(frames)[5:15, 5:15].all()


def test_liveness_mask_rejects_short_or_mismatched_bursts():
    """Fail loudly rather than score a burst that cannot carry a verdict."""
    from obed_edom.html_alpha_probe import liveness_mask

    with pytest.raises(ValueError):
        liveness_mask(_static_burst(n=1, height=20, width=20))
    with pytest.raises(ValueError):
        liveness_mask([np.zeros((20, 20, 3), np.uint8), np.zeros((21, 20, 3), np.uint8)])
    with pytest.raises(ValueError):
        liveness_mask([np.zeros((20, 20), np.uint8), np.zeros((20, 20), np.uint8)])


def test_live_coverage_passes_a_fully_live_rect():
    """The healthy shape: the whole authored movie rect moves."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is True
    assert scored["liveFrac"] == pytest.approx(1.0)
    assert scored["deadColumnBands"] == [] and scored["deadRowBands"] == []
    assert scored["rect"] == {"x": 111, "y": 797, "w": 948, "h": 264}
    assert scored["reason"] is None


def test_live_coverage_reds_on_todays_663x186_sub_rect():
    """Today's real defect: only a 663x186 copy paints at the rect's top-left, so
    the right-hand column bands AND the bottom row bands are dead."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, DEFECT_OVERLAY)
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is False
    assert scored["reason"] == "dead bands"
    assert scored["deadColumnBands"] and max(scored["deadColumnBands"]) == 15
    assert min(scored["deadColumnBands"]) >= 11
    assert scored["deadRowBands"] == [6, 7]
    # the bands are what catch it: 48.6% of the rect is live, which a whole-rect
    # fraction test at 0.35 would have passed
    assert scored["liveFrac"] == pytest.approx(0.486, abs=0.01)


def test_live_coverage_passes_an_interior_opaque_box():
    """P2's 134x114 black ROI inside the 952x268 rect never blanks a whole band."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_static(frames, (400, 870, 134, 114))
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is True
    assert scored["deadColumnBands"] == [] and scored["deadRowBands"] == []
    assert 0.9 < scored["liveFrac"] < 1.0


def test_live_coverage_passes_the_green_square_geometry():
    """The fixture's square covers the top 70% of the right 28% of the rect; the
    live strip left under it keeps every band alive."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    block_w = round(BIG_RECT["w"] * 0.28)
    block_h = round(BIG_RECT["h"] * 0.70)
    _paint_static(frames, (BIG_RECT["x"] + BIG_RECT["w"] - block_w, BIG_RECT["y"], block_w, block_h))
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is True
    assert scored["deadColumnBands"] == [] and scored["deadRowBands"] == []


def test_live_coverage_reds_on_a_full_height_opaque_stripe():
    """A full-height occluder blanks whole column bands — fail closed (documented
    false-RED direction, §1.3)."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_static(frames, (500, BIG_RECT["y"], 200, BIG_RECT["h"]))
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is False
    assert scored["deadColumnBands"] and scored["deadRowBands"] == []


def test_live_coverage_reds_on_a_full_width_opaque_stripe():
    """The row-band mirror of the stripe case."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_static(frames, (BIG_RECT["x"], 900, BIG_RECT["w"], 70))
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is False
    assert scored["deadRowBands"] and scored["deadColumnBands"] == []


def test_live_coverage_reds_on_an_all_static_rect():
    """A poster / frozen decoder: nothing moves, every band dead."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    scored = score_live_coverage(liveness_mask(_static_burst()), BIG_RECT)
    assert scored["verdict"] is False
    assert scored["liveFrac"] == 0.0
    assert len(scored["deadColumnBands"]) == 16 and len(scored["deadRowBands"]) == 8


def test_live_coverage_sees_a_two_state_pattern_when_the_burst_catches_both():
    """A periodic two-state grating is live as soon as the burst holds >=2 distinct
    states — this is why the shot gaps are unequal (§1.3)."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    for i, frame in enumerate(frames):
        state = 30 if i % 2 else 220
        x, y, w, h = _rect_box(BIG_RECT)
        frame[y : y + h, x : x + w, :3] = state
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is True


def test_live_coverage_aliases_when_every_shot_catches_the_same_state():
    """Documented failure mode: equally-spaced shots that land on one phase of the
    grating read as static => RED. The instrument cannot see through aliasing; the
    caller's unequal gaps are what avoid it."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    for frame in frames:
        x, y, w, h = _rect_box(BIG_RECT)
        frame[y : y + h, x : x + w, :3] = 220
    scored = score_live_coverage(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is False
    assert scored["liveFrac"] == 0.0


def test_live_coverage_clips_a_rect_that_runs_off_the_image():
    """A rect hanging off the right edge is clipped and still scored."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst(height=200, width=300)
    _paint_live(frames, (100, 50, 200, 100))
    scored = score_live_coverage(liveness_mask(frames), {"x": 100, "y": 50, "w": 400, "h": 100})
    assert scored["rect"] == {"x": 102, "y": 52, "w": 198, "h": 96}
    assert scored["verdict"] is True


def test_live_coverage_rejects_a_rect_outside_or_too_small():
    """Off-image or sub-band-grid rects can carry no verdict — never a pass."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    mask = liveness_mask(_static_burst(height=200, width=300))
    off = score_live_coverage(mask, {"x": 400, "y": 400, "w": 50, "h": 50})
    assert off["verdict"] is False
    assert off["reason"] == "rect outside image or too small"
    assert off["rect"] is None
    tiny = score_live_coverage(mask, {"x": 10, "y": 10, "w": 14, "h": 20})
    assert tiny["verdict"] is False
    assert tiny["reason"] == "rect outside image or too small"


def test_live_coverage_accepts_float_rects():
    """Screen rects arrive as floats from the stage map; they round, not truncate."""
    from obed_edom.html_alpha_probe import liveness_mask, score_live_coverage

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    floated = {"x": 108.6, "y": 795.4, "w": 952.2, "h": 267.8}
    scored = score_live_coverage(liveness_mask(frames), floated)
    assert scored["verdict"] is True
    assert scored["rect"] == {"x": 111, "y": 797, "w": 948, "h": 264}


def test_no_stray_movie_reds_on_a_45x45_blob_outside_every_rect():
    """A second instance painting outside the authored rects is a stray (>=2000 px)."""
    from obed_edom.html_alpha_probe import liveness_mask, score_no_stray_movie

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_live(frames, (1400, 200, 45, 45))
    scored = score_no_stray_movie(liveness_mask(frames), [BIG_RECT])
    assert scored["verdict"] is False
    assert len(scored["strays"]) == 1
    assert scored["strays"][0]["bbox"] == {"x": 1400, "y": 200, "w": 45, "h": 45}
    assert scored["strays"][0]["area"] == 45 * 45


def test_no_stray_movie_passes_a_20x20_blob():
    """Below the area floor: cursor/AA specks do not fail a slide."""
    from obed_edom.html_alpha_probe import liveness_mask, score_no_stray_movie

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_live(frames, (1400, 200, 20, 20))
    assert score_no_stray_movie(liveness_mask(frames), [BIG_RECT])["verdict"] is True


def test_no_stray_movie_sorts_strays_by_area_descending():
    from obed_edom.html_alpha_probe import liveness_mask, score_no_stray_movie

    frames = _static_burst()
    _paint_live(frames, (100, 100, 50, 50))
    _paint_live(frames, (400, 100, 90, 90))
    strays = score_no_stray_movie(liveness_mask(frames), [])["strays"]
    assert [s["area"] for s in strays] == [90 * 90, 50 * 50]


def test_no_stray_movie_tolerates_a_blob_hugging_a_rect_edge():
    """AA/rounding spill just outside a rect is absorbed by the 6 px dilation: the
    residue falls under the area floor, while dilate_px=0 would call it a stray."""
    from obed_edom.html_alpha_probe import liveness_mask, score_no_stray_movie

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    right = BIG_RECT["x"] + BIG_RECT["w"]
    _paint_live(frames, (right + 3, 800, 45, 45))
    mask = liveness_mask(frames)
    assert score_no_stray_movie(mask, [BIG_RECT])["verdict"] is True
    undilated = score_no_stray_movie(mask, [BIG_RECT], dilate_px=0)
    assert undilated["verdict"] is False
    assert undilated["strays"][0]["area"] == 45 * 45


def test_no_stray_movie_honours_ignore_rects():
    """A caller-declared animated non-movie region is excused explicitly."""
    from obed_edom.html_alpha_probe import liveness_mask, score_no_stray_movie

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    _paint_live(frames, (1400, 200, 45, 45))
    mask = liveness_mask(frames)
    ignore = [{"x": 1390, "y": 190, "w": 70, "h": 70}]
    assert score_no_stray_movie(mask, [BIG_RECT], ignore_rects=ignore)["verdict"] is True
    assert score_no_stray_movie(mask, [BIG_RECT])["verdict"] is False


def test_noise_floor_passes_a_static_control_region():
    from obed_edom.html_alpha_probe import score_noise_floor

    frames = _static_burst(height=200, width=200)
    _paint_live(frames, (100, 100, 50, 50))
    scored = score_noise_floor(frames, CONTROL_RECT)
    assert scored["verdict"] is True and scored["p99"] == 0.0


def test_noise_floor_fails_at_p99_of_eight():
    """A control region jittering by 8 is above the < 6 bar."""
    from obed_edom.html_alpha_probe import score_noise_floor

    frames = _static_burst(height=200, width=200)
    for i, frame in enumerate(frames):
        frame[0:40, 0:40, :3] = 40 + (i % 2) * 8
    scored = score_noise_floor(frames, CONTROL_RECT)
    assert scored["verdict"] is False
    assert scored["p99"] == pytest.approx(8.0)
    assert scored["reason"] == "noise floor above threshold"


def test_noise_floor_fails_closed_on_an_off_image_control_rect():
    from obed_edom.html_alpha_probe import score_noise_floor

    scored = score_noise_floor(_static_burst(height=100, width=100), {"x": 500, "y": 5, "w": 40, "h": 40})
    assert scored["verdict"] is False
    assert scored["p99"] is None
    assert scored["reason"] == "control rect outside image"


def test_visible_slide_passes_a_healthy_slide():
    """Every expected rect fully live, nothing live outside them."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    scored = score_visible_slide(frames, [dict(BIG_RECT, label="movie1")], CONTROL_RECT)
    assert scored["verdict"] is True and scored["status"] == "pass"
    assert scored["perRect"][0]["label"] == "movie1"
    assert scored["perRect"][0]["maxDelta"] == 160
    assert scored["stray"]["verdict"] is True
    assert scored["noiseFloor"]["verdict"] is True


def test_visible_slide_fails_on_todays_slide_two_shape():
    """The deliverable RED: a 663x186 live patch plus a stray elsewhere."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    _paint_live(frames, DEFECT_OVERLAY)
    _paint_live(frames, (1500, 300, 60, 60))
    scored = score_visible_slide(frames, [dict(BIG_RECT, label="movie1")], CONTROL_RECT)
    assert scored["verdict"] is False and scored["status"] == "fail"
    assert scored["perRect"][0]["verdict"] is False
    assert scored["perRect"][0]["deadRowBands"] == [6, 7]
    assert scored["stray"]["verdict"] is False
    assert scored["stray"]["strays"][0]["area"] == 60 * 60


def test_visible_slide_is_inconclusive_when_the_noise_floor_fails():
    """INCONCLUSIVE is never a pass: verdict is None, callers must treat anything
    but True as failure."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    for i, frame in enumerate(frames):
        frame[0:40, 0:40, :3] = 40 + (i % 2) * 8
    scored = score_visible_slide(frames, [BIG_RECT], CONTROL_RECT)
    assert scored["verdict"] is None
    assert scored["status"] == "inconclusive"
    assert scored["perRect"] == [] and scored["stray"] is None
    assert scored["noiseFloor"]["p99"] == pytest.approx(8.0)


def test_visible_slide_records_max_delta_for_a_static_rect():
    """A genuinely static movie segment reads RED; maxDelta is recorded so the
    artifact can distinguish it from a mislocated rect (§1.3)."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    scored = score_visible_slide(frames, [BIG_RECT], CONTROL_RECT)
    assert scored["verdict"] is False
    assert scored["perRect"][0]["maxDelta"] == 0
    assert "label" not in scored["perRect"][0]


# --- dead-expected rects (baseline refusal, I3) ---
#
# A boundary the plan REFUSES to carry hands its movie back to the raw player, so
# the destination slide's movie rect must read FROZEN. The verdict is inverted, and
# a rect that cannot be measured is never evidence of deadness.


def test_dead_rect_passes_a_frozen_movie_rect():
    """The refusal's own green: the whole rect holds still across the burst."""
    from obed_edom.html_alpha_probe import liveness_mask, score_dead_rect

    frames = _static_burst()
    scored = score_dead_rect(liveness_mask(frames), BIG_RECT)
    assert scored["verdict"] is True
    assert scored["liveFrac"] == pytest.approx(0.0)
    assert scored["rect"] == {"x": 111, "y": 797, "w": 948, "h": 264}
    assert scored["reason"] is None


def test_dead_rect_fails_on_ten_percent_live():
    """Well above DEAD_RECT_MAX_LIVE_FRAC: a carried decoder still painting there."""
    from obed_edom.html_alpha_probe import DEAD_RECT_MAX_LIVE_FRAC, liveness_mask, score_dead_rect

    frames = _static_burst()
    _paint_live(frames, (BIG_RECT["x"], BIG_RECT["y"], BIG_RECT["w"], round(BIG_RECT["h"] * 0.1)))
    scored = score_dead_rect(liveness_mask(frames), BIG_RECT)
    assert scored["liveFrac"] > DEAD_RECT_MAX_LIVE_FRAC
    assert scored["verdict"] is False
    assert scored["reason"] == "live pixels in a rect the plan expects to be frozen"


def test_dead_rect_tolerates_a_sub_threshold_seam():
    """An AA seam of a few per cent is not a live movie."""
    from obed_edom.html_alpha_probe import liveness_mask, score_dead_rect

    frames = _static_burst()
    _paint_live(frames, (BIG_RECT["x"], BIG_RECT["y"], BIG_RECT["w"], 6))
    scored = score_dead_rect(liveness_mask(frames), BIG_RECT)
    assert 0 < scored["liveFrac"] <= 0.05
    assert scored["verdict"] is True


def test_dead_rect_that_cannot_be_measured_is_not_evidence_of_deadness():
    """Fail-closed, exactly like the live scorer: an unmeasurable rect is False."""
    from obed_edom.html_alpha_probe import liveness_mask, score_dead_rect

    mask = liveness_mask(_static_burst(height=100, width=100))
    scored = score_dead_rect(mask, {"x": 500, "y": 5, "w": 40, "h": 40})
    assert scored["verdict"] is False
    assert scored["liveFrac"] is None
    assert scored["reason"] == "rect outside image or too small"


def test_visible_slide_scores_a_dead_expected_rect_with_the_inverted_verdict():
    """The baseline's slide 2: the movie rect is frozen and that is GREEN, while
    whatever the player paints there is ignored by the stray check."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    dead = dict(BIG_RECT, label="movie1#1", expect="dead")
    scored = score_visible_slide(frames, [dead], CONTROL_RECT)
    assert scored["verdict"] is True and scored["status"] == "pass"
    assert scored["perRect"][0]["expect"] == "dead"
    assert scored["perRect"][0]["verdict"] is True
    assert scored["perRect"][0]["maxDelta"] == 0
    assert scored["stray"]["verdict"] is True


def test_visible_slide_reds_when_a_dead_expected_rect_is_live():
    """The runtime ignored the refusal and carried the movie anyway."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    _paint_live(frames, _rect_box(BIG_RECT))
    scored = score_visible_slide(frames, [dict(BIG_RECT, label="movie1#1", expect="dead")], CONTROL_RECT)
    assert scored["verdict"] is False and scored["status"] == "fail"
    assert scored["perRect"][0]["verdict"] is False


def test_visible_slide_dead_rect_is_inconclusive_when_the_noise_floor_fails():
    """A dead expectation is not a licence to score a burst the control rejects."""
    from obed_edom.html_alpha_probe import score_visible_slide

    frames = _static_burst()
    for i, frame in enumerate(frames):
        frame[0:40, 0:40, :3] = 40 + (i % 2) * 8
    scored = score_visible_slide(frames, [dict(BIG_RECT, expect="dead")], CONTROL_RECT)
    assert scored["verdict"] is None
    assert scored["status"] == "inconclusive"
    assert scored["perRect"] == []


def test_visible_slide_scores_live_and_dead_rects_side_by_side():
    """One slide may state both expectations; each rect is judged on its own, and
    a live patch inside the DEAD rect does not count as a stray."""
    from obed_edom.html_alpha_probe import score_visible_slide

    live_rect = {"x": 200, "y": 200, "w": 400, "h": 200}
    frames = _static_burst()
    _paint_live(frames, _rect_box(live_rect))
    _paint_live(frames, (BIG_RECT["x"], BIG_RECT["y"], 200, 100))
    scored = score_visible_slide(
        frames,
        [dict(live_rect, label="live#1"), dict(BIG_RECT, label="dead#1", expect="dead")],
        CONTROL_RECT,
    )
    assert [rect["expect"] for rect in scored["perRect"]] == ["live", "dead"]
    assert scored["perRect"][0]["verdict"] is True
    assert scored["perRect"][1]["verdict"] is False
    assert scored["stray"]["verdict"] is True


def _inpage_samples(
    n=30,
    *,
    n_bands=128,
    static_bands=(),
    all_static=False,
    control_amp=0.0,
    green_amp=0.0,
    green_rgb=(10.0, 200.0, 10.0),
    gl_err=0,
):
    """Synthetic in-page samples: every non-static band ramps 100..127 across the
    window (range 27, well past the 1.0 threshold); ``static_bands`` (or
    ``all_static``) hold a band constant to model an occluder or a dead read."""
    samples = []
    for t in range(n):
        if all_static:
            bands = [100.0] * n_bands
        else:
            bands = [
                100.0 if b in static_bands else 100.0 + (t % 10) * 3.0
                for b in range(n_bands)
            ]
        control = 50.0 + control_amp * (t % 2)
        green = 80.0 + green_amp * (t % 2)
        samples.append(
            {
                "t": t,
                "ms": 4.0,
                "vt": t * 0.033,
                "mediaTime": t * 0.033,
                "bands": bands,
                "control": control,
                "green": green,
                "greenRGB": list(green_rgb),
                "glErr": gl_err,
            }
        )
    return samples


class TestInPageLivenessScorer:
    def test_all_bands_moving_reads_live(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples())
        assert scored["verdict"] is True
        assert scored["status"] == "live"
        assert scored["occludedBands"] == 0
        assert scored["judgedBands"] == 128

    def test_one_non_occluded_static_band_reads_dead(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(static_bands=(5,)))
        assert scored["verdict"] is False
        assert scored["status"] == "dead"
        assert scored["reason"] == "a judged band did not move"

    def test_that_same_band_marked_occluded_reads_live(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        samples = _inpage_samples(static_bands=(5,))
        mask = [1 if i == 5 else 0 for i in range(128)]
        scored = score_inpage_liveness(samples, occluder_mask=mask)
        assert scored["verdict"] is True
        assert scored["occludedBands"] == 1
        assert scored["judgedBands"] == 127

    def test_a_moving_control_patch_is_inconclusive(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(control_amp=5.0))
        assert scored["verdict"] is None
        assert scored["status"] == "inconclusive"
        assert scored["reason"] == "control patch moved"

    def test_a_moving_green_patch_reads_dead(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(green_amp=5.0))
        assert scored["verdict"] is False
        assert scored["reason"] == "green patch moved"

    def test_a_green_patch_that_is_not_green_reads_dead(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(green_rgb=(100.0, 100.0, 100.0)))
        assert scored["verdict"] is False
        assert scored["reason"] == "green patch is not green"

    def test_twenty_three_samples_is_inconclusive(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(n=23))
        assert scored["verdict"] is None
        assert scored["status"] == "inconclusive"
        assert scored["reason"] == "too few samples"

    def test_a_non_zero_gl_error_reads_dead(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(gl_err=1))
        assert scored["verdict"] is False
        assert scored["reason"] == "gl error"

    def test_more_than_half_the_bands_occluded_is_inconclusive(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        mask = [1] * 65 + [0] * 63
        scored = score_inpage_liveness(_inpage_samples(), occluder_mask=mask)
        assert scored["verdict"] is None
        assert scored["status"] == "inconclusive"
        assert scored["reason"] == "more than half the bands are occluded"

    def test_empty_samples_is_inconclusive(self):
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness([])
        assert scored["verdict"] is None
        assert scored["status"] == "inconclusive"
        assert scored["reason"] == "no samples"
        assert scored["n"] == 0

    def test_media_time_alone_never_implies_live(self):
        """Advancing mediaTime/vt over static bands must not read live."""
        from obed_edom.html_alpha_probe import score_inpage_liveness

        scored = score_inpage_liveness(_inpage_samples(all_static=True))
        assert scored["vtSpan"] > 0
        assert scored["mediaTimeSpan"] > 0
        assert scored["verdict"] is False

    def test_occluder_mask_from_markers_flags_bands_that_do_not_move(self):
        from obed_edom.html_alpha_probe import occluder_mask_from_markers

        at_bound = occluder_mask_from_markers([100.0], [100.5])
        assert at_bound["verdict"] is True
        assert at_bound["mask"] == [1]
        assert at_bound["occluded"] == 1

        past_bound = occluder_mask_from_markers([100.0], [100.51])
        assert past_bound["mask"] == [0]
        assert past_bound["occluded"] == 0

    def test_occluder_mask_fails_closed_on_mismatched_marker_lengths(self):
        from obed_edom.html_alpha_probe import occluder_mask_from_markers

        result = occluder_mask_from_markers([100.0, 100.0], [100.0])
        assert result["verdict"] is False
        assert result["mask"] is None
        assert result["reason"] == "mismatched marker lengths"


class TestOracleCombiner:
    def _screenshot(self, verdict, reason=None):
        return {"verdict": verdict, "status": "pass" if verdict else ("fail" if verdict is False else "inconclusive"), "reason": reason}

    def _inpage(self, verdict, reason=None):
        return {"verdict": verdict, "status": "live" if verdict else ("dead" if verdict is False else "inconclusive"), "reason": reason}

    def test_agree_live_is_live(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        combined = combine_oracle_verdicts(self._screenshot(True), self._inpage(True))
        assert combined["verdict"] is True
        assert combined["status"] == "pass"

    def test_agree_dead_is_dead(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        combined = combine_oracle_verdicts(self._screenshot(False, "live fraction below threshold"), self._inpage(False))
        assert combined["verdict"] is False
        assert combined["status"] == "fail"
        assert combined["reason"] == "live fraction below threshold"

    def test_screenshot_only_is_passthrough(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        screenshot = self._screenshot(True)
        assert combine_oracle_verdicts(screenshot, None) == {
            "verdict": True,
            "status": "pass",
            "reason": None,
            "oracles": {"screenshot": screenshot, "inpage": None},
        }
        na = {"verdict": None, "status": "n/a", "reason": "no webgl canvas"}
        combined = combine_oracle_verdicts(screenshot, na)
        assert combined["verdict"] is True
        assert combined["status"] == "pass"
        assert combined["oracles"]["inpage"] is na

    def test_disagreement_either_way_is_inconclusive(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        live_vs_dead = combine_oracle_verdicts(self._screenshot(True), self._inpage(False))
        assert live_vs_dead["verdict"] is None
        assert live_vs_dead["status"] == "inconclusive"
        assert live_vs_dead["reason"] == "oracle disagreement"

        dead_vs_live = combine_oracle_verdicts(self._screenshot(False), self._inpage(True))
        assert dead_vs_live["verdict"] is None
        assert dead_vs_live["status"] == "inconclusive"
        assert dead_vs_live["reason"] == "oracle disagreement"

    def test_inpage_inconclusive_over_a_live_screenshot_is_inconclusive(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        combined = combine_oracle_verdicts(self._screenshot(True), self._inpage(None, "control patch moved"))
        assert combined["verdict"] is None
        assert combined["status"] == "inconclusive"
        assert combined["reason"] == "in-page oracle inconclusive: control patch moved"

    def test_inpage_inconclusive_over_a_red_screenshot_stays_red(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        screenshot = self._screenshot(False, "dead bands")
        combined = combine_oracle_verdicts(screenshot, self._inpage(None, "control patch moved"))
        assert combined["verdict"] is False
        assert combined["status"] == "fail"
        assert combined["reason"] == "dead bands"

    def test_an_inconclusive_screenshot_is_never_upgraded(self):
        from obed_edom.html_alpha_probe import combine_oracle_verdicts

        screenshot = {"verdict": None, "status": "inconclusive", "reason": "noise floor above threshold"}
        combined = combine_oracle_verdicts(screenshot, self._inpage(True))
        assert combined["verdict"] is None
        assert combined["status"] == "inconclusive"
        assert combined["reason"] == "noise floor above threshold"

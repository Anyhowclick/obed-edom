"""Synthetic tests for `scripts/managed_obs_qualify.py`; no OBS, no browser.

Magic Move opacity (plan keynote_live_mm_opacity §7, §8, §10): the OBED_LIVE_MM_OPACITY refusal, `EXPECTED_STATS` keyed
by patch mode, M3's opaque reference moved to the `mm-off` twin (and its KB still FAILing), the M3 g2-off T-alpha check
(patch on, GL replay off), the MO-2 scorers (tau, R1, the neutral-background R2 with R3's handovers folded in, R4 and its
tau_key, the premise-INCONCLUSIVE path, a CvC per rate, KB = patch-off twins, the offline `--score` re-scorer), the MO-4 G2
facts in the MO-2 takes and their provenance, the MO-3 mapping onto `mm_opacity_probe`'s scorer and its shared driver (the
logger payload), and the session wiring (mm_opacity passed explicitly, logger transport, alpha-squared splice, forced
stand-down seed).

Hand-back geometry (plan keynote_live_handback_geometry §3.4, W3): the patch-on G2 baseline is `frameLen` 96 and unproven
[{4, size}] (patch off 88, []); M3's edge band is enforced against the DOM (G2-P3), its KB is the mm-off twin's stock
geometry at slot opacity; a patch-on G2 session whose fix did not engage (the pre-fix unproven rest-opacity) makes the
take INVALID, never a pass or a fail of the fix.

Looping soak fixture (loopMode plan §10 WS-C): `output/p2-loop`, built by `scripts/loop_fixture.py`, must qualify on
product code: the harness no longer splices the continuity allowlist in-process. A fixture is looping iff its
`fixture.json` carries the `loop` record the builder adds; the P2 family is the P2 base without that key. Pre-check (a)
is enforced: every slide-1 `untitled.mov` and the handed-back carried element report `video.loop`, and the export
differs from P2 only in the spliced files, by `loopMode="looping"` keys. Synthetic fixtures are built from the committed
P2 slide JSON with the real builder, so the representation check reads Keynote-shaped bytes.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie  # noqa: E402
import live_continuity_probe as lcp  # noqa: E402
import loop_fixture  # noqa: E402
import managed_obs_qualify as q  # noqa: E402

from test_loop_fixture import _binary_manifest, _committed_source  # noqa: E402

SHAPE = (1080, 1920)
ARMED = {
    "instanceRect": {"x": 109.3517074584961, "y": 795.0361938476562, "w": 951.54296875, "h": 267.6214599609375},
    "movieSlot": 3, "assetKeys": ["untitled.mov"], "rects": [],
    "slotRects": [{"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
                  {"x": 1071.6833801269531, "y": 871.9523239135742, "w": 671.0, "h": 195.0},
                  {"x": 541.858301475681, "y": 721.0772309801108, "w": 181.0, "h": 161.0},
                  {"x": 105.1231918334961, "y": 790.846923828125, "w": 960.0, "h": 276.0},
                  {"x": 788.725538103768, "y": 672.9158876261134, "w": 353.0, "h": 313.0}],
    "overrideSlots": [4],
}
OPAQUE = np.array([26.0, 175.0, 0.0])
DOM = np.array([8.0, 52.0, 0.0])
K = 6


def checks_of(gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["check"]: c for c in gate["checks"]}


# --- env refusal ---------------------------------------------------------------------------------------------------------

def test_main_refuses_while_the_mm_opacity_env_is_set(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(q.GL_REPLAY_ENV, raising=False)
    monkeypatch.setenv(q.MM_OPACITY_ENV, "off")
    monkeypatch.setattr(q, "obs_running", lambda: pytest.fail("must refuse before looking for OBS"))
    with pytest.raises(SystemExit) as exc:
        q.main(["--arm", "g2", "--out", str(tmp_path)])
    assert exc.value.code == 2
    assert "OBED_LIVE_MM_OPACITY is set" in capsys.readouterr().err


def test_main_refuses_mmo_arms_on_a_grey_counter_fixture(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(q.MM_OPACITY_ENV, raising=False)
    monkeypatch.setattr(q, "fixture_counter", lambda _fixture: "grey")
    for arm in ("mmo", "mmo-cef"):
        with pytest.raises(SystemExit):
            q.main(["--arm", arm, "--out", str(tmp_path)])
        assert "needs the binary-counter fixture" in capsys.readouterr().err


# --- EXPECTED_STATS by patch mode ----------------------------------------------------------------------------------------

MODE_KEYED = ("frameLen", "occludedBands", "opacityUnproven")


def test_expected_stats_differ_only_in_frame_len_occluded_bands_and_the_unproven_set():
    on, off = q.EXPECTED_STATS["on"], q.EXPECTED_STATS["off"]
    assert on["frameLen"] == 96 and off["frameLen"] == 88
    assert on["occludedBands"] == 0 and off["occludedBands"] == 20
    assert on["opacityUnproven"] == [{"slot": 4, "reason": "size"}] and off["opacityUnproven"] == []
    assert {k: v for k, v in on.items() if k not in MODE_KEYED} == {k: v for k, v in off.items() if k not in MODE_KEYED} == q.G2_STATS


@pytest.mark.parametrize("mode", ["on", "off"])
def test_g2_stats_checks_pass_their_own_mode_and_fail_the_other(mode):
    other = "off" if mode == "on" else "on"
    good: list[dict[str, Any]] = []
    q.g2_stats_checks(good, dict(q.EXPECTED_STATS[mode]), mode)
    assert all(c["ok"] for c in good)
    bad: list[dict[str, Any]] = []
    q.g2_stats_checks(bad, dict(q.EXPECTED_STATS[other]), mode)
    assert {c["check"] for c in bad if not c["ok"]} == set(MODE_KEYED)


def test_g2_stats_checks_record_the_measured_value_and_state_the_expectation_source():
    # Review r1 F6: the patch-on occludedBands / unproven set come from headless Q0b; the check still enforces them in CEF,
    # records the CEF value it read, and says a mismatch is a finding, not a threshold to retune.
    checks: list[dict[str, Any]] = []
    q.g2_stats_checks(checks, {**q.EXPECTED_STATS["on"], "occludedBands": 3}, "on")
    by = {c["check"]: c for c in checks}
    assert by["occludedBands"]["value"] == 3 and not by["occludedBands"]["ok"] and by["occludedBands"]["enforced"]
    assert "headless Q0b only" in by["occludedBands"]["limit"]
    for key in ("frameLen", "opacityUnproven"):
        assert "headless hand-back plan §3.3 only" in by[key]["limit"]
    for key in MODE_KEYED:
        assert "root-cause, not a threshold to retune" in by[key]["limit"]
    assert "CEF, OD-2" in by["bandCount"]["limit"]
    off: list[dict[str, Any]] = []
    q.g2_stats_checks(off, dict(q.EXPECTED_STATS["off"]), "off")
    assert all("CEF, OD-2" in c["limit"] for c in off[1:])
    assert set(q.EXPECTED_STATS_SOURCE["on"]) == set(q.EXPECTED_STATS["on"])
    assert set(q.EXPECTED_STATS_SOURCE["off"]) == set(q.EXPECTED_STATS["off"])


def test_g2_stats_checks_fail_closed_without_a_reported_mode():
    checks: list[dict[str, Any]] = []
    q.g2_stats_checks(checks, dict(q.EXPECTED_STATS["on"]), None)
    assert [c["ok"] for c in checks] == [False]


# --- M3: opaque reference on the mm-off twin -----------------------------------------------------------------------------

# Content inset from the slot rect's left/top (px): the DOM and the fixed GL settle draw the slide-2 texture (content from
# 790.15 on the 788.7 slot rect); stock GL draws the magnified slide-1 texture ~2 px further in (hand-back plan §1.3).
DOM_INSET, STOCK_INSET = 1, 3
EDGE = "edge: G2-S alpha == G2-P3 (DOM) alpha"
EDGE_KB = "KB: edge, G2-P3 vs round(mm-off-S alpha x 0.2947) (stock geometry) fails"


def slot_shot(alpha: int, inset: int = DOM_INSET) -> np.ndarray:
    img = np.zeros((*SHAPE, 4), np.uint8)
    r = ARMED["slotRects"][4]
    img[q.rect_mask(SHAPE, {"x": r["x"] + inset, "y": r["y"] + inset, "w": r["w"] - 2 * inset, "h": r["h"] - 2 * inset})] = \
        (0, 175, 0, alpha)
    return img


def m3_run(tmp_path: Path, mm_off_alpha: int, g2_off_alpha: int = 75, g2_inset: int = DOM_INSET,
           mm_off_inset: int = STOCK_INSET, g2_stats: dict[str, Any] | None = None) -> dict[str, Any]:
    sessions = []
    for name, alpha, mode, inset in (("g2", 75, "on", g2_inset), ("g2-off", g2_off_alpha, "on", DOM_INSET),
                                     ("mm-off", mm_off_alpha, "off", mm_off_inset)):
        shots = {}
        for tag in ("S", "P3"):
            path = tmp_path / f"{name}-{tag}.png"
            Image.fromarray(slot_shot(alpha, inset) if tag == "S" else slot_shot(75)).save(path)
            shots[tag] = str(path)
        sessions.append({"session": name, "shots": shots, "output": {"mmOpacity": {"mode": mode}}})
    if g2_stats is not None:
        sessions[0]["reads"] = {"liveEnd": {"gl": {"api": {"stats": g2_stats}}}}
    return {"sessions": sessions, "rate": 25}


def test_m3_edge_reads_against_the_dom_and_its_kb_against_the_stock_geometry_twin(tmp_path):
    m3 = checks_of(q.g2_gates(m3_run(tmp_path, mm_off_alpha=255), ARMED)["M3"])
    assert m3["prerequisite: mm-off twin is patch off (opaque reference)"]["ok"]
    assert m3["T alpha (G2-S)"]["ok"]
    assert m3[EDGE]["ok"] and m3[EDGE]["enforced"] and m3[EDGE]["value"] == 0
    assert m3[EDGE_KB]["ok"] and m3[EDGE_KB]["enforced"] and m3[EDGE_KB]["value"] == 75
    assert m3["KB: edge vs unscaled mm-off-S alpha fails"]["ok"]
    assert m3["KB: mm-off-S T alpha fails the slot check"]["ok"]
    assert m3["prerequisite: mm-off-S T alpha is opaque (the KB reference)"]["ok"]
    t_off = m3["T alpha (g2-off-S, patch on, GL replay off)"]
    assert t_off["ok"] and t_off["enforced"] and t_off["value"] == [75, 75]


@pytest.mark.parametrize("g2_off_alpha", [255, 60, 90])
def test_m3_fails_a_g2_off_square_that_is_not_the_patchs_alpha(tmp_path, g2_off_alpha):
    # Review r1 F11: the one direct CEF read of the fix with G2 absent is enforced, not report-only.
    m3 = q.g2_gates(m3_run(tmp_path, mm_off_alpha=255, g2_off_alpha=g2_off_alpha), ARMED)["M3"]
    assert "T alpha (g2-off-S, patch on, GL replay off)" in m3["failing"]


def test_m3_with_a_translucent_reference_fails_the_edge_check_and_the_kb(tmp_path):
    """What the old g2-off reference reads once the patch is on: the KB passes the slot check."""
    m3 = checks_of(q.g2_gates(m3_run(tmp_path, mm_off_alpha=75), ARMED)["M3"])
    assert not m3["KB: mm-off-S T alpha fails the slot check"]["ok"]
    assert not m3["prerequisite: mm-off-S T alpha is opaque (the KB reference)"]["ok"]


def test_m3_edge_fails_a_g2_settle_with_the_stock_geometry(tmp_path):
    # The known-bad for the re-cast edge check: G2 replaying today's (pre-fix) settle, ~2 px inside the DOM edge.
    m3 = q.g2_gates(m3_run(tmp_path, mm_off_alpha=255, g2_inset=STOCK_INSET), ARMED)["M3"]
    assert EDGE in m3["failing"]
    assert checks_of(m3)[EDGE]["value"] == 75


def test_m3_edge_kb_fails_closed_when_the_twin_has_the_dom_geometry(tmp_path):
    # If the mm-off twin's settle were already on the DOM geometry, the KB cannot show the edge check sees a geometry
    # error: the KB check itself fails (the gate FAILs), it never passes silently.
    m3 = q.g2_gates(m3_run(tmp_path, mm_off_alpha=255, mm_off_inset=DOM_INSET), ARMED)["M3"]
    assert EDGE_KB in m3["failing"]
    assert checks_of(m3)[EDGE_KB]["value"] == 0


def test_m3_refuses_an_mm_off_twin_that_ran_with_the_patch(tmp_path):
    run = m3_run(tmp_path, mm_off_alpha=255)
    run["sessions"][2]["output"]["mmOpacity"]["mode"] = "on"
    m3 = q.g2_gates(run, ARMED)["M3"]
    assert "prerequisite: mm-off twin is patch off (opaque reference)" in m3["failing"]


def test_m1_reads_g2_stats_by_the_g2_sessions_patch_mode(tmp_path):
    run = m3_run(tmp_path, mm_off_alpha=255)
    run["sessions"][0]["reads"] = {"liveEnd": {"gl": {"api": {"stats": dict(q.EXPECTED_STATS["on"])}}}}
    m1 = checks_of(q.g2_gates(run, ARMED)["M1"])
    assert m1["mmOpacity mode (g2 / g2-off)"]["ok"]
    assert m1["occludedBands"]["ok"] and m1["occludedBands"]["value"] == 0
    assert m1["opacityUnproven"]["ok"]
    run["sessions"][0]["reads"]["liveEnd"]["gl"]["api"]["stats"]["occludedBands"] = 20
    assert not checks_of(q.g2_gates(run, ARMED)["M1"])["occludedBands"]["ok"]


@pytest.mark.parametrize("mode, stats, unengaged", [
    ("on", dict(q.UNENGAGED_STATS), True),
    ("on", {**q.EXPECTED_STATS["on"], **q.UNENGAGED_STATS}, True),
    ("on", dict(q.EXPECTED_STATS["on"]), False),
    ("on", {**q.EXPECTED_STATS["on"], "frameLen": 88}, False),
    ("on", {**q.EXPECTED_STATS["on"], "frameLen": 86, **q.UNENGAGED_STATS}, True),
    ("on", {}, False),
    ("off", dict(q.EXPECTED_STATS["off"]), False),
    ("off", {**q.EXPECTED_STATS["off"], **q.UNENGAGED_STATS}, False),
])
def test_handback_unengaged_is_exactly_the_pre_fix_patch_on_signature(mode, stats, unengaged):
    session = {"session": "g2", "output": {"mmOpacity": {"mode": mode}}, "reads": {"liveEnd": {"gl": {"api": {"stats": stats}}}}}
    reason = q.handback_unengaged(session)
    assert (reason is not None) is unengaged
    if unengaged:
        assert "hand-back fix not engaged" in reason


def test_g2_take_with_an_unengaged_fix_is_invalid_not_failed(tmp_path):
    # Critique finding 3: the pre-fix stats and the stock settle geometry, from a run where the fix did not engage.
    stats = {**q.EXPECTED_STATS["on"], **q.UNENGAGED_STATS}
    run = m3_run(tmp_path, mm_off_alpha=255, g2_inset=STOCK_INSET, g2_stats=stats)
    gates = q.g2_gates(run, ARMED)
    assert gates["M1"]["verdict"] == "INVALID" and gates["M3"]["verdict"] == "INVALID"
    assert "hand-back fix not engaged" in gates["M3"]["invalid"]
    invalid: list[str] = []
    q.arm_gates("g2", run, types.SimpleNamespace(), ARMED, invalid)
    assert any("hand-back fix not engaged" in r for r in invalid)


def test_g2_take_with_an_engaged_fix_is_not_invalidated(tmp_path):
    gates = q.g2_gates(m3_run(tmp_path, mm_off_alpha=255, g2_stats=dict(q.EXPECTED_STATS["on"])), ARMED)
    assert gates["M1"]["invalid"] is None and gates["M3"]["invalid"] is None
    assert checks_of(gates["M1"])["frameLen"]["ok"] and checks_of(gates["M1"])["opacityUnproven"]["ok"]


# --- MO-2 masks ------------------------------------------------------------------------------------------------------------

def test_mmo_roi_top_is_from_to_intersection_minus_the_movie_eroded():
    masks = q.mmo_masks(ARMED, SHAPE)
    ys, xs = np.nonzero(masks["top"])
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (794, 807, 728, 786)
    assert masks["top"].sum() == 14 * 59
    assert not (masks["top"] & q.rect_mask(SHAPE, ARMED["instanceRect"], q.REGION_PAD)).any()
    ys, xs = np.nonzero(masks["empty"])
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (1150, 1199, 690, 779)


def test_mmo_masks_refuse_an_empty_patch_over_a_slot():
    armed = {**ARMED, "slotRects": [*ARMED["slotRects"], {"x": 1140.0, "y": 700.0, "w": 40.0, "h": 40.0}]}
    with pytest.raises(RuntimeError, match="empty patch overlaps"):
        q.mmo_masks(armed, SHAPE)


# --- MO-2 series scorers ---------------------------------------------------------------------------------------------------

PHASES = ["slide1-native"] * 8 + ["mm-move"] * 8 + ["slide2-live"] * 8 + ["slide2-handback"] * 8 + ["slide2-after"] * 4
GL_ROWS = set(range(11, 16)) | set(range(16, 24)) | set(range(24, 28))
MOVE_GL_ROWS = set(range(11, 16))


def over(background: float, alpha: float = q.MM_ALPHA) -> np.ndarray:
    return np.round(alpha * OPAQUE + (1 - alpha) * background)


def series(kind: str, poke: int | None = None, offset: float = 0.0, double: int | None = None) -> dict[str, np.ndarray]:
    """on: GL draws the square translucent (== DOM); off: GL opaque until build 1; off-live: opaque until G2 LIVE (slide2-live);
    square: alpha-squared GL; counter: translucent GL over a white/grey/black counter passing under half of ROI_top during
    the move (as the live p2-binary counter does); poke: one opaque frame at that row; double: at that row the DOM and GL
    squares overlap (alpha * (2 - alpha) over black)."""
    top = np.zeros((len(PHASES), K, 3))
    for row in range(len(PHASES)):
        value = DOM
        if row in GL_ROWS:
            if kind == "off" or (kind == "off-live" and row in MOVE_GL_ROWS):
                value = OPAQUE
            elif kind == "square":
                value = np.round(q.MM_ALPHA ** 2 * OPAQUE)
        top[row] = value + offset
        if kind == "counter" and row in MOVE_GL_ROWS:
            top[row, : K // 2] = over((0, 255, 128)[row % 3])
    if poke is not None:
        top[poke] = OPAQUE
    if double is not None:
        top[double] = np.round(q.MM_ALPHA * (2 - q.MM_ALPHA) * OPAQUE)
    return {"index": np.arange(len(PHASES)) + 100, "phase": np.array(PHASES), "pixels.top": np.clip(top, 0, 255).astype(np.uint8),
            "means.empty": np.zeros((len(PHASES), 3))}


def test_phase_median_and_reference_are_the_opaque_slide2_live_square():
    assert q.phase_median(series("off"), ("slide2-live",)).tolist() == [OPAQUE.tolist()] * K
    assert q.phase_median(series("on"), ("slide2-live",)).tolist() == [DOM.tolist()] * K
    assert q.phase_median(None, ("slide2-live",)) is None
    assert q.phase_median(series("on"), ("slide2-hidden",)) is None


def test_badness_accepts_the_square_over_any_neutral_background_and_rejects_the_rest():
    s_off = np.tile(OPAQUE, (K, 1))
    for background in (0, 64, 128, 255):
        top = np.tile(over(background), (1, K, 1))
        assert q.mmo_badness(top, s_off)[0] <= 1.0, background
    opaque = q.mmo_badness(np.tile(OPAQUE, (1, K, 1)), s_off)[0]
    assert opaque == pytest.approx((1 - q.MM_ALPHA) * (OPAQUE.max() - OPAQUE.min()))
    squared = q.mmo_badness(np.tile(np.round(q.MM_ALPHA ** 2 * OPAQUE), (1, K, 1)), s_off)[0]
    assert squared > 30
    tinted = q.mmo_badness(np.tile(over(0) + (0, 10, 0), (1, K, 1)), s_off)[0]
    assert tinted == pytest.approx(10, abs=1)
    too_bright = q.mmo_badness(np.full((1, K, 3), 255.0), np.zeros((K, 3)))[0]
    assert too_bright == pytest.approx(q.MM_ALPHA * 255)


def all_series(**over: dict[str, np.ndarray]) -> dict[str, dict[str, np.ndarray]]:
    base = {"g2-on": series("on"), "g2-mmoff": series("off-live"), "g2off-on": series("on"), "g2off-mmoff": series("off")}
    return {**base, **over}


def test_tau_is_the_worst_slide1_component_plus_one():
    s_off = np.tile(OPAQUE, (K, 1))
    cal = q.mmo_tau(all_series(), s_off)
    assert cal["domOnOff"] == {"g2-on/g2-mmoff": 0.0, "g2off-on/g2off-mmoff": 0.0}
    instrument = round(float(q.mmo_badness(np.tile(DOM, (1, K, 1)), s_off)[0]), 2)
    assert instrument < 1
    assert set(cal["instrument"].values()) == {instrument}
    assert cal["calibration"] == instrument
    assert cal["tau"] == round(instrument + 1, 2)


def test_tau_grows_with_an_on_vs_off_slide1_difference_and_is_none_when_a_session_is_missing():
    s_off = np.tile(OPAQUE, (K, 1))
    shifted = series("on")
    shifted["pixels.top"][:8] += 2
    cal = q.mmo_tau(all_series(**{"g2-on": shifted}), s_off)
    assert cal["domOnOff"]["g2-on/g2-mmoff"] == 2.0
    assert cal["tau"] >= 3.0
    assert q.mmo_tau(all_series(**{"g2off-on": None}), s_off)["tau"] is None


def test_series_checks_pass_the_patched_player_and_fail_every_patch_off_twin():
    s_off = np.tile(OPAQUE, (K, 1))
    tau = q.mmo_tau(all_series(), s_off)["tau"]
    on = q.mmo_series_checks(series("on"), s_off, tau)
    assert on["frames"] == 24 and on["R1"] == 0 and on["R2"] <= tau and on["R2Over"] == 0 and on["R2Frames"] == []
    assert on["handovers"] == {"moveStart": None, "build1": None}
    off_live = q.mmo_series_checks(series("off-live"), s_off, tau)
    assert off_live["R1"] == 5 and off_live["R1First"] == 111 and off_live["R2"] > tau and off_live["R2Over"] == 5
    off = q.mmo_series_checks(series("off"), s_off, tau)
    assert off["R1"] == 17 and off["R2"] > tau and off["R2Over"] == 17
    assert [f["index"] for f in off["R2Frames"]][:2] == [111, 112]
    assert off["R2Frames"][0]["alphaEffOverBlack"] == 1.0


def test_series_checks_pass_the_translucent_square_over_a_moving_white_counter():
    # The live failure of the old R2 (E from the empty patch) and R3 (raw steps): a white/grey/black counter passes under
    # the translucent square; each pixel is alpha * S + (1 - alpha) * B with B neutral, so the badness stays at the
    # slide-1 calibration while raw frame-to-frame steps reach ~180.
    s_off = np.tile(OPAQUE, (K, 1))
    tau = q.mmo_tau(all_series(), s_off)["tau"]
    counter = q.mmo_series_checks(series("counter"), s_off, tau)
    assert np.abs(np.diff(series("counter")["pixels.top"].astype(float), axis=0)).max() > 170
    assert counter["R1"] == 0 and counter["R2"] <= tau and counter["R2Over"] == 0
    assert counter["handovers"]["moveStart"][1]["index"] == 111


def test_series_checks_catch_a_one_frame_opaque_pop_and_the_alpha_squared_player():
    s_off = np.tile(OPAQUE, (K, 1))
    tau = q.mmo_tau(all_series(), s_off)["tau"]
    pop = q.mmo_series_checks(series("on", poke=26), s_off, tau)
    assert pop["R1"] == 1 and pop["R2Frame"] == 126 and pop["R2"] > tau and pop["R2Over"] == 1
    assert pop["R2Frames"][0]["phase"] == "slide2-handback" and pop["R2Frames"][0]["row"] == 26
    square = q.mmo_series_checks(series("square"), s_off, tau)
    assert square["R1"] == 0 and square["R2"] > tau and square["R2Over"] == 17


def test_series_checks_catch_a_double_frame_and_estimate_its_alpha():
    # One frame where the DOM and GL squares overlap: over black it reads alpha * (2 - alpha) * S (~0.50), as the live
    # 30 fps g2off-on take does at the first GL frame of the move. No allowance: it FAILs and is reported.
    s_off = np.tile(OPAQUE, (K, 1))
    tau = q.mmo_tau(all_series(), s_off)["tau"]
    double = q.mmo_series_checks(series("on", double=11), s_off, tau)
    assert double["R1"] == 0 and double["R2Over"] == 1 and double["R2Frame"] == 111
    frame = double["R2Frames"][0]
    assert frame["phase"] == "mm-move"
    assert frame["alphaEffOverBlack"] == pytest.approx(q.MM_ALPHA * (2 - q.MM_ALPHA), abs=0.01)
    assert double["handovers"]["moveStart"][1] == frame


def test_series_checks_report_the_handover_frames_of_the_patch_off_twin():
    s_off = np.tile(OPAQUE, (K, 1))
    handovers = q.mmo_series_checks(series("off"), s_off, 2.0)["handovers"]
    assert [f["index"] for f in handovers["moveStart"]] == [110, 111]
    assert [f["phase"] for f in handovers["moveStart"]] == ["mm-move", "mm-move"]
    assert [f["index"] for f in handovers["build1"]] == [127, 128]
    assert handovers["build1"][0]["badness"] > 2.0 >= handovers["build1"][1]["badness"]


def test_series_checks_ignore_frames_outside_the_window():
    s_off = np.tile(OPAQUE, (K, 1))
    after_only = series("on", poke=34)
    assert q.mmo_series_checks(after_only, s_off, 2.0)["R1"] == 0


def test_series_checks_read_none_without_a_reference_or_tau():
    assert q.mmo_series_checks(series("on"), None, 2.0)["R1"] is None
    assert q.mmo_series_checks(series("on"), np.tile(OPAQUE, (K, 1)), None)["R2"] is None
    assert q.mmo_series_checks(None, np.tile(OPAQUE, (K, 1)), 2.0)["frames"] == 0


# --- MO-2 key (R4) and CvC -----------------------------------------------------------------------------------------------

def key_shot(alpha: int, empty: int = 0) -> np.ndarray:
    img = np.zeros((*SHAPE, 4), np.uint8)
    masks = q.mmo_masks(ARMED, SHAPE)
    img[masks["top"]] = (0, 175, 0, alpha)
    img[masks["empty"]] = (255, 255, 255, empty)
    return img


def key_shots(on_m: int = 75) -> dict[str, dict[str, np.ndarray]]:
    return {"g2-on": {"D": key_shot(75), "M": key_shot(on_m)}, "g2-mmoff": {"D": key_shot(75), "M": key_shot(255)},
            "g2off-on": {"D": key_shot(75), "M": key_shot(on_m)}, "g2off-mmoff": {"D": key_shot(75), "M": key_shot(255)}}


def test_key_r4_passes_translucent_settle_and_fails_the_opaque_twins():
    key = q.mmo_key(key_shots(), q.mmo_masks(ARMED, SHAPE))
    assert key["domOnOff"] == {"g2-on/g2-mmoff": 0.0, "g2off-on/g2off-mmoff": 0.0}
    assert key["tauKey"] == round(abs(75 - q.MM_ALPHA * 255) + 1, 2)
    assert key["R4"] == {"g2-on": 0.0, "g2-mmoff": 180.0, "g2off-on": 0.0, "g2off-mmoff": 180.0}


def test_tau_key_takes_the_background_from_the_slide2_settle_shot_not_slide1():
    # Live MO-2 r1: slide-1 content covers the empty patch in D (alpha 128/255), so E_key from D's patch read ~188 against a
    # DOM key of 75 and tau_key came out 114. The patch is empty only on slide 2 (mmo_masks), so M supplies it.
    shots = key_shots()
    for pair in shots.values():
        pair["D"] = key_shot(75, empty=255)
    key = q.mmo_key(shots, q.mmo_masks(ARMED, SHAPE))
    assert key["tauKey"] == round(abs(75 - q.MM_ALPHA * 255) + 1, 2)
    assert key["tauKey"] < 2
    shots["g2-on"]["M"] = key_shot(75, empty=100)
    assert q.mmo_key(shots, q.mmo_masks(ARMED, SHAPE))["instrument"]["g2-on"] == pytest.approx(
        abs(75 - (q.MM_ALPHA * 255 + (1 - q.MM_ALPHA) * 100)))


def test_key_r4_catches_an_opaque_settle_and_is_none_without_the_reference():
    key = q.mmo_key(key_shots(on_m=255), q.mmo_masks(ARMED, SHAPE))
    assert key["R4"]["g2-on"] == 180.0
    shots = key_shots()
    shots["g2off-mmoff"]["M"] = None
    assert q.mmo_key(shots, q.mmo_masks(ARMED, SHAPE))["tauKey"] is None


def test_cvc_reads_zero_on_identical_sessions_and_the_worst_delta_otherwise():
    top = q.mmo_masks(ARMED, SHAPE)["top"]
    same = q.mmo_cvc(series("on"), series("on"), {"D": key_shot(75), "M": key_shot(75)}, {"D": key_shot(75), "M": key_shot(75)}, top)
    assert same["max"] == 0.0
    moved = q.mmo_cvc(series("on"), series("on", offset=3), {"D": key_shot(75), "M": key_shot(75)},
                      {"D": key_shot(75), "M": key_shot(76)}, top)
    assert moved["max"] == 3.0 and moved["values"]["key M"] == 1.0
    assert q.mmo_cvc(series("on"), None, {}, {}, top)["max"] is None


# --- MO-2 / MO-4 gates end to end ------------------------------------------------------------------------------------------

def mmo_run(tmp_path: Path, rate: int = 25, **over: Any) -> dict[str, Any]:
    kinds = {"g2-on": "on", "g2-mmoff": "off-live", "g2off-on": "on", "g2off-mmoff": "off", "g2-on-2": "on"}
    names = list(kinds)
    sessions = []
    for name in names:
        ser = over.get(f"series:{name}") or series(kinds[name])
        path = tmp_path / f"{rate}-{name}-series.npz"
        np.savez_compressed(path, **ser)
        opaque_m = kinds[name] != "on" and not over.get(f"translucentM:{name}")
        shots = {}
        for tag, alpha in (("D", 75), ("M", 255 if opaque_m else 75)):
            shot = tmp_path / f"{rate}-{name}-{tag}.png"
            Image.fromarray(key_shot(alpha)).save(shot)
            shots[tag] = str(shot)
        mode = q.MM_MODES[q.MMO_SESSIONS[q.mmo_base(name)][1]]
        stats = over.get(f"stats:{name}") or dict(q.EXPECTED_STATS[mode])
        sessions.append({"session": name, "decode": {"seriesPath": str(path), "phases": {}}, "shots": shots,
                         "output": {"mmOpacity": {"mode": over.get(f"mode:{name}", mode)}}, "liveWait": {"live": True},
                         "reads": {"liveEnd": {"gl": {"api": {"stats": stats}}}}})
    return {"rate": rate, "sessions": sessions}


def test_mmo_gates_pass_the_patched_player_with_every_kb_failing(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path), ARMED)
    assert gates["MO-2"]["verdict"] == "PASS", gates["MO-2"]["failing"]
    assert gates["MO-4"]["verdict"] == "PASS", gates["MO-4"]["failing"]
    checks = checks_of(gates["MO-2"])
    for off in ("g2-mmoff", "g2off-mmoff"):
        for r in ("R1", "R2: neutral-background badness (R3 folded in)", "R4: key alpha |M - D|"):
            assert checks[f"KB: {off} {r}"]["ok"]
    assert checks["CvC g2-on vs g2-on-2 before tau"]["value"]["max"] == 0.0
    assert gates["mmoCalibration"]["cvc"]["max"] == 0.0


def test_mmo_r4_kb_is_enforced_only_on_the_twin_without_g2(tmp_path):
    """Live 2026-09-25: with G2 on and the patch off, G2's LIVE override makes the settle key translucent whenever shot M
    lands after LIVE, so the g2-mmoff R4 KB is timing luck and only reported; the G2-less twin must still fail R4."""
    gates = q.mmo_gates(mmo_run(tmp_path, **{"translucentM:g2-mmoff": True}), ARMED)
    checks = checks_of(gates["MO-2"])
    assert gates["MO-2"]["verdict"] == "PASS", gates["MO-2"]["failing"]
    assert not checks["KB: g2-mmoff R4: key alpha |M - D|"]["ok"]
    assert not checks["KB: g2-mmoff R4: key alpha |M - D|"]["enforced"]
    assert checks["KB: g2off-mmoff R4: key alpha |M - D|"]["enforced"]
    (tmp_path / "b").mkdir()
    failed = q.mmo_gates(mmo_run(tmp_path / "b", **{"translucentM:g2off-mmoff": True}), ARMED)
    assert "KB: g2off-mmoff R4: key alpha |M - D|" in failed["MO-2"]["failing"]


def test_mmo_gates_fail_a_one_frame_opaque_pop_in_the_patched_session(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-on": series("on", poke=20)}), ARMED)
    failing = gates["MO-2"]["failing"]
    assert "g2-on R1: frames within tau of S_off" in failing
    assert "g2-on R2: neutral-background badness (R3 folded in)" in failing
    assert "g2-on-2" not in " ".join(failing)


def test_mmo_gates_fail_when_the_patch_off_twin_reads_like_the_patch(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-mmoff": series("on")}), ARMED)
    assert "KB: g2-mmoff R1" in gates["MO-2"]["failing"]
    assert "KB: g2-mmoff R2: neutral-background badness (R3 folded in)" in gates["MO-2"]["failing"]


def test_mmo_gates_fail_a_cvc_over_two(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-on-2": series("on", offset=3)}), ARMED)
    assert gates["MO-2"]["failing"] == ["CvC g2-on vs g2-on-2 before tau"]


def test_mmo_gates_at_rate_30_run_their_own_cvc(tmp_path):
    # Review r1 F7: tau is per take, so each rate's take carries its own control-vs-control.
    gates = q.mmo_gates(mmo_run(tmp_path, rate=30), ARMED)
    assert gates["MO-2"]["verdict"] == "PASS"
    assert checks_of(gates["MO-2"])["CvC g2-on vs g2-on-2 before tau"]["ok"]
    assert gates["mmoCalibration"]["cvc"]["max"] == 0.0
    failing = q.mmo_gates(mmo_run(tmp_path, rate=30, **{"series:g2-on-2": series("on", offset=3)}), ARMED)["MO-2"]["failing"]
    assert failing == ["CvC g2-on vs g2-on-2 before tau"]


def test_mmo_gates_without_the_cvc_session_fail(tmp_path):
    run = mmo_run(tmp_path, rate=30)
    run["sessions"] = [s for s in run["sessions"] if s["session"] != q.MMO_CVC[1]]
    assert "CvC g2-on vs g2-on-2 before tau" in q.mmo_gates(run, ARMED)["MO-2"]["failing"]


def test_mmo_gates_refuse_a_session_that_ran_in_the_wrong_patch_mode(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"mode:g2off-mmoff": "on"}), ARMED)
    assert "g2off-mmoff: mmOpacity mode" in gates["MO-2"]["failing"]


def test_mmo_gates_fail_without_the_opaque_reference(tmp_path):
    run = mmo_run(tmp_path)
    run["sessions"] = [s for s in run["sessions"] if s["session"] != q.MMO_REFERENCE]
    failing = q.mmo_gates(run, ARMED)["MO-2"]["failing"]
    assert "S_off: g2off-mmoff slide2-live ROI_top" in failing
    assert "g2-on R1: frames within tau of S_off" in failing


def test_mmo_gates_pass_the_counter_under_the_square_and_fail_one_double_frame(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2off-on": series("counter")}), ARMED)
    assert gates["MO-2"]["verdict"] == "PASS", gates["MO-2"]["failing"]
    gates = q.mmo_gates(mmo_run(tmp_path, rate=30, **{"series:g2off-on": series("counter", double=11)}), ARMED)
    assert gates["MO-2"]["failing"] == ["g2off-on R2: neutral-background badness (R3 folded in)"]
    value = checks_of(gates["MO-2"])["g2off-on R2: neutral-background badness (R3 folded in)"]["value"]
    assert value["R2Over"] == 1 and value["R2Frames"][0]["index"] == 111
    assert gates["mmoCalibration"]["doubleFrameAlpha"] == pytest.approx(value["R2Frames"][0]["alphaEffOverBlack"], abs=0.01)


def test_mmo_gates_pass_chroma_rounding_over_the_white_counter_under_the_floor(tmp_path):
    # Review r2 F1: live, a correct square over the white counter reads up to 4.31 (blend rounding), over a tau calibrated on
    # black only (4.57); the next rounding step would false-FAIL. R2's limit is max(tau, MMO_R2_FLOOR): ~5 levels of chroma
    # error over B >= 150 PASS (and stay listed as tau crossings, with their background), a double frame still FAILs.
    bright = series("counter")
    bright["pixels.top"][13] = np.round(over(255) + (5, 0, 0)).astype(np.uint8)
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2off-on": bright}), ARMED)
    assert gates["MO-2"]["verdict"] == "PASS", gates["MO-2"]["failing"]
    tau, limit = gates["mmoCalibration"]["tau"], gates["mmoCalibration"]["r2Limit"]
    assert tau < 5 < limit == q.MMO_R2_FLOOR
    value = checks_of(gates["MO-2"])["g2off-on R2: neutral-background badness (R3 folded in)"]["value"]
    assert tau < value["R2"] <= limit and value["R2Over"] == 1
    assert value["R2Frames"][0]["index"] == 113 and value["R2Frames"][0]["background"] >= 150
    double = series("counter", double=11)
    double["pixels.top"][13] = bright["pixels.top"][13]
    failed = q.mmo_gates(mmo_run(tmp_path, rate=30, **{"series:g2off-on": double}), ARMED)
    assert failed["MO-2"]["failing"] == ["g2off-on R2: neutral-background badness (R3 folded in)"]


def test_mmo_gates_gate_the_cvc_sessions_r2(tmp_path):
    # Review r2 F1: g2-on-2 is a patch-on sample too; a double frame in the move (outside the CvC phases) fails its R2.
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-on-2": series("on", double=12)}), ARMED)
    assert gates["MO-2"]["failing"] == ["g2-on-2 R2: neutral-background badness (R3 folded in)"]
    assert gates["mmoCalibration"]["perSession"]["g2-on-2"]["R2Frame"] == 112


def test_mmo_gates_are_inconclusive_when_the_square_is_grey(tmp_path):
    # Review r2 F4: R2 sees an alpha error only as delta-alpha * spread(S_off); a grey square hides it, so MO-2 is
    # INCONCLUSIVE rather than PASS. The live square (spread 172) has alphaFloor ~0.047.
    grey = series("off")
    grey["pixels.top"][16:24] = 120
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2off-mmoff": grey}), ARMED)
    assert gates["MO-2"]["verdict"] == "INVALID"
    assert "alphaFloor" in gates["MO-2"]["invalid"] and "coloured square" in gates["MO-2"]["invalid"]
    assert not checks_of(gates["MO-2"])["premise: S_off is coloured (R2's alphaFloor = limit / min channel spread)"]["ok"]
    (tmp_path / "ok").mkdir()
    ok = q.mmo_gates(mmo_run(tmp_path / "ok"), ARMED)["mmoCalibration"]["alphaFloor"]
    assert ok == pytest.approx(q.MMO_R2_FLOOR / (OPAQUE.max() - OPAQUE.min()), abs=1e-3) and ok <= q.MMO_ALPHA_FLOOR_MAX


def test_mmo_gates_are_inconclusive_when_slide1_backgrounds_are_not_neutral(tmp_path):
    tinted = {}
    for name, kind in (("g2-on", "on"), ("g2-mmoff", "off-live"), ("g2off-on", "on"), ("g2off-mmoff", "off"), ("g2-on-2", "on")):
        ser = series(kind)
        ser["pixels.top"][:8] = np.round(over(0) + (0, 20, 0)).astype(np.uint8)
        tinted[f"series:{name}"] = ser
    gates = q.mmo_gates(mmo_run(tmp_path, **tinted), ARMED)
    assert gates["MO-2"]["verdict"] == "INVALID"
    assert "INCONCLUSIVE" in gates["MO-2"]["invalid"]
    assert not checks_of(gates["MO-2"])["premise: slide-1 badness (neutral backgrounds under ROI_top)"]["ok"]
    run, invalid = mmo_run(tmp_path, **tinted), []
    q.arm_gates("mmo", run, types.SimpleNamespace(), ARMED, invalid)
    assert invalid and "INCONCLUSIVE" in invalid[0]


def test_score_rescores_saved_takes_without_obs(monkeypatch, tmp_path, capsys):
    # Review r2 F3: --score reads MO-2 takes only (not mmo-cef), and carries each take's live validity, lifecycle checks and
    # fixture identity into its verdict, so a take that failed clean quit live cannot rescore as PASS.
    (tmp_path / "runs").mkdir()
    identity = {"manifestSha256": "m", "movieSha256": ["a"]}
    clean_quit = {"check": "clean quit", "ok": True, "enforced": True}
    takes = {
        "mmo-25": (25, {}, {}),
        "mmo-30": (30, {"series:g2off-on": series("on", double=11)}, {}),
        "mmo-31": (25, {}, {"checks": [{**clean_quit, "ok": False}]}),
        "mmo-32": (25, {}, {"valid": False, "invalid": ["Mac slept", "MO-2 INCONCLUSIVE: stale"]}),
        "mmo-33": (25, {}, {"fixtureIdentity": {"manifestSha256": "old", "movieSha256": ["a"]}}),
    }
    for stem, (rate, over_, extra) in takes.items():
        (tmp_path / stem).mkdir()
        run = {**mmo_run(tmp_path / stem, rate=rate, **over_), "arm": "mmo", "fixture": str(tmp_path / "p2-binary"),
               "fixtureIdentity": identity, "valid": True, "invalid": [], "checks": [clean_quit], **extra}
        (tmp_path / "runs" / f"{stem}.json").write_text(json.dumps(run))
    (tmp_path / "runs" / "mmo-cef-x.json").write_text(json.dumps({"arm": "mmo-cef", "sessions": []}))
    (tmp_path / "runs" / "summary-x.json").write_text("{}")
    facts: list[Path] = []
    monkeypatch.setattr(q, "fixture_facts", lambda fixture: facts.append(fixture) or ARMED)
    monkeypatch.setattr(q.binary_counter_movie, "verify_fixture", lambda fixture: identity)
    monkeypatch.setattr(q, "obs_running", lambda: pytest.fail("--score must not look for OBS"))
    assert q.main(["--score", str(tmp_path)]) == 1
    assert facts == [tmp_path / "p2-binary"]
    results = {r["run"]: r for r in json.loads(next(tmp_path.glob("rescore-*.json")).read_text())}
    assert sorted(results) == [f"{stem}.json" for stem in takes]
    got = {k: (r["rate"], r["verdict"], r["MO-2"], r["failing"], r["lifecycle"], r["invalid"]) for k, r in results.items()}
    assert got["mmo-25.json"] == (25, "PASS", "PASS", [], [], [])
    assert got["mmo-30.json"] == (30, "FAIL", "FAIL", ["g2off-on R2: neutral-background badness (R3 folded in)"], [], [])
    assert got["mmo-31.json"] == (25, "FAIL", "PASS", [], ["clean quit"], [])
    assert got["mmo-32.json"] == (25, "INVALID", "PASS", [], [], ["Mac slept"])
    assert got["mmo-33.json"][:5] == (25, "INVALID", "PASS", [], [])
    assert "fixture identity changed" in got["mmo-33.json"][5][0]
    out = capsys.readouterr().out
    assert "[mmo rate 30 mmo-30] FAIL  MO-2 FAIL" in out and "[mmo rate 25 mmo-31] FAIL  MO-2 PASS" in out


def test_mmo_mo4_reads_g2_facts_per_patch_mode(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"stats:g2-on": dict(q.EXPECTED_STATS["off"])}), ARMED)
    assert set(gates["MO-4"]["failing"]) == {"g2-on: frameLen", "g2-on: occludedBands", "g2-on: opacityUnproven"}


def test_mmo_mo4_fails_an_unproven_set_that_is_neither_baseline(tmp_path):
    stats = {**q.EXPECTED_STATS["on"], "opacityUnproven": [{"slot": 2, "reason": "size"}, {"slot": 4, "reason": "size"}]}
    gates = q.mmo_gates(mmo_run(tmp_path, **{"stats:g2-on": stats}), ARMED)
    assert gates["MO-4"]["verdict"] == "FAIL" and gates["MO-4"]["failing"] == ["g2-on: opacityUnproven"]


def test_mmo_take_with_an_unengaged_fix_is_invalid(tmp_path):
    run = mmo_run(tmp_path, **{"stats:g2-on": {**q.EXPECTED_STATS["on"], "frameLen": 88, **q.UNENGAGED_STATS}})
    gates = q.mmo_gates(run, ARMED)
    assert gates["MO-4"]["verdict"] == "INVALID" and gates["MO-2"]["verdict"] == "INVALID"
    invalid: list[str] = []
    q.arm_gates("mmo", run, types.SimpleNamespace(), ARMED, invalid)
    assert invalid == ["MO-2 INCONCLUSIVE: g2-on: hand-back fix not engaged (G2 frameLen 88, unproven rest-opacity)"]


def test_mmo_take_is_invalid_when_the_cvc_session_g2_on_2_did_not_engage(tmp_path):
    # Review r1 F2: g2-on-2 feeds the enforced MO-2 CvC; a non-engaged CvC twin must not read as a control.
    run = mmo_run(tmp_path, **{"stats:g2-on-2": {**q.EXPECTED_STATS["on"], "frameLen": 88, **q.UNENGAGED_STATS}})
    gates = q.mmo_gates(run, ARMED)
    assert gates["MO-2"]["verdict"] == "INVALID" and "g2-on-2: hand-back fix not engaged" in gates["MO-2"]["invalid"]
    assert gates["MO-4"]["verdict"] == "PASS"
    invalid: list[str] = []
    q.arm_gates("mmo", run, types.SimpleNamespace(), ARMED, invalid)
    assert len(invalid) == 1 and "g2-on-2: hand-back fix not engaged" in invalid[0]


def test_mmo_g2off_on_has_no_engagement_signal_and_is_not_invalidated(tmp_path):
    run = mmo_run(tmp_path, **{"stats:g2off-on": {**q.EXPECTED_STATS["on"], **q.UNENGAGED_STATS}})
    gates = q.mmo_gates(run, ARMED)
    assert gates["MO-2"]["invalid"] is None and gates["MO-4"]["invalid"] is None


# --- HB-OBS hand-back geometry (report-only, decision 7a) ---------------------------------------------------------------

DOM_GREEN, STOCK_GREEN = (790, 675, 1141, 985), (792, 676, 1139, 983)


def y_plane(green: tuple[int, int, int, int]) -> np.ndarray:
    """A tv-range Y plane on the P2 layout: the green square (Y 100), the sentinel's 4-px white stroke, the white movie."""
    y = np.full((1080, 1920), 16, np.uint8)
    y[790:1060, 104:1066] = 235
    y[722:880, 543:723] = 235
    y[726:880, 547:719] = 16
    x0, y0, x1, y1 = green
    y[y0:y1, x0:x1] = 100
    return y


def hb_series(change_row: int | None = 5, n: int = 10) -> dict[str, np.ndarray]:
    top = np.zeros((n, 4, 3), np.uint8)
    if change_row is not None:
        top[change_row:] = 7
    return {"index": np.arange(100, 100 + n), "phase": np.array(["slide2-live"] * 2 + ["slide2-handback"] * (n - 2)),
            "pixels.top": top}


def fake_recording(monkeypatch, dom_from: int, gl: tuple[int, ...] = STOCK_GREEN) -> list[tuple[int, int]]:
    reads: list[tuple[int, int]] = []

    def recording_y(recording, first, last, size=q.HB_OBS_SIZE):
        reads.append((first, last))
        for n in range(first, last + 1):
            yield n, y_plane(DOM_GREEN if n >= dom_from else gl)

    monkeypatch.setattr(q, "recording_y", recording_y)
    return reads


def test_hb_obs_scores_the_build1_pair_found_by_the_roi_top_change(monkeypatch):
    reads = fake_recording(monkeypatch, dom_from=105)
    hb = q.handback_geometry(Path("x.avi"), hb_series(5), (1920, 1080))
    assert (hb["locator"], hb["gl"], hb["dom"]) == ("ROI_top build-1 change", 104, 105)
    assert reads == [(103, 106)]
    assert hb["delta"]["green.left"] == -2.0 and hb["delta"]["green.right"] == 2.0 and hb["delta"]["green.bottom"] == 2.0
    assert hb["max"] == 2.0 and hb["static"] == 0.0 and hb["weak"] == []
    assert hb["nullGL"] == hb["nullDOM"] == 0.0


def test_hb_obs_reads_zero_when_the_settle_already_matches_the_dom(monkeypatch):
    fake_recording(monkeypatch, dom_from=105, gl=DOM_GREEN)
    hb = q.handback_geometry(Path("x.avi"), hb_series(5), (1920, 1080))
    assert hb["max"] == 0.0 and hb["nullGL"] == hb["nullDOM"] == 0.0


def test_hb_obs_without_a_roi_top_change_takes_the_largest_edge_step_in_the_handback(monkeypatch):
    fake_recording(monkeypatch, dom_from=106)
    hb = q.handback_geometry(Path("x.avi"), hb_series(None), (1920, 1080))
    assert (hb["locator"], hb["gl"], hb["dom"], hb["max"]) == ("largest hand-back edge step in slide2-handback", 105, 106, 2.0)


def test_hb_obs_is_report_only_and_never_fails_a_take(tmp_path, monkeypatch):
    assert "error" in q.handback_geometry(Path("x.avi"), hb_series(5), (1280, 720))
    monkeypatch.setattr(q, "handback_geometry", lambda *a: 1 / 0)
    assert q.handback_geometry_safe(Path("x.avi"), hb_series(5), (1920, 1080)) == {"error": "ZeroDivisionError: division by zero"}
    run = mmo_run(tmp_path)
    for sess in run["sessions"]:
        sess["decode"]["handbackGeometry"] = {"max": 2.765}
    gates = q.mmo_gates(run, ARMED)
    assert gates["MO-2"]["verdict"] == "PASS"
    report = checks_of(gates["MO-2"])["report: g2-on HB-OBS hand-back geometry max |DOM - GL| px (decision 7a)"]
    assert report["value"] == {"max": 2.765} and not report["ok"] and not report["enforced"]
    assert checks_of(gates["MO-2"])["report: g2-mmoff HB-OBS hand-back geometry max |DOM - GL| px (decision 7a)"]["ok"]


RECORDING = Path.home() / "Library/Application Support/Obed-Edom/qualify-home/recordings/mmo-20260925-143530/2026-09-25 14-35-31.avi"
SERIES = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/mmo-gates/obs-mo7/shots/mmo-20260925-143530/g2-on-series.npz")


@pytest.mark.skipif(not (RECORDING.exists() and SERIES.exists()), reason="REAL: the pre-fix mmo recording (g2-on, 25 fps) is not on this Mac")
def test_hb_obs_reads_the_stock_jump_on_a_real_pre_fix_recording():
    # Known-bad end to end: the plan's §1.3 table (Δ green right +2.765 at frames 408 -> 409), GL and DOM nulls 0.
    with np.load(SERIES) as data:
        ser = {k: data[k] for k in data.files}
    hb = q.handback_geometry(RECORDING, ser, (1920, 1080))
    assert (hb["gl"], hb["dom"], hb["max"], hb["nullGL"], hb["nullDOM"], hb["static"]) == (408, 409, 2.765, 0.0, 0.0, 0.0)
    assert hb["delta"]["green.left"] == -2.059


def test_mmo_summary_needs_both_rates_and_each_rates_cvc():
    def run(rate: int, cvc: float | None, valid: bool = True) -> dict[str, Any]:
        return {"arm": "mmo", "rate": rate, "valid": valid, "gates": {"mmoCalibration": {"cvc": None if cvc is None else {"max": cvc}}}}

    assert q.mmo_summary([]) == []
    assert all(c["ok"] for c in q.mmo_summary([run(25, 1.0), run(30, 2.0)]))
    failing = {c["check"] for c in q.mmo_summary([run(25, 3.0), run(30, 1.0, valid=False)]) if not c["ok"]}
    assert failing == {"MO-2: a valid take per rate", "MO-2 CvC (rate 25) gates that rate"}
    failing = {c["check"] for c in q.mmo_summary([run(25, 1.0), run(30, None)]) if not c["ok"]}
    assert failing == {"MO-2 CvC (rate 30) gates that rate"}


# --- MO-3 --------------------------------------------------------------------------------------------------------------------

def test_mmo_cef_gates_hand_records_to_the_probe_scorer(monkeypatch):
    seen: dict[str, Any] = {}

    def score_all(records: dict[str, Any]) -> dict[str, Any]:
        seen.update(records)
        return {"overall": "PASS", "modes": {gl: {"MO-1": {"verdict": "PASS", "reasons": []}} for gl in records}}

    monkeypatch.setattr(q.mm_opacity_probe, "score_all", score_all)
    sessions = [{"session": f"mo3-{gl}-{arm}", "mo1": {"gl": gl, "arm": arm, "log": {}}} for gl in q.MMO_CEF_GL
                for arm in q.mo3_arms(gl)]
    sessions[0]["fatal"] = "Traceback: boom"
    sessions[-1]["seedSplice"] = {"reason": q.mm_opacity_probe.FSD_REASON, "splices": 1}
    gates = q.mmo_cef_gates({"sessions": sessions})
    assert gates["MO-3"]["verdict"] == "PASS"
    assert seen["off"]["on"]["error"] == "Traceback: boom"
    assert set(seen["off"]) == set(q.mm_opacity_probe.ARMS)
    assert set(seen["auto"]) == set(q.mm_opacity_probe.ALL_ARMS)
    assert seen["auto"]["fsdoff"]["seedSplice"]["splices"] == 1


def test_mmo_cef_gates_fail_a_missing_arm_or_a_non_pass_gate(monkeypatch):
    monkeypatch.setattr(q.mm_opacity_probe, "score_all", lambda records: {
        "overall": "INCONCLUSIVE", "modes": {"auto": {"MO-1": {"verdict": "INCONCLUSIVE", "reasons": ["CvC FAIL"]}}}})
    sessions = [{"session": f"mo3-auto-{arm}", "mo1": {"gl": "auto", "arm": arm}} for arm in q.mm_opacity_probe.ALL_ARMS]
    failing = q.mmo_cef_gates({"sessions": sessions})["MO-3"]["failing"]
    assert failing == ["off: every arm ran", "auto MO-1"]
    sessions = [s for s in sessions if s["session"] != "mo3-auto-fsd"]
    assert "auto: every arm ran" in q.mmo_cef_gates({"sessions": sessions})["MO-3"]["failing"]


def test_mmo_cef_gates_score_real_probe_records_without_error():
    """Unmocked: empty records read INCONCLUSIVE, never PASS."""
    sessions = [{"session": f"mo3-{gl}-{arm}", "mo1": {"gl": gl, "arm": arm}} for gl in q.MMO_CEF_GL for arm in q.mo3_arms(gl)]
    gates = q.mmo_cef_gates({"sessions": sessions})
    assert gates["MO-3"]["verdict"] == "FAIL"
    assert gates["probeVerdict"]["overall"] != "PASS"


# --- session wiring ------------------------------------------------------------------------------------------------------------

class Args:
    kb = None
    precheck = False
    soak_minutes = 5


def captured_sessions(monkeypatch, arm: str, rate: int = 25) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(q, "run_session", lambda name, script, ctx, **kw: calls.append({"name": name, **kw}) or {"session": name})
    q.sessions_for(arm, {"rate": rate, "fixture": q.FIXTURE}, Args(), ARMED)
    return calls


def test_g2_arm_adds_an_unrecorded_patch_off_gl_off_twin(monkeypatch):
    calls = {c["name"]: c for c in captured_sessions(monkeypatch, "g2")}
    assert list(calls) == ["g2", "g2-off", "hidden-arm", "mm-off"]
    assert calls["mm-off"].get("gl_replay") == "off" and calls["mm-off"]["mm_opacity"] == "off"
    assert not calls["mm-off"].get("record")
    assert all(calls[n].get("mm_opacity", "auto") == "auto" for n in ("g2", "g2-off", "hidden-arm"))


@pytest.mark.parametrize("rate", [25, 30])
def test_mmo_arm_records_gl_by_patch_sessions_and_the_cvc_pair_at_every_rate(monkeypatch, rate):
    calls = captured_sessions(monkeypatch, "mmo", rate)
    assert [c["name"] for c in calls] == ["g2-on", "g2-mmoff", "g2off-on", "g2off-mmoff", "g2-on-2"]
    for c in calls:
        gl, mm = q.MMO_SESSIONS[q.mmo_base(c["name"])]
        assert c["gl_replay"] == gl and c["mm_opacity"] == mm and c["record"] is True


def test_mmo_cef_arm_runs_every_probe_arm_per_gl_mode_with_the_logger(monkeypatch):
    calls = captured_sessions(monkeypatch, "mmo-cef")
    assert [c["name"] for c in calls] == ([f"mo3-off-{a}" for a in ("on", "off", "off2", "sq")]
                                          + [f"mo3-auto-{a}" for a in ("on", "off", "off2", "sq", "fsd", "fsdoff")])
    for c in calls:
        arm = c["name"].split("-", 2)[2]
        assert c["logger"] is True and c["mm_opacity"] == q.mm_opacity_probe.ALL_ARMS[arm] and c["square"] == (arm == "sq")
        assert c["seed"] == ("frameLengthChanged" if arm in ("fsd", "fsdoff") else None)
        assert not c.get("record")


class FakeTransport:
    HASHES = ["#1", "#2", "#3", "#4", "#5", "#7", "#8"]

    def __init__(self, host: "DriveHost") -> None:
        self.host, self.labels = host, {}

    def evaluate(self, expression: str, deadline_s: float | None = None) -> Any:
        prefix = "window.__OBED_MMO__.setLabel("
        if expression.startswith(prefix):
            label, cfg = json.loads("[" + expression[len(prefix):-1] + "]")
            self.labels[label] = cfg
            return True
        if expression == lcp.HASH_JS:
            return self.HASHES[self.host.advances]
        if expression == q.GL_REPLAY_READ_JS:
            return {"api": {"state": "LIVE"}}
        return {}


class DriveHost:
    def __init__(self) -> None:
        self.advances = 0
        self.output = {"mmOpacity": {"mode": "on"}, "continuity": {}}
        self.transport = FakeTransport(self)

    def _require_transport(self) -> FakeTransport:
        return self.transport

    def execute(self, operation: str, slide: int | None = None) -> None:
        self.advances += operation == "advance"


def test_mo3_script_drives_the_logger_with_the_settle_roi_and_armed_movie_masks(monkeypatch):
    # Review r1 F1: MO-3's own copy of the loop sent the bare PLAN config (no ROI, no masks), so it could never PASS.
    import live_host_probe

    monkeypatch.setattr(lcp, "wait_for_decode", lambda host: {"ok": True})
    monkeypatch.setattr(live_host_probe, "wait_for_settlement", lambda host, timeout_s: ({}, 0.1))
    monkeypatch.setattr(q.mm_opacity_probe.time, "sleep", lambda s: None)
    monkeypatch.setattr(q, "obs_screenshot", lambda port, password: np.zeros((1080, 1920, 4), np.uint8))
    host = DriveHost()
    session = types.SimpleNamespace(host=host, creds=(1, "p"), out={})
    q.mo3_script("auto", "on", ARMED)(session)
    mm12 = host.transport.labels["mm12"]
    assert mm12["roi"] == q.mm_opacity_probe.settle_roi()
    assert mm12["masks"] == q.mm_opacity_probe.boundary_masks(ARMED) == [[103, 11, 965, 281], [107, 15, 956, 272]]
    rec = session.out["mo1"]
    assert rec["masks"] == mm12["masks"] and rec["roi"] == mm12["roi"] and rec["mmOpacityKwarg"] == "auto"
    assert [rec["steps"][0]["hashBefore"], rec["steps"][0]["hashAfter"]] == ["#1", "#2"]
    assert len(rec["liveGreen"]) == 12 * 58 * 3


class FakeHost:
    made: list[dict[str, Any]] = []

    def __init__(self, dest: Path, slides: Any, **kwargs: Any) -> None:
        FakeHost.made.append(kwargs)
        self.output = {"mmOpacity": {"mode": "on" if kwargs["mm_opacity"] == "auto" else "off"}}

    def observe(self) -> None:
        pass

    def stop(self) -> None:
        pass


@pytest.mark.parametrize("kwargs, want", [
    ({}, {"mm_opacity": "auto"}),
    ({"gl_replay": "off", "mm_opacity": "off"}, {"gl_replay": "off", "mm_opacity": "off"}),
    ({"gl_replay": "auto", "mm_opacity": "auto", "logger": True}, {"gl_replay": "auto", "mm_opacity": "auto", "transport_factory": q.LoggedCdp}),
])
def test_run_session_passes_mm_opacity_explicitly_and_the_logger_transport(monkeypatch, tmp_path, kwargs, want):
    FakeHost.made = []
    squares: list[bool] = []
    monkeypatch.setattr(q, "LiveOutputHost", FakeHost)
    monkeypatch.setattr(q, "make_export", lambda tag, fixture: (tmp_path / "x" / "html", []))
    monkeypatch.setattr(q, "start_log", lambda host: None)
    monkeypatch.setattr(q.mm_opacity_probe, "square_player", lambda active: squares.append(active) or __import__("contextlib").nullcontext())
    ctx = {"fixture": q.FIXTURE, "tag": "t", "endpoint": "http://127.0.0.1:9", "target": "x", "rate": 25, "creds": (1, "p"),
           "shots": tmp_path, "engineState": lambda: {}}
    out = q.run_session("s", lambda s: None, ctx, **kwargs)
    made = FakeHost.made[0]
    assert {k: made[k] for k in want} == want
    assert ("gl_replay" in made) == ("gl_replay" in kwargs)
    assert out["mmOpacityArg"] == want["mm_opacity"]
    assert squares == [False]


def test_run_session_enters_the_alpha_squared_splice_for_sq(monkeypatch, tmp_path):
    squares: list[bool] = []
    monkeypatch.setattr(q, "LiveOutputHost", FakeHost)
    monkeypatch.setattr(q, "make_export", lambda tag, fixture: (tmp_path / "x" / "html", []))
    monkeypatch.setattr(q, "start_log", lambda host: None)
    monkeypatch.setattr(q.mm_opacity_probe, "square_player", lambda active: squares.append(active) or __import__("contextlib").nullcontext())
    ctx = {"fixture": q.FIXTURE, "tag": "t", "endpoint": "e", "target": "x", "rate": 25, "creds": (1, "p"), "shots": tmp_path,
           "engineState": lambda: {}}
    out = q.run_session("s", lambda s: None, ctx, square=True)
    assert squares == [True] and out["square"] is True


def test_logged_cdp_installs_the_probe_logger_on_new_documents(monkeypatch):
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(q.ChromeCdp, "start", lambda self: None)
    cdp = q.LoggedCdp.__new__(q.LoggedCdp)
    cdp.call = lambda method, **params: calls.append((method, params))
    cdp.start()
    assert calls == [("Page.addScriptToEvaluateOnNewDocument", {"source": q.mm_opacity_probe.LOGGER_JS})]


def test_decode_session_moves_the_series_to_npz_and_out_of_the_result(monkeypatch, tmp_path):
    recording = tmp_path / "r.avi"
    recording.write_bytes(b"x")
    seen: dict[str, Any] = {}

    def decode_recording(path: Path, **kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {"phases": {}, "series": series("on")}

    monkeypatch.setattr(q.obs_cadence_decode, "decode_recording", decode_recording)
    masks = q.mmo_masks(ARMED, SHAPE)
    result = q.decode_session({"session": "g2-on"}, str(recording), rings=None, loop_frames=None, keep=True, masks=masks,
                              series_path=tmp_path / "g2-on-series.npz")
    assert "series" not in result
    assert seen["pixel_series"]["top"] is masks["top"] and seen["mean_series"]["empty"] is masks["empty"]
    loaded = q.load_series({"decode": result})
    assert loaded["pixels.top"].shape == (len(PHASES), K, 3) and list(loaded["phase"][:1]) == ["slide1-native"]


# --- looping soak fixture (loopMode WS-C) ------------------------------------------------------------------------------

HARNESS = REPO / "scripts" / "managed_obs_qualify.py"


def _manifest(root: Path, manifest: dict[str, Any] | None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (root / binary_counter_movie.MANIFEST).write_text(json.dumps(manifest))
    return root


@pytest.fixture
def looped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A P2 base (the harness's FIXTURE) and its `loop_fixture.build` copy with the binary manifest."""
    base = _committed_source(tmp_path / "p2")
    (base / binary_counter_movie.MANIFEST).write_text(json.dumps(_binary_manifest()))
    monkeypatch.setattr(q, "FIXTURE", base)
    dest = tmp_path / "p2-loop"
    loop_fixture.build(base, dest)
    return dest


class TestFixtureFamily:
    def test_binary_copy_without_loop_is_p2_family_and_not_looping(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "p2-binary", _binary_manifest())
        assert q.p2_family(fixture) is True
        assert q.fixture_loops(fixture) is False

    def test_a_loop_key_takes_it_out_of_the_p2_family_and_makes_it_looping(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "p2-loop", {**_binary_manifest(), "loop": {"objectIds": [], "planSha256": {}}})
        assert q.p2_family(fixture) is False
        assert q.fixture_loops(fixture) is True

    def test_the_p2_fixture_itself_is_p2_family(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _manifest(tmp_path / "p2", None)
        monkeypatch.setattr(q, "FIXTURE", base)
        assert q.p2_family(base) is True and q.fixture_loops(base) is False

    def test_no_manifest_elsewhere_is_neither(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "other", None)
        assert q.p2_family(fixture) is False, "no path-inequality inference: an unknown fixture is not P2"
        assert q.fixture_loops(fixture) is False, "and not looping either: looping is the manifest's loop key only"

    def test_a_different_base_is_not_p2_family(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "x", {**_binary_manifest(), "base": "elsewhere"})
        assert q.p2_family(fixture) is False

    def test_the_built_loop_fixture_is_looping(self, looped: Path) -> None:
        assert q.fixture_loops(looped) is True and q.p2_family(looped) is False

    def test_soak_default_is_p2_loop(self) -> None:
        assert q.SOAK_FIXTURE == q.REPO / "output/p2-loop"


class TestSpliceGone:
    def test_harness_never_patches_the_allowlist(self) -> None:
        text = HARNESS.read_text()
        assert "QUALIFIED_PLAN_SHA256" not in text
        assert not re.search(r"mock\.patch[^\n]*plan_signature", text)
        for name in ("allow_soak_plan", "build_fixture", "--build-fixture", "--i-have-owner-go", "allowlistSplice"):
            assert name not in text.replace("binary_counter_movie.py --build-fixture", ""), name
        assert not hasattr(q, "allow_soak_plan") and not hasattr(q, "build_fixture")

    def test_no_path_inequality_looping_inference(self) -> None:
        text = HARNESS.read_text()
        assert 'ctx["fixture"] != FIXTURE' not in text
        assert len(re.findall(r"not p2_family\(", text)) == 1, "the only negation is the non-soak arms' --fixture refusal"

    def test_cli_has_no_build_fixture(self) -> None:
        with pytest.raises(SystemExit):
            q.main(["--arm", "soak", "--build-fixture", "x.key"])

    def test_a_fixture_that_does_not_qualify_on_product_code_exits_clearly(self, tmp_path: Path) -> None:
        """Known-bad: a splice on slides 1-2 only derives, but its plan sha is not allowlisted (the conftest cache root holds the export)."""
        source = _committed_source(tmp_path / "p2")
        partial = tmp_path / "partial-loop"
        loop_fixture.build(source, partial, object_ids=("6BB39942", "CBACAF27", "F9AFED1B"), expected_shas=None)
        with pytest.raises(SystemExit, match="does not qualify on product code"):
            q.fixture_facts(partial)

    def test_the_built_loop_fixture_qualifies_on_product_code(self, looped: Path) -> None:
        """Control: the full five-movie splice is allowlisted on product code and yields the armed facts."""
        armed = q.fixture_facts(looped)
        assert {"instanceRect", "movieSlot", "assetKeys"} <= set(armed)


class TestLoopFrames:
    def test_matching_frames_pass(self, tmp_path: Path) -> None:
        q.check_loop_frames(_manifest(tmp_path / "f", _binary_manifest()))

    def test_no_manifest_passes(self, tmp_path: Path) -> None:
        q.check_loop_frames(_manifest(tmp_path / "f", None))

    def test_other_frames_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not the soak loop period 1381"):
            q.check_loop_frames(_manifest(tmp_path / "f", _binary_manifest(1380)))

    @pytest.mark.parametrize("movies", [[], None, [{"frames": 1381}, {"frames": 1380}]])
    def test_a_looping_manifest_without_exactly_1381_frames_exits(self, tmp_path: Path, movies: Any) -> None:
        """Codex r4 #6: a looping fixture must state its period; an empty movie list is not a pass."""
        manifest = {**_binary_manifest(), "movies": movies, "loop": {}}
        with pytest.raises(SystemExit, match="not the soak loop period 1381"):
            q.check_loop_frames(_manifest(tmp_path / "f", manifest))

    def test_the_built_loop_fixture_passes(self, looped: Path) -> None:
        q.check_loop_frames(looped)


def _post_handback(state: str = "RETIRED", mode: str = "handoff", el_id: Any = 7, handoffs: int = 1,
                   module: dict[str, Any] | None = None) -> dict[str, Any]:
    """A post-build-1 `GL_REPLAY_READ_JS` read: G2 retired by one canvas-removed hand-off, the runtime released `el_id`.

    Mirrors the real emitters: the runtime's `glRelease` notes `glreplay-release` with {ok, reason, mode, elId, retired}
    (live_continuity_js.py), and the G2 module embeds that same object as `glreplay-handoff.detail.released` before
    setting `API.state = 'RETIRED'` (live_gl_replay_js.py). `module` overrides fields of the embedded copy only."""
    released = {"ok": True, "reason": None, "mode": mode, "elId": el_id, "retired": []}
    handoff = {"released": {**released, **(module or {})}, "writebackFailed": False, "posterRestored": True,
               "completedMs": 3.5, "reason": "canvasRemoved"}
    return {
        "api": {"state": state, "standDowns": ["canvasRemoved"] if state == "RETIRED" else [],
                "events": [{"kind": "glreplay-handoff", "detail": handoff}] * handoffs},
        "coreEvents": [{"kind": "glreplay-carried", "detail": {"elId": el_id}},
                       {"kind": "glreplay-release", "detail": released}],
    }


def _session(**over: Any) -> dict[str, Any]:
    """A pre-check session that passes every check: two wraps, LIVE throughout, uploads rising."""
    times = [30.0, 40.0, 4.0, 14.0, 24.0, 34.0, 44.0, 8.0]
    session = {
        "session": "precheck",
        "slide1Videos": [
            {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True},
            {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True},
            {"src": "WA0125.mp4", "loop": False},
        ],
        "handedBack": [{"elId": 7, "loop": True, "isConnected": True, "facade": False, "paused": False, "t": 12.0}],
        "reads": {"postHandback": {"gl": _post_handback()}},
        "outputAtStop": {"continuity": {"mode": "qualified", "glReplay": {"mode": "injected"}}},
        "samples": [{"t": 2.0 * i, "state": "LIVE", "standDowns": [], "videoEnded": False, "uploads": 100 * (i + 1),
                     "carriedT": t} for i, t in enumerate(times)],
    }
    session.update(over)
    return session


def _precheck(session: dict[str, Any], fixture: Path) -> dict[str, Any]:
    return q.precheck_gates({"sessions": [session]}, fixture)["precheck"]


def _check(result: dict[str, Any], prefix: str) -> dict[str, Any]:
    return next(c for c in result["checks"] if c["check"].startswith(prefix))


class TestPrecheckA:
    def test_control_passes(self, looped: Path) -> None:
        result = _precheck(_session(), looped)
        assert result["verdict"] == "PASS", result["failing"]
        static = _check(result, "(a) loop representation")["value"]
        assert static["differing"] == static["spliced"] and len(static["spliced"]) == 8
        assert static["addedLoopKeys"] and all(k.endswith(':loopMode="looping"') for k in static["addedLoopKeys"])
        assert all(c["enforced"] for c in result["checks"] if c["check"].startswith("(a)"))

    def test_a_slide1_movie_that_does_not_loop_fails(self, looped: Path) -> None:
        videos = [{"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True}, {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": False}]
        result = _precheck(_session(slide1Videos=videos), looped)
        assert result["verdict"] == "FAIL"
        assert result["failing"] == ["(a) video.loop on every slide-1 untitled.mov"]

    def test_no_slide1_movie_read_fails(self, looped: Path) -> None:
        result = _precheck(_session(slide1Videos=[{"src": "WA0125.mp4", "loop": False}]), looped)
        assert result["failing"] == ["(a) video.loop on every slide-1 untitled.mov"]

    @pytest.mark.parametrize("handed", [
        None, [], {"elId": 7, "loop": True},
        [{"elId": None, "loop": True, "isConnected": True, "facade": False}],
        [{"elId": 7, "loop": False, "isConnected": True, "facade": False}],
    ], ids=["no-read", "no-element", "old-shape", "no-id", "loop-false"])
    def test_a_missing_or_non_looping_handed_back_element_fails(self, looped: Path, handed: Any) -> None:
        session = _session()
        if handed is None:
            del session["handedBack"]
        else:
            session["handedBack"] = handed
        result = _precheck(session, looped)
        assert result["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_a_facade_fails(self, looped: Path) -> None:
        """Codex r4 #5: a facade `<video>` stamped with the carried id is not the handed-back decoder."""
        session = _session(handedBack=[{"elId": 7, "loop": True, "isConnected": True, "facade": True}])
        assert _precheck(session, looped)["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_a_facade_beside_the_real_element_fails(self, looped: Path) -> None:
        real = {"elId": 7, "loop": True, "isConnected": True, "facade": False}
        session = _session(handedBack=[real, {**real, "facade": True}])
        assert _precheck(session, looped)["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_a_disconnected_element_fails(self, looped: Path) -> None:
        session = _session(handedBack=[{"elId": 7, "loop": True, "isConnected": False, "facade": False}])
        assert _precheck(session, looped)["failing"] == ["(a) video.loop on the handed-back carried element"]

    @pytest.mark.parametrize("post", [
        _post_handback(state="LIVE"), _post_handback(mode="retire"), _post_handback(el_id=8), _post_handback(handoffs=0),
        _post_handback(handoffs=2), None,
        _post_handback(module={"mode": "retire"}), _post_handback(module={"elId": 8}), _post_handback(module={"ok": False}),
        _post_handback(module={"elId": None}),
    ], ids=["g2-still-live", "retired-not-handed-off", "other-element-released", "no-module-handoff", "two-module-handoffs",
            "no-post-read", "module-mode-retire", "module-other-id", "module-not-ok", "module-no-id"])
    def test_without_a_matching_handoff_fails(self, looped: Path, post: Any) -> None:
        """Codex r4 #5: `.loop` on a DOM element proves nothing unless G2 retired by handing off that same element."""
        session = _session(reads={"postHandback": {"gl": post}})
        assert _precheck(session, looped)["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_an_extra_differing_json_fails(self, looped: Path) -> None:
        header = looped / "html-unmodified/assets/header.json"
        header.write_text(header.read_text() + " ")
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert "assets/header.json" in _check(result, "(a) loop representation")["value"]["differing"]

    def test_a_spliced_file_left_unspliced_fails(self, looped: Path) -> None:
        record = json.loads((looped / "loop-splice.json").read_text())
        rel = next(f["path"] for f in record["files"] if f["path"].startswith("html-unmodified/"))
        shutil.copy2(q.FIXTURE / rel, looped / rel)
        assert _precheck(_session(), looped)["failing"] == ["(a) loop representation"]

    @pytest.mark.parametrize("value", ['"loopBackAndForth"', '"none"', "true"])
    def test_a_loop_key_other_than_looping_fails(self, looped: Path, value: str) -> None:
        record = json.loads((looped / "loop-splice.json").read_text())
        rel = next(f["path"] for f in record["files"] if f["path"].startswith("html-unmodified/") and f["path"].endswith(".json"))
        path = looped / rel
        path.write_text(path.read_text().replace('"loopMode":"looping"', f'"loopMode":{value}', 1))
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert any(f"loopMode={value}" in k for k in _check(result, "(a) loop representation")["value"]["addedLoopKeys"])

    def test_a_module_handoff_without_its_released_object_fails(self, looped: Path) -> None:
        post = _post_handback()
        del post["api"]["events"][0]["detail"]["released"]
        session = _session(reads={"postHandback": {"gl": post}})
        assert _precheck(session, looped)["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_control_module_and_runtime_agree_with_the_element(self, looped: Path) -> None:
        value = _check(_precheck(_session(), looped), "(a) video.loop on the handed-back")["value"]["handback"]
        assert value == {"state": "RETIRED", "releases": [{"mode": "handoff", "elId": 7}],
                         "moduleReleased": [{"ok": True, "mode": "handoff", "elId": 7}]}

    def test_a_deleted_unspliced_base_jsonp_fails(self, looped: Path) -> None:
        """Codex r4 #4: a file missing from the fixture (not only an extra or changed one) is a difference."""
        rel = "assets/UNSPLICED/UNSPLICED.jsonp"
        for tree in (q.FIXTURE, looped):
            path = tree / "html-unmodified" / rel
            path.parent.mkdir(parents=True)
            path.write_text('local_slide( {"name":"UNSPLICED","json":{}} )')
        assert _precheck(_session(), looped)["verdict"] == "PASS", "control: the unspliced file identical on both sides"
        (looped / "html-unmodified" / rel).unlink()
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert rel in _check(result, "(a) loop representation")["value"]["differing"]

    def test_an_extra_fixture_json_fails(self, looped: Path) -> None:
        (looped / "html-unmodified/assets/extra.json").write_text("{}")
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert "assets/extra.json" in _check(result, "(a) loop representation")["value"]["differing"]

    def test_a_fixture_without_the_splice_record_fails(self, looped: Path) -> None:
        (looped / "loop-splice.json").unlink()
        assert _precheck(_session(), looped)["failing"] == ["(a) loop representation"]

    def test_the_p2_base_itself_fails_the_representation(self, looped: Path) -> None:
        """Known-bad: a non-looping export has no added loop keys and no splice record."""
        assert _precheck(_session(), q.FIXTURE)["failing"] == ["(a) loop representation"]


class TestTiming:
    def test_timing_summary_keys(self) -> None:
        run = {"arm": "soak", "take": 1, "timingS": {"launch": 4.2, "quit": 3.1, "total": 400.0},
               "sessions": [{"session": "soak", "timingS": {"script": 330.5, "decode": 20.25}},
                            {"session": "soak-off", "timingS": {"script": 20.0, "decode": 0.0}}]}
        summary = q.timing_summary(run)
        assert summary == {"arm": "soak", "take": 1, "launch": 4.2, "script": 350.5, "quit": 3.1, "decode": 20.25,
                           "total": 400.0, "sessions": {"soak": {"script": 330.5, "decode": 20.25},
                                                        "soak-off": {"script": 20.0, "decode": 0.0}}}

    def test_timing_summary_of_a_run_that_never_launched(self) -> None:
        summary = q.timing_summary({"arm": "g2", "take": 1, "timingS": {"quit": 0.5}, "sessions": []})
        assert summary["launch"] is None and summary["script"] == 0 and summary["decode"] == 0

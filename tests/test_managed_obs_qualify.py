"""Synthetic tests for `scripts/managed_obs_qualify.py` Magic Move opacity paths (plan keynote_live_mm_opacity §7, §8, §10); no OBS.

Covered: the OBED_LIVE_MM_OPACITY refusal, `EXPECTED_STATS` keyed by patch mode, M3's opaque reference moved to the
`mm-off` twin (and its KB still FAILing), the M3 g2-off T-alpha check (patch on, GL replay off), the MO-2 scorers (tau, R1-R4,
a CvC per rate, KB = patch-off twins), the MO-4 G2 facts in the MO-2 takes and their provenance, the MO-3 mapping onto
`mm_opacity_probe`'s scorer and its shared driver (the logger payload), and the session wiring (mm_opacity passed explicitly,
logger transport, alpha-squared splice, forced stand-down seed).
"""
from __future__ import annotations

import json
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

import live_continuity_probe as lcp  # noqa: E402
import managed_obs_qualify as q  # noqa: E402

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

def test_expected_stats_differ_only_in_occluded_bands_and_the_unproven_set():
    on, off = q.EXPECTED_STATS["on"], q.EXPECTED_STATS["off"]
    assert on["occludedBands"] == 0 and off["occludedBands"] == 20
    assert on["opacityUnproven"] == [{"slot": 4, "reason": "rest-opacity"}] and off["opacityUnproven"] == []
    assert {k: v for k, v in on.items() if k not in ("occludedBands", "opacityUnproven")} == \
        {k: v for k, v in off.items() if k not in ("occludedBands", "opacityUnproven")} == q.G2_STATS


@pytest.mark.parametrize("mode", ["on", "off"])
def test_g2_stats_checks_pass_their_own_mode_and_fail_the_other(mode):
    other = "off" if mode == "on" else "on"
    good: list[dict[str, Any]] = []
    q.g2_stats_checks(good, dict(q.EXPECTED_STATS[mode]), mode)
    assert all(c["ok"] for c in good)
    bad: list[dict[str, Any]] = []
    q.g2_stats_checks(bad, dict(q.EXPECTED_STATS[other]), mode)
    assert {c["check"] for c in bad if not c["ok"]} == {"occludedBands", "opacityUnproven"}


def test_g2_stats_checks_record_the_measured_value_and_state_the_expectation_source():
    # Review r1 F6: the patch-on occludedBands / unproven set come from headless Q0b; the check still enforces them in CEF,
    # records the CEF value it read, and says a mismatch is a finding, not a threshold to retune.
    checks: list[dict[str, Any]] = []
    q.g2_stats_checks(checks, {**q.EXPECTED_STATS["on"], "occludedBands": 3}, "on")
    by = {c["check"]: c for c in checks}
    assert by["occludedBands"]["value"] == 3 and not by["occludedBands"]["ok"] and by["occludedBands"]["enforced"]
    for key in ("occludedBands", "opacityUnproven"):
        assert "headless Q0b only" in by[key]["limit"] and "root-cause, not a threshold to retune" in by[key]["limit"]
    assert "CEF, OD-2" in by["frameLen"]["limit"]
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

def slot_shot(alpha: int) -> np.ndarray:
    img = np.zeros((*SHAPE, 4), np.uint8)
    img[q.rect_mask(SHAPE, ARMED["slotRects"][4])] = (0, 175, 0, alpha)
    return img


def m3_run(tmp_path: Path, mm_off_alpha: int, g2_off_alpha: int = 75) -> dict[str, Any]:
    sessions = []
    for name, alpha, mode in (("g2", 75, "on"), ("g2-off", g2_off_alpha, "on"), ("mm-off", mm_off_alpha, "off")):
        shots = {}
        for tag in ("S", "P3"):
            path = tmp_path / f"{name}-{tag}.png"
            Image.fromarray(slot_shot(alpha if tag == "S" else 75)).save(path)
            shots[tag] = str(path)
        sessions.append({"session": name, "shots": shots, "output": {"mmOpacity": {"mode": mode}}})
    return {"sessions": sessions, "rate": 25}


def test_m3_edge_and_kb_read_against_the_opaque_mm_off_twin(tmp_path):
    m3 = checks_of(q.g2_gates(m3_run(tmp_path, mm_off_alpha=255), ARMED)["M3"])
    assert m3["prerequisite: mm-off twin is patch off (opaque reference)"]["ok"]
    assert m3["T alpha (G2-S)"]["ok"]
    assert m3["edge: G2-S alpha == round(mm-off-S alpha x 0.2947)"]["ok"]
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
    """What the old g2-off reference reads once the patch is on: the edge squares and the KB passes the slot check."""
    m3 = checks_of(q.g2_gates(m3_run(tmp_path, mm_off_alpha=75), ARMED)["M3"])
    assert not m3["edge: G2-S alpha == round(mm-off-S alpha x 0.2947)"]["ok"]
    assert not m3["KB: mm-off-S T alpha fails the slot check"]["ok"]
    assert not m3["prerequisite: mm-off-S T alpha is opaque (the KB reference)"]["ok"]


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


def series(kind: str, poke: int | None = None, offset: float = 0.0) -> dict[str, np.ndarray]:
    """on: GL draws the square translucent (== DOM); off: GL opaque until build 1; off-live: opaque until G2 LIVE (slide2-live);
    square: alpha-squared GL; poke: one opaque frame at that row."""
    top = np.zeros((len(PHASES), K, 3))
    for row in range(len(PHASES)):
        value = DOM
        if row in GL_ROWS:
            if kind == "off" or (kind == "off-live" and row in MOVE_GL_ROWS):
                value = OPAQUE
            elif kind == "square":
                value = np.round(q.MM_ALPHA ** 2 * OPAQUE)
        top[row] = value + offset
    if poke is not None:
        top[poke] = OPAQUE
    return {"index": np.arange(len(PHASES)) + 100, "phase": np.array(PHASES), "pixels.top": np.clip(top, 0, 255).astype(np.uint8),
            "means.empty": np.zeros((len(PHASES), 3))}


def test_phase_median_and_reference_are_the_opaque_slide2_live_square():
    assert q.phase_median(series("off"), ("slide2-live",)).tolist() == [OPAQUE.tolist()] * K
    assert q.phase_median(series("on"), ("slide2-live",)).tolist() == [DOM.tolist()] * K
    assert q.phase_median(None, ("slide2-live",)) is None
    assert q.phase_median(series("on"), ("slide2-hidden",)) is None


def test_expected_top_blends_s_off_over_the_frames_empty_patch():
    ser = series("on")
    ser["means.empty"][3] = (10.0, 20.0, 30.0)
    e = q.expected_top(ser, np.tile(OPAQUE, (K, 1)))
    assert np.allclose(e[0], q.MM_ALPHA * OPAQUE)
    assert np.allclose(e[3], q.MM_ALPHA * OPAQUE + (1 - q.MM_ALPHA) * np.array([10.0, 20.0, 30.0]))


def all_series(**over: dict[str, np.ndarray]) -> dict[str, dict[str, np.ndarray]]:
    base = {"g2-on": series("on"), "g2-mmoff": series("off-live"), "g2off-on": series("on"), "g2off-mmoff": series("off")}
    return {**base, **over}


def test_tau_is_the_worst_slide1_component_plus_one():
    s_off = np.tile(OPAQUE, (K, 1))
    cal = q.mmo_tau(all_series(), s_off)
    assert cal["domOnOff"] == {"g2-on/g2-mmoff": 0.0, "g2off-on/g2off-mmoff": 0.0}
    instrument = round(float(np.abs(DOM - q.MM_ALPHA * OPAQUE).max()), 2)
    assert set(cal["instrument"].values()) == {instrument}
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
    assert on["frames"] == 24 and on["R1"] == 0 and on["R2"] <= tau and on["R3"] == 0
    for kind in ("off", "off-live"):
        off = q.mmo_series_checks(series(kind), s_off, tau)
        assert off["R1"] > 0 and off["R2"] > tau and off["R3"] > tau
    assert q.mmo_series_checks(series("off-live"), s_off, tau)["R1First"] == 111


def test_series_checks_catch_a_one_frame_opaque_pop_and_the_alpha_squared_player():
    s_off = np.tile(OPAQUE, (K, 1))
    tau = q.mmo_tau(all_series(), s_off)["tau"]
    pop = q.mmo_series_checks(series("on", poke=26), s_off, tau)
    assert pop["R1"] == 1 and pop["R2Frame"] == 126 and pop["R2"] > tau and pop["R3"] > tau
    assert pop["R3At"][1:] in (["slide2-handback", "slide2-handback"],)
    square = q.mmo_series_checks(series("square"), s_off, tau)
    assert square["R1"] == 0 and square["R2"] > tau and square["R3"] > tau


def test_series_checks_ignore_frames_outside_the_window():
    s_off = np.tile(OPAQUE, (K, 1))
    after_only = series("on", poke=34)
    assert q.mmo_series_checks(after_only, s_off, 2.0)["R1"] == 0


def test_series_checks_read_none_without_a_reference_or_tau():
    assert q.mmo_series_checks(series("on"), None, 2.0)["R1"] is None
    assert q.mmo_series_checks(series("on"), np.tile(OPAQUE, (K, 1)), None)["R2"] is None
    assert q.mmo_series_checks(None, np.tile(OPAQUE, (K, 1)), 2.0)["frames"] == 0


# --- MO-2 key (R4) and CvC -----------------------------------------------------------------------------------------------

def key_shot(alpha: int) -> np.ndarray:
    img = np.zeros((*SHAPE, 4), np.uint8)
    img[q.mmo_masks(ARMED, SHAPE)["top"]] = (0, 175, 0, alpha)
    return img


def key_shots(on_m: int = 75) -> dict[str, dict[str, np.ndarray]]:
    return {"g2-on": {"D": key_shot(75), "M": key_shot(on_m)}, "g2-mmoff": {"D": key_shot(75), "M": key_shot(255)},
            "g2off-on": {"D": key_shot(75), "M": key_shot(on_m)}, "g2off-mmoff": {"D": key_shot(75), "M": key_shot(255)}}


def test_key_r4_passes_translucent_settle_and_fails_the_opaque_twins():
    key = q.mmo_key(key_shots(), q.mmo_masks(ARMED, SHAPE))
    assert key["domOnOff"] == {"g2-on/g2-mmoff": 0.0, "g2off-on/g2off-mmoff": 0.0}
    assert key["tauKey"] == round(abs(75 - q.MM_ALPHA * 255) + 1, 2)
    assert key["R4"] == {"g2-on": 0.0, "g2-mmoff": 180.0, "g2off-on": 0.0, "g2off-mmoff": 180.0}


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
        opaque_m = kinds[name] != "on"
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
        for r in ("R1", "R2: max |ROI_top - E|", "R3: max frame-to-frame step", "R4: key alpha |M - D|"):
            assert checks[f"KB: {off} {r}"]["ok"]
    assert checks["CvC g2-on vs g2-on-2 before tau"]["value"]["max"] == 0.0
    assert gates["mmoCalibration"]["cvc"]["max"] == 0.0


def test_mmo_gates_fail_a_one_frame_opaque_pop_in_the_patched_session(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-on": series("on", poke=20)}), ARMED)
    failing = gates["MO-2"]["failing"]
    assert "g2-on R1: frames within tau of S_off" in failing
    assert "g2-on R2: max |ROI_top - E|" in failing and "g2-on R3: max frame-to-frame step" in failing
    assert "g2-on-2" not in " ".join(failing)


def test_mmo_gates_fail_when_the_patch_off_twin_reads_like_the_patch(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"series:g2-mmoff": series("on")}), ARMED)
    assert "KB: g2-mmoff R1" in gates["MO-2"]["failing"]
    assert "KB: g2-mmoff R2: max |ROI_top - E|" in gates["MO-2"]["failing"]


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


def test_mmo_mo4_reads_g2_facts_per_patch_mode(tmp_path):
    gates = q.mmo_gates(mmo_run(tmp_path, **{"stats:g2-on": dict(q.EXPECTED_STATS["off"])}), ARMED)
    assert set(gates["MO-4"]["failing"]) == {"g2-on: occludedBands", "g2-on: opacityUnproven"}


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
    assert len(rec["liveGreen"]) == 16 * 58 * 3


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

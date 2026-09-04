"""Pure-logic tests for the offline geometry-WRITE opt-in (``w-offline-write-optin``).

Style of ``tests/test_as_geometry.py``: everything here is pure Python (no Keynote, no
real IWA decode). Most functions live in ``obed_edom.offline_write``; a few `iwa_write`
calls it makes (``patch_deck_geometry``, ``bridge_specs_kindindex``,
``OfflineWriteCorrupted``) are imported LAZILY inside its functions, so they are
monkeypatched or stood in for here rather than exercised against a real deck.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from obed_edom.offline_write import (
    _fallback_bodies,
    _fallback_specs_by_slide,
    _offline_write_slides,
    _reported_from_bulk_rows,
    _soft_seed_slides,
    build_fallback_scripts,
    counts_from_payload,
    probe_iwa_extra,
    run_offline_write,
    verify_live_frames,
    verify_offline_frames,
)
from obed_edom.remap_keynote import offline_write_mode
from scripts.offline_write_ab import (
    Tolerances,
    accessibility_ok,
    compare_units_by_addr,
    compare_units_identity,
    compare_units_multiset,
    front_err_from_raw,
    keynote_open_documents,
    load_run_record,
    pass2_health,
    pass2_parity,
    plan_oracle_slide,
    plan_parity,
    run_record,
    tol_for_bucket,
    unit_bucket,
    write_run_record,
)


def _spec(**over):
    base = {
        "slide": 3,
        "kind": "text",
        "kindIndex": 0,
        "x": 100,
        "y": 200,
        "w": 300,
        "h": 120,
        "role": "other",
    }
    base.update(over)
    return base


def _result(**over):
    base = dict(refused=False, reason=None, applied=1, missed=0, missed_specs=[],
                soft_fallbacks=0, value_clean=True)
    base.update(over)
    return SimpleNamespace(**base)


# --- offline_write_mode ------------------------------------------------------


def test_offline_write_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
    assert offline_write_mode() == "off"


def test_offline_write_mode_parses_on_and_verify(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    assert offline_write_mode() == "on"
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "verify")
    assert offline_write_mode() == "verify"
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "ON")
    assert offline_write_mode() == "on"


def test_offline_write_mode_unknown_token_is_off(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "bogus")
    assert offline_write_mode() == "off"


def test_offline_write_mode_forced_off_without_as_geometry(monkeypatch):
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    monkeypatch.setenv("OBED_AS_GEOMETRY", "0")
    said = []
    assert offline_write_mode(say=said.append) == "off"
    assert said and "OBED_AS_GEOMETRY" in said[0]


# --- probe_iwa_extra (BLOCKER item 1) -----------------------------------------


def test_probe_iwa_extra_off_stays_off_and_never_probes(monkeypatch):
    # If it tried to import anything, poisoning a real module would blow this up;
    # asserting no say() fired is the simplest proof it short-circuited before probing.
    said = []
    assert probe_iwa_extra("off", said.append) == "off"
    assert said == []


def test_probe_iwa_extra_passes_through_when_importable():
    # obed_edom.iwa_write + keynote_parser are installed in this dev environment.
    assert probe_iwa_extra("on", None) == "on"
    assert probe_iwa_extra("verify", None) == "verify"


def test_probe_iwa_extra_forces_off_on_import_failure(monkeypatch):
    # sys.modules[name] = None is the standard way to make `import name` raise
    # ImportError without touching the real module for every other test.
    monkeypatch.setitem(sys.modules, "obed_edom.iwa_write", None)
    said = []
    assert probe_iwa_extra("on", said.append) == "off"
    assert said and "iwa" in said[0].lower()


# --- _offline_write_slides ---------------------------------------------------


def test_offline_slides_excludes_reuse_targets():
    specs = [
        _spec(slide=3, kind="text", kindIndex=0),
        _spec(slide=4, kind="image", kindIndex=0),
        _spec(slide=5, kind="shape", kindIndex=0),
    ]
    out = _offline_write_slides(specs, reuses=[], reuse_slides={4}, wanted=None)
    assert out == {3, 5}


def test_offline_slides_excludes_reuse_donors():
    specs = [
        _spec(slide=3, kind="text", kindIndex=0),
        _spec(slide=4, kind="image", kindIndex=0),
        _spec(slide=5, kind="shape", kindIndex=0),
    ]
    reuses = [{"slide": 5, "from": 3}]
    out = _offline_write_slides(specs, reuses=reuses, reuse_slides={5}, wanted=None)
    assert out == {4}  # slide 5 is the reuse target, slide 3 is the donor


def test_offline_slides_excludes_unaddressable_slides():
    specs = [
        _spec(slide=6, kind="text", kindIndex=0),
        _spec(slide=6, kind="table", kindIndex=0),  # no AS address -> whole slide excluded
        _spec(slide=7, kind="image", kindIndex=0),
    ]
    out = _offline_write_slides(specs, reuses=[], reuse_slides=set(), wanted=None)
    assert out == {7}


def test_offline_slides_intersects_slide_range():
    specs = [
        _spec(slide=3, kind="text", kindIndex=0),
        _spec(slide=4, kind="image", kindIndex=0),
        _spec(slide=5, kind="shape", kindIndex=0),
    ]
    out = _offline_write_slides(specs, reuses=[], reuse_slides=set(), wanted=[3, 4])
    assert out == {3, 4}


# --- _soft_seed_slides --------------------------------------------------------


def test_soft_seed_slides_only_group_and_text():
    specs_by_slide = {
        1: [_spec(slide=1, kind="group", kindIndex=0)],
        2: [_spec(slide=2, kind="text", kindIndex=0)],
        3: [_spec(slide=3, kind="shape", kindIndex=0)],
        4: [_spec(slide=4, kind="group", kindIndex=0, role="hide")],
        5: [_spec(slide=5, kind="image", kindIndex=0)],  # masked or not: never a soft seed
    }
    out = _soft_seed_slides({1, 2, 3, 4, 5}, specs_by_slide)
    assert out == {1, 2}


# --- _reported_from_bulk_rows -------------------------------------------------


def test_reported_from_bulk_rows_shifts_zero_based_slide_keys():
    bulk = {
        0: {"shape": [[1, 2, 3, 4], [5, 6, 7, 8]]},
        2: {"image": [[9, 9, 9, 9]]},
    }
    out = _reported_from_bulk_rows(bulk)
    assert set(out) == {1, 3}
    assert out[1][("shape", 0)] == [1, 2, 3, 4]
    assert out[1][("shape", 1)] == [5, 6, 7, 8]
    assert out[3][("image", 0)] == [9, 9, 9, 9]


# --- counts_from_payload -------------------------------------------------------


def test_counts_from_payload_matches_derived_kind_counts():
    wall = {
        "slides": [
            {
                "number": 1,
                "items": [
                    {"kind": "text", "kindIndex": 0},
                    {"kind": "text", "kindIndex": 1},
                    {"kind": "image", "kindIndex": 0},
                ],
            },
            {
                "number": 2,
                "items": [{"kind": "shape", "kindIndex": 0}],
            },
        ]
    }
    out = counts_from_payload(wall)
    assert out == {1: {"text": 2, "image": 1}, 2: {"shape": 1}}


# --- build_fallback_scripts ----------------------------------------------------


def test_fallback_script_one_session_bodies_in_order(tmp_path):
    dest = tmp_path / "MyDeck.key"
    dest.write_bytes(b"")
    scripts = build_fallback_scripts(dest, {3: "BODY_THREE", 1: "BODY_ONE"})
    assert len(scripts) == 1
    script = scripts[0]
    assert 'close (every document whose name is "MyDeck.key" or name is "MyDeck") saving no' in script
    assert 'if name of theDoc does not start with "MyDeck" then error' in script
    assert "save theDoc" in script
    assert "close theDoc saving yes" in script
    # slide 1's body comes before slide 3's (sorted by slide number).
    assert script.index("BODY_ONE") < script.index("BODY_THREE")
    assert script.index("tell theDoc") < script.index("BODY_ONE")
    assert script.index("BODY_THREE") < script.index("end tell")


def test_fallback_script_chunks_over_size_limit(tmp_path):
    dest = tmp_path / "MyDeck.key"
    dest.write_bytes(b"")
    bodies = {1: "A" * 100, 2: "B" * 100}
    scripts = build_fallback_scripts(dest, bodies, limit=150)
    assert len(scripts) == 2
    assert "A" * 100 in scripts[0]
    assert "B" * 100 in scripts[1]
    # a single body under the limit still gets one full session.
    one = build_fallback_scripts(dest, bodies, limit=10_000)
    assert len(one) == 1


# --- fallback spec assembly -----------------------------------------------------


def test_fallback_specs_are_bridged(monkeypatch):
    calls = []

    def fake_bridge(specs):
        calls.append(specs)
        return [dict(s, kindIndex=int(s["kindIndex"]) + 100) for s in specs]

    monkeypatch.setattr("obed_edom.iwa_write.bridge_specs_kindindex", fake_bridge, raising=False)
    fallback_by_slide = {3: [_spec(slide=3, kind="text", kindIndex=0)]}
    bodies = _fallback_bodies(fallback_by_slide)
    assert calls == [fallback_by_slide[3]]
    assert "text item 101" in bodies[3]  # bridged kindIndex 100 -> AS element 101


def test_fallback_includes_missed_specs_of_patched_slides():
    specs_by_slide = {
        1: [_spec(slide=1, kindIndex=0), _spec(slide=1, kindIndex=1)],
        2: [_spec(slide=2, kindIndex=0)],
    }
    missed = [_spec(slide=1, kindIndex=1)]
    results = {
        1: _result(missed_specs=missed),
        2: _result(refused=True, reason="reconcile mismatch"),
    }
    out = _fallback_specs_by_slide({1, 2}, specs_by_slide, results)
    assert out[1] == missed
    assert out[2] == specs_by_slide[2]


def test_fallback_specs_by_slide_drops_clean_patches():
    specs_by_slide = {1: [_spec(slide=1, kindIndex=0)]}
    results = {1: _result(missed_specs=[])}
    out = _fallback_specs_by_slide({1}, specs_by_slide, results)
    assert out == {}


# --- verify_offline_frames ------------------------------------------------------


def test_verify_offline_reports_max_delta_per_kind():
    planned = {
        1: [
            _spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=100, h=50),
            _spec(slide=1, kind="image", kindIndex=0, x=10, y=10, w=40, h=40),
        ]
    }
    composed = {
        1: [
            {"id": "s1", "kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 100.5, "h": 50,
             "geom_source": "iwa"},
            # masked image: excluded from the exact-class compare.
            {"id": "i1", "kind": "image", "kindIndex": 0, "x": 999, "y": 999, "w": 1, "h": 1,
             "geom_source": "mask"},
        ]
    }
    out = verify_offline_frames(planned, composed)
    assert set(out) == {"shape"}
    max_delta, n, worst5 = out["shape"]
    assert max_delta == 0.5
    assert n == 1
    assert worst5[0]["slide"] == 1


def test_verify_offline_frames_skips_hide_specs():
    planned = {1: [_spec(slide=1, kind="shape", kindIndex=0, role="hide")]}
    composed = {1: [{"id": "s1", "kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 1, "h": 1,
                      "geom_source": "iwa"}]}
    assert verify_offline_frames(planned, composed) == {}


def test_verify_offline_frames_bridges_before_lookup(monkeypatch):
    # `composed_by_slide` is keyed by SAVED kindIndex; the spec below carries the WALL
    # kindIndex (0) and must be bridged to 5 (a same-kind hide sitting above it) before
    # it can find its match.
    def fake_bridge(specs):
        return [dict(s, kindIndex=int(s["kindIndex"]) + 5) for s in specs]

    monkeypatch.setattr("obed_edom.iwa_write.bridge_specs_kindindex", fake_bridge, raising=False)
    planned = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    composed = {1: [{"id": "s1", "kind": "shape", "kindIndex": 5, "x": 0, "y": 0, "w": 10.3,
                      "h": 10, "geom_source": "iwa"}]}
    out = verify_offline_frames(planned, composed)
    assert set(out) == {"shape"}
    assert out["shape"][1] == 1  # found via the bridged kindIndex 5, not the raw 0


# --- verify_live_frames (BLOCKER items 3 and 6) ----------------------------------


def test_verify_live_frames_bridges_before_lookup(monkeypatch):
    def fake_bridge(specs):
        return [dict(s, kindIndex=int(s["kindIndex"]) + 5) for s in specs]

    monkeypatch.setattr("obed_edom.iwa_write.bridge_specs_kindindex", fake_bridge, raising=False)
    planned = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "shape", "kindIndex": 5, "x": 1, "y": 0, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames(planned, payload)
    assert set(out) == {"shape"}
    assert out["shape"][0] == 1.0


def test_verify_live_frames_excludes_whole_slide_when_stat_finalized():
    # Bring to Front reorders EVERY kind's per-kind collection on a stat-finalize slide,
    # not just the group's — so the whole slide is excluded, despite the param's name.
    planned = {
        1: [
            _spec(slide=1, kind="text", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10),
        ]
    }
    payload = {
        "slides": [
            {
                "number": 1,
                "items": [
                    {"kind": "text", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
                    {"kind": "group", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
                    {"kind": "shape", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
                ],
            }
        ]
    }
    out = verify_live_frames(planned, payload, exclude_slides=frozenset({1}))
    assert out == {}


def test_verify_live_frames_includes_text_on_non_stat_slides():
    # Text was "verified nowhere" — now a real (loose) bar: y is a centre delta, x too.
    planned = {1: [_spec(slide=1, kind="text", kindIndex=0, x=0, y=100, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "text", "kindIndex": 0, "x": 2, "y": 103, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames(planned, payload)
    assert set(out) == {"text"}
    max_delta, n, _worst5 = out["text"]
    assert max_delta == 3.0  # max(|0-2|, |100-103|)
    assert n == 1


# --- run_offline_write (BLOCKER items 2 and 5) -----------------------------------


def test_run_offline_write_omits_fallback_ok_key(monkeypatch):
    # R3: fallbackOk was structurally always True by the time the dict is returned (a
    # False fallback raises before the return) -- dropped rather than kept as dead weight.
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info is not None
    assert info["mode"] == "on"
    assert "fallbackOk" not in info


def test_run_offline_write_omits_offline_verify_pass_in_on_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert "offlineVerifyPass" not in info  # "on" never runs the offline verify pass


def test_run_offline_write_sets_offline_verify_pass_in_verify_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"shape": (0.1, 1, [])})
    info = run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["offlineVerifyPass"] is True  # 0.1px <= OFFLINE_VERIFY_TOL (0.5px)

    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"shape": (5.0, 1, [])})
    info_bad = run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info_bad["offlineVerifyPass"] is False  # 5.0px > 0.5px


def test_run_offline_write_raises_when_fallback_fails(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(refused=True, reason="x", applied=0, value_clean=False)},
    )
    monkeypatch.setattr(ow_mod, "_fallback_bodies", lambda fb: {1: "BODY"})
    monkeypatch.setattr(ow_mod, "build_fallback_scripts", lambda dest, bodies: ["SCRIPT"])
    monkeypatch.setattr(
        ow_mod, "_run_fallback_scripts",
        lambda dest, scripts, say: (False, [Path("/tmp/x.offline-fallback.applescript")]),
    )
    with pytest.raises(RuntimeError, match="offline-write fallback failed"):
        run_offline_write(
            Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
        )


def test_run_offline_write_skips_offline_decode_in_on_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    composed_calls = []
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: composed_calls.append(1) or {})
    run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert composed_calls == []  # "on" never pays for the diagnostic re-decode


def test_run_offline_write_runs_offline_decode_in_verify_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    composed_calls = []
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: composed_calls.append(1) or {})
    run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert composed_calls == [1]


def test_run_offline_write_returns_none_when_no_offline_slides():
    assert run_offline_write(Path("/tmp/x.key"), "on", set(), [], {}, [], lambda m: None) is None


# --- OfflineWriteCorrupted (BLOCKER item 4) ---------------------------------------


def test_patch_offline_slides_never_falls_back_on_corruption(monkeypatch):
    import obed_edom.iwa_write as iwa_write_mod
    import obed_edom.offline_write as ow_mod

    class _StandInCorrupted(Exception):
        pass

    # Stand-in exception object, not a real corrupted deck: proves the specific-except
    # ordering (OfflineWriteCorrupted before the generic Exception fallback path).
    monkeypatch.setattr(iwa_write_mod, "OfflineWriteCorrupted", _StandInCorrupted, raising=False)

    def fake_patch_deck_geometry(*a, **k):
        raise _StandInCorrupted("boom: deck truncated")

    monkeypatch.setattr(iwa_write_mod, "patch_deck_geometry", fake_patch_deck_geometry)

    said = []
    with pytest.raises(_StandInCorrupted):
        ow_mod._patch_offline_slides(
            Path("/tmp/CorruptMe.key"), {1},
            {1: [_spec(slide=1, kind="shape", kindIndex=0)]},  # not group/text: skips the soft-seed bulk_geometry call
            {}, said.append,
        )
    assert any("CORRUPTED" in m and "obedwrite.tmp" in m for m in said)
    assert any("NOT falling back" in m for m in said)


def test_patch_offline_slides_still_falls_back_on_ordinary_exception(monkeypatch):
    import obed_edom.iwa_write as iwa_write_mod
    import obed_edom.offline_write as ow_mod

    def fake_patch_deck_geometry(*a, **k):
        raise ValueError("something ordinary")

    monkeypatch.setattr(iwa_write_mod, "patch_deck_geometry", fake_patch_deck_geometry)

    said = []
    out = ow_mod._patch_offline_slides(
        Path("/tmp/x.key"), {1},
        {1: [_spec(slide=1, kind="shape", kindIndex=0)]},  # not group/text: skips the soft-seed bulk_geometry call
        {}, said.append,
    )
    assert out == {}  # ordinary failures still degrade to "fall back everything"
    assert any("falling back" in m for m in said)


# --- compare_units_multiset (scripts/offline_write_ab.py) ------------------------


def _unit(kind, x, y, w, h, addr=("top", "kind", 0)):
    return {"id": f"{kind}-{x}-{y}", "kind": kind, "addr": addr,
            "sig": {"type": "frame", "frame": (x, y, w, h), "flips": (False, False)}}


def test_compare_units_multiset_pass_and_fail():
    a = [_unit("shape", 0, 0, 100, 50), _unit("image", 10, 10, 20, 20)]
    b = [_unit("shape", 0.2, 0, 100, 50), _unit("image", 10, 10, 20, 20)]
    report = compare_units_multiset(a, b, tol_hard=0.5, tol_soft=1.0)
    assert report["pass"] is True
    assert report["per_kind"]["shape"]["worst"] == 0.2

    b_bad = [_unit("shape", 5, 0, 100, 50), _unit("image", 10, 10, 20, 20)]
    report_bad = compare_units_multiset(a, b_bad, tol_hard=0.5, tol_soft=1.0)
    assert report_bad["pass"] is False
    assert report_bad["per_kind"]["shape"]["pass"] is False

    # a count mismatch fails outright, regardless of tolerance.
    b_short = [_unit("shape", 0, 0, 100, 50)]
    report_count = compare_units_multiset(a, b_short, tol_hard=0.5, tol_soft=1.0)
    assert report_count["pass"] is False
    assert "count" in report_count["per_kind"]["image"]["reasons"][0]


def test_compare_units_multiset_text_is_informational():
    a = [_unit("text", 0, 0, 10, 10)]
    b = [_unit("text", 50, 0, 10, 10)]  # far off in x
    report = compare_units_multiset(a, b, tol_hard=0.5, tol_soft=1.0)
    assert report["pass"] is True  # text never gates
    assert report["per_kind"]["text"]["informational"] is True
    assert report["per_kind"]["text"]["worst"] == 50.0


# --- compare_units_by_addr — demoted to a permutation DIAGNOSTIC only (D2) -------


def test_compare_units_by_addr_flags_permutation_but_never_gates():
    a = [
        _unit("shape", 0, 0, 10, 10, addr=("top", "shape", 0)),
        _unit("shape", 100, 100, 10, 10, addr=("top", "shape", 1)),
    ]
    # B swaps the two shapes' addresses: same population/sorted order (multiset PASSes),
    # but each address now maps to a DIFFERENT box.
    b = [
        {**_unit("shape", 100, 100, 10, 10), "addr": ("top", "shape", 0)},
        {**_unit("shape", 0, 0, 10, 10), "addr": ("top", "shape", 1)},
    ]
    multiset = compare_units_multiset(a, b)
    assert multiset["pass"] is True  # fooled: identical population and sorted order

    addr_report = compare_units_by_addr(a, b)
    assert addr_report["pass"] is True  # D2: informational everywhere, never gates
    assert addr_report["per_kind"]["shape"]["pass"] is False  # still visible as a diagnostic


def test_compare_units_by_addr_group_is_informational():
    a = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (0, 0, 10, 10), "flips": (False, False)}}]
    b = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (50, 50, 10, 10), "flips": (False, False)}}]
    report = compare_units_by_addr(a, b)
    assert report["pass"] is True  # group never gates this pass
    assert report["per_kind"]["group"]["informational"] is True
    assert report["per_kind"]["group"]["worst"] == 50.0


def test_compare_units_by_addr_never_gates_shape_line_image_movie():
    for kind in ("shape", "line", "image", "movie"):
        a = [_unit(kind, 0, 0, 10, 10, addr=("top", kind, 0))]
        b = [_unit(kind, 5, 0, 10, 10, addr=("top", kind, 0))]
        report = compare_units_by_addr(a, b, tol_hard=0.5, tol_soft=0.5)
        assert report["per_kind"][kind]["pass"] is False, kind  # still flagged...
        assert report["pass"] is True, kind  # ...but D2: never gates the overall result


def test_log_multiset_report_flags_text_informational(capsys):
    from scripts.offline_write_ab import _log_multiset_report

    report = {
        "per_kind": {
            "text": {"n_a": 1, "n_b": 1, "pass": True, "worst": 5.0, "reasons": [],
                      "informational": True},
        }
    }
    _log_multiset_report(report)
    out = capsys.readouterr().out
    assert "text: informational only — UNVERIFIED by this gate" in out


# --- flag off: byte-for-byte parity with the pre-W1 plan (BLOCKER item 8) --------


def test_flag_off_builds_the_same_plan_as_today_pure(monkeypatch):
    """Pure-function lock (kept alongside the full remap_keynote() lock below): the exact
    computation the plan-building hook performs when the flag is off.

    SAFETY: OBED_OFFLINE_WRITE is set EXPLICITLY (not delenv'd) -- this repo's ambient
    default is a piece-2-pending flip away from "off" (D14, uncommitted), and relying on
    delenv here would make this test's `remap_keynote()` sibling below silently take the
    REAL offline-write path (and its fallback launches REAL Keynote) whenever it runs
    against a flipped tree. Explicit off is correct under either default.
    """
    from obed_edom.map_remap import ItemTransform
    from obed_edom.remap_keynote import _build_as_geometry, suppress_geometry_slides

    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)

    transforms = [
        ItemTransform(slide_number=3, item_index=0, kind="text", x=1, y=2, w=3, h=4, kind_index=0),
        ItemTransform(slide_number=5, item_index=0, kind="image", x=5, y=6, w=7, h=8, kind_index=0),
    ]
    transform_dicts = [t.as_dict() for t in transforms]

    mode = offline_write_mode()
    assert mode == "off"

    env_suppressed = suppress_geometry_slides()
    offline_slides = set() if mode == "off" else _offline_write_slides(transform_dicts, [], set(), None)
    suppressed = env_suppressed | offline_slides

    today_suppressed = suppress_geometry_slides()
    assert suppressed == today_suppressed
    assert offline_slides == set()
    assert _build_as_geometry(transform_dicts, suppress=suppressed) == _build_as_geometry(
        transform_dicts, suppress=today_suppressed
    )


def test_flag_off_builds_the_same_plan_as_today(monkeypatch, tmp_path):
    """End-to-end lock through a REAL `remap_keynote()` call (env unset): captures the
    actual `plan` dict handed to `_run_jxa` and asserts its suppressGeometry/asGeom match
    what `_build_as_geometry(transform_dicts, suppress=suppress_geometry_slides())` alone
    would give — i.e. the off path is byte-for-byte the pre-W1 plan. A spy on
    `offline_write._offline_write_slides` proves the off path never even computes
    `offline_slides`.

    SAFETY: OBED_OFFLINE_WRITE is set EXPLICITLY (not delenv'd) -- see the `_pure`
    sibling above. Under this repo's currently-flipped ambient default, delenv here
    made this REAL `remap_keynote()` call take the live offline-write path, whose
    AppleScript fallback launches REAL Keynote against a fake (touch()-only) dest --
    confirmed live during verification (killed twice). Explicit off is correct under
    either default and removes the hazard entirely.
    """
    import obed_edom.offline_write as ow_mod
    import obed_edom.remap_keynote as rk
    from obed_edom.map_remap import ItemTransform

    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)

    transforms = [
        ItemTransform(slide_number=3, item_index=0, kind="text", x=1, y=2, w=3, h=4, kind_index=0),
        ItemTransform(slide_number=5, item_index=0, kind="image", x=5, y=6, w=7, h=8, kind_index=0),
    ]

    # Seams used elsewhere (tests/test_export_fold.py: monkeypatch rk.<name>;
    # tests/test_as_geometry.py: exercise the real plan-building pieces directly).
    monkeypatch.setattr(rk, "plan_payload_transforms", lambda *a, **k: transforms)
    monkeypatch.setattr(rk, "plan_slide_reuses", lambda *a, **k: [])
    monkeypatch.setattr(
        rk, "recipe_for",
        lambda wall, template: {
            "source": "test", "mapSrc": "src", "mapDst": "dst",
            "destWidth": 1920, "destHeight": 1080, "characterStyles": [],
        },
    )
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 0, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)

    captured_plan: dict = {}

    def fake_run_jxa(plan):
        captured_plan.update(plan)
        return {"applied": 1, "missed": 0}

    monkeypatch.setattr(rk, "_run_jxa", fake_run_jxa)

    spy_calls = []
    real_offline_write_slides = ow_mod._offline_write_slides

    def spy(*a, **k):
        spy_calls.append((a, k))
        return real_offline_write_slides(*a, **k)

    monkeypatch.setattr(ow_mod, "_offline_write_slides", spy)

    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()

    wall_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        log=lambda m: None,
    )

    assert spy_calls == []  # the off path must never compute offline_slides

    transform_dicts = [t.as_dict() for t in transforms]
    expected_suppressed = rk.suppress_geometry_slides()  # env unset -> empty set
    assert captured_plan["suppressGeometry"] == sorted(expected_suppressed)
    assert captured_plan.get("asGeom") == rk._build_as_geometry(
        transform_dicts, suppress=expected_suppressed
    )


# --- R2: gate keys land + the gate logic that reads them -------------------------


def test_remap_and_inspect_sets_live_verify_pass_key(monkeypatch, tmp_path):
    """`offlineVerifyPass` is set by `run_offline_write` (locked above); `liveVerifyPass`
    is set separately by `remap_and_inspect` once the validated read-back is in hand --
    this locks that it actually lands on `info["offlineWrite"]`."""
    import obed_edom.remap_keynote as rk

    offline_info = {
        "mode": "verify",
        "specs": {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]},
        "statSlides": [],
    }

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        return {"dest": str(dest), "applied": 1, "offlineWrite": offline_info}

    def fake_inspect(dest, *, export_dir=None, slide_range=None, use_cache=None, **kwargs):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 1,
            "slides": [{"number": 1, "items": [
                {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
            ]}],
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    assert "liveVerifyPass" in info["offlineWrite"]
    assert info["offlineWrite"]["liveVerifyPass"] is True  # exact match on the one shape


def test_summary_gate_reasons_green_on_clean_run():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": True, "liveVerifyPass": True}
    assert summary_gate_reasons(ow, applied_a=5, applied_b=5) == []


def test_summary_gate_reasons_flags_offline_verify_fail():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": False, "liveVerifyPass": True}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("offline-write verify" in r for r in reasons)


def test_summary_gate_reasons_flags_live_verify_fail():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": True, "liveVerifyPass": False}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("live verify" in r for r in reasons)


def test_summary_gate_reasons_missing_verify_keys_do_not_spuriously_fail():
    # A run whose mode wasn't "verify" carries neither key -- absence must not read as FAIL.
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True}
    assert summary_gate_reasons(ow, applied_a=5, applied_b=5) == []


# --- accessibility_ok (D5 pre-flight) ---------------------------------------------


def test_accessibility_ok_true(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="true\n", stderr=""),
    )
    ok, detail = accessibility_ok()
    assert ok is True
    assert detail == "true"


def test_accessibility_ok_false_on_false_output(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="false\n", stderr=""),
    )
    ok, _detail = accessibility_ok()
    assert ok is False


def test_accessibility_ok_false_on_osascript_failure(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="not authorized"),
    )
    ok, detail = accessibility_ok()
    assert ok is False
    assert "not authorized" in detail


# --- keynote_open_documents / stray-document guard (Full-deck-gate memory blowup) --


def test_keynote_open_documents_not_running_returns_empty(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="\n", stderr=""),
    )
    assert keynote_open_documents() == []


def test_keynote_open_documents_parses_comma_list(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="A_unflagged.key, B_flagged.key\n", stderr=""
        ),
    )
    assert keynote_open_documents() == ["A_unflagged.key", "B_flagged.key"]


def test_keynote_open_documents_single_name_no_comma(monkeypatch):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="A_unflagged.key\n", stderr=""),
    )
    assert keynote_open_documents() == ["A_unflagged.key"]


def test_main_aborts_when_keynote_already_has_documents_open(monkeypatch, tmp_path, capsys):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(owab, "accessibility_ok", lambda: (True, "true"))
    monkeypatch.setattr(owab, "keynote_open_documents", lambda: ["Stray.key"])

    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    source.touch()
    template.touch()

    rc = owab.main([
        "--source", str(source), "--template", str(template),
        "--out", str(tmp_path / "out"),
    ])
    assert rc == 5
    out = capsys.readouterr().out
    assert "ABORT" in out and "Stray.key" in out


def test_warn_and_close_stray_documents_only_closes_own_deck(monkeypatch, tmp_path):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(
        owab, "keynote_open_documents", lambda: ["A_unflagged.key", "SomeOtherDeck.key"]
    )
    closed = []
    monkeypatch.setattr(owab, "_close_keynote_document", lambda name: closed.append(name))

    deck = tmp_path / "A_unflagged.key"
    owab._warn_and_close_stray_documents("A", deck)

    assert closed == ["A_unflagged.key"]  # NOT "SomeOtherDeck.key"


def test_warn_and_close_stray_documents_noop_when_nothing_open(monkeypatch, tmp_path):
    from scripts import offline_write_ab as owab

    monkeypatch.setattr(owab, "keynote_open_documents", lambda: [])
    closed = []
    monkeypatch.setattr(owab, "_close_keynote_document", lambda name: closed.append(name))

    owab._warn_and_close_stray_documents("A", tmp_path / "A_unflagged.key")
    assert closed == []


def test_close_keynote_document_command_targets_named_document(monkeypatch):
    from scripts import offline_write_ab as owab

    calls = []
    monkeypatch.setattr(
        owab.subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    owab._close_keynote_document("A_unflagged.key")
    assert len(calls) == 1
    script = calls[0][2]  # ["osascript", "-e", "<script>"]
    assert 'close (every document whose name is "A_unflagged.key") saving no' in script


def _is_count_script(cmd):
    return cmd[0] == "osascript" and "bundle identifier" in cmd[2] and "count" in cmd[2]


def _is_quit_script(cmd):
    return cmd[0] == "osascript" and "quit saving no" in cmd[2]


def test_quit_keynote_and_wait_sends_quit_saving_no_and_polls_by_bundle_id(monkeypatch):
    # Never by process name -- this machine's Keynote installs under a different .app
    # name ("Keynote Creator Studio.app"), so a bare "Keynote" process-name match would
    # be wrong; resolve via bundle id (System Events process count) instead.
    from scripts import offline_write_ab as owab

    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if _is_count_script(cmd):
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")  # gone immediately
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(owab.subprocess, "run", fake_run)
    monkeypatch.setattr(owab.time, "sleep", lambda s: None)

    ok, _elapsed = owab.quit_keynote_and_wait()
    assert ok is True
    quit_calls = [c for c in calls if _is_quit_script(c)]
    assert len(quit_calls) == 1
    assert "pgrep" not in " ".join(str(c) for c in calls)
    assert not any(c[0] == "pgrep" for c in calls)
    count_calls = [c for c in calls if _is_count_script(c)]
    assert count_calls and "bundle identifier" in count_calls[0][2]


def test_quit_keynote_and_wait_polls_until_count_reports_zero(monkeypatch):
    from scripts import offline_write_ab as owab

    poll_calls = {"n": 0}

    def fake_run(cmd, **k):
        if _is_count_script(cmd):
            poll_calls["n"] += 1
            # 2 processes on the first two polls, 0 on the third.
            out = "2\n" if poll_calls["n"] < 3 else "0\n"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    slept = []
    monkeypatch.setattr(owab.subprocess, "run", fake_run)
    monkeypatch.setattr(owab.time, "sleep", lambda s: slept.append(s))

    ok, _elapsed = owab.quit_keynote_and_wait(timeout=90.0)
    assert ok is True
    assert poll_calls["n"] == 3
    assert len(slept) == 2  # slept between poll 1->2 and 2->3, not after the final zero


def test_quit_keynote_and_wait_warns_not_raises_when_still_running_at_timeout(monkeypatch):
    from scripts import offline_write_ab as owab

    def fake_run(cmd, **k):
        if _is_count_script(cmd):
            return SimpleNamespace(returncode=0, stdout="1\n", stderr="")  # always "running"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    # Fake a clock so the 90s timeout elapses without a real sleep.
    fake_now = [0.0]
    monkeypatch.setattr(owab.subprocess, "run", fake_run)
    monkeypatch.setattr(owab.time, "sleep", lambda s: fake_now.__setitem__(0, fake_now[0] + s))
    monkeypatch.setattr(owab.time, "monotonic", lambda: fake_now[0])

    ok, elapsed = owab.quit_keynote_and_wait(timeout=5.0)
    assert ok is False
    assert elapsed >= 5.0


def test_quit_keynote_and_wait_nonzero_returncode_never_counts_as_gone(monkeypatch):
    # A nonzero osascript rc (or empty/garbled stdout) is NOT proof Keynote quit --
    # even if stdout happened to be empty or "0"-looking, a failed call must keep polling.
    from scripts import offline_write_ab as owab

    def fake_run(cmd, **k):
        if _is_count_script(cmd):
            return SimpleNamespace(returncode=1, stdout="", stderr="System Events got an error")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    fake_now = [0.0]
    monkeypatch.setattr(owab.subprocess, "run", fake_run)
    monkeypatch.setattr(owab.time, "sleep", lambda s: fake_now.__setitem__(0, fake_now[0] + s))
    monkeypatch.setattr(owab.time, "monotonic", lambda: fake_now[0])

    ok, elapsed = owab.quit_keynote_and_wait(timeout=5.0)
    assert ok is False
    assert elapsed >= 5.0


# --- front_err_from_raw (D4) -------------------------------------------------------


def test_front_err_from_raw_extracts_field():
    raw = ("done=1 skipped=0 sized=0 sizeSkips=0 front=2 dedupDeleted=0 dedupShortfall=0 "
           "frontErr= [-1743] exported=true sigFallback=0 unresolved=0 badgeFallback=0 "
           "badgeUnresolved=0 detail=")
    assert front_err_from_raw(raw) == "[-1743]"


def test_front_err_from_raw_empty_when_clean():
    raw = "done=1 skipped=0 front=2 dedupDeleted=0 dedupShortfall=0 frontErr= exported=true"
    assert front_err_from_raw(raw) == ""


def test_front_err_from_raw_no_match_returns_empty():
    assert front_err_from_raw("garbage, no fields here") == ""


# --- pass2_health (D4) --------------------------------------------------------------


def _pass2(**over):
    base = dict(ok=True, jobs=2, done=2, skipped=0, sized=2, sizeSkips=0, front=1,
                dedupDeleted=0, dedupShortfall=0, sigFallback=0, unresolved=0,
                badgeFallback=0, badgeUnresolved=0, raw="")
    base.update(over)
    return base


def test_pass2_health_green():
    assert pass2_health(_pass2(), label="A", expect_raises=True) == []


def test_pass2_health_none_result_is_healthy():
    # `childResize is None` (no stat/badge jobs planned) is healthy (D4).
    assert pass2_health(None, label="A", expect_raises=True) == []


def test_pass2_health_noop_skipped_bool_form_is_healthy():
    # `_run_stat_finalize`'s no-op return: `skipped` is a BOOL sentinel here, not the
    # per-job skip COUNT the rest of this function reads as an int -- must short-circuit
    # before the count checks would otherwise misread `True` as `1`.
    noop = {"ok": True, "skipped": True, "done": 0, "jobs": 0, "exported": False}
    assert pass2_health(noop, label="A", expect_raises=True) == []


def test_pass2_health_not_ok():
    reasons = pass2_health(_pass2(ok=False), label="A", expect_raises=False)
    assert any("ok=False" in r for r in reasons)


def test_pass2_health_zero_keys():
    reasons = pass2_health(
        _pass2(unresolved=1, dedupShortfall=2, badgeUnresolved=3), label="A", expect_raises=False
    )
    assert len(reasons) == 3


def test_pass2_health_front_when_raises():
    reasons = pass2_health(_pass2(front=0), label="A", expect_raises=True)
    assert any("front=0" in r for r in reasons)
    # front is NOT required when the plan carried no stat jobs / badge raises.
    assert pass2_health(_pass2(front=0), label="A", expect_raises=False) == []


def test_pass2_health_frontErr_flags_accessibility_denied():
    raw = "done=1 skipped=0 front=0 dedupDeleted=0 dedupShortfall=0 frontErr= [-1743] exported=true"
    reasons = pass2_health(_pass2(raw=raw, front=0), label="A", expect_raises=False)
    assert any("Accessibility denied" in r for r in reasons)


def test_pass2_health_fallback_keys_are_warn_only():
    # sigFallback/badgeFallback non-zero must NOT gate (D4: WARN only).
    reasons = pass2_health(_pass2(sigFallback=3, badgeFallback=2), label="A", expect_raises=False)
    assert reasons == []


def test_pass2_health_done_plus_skipped_must_equal_jobs():
    reasons = pass2_health(_pass2(jobs=5, done=2, skipped=2), label="A", expect_raises=False)
    assert any("!= jobs" in r for r in reasons)


# --- pass2_health: --pass2-bar strict (default) vs parity --------------------------


def test_pass2_health_strict_flags_zero_keys():
    # zero_keys_hard defaults True -- unchanged behavior, matches --pass2-bar strict.
    reasons = pass2_health(
        _pass2(unresolved=1, dedupShortfall=2, badgeUnresolved=3), label="A",
        expect_raises=False, zero_keys_hard=True,
    )
    assert len(reasons) == 3


def test_pass2_health_parity_does_not_flag_zero_keys():
    reasons = pass2_health(
        _pass2(unresolved=134, dedupShortfall=6, badgeUnresolved=3), label="A",
        expect_raises=False, zero_keys_hard=False,
    )
    assert reasons == []


def test_pass2_health_parity_still_flags_ok_front_done_skipped():
    assert any("ok=False" in r for r in
               pass2_health(_pass2(ok=False), label="A", expect_raises=False, zero_keys_hard=False))
    assert any("front=0" in r for r in
               pass2_health(_pass2(front=0), label="A", expect_raises=True, zero_keys_hard=False))
    assert any("!= jobs" in r for r in
               pass2_health(_pass2(jobs=5, done=2, skipped=2), label="A", expect_raises=False,
                            zero_keys_hard=False))


def test_pass2_health_strict_flags_any_frontErr_even_without_accessibility_code():
    # -1719 is "invalid index" (a stray GUI raise miss), not an Accessibility code --
    # strict still gates on it (unchanged from before --pass2-bar existed).
    raw = "done=1 skipped=0 front=674 dedupDeleted=0 dedupShortfall=0 frontErr= [-1719] exported=true"
    reasons = pass2_health(_pass2(raw=raw), label="A", expect_raises=False, zero_keys_hard=True)
    assert any("frontErr" in r for r in reasons)
    assert not any("Accessibility denied" in r for r in reasons)


def test_pass2_health_parity_frontErr_without_accessibility_code_is_not_hard():
    raw = "done=1 skipped=0 front=674 dedupDeleted=0 dedupShortfall=0 frontErr= [-1719] exported=true"
    reasons = pass2_health(_pass2(raw=raw), label="A", expect_raises=False, zero_keys_hard=False)
    assert reasons == []


def test_pass2_health_parity_frontErr_with_accessibility_code_stays_hard():
    raw = "done=1 skipped=0 front=0 dedupDeleted=0 dedupShortfall=0 frontErr= [-1743] exported=true"
    reasons = pass2_health(_pass2(raw=raw, front=0), label="A", expect_raises=False, zero_keys_hard=False)
    assert any("Accessibility denied" in r for r in reasons)


# --- pass2_parity (D4) --------------------------------------------------------------


def test_pass2_parity_green():
    assert pass2_parity(_pass2(), _pass2()) == []


def test_pass2_parity_flags_each_key():
    for key in ("jobs", "done", "skipped", "sized", "sizeSkips", "front", "dedupDeleted",
                "dedupShortfall", "sigFallback", "unresolved", "badgeFallback", "badgeUnresolved"):
        b = _pass2(**{key: 99})
        reasons = pass2_parity(_pass2(), b)
        assert any(key in r for r in reasons), key


def test_pass2_parity_ignores_raw():
    a = _pass2(raw="AAA some detail")
    b = _pass2(raw="BBB totally different detail")
    assert pass2_parity(a, b) == []


def test_pass2_parity_handles_none():
    assert pass2_parity(None, None) == []


def test_pass2_parity_front_hard_by_default():
    reasons = pass2_parity(_pass2(), _pass2(front=99))
    assert any("front" in r for r in reasons)


def test_pass2_parity_excludes_front_when_not_hard():
    # front differs but is excluded under --pass2-bar parity (GUI raises are flaky);
    # a genuinely differing OTHER key must still be caught.
    reasons = pass2_parity(_pass2(), _pass2(front=99, unresolved=5), front_hard=False)
    assert not any("front" in r for r in reasons)
    assert any("unresolved" in r for r in reasons)


# --- plan_parity (D5) ----------------------------------------------------------------


def _plan(**over):
    # A's suppressGeometry is always empty and B's always equals the compared-slide set
    # in these `transforms`/`reuses` tests — suppressGeometry drift is tested separately
    # below, since (by construction, D1/D5) it can never be an EQUALITY check between A/B.
    base = {"transforms": [{"slide": 1}], "reuses": [], "suppressGeometry": []}
    base.update(over)
    return base


def test_plan_parity_green():
    plan_a = _plan(suppressGeometry=[])
    plan_b = _plan(suppressGeometry=[5])
    assert plan_parity(plan_a, plan_b, compared_slides=[5]) == []


def test_plan_parity_flags_transform_drift():
    plan_a = _plan(suppressGeometry=[])
    plan_b = _plan(transforms=[{"slide": 2}], suppressGeometry=[5])
    reasons = plan_parity(plan_a, plan_b, compared_slides=[5])
    assert any("transforms" in r for r in reasons)


def test_plan_parity_flags_reuse_drift():
    plan_a = _plan(suppressGeometry=[])
    plan_b = _plan(reuses=[{"slide": 1, "from": 2}], suppressGeometry=[5])
    reasons = plan_parity(plan_a, plan_b, compared_slides=[5])
    assert any("reuses" in r for r in reasons)


def test_plan_parity_flags_a_suppress_geometry_nonempty():
    # A is the production (AppleScript-only) path — it must never suppress geometry.
    plan_a = _plan(suppressGeometry=[1])
    plan_b = _plan(suppressGeometry=[5])
    reasons = plan_parity(plan_a, plan_b, compared_slides=[5])
    assert any("suppressGeometry not empty" in r for r in reasons)


def test_plan_parity_flags_b_suppress_geometry_mismatch():
    # B must suppress EXACTLY the compared-slide set, not merely "something".
    plan_a = _plan(suppressGeometry=[])
    plan_b = _plan(suppressGeometry=[9])
    reasons = plan_parity(plan_a, plan_b, compared_slides=[5])
    assert any("suppressGeometry" in r and "compared slides" in r for r in reasons)


def test_plan_parity_suppress_geometry_never_an_equality_check():
    # A == [] and B == compared_slides is GREEN even though the two lists differ --
    # the old "identical suppressGeometry" rule could never pass by construction.
    plan_a = _plan(suppressGeometry=[])
    plan_b = _plan(suppressGeometry=[2, 5])
    assert plan_a["suppressGeometry"] != plan_b["suppressGeometry"]
    assert plan_parity(plan_a, plan_b, compared_slides=[2, 5]) == []


# --- unit_bucket / tol_for_bucket (D7/D8) ---------------------------------------------


def test_unit_bucket_top_level_keeps_kind():
    assert unit_bucket({"addr": ("top", "shape", 0), "kind": "shape"}) == "shape"


def test_unit_bucket_child_gets_prefix():
    addr = (("top", "group", 0), "child", 0)
    assert unit_bucket({"addr": addr, "kind": "image"}) == "child:image"


def test_tol_for_bucket_masked_uses_mask_tol():
    tols = Tolerances(hard=0.5, soft=1.0, mask=2.0, text=3.0)
    assert tol_for_bucket("image", "masked", tols) == 2.0


def test_tol_for_bucket_autosize_uses_text_tol():
    tols = Tolerances(hard=0.5, soft=1.0, mask=2.0, text=3.0)
    assert tol_for_bucket("text", "autosize", tols) == 3.0


def test_tol_for_bucket_hard_kinds_doubled_for_identity():
    # Two INDEPENDENT runs each within tols.hard of the plan can be 2x that apart.
    tols = Tolerances(hard=0.5, soft=1.0, mask=2.0, text=3.0)
    assert tol_for_bucket("shape", "frame", tols) == 1.0
    assert tol_for_bucket("line", "line", tols) == 1.0


def test_tol_for_bucket_soft_doubled_for_unmasked_top_level():
    tols = Tolerances(hard=0.5, soft=1.0, mask=2.0, text=3.0, child=4.0)
    assert tol_for_bucket("image", "frame", tols) == 2.0
    assert tol_for_bucket("group", "group", tols) == 2.0


def test_tol_for_bucket_child_star_uses_child_tol_regardless_of_kind():
    tols = Tolerances(hard=0.5, soft=1.0, mask=2.0, text=3.0, child=4.0)
    assert tol_for_bucket("child:image", "frame", tols) == 4.0
    assert tol_for_bucket("child:group", "group", tols) == 4.0
    assert tol_for_bucket("child:child", "frame", tols) == 4.0


# --- compare_units_identity (D1) ------------------------------------------------------


def _idunit(id_, kind, x, y, w, h, addr):
    return {"id": id_, "kind": kind, "addr": addr,
            "sig": {"type": "frame", "frame": (x, y, w, h), "flips": (False, False)}}


def test_compare_units_identity_matches_reordered_kindindex():
    a = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    b = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 1))]  # Bring-to-Front reordered
    report = compare_units_identity(a, b, Tolerances())
    assert report["pass"] is True
    assert report["id_rate"] == 1.0


def test_compare_units_identity_id_rate_below_one_fails():
    # Different ids at the SAME address: match_units falls back to addr, so the id RATE
    # drops below 1.0 even though the geometry is identical -- D1 gates on the id set.
    a = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    b = [_idunit("s2", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    report = compare_units_identity(a, b, Tolerances())
    assert report["id_rate"] == 0.0
    assert report["pass"] is False


def test_compare_units_identity_flags_unmatched_unit():
    a = [
        _idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0)),
        _idunit("s2", "shape", 20, 20, 10, 10, ("top", "shape", 1)),
    ]
    b = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    report = compare_units_identity(a, b, Tolerances())
    assert [u["id"] for u in report["unmatched_a"]] == ["s2"]
    assert report["pass"] is False


def test_compare_units_identity_autosize_is_x_only():
    a = [{"id": "t1", "kind": "text", "addr": ("top", "text", 0),
          "sig": {"type": "autosize", "x": 100.0, "flips": (False, False)}}]
    b = [{"id": "t1", "kind": "text", "addr": ("top", "text", 0),
          "sig": {"type": "autosize", "x": 101.5, "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances(text=2.0))
    assert report["pass"] is True
    assert report["per_bucket"]["text"]["worst"] == 1.5


def test_compare_units_identity_carves_autosize_shapes():
    a = [{"id": "sh1", "kind": "shape", "addr": ("top", "shape", 0),
          "sig": {"type": "frame", "frame": (0, 0, 0, 50), "flips": (False, False)}}]
    b = [{"id": "sh1", "kind": "shape", "addr": ("top", "shape", 0),
          "sig": {"type": "frame", "frame": (0, 0, 0, 999), "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances())
    assert report["carved"] == ["sh1"]
    assert report["pass"] is True
    assert report["per_bucket"] == {}


def test_compare_units_identity_buckets_group_children_separately():
    top_addr = ("top", "group", 0)
    child_addr = (top_addr, "child", 0)
    a = [
        _idunit("g1", "group", 0, 0, 100, 100, top_addr),
        _idunit("c1", "image", 10, 10, 20, 20, child_addr),
    ]
    b = [
        _idunit("g1", "group", 0, 0, 100, 100, top_addr),
        _idunit("c1", "image", 10, 10, 20, 20, child_addr),
    ]
    report = compare_units_identity(a, b, Tolerances())
    assert set(report["per_bucket"]) == {"group", "child:image"}


def test_compare_units_identity_duplicateof_twin_matches_both_units():
    # A text-bearing shape emits TWO units sharing ONE drawable id (the text unit and
    # its `duplicateOf` shape twin). id-only matching can cross-pair the A text unit to
    # B's shape unit (and vice versa), stranding the other side as unmatched even though
    # id_rate reads 100%. Composite (id, kind) matching must pair BOTH correctly.
    shared_id = "20539608"
    a = [
        {"id": shared_id, "kind": "text", "addr": ("top", "text", 0),
         "sig": {"type": "frame", "frame": (0, 0, 100, 20), "flips": (False, False)}},
        {"id": shared_id, "kind": "shape", "addr": ("top", "shape", 0),
         "sig": {"type": "frame", "frame": (0, 0, 100, 20), "flips": (False, False)}},
    ]
    b = [
        {"id": shared_id, "kind": "text", "addr": ("top", "text", 0),
         "sig": {"type": "frame", "frame": (0, 0, 100, 20), "flips": (False, False)}},
        {"id": shared_id, "kind": "shape", "addr": ("top", "shape", 0),
         "sig": {"type": "frame", "frame": (0, 0, 100, 20), "flips": (False, False)}},
    ]
    report = compare_units_identity(a, b, Tolerances())
    assert report["id_rate"] == 1.0
    assert report["unmatched_a"] == [] and report["unmatched_b"] == []
    assert report["per_bucket"]["text"]["n"] == 1
    assert report["per_bucket"]["shape"]["n"] == 1
    assert report["pass"] is True


def test_compare_units_identity_masked_image_stays_gating():
    a = [{"id": "i1", "kind": "image", "addr": ("top", "image", 0),
          "sig": {"type": "masked", "crop": (0, 0, 10, 10), "mask_angle": 0,
                  "raw_size": (10, 10), "flips": (False, False)}}]
    b = [{"id": "i1", "kind": "image", "addr": ("top", "image", 0),
          "sig": {"type": "masked", "crop": (5.0, 0, 10, 10), "mask_angle": 0,
                  "raw_size": (10, 10), "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances(mask=2.0))
    assert report["per_bucket"]["image"]["pass"] is False  # 5px > tols.mask
    assert report["pass"] is False


def test_compare_units_identity_child_bucket_uses_tol_child():
    child_addr = (("top", "group", 0), "child", 0)
    a = [_idunit("c1", "image", 0, 0, 10, 10, child_addr)]
    b_ok = [_idunit("c1", "image", 1.5, 0, 10, 10, child_addr)]
    b_bad = [_idunit("c1", "image", 2.5, 0, 10, 10, child_addr)]
    tols = Tolerances(child=2.0)
    assert compare_units_identity(a, b_ok, tols)["pass"] is True
    report_bad = compare_units_identity(a, b_bad, tols)
    assert report_bad["per_bucket"]["child:image"]["pass"] is False
    assert report_bad["pass"] is False


def test_compare_units_identity_shape_drift_1_5_fails_at_doubled_hard_tol():
    # 1.5px > 2*tols.hard (default 2*0.5=1.0) — matches D7's revised A-vs-B budget.
    a = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    b = [_idunit("s1", "shape", 1.5, 0, 10, 10, ("top", "shape", 0))]
    report = compare_units_identity(a, b, Tolerances(hard=0.5))
    assert report["per_bucket"]["shape"]["worst"] == 1.5
    assert report["pass"] is False


def test_compare_units_identity_group_1_43_passes_at_doubled_soft_tol():
    # Measured on the Map deck (2026-09-04): group A-vs-B worst 1.43px, within 2*tols.soft.
    a = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (0, 0, 100, 100), "flips": (False, False)}}]
    b = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (1.43, 0, 100, 100), "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances(soft=1.0))
    assert report["per_bucket"]["group"]["worst"] == 1.43
    assert report["pass"] is True


def test_compare_units_identity_line_0_95_passes_at_doubled_hard_tol():
    # Measured on the Map deck (2026-09-04): line A-vs-B worst 0.95px, within 2*tols.hard.
    a = [{"id": "l1", "kind": "line", "addr": ("top", "line", 0),
          "sig": {"type": "line", "endpoints": ((0.0, 0.0), (10.0, 10.0)), "flips": (False, False)}}]
    b = [{"id": "l1", "kind": "line", "addr": ("top", "line", 0),
          "sig": {"type": "line", "endpoints": ((0.95, 0.0), (10.0, 10.0)), "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances(hard=0.5))
    assert report["per_bucket"]["line"]["worst"] == 0.95
    assert report["pass"] is True


def test_compare_units_identity_mixed_masked_unmasked_bucket_order_independent():
    # Both share the top-level "image" bucket; each unit's OWN sig type picks its
    # tolerance (tols.mask vs 2*tols.soft) -- NOT whichever unit happened to insert the
    # bucket first (the bug the old "informational-decided-by-first-unit" design had).
    masked_a = {"id": "m1", "kind": "image", "addr": ("top", "image", 0),
               "sig": {"type": "masked", "crop": (0, 0, 10, 10), "mask_angle": 0,
                       "raw_size": (10, 10), "flips": (False, False)}}
    masked_b = {"id": "m1", "kind": "image", "addr": ("top", "image", 0),
               "sig": {"type": "masked", "crop": (5.0, 0, 10, 10), "mask_angle": 0,
                       "raw_size": (10, 10), "flips": (False, False)}}  # 5px > tols.mask
    unmasked_a = {"id": "u1", "kind": "image", "addr": ("top", "image", 1),
                 "sig": {"type": "frame", "frame": (0, 0, 10, 10), "flips": (False, False)}}
    unmasked_b = {"id": "u1", "kind": "image", "addr": ("top", "image", 1),
                 "sig": {"type": "frame", "frame": (0.5, 0, 10, 10), "flips": (False, False)}}  # within 2*soft

    order1 = compare_units_identity([masked_a, unmasked_a], [masked_b, unmasked_b], Tolerances())
    order2 = compare_units_identity([unmasked_a, masked_a], [unmasked_b, masked_b], Tolerances())
    assert order1["pass"] is False and order2["pass"] is False
    assert order1["pass"] == order2["pass"]
    assert order1["per_bucket"]["image"]["worst"] == order2["per_bucket"]["image"]["worst"] == 5.0


def test_compare_units_identity_flips_mismatch_fails_regardless_of_worst():
    a = [{"id": "s1", "kind": "shape", "addr": ("top", "shape", 0),
          "sig": {"type": "frame", "frame": (0, 0, 10, 10), "flips": (False, False)}}]
    b = [{"id": "s1", "kind": "shape", "addr": ("top", "shape", 0),
          "sig": {"type": "frame", "frame": (0, 0, 10, 10), "flips": (True, False)}}]
    report = compare_units_identity(a, b, Tolerances())
    assert report["per_bucket"]["shape"]["worst"] == 0.0  # geometry identical
    assert report["pass"] is False  # flips differ -> FAIL regardless of the (zero) delta


def test_compare_units_identity_type_mismatch_fails():
    a = [{"id": "t1", "kind": "text", "addr": ("top", "text", 0),
          "sig": {"type": "autosize", "x": 100.0, "flips": (False, False)}}]
    b = [{"id": "t1", "kind": "text", "addr": ("top", "text", 0),
          "sig": {"type": "frame", "frame": (100.0, 0, 50, 43), "flips": (False, False)}}]
    report = compare_units_identity(a, b, Tolerances())
    assert report["pass"] is False
    assert report["per_bucket"]["text"]["fails"][0]["worst"] == float("inf")


def test_compare_units_identity_raises_on_duplicate_composite_id():
    a = [
        _idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0)),
        _idunit("s1", "shape", 5, 5, 10, 10, ("top", "shape", 1)),  # same (id, kind) twice
    ]
    b = [_idunit("s1", "shape", 0, 0, 10, 10, ("top", "shape", 0))]
    with pytest.raises(ValueError, match="duplicate"):
        compare_units_identity(a, b, Tolerances())


# --- plan_oracle_slide (D3) -----------------------------------------------------------


def test_plan_oracle_slide_matches_by_id():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}]
    id_by_addr = {("shape", 0): "obj1"}
    recs_by_id = {"obj1": {"id": "obj1", "kind": "shape", "kindIndex": 0,
                           "x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["pass"] is True
    assert report["per_kind"]["shape"]["n"] == 1
    assert report["skipped"] == 0
    assert report["compared"] == 1


def test_plan_oracle_slide_skips_hide_role():
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "role": "hide"}]
    report = plan_oracle_slide(specs, {}, {}, Tolerances())
    assert report == {"pass": True, "per_kind": {}, "missing_ids": [], "skipped": 0, "compared": 0}


def test_plan_oracle_slide_skips_text_spec():
    # Autosize text geometry is not offline-recoverable — the identity compare covers it.
    specs = [{"slide": 1, "kind": "text", "kindIndex": 0, "x": 999.0, "y": 999.0}]
    id_by_addr = {("text", 0): "t1"}
    recs_by_id = {"t1": {"id": "t1", "kind": "text", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "autosize"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["per_kind"] == {}
    assert report["pass"] is True
    assert report["skipped"] == 1
    assert report["compared"] == 0  # vacuous — every spec on this slide was skipped


def test_plan_oracle_slide_compares_group_union_at_soft_tol():
    # A group's union IS offline-recoverable (unlike its children's live layout) --
    # compared against the composed group-union record at tols.soft.
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["per_kind"]["group"]["n"] == 1
    assert report["pass"] is True
    assert report["skipped"] == 0
    assert report["compared"] == 1


def test_plan_oracle_slide_group_fails_beyond_soft_tol():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 5.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0))
    assert report["per_kind"]["group"]["worst"] == 5.0
    assert report["pass"] is False


def test_plan_oracle_slide_skips_masked_image():
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 999.0, "y": 999.0}]
    id_by_addr = {("image", 0): "img1"}
    recs_by_id = {"img1": {"id": "img1", "kind": "image", "kindIndex": 0,
                           "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "mask"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["per_kind"] == {}
    assert report["pass"] is True
    assert report["skipped"] == 1
    assert report["compared"] == 0


def test_plan_oracle_slide_unmasked_image_is_compared():
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("image", 0): "img1"}
    recs_by_id = {"img1": {"id": "img1", "kind": "image", "kindIndex": 0,
                           "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["pass"] is True
    assert report["per_kind"]["image"]["n"] == 1
    assert report["skipped"] == 0


def test_plan_oracle_slide_line_uses_position_only():
    # Lines compare POSITION only (offline_write._spec_box) — a huge w/h drift must NOT fail.
    specs = [{"slide": 1, "kind": "line", "kindIndex": 0, "x": 10.0, "y": 20.0, "w": 999.0, "h": 999.0}]
    id_by_addr = {("line", 0): "l1"}
    recs_by_id = {"l1": {"id": "l1", "kind": "line", "kindIndex": 0,
                        "x": 10.0, "y": 20.0, "w": 5.0, "h": 5.0, "geom_source": "line"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["pass"] is True
    assert report["per_kind"]["line"]["worst"] == 0.0


def test_plan_oracle_slide_flags_missing_id():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 0.0, "y": 0.0}]
    report = plan_oracle_slide(specs, {}, {}, Tolerances())
    assert report["pass"] is False
    assert report["missing_ids"][0]["reason"] == "not in source kind index"


def test_plan_oracle_slide_flags_missing_from_output_deck():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 0.0, "y": 0.0}]
    id_by_addr = {("shape", 0): "obj1"}
    report = plan_oracle_slide(specs, id_by_addr, {}, Tolerances())
    assert report["pass"] is False
    assert report["missing_ids"][0]["reason"] == "missing from output deck"


def test_plan_oracle_slide_flags_spec_with_no_kindindex():
    # Should never happen (ItemTransform.as_dict always emits kindIndex) — never a
    # silent drop; a loud RED missing_ids entry instead.
    specs = [{"slide": 1, "kind": "shape", "x": 0.0, "y": 0.0}]
    report = plan_oracle_slide(specs, {}, {}, Tolerances())
    assert report["pass"] is False
    assert report["missing_ids"][0]["reason"] == "spec carries no kindIndex"


def test_plan_oracle_slide_worst_per_kind():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 5.0, "y": 0.0, "w": 0.0, "h": 0.0}]
    id_by_addr = {("shape", 0): "s1"}
    recs_by_id = {"s1": {"id": "s1", "kind": "shape", "kindIndex": 0,
                         "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(hard=0.5))
    assert report["per_kind"]["shape"]["worst"] == 5.0
    assert report["pass"] is False


# --- run_record / write_run_record / load_run_record (D13) ---------------------------


def _record(**over):
    base = dict(
        commit="abc123", deck_digest="dA", source_digest="dS",
        plan={"transforms": [{"slide": 1}], "reuses": [], "suppressGeometry": [],
             "statJobs": [{"slide": 3}]},
        child_resize={"ok": True, "jobs": 0}, applied=5, missed=0,
        offline_write={"slides": [1], "specs": {1: []}},
        spec_id_map={"1": [{"kind": "shape", "kindIndex": 0, "id": "obj1"}]},
    )
    base.update(over)
    return base


def test_run_record_drops_specs_from_offline_write():
    record = run_record(**_record())
    assert "specs" not in record["offlineWrite"]
    assert record["offlineWrite"]["slides"] == [1]


def test_run_record_trims_plan_to_three_keys():
    record = run_record(**_record(plan={"transforms": [1], "reuses": [2], "suppressGeometry": [3],
                                        "asGeom": {"junk": True}, "statJobs": []}))
    assert set(record["plan"]) == {"transforms", "reuses", "suppressGeometry"}


def test_run_record_computes_expect_raises_from_stat_jobs():
    record = run_record(**_record(plan={"transforms": [], "reuses": [], "suppressGeometry": [],
                                        "statJobs": [{"slide": 3}]}))
    assert record["expectRaises"] is True


def test_run_record_computes_expect_raises_from_badge_raises():
    record = run_record(**_record(plan={"transforms": [], "reuses": [], "suppressGeometry": [],
                                        "badgeRaises": [{"slide": 5}]}))
    assert record["expectRaises"] is True


def test_run_record_expect_raises_false_when_both_job_lists_empty():
    record = run_record(**_record(plan={"transforms": [], "reuses": [], "suppressGeometry": [],
                                        "statJobs": [], "badgeRaises": []}))
    assert record["expectRaises"] is False


def test_run_record_raises_when_plan_carries_neither_key():
    # A plan with NEITHER "statJobs" nor "badgeRaises" looks like an already-trimmed
    # persisted plan (a loaded run record's `plan`), not a fresh `plan_out` -- fail
    # loudly rather than silently reading it as "no jobs planned".
    with pytest.raises(ValueError, match="statJobs"):
        run_record(**_record(plan={"transforms": [], "reuses": [], "suppressGeometry": []}))


def test_write_run_record_round_trips(tmp_path):
    record = run_record(**_record())
    path = write_run_record(tmp_path / "A.run.json", record)
    assert json.loads(path.read_text()) == record


def test_load_run_record_refuses_gate_version_mismatch(tmp_path, monkeypatch):
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="digestX"))
    record["gateVersion"] = 999
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="gateVersion"):
        load_run_record(path, deck=deck, source=source)


def test_load_run_record_refuses_deck_digest_mismatch(tmp_path, monkeypatch):
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="something-else"))
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="deck digest"):
        load_run_record(path, deck=deck, source=source)


def test_load_run_record_refuses_source_digest_mismatch(tmp_path, monkeypatch):
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    # deck_digest is monkeypatched to a single constant regardless of path -- keep the
    # deck digest MATCHING so this test proves the SOURCE check specifically fires.
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="digestX", source_digest="something-else"))
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="source digest"):
        load_run_record(path, deck=deck, source=source)


def test_load_run_record_warns_but_does_not_refuse_commit_mismatch(tmp_path, monkeypatch, capsys):
    from scripts import offline_write_ab as owab

    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    monkeypatch.setattr(owab, "_git_head", lambda *a, **k: "current-head")
    record = run_record(**_record(deck_digest="digestX", source_digest="digestX", commit="stale-commit"))
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    loaded = load_run_record(path, deck=deck, source=source)
    assert loaded == record  # NOT refused
    out = capsys.readouterr().out
    assert "WARN" in out and "commit" in out


def test_load_run_record_accepts_matching_record(tmp_path, monkeypatch):
    from scripts import offline_write_ab as owab

    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    monkeypatch.setattr(owab, "_git_head", lambda *a, **k: "abc123")  # matches _record()'s commit
    record = run_record(**_record(deck_digest="digestX", source_digest="digestX"))
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    loaded = load_run_record(path, deck=deck, source=source)
    assert loaded == record


# --- remap_keynote plan_out carries pass-two expectations (spec item 2) --------------


def test_plan_out_carries_pass_two_expectations(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)

    def fake_plan_payload_transforms(wall, recipe, *, child_resize_report=None,
                                     badge_raise_report=None, **kwargs):
        if child_resize_report is not None:
            child_resize_report.append({"slide": 3, "captionPt": 24.0, "groupIndex": 1})
        if badge_raise_report is not None:
            badge_raise_report.append({"slide": 5, "isTitle": True})
        return []

    monkeypatch.setattr(rk, "plan_payload_transforms", fake_plan_payload_transforms)
    monkeypatch.setattr(rk, "plan_slide_reuses", lambda *a, **k: [])
    monkeypatch.setattr(
        rk, "recipe_for",
        lambda wall, template: {
            "source": "test", "mapSrc": "src", "mapDst": "dst",
            "destWidth": 1920, "destHeight": 1080, "characterStyles": [],
        },
    )
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 0, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0})
    # child_resize/badgeRaises are non-empty below, which would otherwise route through
    # the REAL pass-2 stat-finalize AppleScript (Keynote-touching) — never allowed here.
    monkeypatch.setattr(rk, "_run_stat_finalize", lambda *a, **k: {"ok": True, "jobs": 1})
    monkeypatch.setattr(rk, "read_template_stat_sizes", lambda *a, **k: {})
    monkeypatch.setattr(rk, "restore_card_stroke_widths", lambda *a, **k: None)

    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()

    wall_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}

    plan_out: dict = {}
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        plan_out=plan_out, log=lambda m: None,
    )

    assert plan_out["statJobs"] == [{"slide": 3, "captionPt": 24.0, "groupIndex": 1}]
    assert plan_out["badgeRaises"] == [{"slide": 5, "isTitle": True}]
    assert plan_out["groupRemoves"] == []
    assert plan_out["statSlides"] == [3]


# ============================================================================

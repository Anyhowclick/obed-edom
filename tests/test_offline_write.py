"""Pure-logic tests for the offline geometry-WRITE opt-in (``w-offline-write-optin``).

Style of ``tests/test_as_geometry.py``: everything here is pure Python (no Keynote, no
real IWA decode). Most functions live in ``obed_edom.offline_write``; a few `iwa_write`
calls it makes (``patch_deck_geometry``, ``bridge_specs_kindindex``,
``OfflineWriteCorrupted``) are imported LAZILY inside its functions, so they are
monkeypatched or stood in for here rather than exercised against a real deck.
"""

from __future__ import annotations

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
from scripts.offline_write_ab import compare_units_by_addr, compare_units_multiset


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


# --- compare_units_by_addr (BLOCKER item 7 gate follow-up) -----------------------


def test_compare_units_by_addr_catches_permutation_that_fools_the_multiset():
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
    assert addr_report["pass"] is False  # caught: huge per-address delta
    assert addr_report["per_kind"]["shape"]["pass"] is False


def test_compare_units_by_addr_group_is_informational():
    a = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (0, 0, 10, 10), "flips": (False, False)}}]
    b = [{"id": "g1", "kind": "group", "addr": ("top", "group", 0),
          "sig": {"type": "group", "union": (50, 50, 10, 10), "flips": (False, False)}}]
    report = compare_units_by_addr(a, b)
    assert report["pass"] is True  # group never gates this pass
    assert report["per_kind"]["group"]["informational"] is True
    assert report["per_kind"]["group"]["worst"] == 50.0


def test_compare_units_by_addr_gates_shape_line_image_movie():
    for kind in ("shape", "line", "image", "movie"):
        a = [_unit(kind, 0, 0, 10, 10, addr=("top", kind, 0))]
        b = [_unit(kind, 5, 0, 10, 10, addr=("top", kind, 0))]
        report = compare_units_by_addr(a, b, tol_hard=0.5, tol_soft=0.5)
        assert report["per_kind"][kind]["pass"] is False, kind
        assert report["pass"] is False, kind


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
    computation the plan-building hook performs when the flag is off."""
    from obed_edom.map_remap import ItemTransform
    from obed_edom.remap_keynote import _build_as_geometry, suppress_geometry_slides

    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
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
    """
    import obed_edom.offline_write as ow_mod
    import obed_edom.remap_keynote as rk
    from obed_edom.map_remap import ItemTransform

    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
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


# --- fix3 review finding 2: attach_group_children is offline-read-only ----------


def test_offline_read_off_skips_attach_group_children(monkeypatch, tmp_path):
    """child_src's offsets (iwa_runs._group_child_records) are computed against the
    group's STORED archive frame; ItemTransform derives targets against `self.src`,
    which under OBED_OFFLINE_READ=on is the offline-composed group rect (same stored-
    frame space, or the child union — both fine) but under =off is Keynote's LIVE
    frame. For a group whose children have already wrapped, stored != live union, so
    the subtraction would mix origins and displace every child. attach_group_children
    must simply not run when the wall payload did not come from the offline reader."""
    import obed_edom.iwa_runs as iwa_mod
    import obed_edom.remap_keynote as rk

    monkeypatch.setattr(rk, "plan_payload_transforms", lambda *a, **k: [])
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

    monkeypatch.setattr(iwa_mod, "_load_deck", lambda _p: ({}, {}, {}))
    monkeypatch.setattr(iwa_mod, "attach_group_child_text", lambda *a, **k: None)
    monkeypatch.setattr(iwa_mod, "attach_group_captions", lambda *a, **k: None)
    calls: list = []
    monkeypatch.setattr(iwa_mod, "attach_group_children", lambda *a, **k: calls.append(1))

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
        offline_read="off", log=lambda m: None,
    )
    assert calls == []

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        offline_read="on", log=lambda m: None,
    )
    assert calls == [1]


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

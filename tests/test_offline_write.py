"""Pure-logic tests for the offline geometry-WRITE opt-in (``w-offline-write-optin``).

Style of ``tests/test_as_geometry.py``: everything here is pure Python (no Keynote, no
real IWA decode). Most functions live in ``obed_edom.offline_write``; a few `iwa_write`
calls it makes (``patch_deck_geometry``, ``bridge_specs_kindindex``,
``OfflineWriteCorrupted``) are imported LAZILY inside its functions, so they are
monkeypatched or stood in for here rather than exercised against a real deck.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _fake_osascript
from obed_edom import offline_write
from obed_edom.iwa_geometry import audit_natural_consistency, compose_geometry
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.paths import find_repo_root
from obed_edom.offline_write import (
    OFFLINE_VERIFY_TOL,
    _drop_unreadable_seed_rows,
    _fallback_bodies,
    _fallback_specs_by_slide,
    _offline_write_slides,
    _reported_from_bulk_rows,
    _run_fallback_scripts,
    _soft_seed_slides,
    _tol_for_kind,
    build_fallback_scripts,
    coerce_kind_index_map,
    counts_from_payload,
    format_live_verify_coverage,
    group_frame_rows,
    live_verify_coverage,
    probe_iwa_extra,
    run_offline_write,
    verify_live_frames,
    verify_live_frames_multiset,
    verify_offline_frames,
)
from obed_edom.remap_keynote import (
    offline_maskcrop_enabled,
    offline_text_reposition_enabled,
    offline_write_mode,
)
from scripts.offline_write_ab import (
    CARD_REF_FLOOR,
    Tolerances,
    _id_by_addr_for_slide,
    card_border_damage_reasons,
    card_border_refs,
    compare_units_by_addr,
    compare_units_identity,
    compare_units_multiset,
    damage_check_line,
    keynote_open_documents,
    load_run_record,
    pass2_bar_line,
    pass2_health,
    pass2_parity,
    pass2_zero_warn,
    plan_oracle_slide,
    w2_oracle_kwargs,
    plan_parity,
    preview_provenance_warning,
    run_record,
    source_aspects,
    spec_id_map,
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


def _stub_plan(**overrides):
    from obed_edom.map_remap import Plan

    defaults = dict(
        transforms=[], placements=[], skipped_slides=[], fitted_slides=[],
        offframe=[], framing=[], child_resize=[], badge_raises=[], card_grid=[],
        roster={},
    )
    defaults.update(overrides)
    return Plan(**defaults)


def _result(**over):
    base = dict(refused=False, reason=None, applied=1, missed=0, missed_specs=[],
                soft_fallbacks=0, value_clean=True)
    base.update(over)
    return SimpleNamespace(**base)


# --- offline_write_mode ------------------------------------------------------


def test_offline_write_mode_defaults_on(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
    assert offline_write_mode() == "on"
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    assert offline_write_mode() == "off"


def test_offline_write_mode_parses_on_and_verify(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    assert offline_write_mode() == "on"
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "verify")
    assert offline_write_mode() == "verify"
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "ON")
    assert offline_write_mode() == "on"


def test_offline_write_mode_unknown_token_is_on(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "bogus")
    assert offline_write_mode() == "on"


def test_offline_write_mode_forced_off_without_as_geometry(monkeypatch):
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    monkeypatch.setenv("OBED_AS_GEOMETRY", "0")
    said = []
    assert offline_write_mode(say=said.append) == "off"
    assert said and "OBED_AS_GEOMETRY" in said[0]


# --- _drop_unreadable_seed_rows ----------------------------------------------


def test_drop_unreadable_seed_rows_drops_only_errored_item():
    # Error slide is 0-based (doc index); the seed is keyed 1-based. where=item:<row>,
    # row == kindIndex. Only the (text, 0) row on slide 5 is dropped.
    reported = {
        5: {("text", 0): [0.0, 0.0, 174.0, 77.0], ("text", 1): [100.0, 200.0, 50.0, 20.0]},
        6: {("text", 0): [10.0, 20.0, 30.0, 40.0]},
    }
    errors = [{"slide": 4, "kind": "text", "where": "item:0", "error": "position unreadable"}]
    out = _drop_unreadable_seed_rows(reported, errors)
    assert ("text", 0) not in out[5]
    assert out[5][("text", 1)] == [100.0, 200.0, 50.0, 20.0]  # sibling untouched
    assert out[6][("text", 0)] == [10.0, 20.0, 30.0, 40.0]    # other slide untouched


def test_drop_unreadable_seed_rows_ignores_non_item_errors():
    # Whole-collection / bulk / count errors carry no row index; they already null the
    # kind's rows upstream, so there is nothing to drop here.
    reported = {1: {("image", 0): [1.0, 2.0, 3.0, 4.0]}}
    errors = [
        {"slide": 0, "kind": "image", "where": "collection", "error": "x"},
        {"slide": 0, "kind": "image", "where": "bulk:position", "error": "y"},
        {"slide": None, "kind": "text", "where": "item:0", "error": "z"},  # no slide -> skip
    ]
    out = _drop_unreadable_seed_rows(reported, errors)
    assert out[1][("image", 0)] == [1.0, 2.0, 3.0, 4.0]


def test_drop_unreadable_seed_rows_handles_empty_and_missing():
    reported = {2: {("movie", 3): [0.0, 0.0, 0.0, 0.0]}}
    assert _drop_unreadable_seed_rows(reported, None) == reported  # no errors -> unchanged
    # error for a (kind, idx)/slide not present in the seed is a no-op, not an error
    out = _drop_unreadable_seed_rows(reported, [{"slide": 99, "kind": "movie", "where": "item:3"}])
    assert out[2][("movie", 3)] == [0.0, 0.0, 0.0, 0.0]


# --- offline_text_reposition_enabled -----------------------------------------


def test_offline_text_reposition_defaults_on(monkeypatch):
    monkeypatch.delenv("OBED_OFFLINE_TEXT", raising=False)
    assert offline_text_reposition_enabled() is True


def test_offline_text_reposition_parses_truthy_tokens(monkeypatch):
    for tok in ("1", "true", "yes", "on", "ON"):
        monkeypatch.setenv("OBED_OFFLINE_TEXT", tok)
        assert offline_text_reposition_enabled() is True
    for tok in ("0", "false", "off", "no"):
        monkeypatch.setenv("OBED_OFFLINE_TEXT", tok)
        assert offline_text_reposition_enabled() is False
    monkeypatch.setenv("OBED_OFFLINE_TEXT", "")
    assert offline_text_reposition_enabled() is True
    said = []
    monkeypatch.setenv("OBED_OFFLINE_TEXT", "bogus")
    assert offline_text_reposition_enabled(say=said.append) is False
    assert said and "Unknown" in said[0]


def test_offline_text_reposition_forced_off_when_offline_write_off(monkeypatch):
    monkeypatch.setenv("OBED_OFFLINE_TEXT", "on")
    said = []
    assert offline_text_reposition_enabled(offline_mode="off", say=said.append) is False
    assert said and "OBED_OFFLINE_WRITE" in said[0]


# --- offline_maskcrop_enabled ------------------------------------------------


def test_offline_maskcrop_defaults_on_and_parses_tokens(monkeypatch):
    monkeypatch.delenv("OBED_OFFLINE_MASKCROP", raising=False)
    assert offline_maskcrop_enabled() is True
    for tok in ("1", "true", "yes", "on", "ON"):
        monkeypatch.setenv("OBED_OFFLINE_MASKCROP", tok)
        assert offline_maskcrop_enabled() is True
    for tok in ("0", "false", "off", "no"):
        monkeypatch.setenv("OBED_OFFLINE_MASKCROP", tok)
        assert offline_maskcrop_enabled() is False
    monkeypatch.setenv("OBED_OFFLINE_MASKCROP", "")
    assert offline_maskcrop_enabled() is True
    said = []
    monkeypatch.setenv("OBED_OFFLINE_MASKCROP", "bogus")
    assert offline_maskcrop_enabled(say=said.append) is False
    assert said and "Unknown" in said[0]


def test_offline_maskcrop_forced_off_when_offline_write_off(monkeypatch):
    monkeypatch.setenv("OBED_OFFLINE_MASKCROP", "on")
    said = []
    assert offline_maskcrop_enabled(offline_mode="off", say=said.append) is False
    assert said and "OBED_OFFLINE_WRITE" in said[0]


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


def test_offline_slides_excludes_unaddressable_slides():
    specs = [
        _spec(slide=6, kind="text", kindIndex=0),
        _spec(slide=6, kind="table", kindIndex=0),  # no AS address -> whole slide excluded
        _spec(slide=7, kind="image", kindIndex=0),
    ]
    out = _offline_write_slides(specs, wanted=None)
    assert out == {7}


def test_offline_slides_intersects_slide_range():
    specs = [
        _spec(slide=3, kind="text", kindIndex=0),
        _spec(slide=4, kind="image", kindIndex=0),
        _spec(slide=5, kind="shape", kindIndex=0),
    ]
    out = _offline_write_slides(specs, wanted=[3, 4])
    assert out == {3, 4}


def test_offline_slides_includes_former_reuse_chain():
    specs = [_spec(slide=n, kind="text", kindIndex=0) for n in range(120, 130)]
    out = _offline_write_slides(specs, wanted=None)
    assert {123, 124, 125, 126, 127, 128} <= out


# --- _soft_seed_slides --------------------------------------------------------


def test_soft_seed_slides_only_text():
    specs_by_slide = {
        1: [_spec(slide=1, kind="group", kindIndex=0)],  # group: composed offline, no live seed
        2: [_spec(slide=2, kind="text", kindIndex=0)],
        3: [_spec(slide=3, kind="shape", kindIndex=0)],
        4: [_spec(slide=4, kind="text", kindIndex=0, role="hide")],
        5: [_spec(slide=5, kind="image", kindIndex=0)],  # masked or not: never a soft seed
    }
    out = _soft_seed_slides({1, 2, 3, 4, 5}, specs_by_slide)
    assert out == {2}


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


# --- _run_fallback_scripts -------------------------------------------------------


def test_run_fallback_scripts_parses_unwritable_log_lines(monkeypatch):
    _fake_osascript(
        monkeypatch,
        stderr="noise\nOBED_GEOM_UNWRITABLE slide=96 kind=image kindIndex=8\nmore noise\n",
    )
    ok, dumps, unwritable = _run_fallback_scripts(Path("/tmp/x.key"), ["SCRIPT"], lambda m: None)
    assert ok is True
    assert dumps == []
    assert unwritable == ["OBED_GEOM_UNWRITABLE slide=96 kind=image kindIndex=8"]


def test_run_fallback_scripts_reports_unwritable_alongside_session_failure(monkeypatch, tmp_path):
    _fake_osascript(
        monkeypatch,
        returncode=1,
        stderr="OBED_GEOM_UNWRITABLE slide=1 kind=shape kindIndex=0\n",
    )
    dest = tmp_path / "x.key"
    ok, dumps, unwritable = _run_fallback_scripts(dest, ["SCRIPT"], lambda m: None)
    assert ok is False
    assert len(dumps) == 1
    assert unwritable == ["OBED_GEOM_UNWRITABLE slide=1 kind=shape kindIndex=0"]


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


def test_fallback_carries_slide_hide_specs_for_bridging():
    hide = _spec(slide=1, kindIndex=0, role="hide")
    spec = _spec(slide=1, kindIndex=1)
    specs_by_slide = {1: [hide, spec]}
    results = {1: _result(missed_specs=[spec])}
    out = _fallback_specs_by_slide({1}, specs_by_slide, results)
    assert len(out[1]) == 2
    assert out[1][0] == spec
    assert sum(1 for s in out[1] if s.get("role") == "hide") == 1


def test_fallback_specs_by_slide_adds_no_hides_when_nothing_missed():
    specs_by_slide = {1: [_spec(slide=1, kindIndex=0, role="hide")]}
    results = {1: _result(missed_specs=[])}
    out = _fallback_specs_by_slide({1}, specs_by_slide, results)
    assert out == {}


def test_fallback_specs_include_autosize_text_misses():
    """Fix 2: an autosize-height text spec is a hard miss at the offline writer, so it
    must route through the same missed_specs -> fallback path as any other miss, and
    the fallback body writes its geometry via `set properties`."""
    spec = _spec(slide=1, kind="text", kindIndex=0, w=113.4, x=107.15)
    specs_by_slide = {1: [spec]}
    results = {1: _result(missed_specs=[spec])}
    out = _fallback_specs_by_slide({1}, specs_by_slide, results)
    assert out[1] == [spec]
    bodies = _fallback_bodies(out)
    assert "set properties of theObj to {width:" in bodies[1]


def test_slide96_fallback_bridges_missed_image_past_hides_to_correct_address():
    specs_by_slide = {96: [
        _spec(slide=96, kind="image", kindIndex=0, role="hide"),
        _spec(slide=96, kind="image", kindIndex=1, role="hide"),
        _spec(slide=96, kind="image", kindIndex=2, role="hide"),
        _spec(slide=96, kind="image", kindIndex=8, role="map",
              x=929.43, y=888.61, w=239.85, h=163.21),
    ]}
    missed = [specs_by_slide[96][3]]
    results = {96: _result(missed_specs=missed)}
    bodies = _fallback_bodies(_fallback_specs_by_slide({96}, specs_by_slide, results))
    assert "set theObj to image 6" in bodies[96]
    assert "set theObj to image 9" not in bodies[96]
    for hidden_addr in (1, 2, 3):  # the three hides are never addressed
        assert f"set theObj to image {hidden_addr}" not in bodies[96]


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


def test_verify_offline_frames_skips_line_kind():
    planned = {1: [_spec(slide=1, kind="line", kindIndex=0, x=999, y=999)]}
    composed = {1: [{"id": "l1", "kind": "line", "kindIndex": 0, "x": 0, "y": 0, "w": 1, "h": 1,
                      "geom_source": "line"}]}
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


def test_verify_offline_frames_reports_group_bar():
    planned = {1: [_spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=100, h=50)]}
    composed = {1: [{"id": "g1", "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 102,
                      "h": 50, "geom_source": "group-union", "needs_keynote": None}]}
    out = verify_offline_frames(planned, composed)
    assert set(out) == {"group"}
    max_delta, n, worst5 = out["group"]
    assert max_delta == 2.0
    assert n == 1
    assert worst5[0]["slide"] == 1


def test_verify_offline_frames_group_skips_needs_keynote_records():
    # Regression, banked numbers (slide 35 ki0, 2026-09-07 Full bank arm A): the composed
    # union is a `group-residual` record, so it must never enter the gating "group" bar --
    # but its magnitude must still surface via `group_frame_rows`' approximate list.
    planned = {35: [_spec(slide=35, kind="group", kindIndex=0,
                          x=960.0, y=212.55, w=3549.09, h=605.70)]}
    composed = {35: [{"id": "g35", "kind": "group", "kindIndex": 0,
                       "x": 961.43, "y": 292.31, "w": 1764.48, "h": 496.51,
                       "geom_source": "group-union", "needs_keynote": "group-residual"}]}
    out = verify_offline_frames(planned, composed)
    assert "group" not in out
    rows, approx = group_frame_rows(planned, composed)
    assert rows == []
    assert len(approx) == 1
    assert approx[0]["delta"] == pytest.approx(1784.61, abs=0.01)
    assert approx[0]["needs"] == "group-residual"


def test_group_frame_rows_addresses_every_failing_group():
    # The writer-fix consumer contract: every comparable group is individually
    # addressable (slide/kindIndex/id), not folded into a bare max.
    planned = {
        1: [_spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=100, h=50),
            _spec(slide=1, kind="group", kindIndex=1, x=0, y=0, w=100, h=50)],
        2: [_spec(slide=2, kind="group", kindIndex=0, x=0, y=0, w=100, h=50)],
    }
    composed = {
        1: [{"id": "g1", "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 100.1, "h": 50,
             "geom_source": "group-union", "needs_keynote": None},
            {"id": "g2", "kind": "group", "kindIndex": 1, "x": 0, "y": 0, "w": 103, "h": 50,
             "geom_source": "group-union", "needs_keynote": None}],
        2: [{"id": "g3", "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 104, "h": 50,
             "geom_source": "group-union", "needs_keynote": None}],
    }
    rows, approx = group_frame_rows(planned, composed)
    assert approx == []
    assert len(rows) == 3
    for r in rows:
        assert set(r) == {"slide", "kindIndex", "id", "delta"}
    failing = {(r["slide"], r["kindIndex"]) for r in rows if r["delta"] > 2.5}
    assert failing == {(1, 1), (2, 0)}


def test_verify_offline_frames_group_extends_rather_than_clobbers(monkeypatch):
    # N6: `per_kind["group"]` must never be a bare overwrite -- if "group" ever joined
    # `_OFFLINE_EXACT_KINDS`, rows the top-level scan already collected must survive
    # `group_frame_rows`' union-based rows, not be silently discarded by `=`.
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_OFFLINE_EXACT_KINDS", frozenset({"shape", "group"}))
    planned = {1: [_spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=100, h=50),
                   _spec(slide=1, kind="group", kindIndex=1, x=0, y=0, w=100, h=50)]}
    composed = {1: [{"id": "g1", "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 102,
                      "h": 50, "geom_source": "group-union", "needs_keynote": None},
                    {"id": "g2", "kind": "group", "kindIndex": 1, "x": 0, "y": 0, "w": 100,
                     "h": 50, "geom_source": "group-union", "needs_keynote": None}]}
    out = verify_offline_frames(planned, composed)
    # Each of the 2 group specs is picked up once by the top-level exact-kind scan and
    # once more by `group_frame_rows` -- 4 rows if merged, only 2 if clobbered by `=`.
    assert out["group"][1] == 4


def test_verify_offline_frames_group_uses_bridged_kindindex(monkeypatch):
    def fake_bridge(specs):
        return [dict(s, kindIndex=int(s["kindIndex"]) + 5) for s in specs]

    monkeypatch.setattr("obed_edom.iwa_write.bridge_specs_kindindex", fake_bridge, raising=False)
    planned = {1: [_spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10)]}
    composed = {1: [{"id": "g1", "kind": "group", "kindIndex": 5, "x": 0, "y": 0, "w": 10.3,
                      "h": 10, "geom_source": "group-union", "needs_keynote": None}]}
    out = verify_offline_frames(planned, composed)
    assert set(out) == {"group"}
    assert out["group"][1] == 1  # found via the bridged kindIndex 5, not the raw 0


def test_offline_verify_tol_is_per_kind():
    assert _tol_for_kind(OFFLINE_VERIFY_TOL, "shape") == 0.5
    assert _tol_for_kind(OFFLINE_VERIFY_TOL, "group") == 2.5


# --- audit_natural_consistency (naturalSize/originalSize/mask consistency) -------


def _na_geom(x, y, w, h, angle=0.0):
    return {"geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}, "angle": angle}}


def _na_shape(*, w, h, nw, nh, is_textbox=False):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": is_textbox,
            "super": {"pathsource": {"bezierPathSource": {"naturalSize": {"width": nw, "height": nh}}},
                      "super": _na_geom(0.0, 0.0, w, h)}}


def _na_image(*, w, h, ow, oh, mask_id=None, media_natural=None):
    obj = {"_pbtype": "TSD.ImageArchive", "super": _na_geom(0.0, 0.0, w, h),
           "originalSize": {"width": ow, "height": oh}}
    if mask_id is not None:
        obj["mask"] = {"identifier": mask_id}
    if media_natural is not None:
        obj["naturalSize"] = {"width": media_natural[0], "height": media_natural[1]}
    return obj


def _na_mask(*, x, y, w, h, nw, nh):
    return {"_pbtype": "TSD.MaskArchive",
            "pathsource": {"bezierPathSource": {"naturalSize": {"width": nw, "height": nh}}},
            "super": _na_geom(x, y, w, h)}


def _na_slide(*ids):
    return {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": i} for i in ids]}


def test_natural_audit_flags_stale_shape_naturalsize():
    shape = _na_shape(w=209.0, h=47.0, nw=52.238213, nh=11.679036)
    issues = audit_natural_consistency(_na_slide("1"), {"1": shape})
    assert len(issues) == 1
    assert issues[0]["rule"] == "shape-natural" and issues[0]["gating"] is True


def test_natural_audit_flags_stale_mask_naturalsize():
    mask = _na_mask(x=0.0, y=0.0, w=3840.0, h=1080.0, nw=960.0, nh=270.0)
    image = _na_image(w=3840.0, h=1080.0, ow=3840.0, oh=1080.0, mask_id="2")
    issues = audit_natural_consistency(_na_slide("1"), {"1": image, "2": mask})
    assert any(i["rule"] == "mask-natural" and i["gating"] for i in issues)
    assert not any(i["rule"] in ("originalSize", "mask-overhang") for i in issues)


def test_natural_audit_flags_originalsize_mismatch():
    image = _na_image(w=3840.0, h=1080.0, ow=1920.0, oh=540.0)
    issues = audit_natural_consistency(_na_slide("1"), {"1": image})
    assert len(issues) == 1
    assert issues[0]["rule"] == "originalSize" and issues[0]["gating"] is True


def test_natural_audit_flags_mask_overhang():
    # 2000/3840 == 0.5208 > the 0.5 tolerance.
    mask = _na_mask(x=-2000.0, y=0.0, w=3840.0, h=1080.0, nw=3840.0, nh=1080.0)
    image = _na_image(w=3840.0, h=1080.0, ow=3840.0, oh=1080.0, mask_id="2")
    issues = audit_natural_consistency(_na_slide("1"), {"1": image, "2": mask})
    assert any(i["rule"] == "mask-overhang" and i["gating"] for i in issues)

    # Slide-19 production shape: overhang ~6%, well under tolerance -> no issue.
    mask2 = _na_mask(x=-0.97, y=0.0, w=17.98, h=40.0, nw=17.98, nh=40.0)
    image2 = _na_image(w=16.04, h=40.0, ow=16.04, oh=40.0, mask_id="4")
    issues2 = audit_natural_consistency(_na_slide("3"), {"3": image2, "4": mask2})
    assert not any(i["rule"] == "mask-overhang" for i in issues2)


def test_natural_audit_production_mask_offset_is_not_an_issue():
    # Production's measured max overhang (21.93%) must stay comfortably under tolerance.
    mask = _na_mask(x=-21.93, y=0.0, w=100.0, h=100.0, nw=100.0, nh=100.0)
    image = _na_image(w=100.0, h=100.0, ow=100.0, oh=100.0, mask_id="2")
    issues = audit_natural_consistency(_na_slide("1"), {"1": image, "2": mask})
    assert not any(i["rule"] == "mask-overhang" for i in issues)


def test_natural_audit_text_zero_height_is_informational_not_gating():
    laid = _na_shape(w=1140.0, h=0.0, nw=1140.0, nh=328.2, is_textbox=True)
    assert audit_natural_consistency(_na_slide("1"), {"1": laid}) == []

    unlaid = _na_shape(w=1140.0, h=0.0, nw=1140.0, nh=0.0, is_textbox=True)
    issues = audit_natural_consistency(_na_slide("1"), {"1": unlaid})
    assert len(issues) == 1
    assert issues[0]["rule"] == "text-height-unlaid" and issues[0]["gating"] is False


def test_natural_audit_text_width_mismatch_is_gating():
    shape = _na_shape(w=1139.88, h=0.0, nw=581.88, nh=0.0, is_textbox=True)
    issues = audit_natural_consistency(_na_slide("1"), {"1": shape})
    assert any(i["rule"] == "text-natural-width" and i["gating"] for i in issues)


def test_natural_audit_never_reads_image_naturalsize():
    image = _na_image(w=100.0, h=100.0, ow=100.0, oh=100.0, media_natural=(7680.0, 1080.0))
    assert audit_natural_consistency(_na_slide("1"), {"1": image}) == []


def test_natural_audit_walks_group_descendants():
    bad_shape = _na_shape(w=209.0, h=47.0, nw=52.238213, nh=11.679036)
    group = {"_pbtype": "TSD.GroupArchive", "super": _na_geom(0.0, 0.0, 0.0, 0.0),
             "children": [{"identifier": "1"}]}
    issues = audit_natural_consistency(_na_slide("2"), {"1": bad_shape, "2": group})
    assert any(i["id"] == "1" and i["rule"] == "shape-natural" for i in issues)


def test_natural_audit_clean_deck_returns_empty():
    shape = _na_shape(w=100.0, h=50.0, nw=100.0, nh=50.0)
    mask = _na_mask(x=0.0, y=0.0, w=80.0, h=40.0, nw=80.0, nh=40.0)
    image = _na_image(w=80.0, h=40.0, ow=80.0, oh=40.0, mask_id="3")
    text = _na_shape(w=200.0, h=0.0, nw=200.0, nh=60.0, is_textbox=True)
    objects = {"1": shape, "2": image, "3": mask, "4": text}
    assert audit_natural_consistency(_na_slide("1", "2", "4"), objects) == []


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


def test_verify_live_frames_skips_only_multiset_routed_kinds_on_stat_slides():
    # W2 zorder-bridge Piece 1: pass 2 no longer permutes anything but `group` on a
    # stat-finalize slide, so only `(slide, "group")` routes to the Piece 2 multiset bar
    # (skipped here, not compared) — text/shape on the same slide still take the exact
    # positional bar, unlike the old whole-slide exclusion.
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
                    {"kind": "text", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                    {"kind": "group", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
                    {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                ],
            }
        ]
    }
    out = verify_live_frames(planned, payload, multiset_kinds_by_slide={1: {"group"}})
    assert set(out) == {"text", "shape"}
    assert out["text"][0] == 0.0
    assert out["shape"][0] == 0.0


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


def test_verify_live_frames_zorder_permutation_needs_remap():
    """W2 zorder-bridge Piece 1: the offline z-order patch permutes per-kind order on its
    target slides, so `planned` (pre-patch addressing) and `payload` (post-patch,
    Keynote-reported addressing) disagree on which kindIndex names which object.
    Positional compare FAILs without the `kindIndexMap`-derived remap, 0.00px with it."""
    planned = {
        3: [
            _spec(kind="shape", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(kind="shape", kindIndex=1, x=100, y=100, w=20, h=20),
            _spec(kind="shape", kindIndex=2, x=200, y=200, w=30, h=30),
            _spec(kind="text", kindIndex=0, x=5, y=5, w=1, h=1),
            _spec(kind="text", kindIndex=1, x=50, y=50, w=2, h=2),
        ]
    }
    payload = {"slides": [{"number": 3, "items": [
        {"kind": "shape", "kindIndex": 2, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "shape", "kindIndex": 1, "x": 100, "y": 100, "w": 20, "h": 20},
        {"kind": "shape", "kindIndex": 0, "x": 200, "y": 200, "w": 30, "h": 30},
        {"kind": "text", "kindIndex": 1, "x": 5, "y": 5, "w": 1, "h": 1},
        {"kind": "text", "kindIndex": 0, "x": 50, "y": 50, "w": 2, "h": 2},
    ]}]}

    without = verify_live_frames(planned, payload)
    assert without["shape"][0] > 0
    assert without["text"][0] > 0

    remap = {3: {"shape": {0: 2, 1: 1, 2: 0}, "text": {0: 1, 1: 0}}}
    with_remap = verify_live_frames(planned, payload, kindindex_remap=remap)
    assert with_remap["shape"][0] == 0.0
    assert with_remap["text"][0] == 0.0


def test_verify_live_frames_identity_remap_is_noop():
    planned = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames(planned, payload, kindindex_remap={1: {"shape": {0: 0}}})
    assert out["shape"][0] == 0.0


def test_verify_live_frames_remap_missing_index_counts_as_miss():
    # The remap says `shape` WAS permuted on slide 1 (it has an entry for that kind) but
    # carries no mapping for old index 0 — an unresolvable address, not a no-op fallback.
    planned = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames(planned, payload, kindindex_remap={1: {"shape": {1: 2}}})
    assert "shape" in out
    max_delta, n, _worst5 = out["shape"]
    assert max_delta == float("inf")
    assert n == 1


# --- verify_live_frames_multiset / live_verify_coverage (W2 zorder-bridge Piece 2) --


def test_verify_live_frames_multiset_passes_on_permuted_set():
    # Same three group frames as the payload, reported in a DIFFERENT order -- the
    # multiset bar must not care about order/assignment, only population.
    planned = {
        1: [
            _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=1, kind="group", kindIndex=1, x=100, y=100, w=20, h=20),
            _spec(slide=1, kind="group", kindIndex=2, x=200, y=200, w=30, h=30),
        ]
    }
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "group", "kindIndex": 2, "x": 200, "y": 200, "w": 30, "h": 30},
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "group", "kindIndex": 1, "x": 100, "y": 100, "w": 20, "h": 20},
    ]}]}
    out = verify_live_frames_multiset(planned, payload, {1: {"group"}})
    assert out["group"][0] == 0.0
    assert out["group"][1] == 3


def test_verify_live_frames_multiset_fails_on_one_perturbed_frame():
    planned = {
        1: [
            _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=1, kind="group", kindIndex=1, x=100, y=100, w=20, h=20),
        ]
    }
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "group", "kindIndex": 1, "x": 150, "y": 100, "w": 20, "h": 20},  # +50px
    ]}]}
    out = verify_live_frames_multiset(planned, payload, {1: {"group"}})
    assert out["group"][0] == 50.0


def test_verify_live_frames_multiset_only_compares_routed_kinds():
    planned = {
        1: [
            _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=1, kind="shape", kindIndex=0, x=999, y=999, w=1, h=1),
        ]
    }
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "shape", "kindIndex": 0, "x": 999, "y": 999, "w": 1, "h": 1},
    ]}]}
    out = verify_live_frames_multiset(planned, payload, {1: {"group"}})
    assert set(out) == {"group"}


def test_verify_live_frames_multiset_population_mismatch_is_infinite():
    # One extra planned frame with no corresponding reported box -- a real population
    # mismatch (an object went missing), reported as an infinite delta, not dropped.
    planned = {1: [
        _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
        _spec(slide=1, kind="group", kindIndex=1, x=500, y=500, w=5, h=5),
    ]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames_multiset(planned, payload, {1: {"group"}})
    assert out["group"][0] == float("inf")
    assert out["group"][1] == 2


def test_verify_live_frames_multiset_bridges_before_lookup(monkeypatch):
    def fake_bridge(specs):
        return [dict(s, kindIndex=int(s["kindIndex"]) + 5) for s in specs]

    monkeypatch.setattr("obed_edom.iwa_write.bridge_specs_kindindex", fake_bridge, raising=False)
    planned = {1: [_spec(slide=1, kind="group", kindIndex=0, x=1, y=2, w=3, h=4)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "group", "kindIndex": 5, "x": 1, "y": 2, "w": 3, "h": 4},
    ]}]}
    out = verify_live_frames_multiset(planned, payload, {1: {"group"}})
    assert out["group"][0] == 0.0


def test_zorder_bridge_falsifier_perturbed_frame_fails_positional_bar():
    """Plan (c) falsifier (a): perturbing one planned frame by +50px FAILs the
    POSITIONAL bar, naming the offending slide/kindIndex."""
    planned = {4: [_spec(slide=4, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 4, "items": [
        {"kind": "shape", "kindIndex": 0, "x": 50, "y": 0, "w": 10, "h": 10},
    ]}]}
    out = verify_live_frames(planned, payload)
    max_delta, n, worst5 = out["shape"]
    assert max_delta == 50.0
    assert n == 1
    assert worst5[0]["slide"] == 4
    assert worst5[0]["kindIndex"] == 0


def test_zorder_bridge_falsifier_swap_within_stat_group_is_positional_blind_multiset_sees_population():
    """Plan (c) falsifier (b): swapping two planned frames WITHIN a stat slide's `group`
    kind is exactly Option 2's documented blind spot -- the positional bar never sees it
    (the kind is routed away), while the multiset bar only proves population, not
    assignment, so it PASSes too. Both halves asserted together, as the plan requires."""
    # "Swap": what spec A/B *would* individually report is exchanged, but the multiset
    # of the two group frames on the slide is unchanged from what Keynote reports.
    planned = {19: [
        _spec(slide=19, kind="group", kindIndex=0, x=100, y=100, w=20, h=20),  # swapped
        _spec(slide=19, kind="group", kindIndex=1, x=0, y=0, w=10, h=10),      # swapped
    ]}
    payload = {"slides": [{"number": 19, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "group", "kindIndex": 1, "x": 100, "y": 100, "w": 20, "h": 20},
    ]}]}
    multiset_kinds_by_slide = {19: {"group"}}

    positional = verify_live_frames(planned, payload, multiset_kinds_by_slide=multiset_kinds_by_slide)
    assert "group" not in positional  # routed away, silent -- NOT a false PASS on 0 rows

    multiset = verify_live_frames_multiset(planned, payload, multiset_kinds_by_slide)
    assert multiset["group"][0] == 0.0  # PASSes: same two frames, just reassigned


def test_coerce_kind_index_map_int_keys_from_json_strings():
    raw = {"3": {"shape": {"0": 2, "1": 0, "2": 1}}}
    assert coerce_kind_index_map(raw) == {3: {"shape": {0: 2, 1: 0, 2: 1}}}


def test_live_verify_coverage_routes_group_to_set_bar_rest_positional():
    planned = {
        1: [
            _spec(slide=1, kind="text", kindIndex=0, x=0, y=0, w=1, h=1),
            _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=1, h=1),
        ],
        2: [_spec(slide=2, kind="shape", kindIndex=0, x=0, y=0, w=1, h=1)],
    }
    coverage = live_verify_coverage(planned, kindindex_remap={2: {"shape": {0: 0}}},
                                    multiset_kinds_by_slide={1: {"group"}})
    assert coverage["positionalSlides"] == [1, 2]
    assert coverage["remappedSlides"] == [2]
    assert coverage["setSlides"] == [1]
    assert coverage["groupBuckets"] == 1
    assert coverage["uncovered"] == []
    assert coverage["totalSlides"] == 2
    assert coverage["coveredSlides"] == 2


def test_live_verify_coverage_uncovered_when_kindindex_unresolved_and_unrouted():
    # A spec whose `kindIndex` is None is unresolvable by the positional bar
    # (`verify_live_frames` silently `continue`s past it), and this kind is not routed
    # to the multiset bar either -- neither bar can check it. Real data condition, not
    # a routing-table mirror (see `live_verify_coverage`'s docstring).
    planned = {1: [_spec(slide=1, kind="group", kindIndex=None, x=0, y=0, w=1, h=1)]}
    coverage = live_verify_coverage(planned, kindindex_remap={}, multiset_kinds_by_slide={})
    assert coverage["uncovered"] == [(1, "group")]
    assert coverage["coveredSlides"] == 0
    assert coverage["totalSlides"] == 1


def test_live_verify_coverage_unresolved_kindindex_still_covered_via_multiset_route():
    # The SAME unresolved kindIndex, but the kind IS routed to the multiset bar this
    # time -- multiset needs no kindIndex, so this is covered, not uncovered.
    planned = {1: [_spec(slide=1, kind="group", kindIndex=None, x=0, y=0, w=1, h=1)]}
    coverage = live_verify_coverage(planned, kindindex_remap={},
                                    multiset_kinds_by_slide={1: {"group"}})
    assert coverage["uncovered"] == []
    assert coverage["setSlides"] == [1]
    assert coverage["coveredSlides"] == 1


def test_live_verify_coverage_not_gated_bucket_counted_separately_not_uncovered_not_set():
    # Defect B: a `(slide, kind)` bucket the AppleScript fallback touched is covered but
    # neither GATED-set (`setSlides`/`groupBuckets`, which the set bar enforces) nor
    # `uncovered` (which reds the gate) -- its own `notGatedSlides`/`notGatedBuckets`.
    planned = {5: [_spec(slide=5, kind="group", kindIndex=0, x=0, y=0, w=1, h=1)]}
    coverage = live_verify_coverage(
        planned, kindindex_remap={}, multiset_kinds_by_slide={5: {"group"}},
        not_gated_kinds_by_slide={5: {"group"}},
    )
    assert coverage["setSlides"] == []
    assert coverage["groupBuckets"] == 0
    assert coverage["notGatedSlides"] == [5]
    assert coverage["notGatedBuckets"] == 1
    assert coverage["uncovered"] == []
    assert coverage["coveredSlides"] == 1


def test_live_verify_coverage_not_gated_default_empty_preserves_old_behavior():
    # No `not_gated_kinds_by_slide` argument at all -- every routed bucket stays GATED,
    # matching pre-Defect-B behaviour exactly.
    planned = {5: [_spec(slide=5, kind="group", kindIndex=0, x=0, y=0, w=1, h=1)]}
    coverage = live_verify_coverage(planned, kindindex_remap={}, multiset_kinds_by_slide={5: {"group"}})
    assert coverage["setSlides"] == [5]
    assert coverage["groupBuckets"] == 1
    assert coverage["notGatedSlides"] == []
    assert coverage["notGatedBuckets"] == 0


def test_format_live_verify_coverage_matches_plan_line_shape():
    coverage = {
        "positionalSlides": list(range(19)), "remappedSlides": list(range(17)),
        "setSlides": list(range(10)), "groupBuckets": 10,
        "notGatedSlides": [], "notGatedBuckets": 0, "uncovered": [],
        "totalSlides": 19, "coveredSlides": 19,
    }
    line = format_live_verify_coverage(coverage)
    assert line == (
        "live verify: positional 19 slide(s) (17 remapped), set-compare 10 group "
        "bucket(s) on 10 slide(s), not-gated 0 group bucket(s) on 0 slide(s) "
        "(AppleScript fallback), uncovered [] — total 19 of 19."
    )


# --- offline_write.live_verify (single call path, both call sites) ---------------


def test_live_verify_routes_not_gated_bucket_out_of_set_bar_regression_lock():
    """Regression lock for the call-site drift this plan fixes: the replay used to call
    `verify_live_frames_multiset` with the RAW `multiset_kinds_by_slide` (every
    stat-finalize `group` bucket, ungated) and never passed `not_gated_kinds_by_slide=`
    to `live_verify_coverage` -- so it gated buckets the AppleScript fallback wrote,
    which production deliberately excludes. Slide 7's whole `group` bucket here was
    written by the fallback and is 10px off; the OLD-STYLE ungated call below FAILS on
    it. `live_verify` derives the gated/not-gated split itself and PASSES the identical
    data, because that bucket is correctly routed OUT of the gated set bar.
    """
    specs = {
        7: [
            _spec(slide=7, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            _spec(slide=7, kind="group", kindIndex=1, x=100, y=100, w=20, h=20),
        ]
    }
    payload = {"slides": [{"number": 7, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
        {"kind": "group", "kindIndex": 1, "x": 110, "y": 100, "w": 20, "h": 20},
    ]}]}
    multiset_kinds_by_slide = {7: {"group"}}

    old_style_report = verify_live_frames_multiset(specs, payload, multiset_kinds_by_slide)
    old_style_pass = offline_write._say_verify_report(
        "old-style (drifted, ungated)", old_style_report, offline_write.LIVE_VERIFY_TOL, None
    )
    assert old_style_pass is False

    ow = {"specs": specs, "statSlides": [7], "fallbackKinds": {"7": ["group"]}}
    report = offline_write.live_verify(ow, None, payload)
    assert report.set_pass is True


def test_live_verify_ow_updates_match_production_keys():
    specs = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
    ]}]}
    ow = {"specs": specs, "statSlides": [], "fallbackKinds": {}}
    report = offline_write.live_verify(ow, None, payload)
    updates = report.ow_updates()
    assert set(updates) == {"liveVerifyPass", "liveVerifySetPass", "liveVerifyCoverage"}
    assert updates["liveVerifyPass"] is True
    assert updates["liveVerifySetPass"] is True
    assert updates["liveVerifyCoverage"]["uncovered"] == []
    assert all(isinstance(u, list) for u in updates["liveVerifyCoverage"]["uncovered"])


def test_live_verify_uncovered_forces_pass_false():
    # A group spec whose kindIndex is None is unresolvable by BOTH bars -- uncovered,
    # and forces liveVerifyPass False even though the positional bar has nothing
    # comparable to report (a vacuous PASS on its own).
    specs = {1: [_spec(slide=1, kind="group", kindIndex=None, x=0, y=0, w=1, h=1)]}
    payload = {"slides": [{"number": 1, "items": []}]}
    ow = {"specs": specs, "statSlides": [], "fallbackKinds": {}}
    report = offline_write.live_verify(ow, None, payload)
    assert report.positional_pass is True
    updates = report.ow_updates()
    assert updates["liveVerifyCoverage"]["uncovered"] == [[1, "group"]]
    assert updates["liveVerifyPass"] is False


def test_live_verify_planned_override_vs_derived_from_specs():
    specs = {1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)]}
    payload = {"slides": [{"number": 1, "items": [
        {"kind": "shape", "kindIndex": 0, "x": 999, "y": 999, "w": 10, "h": 10},
    ]}]}
    ow = {"specs": specs, "statSlides": [], "fallbackKinds": {}}

    # No `planned=` given -- derived from `ow["specs"]`; the mismatched payload FAILs.
    derived = offline_write.live_verify(ow, None, payload)
    assert derived.positional_pass is False

    # `planned=` override wins over `ow["specs"]` -- empty override compares nothing.
    overridden = offline_write.live_verify(ow, None, payload, planned={})
    assert overridden.positional_pass is True


def test_live_verify_routing_splits_fallback_buckets_out_of_the_gated_set():
    """`live_verify_routing` is the ONE definition of the split, shared by `live_verify`
    and by `scripts/replay_live_verify.py`'s partial path (which runs the set bar alone
    because its banked record predates `kindIndexMap`). Slide 7's group bucket was written
    by the AppleScript fallback, so it is routed OUT of the gated set and INTO not-gated;
    slide 9's was not, so it stays gated. Both remain in the multiset for coverage
    accounting -- a bucket that fell out of both would be `uncovered` and RED the gate.
    """
    ow = {"statSlides": [7, 9], "fallbackKinds": {"7": ["group"]}}

    multiset, gated, not_gated = offline_write.live_verify_routing(ow)

    assert multiset == {7: {"group"}, 9: {"group"}}
    assert gated == {9: {"group"}}
    assert not_gated == {7: {"group"}}


def test_live_verify_routing_without_fallback_kinds_gates_everything():
    """A banked record predating `fallbackKinds` (every record in the 2026-09-16 bank)
    makes the split a no-op: every routed bucket stays gated, so a replay against such a
    record reports the same numbers it did before the routing moved behind the helper."""
    ow = {"statSlides": [2, 4], "fallbackKinds": {}}

    multiset, gated, not_gated = offline_write.live_verify_routing(ow)

    assert gated == multiset == {2: {"group"}, 4: {"group"}}
    assert not_gated == {}


# --- run_offline_zorder kindIndexMap (W2 zorder-bridge Piece 1) ------------------


def _zorder_shape(text_box=False, custom_path=False):
    obj = {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": text_box}
    if custom_path:
        obj["super"] = {"pathsource": {"editableBezierPathSource": {"present": True}}}
    return obj


def test_run_offline_zorder_kind_index_map_joins_on_id_and_kind(monkeypatch):
    """The (id, kind) join regression: a dual (custom-path text box, "d") is permuted
    across both its `text` and `shape` slots and must remap each independently."""
    from obed_edom import offline_write

    slide = {"drawablesZOrder": [{"identifier": i} for i in ("a", "b", "c", "d")]}
    objects = {
        "a": _zorder_shape(),
        "b": _zorder_shape(),
        "c": _zorder_shape(text_box=True),
        "d": _zorder_shape(text_box=True, custom_path=True),
        "slide1": slide,
    }

    # iwa_zorder patched FIRST: it imports `_load_deck`/`slide_order` from iwa_runs at
    # ITS OWN module load, so if this test is the first thing in the process to import
    # iwa_zorder, that import must run before iwa_runs' names below are stubbed -- else
    # iwa_zorder's own copies bind to the stubs permanently (module imports cache once).
    monkeypatch.setattr(
        "obed_edom.iwa_zorder.plan_slide_order",
        lambda slide, objects, stat_ids, badge_ids: ["d", "c", "b", "a"],
        raising=False,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_zorder.patch_deck_zorder",
        lambda dest, orders_by_slide: {n: SimpleNamespace(refused=False) for n in orders_by_slide},
        raising=False,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_runs._load_deck", lambda *a, **k: (objects, {}, {}), raising=False
    )
    monkeypatch.setattr(
        "obed_edom.iwa_runs.slide_order", lambda objs: [("slide1", False)], raising=False
    )

    targets = {1: {"stat": ["a"], "badge": []}}
    result = offline_write.run_offline_zorder(Path("dummy.key"), "on", targets, lambda s: None)

    assert result["slides"] == [1]
    assert result["kindIndexMap"] == {
        "1": {"shape": {"0": 2, "1": 1, "2": 0}, "text": {"0": 1, "1": 0}},
    }


def test_run_offline_zorder_kind_index_map_omits_rolled_back_slide(monkeypatch):
    """`verify`-mode rollback removes a slide from `patched_slides` before the map is
    built, so a slide whose read-back mismatched must carry no `kindIndexMap` entry."""
    from obed_edom import iwa_write, offline_write

    slide1 = {"drawablesZOrder": [{"identifier": i} for i in ("a", "b")]}
    slide2 = {"drawablesZOrder": [{"identifier": i} for i in ("x", "y")]}
    objects = {
        "a": _zorder_shape(), "b": _zorder_shape(),
        "x": _zorder_shape(), "y": _zorder_shape(),
        "slide1": slide1, "slide2": slide2,
    }

    # See the ordering comment in the join-regression test above: iwa_zorder patched
    # before iwa_runs so a first-ever import of iwa_zorder doesn't bind to the stubs.
    monkeypatch.setattr(
        "obed_edom.iwa_zorder.plan_slide_order",
        lambda slide, objects, stat_ids, badge_ids: list(
            reversed([str(r["identifier"]) for r in slide["drawablesZOrder"]])
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_zorder.patch_deck_zorder",
        lambda dest, orders_by_slide: {n: SimpleNamespace(refused=False) for n in orders_by_slide},
        raising=False,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_runs._load_deck", lambda *a, **k: (objects, {}, {}), raising=False
    )
    monkeypatch.setattr(
        "obed_edom.iwa_runs.slide_order",
        lambda objs: [("slide1", False), ("slide2", False)],
        raising=False,
    )

    def fake_read_deck_zorders(dest, ns):
        assert list(ns) == [1, 2]
        return {
            1: (["b", "a"], ["b", "a"]),  # matches the patched order -> keeps slide 1
            2: (["bogus"], ["bogus"]),  # mismatches slide 2's patched order -> rolls back
        }

    monkeypatch.setattr(iwa_write, "read_deck_zorders", fake_read_deck_zorders)

    targets = {1: {"stat": ["a"], "badge": []}, 2: {"stat": ["x"], "badge": []}}
    result = offline_write.run_offline_zorder(Path("dummy.key"), "verify", targets, lambda s: None)

    assert result["slides"] == [1]
    assert set(result["kindIndexMap"]) == {"1"}


def test_run_offline_zorder_kind_index_map_round_trips_via_write_run_record(tmp_path):
    """Defect A regression: `run_offline_zorder` emits a STRING-keyed `kindIndexMap`
    (slide, then old kindIndex), so a record built straight from it survives
    `write_run_record`'s JSON round-trip self-check. Before this fix, production emitted
    int keys, which came back string-keyed after the JSON round trip and raised
    `RuntimeError: run record round-trip mismatch` -- the unit tests missed it because
    they used string keys directly, unlike production."""
    zorder_write = {
        "mode": "verify",
        "slides": [1, 2],
        "kindIndexMap": {
            "1": {"shape": {"0": 2, "1": 1, "2": 0}, "text": {"0": 1, "1": 0}},
            "2": {"group": {"0": 1, "1": 0}},
        },
        "zorderSlides": 2, "zorderStatRaised": 0, "zorderBadgeRaised": 0,
        "zorderNoop": 0, "zorderRefused": 0, "zorderLost": 0, "failures": [],
    }
    record = run_record(**_record(zorder_write=zorder_write))
    path = write_run_record(tmp_path / "A.run.json", record)  # raises on round-trip mismatch
    reloaded = json.loads(path.read_text())
    assert reloaded == record
    assert reloaded["zorderWrite"]["kindIndexMap"] == zorder_write["kindIndexMap"]


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
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
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


def test_run_offline_write_group_bar_gates_at_group_tolerance(monkeypatch):
    # Proves group is judged at OFFLINE_VERIFY_TOL["group"] (2.5px), not the 0.5px default.
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    group_specs = [_spec(slide=1, kind="group", kindIndex=0)]
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"group": (1.0, 5, [])})
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], lambda m: None)
    assert info["offlineVerifyPass"] is True  # 1.0px <= 2.5px

    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"group": (3.0, 5, [])})
    info_bad = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], lambda m: None)
    assert info_bad["offlineVerifyPass"] is False  # 3.0px > 2.5px


def test_run_offline_write_fails_when_group_specs_planned_but_no_group_line(monkeypatch):
    # Regression for the silent PASS that shipped the writer bug: a "group" line missing
    # from the report entirely (not just failing) must itself fail offlineVerifyPass.
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"shape": (0.0, 1, [])})
    said: list[str] = []
    info = run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kind="group", kindIndex=0)], {}, [],
        said.append,
    )
    assert info["offlineVerifyPass"] is False
    assert any("group bar did NOT run" in m for m in said)


def test_run_offline_write_group_verify_payload(monkeypatch):
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"group": (1.0, 1, [])})
    group_specs = [_spec(slide=1, kind="group", kindIndex=0)]
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], lambda m: None)
    assert info["groupVerify"] == {"planned": 1, "written": 1, "n": 1, "max": 1.0, "missedMax": None}

    info_on = run_offline_write(Path("/tmp/x.key"), "on", {1}, group_specs, {}, [], lambda m: None)
    assert "groupVerify" not in info_on


def test_run_offline_write_group_verify_max_none_when_zero_rows(monkeypatch):
    # N7: a 0.0 "max" reads as a perfect score to a later record reader; when the group
    # bar produced zero comparable rows (no "group" key in the report at all), max must
    # be None, not the falsely-perfect 0.0 default.
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"shape": (0.0, 1, [])})
    group_specs = [_spec(slide=1, kind="group", kindIndex=0)]
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], lambda m: None)
    assert info["groupVerify"]["n"] == 0
    assert info["groupVerify"]["max"] is None


def test_run_offline_write_reports_group_approx_not_gated(monkeypatch):
    # N3: needs_keynote-flagged group rows are excluded from the gating bar but must
    # still surface -- a `verify` run must never look silently perfect while 13.5% of
    # groups sat outside the compare, unnoticed.
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"group": (1.0, 1, [])})
    approx_row = {"slide": 36, "kindIndex": 2, "id": "ki2", "delta": 139.25,
                 "needs": "group-residual"}
    monkeypatch.setattr(ow_mod, "group_frame_rows", lambda *a, **k: ([], [approx_row]))
    said: list[str] = []
    group_specs = [_spec(slide=1, kind="group", kindIndex=0)]
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], said.append)
    assert any("group-approx n=1 worst=139.25px NOT GATED" in m for m in said)
    assert info["offlineVerifyPass"] is True  # the approx line is informational, not gating


def test_run_offline_write_group_missed_reports_and_does_not_fail(monkeypatch):
    # T5 -- fix 3: a group spec the offline patcher missed (routed to the AppleScript
    # fallback) must not be scored by the gating group bar, but its magnitude must still
    # surface on a `group-missed ... NOT GATED` line, and it must not sink offlineVerifyPass.
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    written_spec = _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=100, h=50)
    missed_spec = _spec(slide=1, kind="group", kindIndex=1, x=200, y=200, w=100, h=50)
    group_specs = [written_spec, missed_spec]

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(missed_specs=[missed_spec])},
    )
    composed = {1: [
        {"id": "g0", "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 100, "h": 50,
         "geom_source": "group-union", "needs_keynote": None},
        {"id": "g1", "kind": "group", "kindIndex": 1, "x": 339, "y": 200, "w": 100, "h": 50,
         "geom_source": "group-union", "needs_keynote": None},
    ]}
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: composed)
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "_fallback_bodies", lambda fb: {1: "BODY"})
    monkeypatch.setattr(ow_mod, "build_fallback_scripts", lambda dest, bodies: ["SCRIPT"])
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))
    said: list[str] = []
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], said.append)

    assert info["offlineVerifyPass"] is True
    assert info["groupVerify"] == {
        "planned": 2, "written": 1, "n": 1, "max": pytest.approx(0.0), "missedMax": pytest.approx(139.0)
    }
    assert any("group-missed n=1 worst=139.00px NOT GATED" in m for m in said)
    assert not any("group bar did NOT run" in m for m in said)

    # Negative: every group spec missed -> written == 0 -> the "bar did NOT run" line must
    # NOT fire (it would prove nothing) and the run must not FAIL for it.
    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(missed_specs=[written_spec, missed_spec])},
    )
    said2: list[str] = []
    info2 = run_offline_write(Path("/tmp/x.key"), "verify", {1}, group_specs, {}, [], said2.append)
    assert info2["offlineVerifyPass"] is True
    assert not any("group bar did NOT run" in m for m in said2)


def test_run_offline_write_fallback_reason_histogram(monkeypatch):
    # OPEN 1 instrumentation: every fallback spec is bucketed by its coarse miss reason
    # (from PatchResult.miss_reasons, aligned with missed_specs), surfaced both in the
    # payload and on a log line, so a future run can characterize which specs miss.
    import obed_edom.offline_write as ow_mod

    s1a = _spec(slide=1, kind="text", kindIndex=0)
    s1b = _spec(slide=1, kind="image", kindIndex=0)
    s2 = _spec(slide=2, kind="text", kindIndex=0)
    transform_dicts = [s1a, s1b, s2]

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {
            1: _result(missed_specs=[s1a, s1b], miss_reasons=["text-autosize", "masked-media"]),
            2: _result(missed_specs=[s2], miss_reasons=["text-autosize"]),
        },
    )
    monkeypatch.setattr(ow_mod, "_fallback_bodies", lambda fb: {n: "BODY" for n in fb})
    monkeypatch.setattr(ow_mod, "build_fallback_scripts", lambda dest, bodies: ["SCRIPT"])
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))

    said: list[str] = []
    info = run_offline_write(Path("/tmp/x.key"), "on", {1, 2}, transform_dicts, {}, [], said.append)

    assert info["fallbackReasons"] == {"text-autosize": 2, "masked-media": 1}
    assert info["fallbackReasonsBySlide"] == {
        "1": {"text-autosize": 1, "masked-media": 1},
        "2": {"text-autosize": 1},
    }
    # Sorted by descending count, so the dominant reason leads.
    assert any("fallback reasons: text-autosize 2, masked-media 1." in m for m in said)
    assert any("fallback worst slides" in m for m in said)


def test_run_offline_write_refused_slide_reason_bucket(monkeypatch):
    # A refused slide falls back whole; its non-hide specs land in a single refused:<reason>
    # bucket rather than a per-spec family (the patcher never reached per-spec resolution).
    import obed_edom.offline_write as ow_mod

    s1 = _spec(slide=1, kind="shape", kindIndex=0)
    s2 = _spec(slide=1, kind="shape", kindIndex=1)
    hide = _spec(slide=1, kind="shape", kindIndex=2, role="hide")
    transform_dicts = [s1, s2, hide]

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(refused=True, reason="reconcile mismatch", missed_specs=[])},
    )
    monkeypatch.setattr(ow_mod, "_fallback_bodies", lambda fb: {n: "BODY" for n in fb})
    monkeypatch.setattr(ow_mod, "build_fallback_scripts", lambda dest, bodies: ["SCRIPT"])
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))

    said: list[str] = []
    info = run_offline_write(Path("/tmp/x.key"), "on", {1}, transform_dicts, {}, [], said.append)

    # Two non-hide specs, one refused bucket; the hide does not count.
    assert info["fallbackReasons"] == {"refused:reconcile mismatch": 2}
    assert info["fallbackReasonsBySlide"] == {"1": {"refused:reconcile mismatch": 2}}


def test_run_offline_write_group_bar_still_gates_the_written_group(monkeypatch):
    # T6 -- fix 3 must not weaken the writer's own bar: a WRITTEN group 5px off-plan
    # still fails offlineVerifyPass (2.5px tolerance).
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    written_spec = _spec(slide=1, kind="group", kindIndex=0, x=0, y=0, w=100, h=50)
    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    composed = {1: [
        {"id": "g0", "kind": "group", "kindIndex": 0, "x": 5, "y": 0, "w": 100, "h": 50,
         "geom_source": "group-union", "needs_keynote": None},
    ]}
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: composed)
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    info = run_offline_write(Path("/tmp/x.key"), "verify", {1}, [written_spec], {}, [], lambda m: None)
    assert info["offlineVerifyPass"] is False  # 5px > OFFLINE_VERIFY_TOL["group"] (2.5px)


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
        lambda dest, scripts, say: (False, [Path("/tmp/x.offline-fallback.applescript")], []),
    )
    with pytest.raises(RuntimeError, match="offline-write fallback failed"):
        run_offline_write(
            Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
        )


def test_run_offline_write_records_fallback_unwritable(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(refused=True, reason="x", applied=0, value_clean=False)},
    )
    monkeypatch.setattr(ow_mod, "_fallback_bodies", lambda fb: {1: "BODY"})
    monkeypatch.setattr(ow_mod, "build_fallback_scripts", lambda dest, bodies: ["SCRIPT"])
    monkeypatch.setattr(
        ow_mod, "_run_fallback_scripts",
        lambda dest, scripts, say: (True, [], ["OBED_GEOM_UNWRITABLE slide=1 kind=image kindIndex=8"]),
    )
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["fallbackUnwritable"] == 1


def test_run_offline_write_fallback_unwritable_zero_by_default(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["fallbackUnwritable"] == 0


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
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    composed_calls = []
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: composed_calls.append(1) or {})
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: {})
    run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert composed_calls == [1]


def test_run_offline_write_decodes_once_for_the_frames_and_audit_pair(monkeypatch):
    # fix5: _composed_frames and _natural_audit each did their own _load_deck; verify
    # mode must now load once and pass the same deck to both.
    import obed_edom.offline_write as ow_mod

    load_calls = []

    def _fake_load_deck(*a, **k):
        load_calls.append(1)
        skipped = k.get("skipped")
        if skipped is not None:
            skipped.append(("Slide123.iwa", "bad zip member"))
        return ({}, {}, {})

    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", _fake_load_deck, raising=False)
    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    messages = []
    run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], messages.append
    )
    assert load_calls == [1]
    output = "\n".join(messages)
    assert "WARN" in output
    assert "Slide123.iwa" in output
    assert "1 undecodable" in output


def test_run_offline_write_skips_natural_audit_in_on_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    audit_calls = []
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: audit_calls.append(1) or {})
    run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert audit_calls == []  # "on" never pays for the diagnostic natural-consistency audit


def test_run_offline_write_runs_natural_audit_in_verify_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    audit_calls = []
    monkeypatch.setattr(ow_mod, "_natural_audit", lambda *a, **k: audit_calls.append(1) or {})
    run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert audit_calls == [1]


def test_run_offline_write_natural_consistency_fails_offline_verify_pass(monkeypatch):
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {"shape": (0.1, 1, [])})
    monkeypatch.setattr(
        ow_mod, "_natural_audit",
        lambda *a, **k: {1: [{"id": "9", "rule": "shape-natural", "gating": True, "detail": None}]},
    )
    info = run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    # A passing frame report alone is not enough: a gating natural-consistency issue
    # must also fail offlineVerifyPass.
    assert info["offlineVerifyPass"] is False
    assert info["naturalConsistencyIssues"] == 1


def test_run_offline_write_natural_consistency_keys_present_in_verify_mode(monkeypatch):
    import obed_edom.offline_write as ow_mod
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda *a, **k: ({}, {}, {}), raising=False)

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    monkeypatch.setattr(ow_mod, "_composed_frames", lambda *a, **k: {})
    monkeypatch.setattr(ow_mod, "verify_offline_frames", lambda *a, **k: {})
    monkeypatch.setattr(
        ow_mod, "_natural_audit",
        lambda *a, **k: {1: [{"id": "9", "rule": "text-height-unlaid", "gating": False, "detail": None}]},
    )
    info = run_offline_write(
        Path("/tmp/x.key"), "verify", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["naturalConsistencyIssues"] == 0
    assert info["naturalConsistencyInformational"] == 1


def test_run_offline_write_natural_consistency_keys_zero_in_on_mode(monkeypatch):
    # "on" mode never runs the audit (see test_run_offline_write_skips_natural_audit_in_on_mode):
    # the keys stay present (same unconditional-dict shape as softFallbacks) but read 0.
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result()})
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["naturalConsistencyIssues"] == 0
    assert info["naturalConsistencyInformational"] == 0


def test_run_offline_write_returns_none_when_no_offline_slides():
    assert run_offline_write(Path("/tmp/x.key"), "on", set(), [], {}, [], lambda m: None) is None


def test_run_offline_write_fallback_specs_count_excludes_hides(monkeypatch):
    import obed_edom.offline_write as ow_mod

    hide = _spec(slide=1, kind="image", kindIndex=0, role="hide")
    missed = _spec(slide=1, kind="image", kindIndex=1, role="map", x=1, y=1, w=1, h=1)
    monkeypatch.setattr(ow_mod, "_patch_offline_slides", lambda *a, **k: {1: _result(missed_specs=[missed])})
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [hide, missed], {}, [], lambda m: None
    )
    assert info["fallbackSpecs"] == {"1": 1}
    assert info["missedSpecs"] == 1


def test_run_offline_write_fallback_specs_keys_are_strings_and_record_round_trips(
    monkeypatch, tmp_path
):
    # Regression: fallback_by_slide is int-keyed internally (needed by _fallback_bodies'
    # AppleScript addressing); a record built from it must round-trip through JSON, which
    # requires str keys in fallbackSpecs (see write_run_record's round-trip self-check).
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(refused=True, reason="x", applied=0, value_clean=False)},
    )
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [_spec(slide=1, kindIndex=0)], {}, [], lambda m: None
    )
    assert info["fallbackSpecs"] == {"1": 1}

    record = run_record(**_record(offline_write=info))
    path = write_run_record(tmp_path / "A.run.json", record)  # raises on round-trip mismatch
    assert json.loads(path.read_text())["offlineWrite"]["fallbackSpecs"] == {"1": 1}


def test_run_offline_write_refused_slide_fallback_specs_count_excludes_hides(monkeypatch):
    # A refused slide falls back WHOLE (specs_by_slide[n], hides included); fallbackSpecs
    # must still count only the specs the fallback script actually writes.
    import obed_edom.offline_write as ow_mod

    monkeypatch.setattr(
        ow_mod, "_patch_offline_slides",
        lambda *a, **k: {1: _result(refused=True, reason="x", applied=0, value_clean=False)},
    )
    monkeypatch.setattr(ow_mod, "_run_fallback_scripts", lambda dest, scripts, say: (True, [], []))
    hide = _spec(slide=1, kindIndex=0, role="hide")
    spec = _spec(slide=1, kindIndex=1)
    info = run_offline_write(
        Path("/tmp/x.key"), "on", {1}, [hide, spec], {}, [], lambda m: None
    )
    assert info["fallbackSpecs"] == {"1": 1}


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
    assert report["per_kind"]["shape"]["worstUpperBound"] == 0.2

    # fix 4: without object ids, positional pairing can never be proven correct, so an
    # over-tolerance delta is reported as an upper bound and never fails the bucket or
    # the overall report.
    b_bad = [_unit("shape", 5, 0, 100, 50), _unit("image", 10, 10, 20, 20)]
    report_bad = compare_units_multiset(a, b_bad, tol_hard=0.5, tol_soft=1.0)
    assert report_bad["pass"] is True
    assert report_bad["per_kind"]["shape"]["pass"] is True
    assert report_bad["per_kind"]["shape"]["worstUpperBound"] == 5.0
    assert report_bad["per_kind"]["shape"]["reasons"]

    # a count mismatch still fails outright, regardless of tolerance -- order-independent
    # and immune to zip truncation, it is the only thing that still gates here.
    b_short = [_unit("shape", 0, 0, 100, 50)]
    report_count = compare_units_multiset(a, b_short, tol_hard=0.5, tol_soft=1.0)
    assert report_count["pass"] is False
    assert "count" in report_count["per_kind"]["image"]["reasons"][0]


def test_compare_units_multiset_tightly_packed_shape_reports_bound_not_failure():
    # Pins the slide-144 shape: many units sharing a constant leading key (x), packed at
    # sub-tolerance y-gaps (0.3px, tol=1.0px), with an INDEPENDENT per-unit y
    # perturbation (+-3px, alternating sign) between arms -- on the order of the plan's
    # own measured "+-3px reorders 68 of 68" perturbation. Positional pairing has no way
    # to prove this delta is real rather than a crossed pairing, so it must be reported
    # as an upper bound, never a failure.
    def _u(y):
        return _unit("shape", 16.0, y, 10, 10)

    a = [_u(0.0), _u(0.3), _u(0.6), _u(0.9), _u(1.2)]
    perturb = [3.0, -3.0, 3.0, -3.0, 3.0]
    b = [_u(y + dy) for y, dy in zip((0.0, 0.3, 0.6, 0.9, 1.2), perturb)]
    report = compare_units_multiset(a, b, tol_hard=1.0, tol_soft=1.0)
    entry = report["per_kind"]["shape"]
    assert report["pass"] is True
    assert entry["pass"] is True
    assert entry["informational"] is True


def test_compare_units_multiset_opposite_axis_certification_does_not_false_fail():
    # Regression for the round-3 defect: fix 3's per-arm separation on the first
    # differing ROUNDED sort-key component let each arm certify pairing safety on a
    # DIFFERENT axis -- arm A resolvable on x (gap 1.1), arm B resolvable on y (gap 2.0)
    # -- giving opposite sort orders and a fabricated worst=2.0px, while the true
    # identity-paired deltas are only 0.5px and 0.6px. Fix 4 deletes the whole predicate:
    # every paired delta, including this one, is now an upper bound that never fails.
    def _u(x, y):
        return _unit("shape", x, y, 10, 10)

    a = [_u(0.0, 1.0), _u(1.1, -1.0)]
    b = [_u(0.5, 1.0), _u(0.5, -1.0)]
    report = compare_units_multiset(a, b, tol_hard=1.0, tol_soft=1.0)
    entry = report["per_kind"]["shape"]
    assert report["pass"] is True
    assert entry["pass"] is True
    assert entry["worstUpperBound"] == pytest.approx(2.0)
    assert entry["reasons"]


def test_compare_units_multiset_text_is_informational():
    a = [_unit("text", 0, 0, 10, 10)]
    b = [_unit("text", 50, 0, 10, 10)]  # far off in x
    report = compare_units_multiset(a, b, tol_hard=0.5, tol_soft=1.0)
    assert report["pass"] is True  # text never gates
    assert report["per_kind"]["text"]["informational"] is True
    assert report["per_kind"]["text"]["worstUpperBound"] == 50.0


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
            "text": {"n_a": 1, "n_b": 1, "pass": True, "worstUpperBound": 5.0,
                      "reasons": [], "informational": True},
        }
    }
    _log_multiset_report(report)
    out = capsys.readouterr().out
    assert "text: informational only — UNVERIFIED by this gate" in out


# --- flag off: byte-for-byte parity with the pre-W1 plan (BLOCKER item 8) --------


def test_flag_off_builds_the_same_plan_as_today_pure(monkeypatch):
    """Pure-function lock (kept alongside the full remap_keynote() lock below): the exact
    computation the plan-building hook performs when the flag is off.

    SAFETY: OBED_OFFLINE_WRITE is set EXPLICITLY (not delenv'd) -- the ambient default
    is "on" since the W1 flip (2026-09-14), and relying on delenv here would make this test's `remap_keynote()` sibling below silently take the
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
    offline_slides = set() if mode == "off" else _offline_write_slides(transform_dicts, None)
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
    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: _stub_plan(transforms=transforms))
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
        return {"applied": 1, "missed": 0, "saved": True, "closed": True}

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

    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: _stub_plan())
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
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0, "saved": True, "closed": True})

    monkeypatch.setattr(iwa_mod, "_load_deck", lambda _p: ({}, {}, {}))
    monkeypatch.setattr(iwa_mod, "attach_group_child_text", lambda *a, **k: None)
    monkeypatch.setattr(iwa_mod, "attach_group_captions", lambda *a, **k: None)
    # attach_slide_builds re-reads the raw zip for image identity (deck_builds); the
    # fixture's `source` is a 0-byte stand-in, not a real .key, so it must be mocked too.
    monkeypatch.setattr(iwa_mod, "attach_slide_builds", lambda *a, **k: None)
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

    calls.clear()
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload={**wall_payload, "reader": "jxa"}, template_payload=template_payload,
        offline_read="on", log=lambda m: None,
    )
    assert calls == []

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload={**wall_payload, "reader": "offline"}, template_payload=template_payload,
        offline_read="off", log=lambda m: None,
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


def test_remap_and_inspect_remaps_zorder_patched_slides_in_live_verify(monkeypatch, tmp_path):
    """W2 zorder-bridge Piece 1 (inverse of the old exclusion test): the offline z-order
    patch's `kindIndexMap` now lets `remap_and_inspect` positionally verify its target
    slides via `kindindex_remap`, instead of excluding them from live verify wholesale."""
    import obed_edom.remap_keynote as rk

    offline_info = {
        "mode": "verify",
        "specs": {
            1: [_spec(slide=1, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)],
            2: [_spec(slide=2, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10)],
        },
        "statSlides": [],
    }

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        return {
            "dest": str(dest), "applied": 1, "offlineWrite": offline_info,
            "zorderWrite": {"slides": [1], "kindIndexMap": {"1": {"shape": {"0": 1}}}},
        }

    def fake_inspect(dest, *, export_dir=None, slide_range=None, use_cache=None, **kwargs):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 2,
            "slides": [
                {"number": 1, "items": [
                    {"kind": "shape", "kindIndex": 1, "x": 0, "y": 0, "w": 10, "h": 10},
                ]},
                {"number": 2, "items": [
                    {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                ]},
            ],
        }

    captured = {}
    real_verify_live_frames = offline_write.verify_live_frames

    def spy_verify_live_frames(planned, payload, *, kindindex_remap=None, multiset_kinds_by_slide=None):
        captured["kindindex_remap"] = kindindex_remap
        return real_verify_live_frames(
            planned, payload,
            kindindex_remap=kindindex_remap, multiset_kinds_by_slide=multiset_kinds_by_slide,
        )

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(offline_write, "verify_live_frames", spy_verify_live_frames)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    assert captured["kindindex_remap"] == {1: {"shape": {0: 1}}}
    assert info["offlineWrite"]["liveVerifyPass"] is True


def test_remap_and_inspect_sets_live_verify_set_pass_for_stat_slide_group(monkeypatch, tmp_path):
    """W2 zorder-bridge Piece 2: a stat-finalize slide's `group` kind is routed to the
    multiset bar and lands on `liveVerifySetPass`, alongside (not instead of)
    `liveVerifyPass` for the slide's other kinds."""
    import obed_edom.remap_keynote as rk

    offline_info = {
        "mode": "verify",
        "specs": {
            5: [
                _spec(slide=5, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10),
                _spec(slide=5, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            ],
        },
        "statSlides": [5],
    }

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        return {"dest": str(dest), "applied": 1, "offlineWrite": offline_info}

    def fake_inspect(dest, *, export_dir=None, slide_range=None, use_cache=None, **kwargs):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 1,
            "slides": [{"number": 5, "items": [
                {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
            ]}],
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    ow = info["offlineWrite"]
    assert ow["liveVerifyPass"] is True
    assert ow["liveVerifySetPass"] is True
    assert ow["liveVerifyCoverage"]["uncovered"] == []
    assert ow["liveVerifyCoverage"]["setSlides"] == [5]


def test_remap_and_inspect_not_gates_stat_group_bucket_with_fallback_spec(monkeypatch, tmp_path):
    """Defect B: a stat slide's `group` bucket that had ANY spec routed to the
    AppleScript fallback must be excluded from the set bar's gate entirely -- even a
    genuine mismatch on that bucket must not fail the run. It stays visible as
    `notGated`, not `uncovered` (which would red the gate) and not a gated `setSlides`
    bucket."""
    import obed_edom.remap_keynote as rk

    offline_info = {
        "mode": "verify",
        "specs": {
            5: [
                _spec(slide=5, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10),
                _spec(slide=5, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            ],
        },
        "statSlides": [5],
        "fallbackKinds": {"5": ["group"]},
    }

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        return {"dest": str(dest), "applied": 1, "offlineWrite": offline_info}

    def fake_inspect(dest, *, export_dir=None, slide_range=None, use_cache=None, **kwargs):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 1,
            "slides": [{"number": 5, "items": [
                {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                # Genuine mismatch on the group bucket -- would FAIL the set bar if gated.
                {"kind": "group", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
            ]}],
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    ow = info["offlineWrite"]
    assert ow["liveVerifyPass"] is True
    assert ow["liveVerifySetPass"] is True
    assert ow["liveVerifyCoverage"]["uncovered"] == []
    assert ow["liveVerifyCoverage"]["setSlides"] == []
    assert ow["liveVerifyCoverage"]["notGatedSlides"] == [5]
    assert ow["liveVerifyCoverage"]["notGatedBuckets"] == 1


def test_remap_and_inspect_still_gates_stat_group_bucket_without_fallback_spec(monkeypatch, tmp_path):
    """Regression: absent any fallback spec on the slide's `group` kind, the set bar
    still gates it -- a genuine mismatch on the bucket must FAIL the run, exactly as
    before Defect B's fix."""
    import obed_edom.remap_keynote as rk

    offline_info = {
        "mode": "verify",
        "specs": {
            5: [
                _spec(slide=5, kind="shape", kindIndex=0, x=0, y=0, w=10, h=10),
                _spec(slide=5, kind="group", kindIndex=0, x=0, y=0, w=10, h=10),
            ],
        },
        "statSlides": [5],
    }

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        return {"dest": str(dest), "applied": 1, "offlineWrite": offline_info}

    def fake_inspect(dest, *, export_dir=None, slide_range=None, use_cache=None, **kwargs):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 1,
            "slides": [{"number": 5, "items": [
                {"kind": "shape", "kindIndex": 0, "x": 0, "y": 0, "w": 10, "h": 10},
                {"kind": "group", "kindIndex": 0, "x": 999, "y": 999, "w": 999, "h": 999},
            ]}],
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    ow = info["offlineWrite"]
    assert ow["liveVerifySetPass"] is False
    assert ow["liveVerifyCoverage"]["setSlides"] == [5]
    assert ow["liveVerifyCoverage"]["notGatedSlides"] == []


def test_remap_and_inspect_reds_gate_when_coverage_reports_uncovered(monkeypatch, tmp_path):
    """A non-empty `uncovered` (a routing-table wiring bug between the two live-verify
    calls) must RED `liveVerifyPass` even when both bars individually PASS."""
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

    def fake_coverage(planned, kindindex_remap, multiset_kinds_by_slide, not_gated_kinds_by_slide=None):
        return {
            "positionalSlides": [], "remappedSlides": [], "setSlides": [],
            "groupBuckets": 0, "notGatedSlides": [], "notGatedBuckets": 0,
            "uncovered": [(1, "shape")], "totalSlides": 1,
            "coveredSlides": 0,
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(offline_write, "live_verify_coverage", fake_coverage)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )
    assert info["offlineWrite"]["liveVerifyPass"] is False


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


def test_summary_gate_reasons_flags_live_verify_set_fail():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": True, "liveVerifyPass": True, "liveVerifySetPass": False}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("live verify (set)" in r for r in reasons)


def test_summary_gate_reasons_flags_uncovered_pairs():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": True, "liveVerifyPass": True, "liveVerifySetPass": True,
          "liveVerifyCoverage": {"uncovered": [[3, "group"]]}}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("uncovered" in r for r in reasons)


def test_summary_gate_reasons_v3_record_missing_set_pass_and_coverage_is_not_a_fail():
    # GATE_VERSION 3->4 (W2 zorder-bridge Piece 2): a reused v3 record has neither
    # `liveVerifySetPass` nor `liveVerifyCoverage` -- absence must read as "not
    # measured", never as a red, exactly like the older liveVerifyPass/offlineVerifyPass
    # absence case above.
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 0, "softFallbacks": 0, "valueClean": True,
          "offlineVerifyPass": True, "liveVerifyPass": True}
    assert summary_gate_reasons(ow, applied_a=5, applied_b=5) == []


def test_summary_gate_reasons_downgrades_fully_covered_missed_specs_to_non_gating():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 3, "softFallbacks": 0, "valueClean": True,
          "fallbackSpecs": {"5": 3}, "fallbackUnwritable": 0}
    assert summary_gate_reasons(ow, applied_a=5, applied_b=5) == []


def test_summary_gate_reasons_reds_missed_specs_not_fully_covered():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 3, "softFallbacks": 0, "valueClean": True,
          "fallbackSpecs": {"5": 1}, "fallbackUnwritable": 0}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("did not fully cover" in r and "fallback_specs=1" in r for r in reasons)


def test_summary_gate_reasons_reds_on_fallback_unwritable():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 3, "softFallbacks": 0, "valueClean": True,
          "fallbackSpecs": {"5": 3}, "fallbackUnwritable": 1}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("unwritable=1" in r for r in reasons)


def test_summary_gate_reasons_missed_specs_absent_fallback_keys_still_red():
    from scripts.offline_write_ab import summary_gate_reasons

    ow = {"refused": [], "missedSpecs": 3, "softFallbacks": 0, "valueClean": True}
    reasons = summary_gate_reasons(ow, applied_a=5, applied_b=5)
    assert any("missed the offline patch" in r for r in reasons)


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


# --- pass2_health (D4) --------------------------------------------------------------


def _pass2(**over):
    base = dict(ok=True, jobs=2, done=2, skipped=0, sized=2, sizeSkips=0,
                dedupDeleted=0, dedupShortfall=0, sigFallback=0, unresolved=0, raw="")
    base.update(over)
    return base


def test_pass2_health_green():
    assert pass2_health(_pass2(), label="A") == []


def test_pass2_health_none_result_is_healthy():
    # `childResize is None` (no stat/badge jobs planned) is healthy (D4).
    assert pass2_health(None, label="A") == []


def test_pass2_health_noop_skipped_bool_form_is_healthy():
    # `_run_stat_finalize`'s no-op return: `skipped` is a BOOL sentinel here, not the
    # per-job skip COUNT the rest of this function reads as an int -- must short-circuit
    # before the count checks would otherwise misread `True` as `1`.
    noop = {"ok": True, "skipped": True, "done": 0, "jobs": 0, "exported": False}
    assert pass2_health(noop, label="A") == []


def test_pass2_health_not_ok():
    reasons = pass2_health(_pass2(ok=False), label="A")
    assert any("ok=False" in r for r in reasons)


def test_pass2_health_zero_keys():
    reasons = pass2_health(_pass2(unresolved=1, dedupShortfall=2), label="A")
    assert len(reasons) == 2


def test_pass2_health_fallback_keys_are_warn_only():
    # sigFallback non-zero must NOT gate (D4: WARN only).
    reasons = pass2_health(_pass2(sigFallback=3), label="A")
    assert reasons == []


def test_pass2_health_done_plus_skipped_must_equal_jobs():
    reasons = pass2_health(_pass2(jobs=5, done=2, skipped=2), label="A")
    assert any("!= jobs" in r for r in reasons)


# --- pass2_health: --pass2-bar strict (default) vs parity --------------------------


def test_pass2_health_strict_flags_zero_keys():
    # zero_keys_hard defaults True -- unchanged behavior, matches --pass2-bar strict.
    reasons = pass2_health(
        _pass2(unresolved=1, dedupShortfall=2), label="A", zero_keys_hard=True,
    )
    assert len(reasons) == 2


def test_pass2_health_parity_does_not_flag_zero_keys():
    reasons = pass2_health(
        _pass2(unresolved=134, dedupShortfall=6), label="A", zero_keys_hard=False,
    )
    assert reasons == []


def test_pass2_health_parity_still_flags_ok_and_done_skipped():
    assert any("ok=False" in r for r in
               pass2_health(_pass2(ok=False), label="A", zero_keys_hard=False))
    assert any("!= jobs" in r for r in
               pass2_health(_pass2(jobs=5, done=2, skipped=2), label="A", zero_keys_hard=False))


# --- pass2_parity (D4) --------------------------------------------------------------


def test_pass2_parity_green():
    assert pass2_parity(_pass2(), _pass2()) == []


def test_pass2_parity_flags_each_key():
    for key in ("jobs", "done", "skipped", "sized", "sizeSkips", "dedupDeleted",
                "dedupShortfall", "sigFallback", "unresolved"):
        b = _pass2(**{key: 99})
        reasons = pass2_parity(_pass2(), b)
        assert any(key in r for r in reasons), key


def test_pass2_parity_ignores_raw():
    a = _pass2(raw="AAA some detail")
    b = _pass2(raw="BBB totally different detail")
    assert pass2_parity(a, b) == []


def test_pass2_parity_handles_none():
    assert pass2_parity(None, None) == []


# --- pass2_bar_line / pass2_zero_warn (item 3: false "tolerated because A==B") -------


def test_pass2_bar_line_strict():
    assert pass2_bar_line(zero_keys_hard=True, parity=[], a=None, b=None) == "pass-2 bar: strict"


def test_pass2_bar_line_parity_tolerated_when_equal():
    line = pass2_bar_line(zero_keys_hard=False, parity=[],
                          a=_pass2(unresolved=0), b=_pass2(unresolved=0))
    assert "tolerated because A==B" in line


def test_pass2_bar_line_parity_not_tolerated_when_a_differs_from_b():
    # Regression, the banked 2026-09-07 run: `parity` carries the seven real A!=B
    # reasons, and A's unresolved/dedupShortfall are non-zero while B's are clean --
    # the summary line must never claim "tolerated because A==B" underneath that.
    parity = [f"pass-2 key{i}: A=x != B=y" for i in range(7)]
    line = pass2_bar_line(
        zero_keys_hard=False, parity=parity,
        a={"unresolved": 67, "dedupShortfall": 141}, b={"unresolved": 0, "dedupShortfall": 0},
    )
    assert "tolerated" not in line
    assert "7 key(s)" in line
    assert "A=67 B=0" in line
    assert "A=141 B=0" in line


def test_pass2_bar_line_reports_both_arms():
    # The old code read child_resize_a's counters only; both arms must appear now.
    # Distinct A/B values so a `f"A={ua} B={ua}"` regression (reading A twice) fails.
    line = pass2_bar_line(zero_keys_hard=False, parity=[],
                          a=_pass2(unresolved=3), b=_pass2(unresolved=5))
    assert "A=3 B=5" in line


def test_pass2_zero_warn_not_tolerated_when_parity_nonempty():
    warn = pass2_zero_warn("A", _pass2(unresolved=67, dedupShortfall=141), tolerated=False)
    assert "tolerated because A==B" not in warn
    assert "NOT tolerated" in warn
    assert "unresolved=67" in warn


def test_pass2_zero_warn_empty_when_all_zero():
    assert pass2_zero_warn("A", _pass2(), tolerated=True) == ""
    assert pass2_zero_warn("A", _pass2(), tolerated=False) == ""


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


# --- card_border_damage_reasons / card_border_refs (item 4) ---------------------------


def test_card_border_damage_reasons_clean_arm():
    # Arm B, banked (2026-09-07 Full bank): output refs == source refs.
    assert card_border_damage_reasons("B", 83, 83, None) == []


def test_card_border_damage_reasons_hard_fails_on_card_loss():
    # Regression, banked numbers (2026-09-07 Full bank arm A: 43 vs source 83).
    reasons = card_border_damage_reasons("A", 43, 83, {"dedupShortfall": 141, "unresolved": 67})
    assert len(reasons) == 1
    r = reasons[0]
    assert "43" in r
    assert "83" in r
    assert "dedupShortfall=141" in r
    assert "unresolved=67" in r
    assert "MISSING card images" in r
    assert "does NOT establish a cause" in r
    assert "f76e8d3" in r
    assert "FATAL reuse slide" in r
    assert "census cards per slide" in r


def test_card_border_damage_reasons_carries_no_disproven_advice():
    # D1 attributed the 43-vs-83 shortfall to a stolen GUI focus/clipboard interaction and
    # told the operator to re-run on an untouched machine and not debug the code. D6
    # disproved that (a second run on a verified-untouched machine reproduced 43 refs and
    # character-identical stat-finalize integers) and f76e8d3 fixed the real load-sensitive
    # applyReuse paste defect. Neither branch of this message may carry that advice again.
    shortfall = card_border_damage_reasons("A", 43, 83, None)
    ambiguous = card_border_damage_reasons("A", None, 83, None)
    for r in shortfall + ambiguous:
        assert "stolen" not in r.lower()
        assert "untouched machine" not in r
        assert "do NOT debug the code first" not in r
        assert "known cause" not in r


def test_card_border_damage_reasons_tolerates_borderline_shortfall():
    # 70/83 = 0.843 >= CARD_REF_FLOOR (0.75) — the false-positive guard.
    assert CARD_REF_FLOOR == 0.75
    assert card_border_damage_reasons("A", 70, 83, None) == []


def test_card_border_damage_reasons_not_applicable_without_card_style():
    # No unambiguous card-border style in the SOURCE — the check cannot apply.
    assert card_border_damage_reasons("A", 43, None, None) == []


def test_card_border_damage_reasons_output_lost_its_card_style():
    # N2: an ambiguous OUTPUT style is not a measured shortfall -- no fabricated ratio,
    # and the remedy must not blame the machine (a surplus of stranded donor copies
    # lands here too, and a surplus must never be told "re-run on an untouched machine").
    reasons = card_border_damage_reasons("A", None, 83, None)
    assert len(reasons) == 1
    r = reasons[0]
    assert "83" in r
    assert "no longer carries an unambiguous card-border style" in r
    assert "ratio" not in r
    assert "0.000" not in r
    assert "re-run this arm on an untouched machine" not in r
    assert "inspect the deck's media styles" in r
    assert "stolen" not in r.lower()


def test_card_border_damage_reasons_surplus_is_not_hard():
    # A surplus (stranded donor copies) is a dedup shortfall, not this hard fail.
    assert card_border_damage_reasons("B", 120, 83, None) == []


def test_card_border_refs_single_style(monkeypatch):
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck",
                        lambda deck: ({}, {}, {}), raising=False)
    monkeypatch.setattr(
        "obed_edom.iwa_write.card_styles",
        lambda objects, id_to_file: [
            {"id": "m1", "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern",
             "refs": 83, "inherited": False},
        ],
        raising=False,
    )
    assert card_border_refs(Path("/tmp/x.key")) == 83


def test_card_border_refs_none_when_ambiguous(monkeypatch):
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck",
                        lambda deck: ({}, {}, {}), raising=False)
    monkeypatch.setattr(
        "obed_edom.iwa_write.card_styles",
        lambda objects, id_to_file: [
            {"id": "m1", "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern",
             "refs": 83, "inherited": False},
            {"id": "m2", "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern",
             "refs": 50, "inherited": False},
        ],
        raising=False,
    )
    assert card_border_refs(Path("/tmp/x.key")) is None


# --- damage_check_line (N1) -----------------------------------------------------------


def test_damage_check_line_ok_reports_both_counts():
    line = damage_check_line("A", src_ok=True, refs_ok=True, src_refs=83, out_refs=83, damage=[])
    assert line == "A damage check: OK (83 vs source 83 card-border refs)."


def test_damage_check_line_not_applicable_when_source_ambiguous():
    line = damage_check_line("A", src_ok=True, refs_ok=True, src_refs=None, out_refs=43, damage=[])
    assert line == "A damage check: NOT APPLICABLE (source has no unambiguous card-border style)."


def test_damage_check_line_skipped_on_read_failure():
    line = damage_check_line("B", src_ok=False, refs_ok=True, src_refs=None, out_refs=None, damage=[])
    assert "SKIPPED" in line
    assert "read failed" in line


def test_damage_check_line_empty_when_damage_present():
    # The RED reason line(s) already say it -- no redundant status line on top.
    line = damage_check_line("A", src_ok=True, refs_ok=True, src_refs=83, out_refs=43,
                             damage=["A: card-border refs 43 vs source 83 ..."])
    assert line == ""


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
    assert report == {"pass": True, "per_kind": {}, "missing_ids": [], "skipped": 0,
                       "compared": 0, "approx": []}


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


def test_plan_oracle_slide_skips_group_with_needs_keynote():
    # Regression, banked numbers (slide 35 ki0, 2026-09-07 Full bank arm A).
    specs = [{"slide": 35, "kind": "group", "kindIndex": 0,
              "x": 960.0, "y": 212.55, "w": 3549.09, "h": 605.70}]
    id_by_addr = {("group", 0): "g35"}
    recs_by_id = {"g35": {"id": "g35", "kind": "group", "kindIndex": 0,
                          "x": 961.43, "y": 292.31, "w": 1764.48, "h": 496.51,
                          "geom_source": "group-union", "needs_keynote": "group-residual"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["per_kind"] == {}
    assert report["pass"] is True
    assert report["skipped"] == 1
    assert report["compared"] == 0
    assert len(report["approx"]) == 1
    assert report["approx"][0]["worst"] == pytest.approx(1784.61, abs=0.01)
    assert report["approx"][0]["needs"] == ["output:group-residual"]


def test_plan_oracle_slide_group_flagged_on_source_only_routes_to_approx():
    # The writer refuses this spec from the SOURCE record (iwa_write._slide_edits),
    # and the write itself erases the flag -- the OUTPUT record composes clean. The
    # oracle must still treat it as not comparable, from the source side.
    specs = [{"slide": 124, "kind": "group", "kindIndex": 0,
              "x": 16.0, "y": 175.0, "w": 332.47, "h": 232.0}]
    id_by_addr = {("group", 0): "g124"}
    recs_by_id = {"g124": {"id": "g124", "kind": "group", "kindIndex": 0,
                           "x": 16.0, "y": 175.0, "w": 565.91, "h": 232.0,
                           "geom_source": "group-union"}}
    src_recs_by_id = {"g124": {"id": "g124", "kind": "group", "kindIndex": 0,
                               "x": 16.0, "y": 175.0, "w": 200.0, "h": 232.0,
                               "geom_source": "group-union", "needs_keynote": "group-residual"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(),
                                src_recs_by_id=src_recs_by_id)
    assert report["per_kind"] == {}
    assert report["pass"] is True
    assert report["skipped"] == 1
    assert report["compared"] == 0
    assert len(report["approx"]) == 1
    assert report["approx"][0]["needs"] == ["source:group-residual"]


def test_plan_oracle_slide_group_flagged_on_both_sides_tags_both():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0,
              "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                        "needs_keynote": "rotated-group"}}
    src_recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                             "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                             "needs_keynote": "group-residual"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(),
                                src_recs_by_id=src_recs_by_id)
    assert report["approx"][0]["needs"] == ["source:group-residual", "output:rotated-group"]


def test_plan_oracle_slide_group_flagged_on_neither_side_still_gates():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 5.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    src_recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                             "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                             "needs_keynote": None}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0),
                                src_recs_by_id=src_recs_by_id)
    assert report["pass"] is False
    assert report["approx"] == []


def test_plan_oracle_slide_group_without_needs_flag_still_gates():
    # The flagged skip must not become a blanket group exemption.
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 5.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                        "needs_keynote": None}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0))
    assert report["pass"] is False
    assert report["approx"] == []


def test_plan_oracle_slide_group_missing_from_source_map_is_red_not_pass():
    # src_recs_by_id supplied but the id is absent -- a decode-skipped source slide/
    # member must never fall back to an ordinary compare.
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                        "needs_keynote": None}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(),
                                src_recs_by_id={})
    assert report["pass"] is False
    assert report["missing_ids"] == [{"addr": ("group", 0), "id": "g1",
                                       "reason": "source record missing for (group, 0)"}]
    assert report["compared"] == 0
    assert report["approx"] == []


def test_w2_oracle_kwargs_neither_arm_gets_aspects():
    kwargs_a, kwargs_b = w2_oracle_kwargs({"g1": {"id": "g1"}})
    assert "aspects" not in kwargs_a
    assert "aspects" not in kwargs_b
    assert kwargs_a == kwargs_b == {"src_recs_by_id": {"g1": {"id": "g1"}}}


def test_plan_oracle_slide_group_missing_from_source_map_unaffected_when_map_none():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                        "needs_keynote": None}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["pass"] is True
    assert report["missing_ids"] == []
    assert report["compared"] == 1


def test_plan_oracle_slide_approx_is_not_counted_as_compared():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union",
                        "needs_keynote": "rotated-group"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["compared"] == 0
    assert report["skipped"] == 1


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


def test_plan_oracle_slide_skips_line_kind():
    # A line spec's x/y is an ordinary bbox, a composed line's is `_line_rect`'s anchor
    # (offline_write._spec_box) — not a comparable pair, so line is skipped outright.
    specs = [{"slide": 1, "kind": "line", "kindIndex": 0, "x": 10.0, "y": 20.0, "w": 999.0, "h": 999.0}]
    id_by_addr = {("line", 0): "l1"}
    recs_by_id = {"l1": {"id": "l1", "kind": "line", "kindIndex": 0,
                        "x": 10.0, "y": 20.0, "w": 5.0, "h": 5.0, "geom_source": "line"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report["per_kind"] == {}
    assert report["pass"] is True
    assert report["skipped"] == 1
    assert report["compared"] == 0


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


def test_log_plan_oracle_report_prints_approx_line(capsys):
    from scripts.offline_write_ab import _log_plan_oracle_report

    report = {"pass": True, "per_kind": {}, "missing_ids": [], "skipped": 1, "compared": 0,
              "approx": [{"addr": ("group", 0), "id": "g35", "needs": "group-residual",
                         "worst": 1784.61}]}
    _log_plan_oracle_report("A", report)
    out = capsys.readouterr().out
    assert "group-approx" in out
    assert "n=1" in out
    assert "1784.61" in out
    assert "NOT GATED" in out


def test_plan_oracle_aspect_predicts_keynote_rounded_width():
    ar = 2.9014084507042255
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 10.0, "y": 20.0, "w": 999.0, "h": 71.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 10.0, "y": 20.0, "w": round(71.0) * ar, "h": 71.0,
                        "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"g1": ar})
    assert report["pass"] is True
    report_no_aspects = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances())
    assert report_no_aspects["pass"] is False


def test_plan_oracle_aspect_bar_is_quarter_pixel():
    ar = 2.0
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 999.0, "h": 20.0}]
    id_by_addr = {("image", 0): "i1"}
    recs_by_id = {"i1": {"id": "i1", "kind": "image", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 40.3, "h": 20.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"i1": ar})
    assert report["pass"] is False
    recs_by_id["i1"]["w"] = 40.2
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"i1": ar})
    assert report["pass"] is True


def test_plan_oracle_aspect_accepts_stretched_integer_width():
    ar = 3.7433
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 374.33, "h": 100.0}]
    id_by_addr = {("image", 0): "i1"}
    recs_by_id = {"i1": {"id": "i1", "kind": "image", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 374.0, "h": 100.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"i1": ar})
    assert report["pass"] is True


def test_plan_oracle_aspect_still_accepts_float_lock_width():
    ar = 1.339245
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 1268.26, "h": 947.0}]
    id_by_addr = {("image", 0): "i1"}
    recs_by_id = {"i1": {"id": "i1", "kind": "image", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 947.0 * ar, "h": 947.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"i1": ar})
    assert report["pass"] is True


def test_plan_oracle_aspect_rejects_width_matching_neither():
    ar = 3.7433
    specs = [{"slide": 1, "kind": "image", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 374.33, "h": 100.0}]
    id_by_addr = {("image", 0): "i1"}
    recs_by_id = {"i1": {"id": "i1", "kind": "image", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 373.6, "h": 100.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"i1": ar})
    assert report["pass"] is False
    assert report["per_kind"]["image"]["worst"] == pytest.approx(0.4)


def test_plan_oracle_stretched_integer_width_ignored_for_shape():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 374.33, "h": 100.0}]
    id_by_addr = {("shape", 0): "s1"}
    recs_by_id = {"s1": {"id": "s1", "kind": "shape", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 374.0, "h": 100.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(hard=0.5), aspects={"s1": 3.7433})
    assert report["pass"] is True
    assert report["per_kind"]["shape"]["worst"] == pytest.approx(0.33)


def test_plan_oracle_without_aspects_is_unchanged():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 5.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0))
    assert report["per_kind"]["group"]["worst"] == 5.0
    assert report["pass"] is False


def test_plan_oracle_aspect_ignored_for_shape():
    specs = [{"slide": 1, "kind": "shape", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]
    id_by_addr = {("shape", 0): "s1"}
    recs_by_id = {"s1": {"id": "s1", "kind": "shape", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.6, "h": 10.0, "geom_source": "iwa"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(hard=0.5), aspects={"s1": 1.0})
    assert report["pass"] is False
    assert report["per_kind"]["shape"]["worst"] == pytest.approx(0.6)


def test_plan_oracle_missing_aspect_falls_back_to_soft():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 10.6, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0), aspects={})
    assert report["pass"] is True
    assert report["per_kind"]["group"]["worst"] == pytest.approx(0.6)


def test_plan_oracle_aspect_still_red_on_gross_miss():
    specs = [{"slide": 36, "kind": "group", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}]
    id_by_addr = {("group", 0): "g36"}
    recs_by_id = {"g36": {"id": "g36", "kind": "group", "kindIndex": 0,
                         "x": 0.0, "y": 90.0, "w": 100.0, "h": 100.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(), aspects={"g36": 1.0})
    assert report["pass"] is False
    assert report["per_kind"]["group"]["worst"] == 90.0


def test_plan_oracle_child_written_group_keeps_soft_compare():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "children": [{"kind": "image"}],
              "x": 0.0, "y": 0.0, "w": 10.6, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0), aspects={"g1": 1.0})
    assert report["pass"] is True
    assert report["per_kind"]["group"]["worst"] == pytest.approx(0.6)


def test_plan_oracle_childless_group_still_aspect_aware():
    specs = [{"slide": 1, "kind": "group", "kindIndex": 0, "children": [],
              "x": 0.0, "y": 0.0, "w": 10.6, "h": 10.0}]
    id_by_addr = {("group", 0): "g1"}
    recs_by_id = {"g1": {"id": "g1", "kind": "group", "kindIndex": 0,
                        "x": 0.0, "y": 0.0, "w": 15.0, "h": 10.0, "geom_source": "group-union"}}
    report = plan_oracle_slide(specs, id_by_addr, recs_by_id, Tolerances(soft=1.0), aspects={"g1": 1.5})
    assert report["pass"] is True
    assert report["per_kind"]["group"]["worst"] == pytest.approx(0.0)


def test_source_aspects_filters_masked_media(monkeypatch):
    objects = {"s1": {"kind": "slide"}}
    monkeypatch.setattr("obed_edom.iwa_runs._load_deck", lambda deck: (objects, {}, {}), raising=False)
    monkeypatch.setattr("obed_edom.iwa_runs.slide_order", lambda objs: [("s1", False)], raising=False)
    monkeypatch.setattr(
        "obed_edom.iwa_geometry.compose_geometry",
        lambda slide, objs: [
            {"id": "visible", "w": 100.0, "h": 50.0, "geom_source": "iwa"},
            {"id": "masked", "w": 100.0, "h": 50.0, "geom_source": "mask"},
        ],
        raising=False,
    )
    assert source_aspects(Path("/tmp/x.key")) == {"visible": 2.0}


# --- run_record / write_run_record / load_run_record (D13) ---------------------------


def _record(**over):
    base = dict(
        commit="abc123", deck_digest="dA", source_digest="dS",
        plan={"transforms": [{"slide": 1}], "reuses": [], "suppressGeometry": [],
             "statJobs": [{"slide": 3}], "badgeRaises": []},
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
                                        "asGeom": {"junk": True}, "statJobs": [],
                                        "badgeRaises": []}))
    assert set(record["plan"]) == {"transforms", "reuses", "suppressGeometry"}


def test_run_record_persists_stat_and_badge_job_lists():
    record = run_record(**_record(plan={"transforms": [], "reuses": [], "suppressGeometry": [],
                                        "statJobs": [{"slide": 3}], "badgeRaises": [{"slide": 5}]}))
    assert record["statJobs"] == [{"slide": 3}]
    assert record["badgeRaises"] == [{"slide": 5}]


def test_run_record_round_trips_preview_provenance(tmp_path):
    record = run_record(**_record(previews={"source": "/x/.cache/previews/abc", "placements": 90}))
    assert record["previews"] == {"source": "/x/.cache/previews/abc", "placements": 90}
    path = write_run_record(tmp_path / "A.run.json", record)  # raises on round-trip mismatch
    assert json.loads(path.read_text())["previews"] == record["previews"]


def test_run_record_previews_defaults_to_none():
    record = run_record(**_record())
    assert record["previews"] is None


def test_preview_provenance_warning_none_when_sources_match():
    a = run_record(**_record(previews={"source": "/cache/previews/x", "placements": 5}))
    b = run_record(**_record(previews={"source": "/cache/previews/x", "placements": 5}))
    assert preview_provenance_warning(a, b) is None


def test_preview_provenance_warning_fires_on_mismatched_source():
    a = run_record(**_record(previews={"source": None, "placements": 0}))
    b = run_record(**_record(previews={"source": "/cache/previews/x", "placements": 90}))
    warning = preview_provenance_warning(a, b)
    assert warning is not None
    assert "arm A planned with preview source None" in warning


def test_preview_provenance_warning_flags_older_record_missing_field():
    a = run_record(**_record())
    del a["previews"]
    b = run_record(**_record(previews={"source": "/cache/previews/x", "placements": 90}))
    assert preview_provenance_warning(a, b) == (
        "provenance unknown (older run record predates preview-cache provenance)."
    )


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


def test_load_run_record_accepts_compatible_v3_record(tmp_path, monkeypatch):
    # W2 zorder-bridge Piece 2: GATE_VERSION bumped 3->4 (COMPATIBLE_GATE_VERSIONS
    # {3, 4}) -- a v3 record (predates liveVerifySetPass/liveVerifyCoverage) is still
    # accepted; only v2 and older are refused now.
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="digestX", source_digest="digestX"))
    record["gateVersion"] = 3
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    loaded = load_run_record(path, deck=deck, source=source)
    assert loaded == record


def test_load_run_record_refuses_v2_record_now_incompatible(tmp_path, monkeypatch):
    # v2 was dropped from COMPATIBLE_GATE_VERSIONS when GATE_VERSION bumped 3->4.
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="digestX", source_digest="digestX"))
    record["gateVersion"] = 2
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="gateVersion"):
        load_run_record(path, deck=deck, source=source)


def test_load_run_record_refuses_unknown_gate_version(tmp_path, monkeypatch):
    deck = tmp_path / "d.key"
    deck.write_bytes(b"x")
    source = tmp_path / "s.key"
    monkeypatch.setattr("obed_edom.baseline.deck_digest", lambda p: "digestX")
    record = run_record(**_record(deck_digest="digestX"))
    record["gateVersion"] = 1
    path = tmp_path / "d.run.json"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="gateVersion"):
        load_run_record(path, deck=deck, source=source)


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

    def fake_plan_payload(wall, recipe, **kwargs):
        return _stub_plan(
            child_resize=[{"slide": 3, "captionPt": 24.0, "groupIndex": 1}],
            badge_raises=[{"slide": 5, "isTitle": True}],
        )

    monkeypatch.setattr(rk, "plan_payload", fake_plan_payload)
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
    jxa_plans: list[dict] = []

    def fake_run_jxa(plan):
        jxa_plans.append(plan)
        return {"applied": 1, "missed": 0, "saved": True, "closed": True}

    monkeypatch.setattr(rk, "_run_jxa", fake_run_jxa)
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
    assert plan_out["reuses"] == []
    assert len(jxa_plans) == 1
    assert jxa_plans[0]["reuses"] == []


def test_plan_out_collects_group_collapse_refused_from_a_non_other_transform(monkeypatch, tmp_path):
    """A pin-role group's groupCollapseRefused token lives only on the transform
    dict (map_remap.py's as_dict), never in a child_resize_report row (that row is
    gated on role=="other"). plan_out["groupCollapseRefused"] must still pick it up
    by scanning transform_dicts, not child_resize — otherwise a pin's collapse
    token never reaches the run record."""
    import obed_edom.remap_keynote as rk
    from obed_edom.map_remap import ItemTransform

    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)

    pin_transform = ItemTransform(
        slide_number=2, item_index=0, kind="group", x=0, y=0, w=10, h=10,
        kind_index=0, role="pin",
    )
    pin_transform.group_collapse_refused = "groupCollapseRefused(s=2,idx=1)"

    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: _stub_plan(transforms=[pin_transform]))
    monkeypatch.setattr(
        rk, "recipe_for",
        lambda wall, template: {
            "source": "test", "mapSrc": "src", "mapDst": "dst",
            "destWidth": 1920, "destHeight": 1080, "characterStyles": [],
        },
    )
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 1, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0, "saved": True, "closed": True})
    monkeypatch.setattr(rk, "restore_card_stroke_widths", lambda *a, **k: None)

    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()

    wall_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}

    plan_out: dict = {}
    logs: list[str] = []
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        plan_out=plan_out, log=logs.append,
    )

    assert plan_out.get("statJobs") == []
    assert plan_out["groupCollapseRefused"] == ["groupCollapseRefused(s=2,idx=1)"]
    warn_lines = [line for line in logs if line.startswith("WARNING remap: groupCollapseRefused")]
    assert warn_lines == ["WARNING remap: groupCollapseRefused(s=2,idx=1)"]


def test_plan_warns_once_per_run_on_aspect_less_items(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk
    from obed_edom.map_remap import ItemTransform

    monkeypatch.delenv("OBED_OFFLINE_WRITE", raising=False)
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)

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
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0, "saved": True, "closed": True})
    monkeypatch.setattr(rk, "restore_card_stroke_widths", lambda *a, **k: None)

    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()

    wall_payload = {
        "slideWidth": 7680, "slideHeight": 1080,
        "slides": [{
            "number": 1,
            "items": [
                {"kind": "image", "kindIndex": 0},
                {"kind": "group", "kindIndex": 0},
                {"kind": "image", "kindIndex": 1},
                {"kind": "image", "kindIndex": 2, "aspect": 1.0},
            ],
        }],
    }
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}

    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: _stub_plan())
    logs: list[str] = []
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        plan_out={}, log=logs.append,
    )
    warn_lines = [line for line in logs if line.startswith("WARN: aspect-snap unavailable")]
    assert len(warn_lines) == 1
    assert "3 item(s) on 1 slide(s)" in warn_lines[0]

    hide_transform = ItemTransform(
        slide_number=1, item_index=1, kind="image", x=0, y=0, w=1, h=1,
        kind_index=1, role="hide",
    )
    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: _stub_plan(transforms=[hide_transform]))
    logs = []
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        plan_out={}, log=logs.append,
    )
    warn_lines = [line for line in logs if line.startswith("WARN: aspect-snap unavailable")]
    assert len(warn_lines) == 1
    assert "2 item(s) on 1 slide(s)" in warn_lines[0]


# ============================================================================
# M-ASPECT falsifier — Keynote-free: the snap must equal its own predicted
# aspect-locked rect for every image/movie/group spec (see plan-aspect.md 26).
# ============================================================================
_DECKS = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
_FULL_DECK = _DECKS / "Full_Report_Card_Wall.key"
_BASE_TEMPLATE = _DECKS / "Base_CG_Assets.key"
_FAILS_JSON = find_repo_root() / "tests/fixtures/as-geometry-rounding/fails.json"


@pytest.mark.skipif(
    not (_FULL_DECK.exists() and _BASE_TEMPLATE.exists()), reason="local gold deck only"
)
def test_full_deck_plan_is_aspect_consistent():
    """71/674/633 (and the derived 1378/1440) are measured pins on
    ``Full_Report_Card_Wall.key`` — a change in any of them is a re-measurement
    decision, not a fixture bump."""
    import obed_edom.remap_keynote as rk
    from scripts import golden_plan

    with golden_plan._pinned_env():
        wall, tmpl, plan, _env = golden_plan.capture_plan(_FULL_DECK, _BASE_TEMPLATE)
    aspects = source_aspects(_FULL_DECK)
    id_map = spec_id_map(_FULL_DECK)
    objects, _id_to_file, _file_ids = _load_deck(_FULL_DECK)
    geom_sources: dict[str, str | None] = {}
    for slide_id, _skipped in slide_order(objects):
        if slide_id not in objects:
            continue
        for r in compose_geometry(objects[slide_id], objects):
            geom_sources[r["id"]] = r.get("geom_source")
    recipe = rk.recipe_for(wall, tmpl)
    card_sizes = {
        (round(s["rect"]["w"], 2), round(s["rect"]["h"], 2)) for s in recipe.get("cardSamples") or []
    }
    badge_sizes = {
        (round(r["w"], 2), round(r["h"], 2)) for r in (recipe.get("badgeSlots") or {}).values() if r
    }

    assert _FAILS_JSON.exists(), f"banked fails missing: {_FAILS_JSON}"
    fails = json.loads(_FAILS_JSON.read_text())
    banked_fail_addrs = {
        (f["slide"], f["kind"], f["ki"]) for f in fails if f["slide"] != 36
    }

    id_by_addr_cache: dict[int, dict[tuple[str, int], str]] = {}
    asserted: set[tuple[int, str, int]] = set()
    dropped_no_aspect_ids: list[str] = []
    card_badge_rows: list[tuple[int, str, int]] = []
    buckets: collections.Counter = collections.Counter()
    candidates = 0
    for t in plan.get("transforms") or []:
        if t.get("role") == "hide":
            continue
        kind = t.get("kind")
        if kind not in {"image", "movie", "group"}:
            continue
        candidates += 1
        slide = t["slide"]
        if slide == 36:
            buckets["slide36"] += 1
            continue
        if t.get("children"):
            buckets["child"] += 1
            continue
        kind_index = t.get("kindIndex")
        if slide not in id_by_addr_cache:
            id_by_addr_cache[slide] = _id_by_addr_for_slide(id_map, slide)
        obj_id = id_by_addr_cache[slide].get((kind, kind_index))
        if obj_id is None:
            buckets["no_id"] += 1
            continue
        x, y, w, h = t["x"], t["y"], t["w"], t["h"]
        size = (round(w, 2), round(h, 2))
        if kind == "group" and (size in card_sizes or size in badge_sizes):
            buckets["card_badge"] += 1
            card_badge_rows.append((slide, kind, kind_index))
            continue
        ar = aspects.get(obj_id)
        if ar is None:
            buckets["masked"] += 1
            dropped_no_aspect_ids.append(obj_id)
            continue
        h_r = round(h)
        pred = (round(x), round(y), round(h_r * ar, 2), float(h_r))
        worst = max(abs(a - b) for a, b in zip(pred, (x, y, w, h)))
        assert worst <= 0.001, (slide, kind, kind_index, pred, (x, y, w, h))
        assert abs(x - round(x)) <= 5e-3
        assert abs(y - round(y)) <= 5e-3
        assert abs(h - round(h)) <= 5e-3
        asserted.add((slide, kind, kind_index))
        buckets["asserted"] += 1

    assert candidates == 1440
    assert candidates == (
        buckets["slide36"] + buckets["child"] + buckets["no_id"]
        + buckets["card_badge"] + buckets["masked"] + len(asserted)
    )
    assert buckets["no_id"] == 0, buckets
    assert buckets["slide36"] == 6
    assert buckets["child"] == 56
    assert buckets["masked"] == 674
    assert buckets["card_badge"] == 71
    assert len(asserted) == 633
    assert buckets["asserted"] == len(asserted)
    assert buckets["masked"] + buckets["card_badge"] + len(asserted) == 1378

    assert all(geom_sources.get(obj_id) == "mask" for obj_id in dropped_no_aspect_ids), (
        dropped_no_aspect_ids
    )
    assert len(dropped_no_aspect_ids) == 674
    assert all(row[1] == "group" for row in card_badge_rows), card_badge_rows

    missing = banked_fail_addrs - asserted
    assert not missing, f"banked fail rows silently excluded from the aspect snap: {missing}"
    slide_36_fail_addrs = {(f["slide"], f["kind"], f["ki"]) for f in fails if f["slide"] == 36}
    assert len(slide_36_fail_addrs) == 4

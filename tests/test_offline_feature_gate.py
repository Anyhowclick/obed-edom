from __future__ import annotations

import os
from pathlib import Path

import pytest

from obed_edom.baseline import deck_digest

from scripts.offline_write_ab import (
    GATE_AXIS_TEXT_MASK,
    GATE_AXIS_ZORDER,
    GATE_VERSION,
    Tolerances,
    apply_arm_env,
    arm_config_reasons,
    clear_arm_env,
    compare_units_identity,
    feature_scope_reasons,
    gate_arm_configs,
    required_live_verify_reasons,
    run_record,
    visual_authority_ids,
    visual_oracle_reasons,
)


def test_zorder_axis_isolates_text_and_mask_flags():
    arm_a, arm_b = gate_arm_configs(GATE_AXIS_ZORDER, "verify")
    assert arm_a["OBED_ZORDER_WRITE"] == "off"
    assert arm_b["OBED_ZORDER_WRITE"] == "on"
    for arm in (arm_a, arm_b):
        assert arm["OBED_OFFLINE_WRITE"] == "verify"
        assert arm["OBED_OFFLINE_TEXT"] == "off"
        assert arm["OBED_OFFLINE_MASKCROP"] == "off"


def test_text_mask_axis_changes_only_the_two_feature_flags():
    arm_a, arm_b = gate_arm_configs(GATE_AXIS_TEXT_MASK, "verify")
    changed = {key for key in arm_a if arm_a[key] != arm_b[key]}
    assert changed == {"OBED_OFFLINE_TEXT", "OBED_OFFLINE_MASKCROP"}
    assert arm_a["OBED_ZORDER_WRITE"] == arm_b["OBED_ZORDER_WRITE"] == "on"
    assert arm_a["OBED_OFFLINE_TEXT"] == "off"
    assert arm_b["OBED_OFFLINE_TEXT"] == "on"
    assert arm_a["OBED_OFFLINE_MASKCROP"] == "off"
    assert arm_b["OBED_OFFLINE_MASKCROP"] == "on"


def test_gate_arm_configs_refuses_unknown_axis_or_mode():
    with pytest.raises(ValueError, match="unknown gate axis"):
        gate_arm_configs("other", "verify")
    with pytest.raises(ValueError, match="unknown offline-write mode"):
        gate_arm_configs(GATE_AXIS_TEXT_MASK, "off")


def test_apply_arm_env_clears_ambient_experiments(monkeypatch):
    monkeypatch.setenv("OBED_OFFLINE_READ", "off")
    monkeypatch.setenv("OBED_BULK_READ", "off")
    monkeypatch.setenv("OBED_DEBUG_PASS1_SNAPSHOT", "/tmp/ambient")
    arm_a, _ = gate_arm_configs(GATE_AXIS_TEXT_MASK, "verify")
    previous = apply_arm_env(arm_a)
    try:
        assert os.environ["OBED_OFFLINE_READ"] == "on"
        assert os.environ["OBED_BULK_READ"] == "on"
        assert os.environ["OBED_DEBUG_PASS1_SNAPSHOT"] == ""
        assert os.environ["OBED_OFFLINE_TEXT"] == "off"
        assert os.environ["OBED_OFFLINE_MASKCROP"] == "off"
    finally:
        clear_arm_env(previous)
    assert os.environ["OBED_OFFLINE_READ"] == "off"
    assert os.environ["OBED_BULK_READ"] == "off"
    assert os.environ["OBED_DEBUG_PASS1_SNAPSHOT"] == "/tmp/ambient"


def test_arm_config_provenance_is_required_for_feature_gate():
    arm_a, _ = gate_arm_configs(GATE_AXIS_TEXT_MASK, "verify")
    assert arm_config_reasons({}, arm_a, allow_legacy=False)
    assert arm_config_reasons({}, arm_a, allow_legacy=True) == []
    assert arm_config_reasons(
        {"gateVersion": GATE_VERSION, "armConfig": arm_a}, arm_a, allow_legacy=False
    ) == []
    wrong = {**arm_a, "OBED_OFFLINE_TEXT": "on"}
    reasons = arm_config_reasons(
        {"gateVersion": GATE_VERSION, "armConfig": wrong}, arm_a, allow_legacy=False
    )
    assert reasons and "armConfig" in reasons[0]


def test_run_record_persists_complete_arm_config():
    arm_a, _ = gate_arm_configs(GATE_AXIS_TEXT_MASK, "verify")
    record = run_record(
        commit="c",
        deck_digest="deck",
        source_digest="source",
        plan={"transforms": [], "reuses": [], "statJobs": [], "badgeRaises": []},
        child_resize={"ok": True},
        applied=1,
        missed=0,
        offline_write={"slides": [1]},
        spec_id_map={},
        arm_config=arm_a,
        gate_axis=GATE_AXIS_TEXT_MASK,
    )
    assert record["armConfig"] == arm_a
    assert record["gateAxis"] == GATE_AXIS_TEXT_MASK
    assert record["slideScope"] is None


def test_text_mask_gate_requires_whole_deck_axis_provenance():
    assert feature_scope_reasons(
        {"gateAxis": GATE_AXIS_TEXT_MASK, "slideScope": None}
    ) == []
    assert feature_scope_reasons({})
    assert feature_scope_reasons(
        {"gateAxis": GATE_AXIS_ZORDER, "slideScope": [4, 5]}
    ) == [
        "run record gateAxis 'zorder' != 'text-mask'",
        "run record slideScope is partial: [4, 5]",
    ]


def test_text_mask_gate_requires_measured_live_verify():
    good = {
        "offlineVerifyPass": True,
        "liveVerifyPass": True,
        "liveVerifySetPass": True,
        "liveVerifyCoverage": {"uncovered": []},
    }
    assert required_live_verify_reasons(good, label="A") == []
    assert required_live_verify_reasons({}, label="A")
    assert required_live_verify_reasons(
        {**good, "liveVerifyPass": None}, label="A"
    ) == ["A liveVerifyPass was not measured PASS"]


def _visual_report() -> dict:
    manifest_a = {"count": 5, "sha256": "pa"}
    manifest_b = {"count": 5, "sha256": "pb"}
    manifest_null = {"count": 5, "sha256": "pn"}
    return {
        "version": 3,
        "oracleDigest": deck_digest(
            Path(__file__).parents[1] / "scripts" / "text_mask_visual_oracle.py"
        ),
        "armADigest": "a",
        "armBDigest": "b",
        "armAPreviews": manifest_a,
        "armBPreviews": manifest_b,
        "nullAPreviews": manifest_null,
        "crop": {
            "pass": True,
            "nullControl": True,
            "positiveControl": True,
            "regions": 5,
            "rows": [
                {
                    "pass": True, "slide": 1, "id": f"crop-{index}",
                    "actualRatio": 0.1, "nullRatio": 0.0, "positiveRatio": 0.5,
                    "cropDeltaPx": 1.0,
                }
                for index in range(5)
            ],
        },
        "text": {
            "pass": True,
            "nullControl": True,
            "positiveControl": True,
            "labels": 137,
            "translationTolerancePx": 8.0,
            "rows": [
                {
                    "pass": True, "slide": 1, "id": f"text-{index}",
                    "actualRatio": 0.1, "nullRatio": 0.0, "positiveRatio": 0.5,
                    "translationPx": 1.0,
                }
                for index in range(137)
            ],
        },
    }


def _visual_reasons(report: dict | None, **overrides) -> list[str]:
    kwargs = {
        "arm_a_digest": "a",
        "arm_b_digest": "b",
        "arm_a_previews": {"count": 5, "sha256": "pa"},
        "arm_b_previews": {"count": 5, "sha256": "pb"},
        "null_a_previews": {"count": 5, "sha256": "pn"},
    }
    kwargs.update(overrides)
    return visual_oracle_reasons(report, **kwargs)


def test_visual_oracle_requires_exact_decks_and_both_controlled_bars():
    report = _visual_report()
    assert _visual_reasons(report) == []
    report["armBDigest"] = "stale"
    report["crop"]["positiveControl"] = False
    report["crop"]["rows"][0]["pass"] = False
    report["text"]["labels"] = 0
    reasons = _visual_reasons(report)
    assert any("arm B digest" in reason for reason in reasons)
    assert any("crop positive control" in reason for reason in reasons)
    assert any("crop row 1/crop-0 asserted pass" in reason for reason in reasons)
    assert any("text compared no labels" in reason for reason in reasons)


def test_visual_oracle_missing_report_is_red():
    assert _visual_reasons(None) == [
        "text-mask gate has no visual oracle report"
    ]


def test_visual_oracle_accepts_only_explicit_zero_span_inert_rows():
    report = _visual_report()
    row = report["text"]["rows"][0]
    row.update(
        {
            "actualRatio": 0.0,
            "nullRatio": 0.0,
            "positiveRatio": 0.0,
            "visualSpan": 0,
            "visuallyInert": True,
        }
    )
    assert _visual_reasons(report) == []
    row["visualSpan"] = 1
    assert any("asserted pass" in reason for reason in _visual_reasons(report))


def test_visual_oracle_rejects_text_translation_over_fixed_limit():
    report = _visual_report()
    report["text"]["rows"][0]["translationPx"] = 9.0
    assert any("asserted pass" in reason for reason in _visual_reasons(report))


@pytest.mark.parametrize(
    "report",
    [[], {"version": "one"}, {"version": 3, "crop": {"regions": "five"}}],
)
def test_visual_oracle_malformed_report_is_red_without_raising(report):
    assert _visual_reasons(report)


def test_visual_authority_is_scoped_to_reported_slide_and_id():
    report = _visual_report()
    assert ("masked", "crop-0") in visual_authority_ids(report, 1)
    assert ("autosize", "text-0") in visual_authority_ids(report, 1)
    assert visual_authority_ids(report, 2) == set()


def _unit(obj_id: str, kind: str, sig: dict) -> dict:
    return {"id": obj_id, "kind": kind, "addr": ("top", kind, 0), "sig": sig}


def test_visual_authority_delegates_autosize_archive_anchor_only():
    a = [_unit("text-1", "text", {"type": "autosize", "x": 10.0, "flips": (False, False)})]
    b = [_unit("text-1", "text", {"type": "autosize", "x": 300.0, "flips": (False, False)})]
    assert compare_units_identity(a, b, Tolerances()).get("pass") is False
    report = compare_units_identity(
        a, b, Tolerances(), visual_authority={("autosize", "text-1")}
    )
    assert report["pass"] is True
    assert report["per_bucket"]["text"]["visualDelegated"] == 1
    assert compare_units_identity(
        a, b, Tolerances(), visual_authority={("autosize", "other")}
    )["pass"] is False


def test_visual_authority_keeps_mask_crop_geometry_and_structure_hard():
    base = {
        "type": "masked",
        "crop": (10.0, 20.0, 30.0, 40.0),
        "raw_size": (100.0, 100.0),
        "mask_angle": 0.0,
        "flips": (False, False),
    }
    raw_size_only = {**base, "crop": (11.0, 20.0, 30.0, 40.0), "raw_size": (110.0, 100.0)}
    a = [_unit("image-1", "image", base)]
    b = [_unit("image-1", "image", raw_size_only)]
    assert compare_units_identity(a, b, Tolerances(mask=2.0))["pass"] is False
    assert compare_units_identity(
        a, b, Tolerances(mask=2.0), visual_authority={("masked", "image-1")}
    )["pass"] is True

    b[0]["sig"] = {**raw_size_only, "crop": (13.0, 20.0, 30.0, 40.0)}
    assert compare_units_identity(
        a, b, Tolerances(mask=2.0), visual_authority={("masked", "image-1")}
    )["pass"] is False
    b[0]["sig"] = {**raw_size_only, "mask_angle": 90.0}
    assert compare_units_identity(
        a, b, Tolerances(mask=2.0), visual_authority={("masked", "image-1")}
    )["pass"] is False

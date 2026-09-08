"""Tests for the `applyReuse` add-delta paste verification gate as it surfaces
through `remap_keynote.remap_keynote` — the RuntimeError raise on `addFailure`,
the ordering against the pre-existing `applied == 0` raise, and the additive
`missReasons`/`addReports` log/run-record surfacing.

Built on the harness in `tests/test_offline_write.py::test_reuse_chain_line_marks_the_preadd_links`:
`_run_jxa` is stubbed to hand back a fixed JXA result dict instead of shelling out to
Keynote, so these are pure-Python tests of the surrounding surfacing/raise logic —
no Keynote, no Apple Events, no child_process.

SAFETY: OBED_OFFLINE_WRITE is set EXPLICITLY (not delenv'd) on every test — an
un-set/delenv'd flag can default to a mode that opens a REAL Keynote via
`_run_stat_finalize`; see the safety note on `test_flag_off_builds_the_same_plan_as_today`
in test_offline_write.py.
"""

from __future__ import annotations

import pytest


def _wire_common(monkeypatch, rk, *, jxa_result):
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
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
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: jxa_result)


def _payloads():
    wall_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    return wall_payload, template_payload


def _touch_paths(tmp_path):
    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()
    return source, template, dest


def _add_failure_125():
    return {
        "slide": 125,
        "expected": {"group": 45},
        "pasted": {"group": 6, "line": 1},
        "shortfall": {"group": 39},
        "surplus": {"line": 1},
        "unmeasured": [],
        "attempts": 3,
        "gates": [{"attempt": 1, "pasteboard": "stuck"}],
        "origAfterStrip": {"groups": 45},
        "addSpecs": 45,
    }


def test_add_failure_raises_before_the_stroke_pass(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    stroke_calls: list[int] = []
    monkeypatch.setattr(rk, "restore_card_stroke_widths", lambda *a, **k: stroke_calls.append(1))

    jxa_result = {"applied": 45, "missed": 0, "addFailure": _add_failure_125()}
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    with pytest.raises(RuntimeError) as excinfo:
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload,
            log=lambda m: None,
        )
    msg = str(excinfo.value)
    assert "125" in msg
    assert "'group': 45" in msg
    assert "left intact" in msg
    assert "NOT saved" in msg
    assert stroke_calls == []


def test_add_failure_detail_is_logged_before_the_raise(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    jxa_result = {"applied": 45, "missed": 0, "addFailure": _add_failure_125()}
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    lines: list[str] = []
    with pytest.raises(RuntimeError):
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload,
            log=lines.append,
        )
    assert any(line.startswith("FATAL reuse slide 125") for line in lines)


def test_add_failure_is_checked_before_the_applied_zero_raise(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    add_fail = {
        "slide": 125, "expected": {"group": 45}, "pasted": {}, "shortfall": {"group": 45},
        "surplus": {}, "unmeasured": [], "attempts": 3, "gates": [],
        "origAfterStrip": {"groups": 45}, "addSpecs": 45,
    }
    jxa_result = {"applied": 0, "missed": 45, "addFailure": add_fail}
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    with pytest.raises(RuntimeError) as excinfo:
        rk.remap_keynote(
            source, dest, template=template,
            wall_payload=wall_payload, template_payload=template_payload,
            log=lambda m: None,
        )
    msg = str(excinfo.value)
    assert "could not verify its pasted add-delta" in msg
    assert "moved 0 objects" not in msg


def test_miss_reasons_are_surfaced_even_when_objects_were_applied(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    jxa_result = {
        "applied": 3344, "missed": 0,
        "missReasons": ["paste delta slide 125: Error: some AppleScript failure"],
    }
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    lines: list[str] = []
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        log=lines.append,
    )
    assert "WARNING remap: paste delta slide 125: Error: some AppleScript failure" in lines


def test_clean_run_emits_no_new_warning_lines(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    jxa_result = {
        "applied": 45, "missed": 0,
        "addReports": [
            {
                "slide": 125,
                "report": {
                    "attempts": 1, "expected": {"group": 45}, "pasted": {"group": 45},
                    "surplus": {}, "shortfall": {}, "unmeasured": [],
                },
            },
        ],
    }
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    lines: list[str] = []
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        log=lines.append,
    )
    assert not any("WARNING" in line for line in lines)


def test_add_reports_land_in_the_run_record(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    add_reports = [
        {
            "slide": 125,
            "report": {
                "attempts": 1, "expected": {"group": 45}, "pasted": {"group": 45},
                "surplus": {}, "shortfall": {}, "unmeasured": [],
            },
        },
    ]
    jxa_result = {"applied": 45, "missed": 0, "addReports": add_reports}
    _wire_common(monkeypatch, rk, jxa_result=jxa_result)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()

    result = rk.remap_keynote(
        source, dest, template=template,
        wall_payload=wall_payload, template_payload=template_payload,
        log=lambda m: None,
    )
    assert result["addReports"] == add_reports

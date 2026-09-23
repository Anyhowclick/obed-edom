"""Keynote-free locks for `remap_keynote._require_pass1_saved_closed`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from obed_edom.remap_keynote import (
    _PASS1_JS_STAGES,
    _pass1_census,
    _require_pass1_saved_closed,
    _say_pass1_census,
    _say_pass1_stages,
)


def _touch_paths(tmp_path: Path):
    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    dest = tmp_path / "out.key"
    source.touch()
    template.touch()
    return source, template, dest


def _payloads():
    wall_payload = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    return wall_payload, template_payload


def test_require_pass1_saved_closed_accepts_true_true():
    _require_pass1_saved_closed({"saved": True, "closed": True})


def test_require_pass1_saved_closed_rejects_string_false():
    with pytest.raises(RuntimeError):
        _require_pass1_saved_closed({"saved": "false", "closed": True})


def test_require_pass1_saved_closed_rejects_truthy_non_bool():
    with pytest.raises(RuntimeError):
        _require_pass1_saved_closed({"saved": 1, "closed": True})


def test_say_pass1_stages_prints_in_order_with_residuals():
    lines: list[str] = []
    py = {"prep": 1.04, "copyDeck": 212.44, "copyTemplate": 0.5, "runJxa": 30.0}
    stages = {
        "total": 28000, "close": 1000, "save": 10000, "open": 2000, "slideSize": 500,
        "templateOpen": 300, "layoutImport": 200, "layoutApply": 1000, "trailingDelete": 100,
        "templateClose": 100, "attrs": 9000, "hides": 2000, "finish": 1500,
    }
    jxa = {"stages": stages, "sizeProp": "width", "saveRetried": True, "saveFirstError": "-1712"}
    _say_pass1_stages(py, jxa, lines.append, {"copyDeck": "6.77 GB"})
    assert lines == [
        "Pass 1 stage prep: 1.0 s",
        "Pass 1 stage copyDeck: 212.4 s (6.77 GB)",
        "Pass 1 stage copyTemplate: 0.5 s",
        "Pass 1 stage runJxa: 30.0 s",
        "Pass 1 stage open: 2.0 s",
        "Pass 1 stage slideSize: 0.5 s (sizeProp: width)",
        "Pass 1 stage templateOpen: 0.3 s",
        "Pass 1 stage layoutImport: 0.2 s",
        "Pass 1 stage layoutApply: 1.0 s",
        "Pass 1 stage trailingDelete: 0.1 s",
        "Pass 1 stage templateClose: 0.1 s",
        "Pass 1 stage attrs: 9.0 s",
        "Pass 1 stage hides: 2.0 s",
        "Pass 1 stage finish: 1.5 s",
        "Pass 1 stage save: 10.0 s (retried: yes; first error: -1712)",
        "Pass 1 stage close: 1.0 s",
        "Pass 1 stage total: 28.0 s",
        "Pass 1 unattributed: js 0.3 s, osascript/launch 2.0 s",
    ]


def test_say_pass1_stages_tolerates_bare_jxa_dict():
    lines: list[str] = []
    _say_pass1_stages({"copyDeck": 2.0, "runJxa": 3.0}, {"applied": 1, "missed": 0}, lines.append)
    assert lines == ["Pass 1 stage copyDeck: 2.0 s", "Pass 1 stage runJxa: 3.0 s"]


def test_say_pass1_stages_save_without_retry_flag_reads_no():
    lines: list[str] = []
    _say_pass1_stages({}, {"stages": {"save": 1500}}, lines.append)
    assert lines == ["Pass 1 stage save: 1.5 s (retried: no)"]


def test_pass1_census_counts_paths_and_classes():
    transforms = [
        {"slide": 1, "role": "pin", "font": "Helvetica", "locked": True},
        {"slide": 1, "role": "hide"},
        {"slide": 2, "role": "map", "children": [{"kind": "shape"}]},
        {"slide": 2, "role": "hide"},
        {"slide": 3, "role": "pin", "opacity": 0.5},
        {"slide": 4, "role": "pin", "fontSize": 12, "locked": True},
        {"slide": 5, "role": "hide"},
    ]
    census = _pass1_census(transforms, suppressed={1, 2}, as_geom_slides={2, 3})
    assert census == {
        "attrs": 2, "as": 1, "jxa": 2, "specs": 4, "hides": 3,
        "noAttr": 1, "locked": 2, "groupChildren": 1,
    }
    lines: list[str] = []
    _say_pass1_census(census, lines.append)
    assert lines == [
        "Pass 1 census: slides attrs=2 as=1 jxa=2; specs 4 "
        "(hides 3, no-attr 1, locked 2, group-children 1)"
    ]


def test_say_pass1_stages_without_total_prints_no_residual():
    lines: list[str] = []
    _say_pass1_stages({"runJxa": 5.0}, {"stages": {"open": 1000, "save": 2000}}, lines.append)
    assert lines == [
        "Pass 1 stage runJxa: 5.0 s",
        "Pass 1 stage open: 1.0 s",
        "Pass 1 stage save: 2.0 s (retried: no)",
    ]


def test_say_pass1_stages_without_runjxa_prints_na_launch():
    lines: list[str] = []
    _say_pass1_stages({}, {"stages": {"open": 1000, "total": 1500}}, lines.append)
    assert lines[-1] == "Pass 1 unattributed: js 0.5 s, osascript/launch n/a"


def test_pass1_census_no_attr_matches_apply_geom_truthiness():
    transforms = [
        {"slide": 1, "font": ""},
        {"slide": 1, "fontSize": 0},
        {"slide": 1, "color": [1, 2]},
        {"slide": 1, "opacity": 0},
        {"slide": 1, "color": [1, 0, 0]},
    ]
    census = _pass1_census(transforms, suppressed=set(), as_geom_slides=set())
    assert census["noAttr"] == 3


def test_pass1_js_stage_names_match_js_source():
    js = (Path(__file__).resolve().parents[1] / "src/obed_edom/remap_keynote.js").read_text()
    assert set(re.findall(r'_stage\("(\w+)"', js)) == set(_PASS1_JS_STAGES) | {"total"}

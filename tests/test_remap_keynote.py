"""Keynote-free locks for `remap_keynote._require_pass1_saved_closed`."""

from __future__ import annotations

from pathlib import Path

import pytest

from obed_edom.remap_keynote import _require_pass1_saved_closed


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

"""Keynote-free locks for `remap_keynote.slide_reuse_mode` and its single call site.

Mirrors `tests/test_as_geometry.py`'s flag table and the `remap_keynote()` harness
in `tests/test_offline_write.py`. SAFETY: `OBED_OFFLINE_WRITE` is set explicitly
to `off` so a flipped ambient default cannot open Keynote against a touch()-only dest.
"""

from __future__ import annotations

from pathlib import Path

from obed_edom.remap_keynote import slide_reuse_mode


def test_slide_reuse_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("OBED_SLIDE_REUSE", raising=False)
    assert slide_reuse_mode() == "off"


def test_slide_reuse_mode_parse_table(monkeypatch):
    monkeypatch.delenv("OBED_SLIDE_REUSE", raising=False)
    assert slide_reuse_mode() == "off"
    for value, expected in (
        ("off", "off"),
        ("OFF", "off"),
        ("on", "on"),
        ("ON", "on"),
        ("garbage", "off"),
        ("", "off"),
        ("  on  ", "on"),
    ):
        monkeypatch.setenv("OBED_SLIDE_REUSE", value)
        assert slide_reuse_mode() == expected, value
    assert slide_reuse_mode(explicit="on") == "on"
    monkeypatch.setenv("OBED_SLIDE_REUSE", "off")
    assert slide_reuse_mode(explicit="on") == "on"
    assert slide_reuse_mode(explicit="nope") == "off"


def _wire_remap(monkeypatch, rk, *, reuse_spy=None):
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    monkeypatch.setattr(rk, "plan_payload_transforms", lambda *a, **k: [])
    if reuse_spy is not None:
        monkeypatch.setattr(rk, "plan_slide_reuses", reuse_spy)
    monkeypatch.setattr(
        rk,
        "recipe_for",
        lambda wall, template: {
            "source": "test",
            "mapSrc": "src",
            "mapDst": "dst",
            "destWidth": 1920,
            "destHeight": 1080,
            "characterStyles": [],
        },
    )
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 0, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)
    monkeypatch.setattr(rk, "_run_jxa", lambda plan: {"applied": 1, "missed": 0})


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


def test_plan_slide_reuses_not_called_when_off(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    calls: list = []

    def spy(*a, **k):
        calls.append((a, k))
        return [{"slide": 12, "from": 11}]

    monkeypatch.delenv("OBED_SLIDE_REUSE", raising=False)
    _wire_remap(monkeypatch, rk, reuse_spy=spy)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()
    lines: list[str] = []
    rk.remap_keynote(
        source,
        dest,
        template=template,
        wall_payload=wall_payload,
        template_payload=template_payload,
        log=lines.append,
    )
    assert calls == []
    assert any("0 reuse slide(s)" in m for m in lines)
    assert not any("Duplicating remapped slides" in m for m in lines)
    assert not any("FATAL reuse slide" in m for m in lines)
    assert not any("WARNING reuse slide" in m for m in lines)
    assert not any("donor-copy group(s) deduped" in m and not m.startswith("OBED_") for m in lines)


def test_plan_slide_reuses_called_when_on(monkeypatch, tmp_path):
    import obed_edom.remap_keynote as rk

    calls: list = []

    def spy(*a, **k):
        calls.append((a, k))
        return [{"slide": 12, "from": 11, "remove": [], "add": [], "mutate": []}]

    monkeypatch.setenv("OBED_SLIDE_REUSE", "on")
    _wire_remap(monkeypatch, rk, reuse_spy=spy)
    source, template, dest = _touch_paths(tmp_path)
    wall_payload, template_payload = _payloads()
    lines: list[str] = []
    rk.remap_keynote(
        source,
        dest,
        template=template,
        wall_payload=wall_payload,
        template_payload=template_payload,
        log=lines.append,
    )
    assert len(calls) == 1
    assert any("1 reuse slide(s)" in m for m in lines)
    assert any("Duplicating remapped slides" in m for m in lines)

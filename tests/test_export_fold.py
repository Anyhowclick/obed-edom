"""remap_and_inspect wiring for the folded preview export (Stage A).

The heavy Keynote passes are mocked; these lock only the orchestration:
  - validate=False folds the export into the stat-finalize session, so
    remap_and_inspect must NOT also call export_slide_images;
  - a run with no stat-group jobs (nothing folded) still exports via the fallback;
  - validate=False threads export_dir into remap_keynote, validate=True does not
    (its read-back path exports through inspect_keynote and stays unchanged).
"""

import pytest

from obed_edom import remap_keynote as rk


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "previews"
    d.mkdir()
    (d / "slide-001.png").write_bytes(b"png")
    return d


def _capture_remap(monkeypatch, *, exported: bool):
    """Replace remap_keynote with a stub that records the export_dir it got."""
    seen = {}

    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        seen["export_dir"] = export_dir
        return {
            "dest": str(dest),
            "exported": exported,
            "previewFiles": ["slide-001.png"] if exported else [],
        }

    monkeypatch.setattr(rk, "remap_keynote", fake_remap)
    return seen


def test_validate_false_skips_export_when_folded(monkeypatch, tmp_path, export_dir):
    seen = _capture_remap(monkeypatch, exported=True)
    export_calls = []
    monkeypatch.setattr(
        rk, "export_slide_images", lambda *a, **k: export_calls.append(a) or None
    )

    info = rk.remap_and_inspect(
        tmp_path / "wall.key",
        tmp_path / "out.key",
        template=tmp_path / "tpl.key",
        export_dir=export_dir,
        validate=False,
    )

    # The stat-finalize session already exported, so no standalone export runs.
    assert export_calls == []
    # And the export_dir was threaded into remap_keynote for the fold.
    assert seen["export_dir"] == export_dir
    assert info["previewFiles"] == ["slide-001.png"]


def test_validate_false_falls_back_when_not_folded(monkeypatch, tmp_path, export_dir):
    # No stat-group jobs → remap_keynote reports exported=False → fallback must export.
    _capture_remap(monkeypatch, exported=False)
    export_calls = []
    monkeypatch.setattr(
        rk, "export_slide_images", lambda *a, **k: export_calls.append(a) or None
    )

    rk.remap_and_inspect(
        tmp_path / "wall.key",
        tmp_path / "out.key",
        template=tmp_path / "tpl.key",
        export_dir=export_dir,
        validate=False,
    )

    assert len(export_calls) == 1  # standalone export ran as the fallback


def test_validate_true_does_not_thread_export_dir(monkeypatch, tmp_path, export_dir):
    seen = _capture_remap(monkeypatch, exported=False)
    # The read-back path exports through inspect_keynote; stub it out.
    inspect_calls = {}

    def fake_inspect(dest, *, export_dir=None, slide_range=None, **kwargs):
        inspect_calls["export_dir"] = export_dir
        return {"slideWidth": 1920, "slideHeight": 1080, "slideCount": 1, "exported": True}

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)
    export_calls = []
    monkeypatch.setattr(
        rk, "export_slide_images", lambda *a, **k: export_calls.append(a) or None
    )

    rk.remap_and_inspect(
        tmp_path / "wall.key",
        tmp_path / "out.key",
        template=tmp_path / "tpl.key",
        export_dir=export_dir,
        validate=True,
    )

    # remap_keynote must not fold export on the validate=True path…
    assert seen["export_dir"] is None
    # …the read-back inspect handles the export instead, and no standalone export runs.
    assert inspect_calls["export_dir"] == export_dir
    assert export_calls == []

from pathlib import Path

import pytest

from obed_edom.paths import find_repo_root, resolve_keynote_template, select_deck_template


def test_find_repo_root_uses_pyproject():
    root = find_repo_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "obed_edom").is_dir()


def test_resolve_keynote_template_absolute(tmp_path: Path):
    key = tmp_path / "Sermon_GW.key"
    key.write_text("x")
    assert resolve_keynote_template(key) == key.resolve()


def test_resolve_keynote_template_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from obed_edom import paths

    monkeypatch.setattr(paths, "find_repo_root", lambda: tmp_path)
    folder = tmp_path / "Default Templates"
    folder.mkdir()
    key = folder / "Sermon_GW.key"
    key.write_text("x")
    assert (
        paths.resolve_keynote_template(None, fallback_rel="Default Templates/Sermon_GW.key")
        == key.resolve()
    )


def test_resolve_keynote_template_missing_raises():
    with pytest.raises(FileNotFoundError, match="Template not found"):
        resolve_keynote_template("/no/such/template.key")


def test_select_deck_template_skips_when_not_provided():
    assert select_deck_template(None, fallback_rel="Default Templates/x.key", allow_fallback=False) is None


def test_select_deck_template_missing_fallback_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from obed_edom import paths

    monkeypatch.setattr(paths, "find_repo_root", lambda: tmp_path)
    assert paths.select_deck_template(None, fallback_rel="Default Templates/x.key", allow_fallback=True) is None


def test_generate_both_lw_only_skips_dsk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from obed_edom import keynote

    lw = tmp_path / "lw.key"
    lw.write_text("x")
    called: list[str] = []

    def fake_deck(slides, template, dest, export_dir=None, **kwargs):
        called.append(Path(template).name)
        return {"exported": True, "missingMasters": [], "superscriptFix": {"ok": True, "skipped": True}}

    monkeypatch.setattr(keynote, "generate_deck", fake_deck)
    monkeypatch.setattr(keynote, "output_dir_for", lambda docx: tmp_path / "out")
    _out, lw_key, dsk_key, _lw_res, dsk_res = keynote.generate_both(
        tmp_path / "outline.docx",
        [],
        [],
        export=False,
        lw_template=lw,
        dsk_template=None,
        only_provided=True,
    )
    assert called == ["lw.key"]
    assert lw_key is not None
    assert dsk_key is None
    assert dsk_res.get("skipped") is True


def test_generate_both_requires_at_least_one_template():
    from obed_edom.keynote import generate_both

    with pytest.raises(FileNotFoundError, match="At least one"):
        generate_both(
            Path("outline.docx"),
            [],
            [],
            export=False,
            lw_template=None,
            dsk_template=None,
            only_provided=True,
        )

from pathlib import Path

import pytest

from obed_edom.paths import (
    export_destination,
    find_repo_root,
    output_root,
    resolve_keynote_template,
    validate_export_dir,
)


def test_find_repo_root_uses_pyproject():
    root = find_repo_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "obed_edom").is_dir()


def test_resolve_keynote_template_absolute(tmp_path: Path):
    key = tmp_path / "Sermon_GW.key"
    key.write_text("x")
    assert resolve_keynote_template(key) == key.resolve()


def test_resolve_keynote_template_missing_raises():
    with pytest.raises(FileNotFoundError, match="Template not found"):
        resolve_keynote_template("/no/such/template.key")


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
        )


def test_validate_export_dir_rejects_relative():
    with pytest.raises(ValueError, match="absolute"):
        validate_export_dir("relative/dir")


def test_validate_export_dir_expands_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    resolved = validate_export_dir("~/exports")
    assert resolved == (tmp_path / "exports").resolve()
    assert resolved.is_dir()


def test_validate_export_dir_creates_missing_dir(tmp_path: Path):
    target = tmp_path / "a" / "b" / "exports"
    assert not target.exists()
    resolved = validate_export_dir(target)
    assert resolved.is_dir()


def test_validate_export_dir_rejects_file(tmp_path: Path):
    target = tmp_path / "not-a-dir"
    target.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        validate_export_dir(target)


@pytest.mark.parametrize(
    "root_name",
    [".maps", ".watercolour", ".resize", ".diff", ".outline", ".inspect", ".uploads", ".sessions", ".geocode"],
)
def test_validate_export_dir_rejects_private_roots(root_name: str):
    with pytest.raises(ValueError, match="cannot be inside"):
        validate_export_dir(output_root() / root_name / "sub")


def test_validate_export_dir_rejects_cache_root():
    from obed_edom.baseline import cache_root

    with pytest.raises(ValueError, match="cannot be inside"):
        validate_export_dir(cache_root() / "sub")


def test_validate_export_dir_accepts_sibling_of_output_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OBED_EDOM_OUTPUT_ROOT", str(tmp_path / "output"))
    target = tmp_path / "output" / "exports"
    resolved = validate_export_dir(target)
    assert resolved == target.resolve()


def test_export_destination_job_override_wins(tmp_path: Path):
    override = tmp_path / "override"
    override.mkdir()

    class FakeJob:
        result = {"exportDir": str(override)}

    assert export_destination(FakeJob()) == override
    assert "exportDirFallback" not in FakeJob.result


def test_export_destination_job_override_removed_falls_back(tmp_path: Path):
    override = tmp_path / "override"  # never created — removed between submit and run

    class FakeJob:
        result = {"exportDir": str(override)}

    assert export_destination(FakeJob()) == output_root()
    assert FakeJob.result["exportDirFallback"] is True


def test_export_destination_job_override_now_a_file_falls_back(tmp_path: Path):
    override = tmp_path / "override"
    override.write_text("now a file")

    class FakeJob:
        result = {"exportDir": str(override)}

    assert export_destination(FakeJob()) == output_root()
    assert FakeJob.result["exportDirFallback"] is True


def test_export_destination_setting_wins_over_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    class FakeJob:
        result = {}

    from obed_edom import settings as settings_mod

    default_dir = tmp_path / "default"
    default_dir.mkdir()
    monkeypatch.setattr(
        settings_mod, "load_settings", lambda *a, **k: {"defaultExportDir": str(default_dir)}
    )
    assert export_destination(FakeJob()) == default_dir


def test_export_destination_stale_setting_falls_back_to_output_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeJob:
        result = {}

    from obed_edom import settings as settings_mod

    stale_dir = tmp_path / "gone"
    monkeypatch.setattr(
        settings_mod, "load_settings", lambda *a, **k: {"defaultExportDir": str(stale_dir)}
    )
    assert not stale_dir.exists()
    assert export_destination(FakeJob()) == output_root()


def test_export_destination_falls_back_to_output_root(monkeypatch: pytest.MonkeyPatch):
    class FakeJob:
        result = {}

    from obed_edom import settings as settings_mod

    monkeypatch.setattr(settings_mod, "load_settings", lambda *a, **k: {"defaultExportDir": ""})
    assert export_destination(FakeJob()) == output_root()

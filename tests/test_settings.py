from pathlib import Path

import pytest

from obed_edom.settings import DEFAULTS, load_settings, save_settings


def test_settings_defaults_and_clamp(tmp_path: Path):
    assert load_settings(tmp_path) == DEFAULTS
    written = save_settings({"reuseThreshold": 1.4, "reusePairings": False}, tmp_path)
    assert written["reuseThreshold"] == 1.0
    assert written["reusePairings"] is False
    assert written["reusePreviews"] is True
    again = load_settings(tmp_path)
    assert again["reusePairings"] is False
    assert again["reuseThreshold"] == 1.0


def test_default_export_dir_round_trips(tmp_path: Path):
    export_dir = tmp_path / "exports"
    written = save_settings({"defaultExportDir": str(export_dir)}, tmp_path)
    assert written["defaultExportDir"] == str(export_dir.resolve())
    assert export_dir.is_dir()
    again = load_settings(tmp_path)
    assert again["defaultExportDir"] == str(export_dir.resolve())


def test_default_export_dir_empty_string_is_valid(tmp_path: Path):
    written = save_settings({"defaultExportDir": ""}, tmp_path)
    assert written["defaultExportDir"] == ""


def test_default_export_dir_rejects_bad_path(tmp_path: Path):
    with pytest.raises(ValueError):
        save_settings({"defaultExportDir": "relative/path"}, tmp_path)


def test_load_settings_succeeds_with_deleted_export_dir(tmp_path: Path):
    export_dir = tmp_path / "exports"
    save_settings({"defaultExportDir": str(export_dir)}, tmp_path)
    export_dir.rmdir()
    again = load_settings(tmp_path)
    assert again["defaultExportDir"] == str(export_dir.resolve())
    assert not export_dir.exists()


def test_load_settings_succeeds_with_stored_path_now_a_file(tmp_path: Path):
    export_dir = tmp_path / "exports"
    save_settings({"defaultExportDir": str(export_dir)}, tmp_path)
    export_dir.rmdir()
    export_dir.write_text("now a file")
    again = load_settings(tmp_path)
    assert again["defaultExportDir"] == str(export_dir.resolve())

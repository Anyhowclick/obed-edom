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


def test_highlight_colour_default(tmp_path: Path):
    assert load_settings(tmp_path)["highlightColour"] == "#e8772a"


def test_highlight_colour_round_trips_lowercased(tmp_path: Path):
    written = save_settings({"highlightColour": "#0A84FF"}, tmp_path)
    assert written["highlightColour"] == "#0a84ff"
    again = load_settings(tmp_path)
    assert again["highlightColour"] == "#0a84ff"


def test_highlight_colour_rejects_invalid_value(tmp_path: Path):
    written = save_settings({"highlightColour": "nope"}, tmp_path)
    assert written["highlightColour"] == "#e8772a"


def test_highlight_colour_expands_3_digit_hex(tmp_path: Path):
    written = save_settings({"highlightColour": "#0AF"}, tmp_path)
    assert written["highlightColour"] == "#00aaff"
    again = load_settings(tmp_path)
    assert again["highlightColour"] == "#00aaff"


def test_highlight_colour_strips_trailing_newline(tmp_path: Path):
    written = save_settings({"highlightColour": "#abc\n"}, tmp_path)
    assert written["highlightColour"] == "#aabbcc"


def test_highlight_colour_rejects_embedded_control_char(tmp_path: Path):
    written = save_settings({"highlightColour": "#0a\x0084ff"}, tmp_path)
    assert written["highlightColour"] == "#e8772a"


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


def test_templates_round_trip(tmp_path: Path):
    assert load_settings(tmp_path)["dskTemplate"] == ""
    assert load_settings(tmp_path)["lwTemplate"] == ""
    save_settings({"dskTemplate": " /Users/x/DSK.key \n", "lwTemplate": "/Users/x/LW.key"}, tmp_path)
    again = load_settings(tmp_path)
    assert again["dskTemplate"] == "/Users/x/DSK.key"
    assert again["lwTemplate"] == "/Users/x/LW.key"


def test_templates_clear_with_empty_string(tmp_path: Path):
    save_settings({"dskTemplate": "/Users/x/DSK.key"}, tmp_path)
    save_settings({**load_settings(tmp_path), "dskTemplate": ""}, tmp_path)
    assert load_settings(tmp_path)["dskTemplate"] == ""


def test_ak_output_defaults(tmp_path: Path):
    got = load_settings(tmp_path)
    assert got["akOutputMode"] == "screen"
    assert got["akOutputRate"] == 25
    assert got["akKeyer"] == "external"


def test_ak_output_valid_values_round_trip(tmp_path: Path):
    written = save_settings({"akOutputMode": "keyer", "akOutputRate": 30, "akKeyer": "off"}, tmp_path)
    assert (written["akOutputMode"], written["akOutputRate"], written["akKeyer"]) == ("keyer", 30, "off")
    again = load_settings(tmp_path)
    assert (again["akOutputMode"], again["akOutputRate"], again["akKeyer"]) == ("keyer", 30, "off")
    assert isinstance(again["akOutputRate"], int)


def test_ak_output_rate_accepts_numeric_strings(tmp_path: Path):
    assert save_settings({"akOutputRate": "30"}, tmp_path)["akOutputRate"] == 30
    assert save_settings({"akOutputRate": " 25 "}, tmp_path)["akOutputRate"] == 25


@pytest.mark.parametrize("value", [24, 60, 30.5, 25.0, "30fps", "", None, True, [30], {"rate": 30}])
def test_ak_output_rate_invalid_falls_back_to_default(tmp_path: Path, value):
    assert save_settings({"akOutputRate": value}, tmp_path)["akOutputRate"] == 25


@pytest.mark.parametrize("value", ["Keyer", "window", "", None, 1, True, ["keyer"]])
def test_ak_output_mode_invalid_falls_back_to_default(tmp_path: Path, value):
    assert save_settings({"akOutputMode": value}, tmp_path)["akOutputMode"] == "screen"


@pytest.mark.parametrize("value", ["OFF", "internal", "", None, 0, False, ["off"]])
def test_ak_keyer_invalid_falls_back_to_default(tmp_path: Path, value):
    assert save_settings({"akKeyer": value}, tmp_path)["akKeyer"] == "external"


def test_ak_output_values_survive_unrelated_load_patch_save(tmp_path: Path):
    save_settings({"akOutputMode": "keyer", "akOutputRate": 30, "akKeyer": "off"}, tmp_path)
    current = load_settings(tmp_path)
    current["reusePreviews"] = False
    save_settings(current, tmp_path)
    again = load_settings(tmp_path)
    assert (again["akOutputMode"], again["akOutputRate"], again["akKeyer"]) == ("keyer", 30, "off")
    assert again["reusePreviews"] is False


def test_ak_output_invalid_stored_values_load_as_defaults(tmp_path: Path):
    import json

    from obed_edom.settings import settings_path

    path = settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"akOutputMode": "hdmi", "akOutputRate": 50, "akKeyer": 1}), encoding="utf-8")
    got = load_settings(tmp_path)
    assert (got["akOutputMode"], got["akOutputRate"], got["akKeyer"]) == ("screen", 25, "external")

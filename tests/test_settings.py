from pathlib import Path

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

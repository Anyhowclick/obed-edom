"""Operator-tunable reuse settings. Stored under the cache root as settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from obed_edom.baseline import cache_root

DEFAULTS = {
    "reuseThreshold": 0.6,
    "reusePairings": True,
    "reusePreviews": True,
    "defaultExportDir": "",
}


def settings_path(root: Path | None = None) -> Path:
    return cache_root(root) / "settings.json"


def _clamp(data: dict) -> dict:
    out = dict(DEFAULTS)
    if "reuseThreshold" in data:
        try:
            value = float(data["reuseThreshold"])
        except (TypeError, ValueError):
            value = DEFAULTS["reuseThreshold"]
        out["reuseThreshold"] = min(1.0, max(0.0, value))
    if "reusePairings" in data:
        out["reusePairings"] = bool(data["reusePairings"])
    if "reusePreviews" in data:
        out["reusePreviews"] = bool(data["reusePreviews"])
    if "defaultExportDir" in data:
        out["defaultExportDir"] = str(data["defaultExportDir"] or "").strip()
    return out


def load_settings(root: Path | None = None) -> dict:
    path = settings_path(root)
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    return _clamp(data)


def save_settings(data: dict, root: Path | None = None) -> dict:
    out = _clamp(data)
    if out["defaultExportDir"]:
        from obed_edom.paths import validate_export_dir  # noqa: PLC0415

        out["defaultExportDir"] = str(validate_export_dir(out["defaultExportDir"]))
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out

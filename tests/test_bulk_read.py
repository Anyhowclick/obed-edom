"""Lock the OBED_BULK_READ flag and its plumbing into the JXA inspect plan.

The bulk-read path in inspect_keynote.js is byte-identical to the legacy
per-object path (guarded by a per-collection length check + fallback), so there
is nothing to assert about the payload here. What matters on the Python side is
that the flag defaults ON, that only an explicit off-value forces the legacy
path, and that whichever the flag resolves to actually reaches the JXA plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from obed_edom import inspect as inspect_mod
from obed_edom.inspect import bulk_read_enabled, inspect_keynote

# --- flag ------------------------------------------------------------------


def test_flag_on_by_default(monkeypatch):
    monkeypatch.delenv("OBED_BULK_READ", raising=False)
    assert bulk_read_enabled() is True


def test_flag_forced_off_values(monkeypatch):
    # Bulk read is the default; only an explicit off-value falls back to per-object.
    for value in ("0", "false", "FALSE", "no", "off", "  Off  "):
        monkeypatch.setenv("OBED_BULK_READ", value)
        assert bulk_read_enabled() is False
    for value in ("1", "true", "yes", "on", "", "anything"):
        monkeypatch.setenv("OBED_BULK_READ", value)
        assert bulk_read_enabled() is True


# --- plumbing into the JXA plan --------------------------------------------


def _capture_plan(monkeypatch):
    """Run inspect_keynote with osascript stubbed; return the plan dict it wrote."""
    captured: dict = {}

    def fake_popen(args, *a, **kw):
        # inspect_keynote calls: ["osascript", "-l", "JavaScript", JS, plan_path]
        plan_path = args[-1]
        captured["plan"] = json.loads(open(plan_path, encoding="utf-8").read())
        payload = {
            "path": captured["plan"]["path"],
            "slideWidth": 1920,
            "slideHeight": 1080,
            "slideCount": 0,
            "slides": [],
        }
        kw["stdout"].write(json.dumps(payload).encode())
        return SimpleNamespace(args=args, returncode=0, poll=lambda: 0)

    monkeypatch.setattr(inspect_mod.subprocess, "Popen", fake_popen)
    return captured


def test_plan_carries_bulk_read_on(tmp_path, monkeypatch):
    monkeypatch.delenv("OBED_BULK_READ", raising=False)
    captured = _capture_plan(monkeypatch)
    key = tmp_path / "deck.key"
    key.write_text("stub")
    inspect_keynote(key, use_cache=False)
    assert captured["plan"]["bulkRead"] is True


def test_plan_carries_bulk_read_off(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_BULK_READ", "0")
    captured = _capture_plan(monkeypatch)
    key = tmp_path / "deck.key"
    key.write_text("stub")
    inspect_keynote(key, use_cache=False)
    assert captured["plan"]["bulkRead"] is False


def test_use_cache_false_exports_into_export_dir_not_the_digest_cache(tmp_path, monkeypatch):
    # The resizer readback passes use_cache=False so the export lands in export_dir where
    # the dashboard serves it — NOT redirected into preview_cache_dir(digest) (the cache
    # miss branch, inspect.py:138-140), which left the served dir empty. Pin that the plan
    # exportDir the JXA pass writes to is export_dir itself.
    captured = _capture_plan(monkeypatch)
    monkeypatch.setattr(inspect_mod, "export_slide_images", lambda *a, **k: None)
    key = tmp_path / "deck.key"
    key.write_text("stub")
    export_dir = tmp_path / "job_previews"
    inspect_keynote(key, export_dir=export_dir, use_cache=False)
    assert captured["plan"]["exportDir"] == str(export_dir.resolve())


def test_successful_fallback_export_clears_stale_jxa_export_error(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")
    export_dir = tmp_path / "previews"

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"slideCount": 0, "slides": [], "exportError": "JXA export failed"}),
            stderr="",
        )

    def fake_export(_key_path, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "slide-1.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_keynote(key, export_dir=export_dir, use_cache=False)

    assert out["exported"] is True
    assert "exportError" not in out


def test_failed_fallback_export_keeps_its_error(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"slideCount": 0, "slides": [], "exportError": "old error"}),
            stderr="",
        )

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(inspect_mod, "export_slide_images", lambda *_args: "fallback failed")

    out = inspect_keynote(key, export_dir=tmp_path / "previews", use_cache=False)

    assert out["exported"] is False
    assert out["exportError"] == "fallback failed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

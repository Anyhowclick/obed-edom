"""Lock the OBED_BULK_READ flag and its plumbing into the JXA inspect plan.

The bulk-read path in inspect_keynote.js is byte-identical to the legacy
per-object path (guarded by a per-collection length check + fallback), so there
is nothing to assert about the payload here. What matters on the Python side is
that the flag defaults ON, that only an explicit off-value forces the legacy
path, and that whichever the flag resolves to actually reaches the JXA plan.
"""

from __future__ import annotations

import json
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

    def fake_run(args, *a, **kw):
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
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

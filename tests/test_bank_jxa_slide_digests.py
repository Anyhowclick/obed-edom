"""Keynote-free JXA digest-bank helpers (digest-bank-version-decouple)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom import baseline
from scripts import bank_jxa_slide_digests as banker


def _bank(**over) -> dict:
    base = {
        "bankVersion": 1,
        "inspectVersion": 4,
        "slideDigestVersion": 1,
        "deck": "Gold_Wall_Input.key",
        "sourceDigest": "a" * 64,
        "reader": "jxa",
        "slides": [{"slide": 0, "digest": "x", "skipped": False, "text": [], "images": []}],
        "slideCount": 1,
        "capturedUTC": "2026-01-01T00:00:00+00:00",
    }
    base.update(over)
    return base


def test_stamp_inspect_version_rewrites_only_version_and_timestamp(tmp_path):
    path = tmp_path / "gold.json"
    original = _bank()
    path.write_text(json.dumps(original))
    out = banker.stamp_inspect_version(path)
    written = json.loads(path.read_text())
    assert out == written
    assert written["inspectVersion"] == baseline.INSPECT_VERSION
    assert written["sourceDigest"] == original["sourceDigest"]
    assert written["slides"] == original["slides"]
    assert written["capturedUTC"] != original["capturedUTC"]


def test_stamp_cli_is_keynote_free(tmp_path, monkeypatch):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(_bank()))
    monkeypatch.setattr(banker, "bank_path", lambda _name: path)
    monkeypatch.setattr(banker, "DECKS", tmp_path / "missing-decks")
    monkeypatch.setattr(banker, "inspect_keynote", lambda *a, **k: pytest.fail("must not open Keynote"))
    assert banker.main(["--deck", "Gold_Wall_Input.key", "--stamp-inspect-version"]) == 0
    assert json.loads(path.read_text())["inspectVersion"] == baseline.INSPECT_VERSION


def test_stamp_cli_refuses_payload_and_drift_flags():
    with pytest.raises(SystemExit, match="Keynote-free"):
        banker.main([
            "--deck", "Gold_Wall_Input.key", "--stamp-inspect-version",
            "--payload", "x.json",
        ])
    with pytest.raises(SystemExit, match="Keynote-free"):
        banker.main([
            "--deck", "Gold_Wall_Input.key", "--stamp-inspect-version",
            "--accept-input-drift",
        ])


def test_stamp_cli_refuses_missing_bank(tmp_path, monkeypatch):
    monkeypatch.setattr(banker, "bank_path", lambda _name: tmp_path / "absent.json")
    with pytest.raises(SystemExit, match="no bank to stamp"):
        banker.main(["--deck", "Gold_Wall_Input.key", "--stamp-inspect-version"])


def test_stamp_cli_refuses_deck_digest_drift(tmp_path, monkeypatch):
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(_bank(sourceDigest="b" * 64)))
    deck_dir = tmp_path / "decks"
    deck_dir.mkdir()
    (deck_dir / "Gold_Wall_Input.key").write_bytes(b"not-the-banked-bytes")
    monkeypatch.setattr(banker, "bank_path", lambda _name: path)
    monkeypatch.setattr(banker, "DECKS", deck_dir)
    monkeypatch.setattr(baseline, "deck_digest", lambda _p: "c" * 64)
    with pytest.raises(SystemExit, match="digest drift"):
        banker.main(["--deck", "Gold_Wall_Input.key", "--stamp-inspect-version"])


def test_golden_plan_bank_ladder_does_not_pin_inspect_version():
    """A payload-shape bump must not fail the JXA digest bank (the digests ignore it)."""
    import inspect

    from tests import test_golden_plan as gp

    src = inspect.getsource(gp._bank_skip_ladder)
    assert 'slideDigestVersion' in src
    assert '("inspectVersion", baseline.INSPECT_VERSION)' not in src

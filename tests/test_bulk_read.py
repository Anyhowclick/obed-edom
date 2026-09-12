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

import pytest

from conftest import _fake_osascript
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

    def on_argv(args):
        # inspect_keynote calls: ["osascript", "-l", "JavaScript", JS, plan_path]
        plan_path = args[-1]
        captured["plan"] = json.loads(open(plan_path, encoding="utf-8").read())

    payload = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"index": 0, "number": 1, "skipped": False, "items": []}],
    }
    _fake_osascript(monkeypatch, stdout=json.dumps(payload), on_argv=on_argv)
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
    # miss branch). The JXA plan no longer carries an exportDir at all (item (a): the JXA
    # export never worked on 15.3.1 and was deleted); the AppleScript fallback exporter
    # is what actually writes into export_dir itself.
    captured = _capture_plan(monkeypatch)
    export_calls: list[Path] = []

    def fake_export(_key_path, dest, **_kwargs):
        export_calls.append(Path(dest))
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)
    key = tmp_path / "deck.key"
    key.write_text("stub")
    export_dir = tmp_path / "job_previews"
    inspect_keynote(key, export_dir=export_dir, use_cache=False)
    assert export_calls == [export_dir]
    assert "exportDir" not in captured["plan"]


def test_legacy_jxa_plan_never_carries_export_dir(tmp_path, monkeypatch):
    captured = _capture_plan(monkeypatch)
    monkeypatch.setattr(inspect_mod, "export_slide_images", lambda *a, **k: None)
    key = tmp_path / "deck.key"
    key.write_text("stub")
    inspect_keynote(key, export_dir=tmp_path / "previews", use_cache=False)
    assert "exportDir" not in captured["plan"]


def test_successful_fallback_export_clears_stale_jxa_export_error(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")
    export_dir = tmp_path / "previews"

    def fake_export(_key_path, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "slide-1.png").write_bytes(b"\x89PNG")
        return None

    _fake_osascript(
        monkeypatch,
        stdout=json.dumps({"slideCount": 0, "slides": [], "exportError": "JXA export failed"}),
    )
    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_keynote(key, export_dir=export_dir, use_cache=False)

    assert out["exported"] is True
    assert "exportError" not in out


def test_failed_fallback_export_keeps_its_error(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")

    _fake_osascript(
        monkeypatch,
        stdout=json.dumps(
            {
                "slideCount": 1,
                "slides": [{"index": 0, "number": 1, "skipped": False}],
                "exportError": "old error",
            }
        ),
    )
    monkeypatch.setattr(inspect_mod, "export_slide_images", lambda *_args, **_kwargs: "fallback failed")

    out = inspect_keynote(key, export_dir=tmp_path / "previews", use_cache=False)

    assert out["exported"] is False
    assert out["exportError"] == "fallback failed"


# --- legacy cache-hit / export-only (item d: ported from the checker, sans the
# reader=="offline" guard -- legacy cross-serves any cached payload) -----------


@pytest.fixture()
def cached_deck(tmp_path, monkeypatch) -> Path:
    from obed_edom.baseline import CACHE_DIR_ENV

    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "deck.key"
    path.write_bytes(b"not a real keynote, just bytes to hash")
    return path


def _seed_legacy_cache(deck: Path, payload: dict) -> Path:
    from obed_edom.baseline import deck_digest, inspect_cache_path

    json_path = inspect_cache_path(deck_digest(deck))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    return json_path


def _boom_jxa(monkeypatch):
    def boom(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("legacy JXA inspect must not run on an export-only hit")

    from obed_edom import osascript_runner

    monkeypatch.setattr(osascript_runner.subprocess, "Popen", boom)


def test_legacy_cache_hit_export_only_skips_jxa(cached_deck, monkeypatch, tmp_path):
    from obed_edom.baseline import deck_digest, preview_cache_dir

    _seed_legacy_cache(cached_deck, {"slideCount": 2,
                                      "slides": [{"index": 0, "number": 1, "items": []},
                                                 {"index": 1, "number": 2, "items": []}],
                                      "sentinel": "CACHED", "exportError": "old export failed"})
    _boom_jxa(monkeypatch)

    def fake_export(_key_path, export_dir, **kwargs):
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        for n in (1, 2):
            (export_dir / f"slide-{n}.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    png_dir = preview_cache_dir(deck_digest(cached_deck))
    assert not inspect_mod.preview_pngs(png_dir)

    out = inspect_keynote(cached_deck, export_dir=tmp_path / "job_previews", use_cache=True)

    assert out["sentinel"] == "CACHED"
    assert out["_cached"] is True
    assert out["exported"] is True
    assert "exportError" not in out
    assert out["previewDir"] == str(png_dir)
    assert "export" in out["_timing"]


def test_legacy_complete_preview_set_with_a_skipped_slide_is_a_hit(cached_deck, monkeypatch, tmp_path):
    from obed_edom.baseline import deck_digest, preview_cache_dir

    _seed_legacy_cache(cached_deck, {"slideCount": 3,
                                      "slides": [{"index": 0, "number": 1, "items": []},
                                                 {"index": 1, "number": 2, "items": [], "skipped": True},
                                                 {"index": 2, "number": 3, "items": []}],
                                      "sentinel": "CACHED", "exportError": "old export failed"})
    png_dir = preview_cache_dir(deck_digest(cached_deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    for n in (1, 3):
        (png_dir / f"slide-{n}.png").write_bytes(b"\x89PNG")

    _boom_jxa(monkeypatch)

    def boom_export(*_a, **_k):  # pragma: no cover
        raise AssertionError("a complete preview set (minus skipped) must be a warm hit")

    monkeypatch.setattr(inspect_mod, "export_slide_images", boom_export)

    out = inspect_keynote(cached_deck, export_dir=tmp_path / "job", use_cache=True)

    assert out["_cached"] is True
    assert out["exported"] is True
    assert "exportError" not in out
    assert "export" not in out["_timing"]


def test_legacy_partial_set_on_a_skipped_deck_still_re_exports(cached_deck, monkeypatch, tmp_path):
    from obed_edom.baseline import deck_digest, preview_cache_dir

    _seed_legacy_cache(cached_deck, {"slideCount": 3,
                                      "slides": [{"index": 0, "number": 1, "items": []},
                                                 {"index": 1, "number": 2, "items": [], "skipped": True},
                                                 {"index": 2, "number": 3, "items": []}],
                                      "sentinel": "CACHED"})
    png_dir = preview_cache_dir(deck_digest(cached_deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    (png_dir / "slide-1.png").write_bytes(b"\x89PNG")  # only 1 of the 2 expected

    _boom_jxa(monkeypatch)
    filled = {"calls": 0}

    def fake_export(_key_path, export_dir, **kwargs):
        filled["calls"] += 1
        (Path(export_dir) / "slide-3.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_keynote(cached_deck, export_dir=tmp_path / "job", use_cache=True)

    assert filled["calls"] == 1
    assert out["exported"] is True


def test_legacy_all_slides_skipped_empty_set_is_a_hit(cached_deck, monkeypatch, tmp_path):
    from obed_edom.baseline import deck_digest, preview_cache_dir

    _seed_legacy_cache(cached_deck, {"slideCount": 2,
                                      "slides": [{"index": 0, "number": 1, "items": [], "skipped": True},
                                                 {"index": 1, "number": 2, "items": [], "skipped": True}],
                                      "sentinel": "CACHED"})
    preview_cache_dir(deck_digest(cached_deck)).mkdir(parents=True, exist_ok=True)

    _boom_jxa(monkeypatch)

    def boom_export(*_a, **_k):  # pragma: no cover
        raise AssertionError("all-skipped empty set must be a warm hit")

    monkeypatch.setattr(inspect_mod, "export_slide_images", boom_export)

    out = inspect_keynote(cached_deck, export_dir=tmp_path / "job", use_cache=True)

    assert out["_cached"] is True
    assert "export" not in out["_timing"]


def test_legacy_partial_preview_set_is_not_served_as_a_hit(cached_deck, monkeypatch, tmp_path):
    from obed_edom.baseline import deck_digest, preview_cache_dir

    _seed_legacy_cache(cached_deck, {"slideCount": 2,
                                      "slides": [{"index": 0, "number": 1, "items": []},
                                                 {"index": 1, "number": 2, "items": []}],
                                      "sentinel": "CACHED"})
    png_dir = preview_cache_dir(deck_digest(cached_deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    (png_dir / "slide-1.png").write_bytes(b"\x89PNG")  # only 1 of 2

    _boom_jxa(monkeypatch)
    filled = {"calls": 0}

    def fake_export(_key_path, export_dir, **kwargs):
        filled["calls"] += 1
        (Path(export_dir) / "slide-2.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_keynote(cached_deck, export_dir=tmp_path / "job", use_cache=True)

    assert filled["calls"] == 1
    assert len(inspect_mod.preview_pngs(png_dir)) == 2
    assert out["exported"] is True


def test_legacy_cross_serves_offline_and_jxa_readers_alike(cached_deck, monkeypatch, tmp_path):
    """Legacy `inspect_keynote` has no `reader` gate (unlike the checker): a payload
    written by either reader is served as-is from the shared digest cache."""
    for reader in ("jxa", "offline"):
        _seed_legacy_cache(cached_deck, {"slideCount": 0, "slides": [], "reader": reader,
                                          "sentinel": f"CACHED-{reader}"})
        out = inspect_keynote(cached_deck, use_cache=True)
        assert out["sentinel"] == f"CACHED-{reader}"
        assert out["_cached"] is True


# --- bulk_geometry(): keep_open plumbing + default close behaviour for other
# callers (offline_write.py, remap_keynote.py, offline_inspect.py's non-folded
# path, scripts/probe_nested_bulk.py) -----------------------------------------


def _capture_bulk_plan(monkeypatch, *, kept_open: bool):
    captured: dict = {}

    def on_argv(args):
        plan_path = args[-1]
        captured["plan"] = json.loads(Path(plan_path).read_text(encoding="utf-8"))

    payload = {
        "slideCount": 0,
        "geometry": {},
        "errors": [],
        "errorCount": 0,
        "notes": [],
        "noteCount": 0,
        "keptOpen": kept_open,
    }
    _fake_osascript(monkeypatch, stdout=json.dumps(payload), on_argv=on_argv)
    return captured


def test_bulk_geometry_default_call_carries_no_keep_open(tmp_path, monkeypatch):
    captured = _capture_bulk_plan(monkeypatch, kept_open=False)
    key = tmp_path / "deck.key"
    key.write_text("stub")

    inspect_mod.bulk_geometry(key)

    assert "keepOpen" not in captured["plan"]
    assert inspect_mod.LAST_BULK_KEPT_OPEN is None


def test_bulk_geometry_keep_open_true_sets_plan_and_last_kept_open(tmp_path, monkeypatch):
    captured = _capture_bulk_plan(monkeypatch, kept_open=True)
    key = tmp_path / "deck.key"
    key.write_text("stub")

    inspect_mod.bulk_geometry(key, keep_open=True)

    assert captured["plan"]["keepOpen"] is True
    assert inspect_mod.LAST_BULK_KEPT_OPEN == str(key.resolve())


def test_bulk_geometry_resets_last_kept_open_every_call(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")

    _capture_bulk_plan(monkeypatch, kept_open=True)
    inspect_mod.bulk_geometry(key, keep_open=True)
    assert inspect_mod.LAST_BULK_KEPT_OPEN == str(key.resolve())

    _capture_bulk_plan(monkeypatch, kept_open=False)
    inspect_mod.bulk_geometry(key)
    assert inspect_mod.LAST_BULK_KEPT_OPEN is None


def test_bulk_geometry_keep_open_closes_by_name_on_invalid_json(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")
    closed: list[Path] = []

    _fake_osascript(monkeypatch, stdout="not json")
    monkeypatch.setattr(
        inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p))
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        inspect_mod.bulk_geometry(key, keep_open=True)

    assert closed == [key.resolve()]
    assert inspect_mod.LAST_BULK_KEPT_OPEN is None


def test_bulk_geometry_default_no_close_by_name_on_invalid_json(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")
    closed: list[Path] = []

    _fake_osascript(monkeypatch, stdout="not json")
    monkeypatch.setattr(
        inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p))
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        inspect_mod.bulk_geometry(key)

    assert closed == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

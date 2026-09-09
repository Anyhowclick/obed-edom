"""Cache-serving behaviour of ``inspect.inspect_keynote_checker`` (Keynote-free).

Exercises the two follow-ups on the checker's digest cache block:

* the REVERSE cross-serve guard — a runs-less JXA (or legacy reader-less) payload
  cached under the shared digest must NOT be served to the checker; it rebuilds;
* the cache-hit export-only path — a cached-JSON-present / previews-evicted state
  runs ONLY the export, never the offline+bulk rebuild.

The offline builder and the Keynote export are both stubbed, so no deck is decoded
and Keynote is never opened; the deck file is a throwaway of arbitrary bytes.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from obed_edom import inspect as inspect_mod
from obed_edom.baseline import (
    CACHE_DIR_ENV,
    deck_digest,
    inspect_cache_path,
    preview_cache_dir,
)


@pytest.fixture()
def deck(tmp_path, monkeypatch) -> Path:
    """A throwaway .key file with the cache redirected under tmp."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "deck.key"
    path.write_bytes(b"not a real keynote, just bytes to hash")
    return path


def _seed_cache(deck: Path, payload: dict) -> Path:
    json_path = inspect_cache_path(deck_digest(deck))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    return json_path


@pytest.mark.parametrize("reader", ["jxa", None])
def test_non_offline_cached_payload_is_rejected_and_rebuilt(deck, monkeypatch, reader):
    # A JXA (runs-less) or legacy reader-less payload sits in the shared digest cache.
    seeded = {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
              "sentinel": "CACHED"}
    if reader is not None:
        seeded["reader"] = reader
    _seed_cache(deck, seeded)

    calls = {"n": 0}

    def spy_build(key_path, bulk_geometry_fn, **kwargs):
        calls["n"] += 1
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "sentinel": "REBUILT", "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    # No dest => no export, no Keynote. The cached non-offline payload must be
    # rejected and the offline builder invoked instead.
    out = inspect_mod.inspect_keynote_checker(deck, use_cache=True)
    assert calls["n"] == 1, "rebuild must run when the cached payload is not offline"
    assert out["sentinel"] == "REBUILT"
    assert out["reader"] == "offline"


def test_offline_cached_payload_is_served_without_rebuild(deck, monkeypatch):
    # The positive control: an offline-reader payload IS served (builder untouched).
    _seed_cache(deck, {"reader": "offline", "slideCount": 1,
                       "slides": [{"index": 0, "number": 1, "items": []}],
                       "sentinel": "CACHED"})

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("builder must not run on a valid offline cache hit")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)
    out = inspect_mod.inspect_keynote_checker(deck, use_cache=True)
    assert out["sentinel"] == "CACHED"
    assert out["_cached"] is True


def test_cache_hit_export_only_skips_the_rebuild(deck, monkeypatch, tmp_path):
    # Cached JSON present + preview dir empty + dest set: export ONLY, never rebuild.
    _seed_cache(deck, {"reader": "offline", "slideCount": 2,
                       "slides": [{"index": 0, "number": 1, "items": []},
                                  {"index": 1, "number": 2, "items": []}],
                       "sentinel": "CACHED", "exportError": "old export failed"})

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("offline+bulk rebuild must not run when only export is needed")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)
    monkeypatch.setattr(inspect_mod, "inspect_keynote", boom)

    exported: dict = {"calls": 0}

    def fake_export(key_path, export_dir, **kwargs):
        # Stand in for Keynote: drop the full (skipped:false) preview set.
        exported["calls"] += 1
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        for n in (1, 2):
            (export_dir / f"slide-{n}.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    dest = tmp_path / "job_previews"
    png_dir = preview_cache_dir(deck_digest(deck))
    assert not inspect_mod.preview_pngs(png_dir)  # evicted / empty

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=dest, use_cache=True)

    assert exported["calls"] == 1, "export must run exactly once"
    assert out["sentinel"] == "CACHED", "payload is the cache hit, not a rebuild"
    assert out["_cached"] is True
    assert out["exported"] is True
    assert "exportError" not in out
    # Export lands in the digest-keyed preview cache dir (want_cache), served from there.
    assert out["previewDir"] == str(png_dir)
    assert len(inspect_mod.preview_pngs(png_dir)) == 2
    assert "export" in out["_timing"]


def test_complete_preview_set_with_a_skipped_slide_is_a_hit(deck, monkeypatch, tmp_path):
    # A skipped slide gets NO preview (export uses skipped slides:false), so a COMPLETE
    # set is one PNG per non-skipped slide (2 of 3 here) — this must be served as a warm
    # hit, not re-exported every run. Guards the off-by-skipped-count fix.
    _seed_cache(deck, {"reader": "offline", "slideCount": 3,
                       "slides": [{"index": 0, "number": 1, "items": []},
                                  {"index": 1, "number": 2, "items": [], "skipped": True},
                                  {"index": 2, "number": 3, "items": []}],
                       "sentinel": "CACHED", "exportError": "old export failed"})
    png_dir = preview_cache_dir(deck_digest(deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    for n in (1, 3):  # only the 2 non-skipped slides have a PNG
        (png_dir / f"slide-{n}.png").write_bytes(b"\x89PNG")

    def boom(*a, **k):  # pragma: no cover - neither may run on a complete-set hit
        raise AssertionError("a complete preview set (minus skipped) must be a warm hit")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)
    monkeypatch.setattr(inspect_mod, "export_slide_images", boom)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)
    assert out["_cached"] is True
    assert out["sentinel"] == "CACHED"
    assert out["previewDir"] == str(png_dir)
    assert out["exported"] is True
    assert "exportError" not in out
    assert "export" not in out["_timing"], "no re-export on a complete-set hit"


def test_partial_set_on_a_skipped_deck_still_re_exports(deck, monkeypatch, tmp_path):
    # Intersection of the two behaviours: a deck WITH a skipped slide but an INCOMPLETE
    # preview set (1 PNG when 2 non-skipped slides are expected) must NOT be served — the
    # skipped-count fix must narrow the hit, not over-serve a genuinely partial set.
    _seed_cache(deck, {"reader": "offline", "slideCount": 3,
                       "slides": [{"index": 0, "number": 1, "items": []},
                                  {"index": 1, "number": 2, "items": [], "skipped": True},
                                  {"index": 2, "number": 3, "items": []}],
                       "sentinel": "CACHED"})
    png_dir = preview_cache_dir(deck_digest(deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    (png_dir / "slide-1.png").write_bytes(b"\x89PNG")  # only 1 of the 2 expected

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("rebuild must not run")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)

    filled: dict = {"calls": 0}

    def fake_export(key_path, export_dir, **kwargs):
        filled["calls"] += 1
        (Path(export_dir) / "slide-3.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)
    assert filled["calls"] == 1, "a partial set on a skipped deck must still re-export"
    assert out["exported"] is True


def test_all_slides_skipped_empty_set_is_a_hit(deck, monkeypatch, tmp_path):
    # Degenerate case: every slide skipped => expected_pngs == 0, so an empty preview dir
    # IS a complete set and must be served as a hit with no export.
    _seed_cache(deck, {"reader": "offline", "slideCount": 2,
                       "slides": [{"index": 0, "number": 1, "items": [], "skipped": True},
                                  {"index": 1, "number": 2, "items": [], "skipped": True}],
                       "sentinel": "CACHED"})
    preview_cache_dir(deck_digest(deck)).mkdir(parents=True, exist_ok=True)  # empty

    def boom(*a, **k):  # pragma: no cover - neither may run
        raise AssertionError("all-skipped empty set must be a warm hit")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)
    monkeypatch.setattr(inspect_mod, "export_slide_images", boom)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)
    assert out["_cached"] is True
    assert out["sentinel"] == "CACHED"
    assert "export" not in out["_timing"]


def test_partial_preview_set_is_not_served_as_a_hit(deck, monkeypatch, tmp_path):
    # Hardened hit: a partial preview set (< slideCount) must NOT be served as a hit;
    # the export-only path re-runs the export instead of returning the partial dir.
    _seed_cache(deck, {"reader": "offline", "slideCount": 2,
                       "slides": [{"index": 0, "number": 1, "items": []},
                                  {"index": 1, "number": 2, "items": []}],
                       "sentinel": "CACHED"})
    png_dir = preview_cache_dir(deck_digest(deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    (png_dir / "slide-1.png").write_bytes(b"\x89PNG")  # only 1 of 2

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("rebuild must not run")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)

    filled: dict = {"calls": 0}

    def fake_export(key_path, export_dir, **kwargs):
        filled["calls"] += 1
        (Path(export_dir) / "slide-2.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)
    assert filled["calls"] == 1, "a partial set must trigger a re-export, not a hit"
    assert len(inspect_mod.preview_pngs(png_dir)) == 2
    assert out["exported"] is True


def test_cache_hit_repair_osascript_failure_with_stale_png_reports_error(deck, monkeypatch, tmp_path):
    """BLOCKER 4: a partial/stale preview set present before a failed re-export must
    not be read back as success -- the real ``export_slide_images`` -> ``osascript``
    path is exercised end to end (only ``subprocess.run`` is stubbed)."""
    _seed_cache(deck, {"reader": "offline", "slideCount": 2,
                       "slides": [{"index": 0, "number": 1, "items": []},
                                  {"index": 1, "number": 2, "items": []}],
                       "sentinel": "CACHED"})
    png_dir = preview_cache_dir(deck_digest(deck))
    png_dir.mkdir(parents=True, exist_ok=True)
    (png_dir / "slide-1.png").write_bytes(b"\x89PNG")  # stale, only 1 of 2 expected

    monkeypatch.setattr(inspect_mod, "_build_checker_offline",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("rebuild must not run")))

    def fake_run(args, **kwargs):
        if args[0] == "open":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="export bound wrong document")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(inspect_mod.time, "sleep", lambda s: None)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)

    assert out["exported"] is False
    assert out["exportError"] == "Preview export failed: export bound wrong document"


def test_cache_written_payload_keeps_bulk_errors(deck, monkeypatch):
    """bulkErrors (non-underscore) must survive the cache-write's underscore strip --
    unlike `_offline.bulk_errors`, which lives under a stripped "_offline" key. This is
    what makes a silent-partial bulk read durable evidence in a LATER cache hit."""
    sample_errors = [{"slide": 5, "kind": "movie", "where": "collection", "error": "boom"}]

    def fake_build(key_path, bulk_geometry_fn, **kwargs):
        return {
            "slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
            "bulkErrors": sample_errors,
            "_offline": {"bulk_ok": True, "fallback_slides": [], "bulk_errors": sample_errors},
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", fake_build)

    inspect_mod.inspect_keynote_checker(deck, use_cache=True)

    json_path = inspect_cache_path(deck_digest(deck))
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert stored["bulkErrors"] == sample_errors
    assert "_offline" not in stored  # underscore keys ARE stripped -- confirms the contrast


def test_cache_hit_with_bulk_errors_warns_loudly(deck, monkeypatch):
    sample_errors = [{"slide": 5, "kind": "movie", "where": "collection", "error": "boom"}]
    _seed_cache(deck, {"reader": "offline", "slideCount": 1,
                       "slides": [{"index": 0, "number": 1, "items": []}],
                       "bulkErrors": sample_errors})

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("builder must not run on a valid offline cache hit")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)

    logged = []
    out = inspect_mod.inspect_keynote_checker(deck, use_cache=True, log=logged.append)
    assert out["_cached"] is True
    assert any("bulk-geometry error" in m for m in logged), logged


def test_cache_hit_without_bulk_errors_does_not_warn(deck, monkeypatch):
    _seed_cache(deck, {"reader": "offline", "slideCount": 1,
                       "slides": [{"index": 0, "number": 1, "items": []}]})

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("builder must not run on a valid offline cache hit")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)

    logged = []
    inspect_mod.inspect_keynote_checker(deck, use_cache=True, log=logged.append)
    assert logged == []


# --- checker export fold: keepOpen handoff ---------------------------------


def test_keep_open_requested_only_when_exporting(deck, monkeypatch, tmp_path):
    calls: dict = {}

    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        calls["keep_open"] = keep_open
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    def boom_export(*a, **k):  # pragma: no cover - must not run, this test is about the flag
        raise AssertionError("export must not run in this test")

    monkeypatch.setattr(inspect_mod, "export_slide_images", boom_export)
    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", boom_export)

    inspect_mod.inspect_keynote_checker(deck, use_cache=False)
    assert calls["keep_open"] is False

    with pytest.raises(AssertionError):
        inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)
    assert calls["keep_open"] is True


def _boom_close(*a, **k):  # pragma: no cover - must not run in a Keynote-free test
    raise AssertionError("_close_document_by_name must not run: no leaked doc to close here")


def test_folded_export_uses_the_already_open_form_when_bulk_kept_it_open(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", _boom_close)

    open_calls: list[Path] = []
    standalone_calls: list[Path] = []

    def fake_open_export(key_path, export_dir, **kwargs):
        open_calls.append(Path(export_dir))
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide-1.png").write_bytes(b"\x89PNG")
        return None

    def boom_standalone(*a, **k):  # pragma: no cover
        raise AssertionError("the already-open handoff must not also run a standalone export")

    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", fake_open_export)
    monkeypatch.setattr(inspect_mod, "export_slide_images", boom_standalone)

    dest = tmp_path / "job"
    out = inspect_mod.inspect_keynote_checker(deck, export_dir=dest, use_cache=False)

    assert open_calls == [dest]
    assert standalone_calls == []
    assert out["exported"] is True
    assert "exportError" not in out
    assert inspect_mod.LAST_BULK_KEPT_OPEN is None


def test_fold_falls_back_to_standalone_export_when_bulk_never_opened_a_doc(deck, monkeypatch, tmp_path):
    """DRIFT-4: wanted==[] (or any path where bulk_geometry_fn is never actually
    invoked) must leave `LAST_BULK_KEPT_OPEN` unset for THIS deck -- the fold falls
    back to the ordinary fresh-open-and-close standalone exporter, never the
    already-open form. A stale value stamped with a DIFFERENT deck's path (BLOCKER 5)
    must not be trusted either."""

    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        # bulk_geometry_fn is never called (mirrors offline_inspect's `wanted == []`).
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", _boom_close)
    inspect_mod.LAST_BULK_KEPT_OPEN = str(Path("/some/other/deck.key").resolve())

    standalone_calls: list[Path] = []

    def fake_standalone(key_path, export_dir, **kwargs):
        standalone_calls.append(Path(export_dir))
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide-1.png").write_bytes(b"\x89PNG")
        return None

    def boom_open(*a, **k):  # pragma: no cover
        raise AssertionError("must not use the already-open form when bulk never kept a doc open")

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_standalone)
    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", boom_open)

    dest = tmp_path / "job"
    out = inspect_mod.inspect_keynote_checker(deck, export_dir=dest, use_cache=False)

    assert standalone_calls == [dest]
    assert out["exported"] is True


def test_folded_export_failure_is_surfaced_once_and_does_not_fail_geometry(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    closed: list[Path] = []
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    attempts = {"calls": 0}

    def failing_open_export(key_path, export_dir, **kwargs):
        attempts["calls"] += 1
        return "export bound wrong document"

    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", failing_open_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert attempts["calls"] == 1
    assert out["exported"] is False
    assert out["exportError"] == "export bound wrong document"
    assert out["slideCount"] == 1  # geometry payload survives the export failure
    assert closed == [deck.resolve()]


def test_folded_export_exception_does_not_fail_geometry(deck, monkeypatch, tmp_path):
    """An exception from `_export_open_slide_images` must not clear ownership: the
    outer `finally` (not the exporter, which never ran to completion) closes the doc."""

    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    closed: list[Path] = []
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    def boom_open_export(*a, **k):
        raise RuntimeError("osascript crashed")

    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", boom_open_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert closed == [deck.resolve()]
    assert out["exported"] is False
    assert out["exportError"] == "osascript crashed"
    assert out["slideCount"] == 1


def test_read_and_export_timings_both_present_and_non_negative(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                "_offline": {"bulk_ok": True, "fallback_slides": []}}

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    def fake_open_export(key_path, export_dir, **kwargs):
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide-1.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", fake_open_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert out["_timing"]["read"] >= 0
    assert out["_timing"]["export"] >= 0


# --- cleanup guarantee: kept-open doc is always closed (R0.4 review BLOCKER 1) ----


def test_builder_exception_after_kept_open_closes_via_finally(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        raise RuntimeError("iwa decode blew up after bulk left the doc open")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    closed: list[Path] = []
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    def fake_legacy(*a, **k):
        return {"slideCount": 0, "slides": []}

    monkeypatch.setattr(inspect_mod, "inspect_keynote", fake_legacy)

    inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert closed == [deck.resolve()]


def test_narrow_merge_exception_after_kept_open_closes_via_finally(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {
            "slideCount": 1,
            "slides": [{"index": 0, "number": 1, "items": []}],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [],
                "fallback": [{"slide": 1, "kind": "text", "kindIndex": 0}],
            },
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    closed: list[Path] = []
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    def boom_merge(*a, **k):
        raise RuntimeError("inspect_items crashed")

    monkeypatch.setattr(inspect_mod, "_merge_legacy_items", boom_merge)

    with pytest.raises(RuntimeError, match="inspect_items crashed"):
        inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert closed == [deck.resolve()]


def test_legacy_cache_hit_fallback_after_kept_open_still_closes(deck, monkeypatch, tmp_path):
    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        inspect_mod.LAST_BULK_KEPT_OPEN = str(Path(key_path).resolve())
        return {
            "slideCount": 1,
            "slides": [{"index": 0, "number": 1, "items": []}],
            "_offline": {"bulk_ok": False, "fallback_slides": [1], "fallback": []},
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    closed: list[Path] = []
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    def fake_legacy(*a, **k):
        return {"slideCount": 0, "slides": [], "sentinel": "LEGACY"}

    monkeypatch.setattr(inspect_mod, "inspect_keynote", fake_legacy)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=False)

    assert out["sentinel"] == "LEGACY"
    assert closed == [deck.resolve()]


def test_all_skipped_real_traversal_never_opens_bulk_and_needs_no_export(deck, monkeypatch, tmp_path):
    """A REAL (unmocked) `_build_checker_offline` / `two_tier_wall_payload` traversal:
    an all-skipped deck never reaches `bulk_geometry_fn`, so `LAST_BULK_KEPT_OPEN` stays
    unset for this deck; expected PNGs is 0, already satisfied by an empty dest, so
    neither exporter form runs and the fold still reports success."""
    from obed_edom import iwa_runs, offline_inspect

    def fake_offline_wall_payload(key_path, slide_range=None, *, deck=None):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 3,
            "slides": [{"index": i, "number": i + 1, "skipped": True, "items": []}
                       for i in range(3)],
            "_offline": {"guard": [], "soft_geometry": []},
        }

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", fake_offline_wall_payload)
    monkeypatch.setattr(iwa_runs, "_load_deck", lambda key_path: ({}, {}, {}))

    def boom_bulk(*a, **k):
        raise AssertionError("bulk_geometry must not run for an all-skipped deck")

    monkeypatch.setattr(inspect_mod, "bulk_geometry", boom_bulk)
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", _boom_close)

    standalone_calls: list[Path] = []

    def fake_standalone(key_path, export_dir, **kwargs):
        standalone_calls.append(Path(export_dir))
        return None

    def boom_open(*a, **k):  # pragma: no cover
        raise AssertionError("must not use the already-open form: bulk never opened a doc")

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_standalone)
    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", boom_open)

    dest = tmp_path / "job"
    out = inspect_mod.inspect_keynote_checker(deck, export_dir=dest, use_cache=False)

    assert standalone_calls == []  # expected PNGs is 0, already satisfied
    assert inspect_mod.LAST_BULK_KEPT_OPEN is None
    assert out["slideCount"] == 3
    assert out["exported"] is True


def test_lock_blocks_a_racing_reset_from_clearing_kept_open_ownership(deck, tmp_path, monkeypatch):
    """The `LAST_BULK_KEPT_OPEN = None` reset lives inside the locked transaction; a
    second checker call must block on the lock before it can run that reset, so it
    can never clear a lock-holder's just-stamped ownership."""
    deck_b = tmp_path / "deck-b.key"
    deck_b.write_bytes(b"other deck bytes")

    a_ready = threading.Event()
    release_a = threading.Event()
    b_entered = threading.Event()
    ownership_seen_by_a: list[str | None] = []

    def dispatch_offline(key_path, bulk_geometry_fn, *, slide_range=None, keep_open=False, log=None):
        key_path = Path(key_path)
        if key_path.name == "deck.key":
            inspect_mod.LAST_BULK_KEPT_OPEN = str(key_path.resolve())
            a_ready.set()
            assert release_a.wait(timeout=5)
            return {"slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
                    "_offline": {"bulk_ok": True, "fallback_slides": []}}
        b_entered.set()
        return {"slideCount": 0, "slides": [], "_offline": {"bulk_ok": True, "fallback_slides": []}}

    closed: list[Path] = []

    def failing_open_export(key_path, export_dir, **kwargs):
        ownership_seen_by_a.append(inspect_mod.LAST_BULK_KEPT_OPEN)
        return "export bound wrong document"

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", dispatch_offline)
    monkeypatch.setattr(inspect_mod, "_export_open_slide_images", failing_open_export)
    monkeypatch.setattr(inspect_mod, "_close_document_by_name", lambda p: closed.append(Path(p)))

    result_a: dict[str, Any] = {}

    def run_a():
        result_a["out"] = inspect_mod.inspect_keynote_checker(
            deck, export_dir=tmp_path / "job", use_cache=False
        )

    thread_a = threading.Thread(target=run_a)
    thread_a.start()
    assert a_ready.wait(timeout=5)

    thread_b = threading.Thread(
        target=lambda: inspect_mod.inspect_keynote_checker(deck_b, use_cache=False)
    )
    thread_b.start()

    assert not b_entered.wait(timeout=0.3)
    assert inspect_mod.LAST_BULK_KEPT_OPEN == str(deck.resolve())

    release_a.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    assert ownership_seen_by_a == [str(deck.resolve())]
    assert closed == [deck.resolve()]
    assert result_a["out"]["exported"] is False

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
from pathlib import Path

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

    def spy_build(key_path, bulk_geometry_fn):
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
                       "sentinel": "CACHED"})

    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("offline+bulk rebuild must not run when only export is needed")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)

    exported: dict = {"calls": 0}

    def fake_export(key_path, export_dir):
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
                       "sentinel": "CACHED"})
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

    def fake_export(key_path, export_dir):
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

    def fake_export(key_path, export_dir):
        filled["calls"] += 1
        (Path(export_dir) / "slide-2.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=tmp_path / "job", use_cache=True)
    assert filled["calls"] == 1, "a partial set must trigger a re-export, not a hit"
    assert len(inspect_mod.preview_pngs(png_dir)) == 2
    assert out["exported"] is True

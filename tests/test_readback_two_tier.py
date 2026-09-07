"""R2 (`r-readback-two-tier`): the validated-resize readback routes to the two-tier
offline+bulk checker, fail-safe to legacy JXA, cache off, ranged supported. Keynote-free
(``_build_checker_offline``, ``inspect_keynote``, ``inspect_keynote_checker`` and
``export_slide_images`` are all stubbed; no deck is ever decoded or opened).

Two layers are exercised:
  - `remap_and_inspect`'s `_readback_payload` ladder (force-legacy on offline-write
    verify, env kill switch, package-directory dest, checker-raises fail-safe);
  - `inspect_keynote_checker` itself (ranged subsetting/no-cache, ranged legacy
    fallback threading, uncached export target, cache-blind `use_cache=False`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom import inspect as inspect_mod
from obed_edom import remap_keynote as rk
from obed_edom.baseline import CACHE_DIR_ENV, deck_digest, inspect_cache_path, preview_cache_dir


def _fake_remap(*, exported: bool = False, offline_write: dict | None = None):
    def fake_remap(source, dest, *, export_dir=None, **kwargs):
        info: dict = {"dest": str(dest), "exported": exported}
        if offline_write is not None:
            info["offlineWrite"] = offline_write
        return info

    return fake_remap


def _fake_legacy_payload(**overrides):
    payload = {"slideWidth": 1920, "slideHeight": 1080, "slideCount": 1, "slides": []}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# `_readback_payload` ladder, via `remap_and_inspect`
# ---------------------------------------------------------------------------


def test_validate_true_routes_to_checker(monkeypatch, tmp_path):
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap())
    calls = {}

    def fake_checker(dest, *, export_dir=None, slide_range=None, use_cache=None, log=None):
        calls["export_dir"] = export_dir
        calls["slide_range"] = slide_range
        calls["use_cache"] = use_cache
        return _fake_legacy_payload()

    monkeypatch.setattr(rk, "inspect_keynote_checker", fake_checker)
    legacy_calls = []
    monkeypatch.setattr(rk, "inspect_keynote", lambda *a, **k: legacy_calls.append(1) or {})

    previews = tmp_path / "previews"
    rk.remap_and_inspect(
        tmp_path / "wall.key",
        tmp_path / "out.key",
        template=tmp_path / "tpl.key",
        export_dir=previews,
        slide_range=frozenset({2, 3}),
        validate=True,
    )

    assert calls["use_cache"] is False
    assert calls["export_dir"] == previews
    assert calls["slide_range"] == frozenset({2, 3})
    assert legacy_calls == []


def test_offline_read_off_env_uses_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("OBED_OFFLINE_READ", "off")
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap())
    checker_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote_checker", lambda *a, **k: checker_calls.append(1) or {}
    )
    legacy_calls = {}

    def fake_legacy(dest, *, export_dir=None, slide_range=None, use_cache=None):
        legacy_calls["use_cache"] = use_cache
        return _fake_legacy_payload()

    monkeypatch.setattr(rk, "inspect_keynote", fake_legacy)

    rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True,
    )

    assert legacy_calls["use_cache"] is False
    assert checker_calls == []


def test_package_directory_dest_uses_legacy_with_log(monkeypatch, tmp_path):
    """SHOULD-FIX-3: the package-directory arm must thread `slide_range` through to legacy
    like every other arm of the ladder -- dropping it silently un-scopes a ranged validated
    resize to a whole-deck legacy read (regression vs b6039ef, and exactly the harm AM-5
    argues against)."""
    dest = tmp_path / "out.key"
    dest.mkdir()  # a package-directory save, not a zip
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap())
    checker_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote_checker", lambda *a, **k: checker_calls.append(1) or {}
    )
    legacy_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(k) or _fake_legacy_payload(),
    )
    logged: list[str] = []

    rk.remap_and_inspect(
        tmp_path / "wall.key", dest, template=tmp_path / "tpl.key",
        slide_range=frozenset({2}), validate=True, log=logged.append,
    )

    assert checker_calls == []
    assert legacy_calls
    assert legacy_calls[0]["slide_range"] == frozenset({2})
    assert any("package directory" in m for m in logged)


def test_checker_raises_falls_back_to_legacy_with_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap())

    def boom_checker(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rk, "inspect_keynote_checker", boom_checker)
    legacy_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(k) or _fake_legacy_payload(),
    )
    logged: list[str] = []

    rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True, log=logged.append,
    )

    assert legacy_calls  # readback never raises past the checker failure
    assert any("Two-tier readback failed" in m for m in logged)


def test_readback_payload_reraises_legacy_inspect_failed_without_extra_legacy_calls(
    monkeypatch, tmp_path,
):
    """BLOCKER-2(a): `LegacyInspectFailed` means legacy already ran and failed inside the
    checker -- `_readback_payload` must re-raise it, not retry legacy a second time."""
    dest = tmp_path / "out.key"

    def boom_checker(*a, **k):
        raise rk.LegacyInspectFailed("legacy already ran and failed")

    monkeypatch.setattr(rk, "inspect_keynote_checker", boom_checker)
    legacy_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(1) or _fake_legacy_payload(),
    )

    with pytest.raises(rk.LegacyInspectFailed):
        rk._readback_payload(dest, None, None, None)

    assert legacy_calls == []


def test_readback_payload_plain_exception_falls_back_to_legacy_exactly_once(
    monkeypatch, tmp_path,
):
    """BLOCKER-2(b): a plain (non-sentinel) exception out of the checker is the fail-safe
    arm -- legacy must run exactly once and the readback must complete."""
    dest = tmp_path / "out.key"

    def boom_checker(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(rk, "inspect_keynote_checker", boom_checker)
    legacy_calls = []
    legacy_payload = _fake_legacy_payload()
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(1) or legacy_payload,
    )

    out = rk._readback_payload(dest, None, None, None)

    assert legacy_calls == [1]
    assert out is legacy_payload


def test_arm_c_merge_failure_falls_back_to_legacy_once_not_reraised(monkeypatch, tmp_path):
    """BLOCKER-2(c) / post-BLOCKER-1-fix: arm C's `_merge_legacy_items`/`_merge_legacy_slides`
    calls are narrow reads, not a whole-deck legacy read, so a failure there (Keynote or
    pure-Python) must escape `inspect_keynote_checker` as a plain exception -- never
    relabelled `LegacyInspectFailed` -- so `_readback_payload`'s fail-safe still runs one
    whole-deck legacy read and the resize completes. Fails on b50d22b's src: arm C wrapped
    the merge calls in `LegacyInspectFailed`, which `_readback_payload` re-raises instead of
    falling back."""
    dest = tmp_path / "out.key"
    dest.write_bytes(b"not a real keynote, just bytes to hash")

    def spy_build(key_path, bulk_geometry_fn, **kwargs):
        return {
            "slideCount": 1,
            "slides": [{"index": 0, "number": 1, "items": []}],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [],
                "fallback": [{"slide": 1, "kind": "shape", "kindIndex": 0}],
            },
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)
    monkeypatch.setattr(
        inspect_mod, "_merge_legacy_items",
        lambda *a, **k: (_ for _ in ()).throw(TypeError("boom")),
    )
    legacy_calls = []
    legacy_payload = _fake_legacy_payload()
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(1) or legacy_payload,
    )

    out = rk._readback_payload(dest, None, None, None)

    assert legacy_calls == [1]
    assert out is legacy_payload


def test_offline_write_verify_mode_forces_legacy_readback(monkeypatch, tmp_path):
    """AM-2: `verify_live_frames` is an independent oracle beside `verify_offline_frames` --
    a two-tier readback would self-confirm the shape/line frames the offline patch just
    wrote (they never ride the bulk tier), so verify mode must skip the checker entirely."""
    offline_write_info = {"mode": "verify", "specs": {}, "statSlides": []}
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap(offline_write=offline_write_info))
    checker_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote_checker", lambda *a, **k: checker_calls.append(1) or {}
    )
    legacy_calls = []
    monkeypatch.setattr(
        rk, "inspect_keynote",
        lambda *a, **k: legacy_calls.append(k) or _fake_legacy_payload(),
    )
    logged: list[str] = []

    rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        validate=True, log=logged.append,
    )

    assert checker_calls == []
    assert legacy_calls
    assert any("Offline-write verify is on" in m for m in logged)


def test_remap_and_inspect_preview_files_from_checker_export(monkeypatch, tmp_path):
    """AM-8 (remap_and_inspect level): the checker's own export lands in `export_dir` and
    `previewFiles`/`exported` are read from it, exactly as with the legacy readback."""
    monkeypatch.setattr(rk, "remap_keynote", _fake_remap())

    def fake_checker(dest, *, export_dir=None, slide_range=None, use_cache=None, log=None):
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide.001.png").write_bytes(b"\x89PNG")
        return _fake_legacy_payload(exported=True)

    monkeypatch.setattr(rk, "inspect_keynote_checker", fake_checker)

    info = rk.remap_and_inspect(
        tmp_path / "wall.key", tmp_path / "out.key", template=tmp_path / "tpl.key",
        export_dir=tmp_path / "previews", validate=True,
    )

    assert info["previewFiles"] == ["slide.001.png"]
    assert info["inspect"]["exported"] is True


# ---------------------------------------------------------------------------
# `inspect_keynote_checker` itself: ranged subsetting, ranged fallback, export
# target and cache-blindness.
# ---------------------------------------------------------------------------


@pytest.fixture()
def deck(tmp_path, monkeypatch) -> Path:
    """A throwaway .key file with the cache redirected under tmp (test_inspect_checker.py idiom)."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "deck.key"
    path.write_bytes(b"not a real keynote, just bytes to hash")
    return path


def test_checker_ranged_subsets_slides_and_never_caches(deck, monkeypatch):
    """NIT-1: `slide_range` must reach the offline builder as a named argument (not silently
    dropped and swallowed by a `**kwargs` stub) -- that's what scopes the bulk Keynote read
    itself, the ranged path's entire cost saving."""

    def spy_build(key_path, bulk_geometry_fn, *, slide_range=None, log=None):
        assert slide_range == frozenset({2})
        return {
            "slideCount": 3,
            "slides": [
                {"index": 0, "number": 1, "items": []},
                {"index": 1, "number": 2, "items": []},
                {"index": 2, "number": 3, "items": []},
            ],
            "_offline": {"bulk_ok": True, "fallback_slides": []},
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    out = inspect_mod.inspect_keynote_checker(deck, slide_range=frozenset({2}), use_cache=True)

    # Legacy-ranged shape: only the wanted slide, full-deck slideCount kept.
    assert [s["number"] for s in out["slides"]] == [2]
    assert out["slideCount"] == 3
    # Ranged never caches, even with use_cache=True (matches legacy's `_truthy_cache`).
    json_path = inspect_cache_path(deck_digest(deck))
    assert not json_path.exists()


def test_checker_ranged_fallback_threads_slide_range_to_legacy(deck, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no iwa extra")

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", boom)
    legacy_calls: dict = {}

    def fake_legacy(key_path, *, export_dir=None, slide_range=None, use_cache=None):
        legacy_calls["slide_range"] = slide_range
        return {"slideCount": 3, "slides": [{"index": 1, "number": 2, "items": []}]}

    monkeypatch.setattr(inspect_mod, "inspect_keynote", fake_legacy)

    out = inspect_mod.inspect_keynote_checker(deck, slide_range=frozenset({2}))

    assert legacy_calls["slide_range"] == frozenset({2})
    assert [s["number"] for s in out["slides"]] == [2]


def test_uncached_checker_exports_into_export_dir_not_digest_cache(deck, monkeypatch, tmp_path):
    """AM-8: locks `export_target = dest` when `want_cache` is False -- the reason
    `previewFiles`/the dashboard preview grid keep working on the checker path."""

    def spy_build(key_path, bulk_geometry_fn, **kwargs):
        return {
            "slideCount": 1,
            "slides": [{"index": 0, "number": 1, "items": []}],
            "_offline": {"bulk_ok": True, "fallback_slides": []},
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    export_calls: list[Path] = []

    def fake_export(key_path, export_dir):
        export_calls.append(Path(export_dir))
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide.001.png").write_bytes(b"\x89PNG")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)

    previews = tmp_path / "previews"
    assert not previews.exists()  # the checker must create it, not the test

    out = inspect_mod.inspect_keynote_checker(deck, export_dir=previews, use_cache=False)

    assert export_calls == [previews]
    assert previews.is_dir()
    assert out["exported"] is True
    assert out["previewDir"] == str(previews.resolve())
    assert not preview_cache_dir(deck_digest(deck)).exists()


def test_use_cache_false_is_cache_blind_both_directions(deck, monkeypatch):
    """Caveat (f)'s actual assertion: `use_cache=False` neither reads a warm cache
    entry nor writes one, in either direction."""
    seeded = {
        "reader": "offline", "slideCount": 1,
        "slides": [{"index": 0, "number": 1, "items": []}], "sentinel": "CACHED",
    }
    json_path = inspect_cache_path(deck_digest(deck))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(seeded), encoding="utf-8")
    original_bytes = json_path.read_bytes()

    def spy_build(key_path, bulk_geometry_fn, **kwargs):
        return {
            "slideCount": 1, "slides": [{"index": 0, "number": 1, "items": []}],
            "sentinel": "REBUILT", "_offline": {"bulk_ok": True, "fallback_slides": []},
        }

    monkeypatch.setattr(inspect_mod, "_build_checker_offline", spy_build)

    out = inspect_mod.inspect_keynote_checker(deck, use_cache=False)

    assert out["sentinel"] == "REBUILT"  # cache not read
    assert out["_digest"] == ""  # no deck_digest ran
    assert json_path.read_bytes() == original_bytes  # cache not written
    assert list(json_path.parent.iterdir()) == [json_path]

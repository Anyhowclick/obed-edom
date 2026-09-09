from __future__ import annotations

import pytest

from obed_edom import remap_keynote as rk
from obed_edom.baseline import CACHE_DIR_ENV


def _cached_wall(reader: str = "jxa") -> dict:
    return {
        "reader": reader,
        "slideCount": 3,
        "slides": [
            {"number": 1, "index": 0, "items": []},
            {"number": 2, "index": 1, "items": []},
            {"number": 3, "index": 2, "items": []},
        ],
    }


@pytest.mark.parametrize(
    ("mode", "reader"),
    [("on", "jxa"), ("on", "offline"), ("off", "jxa")],
)
def test_acquire_uses_compatible_complete_cache_for_ranged_apply(
    monkeypatch, tmp_path, mode, reader,
):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall(reader)
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", lambda *a, **k: pytest.fail("legacy read"))

    out = rk.acquire_wall_payload(
        source, slide_range=frozenset({2}), mode=mode, say=logs.append
    )

    assert out is cached
    assert [slide["number"] for slide in out["slides"]] == [1, 2, 3]
    assert any("cached " + reader in line for line in logs)


def test_acquire_warns_but_serves_cached_bulk_errors(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    cached["bulkErrors"] = [{"slide": 1}, {"slide": 2}]
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is cached
    assert any("WARN:" in line and "bulk-geometry error" in line for line in logs)


@pytest.mark.parametrize("cached", [_cached_wall("offline"), {"reader": "jxa", "slideCount": 1, "slides": []}])
def test_rejected_cache_bypasses_legacy_cache(monkeypatch, tmp_path, cached):
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(
        rk, "inspect_keynote", lambda *_args, **kwargs: calls.append(kwargs) or {"legacy": True}
    )

    out = rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="off", say=lambda _m: None)

    assert out == {"legacy": True}
    assert calls == [{"use_cache": False}]


def test_rejected_cache_bypasses_cache_after_two_tier_failure(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: {"reader": "offline", "slides": []})
    monkeypatch.setattr(rk, "inspect_keynote", lambda *_args, **kwargs: calls.append(kwargs) or {"legacy": True})
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad IWA")))

    out = rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="on", say=lambda _m: None)

    assert out == {"legacy": True}
    assert calls == [{"use_cache": False}]


def test_fresh_two_tier_read_is_full_deck_and_stamped_offline(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.touch()
    seen: dict = {}
    monkeypatch.setattr(rk, "cached_payload", lambda _source: None)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda *_args, **_kwargs: {})

    def fake_two_tier(_source, **kwargs):
        seen.update(kwargs)
        return {"slideCount": 3, "slides": _cached_wall()["slides"], "_offline": {"bulk_ok": True}}

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)

    out = rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="on", say=lambda _m: None)

    assert "slide_range" not in seen
    assert [slide["number"] for slide in out["slides"]] == [1, 2, 3]
    assert out["reader"] == "offline"


def test_rejected_cache_bypasses_cache_on_partial_two_tier_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: {"reader": "offline", "slides": []})
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        offline_mod,
        "two_tier_wall_payload",
        lambda *_args, **_kwargs: {
            "slideCount": 1,
            "slides": [{"number": 1, "index": 0, "items": []}],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [1],
                "fallback": [{"slide": 1, "reason": "count-mismatch"}],
            },
        },
    )
    monkeypatch.setattr(
        rk, "_merge_legacy_slides", lambda *_args, **kwargs: calls.append(kwargs)
    )

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert calls == [{"use_cache": False}]
    assert out["reader"] == "offline"


def test_no_cache_keeps_legacy_cache_behavior(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: None)
    monkeypatch.setattr(
        rk, "inspect_keynote", lambda *_args, **kwargs: calls.append(kwargs) or {"legacy": True}
    )

    rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="off", say=lambda _m: None)

    assert calls == [{}]

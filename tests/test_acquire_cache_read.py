from __future__ import annotations

import pytest

from obed_edom import remap_keynote as rk
from obed_edom.baseline import CACHE_DIR_ENV


def _cached_wall(reader: str = "jxa") -> dict:
    wall = {
        "reader": reader,
        "slideCount": 3,
        "slides": [
            {"number": 1, "index": 0, "items": []},
            {"number": 2, "index": 1, "items": []},
            {"number": 3, "index": 2, "items": []},
        ],
    }
    if reader == "offline":
        wall["offlineFallbackTagged"] = True
    return wall


def _fail_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                   is_cancelled=None):
    pytest.fail("legacy read")


def _no_bulk_geometry(key_path, slides=None, *, keep_open=False, log=None):
    return {}


@pytest.mark.parametrize(
    # A cached jxa read in mode "on" is no longer directly compatible — see
    # test_stale_jxa_cache_is_rejected_and_offline_reread_in_mode_on below.
    ("mode", "reader"),
    [("on", "offline"), ("off", "jxa")],
)
def test_acquire_uses_compatible_complete_cache_for_ranged_apply(
    monkeypatch, tmp_path, mode, reader,
):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall(reader)
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

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

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        calls.append({"use_cache": use_cache})
        return {"legacy": True}

    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    out = rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="off", say=lambda _m: None)

    assert out == {"legacy": True}
    assert calls == [{"use_cache": False}]


def test_rejected_cache_bypasses_cache_after_two_tier_failure(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        calls.append({"use_cache": use_cache})
        return {"legacy": True}

    def boom_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        raise RuntimeError("bad IWA")

    monkeypatch.setattr(rk, "cached_payload", lambda _source: {"reader": "offline", "slides": []})
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom_two_tier)

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

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)

    _unset = object()

    def fake_two_tier(key_path, bulk_geometry_fn=None, slide_range=_unset, *, deck=None, log=None):
        if slide_range is not _unset:
            seen["slide_range"] = slide_range
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

    def fake_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        return {
            "slideCount": 1,
            "slides": [{"number": 1, "index": 0, "items": []}],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [1],
                "fallback": [{"slide": 1, "reason": "count-mismatch"}],
            },
        }

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)
    monkeypatch.setattr(
        rk, "_merge_legacy_slides", lambda *_args, **kwargs: calls.append(kwargs)
    )

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert calls == [{"use_cache": False}]
    assert out["reader"] == "offline"


def test_fresh_partial_fallback_tags_only_the_fallback_slides(monkeypatch, tmp_path):
    """Two-tier read succeeds overall (reader stays "offline") but slide 1 falls back
    to a scoped legacy read — its group rects are live union frames, so it alone must
    carry groupChildrenUnavailable; slide 2's offline geometry is untouched."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.touch()
    monkeypatch.setattr(rk, "cached_payload", lambda _source: None)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)

    def fake_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        return {
            "slideCount": 2,
            "slides": [
                {"number": 1, "index": 0, "items": []},
                {"number": 2, "index": 1, "items": []},
            ],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [1],
                "fallback": [{"slide": 1, "reason": "count-mismatch"}],
            },
        }

    def fake_inspect_keynote(key_path, *, slide_range=None, use_cache=None):
        return {"slides": [{"number": 1, "index": 0, "items": [{"kind": "image", "kindIndex": 0}]}]}

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect_keynote)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out["reader"] == "offline"
    assert out["offlineFallbackTagged"] is True
    assert out["slides"][0]["groupChildrenUnavailable"] is True
    assert "groupChildrenUnavailable" not in out["slides"][1]


def test_fallback_tagging_survives_the_cache_round_trip(monkeypatch, tmp_path):
    """store_inspect_payload only strips `_`-prefixed top-level keys, so the per-slide
    groupChildrenUnavailable flag (nested, not top-level) and offlineFallbackTagged
    (top-level, no underscore) both survive a write-then-read cache round trip."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.touch()
    payload = {
        "reader": "offline",
        "offlineFallbackTagged": True,
        "slideCount": 2,
        "slides": [
            {"number": 1, "index": 0, "items": [], "groupChildrenUnavailable": True},
            {"number": 2, "index": 1, "items": []},
        ],
    }
    from obed_edom.inspect import cached_payload, store_inspect_payload

    store_inspect_payload(source, payload)
    restored = cached_payload(source)

    assert restored["offlineFallbackTagged"] is True
    assert restored["slides"][0]["groupChildrenUnavailable"] is True
    assert "groupChildrenUnavailable" not in restored["slides"][1]


def test_stale_mixed_offline_cache_is_rejected_and_reread_in_mode_on(monkeypatch, tmp_path):
    """An offline cache predating per-slide groupChildrenUnavailable tagging cannot
    tell a JXA-fallback slide from a genuinely offline one, so it must not be trusted
    merely because it is otherwise complete and carries aspect."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    del cached["offlineFallbackTagged"]
    logs: list[str] = []
    offline_payload = {"slideCount": 3, "slides": _cached_wall("offline")["slides"],
                        "_offline": {"bulk_ok": True}}
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", lambda *a, **k: offline_payload)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is offline_payload
    assert any("mixed-slide-tagged" in line for line in logs)


def _image_item(*, aspect: object = "missing") -> dict:
    item = {"kind": "image", "kindIndex": 0, "start": [0, 0], "end": [1, 1]}
    if aspect != "missing":
        item["aspect"] = aspect
    return item


def test_aspect_less_jxa_cache_is_rejected_in_offline_mode(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    cached["slides"][0]["items"] = [_image_item()]
    offline_payload = {"slideCount": 3, "slides": _cached_wall("offline")["slides"],
                        "_offline": {"bulk_ok": True}}
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", lambda *a, **k: offline_payload)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is offline_payload


def test_stale_jxa_cache_is_rejected_and_offline_reread_in_mode_on(monkeypatch, tmp_path):
    """A cached jxa read is coordinate-space-incompatible with groupChildren (archive
    offsets vs a JXA group's live union frame) — serving it in mode "on" merely
    because a fresh offline decode would succeed is exactly what let Gold slide 2's
    badge groups collapse (the maps-tab worktree's stale jxa cache). It must be
    re-read offline instead, with a WARNING naming the group children incompatibility."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    offline_payload = {"slideCount": 3, "slides": _cached_wall("offline")["slides"],
                        "_offline": {"bulk_ok": True}}
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", lambda *a, **k: offline_payload)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is offline_payload
    assert any("jxa" in line and "group children" in line for line in logs)


def test_stale_jxa_cache_serves_the_cached_payload_when_offline_read_genuinely_unavailable(
    monkeypatch, tmp_path,
):
    """When tier 1 raises while the cache is a stale-jxa payload, the cached payload
    is served rather than paying for a full Keynote re-read — it is complete and
    carries aspect, only children-incompatible."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        pytest.fail("legacy read")

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    def boom_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        raise RuntimeError("bad IWA")

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom_two_tier)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is cached


def test_stale_mixed_cache_serves_the_cached_payload_when_offline_read_genuinely_unavailable(
    monkeypatch, tmp_path,
):
    """When tier 1 raises while the cache is a stale-mixed (untagged offline) payload,
    the cached payload is served conservatively — every slide's group size refused —
    rather than paying for a full Keynote re-read."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    del cached["offlineFallbackTagged"]
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        pytest.fail("legacy read")

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    def boom_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        raise RuntimeError("bad IWA")

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom_two_tier)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is cached
    assert all(slide["groupChildrenUnavailable"] is True for slide in out["slides"])


def test_aspect_less_jxa_cache_is_served_when_mode_off(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    cached["slides"][0]["items"] = [_image_item()]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="off", say=lambda _m: None)

    assert out is cached


def test_aspect_complete_offline_cache_is_served(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.offline_inspect as offline_mod

    def boom(*a, **k):
        pytest.fail("two_tier_wall_payload should not be called")

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is cached


def test_wall_payload_carries_aspect_accepts_none_for_masked():
    from obed_edom.inspect import wall_payload_carries_aspect

    payload = {"slides": [{"items": [{"kind": "image", "aspect": None}]}]}
    assert wall_payload_carries_aspect(payload) is True


def test_legacy_merge_preserves_media_aspect_and_drops_group_aspect(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    payload = {
        "slides": [{
            "number": 1,
            "items": [
                {"kind": "image", "kindIndex": 0, "aspect": 1.5},
                {"kind": "group", "kindIndex": 0, "aspect": 2.0},
            ],
        }],
    }

    def fake_inspect_keynote(key_path, *, slide_range=None, use_cache=None):
        return {
            "slides": [{
                "number": 1,
                "items": [
                    {"kind": "image", "kindIndex": 0},
                    {"kind": "group", "kindIndex": 0},
                ],
            }],
        }

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect_keynote)

    rk._merge_legacy_slides(payload, source, [1])

    items = {(it["kind"], it["kindIndex"]): it for it in payload["slides"][0]["items"]}
    assert items[("image", 0)]["aspect"] == 1.5
    assert "aspect" not in items[("group", 0)]


def test_no_cache_keeps_legacy_cache_behavior(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    calls: list[dict] = []

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        calls.append({} if use_cache is None else {"use_cache": use_cache})
        return {"legacy": True}

    monkeypatch.setattr(rk, "cached_payload", lambda _source: None)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    rk.acquire_wall_payload(source, slide_range=frozenset({2}), mode="off", say=lambda _m: None)

    assert calls == [{}]

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
        wall["spliceAspectRefreshed"] = True
    return wall


def _fail_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                   is_cancelled=None):
    pytest.fail("legacy read")


def _no_bulk_geometry(key_path, slides=None, *, keep_open=False, log=None):
    return {}


def _fail_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
    raise RuntimeError("bad IWA")


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

    monkeypatch.setattr(rk, "cached_payload", lambda _source: {"reader": "offline", "slides": []})
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", _fail_two_tier)

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
    assert out["offlineFallbackTagged"] is True
    assert out["spliceAspectRefreshed"] is True


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
    groupChildrenUnavailable flag (nested, not top-level) and offlineFallbackTagged /
    spliceAspectRefreshed (top-level, no underscore) all survive a write-then-read
    cache round trip."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.touch()
    payload = {
        "reader": "offline",
        "offlineFallbackTagged": True,
        "spliceAspectRefreshed": True,
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
    assert restored["spliceAspectRefreshed"] is True
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


def test_stale_aspect_offline_cache_is_rejected_and_reread_in_mode_on(monkeypatch, tmp_path):
    """An offline cache written before the bulk splice refreshed a stale frame's aspect
    (no spliceAspectRefreshed) may carry the pre-splice offline aspect, which sizes the
    planner's aspect snap from the wrong frame (Full wall slide 127 group 2: 406 pt
    planned vs ~108 pt). It is complete, tagged and carries aspect, yet must be
    re-read offline rather than served."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    del cached["spliceAspectRefreshed"]
    cached["slides"][0]["items"] = [_image_item(aspect=3.76, iwa_id="301")]
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
    assert out["spliceAspectRefreshed"] is True
    assert any("splice aspect refresh" in line for line in logs)
    assert not any("mixed-slide-tagged" in line for line in logs)


def test_stale_aspect_cache_serves_the_cached_payload_when_offline_read_genuinely_unavailable(
    monkeypatch, tmp_path,
):
    """When tier 1 raises while the cache predates the splice aspect refresh, the cached
    payload is served conservatively — every aspect nulled, so no item is aspect-snapped
    from a possibly stale frame (a None aspect already means "no snap", like a masked
    item or an aspect-less JXA read) — rather than paying for a full Keynote re-read.
    The fallback tagging is trusted, so group sizes stay allowed."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    del cached["spliceAspectRefreshed"]
    cached["slides"][0]["items"] = [
        _image_item(aspect=1.5, iwa_id="301"),
        {"kind": "group", "kindIndex": 0, "aspect": 3.76, "iwaId": "302"},
        {"kind": "image", "kindIndex": 1, "aspect": None, "iwaId": "303"},
        {"kind": "text", "kindIndex": 0, "iwaId": "304"},
    ]
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", _fail_two_tier)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is cached
    items = out["slides"][0]["items"]
    assert [item.get("aspect", "absent") for item in items] == [None, None, None, "absent"]
    assert not any("groupChildrenUnavailable" in slide for slide in out["slides"])
    assert any("aspect snaps refused" in line for line in logs)
    assert not any("group sizes" in line for line in logs)


def test_stale_mixed_and_stale_aspect_cache_refuses_both_when_offline_read_unavailable(
    monkeypatch, tmp_path,
):
    """A cache predating both markers (every offline cache written before fallback tagging) degrades on
    both axes at once: group sizes and aspect snaps are refused."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    del cached["offlineFallbackTagged"]
    del cached["spliceAspectRefreshed"]
    cached["slides"][0]["items"] = [_image_item(aspect=1.5, iwa_id="301")]
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", _fail_two_tier)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is cached
    assert out["slides"][0]["items"][0]["aspect"] is None
    assert all(slide["groupChildrenUnavailable"] is True for slide in out["slides"])
    assert any("group sizes and aspect snaps refused" in line for line in logs)


def test_stale_aspect_marker_is_ignored_when_mode_off(monkeypatch, tmp_path):
    """Mode "off" never serves an offline cache at all, so the marker plays no part:
    a JXA cache (which never carries the marker) is served as before."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="off", say=lambda _m: None)

    assert out is cached
    assert "spliceAspectRefreshed" not in out


def _image_item(*, aspect: object = "missing", iwa_id: object = None) -> dict:
    item = {"kind": "image", "kindIndex": 0, "start": [0, 0], "end": [1, 1]}
    if aspect != "missing":
        item["aspect"] = aspect
    if iwa_id is not None:
        item["iwaId"] = iwa_id
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

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", _fail_two_tier)

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
    cached["slides"][0]["items"] = [_image_item(aspect=1.5, iwa_id="301")]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        pytest.fail("legacy read")

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect)

    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", _fail_two_tier)

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
    cached["slides"][0]["items"] = [_image_item(aspect=1.5, iwa_id="301")]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.offline_inspect as offline_mod

    def boom(*a, **k):
        pytest.fail("two_tier_wall_payload should not be called")

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is cached


def test_id_less_offline_cache_is_rejected_and_reread(monkeypatch, tmp_path):
    """An offline cache written before items carried their source `iwaId` makes no slide
    eligible for offline hides; re-read it like an aspect-less cache."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    offline_payload = {"slideCount": 3, "slides": _cached_wall("offline")["slides"],
                        "_offline": {"bulk_ok": True}}
    logs: list[str] = []
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod

    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", lambda *a, **k: offline_payload)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert out is offline_payload
    assert any("predates per-item source ids; re-reading" in line for line in logs)


def test_id_bearing_offline_cache_is_served_and_fallback_slides_are_exempt(monkeypatch, tmp_path):
    """A cache whose offline-decoded items carry `iwaId` is reused; JXA-fallback slides
    (`groupChildrenUnavailable`) never carry it and do not make it stale."""
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("offline")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5, iwa_id="301")]
    cached["slides"][1]["items"] = [_image_item(aspect=1.5, iwa_id="302")]
    cached["slides"][2]["items"] = [_image_item(aspect=1.5)]
    cached["slides"][2]["groupChildrenUnavailable"] = True
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    import obed_edom.offline_inspect as offline_mod

    def boom(*a, **k):
        pytest.fail("two_tier_wall_payload should not be called")

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", boom)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert out is cached


def test_id_less_jxa_cache_is_unaffected(monkeypatch, tmp_path):
    source = tmp_path / "wall.key"
    source.touch()
    cached = _cached_wall("jxa")
    cached["slides"][0]["items"] = [_image_item(aspect=1.5)]
    monkeypatch.setattr(rk, "cached_payload", lambda _source: cached)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)

    out = rk.acquire_wall_payload(source, slide_range=None, mode="off", say=lambda _m: None)

    assert out is cached
    assert rk._offline_payload_carries_iwa_ids(cached) is True


def test_wall_payload_carries_aspect_accepts_none_for_masked():
    from obed_edom.inspect import wall_payload_carries_aspect

    payload = {"slides": [{"items": [{"kind": "image", "aspect": None}]}]}
    assert wall_payload_carries_aspect(payload) is True


def test_legacy_merge_preserves_media_aspect_and_nulls_group_aspect(monkeypatch, tmp_path):
    """A JXA group's frame is its live union, so its offline aspect never carries over;
    it still gets an explicit `aspect: None` so the payload carries aspect."""
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
    assert items[("group", 0)]["aspect"] is None
    from obed_edom.inspect import wall_payload_carries_aspect

    assert wall_payload_carries_aspect(payload) is True


def test_legacy_merge_restores_an_aspect_only_where_correspondence_and_frame_hold(
    monkeypatch, tmp_path,
):
    """Codex r2 MAJOR: a count mismatch means the offline kindIndex may not address the
    same object as the JXA one, so a restored aspect could be another image's ratio.
    Slide 1's images count-mismatch: both JXA images get None even though image 0's
    frame happens to agree with offline image 0's. Its movies matched by count: movie 0
    (frame within 1 pt) keeps its precise offline aspect, movie 1 (frame moved > 1 pt,
    a stale offline frame) gets None, and movie 2 (new in JXA, no offline twin) gets
    None. Slide 2 has no mismatch, so its image keeps its aspect."""
    source = tmp_path / "wall.key"
    source.touch()
    payload = {
        "slides": [
            {"number": 1, "index": 0, "items": [
                {"kind": "image", "kindIndex": 0, "w": 100, "h": 50, "aspect": 2.01},
                {"kind": "image", "kindIndex": 1, "w": 30, "h": 90, "aspect": 0.33},
                {"kind": "movie", "kindIndex": 0, "w": 160, "h": 90, "aspect": 1.7778},
                {"kind": "movie", "kindIndex": 1, "w": 160, "h": 90, "aspect": 1.7778},
            ]},
            {"number": 2, "index": 1, "items": [
                {"kind": "image", "kindIndex": 0, "w": 40, "h": 20, "aspect": 2.02},
            ]},
        ],
        "_offline": {"fallback": [
            {"slide": 1, "kind": "image", "kindIndex": -1, "reason": "count-mismatch"},
            {"slide": 2, "kind": "group", "kindIndex": 3, "reason": "bulk-missing"},
        ]},
    }

    def fake_inspect_keynote(key_path, *, slide_range=None, use_cache=None):
        return {"slides": [
            {"number": 1, "index": 0, "items": [
                {"kind": "image", "kindIndex": 0, "w": 100, "h": 50},
                {"kind": "image", "kindIndex": 1, "w": 100, "h": 50},
                {"kind": "image", "kindIndex": 2, "w": 30, "h": 90},
                {"kind": "movie", "kindIndex": 0, "w": 161, "h": 90},
                {"kind": "movie", "kindIndex": 1, "w": 120, "h": 90},
                {"kind": "movie", "kindIndex": 2, "w": 160, "h": 90},
            ]},
            {"number": 2, "index": 1, "items": [
                {"kind": "image", "kindIndex": 0, "w": 40, "h": 20},
                {"kind": "group", "kindIndex": 0, "w": 300, "h": 100},
            ]},
        ]}

    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect_keynote)

    rk._merge_legacy_slides(payload, source, [1, 2])

    one = {(it["kind"], it["kindIndex"]): it.get("aspect", "absent")
           for it in payload["slides"][0]["items"]}
    two = {(it["kind"], it["kindIndex"]): it.get("aspect", "absent")
           for it in payload["slides"][1]["items"]}
    assert one == {
        ("image", 0): None, ("image", 1): None, ("image", 2): None,
        ("movie", 0): 1.7778, ("movie", 1): None, ("movie", 2): None,
    }
    assert two == {("image", 0): 2.02, ("group", 0): None}


def test_count_mismatch_fallback_round_trips_fresh_and_plans_the_raw_affine(
    monkeypatch, tmp_path,
):
    """Codex r2 MAJOR + MINOR end to end. A fresh two-tier read whose slide 1 falls
    back on an image count mismatch, with a JXA group and a JXA-only image on it:
    the stamped (spliceAspectRefreshed) payload carries no restored offline aspect
    on the desynced kind, every fallback image/group carries an explicit aspect key,
    so the stored cache is served on the next acquire with no re-read, and the
    planner maps the desynced image by its raw affine instead of snapping it to the
    wrong image's ratio (offline image 0 was 3.0 wide; Keynote's image 0 is 110x244)."""
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    source = tmp_path / "wall.key"
    source.write_bytes(b"deck")
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod
    from obed_edom.map_remap import plan_slide_transforms

    monkeypatch.setattr(rk, "_truthy_cache", lambda *_a: True)
    monkeypatch.setattr(inspect_mod, "bulk_geometry", _no_bulk_geometry)

    def fake_two_tier(key_path, bulk_geometry_fn=None, slide_range=None, *, deck=None, log=None):
        return {
            "slideCount": 1,
            "slides": [{"number": 1, "index": 0, "items": [
                {"index": 0, "kind": "image", "kindIndex": 0, "x": 4687, "y": 97,
                 "w": 110, "h": 244, "aspect": 3.0, "iwaId": "301"},
            ]}],
            "_offline": {
                "bulk_ok": True,
                "fallback_slides": [1],
                "fallback": [{"slide": 1, "kind": "image", "kindIndex": -1,
                              "reason": "count-mismatch"}],
            },
        }

    def fake_inspect_keynote(key_path, *, slide_range=None, use_cache=None):
        return {"slides": [{"number": 1, "index": 0, "items": [
            {"index": 0, "kind": "image", "kindIndex": 0, "x": 4687, "y": 97, "w": 110,
             "h": 244, "text": "", "fileName": "a.png", "locked": False},
            {"index": 1, "kind": "image", "kindIndex": 1, "x": 10, "y": 10, "w": 300,
             "h": 100, "text": "", "fileName": "b.png", "locked": False},
            {"index": 2, "kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 50,
             "h": 50, "text": "", "fileName": "", "locked": False},
        ]}]}

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)
    monkeypatch.setattr(rk, "inspect_keynote", fake_inspect_keynote)

    fresh = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=lambda _m: None)

    assert fresh["spliceAspectRefreshed"] is True
    assert [it["aspect"] for it in fresh["slides"][0]["items"]] == [None, None, None]

    def no_reread(*_a, **_k):
        pytest.fail("a fresh, correctly marked cache must not be re-read")

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", no_reread)
    monkeypatch.setattr(rk, "inspect_keynote", _fail_inspect)
    logs: list[str] = []

    served = rk.acquire_wall_payload(source, slide_range=None, mode="on", say=logs.append)

    assert any("cached offline payload" in line for line in logs)
    assert [it["aspect"] for it in served["slides"][0]["items"]] == [None, None, None]
    recipe = {"destWidth": 1920.0, "destHeight": 1080.0,
              "groups": [{"s": 0.25, "tx": 0.0, "ty": 0.0,
                          "src": {"x": 4687, "y": 97, "w": 110, "h": 244}}]}
    planned = plan_slide_transforms(served["slides"][0], recipe, wall_size=(7680, 1080))
    image0 = next(t for t in planned if t.kind == "image" and t.kind_index == 0).as_dict()
    assert (image0["w"], image0["h"]) == (27.5, 61.0)


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

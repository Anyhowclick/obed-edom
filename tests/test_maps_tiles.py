"""OpenFreeMap tile cache helpers. No live CDN in the default tests."""

from __future__ import annotations

import pytest

from obed_edom.maps_tiles import (
    PINNED_CACHE_COUNTRIES,
    cache_country_rows,
    cache_path,
    normalize_rel,
    prefetch_rels,
    tiles_for_bbox,
    tiles_for_camera,
)


def test_pinned_cache_countries_come_first():
    rows = cache_country_rows()
    assert [row["code"] for row in rows[:4]] == list(PINNED_CACHE_COUNTRIES)
    rest = rows[4:]
    names = [row["name"] for row in rest]
    assert names == sorted(names, key=str.casefold)


def test_normalize_rel_rejects_parent():
    with pytest.raises(ValueError):
        normalize_rel("../secret")
    with pytest.raises(ValueError):
        normalize_rel("planet/../../etc/passwd")
    assert normalize_rel("/planet/0/0/0.pbf") == "planet/0/0/0.pbf"


def test_tiles_for_bbox_z0_is_one_tile():
    assert tiles_for_bbox(-180, -85, 180, 85, 0) == {(0, 0, 0)}


def test_tiles_for_camera_are_finite():
    tiles = tiles_for_camera(
        {"lat": 3.0, "lon": 101.0, "zoom": 6, "bearing": 0, "pitch": 0},
        width=3840,
        height=1080,
        maxzoom=6,
    )
    assert tiles
    assert all(z <= 6 for z, _x, _y in tiles)
    assert len(tiles) < 200


def test_prefetch_hits_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"pbf")
    first = prefetch_rels(["planet/0/0/0.pbf"])
    assert first["fetched"] == 1
    assert first["cached"] == 0
    assert cache_path("planet/0/0/0.pbf").read_bytes() == b"pbf"
    second = prefetch_rels(["planet/0/0/0.pbf"])
    assert second["cached"] == 1
    assert second["fetched"] == 0


def test_tilejson_does_not_block_nested_tiles(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr(
        "obed_edom.maps_tiles.fetch_upstream",
        lambda rel: b'{"tiles":["https://tiles.openfreemap.org/planet/rev/{z}/{x}/{y}.pbf"]}'
        if rel == "planet"
        else b"pbf",
    )
    from obed_edom.maps_tiles import fetch_and_cache

    json_path = fetch_and_cache("planet")
    assert json_path.name == "planet.json"
    nested = fetch_and_cache("planet/rev/0/0/0.pbf")
    assert nested.is_file()
    assert nested.read_bytes() == b"pbf"

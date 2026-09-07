"""OpenFreeMap tile cache helpers. No live CDN in the default tests."""

from __future__ import annotations

import inspect
import threading
import time

import pytest

from obed_edom.maps_tiles import (
    PINNED_CACHE_COUNTRIES,
    TERRAIN_MAXZOOM,
    cache_country_rows,
    cache_path,
    cache_stats,
    fetch_and_cache,
    fetch_upstream,
    media_type_for,
    normalize_rel,
    prefetch_rels,
    rels_for_cameras,
    terrain_tiles_for_camera,
    tiles_for_bbox,
    tiles_for_camera,
    viewport_bbox,
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
    with pytest.raises(ValueError):
        normalize_rel("fonts/Noto Sans/../../../etc/passwd")
    with pytest.raises(ValueError):
        normalize_rel("planet/%2e%2e/secret")
    assert normalize_rel("/planet/0/0/0.pbf") == "planet/0/0/0.pbf"


def test_normalize_rel_accepts_glyph_and_sprite_paths():
    fontstack = "fonts/Noto Sans Regular,Noto Sans Bold/0-255.pbf"
    assert normalize_rel(fontstack) == fontstack
    assert normalize_rel("fonts/Noto%20Sans%20Regular/0-255.pbf") == "fonts/Noto Sans Regular/0-255.pbf"
    assert normalize_rel("sprites/ofm_3.3/sprite@2x.png") == "sprites/ofm_3.3/sprite@2x.png"
    assert normalize_rel("sprites/ofm_3.3/sprite@2x.json") == "sprites/ofm_3.3/sprite@2x.json"


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
    json_path = fetch_and_cache("planet")
    assert json_path.name == "planet.json"
    nested = fetch_and_cache("planet/rev/0/0/0.pbf")
    assert nested.is_file()
    assert nested.read_bytes() == b"pbf"


def test_fetch_and_cache_writes_via_tmp_replace():
    src = inspect.getsource(fetch_and_cache)
    assert "replace(" in src
    assert "mkstemp" in src
    assert "path.write_bytes" not in src


def test_fetch_and_cache_replace_is_atomic_for_readers(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    payload = b"complete-tile-bytes" * 4096
    released = threading.Event()

    def fetch(_rel: str) -> bytes:
        released.wait(timeout=5)
        return payload

    seen: list[bytes] = []
    path = cache_path("planet/0/0/0.pbf")

    def reader() -> None:
        deadline = time.time() + 5
        while time.time() < deadline:
            if path.is_file():
                seen.append(path.read_bytes())
                return
            time.sleep(0.001)

    worker = threading.Thread(target=lambda: fetch_and_cache("planet/0/0/0.pbf", fetch=fetch))
    peek = threading.Thread(target=reader)
    worker.start()
    peek.start()
    time.sleep(0.05)
    released.set()
    worker.join(timeout=5)
    peek.join(timeout=5)
    assert path.read_bytes() == payload
    assert seen in ([], [payload])
    leftovers = [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_fetch_upstream_percent_encodes_segments(monkeypatch):
    seen: list[str] = []

    class FakeResp:
        def __init__(self, url: str):
            self.url = url
            self.content = b"ok"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, **_kwargs):
        seen.append(url)
        return FakeResp(url)

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get)
    fetch_upstream("fonts/Noto Sans Regular,Noto Sans Bold/0-255.pbf")
    fetch_upstream("sprites/ofm_f384/ofm@2x.png")
    assert seen[0] == "https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular%2CNoto%20Sans%20Bold/0-255.pbf"
    assert seen[1] == "https://tiles.openfreemap.org/sprites/ofm_f384/ofm%402x.png"


def test_viewport_bbox_rotates_with_bearing():
    lat, lon, zoom = 0.0, 0.0, 8.0
    width, height = 3840.0, 1080.0
    west, south, east, north = viewport_bbox(lat, lon, zoom, width, height, pad=0.0, bearing=0.0)
    rwest, rsouth, reast, rnorth = viewport_bbox(lat, lon, zoom, width, height, pad=0.0, bearing=90.0)
    assert (east - west) > (north - south)
    assert (rnorth - rsouth) > (reast - rwest)
    assert (rnorth - rsouth) > (north - south)
    unrot = tiles_for_camera(
        {"lat": lat, "lon": lon, "zoom": zoom, "bearing": 0, "pitch": 0},
        width=width,
        height=height,
        maxzoom=8,
    )
    rot = tiles_for_camera(
        {"lat": lat, "lon": lon, "zoom": zoom, "bearing": 90, "pitch": 0},
        width=width,
        height=height,
        maxzoom=8,
    )
    y_unrot = {y for z, _x, y in unrot if z == 8}
    y_rot = {y for z, _x, y in rot if z == 8}
    x_unrot = {x for z, x, _y in unrot if z == 8}
    x_rot = {x for z, x, _y in rot if z == 8}
    assert len(y_rot) > len(y_unrot)
    assert len(x_rot) < len(x_unrot)


def test_rels_for_cameras_subsamples_along_hop(monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.MAX_PREFETCH_TILES", 40)
    monkeypatch.setattr("obed_edom.maps_tiles.planet_tile_template", lambda **_: "planet/{z}/{x}/{y}.pbf")
    cameras = [
        {"lat": 0.0, "lon": float(i) * 8.0 - 80.0, "zoom": 10, "bearing": 0, "pitch": 0} for i in range(30)
    ]
    rels = rels_for_cameras(cameras, width=3840, height=1080, maxzoom=10)
    tiles = []
    for rel in rels:
        if not rel.startswith("planet/"):
            continue
        _kind, z, x, y = rel.replace(".pbf", "").split("/")
        tiles.append((int(z), int(x), int(y)))
    assert tiles
    hi = [t for t in tiles if t[0] == 10]
    assert hi, "subsample must keep high-z tiles from hop cameras, not a low-z prefix"
    xs = [x for z, x, _y in hi]
    assert max(xs) - min(xs) > 400


def test_cache_stats_counts_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"abcd")
    fetch_and_cache("planet/0/0/0.pbf")
    stats = cache_stats()
    assert stats["files"] >= 1
    assert stats["bytes"] >= 4


class _FakeResp:
    def __init__(self, url: str, content: bytes = b"ok"):
        self.url = url
        self.content = content

    def raise_for_status(self) -> None:
        return None


def test_terrain_rel_routes_to_aws_and_ofm_unchanged(monkeypatch):
    seen: list[str] = []

    def fake_get(url, **_kwargs):
        seen.append(url)
        return _FakeResp(url)

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get)
    fetch_upstream("terrarium/9/3/4.png")
    fetch_upstream("planet/0/0/0.pbf")
    assert seen[0] == "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/9/3/4.png"
    assert seen[1] == "https://tiles.openfreemap.org/planet/0/0/0.pbf"


def test_terrain_redirect_host_guard(monkeypatch):
    def fake_get(_url, **_kwargs):
        return _FakeResp("https://evil.example.com/terrarium/9/3/4.png")

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get)
    with pytest.raises(ValueError):
        fetch_upstream("terrarium/9/3/4.png")

    def fake_get_lookalike(_url, **_kwargs):
        return _FakeResp("https://evil-amazonaws.com/terrarium/9/3/4.png")

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get_lookalike)
    with pytest.raises(ValueError):
        fetch_upstream("terrarium/9/3/4.png")

    def fake_get_regional(_url, **_kwargs):
        return _FakeResp("https://elevation-tiles-prod.s3.us-east-1.amazonaws.com/terrarium/9/3/4.png")

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get_regional)
    fetch_upstream("terrarium/9/3/4.png")

    def fake_get_planet_to_s3(_url, **_kwargs):
        return _FakeResp("https://elevation-tiles-prod.s3.amazonaws.com/planet/0/0/0.pbf")

    monkeypatch.setattr("obed_edom.maps_tiles.requests.get", fake_get_planet_to_s3)
    with pytest.raises(ValueError):
        fetch_upstream("planet/0/0/0.pbf")


def test_terrain_rel_caches_under_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"dem-bytes")
    path = fetch_and_cache("terrarium/9/3/4.png")
    assert path == cache_path("terrarium/9/3/4.png")
    assert path.read_bytes() == b"dem-bytes"
    assert media_type_for("terrarium/9/3/4.png") == "image/png"
    with pytest.raises(ValueError):
        normalize_rel("terrarium/../planet/0/0/0.pbf")


def test_terrain_tiles_are_one_zoom_deeper_and_capped():
    tiles = terrain_tiles_for_camera(
        {"lat": 27.9, "lon": 86.9, "zoom": 9, "bearing": 0, "pitch": 0},
        width=3840,
        height=1080,
    )
    assert tiles
    assert all(z == 10 for z, _x, _y in tiles)

    capped = terrain_tiles_for_camera(
        {"lat": 27.9, "lon": 86.9, "zoom": 14, "bearing": 0, "pitch": 0},
        width=3840,
        height=1080,
    )
    assert capped
    assert all(z == TERRAIN_MAXZOOM for z, _x, _y in capped)


def test_rels_for_cameras_terrain_adds_dem_within_one_budget(monkeypatch):
    # A single camera bypasses the binary search entirely, so this is the path
    # that exposed the vector+dem double-budget bug (each family capped against
    # the full MAX_PREFETCH_TILES independently).
    monkeypatch.setattr("obed_edom.maps_tiles.MAX_PREFETCH_TILES", 100)
    monkeypatch.setattr("obed_edom.maps_tiles.planet_tile_template", lambda **_: "planet/{z}/{x}/{y}.pbf")
    camera = {"lat": 0.0, "lon": 0.0, "zoom": 10, "bearing": 0, "pitch": 0}

    without = rels_for_cameras([camera], width=3840, height=1080, maxzoom=10, terrain=False)
    assert without
    assert all(not rel.startswith("terrarium/") for rel in without)
    assert len(without) <= 100

    withit = rels_for_cameras([camera], width=3840, height=1080, maxzoom=10, terrain=True)
    assert any(rel.startswith("planet/") for rel in withit)
    assert any(rel.startswith("terrarium/") for rel in withit)
    assert len(withit) <= 100


def test_fetch_and_cache_two_threads_same_missing_rel(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    barrier = threading.Barrier(2)

    def fetch(_rel: str) -> bytes:
        barrier.wait(timeout=5)
        return b"same-bytes"

    results: list[bytes] = []

    def worker() -> None:
        results.append(fetch_and_cache("planet/1/0/0.pbf", fetch=fetch).read_bytes())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert results == [b"same-bytes", b"same-bytes"]
    assert cache_path("planet/1/0/0.pbf").read_bytes() == b"same-bytes"

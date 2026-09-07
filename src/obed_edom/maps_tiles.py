"""Disk cache and prefetch for OpenFreeMap vector tiles.

Authoring still talks to OpenFreeMap's OpenMapTiles schema; this module only
proxies those URLs through `output/.maps/tile-cache` so Movie export is not
waiting on the public CDN for every 7680px frame.
"""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from obed_edom.maps_geo import (
    MAX_LAT,
    WALL_HEIGHT,
    WALL_WIDTH,
    clamp_lon,
    geometry_bbox,
    inverse_mercator_y,
    load_admin0,
    mercator_y,
    world_width,
)
from obed_edom.paths import output_root

UPSTREAM = "https://tiles.openfreemap.org"
TILE_UA = "Obed-Edom-Maps/1.0 (local dashboard tile cache)"
PINNED_CACHE_COUNTRIES = ("PHL", "IND", "IDN", "MYS")
PLANET_TILEJSON = "planet"
PLANET_TEMPLATE_FALLBACK = "planet/{z}/{x}/{y}.pbf"
NE_RASTER_TEMPLATE = "natural_earth/ne2sr/{z}/{x}/{y}.png"
DEFAULT_COUNTRY_MAXZOOM = 8
DEFAULT_CAMERA_MAXZOOM = 14
NE_MAXZOOM = 6
MAX_PREFETCH_TILES = 8000
FETCH_WORKERS = 8
_SAFE_REL = re.compile(r"^[A-Za-z0-9._/-]+$")
_MEDIA = {
    ".pbf": "application/x-protobuf",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".css": "text/css",
}


def cache_root() -> Path:
    path = output_root() / ".maps" / "tile-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_rel(rest: str) -> str:
    rel = (rest or "").strip().lstrip("/")
    if not rel or not _SAFE_REL.match(rel):
        raise ValueError("Invalid tile path")
    parts = Path(rel).parts
    if ".." in parts or any(part in {".", ""} for part in parts):
        raise ValueError("Invalid tile path")
    return "/".join(parts)


def cache_path(rel: str) -> Path:
    rel = normalize_rel(rel)
    # Extensionless TileJSON URLs like `planet` must not occupy the directory of z/x/y tiles.
    if not Path(rel).suffix:
        rel = f"{rel}.json"
    return cache_root() / rel


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    cache = cache_root()
    while parent != cache and parent != parent.parent:
        if parent.is_file():
            parent.unlink()
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)


def media_type_for(rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    if not suffix:
        return "application/json"
    return _MEDIA.get(suffix, "application/octet-stream")


def fetch_upstream(rel: str) -> bytes:
    url = f"{UPSTREAM}/{normalize_rel(rel)}"
    resp = requests.get(url, timeout=45, headers={"User-Agent": TILE_UA}, allow_redirects=True)
    resp.raise_for_status()
    final = urlparse(resp.url)
    if final.hostname and final.hostname.lower() != "tiles.openfreemap.org":
        raise ValueError("Unexpected tile redirect")
    return resp.content


def fetch_and_cache(rel: str, *, fetch=None) -> Path:
    getter = fetch or fetch_upstream
    path = cache_path(rel)
    if path.is_file():
        return path
    _ensure_parent_dir(path)
    path.write_bytes(getter(rel))
    return path


def cache_country_rows(admin0: dict[str, Any] | None = None) -> list[dict[str, str]]:
    feats = (admin0 or load_admin0()).get("features") or []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for feat in feats:
        props = feat.get("properties") or {}
        code = str(props.get("ADM0_A3") or "").upper()
        name = str(props.get("NAME") or "").strip()
        if not code or not name or code in seen:
            continue
        seen.add(code)
        rows.append({"code": code, "name": name})
    pin = {code: index for index, code in enumerate(PINNED_CACHE_COUNTRIES)}
    rows.sort(
        key=lambda row: (0, pin[row["code"]]) if row["code"] in pin else (1, row["name"].casefold())
    )
    return rows


def country_bbox(code: str) -> dict[str, float] | None:
    wanted = (code or "").upper()
    if not wanted:
        return None
    for feat in load_admin0().get("features") or []:
        props = feat.get("properties") or {}
        if str(props.get("ADM0_A3") or "").upper() == wanted:
            return geometry_bbox(feat.get("geometry") or {})
    return None


def _lat_to_y(lat: float, n: int) -> float:
    clamped = max(-MAX_LAT, min(MAX_LAT, lat))
    rad = math.radians(clamped)
    return (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * n


def tiles_for_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    z: int,
) -> set[tuple[int, int, int]]:
    z = max(0, min(22, int(z)))
    n = 2**z
    south = max(-MAX_LAT, min(MAX_LAT, south))
    north = max(-MAX_LAT, min(MAX_LAT, north))
    if north < south:
        south, north = north, south
    span = east - west if east >= west else east + 360.0 - west
    span = min(360.0, max(0.0, span))
    if span >= 359.9:
        x_indices = range(n)
    else:
        x0 = int(math.floor((west + 180.0) / 360.0 * n))
        count = int(math.ceil(span / 360.0 * n)) + 1
        x_indices = [(x0 + i) % n for i in range(count)]
    y0 = int(math.floor(_lat_to_y(north, n)))
    y1 = int(math.floor(_lat_to_y(south, n)))
    y0 = max(0, min(n - 1, y0))
    y1 = max(0, min(n - 1, y1))
    if y1 < y0:
        y0, y1 = y1, y0
    tiles: set[tuple[int, int, int]] = set()
    for x in x_indices:
        for y in range(y0, y1 + 1):
            tiles.add((z, int(x) % n, y))
    return tiles


def viewport_bbox(
    lat: float,
    lon: float,
    zoom: float,
    width: float,
    height: float,
    *,
    pad: float = 0.25,
) -> tuple[float, float, float, float]:
    world = world_width(zoom)
    cx = (clamp_lon(lon) + 180.0) / 360.0
    cy = mercator_y(lat)
    nw = (float(width) / world) * (1.0 + pad)
    nh = (float(height) / world) * (1.0 + pad)
    west = (cx - nw / 2.0) * 360.0 - 180.0
    east = (cx + nw / 2.0) * 360.0 - 180.0
    north = inverse_mercator_y(cy - nh / 2.0)
    south = inverse_mercator_y(cy + nh / 2.0)
    return west, south, east, north


def tiles_for_camera(
    camera: dict[str, Any],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
    maxzoom: int = DEFAULT_CAMERA_MAXZOOM,
) -> set[tuple[int, int, int]]:
    lat = float(camera.get("lat") or 0)
    lon = float(camera.get("lon") or 0)
    zoom = float(camera.get("zoom") or 0)
    pitch = abs(float(camera.get("pitch") or 0))
    pad = 0.3 + 0.6 * min(1.0, pitch / 60.0)
    z_hi = max(0, min(int(maxzoom), int(math.floor(zoom))))
    west, south, east, north = viewport_bbox(lat, lon, zoom, width, height, pad=pad)
    tiles: set[tuple[int, int, int]] = set()
    for z in range(max(0, z_hi - 2), z_hi + 1):
        tiles.update(tiles_for_bbox(west, south, east, north, z))
    return tiles


def planet_tile_template(*, fetch=None) -> str:
    try:
        path = fetch_and_cache(PLANET_TILEJSON, fetch=fetch)
        data = json.loads(path.read_bytes().decode("utf-8"))
        url = (data.get("tiles") or [None])[0]
        if isinstance(url, str) and "{z}" in url:
            rel = urlparse(url).path.lstrip("/")
            if rel:
                return rel
    except Exception:
        pass
    return PLANET_TEMPLATE_FALLBACK


def planet_rels(tiles: Iterable[tuple[int, int, int]], *, fetch=None) -> list[str]:
    template = planet_tile_template(fetch=fetch)
    rels: set[str] = set()
    for z, x, y in tiles:
        rels.add(template.format(z=z, x=x, y=y))
        if z <= NE_MAXZOOM:
            rels.add(NE_RASTER_TEMPLATE.format(z=z, x=x, y=y))
    return sorted(rels)


def rels_for_countries(codes: Iterable[str], *, maxzoom: int = DEFAULT_COUNTRY_MAXZOOM) -> list[str]:
    tiles: set[tuple[int, int, int]] = set()
    z_max = max(0, min(int(maxzoom), DEFAULT_COUNTRY_MAXZOOM))
    for code in codes:
        bbox = country_bbox(str(code))
        if not bbox:
            continue
        for z in range(0, z_max + 1):
            tiles.update(
                tiles_for_bbox(bbox["west"], bbox["south"], bbox["east"], bbox["north"], z)
            )
    if len(tiles) > MAX_PREFETCH_TILES:
        keep = sorted(tiles, key=lambda t: (t[0], t[1], t[2]))[:MAX_PREFETCH_TILES]
        tiles = set(keep)
    return planet_rels(tiles)


def rels_for_cameras(
    cameras: Iterable[dict[str, Any]],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
    maxzoom: int = DEFAULT_CAMERA_MAXZOOM,
) -> list[str]:
    tiles: set[tuple[int, int, int]] = set()
    for camera in cameras:
        tiles.update(tiles_for_camera(camera, width=width, height=height, maxzoom=maxzoom))
        if len(tiles) >= MAX_PREFETCH_TILES:
            break
    if len(tiles) > MAX_PREFETCH_TILES:
        tiles = set(sorted(tiles)[:MAX_PREFETCH_TILES])
    return planet_rels(tiles)


def prefetch_rels(rels: Iterable[str], *, fetch=None) -> dict[str, int]:
    getter = fetch or fetch_upstream
    unique = list(dict.fromkeys(normalize_rel(rel) for rel in rels))
    cached = 0
    fetched = 0
    failed = 0
    pending: list[str] = []
    for rel in unique:
        path = cache_path(rel)
        if path.is_file():
            cached += 1
        else:
            pending.append(rel)
    if pending:
        workers = min(FETCH_WORKERS, len(pending))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_and_cache, rel, fetch=getter): rel for rel in pending}
            for future in as_completed(futures):
                try:
                    future.result()
                    fetched += 1
                except Exception:
                    failed += 1
    return {"tiles": len(unique), "cached": cached, "fetched": fetched, "failed": failed}

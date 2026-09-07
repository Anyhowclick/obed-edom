"""Maps cameras, geocode, and Natural Earth lookups.

Nominatim GET handlers must not sleep; a rate-limited call returns 429.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

from obed_edom.paths import output_root

DATA_DIR = Path(__file__).resolve().parent / "data" / "ne"
ADMIN0_PATH = DATA_DIR / "admin0_50m.geojson"
PLACES_PATH = DATA_DIR / "places_110m.geojson"

NOMINATIM_UA = (
    "Obed-Edom-Maps/1.0 (local dashboard; +https://nominatim.openstreetmap.org/usage-policy)"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

TILE_SIZE = 512
WALL_WIDTH = 7680
WALL_HEIGHT = 1080
CENTRE_WIDTH = 3840
CENTRE_ORIGIN_X = 1920
WORLD_MIN_ZOOM = math.log2(WALL_WIDTH / TILE_SIZE)
MAX_LAT = 85.051129
DEFAULT_POINT_ZOOM = 8

SEA_OVERVIEW_BBOX = {"west": 70.0, "south": -42.0, "east": 155.0, "north": 28.0}

_PLACE_ALIASES = {
    "kl": "kuala lumpur",
}

_AT_RE = re.compile(
    r"@(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)(?:\s*,\s*(-?\d+(?:\.\d+)?)z)?",
    re.I,
)
_COMMA_ZOOM_RE = re.compile(r",(-?\d+(?:\.\d+)?)z\b", re.I)
_LATLNG_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$")

_admin0: dict[str, Any] | None = None
_places: dict[str, Any] | None = None
_last_nominatim = 0.0
_NOMINATIM_GAP = 1.0


def reset_nominatim_throttle() -> None:
    global _last_nominatim
    _last_nominatim = 0.0


class GeocodeError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class GeocodeRateLimited(GeocodeError):
    def __init__(self, message: str = "Nominatim rate limited") -> None:
        super().__init__(message, status=429)


def clamp_lat(lat: float) -> float:
    return max(-MAX_LAT, min(MAX_LAT, float(lat)))


def clamp_lon(lon: float) -> float:
    lon = float(lon)
    while lon > 180:
        lon -= 360
    while lon < -180:
        lon += 360
    return lon


def clamp_zoom(zoom: float) -> float:
    return max(WORLD_MIN_ZOOM, min(22.0, float(zoom)))


def world_width(zoom: float) -> float:
    return TILE_SIZE * (2 ** float(zoom))


def camera_dict(lat: float, lon: float, zoom: float, bearing: float = 0.0, pitch: float = 0.0) -> dict[str, float]:
    return {
        "lat": clamp_lat(lat),
        "lon": clamp_lon(lon),
        "zoom": clamp_zoom(zoom),
        "bearing": float(bearing),
        "pitch": float(pitch),
    }


def camera_from_point(lat: float, lon: float, zoom: float = DEFAULT_POINT_ZOOM) -> dict[str, float]:
    return camera_dict(lat, lon, zoom)


def mercator_y(lat: float) -> float:
    lat = clamp_lat(lat)
    rad = math.radians(lat)
    sin = math.sin(rad)
    return 0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)


def inverse_mercator_y(y: float) -> float:
    n = math.pi * (1 - 2 * float(y))
    return clamp_lat(math.degrees(math.atan(math.sinh(n))))


def camera_from_bbox(
    bbox: dict[str, float],
    width: int = WALL_WIDTH,
    height: int = WALL_HEIGHT,
) -> dict[str, float]:
    west = float(bbox["west"])
    south = float(bbox["south"])
    east = float(bbox["east"])
    north = float(bbox["north"])
    if east < west:
        east += 360.0
    span = abs(mercator_y(south) - mercator_y(north))
    if span <= 0:
        z_height = WORLD_MIN_ZOOM
    else:
        z_height = math.log2(height / (TILE_SIZE * span))
    # Height-contain, but never zoom below WORLD_MIN_ZOOM. The wall is 7680px;
    # below that zoom a wrapped world tiles and pins/highlights repeat.
    zoom = max(z_height, WORLD_MIN_ZOOM)
    lon = clamp_lon((west + east) / 2.0)
    lat = inverse_mercator_y((mercator_y(north) + mercator_y(south)) / 2.0)
    return camera_dict(lat, lon, zoom)


CG_WIDTH = 1920.0
CG_ORIGIN_X = 2880.0
CENTER_LEFT = 1920.0
CENTER_RIGHT = 5760.0
CG_SHIFT_MAX = 960.0


def clamp_cg_shift(dx: float, dy: float) -> tuple[float, float]:
    """1920 CG window stays inside the 3840 centre wall; dy is always 0."""
    dx = max(-CG_SHIFT_MAX, min(CG_SHIFT_MAX, float(dx)))
    left = CG_ORIGIN_X + dx
    if left < CENTER_LEFT:
        dx += CENTER_LEFT - left
    right = CG_ORIGIN_X + dx + CG_WIDTH
    if right > CENTER_RIGHT:
        dx -= right - CENTER_RIGHT
    return (dx, 0.0)


def toggle_adm0(highlights: list[str], adm0_a3: str) -> list[str]:
    code = str(adm0_a3 or "").strip().upper()
    if not code:
        return list(highlights)
    current = [str(h).upper() for h in highlights]
    if code in current:
        return [h for h in current if h != code]
    return [*current, code]


def infer_hop_kind(from_slide: dict[str, Any], to_slide: dict[str, Any]) -> str:
    from_style = str(from_slide.get("style") or "")
    to_style = str(to_slide.get("style") or "")
    from_hi = sorted(str(h).upper() for h in (from_slide.get("highlights") or []))
    to_hi = sorted(str(h).upper() for h in (to_slide.get("highlights") or []))
    if from_style != to_style or from_hi != to_hi:
        return "cut"
    from_cam = from_slide.get("camera") or {}
    to_cam = to_slide.get("camera") or {}
    pitch = max(abs(float(from_cam.get("pitch") or 0)), abs(float(to_cam.get("pitch") or 0)))
    bearing = max(abs(float(from_cam.get("bearing") or 0)), abs(float(to_cam.get("bearing") or 0)))
    d_zoom = abs(float(from_cam.get("zoom") or 0) - float(to_cam.get("zoom") or 0))
    if from_style == "buildings3d" or to_style == "buildings3d" or pitch > 0.5 or bearing > 0.5 or d_zoom > 1:
        return "movie"
    return "morph"


def sea_overview_camera() -> dict[str, float]:
    return camera_from_bbox(SEA_OVERVIEW_BBOX, WALL_WIDTH, WALL_HEIGHT)


def load_admin0() -> dict[str, Any]:
    global _admin0
    if _admin0 is None:
        _admin0 = json.loads(ADMIN0_PATH.read_text(encoding="utf-8"))
    return _admin0


def load_places() -> dict[str, Any]:
    global _places
    if _places is None:
        _places = json.loads(PLACES_PATH.read_text(encoding="utf-8"))
    return _places


def _walk_coords(coords: Any, n: int, fn) -> None:
    if n == 0:
        fn(coords)
        return
    for item in coords:
        _walk_coords(item, n - 1, fn)


def _lon_bounds(lons: list[float]) -> tuple[float, float]:
    """Smallest arc containing the lons, so Fiji/USA/Russia do not frame at lon 0."""
    xs = sorted({(float(lon) + 180.0) % 360.0 for lon in lons})
    if not xs:
        return 0.0, 0.0
    if len(xs) == 1:
        lon = xs[0] - 180.0
        return lon, lon
    best_gap = (xs[0] + 360.0) - xs[-1]
    idx = 0
    for i in range(1, len(xs)):
        gap = xs[i] - xs[i - 1]
        if gap > best_gap:
            best_gap = gap
            idx = i
    if idx == 0:
        west360, east360 = xs[0], xs[-1]
    else:
        west360, east360 = xs[idx], xs[idx - 1] + 360.0
    return west360 - 180.0, east360 - 180.0


def geometry_bbox(geometry: dict[str, Any]) -> dict[str, float] | None:
    gtype = geometry.get("type")
    nest = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}
    if gtype not in nest:
        return None
    xs: list[float] = []
    ys: list[float] = []

    def take(pt: Any) -> None:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))

    _walk_coords(geometry.get("coordinates"), nest[gtype], take)
    if not xs:
        return None
    west, east = _lon_bounds(xs)
    return {"west": west, "south": min(ys), "east": east, "north": max(ys)}


def _admin0_match(query: str, *, exact: bool) -> dict[str, Any] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    for feat in load_admin0().get("features") or []:
        props = feat.get("properties") or {}
        code = str(props.get("ADM0_A3") or "").lower()
        name = str(props.get("NAME") or "").lower()
        if q == code or q == name:
            return feat
        if not exact and len(q) > 2 and q in name:
            return feat
    return None


def find_country(query: str) -> dict[str, Any] | None:
    return _admin0_match(query, exact=False)


def parse_maps_query(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    at = _AT_RE.search(text)
    if at:
        lat = float(at.group(1))
        lon = float(at.group(2))
        zoom = float(at.group(3)) if at.group(3) is not None else DEFAULT_POINT_ZOOM
        z_extra = _COMMA_ZOOM_RE.search(text[at.end() :])
        if z_extra and at.group(3) is None:
            zoom = float(z_extra.group(1))
        return {
            "source": "parse",
            "label": text,
            "camera": camera_from_point(lat, lon, zoom),
        }
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if ("google." in host and "/maps" in path) or host.endswith("goo.gl"):
        qs = parse_qs(parsed.query)
        for key in ("q", "query", "ll", "center"):
            vals = qs.get(key) or []
            if not vals:
                continue
            pair = _LATLNG_RE.match(unquote(vals[0]).replace("+", " ").strip())
            if pair:
                return {
                    "source": "parse",
                    "label": text,
                    "camera": camera_from_point(float(pair.group(1)), float(pair.group(2))),
                }
    pair = _LATLNG_RE.match(text)
    if pair:
        return {
            "source": "parse",
            "label": text,
            "camera": camera_from_point(float(pair.group(1)), float(pair.group(2))),
        }
    return None


_PLACE_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _place_tokens(text: str) -> list[str]:
    return _PLACE_TOKEN_RE.findall((text or "").lower())


def search_places(query: str) -> dict[str, Any] | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    q = _PLACE_ALIASES.get(q, q)
    q_tokens = _place_tokens(q)
    if not q_tokens:
        return None
    q_join = " ".join(q_tokens)
    best = None
    best_score = 10**9
    for feat in load_places().get("features") or []:
        props = feat.get("properties") or {}
        name = str(props.get("NAME") or "")
        ascii_name = str(props.get("NAMEASCII") or name)
        name_join = " ".join(_place_tokens(name))
        ascii_join = " ".join(_place_tokens(ascii_name))
        hay_tokens = _place_tokens(f"{name} {ascii_name}")
        exact = q_join in {name.lower(), ascii_name.lower(), name_join, ascii_join}
        prefix = all(any(token.startswith(qt) for token in hay_tokens) for qt in q_tokens)
        if not exact and not prefix:
            continue
        score = 0 if exact else 1
        if score < best_score:
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            best_score = score
            best = {
                "source": "places",
                "label": name,
                "camera": camera_from_point(float(coords[1]), float(coords[0])),
            }
            if score == 0:
                break
    return best


def geocode_cache_dir() -> Path:
    path = output_root() / ".geocode"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(query: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", query.strip().lower())[:80] or "q"
    return safe


def _read_geocode_cache(query: str) -> dict[str, Any] | None:
    path = geocode_cache_dir() / f"{_cache_key(query)}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_geocode_cache(query: str, payload: dict[str, Any]) -> None:
    path = geocode_cache_dir() / f"{_cache_key(query)}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def nominatim_search(query: str, *, wait: bool = False) -> dict[str, Any]:
    """Call Nominatim. ``wait=True`` sleeps on a job thread; GET handlers must pass False."""
    global _last_nominatim
    cached = _read_geocode_cache(query)
    if cached:
        return cached
    now = time.monotonic()
    gap = now - _last_nominatim
    if gap < _NOMINATIM_GAP:
        if not wait:
            raise GeocodeRateLimited()
        time.sleep(_NOMINATIM_GAP - gap)
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": NOMINATIM_UA, "Accept": "application/json"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GeocodeError(f"Nominatim error: {exc}", status=502) from exc
    _last_nominatim = time.monotonic()
    if resp.status_code == 429:
        raise GeocodeRateLimited()
    if not resp.ok:
        raise GeocodeError(f"Nominatim HTTP {resp.status_code}", status=502)
    hits = resp.json()
    if not isinstance(hits, list) or not hits:
        raise GeocodeError(f"No results for {query!r}")
    hit = hits[0]
    lat = float(hit["lat"])
    lon = float(hit["lon"])
    bbox = hit.get("boundingbox")
    camera = camera_from_point(lat, lon)
    if isinstance(bbox, list) and len(bbox) == 4:
        south, north, west, east = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if abs(north - south) > 0.4 or abs(east - west) > 0.4:
            camera = camera_from_bbox({"west": west, "south": south, "east": east, "north": north})
    payload = {
        "source": "nominatim",
        "label": str(hit.get("display_name") or query),
        "camera": camera,
    }
    _write_geocode_cache(query, payload)
    return payload


def geocode(query: str, *, wait: bool = False) -> dict[str, Any]:
    text = (query or "").strip()
    if not text:
        raise GeocodeError("Empty query")
    parsed = parse_maps_query(text)
    if parsed:
        return parsed
    place = search_places(text)
    if place:
        return place
    country = find_country(text)
    if country:
        bbox = geometry_bbox(country.get("geometry") or {})
        name = str((country.get("properties") or {}).get("NAME") or text)
        if bbox:
            return {"source": "admin0", "label": name, "camera": camera_from_bbox(bbox)}
    return nominatim_search(text, wait=wait)

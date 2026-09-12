"""Tolerant CSV/paste parsing for the Maps CSV bootstrap, and the zoom ladder.

Pure: no FastAPI, no HTTP, no network.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from obed_edom.maps_geo import clamp_lat, clamp_lon


@dataclass(frozen=True)
class Place:
    line: int
    name: str
    url: str | None = None
    lat: float | None = None
    lon: float | None = None
    zoom: float | None = None
    kind: str | None = None
    query: str | None = None


KNOWN_HEADERS = frozenset(
    {"name", "title", "lat", "lon", "lng", "latitude", "longitude", "url", "maps_url", "zoom", "kind", "place"}
)

ZOOM_LADDER: dict[str, float] = {
    "country": 4.3,
    "state": 6.8,
    "city": 10.5,
    "town": 13.0,
    "neighbourhood": 15.5,
    "building": 18.0,
}
COORD_DEFAULT_ZOOM = ZOOM_LADDER["town"]

PLACE_TYPE_TIER: dict[str, str] = {
    "country": "country",
    "sovereign_state": "country",
    "state": "state",
    "province": "state",
    "region": "state",
    "county": "state",
    "administrative": "state",
    "city": "city",
    "municipality": "city",
    "metropolis": "city",
    "town": "town",
    "village": "town",
    "suburb_of_town": "town",
    "district": "town",
    "borough": "town",
    "neighbourhood": "neighbourhood",
    "quarter": "neighbourhood",
    "hamlet": "neighbourhood",
    "campus": "neighbourhood",
    "university": "neighbourhood",
    "school": "neighbourhood",
    "building": "building",
    "house": "building",
    "amenity": "building",
    "church": "building",
    "place_of_worship": "building",
    "shop": "building",
    "office": "building",
    "tourism": "building",
}


def zoom_for_place_type(place_type: str | None) -> float:
    tier = PLACE_TYPE_TIER.get((place_type or "").strip().lower())
    return ZOOM_LADDER.get(tier, COORD_DEFAULT_ZOOM)


def resolve_zoom(place: Place, place_type: str | None = None, zoom_from_url: float | None = None) -> float:
    if place.zoom is not None:
        return place.zoom
    if zoom_from_url is not None:
        return zoom_from_url
    return zoom_for_place_type(place_type)


def looks_like_header(fields: list[str]) -> bool:
    non_empty = [f.strip().lower() for f in fields if f.strip()]
    if not non_empty:
        return False
    return all(field in KNOWN_HEADERS for field in non_empty)


_HALF_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*°?\s*([NSEWnsew])?$")
_DMS_RE = re.compile(
    r"^(\d+)\s*°\s*(?:(\d+(?:\.\d+)?)\s*['′]\s*)?(?:(\d+(?:\.\d+)?)\s*[\"″]\s*)?([NSEWnsew])$"
)
_ZOOM_RE = re.compile(r"^(?:z\s*=\s*|@|zoom\s+)(-?\d+(?:\.\d+)?)$", re.I)


def _coord_one(token: str) -> tuple[float, str | None] | None:
    token = token.strip()
    dms = _DMS_RE.match(token)
    if dms:
        deg = float(dms.group(1))
        minutes = float(dms.group(2) or 0)
        seconds = float(dms.group(3) or 0)
        value = deg + minutes / 60 + seconds / 3600
        hemi = dms.group(4).upper()
        if hemi in ("S", "W"):
            value = -value
        return value, hemi
    half = _HALF_RE.match(token)
    if half:
        value = float(half.group(1))
        hemi = half.group(2).upper() if half.group(2) else None
        if hemi in ("S", "W"):
            value = -value
        return value, hemi
    return None


def _order_halves(a: tuple[float, str | None], b: tuple[float, str | None]) -> tuple[float, float]:
    va, ea = a
    vb, eb = b
    if ea in ("N", "S") or eb in ("E", "W"):
        return va, vb
    if eb in ("N", "S") or ea in ("E", "W"):
        return vb, va
    return va, vb


def _coord_pair(field: str) -> tuple[float, float] | None:
    field = field.strip()
    if not field:
        return None
    if "," in field:
        parts = [p.strip() for p in field.split(",")]
        if len(parts) != 2:
            return None
    else:
        tokens = field.split()
        if not tokens:
            return None
        parts = []
        for tok in tokens:
            if tok.upper() in ("N", "S", "E", "W") and parts:
                parts[-1] = parts[-1] + tok
            else:
                parts.append(tok)
        if len(parts) != 2:
            return None
    a = _coord_one(parts[0])
    b = _coord_one(parts[1])
    if a is None or b is None:
        return None
    return _order_halves(a, b)


def _explicit_zoom(field: str) -> float | None:
    match = _ZOOM_RE.match(field.strip())
    return float(match.group(1)) if match else None


def _is_number(field: str) -> bool:
    try:
        float(field)
    except ValueError:
        return False
    return True


def _parse_headerless_row(fields: list[str], line: int) -> Place | str:
    fields = [f.strip() for f in fields]
    while fields and fields[-1] == "":
        fields.pop()
    name = fields[0] if fields else ""
    if not name:
        return f"Line {line}: no name"
    rest = fields[1:]
    url: str | None = None
    lat: float | None = None
    lon: float | None = None
    zoom: float | None = None
    kind: str | None = None
    i = 0
    n = len(rest)
    while i < n:
        field = rest[i]
        if not field:
            i += 1
            continue
        if "http" in field.lower():
            if url is not None:
                return f"Line {line}: two URLs"
            url = field
            i += 1
            continue
        pair = _coord_pair(field)
        if pair is not None:
            if lat is not None:
                return f"Line {line}: two coordinates"
            lat, lon = pair
            i += 1
            continue
        half = _coord_one(field)
        if half is not None and half[1] is not None:
            other = _coord_one(rest[i + 1]) if i + 1 < n else None
            if other is None:
                return f"Line {line}: lone coordinate half {field!r}"
            if lat is not None:
                return f"Line {line}: two coordinates"
            lat, lon = _order_halves(half, other)
            i += 2
            continue
        zoom_val = _explicit_zoom(field)
        if zoom_val is not None:
            if zoom is not None:
                return f"Line {line}: two zooms"
            zoom = zoom_val
            i += 1
            continue
        if _is_number(field):
            return f"Line {line}: cannot tell if {field!r} is a zoom or a coordinate"
        if kind is not None:
            return f"Line {line}: two kinds"
        kind = field
        i += 1
    lat_c = clamp_lat(lat) if lat is not None else None
    lon_c = clamp_lon(lon) if lon is not None else None
    return Place(line=line, name=name, url=url, lat=lat_c, lon=lon_c, zoom=zoom, kind=kind)


def _place_from_dict_row(row: dict[str, str], line: int) -> Place | str:
    name = (row.get("name") or row.get("title") or "").strip()
    if not name:
        return f"Line {line}: no name"
    lat_raw = (row.get("lat") or row.get("latitude") or "").strip()
    lon_raw = (row.get("lon") or row.get("lng") or row.get("longitude") or "").strip()
    lat = clamp_lat(float(lat_raw)) if lat_raw else None
    lon = clamp_lon(float(lon_raw)) if lon_raw else None
    url = (row.get("maps_url") or row.get("url") or "").strip() or None
    zoom_raw = (row.get("zoom") or "").strip()
    zoom = float(zoom_raw) if zoom_raw else None
    kind = (row.get("kind") or "").strip() or None
    query = (row.get("place") or "").strip() or None
    return Place(line=line, name=name, url=url, lat=lat, lon=lon, zoom=zoom, kind=kind, query=query)


def _parse_header_form(sample: str) -> tuple[list[Place], list[str]]:
    reader = csv.DictReader(io.StringIO(sample))
    places: list[Place] = []
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {str(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
        if not any(row.values()):
            continue
        result = _place_from_dict_row(row, line_no)
        if isinstance(result, str):
            errors.append(result)
        else:
            places.append(result)
    return places, errors


def parse_places(text: str) -> tuple[list[Place], list[str]]:
    sample = text.lstrip("﻿")
    raw_lines = sample.splitlines()
    numbered = [(i + 1, line) for i, line in enumerate(raw_lines) if line.strip()]
    if not numbered:
        return [], []
    first_fields = next(csv.reader([numbered[0][1]]))
    if looks_like_header(first_fields):
        return _parse_header_form(sample)
    places: list[Place] = []
    errors: list[str] = []
    for line_no, raw_line in numbered:
        fields = next(csv.reader([raw_line]))
        result = _parse_headerless_row(fields, line_no)
        if isinstance(result, str):
            errors.append(result)
        else:
            places.append(result)
    return places, errors

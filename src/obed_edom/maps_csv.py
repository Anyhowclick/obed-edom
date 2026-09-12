"""Tolerant CSV/paste parsing for the Maps CSV bootstrap, and the zoom ladder.

Pure: no FastAPI, no HTTP, no network.
"""

from __future__ import annotations

import csv
import io
import math
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
    full_query: bool = False


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


_SINGLE_FIELD_HEADERS = frozenset({"name", "title", "place"})


def looks_like_header(fields: list[str], has_more_lines: bool = False) -> bool:
    non_empty = [f.strip().lower() for f in fields if f.strip()]
    if len(non_empty) == 1:
        return has_more_lines and non_empty[0] in _SINGLE_FIELD_HEADERS
    if len(non_empty) < 2:
        return False
    return all(field in KNOWN_HEADERS for field in non_empty)


_HALF_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*°?\s*([NSEWnsew])?$")
_DMS_RE = re.compile(
    r"^(\d+)\s*°\s*(?:(\d+(?:\.\d+)?)\s*['′]\s*)?(?:(\d+(?:\.\d+)?)\s*[\"″]\s*)?([NSEWnsew])$"
)
_ZOOM_RE = re.compile(r"^(?:z\s*=\s*|@|zoom\s+)(-?\d+(?:\.\d+)?)$", re.I)
_URL_RE = re.compile(r"https?://\S+")
_KIND_CANON: dict[str, str] = {"dot": "dot", "droppin": "dropPin", "landmark": "landmark"}


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
            value = -abs(value)
        return value, hemi
    half = _HALF_RE.match(token)
    if half:
        value = float(half.group(1))
        hemi = half.group(2).upper() if half.group(2) else None
        if hemi in ("S", "W"):
            value = -abs(value)
        elif hemi in ("N", "E"):
            value = abs(value)
        return value, hemi
    return None


def _peelable_field(token: str, after: str) -> bool:
    if _explicit_zoom(token) is not None:
        return True
    if token.lower() in _KIND_CANON:
        return True
    half = _coord_one(token)
    if half is not None:
        if half[1] is not None:
            return True
        return re.match(r"^\s*[NSEWnsew]\b", after) is not None
    return False


_MAX_URL_PEEL = 8


def _extract_unquoted_url(raw_line: str) -> tuple[str, str | None, str | None]:
    match = _URL_RE.search(raw_line)
    if not match:
        return raw_line, None, None
    start = match.start()
    if start > 0 and raw_line[start - 1] == '"':
        return raw_line, None, None
    end = match.end()
    while end > start and raw_line[end - 1] == ",":
        end -= 1
    tokens = raw_line[start:end].split(",")
    after = raw_line[end:]
    for _ in range(_MAX_URL_PEEL):
        if len(tokens) <= 1:
            break
        trailing_token = tokens[-1]
        if not _peelable_field(trailing_token, after):
            break
        after = "," + trailing_token + after
        tokens.pop()
    else:
        if len(tokens) > 1 and _peelable_field(tokens[-1], after):
            return raw_line, None, "too many fields after URL"
    url = ",".join(tokens)
    new_end = start + len(url)
    remainder = raw_line[:start] + raw_line[new_end:]
    return remainder, url, None


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


def _check_zoom_range(zoom: float, line: int, raw: str) -> str | None:
    if not math.isfinite(zoom):
        return f"Line {line}: bad zoom {raw!r}"
    if not (0 <= zoom <= 22):
        return f"Line {line}: zoom out of range {raw!r} (must be 0-22)"
    return None


def _parse_headerless_row(fields: list[str], line: int, extracted_url: str | None = None) -> Place | str:
    fields = [f.strip() for f in fields]
    while fields and fields[-1] == "":
        fields.pop()
    name = fields[0] if fields else ""
    if not name:
        return f"Line {line}: no name"
    rest = fields[1:]
    url: str | None = extracted_url
    lat: float | None = None
    lon: float | None = None
    zoom: float | None = None
    kind: str | None = None
    query_parts: list[str] = []
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
            zoom_error = _check_zoom_range(zoom_val, line, field)
            if zoom_error is not None:
                return zoom_error
            zoom = zoom_val
            i += 1
            continue
        if _is_number(field):
            next_field = rest[i + 1] if i + 1 < n else None
            if next_field is not None and _is_number(next_field):
                a, b = float(field), float(next_field)
                if abs(a) <= 90 and abs(b) <= 180:
                    if lat is not None:
                        return f"Line {line}: two coordinates"
                    lat, lon = a, b
                    i += 2
                    continue
            return (
                f"Line {line}: cannot tell if {field!r} is a zoom or a coordinate"
                " — use z=… for zoom or N/E for coordinates"
            )
        canon = _KIND_CANON.get(field.lower())
        if canon is not None:
            if kind is not None:
                return f"Line {line}: two kinds"
            kind = canon
            i += 1
            continue
        query_parts.append(field)
        i += 1
    if lat is not None and not (math.isfinite(lat) and math.isfinite(lon)):
        return f"Line {line}: bad lat/lon {lat!r}, {lon!r}"
    lat_c = clamp_lat(lat) if lat is not None else None
    lon_c = clamp_lon(lon) if lon is not None else None
    query = ", ".join(query_parts) or None
    return Place(line=line, name=name, url=url, lat=lat_c, lon=lon_c, zoom=zoom, kind=kind, query=query, full_query=False)


def _place_from_dict_row(row: dict[str, str], line: int) -> Place | str:
    name = (row.get("name") or row.get("title") or "").strip()
    query = (row.get("place") or "").strip() or None
    if not name and not query:
        return f"Line {line}: no name"
    lat_raw = (row.get("lat") or row.get("latitude") or "").strip()
    lon_raw = (row.get("lon") or row.get("lng") or row.get("longitude") or "").strip()
    try:
        lat_val = float(lat_raw) if lat_raw else None
        lon_val = float(lon_raw) if lon_raw else None
        if (lat_val is not None and not math.isfinite(lat_val)) or (
            lon_val is not None and not math.isfinite(lon_val)
        ):
            return f"Line {line}: bad lat/lon {lat_raw!r}, {lon_raw!r}"
        lat = clamp_lat(lat_val) if lat_val is not None else None
        lon = clamp_lon(lon_val) if lon_val is not None else None
    except ValueError:
        return f"Line {line}: bad lat/lon {lat_raw!r}, {lon_raw!r}"
    url = (row.get("maps_url") or row.get("url") or "").strip() or None
    zoom_raw = (row.get("zoom") or "").strip()
    try:
        zoom = float(zoom_raw) if zoom_raw else None
    except ValueError:
        return f"Line {line}: bad zoom {zoom_raw!r}"
    if zoom is not None:
        zoom_error = _check_zoom_range(zoom, line, zoom_raw)
        if zoom_error is not None:
            return zoom_error
    if (lat_raw and not lon_raw) or (lon_raw and not lat_raw):
        return f"Line {line}: lat without lon" if lat_raw else f"Line {line}: lon without lat"
    kind_raw = (row.get("kind") or "").strip()
    kind: str | None = None
    if kind_raw:
        kind = _KIND_CANON.get(kind_raw.lower())
        if kind is None:
            return f"Line {line}: unknown kind {kind_raw!r}"
    return Place(line=line, name=name, url=url, lat=lat, lon=lon, zoom=zoom, kind=kind, query=query, full_query=bool(query))


_RESTKEY = "__extra__"


def _parse_header_form(sample: str, line_offset: int) -> tuple[list[Place], list[str]]:
    reader = csv.DictReader(io.StringIO(sample), restkey=_RESTKEY)
    try:
        fieldnames = [str(f or "").strip().lower() for f in (reader.fieldnames or [])]
    except csv.Error as exc:
        return [], [f"Line {line_offset + 1}: unreadable row ({exc})"]
    seen: set[str] = set()
    for field in fieldnames:
        if field in seen:
            return [], [f"Line {line_offset + 1}: duplicate column {field!r}"]
        seen.add(field)
    single_joinable_header = len(fieldnames) == 1 and fieldnames[0] in _SINGLE_FIELD_HEADERS
    places: list[Place] = []
    errors: list[str] = []
    row_iter = iter(reader)
    while True:
        prev_line_num = reader.line_num
        try:
            raw = next(row_iter)
        except StopIteration:
            break
        except csv.Error as exc:
            errors.append(f"Line {line_offset + prev_line_num + 1}: unreadable row ({exc})")
            continue
        extra = raw.pop(_RESTKEY, None)
        row = {str(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
        if not any(row.values()) and not extra:
            continue
        # A quoted multiline value makes this record span more than one
        # physical line; report the record's starting line, not its end
        # (reader.line_num, which DictReader also advances past any
        # blank lines it silently swallowed before this record).
        newline_counts = [v.count("\n") for v in row.values()]
        if extra:
            newline_counts += [str(e).count("\n") for e in extra]
        span = 1 + max(newline_counts, default=0)
        line_no = line_offset + reader.line_num - span + 1
        if extra:
            if single_joinable_header:
                key = fieldnames[0]
                parts = [row.get(key, "")] + [str(e).strip() for e in extra if str(e).strip()]
                row[key] = ", ".join(p for p in parts if p)
            else:
                errors.append(f"Line {line_no}: too many columns")
                continue
        result = _place_from_dict_row(row, line_no)
        if isinstance(result, str):
            errors.append(result)
        else:
            places.append(result)
    return places, errors


_MAX_RECORD_LINES = 4


def _read_bounded_record(lines: list[str], start: int) -> tuple[list[str] | None, int, str | None]:
    """Read one logical CSV record starting at ``lines[start]``.

    Bounds a multiline (quoted) record to ``_MAX_RECORD_LINES`` physical
    lines: if the quote is still open after that many lines (or at EOF),
    the record is reported as unterminated rather than silently
    swallowing the rest of the file.
    """
    end_limit = min(start + _MAX_RECORD_LINES, len(lines))
    chunk = lines[start:end_limit]
    reader = csv.reader(io.StringIO("\n".join(chunk)))
    try:
        fields = next(reader)
    except StopIteration:
        return None, 1, None
    except csv.Error as exc:
        return None, 1, str(exc)
    consumed = reader.line_num
    if consumed == len(chunk):
        # The reader used up everything we gave it: if the quote it opened
        # is still unclosed, it would have kept consuming past our bound
        # (or to EOF) rather than stopping here on its own.
        record_text = "\n".join(chunk[:consumed])
        if record_text.count('"') % 2 == 1:
            return None, 1, "unterminated quote"
    return fields, consumed, None


def parse_places(text: str) -> tuple[list[Place], list[str]]:
    sample = text.lstrip("﻿")
    raw_lines = sample.splitlines()
    if not any(line.strip() for line in raw_lines):
        return [], []
    first_idx = next(i for i, line in enumerate(raw_lines) if line.strip())
    try:
        first_fields = next(csv.reader([raw_lines[first_idx]]))
    except csv.Error as exc:
        return [], [f"Line {first_idx + 1}: unreadable row ({exc})"]
    has_more_lines = any(line.strip() for line in raw_lines[first_idx + 1 :])
    if looks_like_header(first_fields, has_more_lines=has_more_lines):
        header_sample = "\n".join(raw_lines[first_idx:])
        return _parse_header_form(header_sample, first_idx)

    places: list[Place] = []
    errors: list[str] = []
    total = len(raw_lines)
    idx = 0
    while idx < total:
        line_no = idx + 1
        fields, consumed, err = _read_bounded_record(raw_lines, idx)
        idx += consumed
        if err is not None:
            errors.append(f"Line {line_no}: unreadable row ({err})")
            continue
        if fields is None or not any(f.strip() for f in fields):
            continue
        raw_record = "\n".join(raw_lines[line_no - 1 : line_no - 1 + consumed])
        extracted_url: str | None = None
        if '"' not in raw_record:
            remainder, extracted_url, peel_err = _extract_unquoted_url(raw_record)
            if peel_err is not None:
                errors.append(f"Line {line_no}: unreadable row ({peel_err})")
                continue
            try:
                fields = next(csv.reader(io.StringIO(remainder)))
            except StopIteration:
                fields = []
            except csv.Error as exc:
                errors.append(f"Line {line_no}: unreadable row ({exc})")
                continue
        result = _parse_headerless_row(fields, line_no, extracted_url)
        if isinstance(result, str):
            errors.append(result)
        else:
            places.append(result)
    return places, errors

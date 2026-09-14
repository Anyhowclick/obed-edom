"""Natural Earth admin-1 (state/province) polygons, fetched once and split per country.

The 40 MB upstream file is never persisted; only the slimmed per-country splits live on
disk, under `output/.maps/admin1` — deliberately a sibling of the tile cache rather than
inside it, so admin-1 never lands in a saved session `.zip`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import requests

from obed_edom.paths import output_root

ADMIN1_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/"
    "geojson/ne_10m_admin_1_states_provinces.geojson"
)
ADMIN1_KEYS = ("adm0_a3", "adm1_code", "iso_3166_2", "name", "type_en")
ADMIN1_UA = "Obed-Edom-Maps/1.0 (local dashboard admin-1 fetch)"
INDEX_NAME = "_index.json"
ADMIN1_CACHE_MAX = 8

_ADM0_RE = re.compile(r"^[A-Z]{3}$")
_fetch_lock = threading.Lock()
_admin1: OrderedDict[str, dict[str, Any]] = OrderedDict()


class Admin1FetchError(RuntimeError):
    """The upstream admin-1 file could not be downloaded or parsed."""


def admin1_dir() -> Path:
    """The split's home. Read-only: only `ensure_admin1` creates it."""
    return output_root() / ".maps" / "admin1"


def _write_json(path: Path, payload: Any) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def split_admin1(raw: dict[str, Any], dest: Path) -> int:
    """Group `raw`'s features by `adm0_a3` into slimmed per-country files under `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for feat in raw.get("features") or []:
        props = feat.get("properties") or {}
        adm0 = str(props.get("adm0_a3") or "").upper()
        if not _ADM0_RE.match(adm0):
            continue
        if not props.get("name") or not props.get("adm1_code"):
            continue
        grouped.setdefault(adm0, []).append(
            {
                "type": "Feature",
                "properties": {key: props.get(key) for key in ADMIN1_KEYS},
                "geometry": feat.get("geometry"),
            }
        )
    count = 0
    for adm0, feats in sorted(grouped.items()):
        _write_json(dest / f"{adm0}.geojson", {"type": "FeatureCollection", "features": feats})
        count += len(feats)
    _write_json(
        dest / INDEX_NAME,
        {"url": ADMIN1_URL, "features": count, "countries": sorted(grouped)},
    )
    return count


def ensure_admin1(timeout: float = 120) -> Path:
    """Download and split the admin-1 file unless the split is already on disk."""
    dest = admin1_dir()
    if (dest / INDEX_NAME).is_file():
        return dest
    with _fetch_lock:
        if (dest / INDEX_NAME).is_file():
            return dest
        try:
            resp = requests.get(ADMIN1_URL, timeout=timeout, headers={"User-Agent": ADMIN1_UA})
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            raise Admin1FetchError(f"Could not fetch admin-1 data: {exc}") from exc
        if not isinstance(raw, dict) or not raw.get("features"):
            raise Admin1FetchError("Admin-1 download had no features")
        split_admin1(raw, dest)
        _admin1.clear()
        return dest


def load_admin1(adm0: str) -> dict[str, Any] | None:
    code = str(adm0 or "").upper()
    if not _ADM0_RE.match(code):
        return None
    cached = _admin1.get(code)
    if cached is not None:
        _admin1.move_to_end(code)
        return cached
    path = admin1_dir() / f"{code}.geojson"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if len(_admin1) >= ADMIN1_CACHE_MAX:
        _admin1.popitem(last=False)
    _admin1[code] = data
    return data


def admin1_stats() -> dict[str, int]:
    root = admin1_dir()
    nbytes = 0
    nfiles = 0
    if not root.is_dir():
        return {"bytes": 0, "files": 0}
    for path in root.rglob("*"):
        if path.is_file():
            nfiles += 1
            nbytes += path.stat().st_size
    return {"bytes": nbytes, "files": nfiles}


def clear_admin1() -> None:
    _admin1.clear()
    shutil.rmtree(admin1_dir(), ignore_errors=True)

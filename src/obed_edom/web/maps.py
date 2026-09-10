"""Maps tab API. P2 (is_backdrop / HEVC / score_resize / map_remap) is deferred."""

from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from obed_edom.maps_geo import (
    DEFAULT_HIDDEN_LAYERS,
    GeocodeError,
    camera_dict,
    clamp_cg_shift,
    find_country,
    geocode,
    geometry_bbox,
    infer_hop_kind,
    inherit_hidden_layers,
    load_admin0,
    load_places,
    parse_maps_query,
    sea_overview_camera,
)
from obed_edom.maps_keynote import coerce_link_kinds, maps_export_plan, plate_filename, split_cg_export_plan
from obed_edom.maps_tiles import (
    DEFAULT_CAMERA_MAXZOOM,
    DEFAULT_COUNTRY_MAXZOOM,
    MAX_PREFETCH_BATCH,
    cache_country_rows,
    cache_path,
    cache_root,
    cache_stats,
    camera_tile_plan,
    clear_tile_cache,
    fetch_and_cache,
    media_type_for,
    normalize_rel,
    prefetch_rels,
    rels_for_cameras,
    rels_for_countries,
)
from obed_edom.paths import output_root

router = APIRouter(prefix="/api/maps", tags=["maps"])

SESSION_VERSION = 2
SESSION_MAX_FILES = 100_000
SESSION_MAX_BYTES = 2 * 1024 * 1024 * 1024

DEFAULT_ISOLATE_STRENGTH = 0.65
MAX_RETIRED_LINKS = 200

DIR_KEYS = {"outputDir", "workDir", "previewDir", "stem", "previews", "previewFiles"}
_MUTATION_LOCKS: dict[str, threading.RLock] = {}


def _mutation_lock(job_id: str) -> threading.RLock:
    return _MUTATION_LOCKS.setdefault(job_id, threading.RLock())


def _mutate_document(job_id: str, expected_revision: int | None, mutate) -> dict[str, Any]:
    with _mutation_lock(job_id):
        job = _job_or_404(job_id)
        _require_idle(job)
        result = copy.deepcopy(job.result or {})
        revision = int(result.get("stateRevision") or 0)
        if expected_revision is not None and expected_revision != revision:
            raise HTTPException(409, {"stateRevision": revision, "document": _dump_document(_parse_document(result))})
        updated = mutate(result)
        updated["stateRevision"] = revision + 1
        saved = _runner().update_result(job_id, updated)
        if not saved:
            raise HTTPException(404, "Unknown maps job")
        return _runner().public_dict(saved)
STYLE_IDS = ("positron", "liberty", "bright", "dark", "fiord", "buildings3d", "toner", "toner-background", "toner-lines", "watercolour")
MapsStyleId = Literal["positron", "liberty", "bright", "dark", "fiord", "buildings3d", "toner", "toner-background", "toner-lines", "watercolour"]
MapsCropId = Literal["wall", "center+cg"]
MapsLayerFilterId = Literal[
    "roads", "roadnames", "shields", "arrows", "pois", "rail", "buildings", "labels", "boundaries"
]
MapsHopKind = Literal["morph", "movie", "dissolve", "cut"]
MapsPinKind = Literal["dot", "dropPin", "landmark"]
MapsIconId = Literal["none", "building", "cross"]
MapsEasing = Literal["ease-in-out", "linear", "ease-in", "ease-out"]


def _runner():
    from obed_edom.web.app import RUNNER

    return RUNNER


class MapsCamera(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float
    lon: float
    zoom: float
    bearing: float = 0.0
    pitch: float = 0.0


class MapsIsolate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["darken"] = "darken"
    strength: float = Field(default=DEFAULT_ISOLATE_STRENGTH, ge=0, le=1)


class MapsReveal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["brush"] = "brush"
    duration: float = Field(default=1.2, ge=0.3, le=5)
    strokes: int = Field(default=4, ge=2, le=24)


class MapsChurch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    lat: float
    lon: float
    kind: MapsPinKind
    color: str
    showLabel: bool = True
    icon: MapsIconId | None = None
    photoPath: str | None = None
    assetId: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    assetVersion: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,64}$")
    assetWidth: int | None = Field(default=None, ge=1, le=10000)
    assetHeight: int | None = Field(default=None, ge=1, le=10000)
    size: float | None = Field(default=None, ge=1, le=4000)
    opacity: float | None = Field(default=None, ge=0, le=1)
    reveal: MapsReveal | None = None


class MapsAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    version: str = Field(pattern=r"^[a-f0-9]{8,64}$")
    width: int = Field(ge=1, le=10000)
    height: int = Field(ge=1, le=10000)


class MapsCgOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: MapsCamera
    style: MapsStyleId
    highlights: list[str] = Field(default_factory=list)
    churches: list[MapsChurch] = Field(default_factory=list)
    hiddenLayers: list[MapsLayerFilterId] | None = None
    hillshade: bool | None = None
    isolate: MapsIsolate | None = None
    stillPng: str | None = None
    movieMov: str | None = None
    movieDuration: float | None = None
    revealMovie: bool = False


class MapsSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    style: MapsStyleId
    camera: MapsCamera
    highlights: list[str] = Field(default_factory=list)
    churches: list[MapsChurch] = Field(default_factory=list)
    hiddenLayers: list[MapsLayerFilterId] | None = None
    hillshade: bool = False
    isolate: MapsIsolate | None = None
    stillPng: str | None = None
    movieMov: str | None = None
    movieDuration: float | None = None
    revealMovie: bool = False
    cgShiftX: float = 0
    cgShiftY: float = 0
    includeSidePanels: bool = False
    cg: MapsCgOverride | None = None

    @field_validator("includeSidePanels", mode="before")
    @classmethod
    def _side_panels(cls, value: object) -> object:
        if value is None:
            return False
        return value

    @model_validator(mode="after")
    def _clamp_shift(self) -> MapsSlide:
        dx, dy = clamp_cg_shift(self.cgShiftX, self.cgShiftY)
        self.cgShiftX = dx
        self.cgShiftY = dy
        return self


class MapsRoutePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float
    lon: float


class MapsRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    points: list[MapsRoutePoint] = Field(min_length=2)


class MapsLink(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    kind: MapsHopKind
    duration: float
    playWithoutClick: bool = False
    easing: MapsEasing | None = None
    plateId: str | None = None
    route: MapsRoute | None = None
    easeIn: float | None = None
    easeOut: float | None = None
    flyZoom: float | None = None
    curve: float | None = Field(default=None, ge=0.5, le=3)
    objectTransition: Literal["fade", "hold"] | None = None

    def dumped(self) -> dict[str, Any]:
        data = self.model_dump(by_alias=True)
        movie_only = ("easing", "route", "easeIn", "easeOut", "flyZoom", "curve", "objectTransition")
        if data.get("kind") != "movie":
            for key in movie_only:
                data.pop(key, None)
        else:
            for key in movie_only:
                if data.get(key) is None:
                    data.pop(key, None)
        if data.get("plateId") is None:
            data.pop("plateId", None)
        return data


class MapsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaultStyle: MapsStyleId
    crop: MapsCropId
    exportLw: bool = True
    exportCg: bool = True
    exportDsk: bool = False
    hiddenLayers: list[MapsLayerFilterId] = Field(default_factory=lambda: list(DEFAULT_HIDDEN_LAYERS))
    cachedCountries: list[str] = Field(default_factory=list)
    assets: list[MapsAsset] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _inherit_hidden_layers(cls, data: object) -> object:
        return inherit_hidden_layers(data) if isinstance(data, dict) else data

    @field_validator("hiddenLayers", mode="before")
    @classmethod
    def _hidden_layers(cls, value: object) -> object:
        if value is None:
            return list(DEFAULT_HIDDEN_LAYERS)
        return value

    @field_validator("cachedCountries", mode="before")
    @classmethod
    def _cached_countries(cls, value: object) -> object:
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            code = str(item or "").strip().upper()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
        return out
    slides: list[MapsSlide]
    links: list[MapsLink]
    retiredLinks: list[MapsLink] = Field(default_factory=list)

    @field_validator("exportLw", "exportCg", "exportDsk")
    @classmethod
    def _bool(cls, value: bool) -> bool:
        return bool(value)

    @model_validator(mode="after")
    def _one_export(self) -> MapsDocument:
        if not self.exportLw and not self.exportCg and not self.exportDsk:
            raise ValueError("At least one export target must be on")
        slide_ids = [slide.id.strip() for slide in self.slides]
        if not all(slide_ids) or len(set(slide_ids)) != len(slide_ids):
            raise ValueError("Slide ids must be non-empty and unique")
        if any(sid.endswith("__landing") for sid in slide_ids):
            raise ValueError("Slide ids may not end in '__landing' (reserved for synthetic landings)")
        for slide in self.slides:
            for view in (slide, slide.cg):
                if view is None:
                    continue
                church_ids = [church.id.strip() for church in view.churches]
                if not all(church_ids) or len(set(church_ids)) != len(church_ids):
                    raise ValueError("Object ids must be non-empty and unique on each slide")
        links = [(link.from_, link.to) for link in self.links]
        if len(set(links)) != len(links):
            raise ValueError("Map links must be unique")
        if any(source not in slide_ids or target not in slide_ids for source, target in links):
            raise ValueError("Map links must reference slides in this document")
        slide_id_set = set(slide_ids)
        pruned: list[MapsLink] = []
        seen_retired: set[tuple[str, str]] = set()
        for link in self.retiredLinks:
            key = (link.from_, link.to)
            if link.from_ not in slide_id_set or link.to not in slide_id_set:
                continue
            if key in seen_retired:
                continue
            seen_retired.add(key)
            pruned.append(link)
        if len(pruned) > MAX_RETIRED_LINKS:
            pruned = pruned[-MAX_RETIRED_LINKS:]
        self.retiredLinks = pruned
        return self


class TilePrefetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    countries: list[str] = Field(default_factory=list)
    cameras: list[MapsCamera] = Field(default_factory=list)
    maxzoom: int | None = None
    width: float = 7680
    height: float = 1080
    terrain: bool = False
    rels: list[str] | None = None


class ExportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exportLw: bool | None = None
    exportCg: bool | None = None
    exportDsk: bool | None = None


def _job_or_404(job_id: str):
    job = _runner().get(job_id)
    if not job or job.feature != "maps":
        raise HTTPException(404, "Unknown maps job")
    return job


def _require_idle(job) -> None:
    """Authoring writes may resume after a failed encode (`error`). Block only in-flight jobs."""
    if job.status in {"queued", "running"}:
        raise HTTPException(409, "Maps job is not ready")


def _safe_name(raw: str) -> str:
    name = Path(raw).name
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Invalid slideId")
    return name


def _asset_root(result: dict[str, Any]) -> Path:
    root = Path(str(result.get("outputDir") or "")) / "assets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _asset_path(result: dict[str, Any], asset_id: str) -> Path:
    if not asset_id or Path(asset_id).name != asset_id:
        raise HTTPException(400, "Invalid Maps asset id")
    return _asset_root(result) / f"{asset_id}.png"


def _decode_png(raw: bytes) -> tuple[bytes, int, int, str]:
    if not raw or len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Image exceeds the 20 MB upload limit")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.width * image.height > 24_000_000:
                raise HTTPException(413, "Image exceeds the 24 megapixel limit")
            converted = image.convert("RGBA")
            output = io.BytesIO()
            converted.save(output, "PNG", optimize=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "Invalid image upload") from exc
    payload = output.getvalue()
    return payload, converted.width, converted.height, hashlib.sha256(payload).hexdigest()


def _read_limited(stream, limit: int = 20 * 1024 * 1024) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "Image exceeds the 20 MB upload limit")
        chunks.append(chunk)


RASTER_MAX_BYTES = 20 * 1024 * 1024
RASTER_MAX_SIDE = 8192


async def _read_limited_request(request: Request, limit: int | None = None) -> bytes:
    cap = RASTER_MAX_BYTES if limit is None else limit
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise HTTPException(413, f"Body exceeds the {cap // (1024 * 1024)} MB upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_raster(raw: bytes, *, max_side: int | None = None) -> tuple[int, int]:
    cap = RASTER_MAX_SIDE if max_side is None else max_side
    is_png = raw.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = raw[:3] == b"\xff\xd8\xff"
    if not raw or not (is_png or is_jpeg):
        raise HTTPException(400, "Invalid image upload")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.width, image.height
    except Exception as exc:
        raise HTTPException(400, "Invalid image upload") from exc
    if width < 1 or height < 1 or width > cap or height > cap:
        raise HTTPException(400, f"Image dimensions must be between 1 and {cap} pixels")
    return width, height


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _referenced_asset_ids(doc: MapsDocument) -> set[str]:
    return {
        church.assetId
        for slide in doc.slides
        for view in (slide, slide.cg)
        if view is not None
        for church in view.churches
        if church.assetId
    }


def _validate_asset_document(doc: MapsDocument, result: dict[str, Any]) -> MapsDocument:
    for slide in doc.slides:
        for view in (slide, slide.cg):
            if view is None:
                continue
            for church in view.churches:
                if church.photoPath:
                    raise HTTPException(400, "Legacy external photo paths are not supported; upload an owned Maps asset")
                if church.kind == "landmark" and not church.assetId:
                    raise HTTPException(400, "Landmark objects require an uploaded Maps asset")
                if church.reveal and church.kind != "landmark":
                    raise HTTPException(400, "Paint-on reveal is only available for landmark objects")
            if view.revealMovie and not any(c.kind == "landmark" and c.reveal for c in view.churches):
                raise HTTPException(400, "Reveal as slide movie needs a landmark with a paint-on reveal")
    available = {asset.id: asset for asset in (MapsAsset.model_validate(row) for row in result.get("assets") or [])}
    referenced = _referenced_asset_ids(doc)
    if referenced - set(available):
        raise HTTPException(400, "Maps document references an unknown asset")
    for asset_id in referenced:
        if not _asset_path(result, asset_id).is_file():
            raise HTTPException(400, "Maps document references an unavailable asset")
    for slide in doc.slides:
        for view in (slide, slide.cg):
            if view is None:
                continue
            for church in view.churches:
                if church.assetId:
                    asset = available[church.assetId]
                    church.assetVersion = asset.version
                    church.assetWidth = asset.width
                    church.assetHeight = asset.height
    doc.assets = [available[asset_id] for asset_id in sorted(referenced)]
    return doc


def _dump_document(doc: MapsDocument) -> dict[str, Any]:
    return {
        "defaultStyle": doc.defaultStyle,
        "crop": doc.crop,
        "exportLw": doc.exportLw,
        "exportCg": doc.exportCg,
        "exportDsk": doc.exportDsk,
        "hiddenLayers": list(doc.hiddenLayers),
        "cachedCountries": list(doc.cachedCountries),
        "assets": [asset.model_dump() for asset in doc.assets],
        "slides": [slide.model_dump() for slide in doc.slides],
        "links": [link.dumped() for link in doc.links],
        "retiredLinks": [link.dumped() for link in doc.retiredLinks],
    }


def _parse_document(payload: dict[str, Any]) -> MapsDocument:
    cleaned = {key: value for key, value in payload.items() if key not in DIR_KEYS}
    keep = (
        "defaultStyle",
        "crop",
        "exportLw",
        "exportCg",
        "exportDsk",
        "hiddenLayers",
        "cachedCountries",
        "assets",
        "slides",
        "links",
        "retiredLinks",
    )
    body = {key: cleaned[key] for key in keep if key in cleaned}
    for slide in body.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for isolate in (slide.get("isolate"), (slide.get("cg") or {}).get("isolate")):
            if isinstance(isolate, dict) and isolate.get("mode") == "erase":
                isolate["mode"] = "darken"
    try:
        return MapsDocument.model_validate(body)
    except Exception as exc:
        message = str(exc)
        if "exportLw" in message or "exportCg" in message or "exportDsk" in message or "at least one" in message.lower():
            raise HTTPException(400, "At least one export target must be on") from exc
        raise HTTPException(400, message) from exc


def _seed_result(job_id: str) -> dict[str, Any]:
    root = output_root() / ".maps" / job_id
    preview = root / "previews"
    preview.mkdir(parents=True, exist_ok=True)
    camera = sea_overview_camera()
    return {
        "stem": f"maps-{job_id}",
        "outputDir": str(root),
        "workDir": str(root),
        "previewDir": str(preview),
        "previews": {"maps": str(preview)},
        "previewFiles": {"maps": []},
        "exportLw": True,
        "exportCg": True,
        "exportDsk": False,
        "stateRevision": 0,
        "isolateDefaultVersion": 1,
        "defaultStyle": "positron",
        "crop": "center+cg",
        "hiddenLayers": list(DEFAULT_HIDDEN_LAYERS),
        "cachedCountries": [],
        "assets": [],
        "slides": [
            {
                "id": "s1",
                "title": "Southeast Asia",
                "style": "positron",
                "camera": camera,
                "highlights": [],
                "churches": [],
                "hiddenLayers": list(DEFAULT_HIDDEN_LAYERS),
                "hillshade": False,
                "cgShiftX": 0,
                "cgShiftY": 0,
            }
        ],
        "links": [],
        "retiredLinks": [],
    }


def _run_maps(job) -> dict[str, Any]:
    return _seed_result(job.id)


def _next_slide_id(slides: list[dict[str, Any]]) -> str:
    used = {str(slide.get("id") or "") for slide in slides}
    index = 1
    while f"s{index}" in used:
        index += 1
    return f"s{index}"


def _row_slide(row: dict[str, str], slide_id: str, hidden_layers: list[str] | None = None) -> dict[str, Any]:
    name = (row.get("name") or row.get("title") or "Untitled").strip() or "Untitled"
    lat_raw = (row.get("lat") or row.get("latitude") or "").strip()
    lon_raw = (row.get("lon") or row.get("lng") or row.get("longitude") or "").strip()
    maps_url = (row.get("maps_url") or row.get("url") or "").strip()
    place = (row.get("place") or "").strip()
    camera = None
    if lat_raw and lon_raw:
        camera = camera_dict(float(lat_raw), float(lon_raw), 8)
    elif maps_url:
        parsed = parse_maps_query(maps_url)
        if parsed:
            camera = parsed["camera"]
    query = place or name
    country = find_country(query) if query else None
    if camera is None and country:
        bbox = geometry_bbox(country.get("geometry") or {})
        if bbox:
            from obed_edom.maps_geo import camera_from_bbox

            camera = camera_from_bbox(bbox)
    if camera is None:
        hit = geocode(query, wait=True)
        camera = hit["camera"]
        if not name or name == "Untitled":
            name = str(hit.get("label") or name)
    church = {
        "id": f"{slide_id}-pin",
        "name": name,
        "lat": camera["lat"],
        "lon": camera["lon"],
        "kind": "dropPin",
        "color": "#c44a42",
    }
    return {
        "id": slide_id,
        "title": name,
        "style": "positron",
        "camera": camera,
        "highlights": [],
        "churches": [church],
        "hiddenLayers": list(DEFAULT_HIDDEN_LAYERS) if hidden_layers is None else list(hidden_layers),
        "hillshade": False,
        "cgShiftX": 0,
        "cgShiftY": 0,
    }


def _parse_csv(text: str) -> list[dict[str, str]]:
    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV needs a header row with a name column")
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {str(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
        if any(row.values()):
            rows.append(row)
    if not rows:
        raise HTTPException(400, "CSV has no data rows")
    return rows


def _run_bootstrap(job, csv_text: str, replace: bool) -> dict[str, Any]:
    result = inherit_hidden_layers(dict(job.result or {}))
    if replace:
        _clear_derived_maps_output(result)
    slides = [] if replace else list(result.get("slides") or [])
    links = [] if replace else list(result.get("links") or [])
    stored_hidden_layers = result.get("hiddenLayers")
    hidden_layers = list(DEFAULT_HIDDEN_LAYERS) if stored_hidden_layers is None else stored_hidden_layers
    for row in _parse_csv(csv_text):
        slide = _row_slide(row, _next_slide_id(slides), hidden_layers)
        if slides:
            prev = slides[-1]
            links.append(
                {
                    "from": prev["id"],
                    "to": slide["id"],
                    "kind": infer_hop_kind(prev, slide),
                    "objectTransition": "fade" if infer_hop_kind(prev, slide) == "movie" else None,
                    "duration": 1.2,
                    "playWithoutClick": False,
                }
            )
        slides.append(slide)
    result["slides"] = slides
    result["links"] = links
    return result


def _next_pin_id(churches: list[dict[str, Any]]) -> str:
    used = {str(church.get("id") or "") for church in churches}
    index = 1
    while f"p{index}" in used:
        index += 1
    return f"p{index}"


def _run_pin_bootstrap(job, csv_text: str, slide_id: str, audience: str) -> dict[str, Any]:
    result = dict(job.result or {})
    slides = [dict(slide) for slide in (result.get("slides") or [])]
    target = next((slide for slide in slides if str(slide.get("id") or "") == slide_id), None)
    if target is None:
        raise ValueError("Target slide is not in this deck")
    view = dict(target.get("cg") or {}) if audience == "cg" and isinstance(target.get("cg"), dict) else target
    churches = [dict(church) for church in (view.get("churches") or [])]
    for row in _parse_csv(csv_text):
        generated = _row_slide(row, "csv")["churches"][0]
        churches.append({**generated, "id": _next_pin_id(churches)})
    if view is target:
        target["churches"] = churches
    else:
        target["cg"] = {**view, "churches": churches}
    result["slides"] = slides
    return result


def _session_path(job) -> Path:
    result = job.result or {}
    output_dir = Path(str(result.get("outputDir") or ""))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"{str(result.get('stem') or f'maps-{job.id}')}.obedmaps"


def _clear_derived_maps_output(result: dict[str, Any], *, clear_preview: bool = True) -> Path:
    output_dir = Path(str(result.get("outputDir") or ""))
    preview_dir = Path(str(result.get("previewDir") or output_dir / "previews"))
    output_root_resolved = output_dir.resolve()
    for key in ("destPath", "destPathCg", "destPathDsk"):
        raw = str(result.get(key) or "")
        if raw:
            derived = Path(raw)
            try:
                derived.resolve().relative_to(output_root_resolved)
            except ValueError:
                pass
            else:
                try:
                    derived.unlink(missing_ok=True)
                except OSError:
                    pass
    for key in ("destPath", "destPathCg", "destPathDsk", "flags", "flagsCg", "flagsDsk"):
        result.pop(key, None)
    folders = [output_dir / "frames", output_dir / "movies", output_dir / "stills", output_dir / "plates"]
    if clear_preview:
        folders.append(preview_dir)
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
    if clear_preview:
        preview_dir.mkdir(parents=True, exist_ok=True)
    result["previewFiles"] = {"maps": []}
    return preview_dir


def _write_session_archive(job) -> Path:
    result = dict(job.result or {})
    doc = _validate_asset_document(_parse_document(result), result)
    path = _session_path(job)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    manifest = {
        "format": "obed-edom-maps",
        "version": SESSION_VERSION,
        "isolateDefaultVersion": int(result.get("isolateDefaultVersion") or 0),
        "document": _dump_document(doc),
    }
    preview_dir = Path(str(result.get("previewDir") or ""))
    preview_names = {
        Path(str(name)).name
        for name in ((result.get("previewFiles") or {}).get("maps") or [])
        if Path(str(name)).name == str(name)
    }
    entries: list[tuple[Path, str]] = []
    for name in sorted(preview_names):
        source = preview_dir / name
        if source.is_file():
            entries.append((source, f"previews/{name}"))
    referenced = _referenced_asset_ids(doc)
    for asset_id in sorted(referenced):
        source = _asset_path(result, asset_id)
        if not source.is_file():
            raise HTTPException(400, "Maps document references an unavailable asset")
        entries.append((source, f"assets/{asset_id}.png"))
    root = cache_root()
    for source in sorted(root.rglob("*")):
        if source.is_file() and not source.name.endswith(".tmp"):
            entries.append((source, f"tile-cache/{source.relative_to(root).as_posix()}"))
    total_bytes = len(json.dumps(manifest, indent=2).encode("utf-8")) + sum(source.stat().st_size for source, _ in entries)
    if len(entries) + 1 > SESSION_MAX_FILES or total_bytes > SESSION_MAX_BYTES:
        raise HTTPException(413, "Maps session is too large; clear or reduce the tile cache before saving")
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        for source, archive_name in entries:
            archive.write(source, archive_name)
    temp_path.replace(path)
    return path


def _valid_session_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if member.is_absolute() or not member.parts or ".." in member.parts or "\\" in name:
        raise HTTPException(400, "Invalid Maps session archive path")
    return member


def _bump_legacy_isolate(result: dict[str, Any]) -> None:
    if int(result.get("isolateDefaultVersion") or 0) >= 1:
        return
    for slide in result.get("slides") or []:
        for view in [slide, *([slide["cg"]] if isinstance(slide.get("cg"), dict) else [])]:
            isolate = view.get("isolate")
            if (
                isinstance(isolate, dict)
                and isolate.get("mode") == "darken"
                and abs(float(isolate.get("strength", 0)) - 0.60) < 1e-6
            ):
                isolate["strength"] = DEFAULT_ISOLATE_STRENGTH
    result["isolateDefaultVersion"] = 1


def _read_session_archive(job, source) -> tuple[dict[str, Any], dict[str, int]]:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "Invalid Maps session file") from exc
    with archive:
        files = [info for info in archive.infolist() if not info.is_dir()]
        if len(files) > SESSION_MAX_FILES or sum(info.file_size for info in files) > SESSION_MAX_BYTES:
            raise HTTPException(413, "Maps session is too large")
        preview_entries: list[tuple[zipfile.ZipInfo, str]] = []
        tile_entries: list[tuple[zipfile.ZipInfo, str]] = []
        asset_entries: list[tuple[zipfile.ZipInfo, str]] = []
        destinations: set[str] = set()
        for info in files:
            member = _valid_session_member(info.filename)
            destination = member.as_posix()
            if destination in destinations:
                raise HTTPException(400, "Maps session has duplicate archive paths")
            destinations.add(destination)
            if len(member.parts) == 2 and member.parts[0] == "previews":
                name = member.parts[1]
                if Path(name).name != name:
                    raise HTTPException(400, "Invalid Maps session preview path")
                preview_entries.append((info, name))
            elif member.parts[0] == "tile-cache" and len(member.parts) > 1:
                try:
                    rel = normalize_rel("/".join(member.parts[1:]))
                except ValueError as exc:
                    raise HTTPException(400, "Invalid Maps session tile path") from exc
                tile_entries.append((info, rel))
            elif len(member.parts) == 2 and member.parts[0] == "assets" and member.parts[1].endswith(".png"):
                asset_id = member.parts[1][:-4]
                if not asset_id or Path(asset_id).name != asset_id:
                    raise HTTPException(400, "Invalid Maps session asset path")
                asset_entries.append((info, asset_id))
            elif destination != "manifest.json":
                raise HTTPException(400, "Maps session contains an unknown archive path")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Maps session manifest is missing or invalid") from exc
        if manifest.get("format") != "obed-edom-maps" or manifest.get("version") not in {1, SESSION_VERSION}:
            raise HTTPException(400, "Unsupported Maps session format")
        isolate_default_version_raw = manifest.get("isolateDefaultVersion", 0)
        if isinstance(isolate_default_version_raw, bool) or not isinstance(isolate_default_version_raw, int) or isolate_default_version_raw < 0:
            raise HTTPException(400, "Invalid Maps session isolateDefaultVersion")
        isolate_default_version = isolate_default_version_raw
        doc = _parse_document(manifest.get("document") or {})
        if len({asset.id for asset in doc.assets}) != len(doc.assets):
            raise HTTPException(400, "Maps session has duplicate asset metadata ids")
        assets_by_id = {asset.id: asset for asset in doc.assets}
        referenced = _referenced_asset_ids(doc)
        if manifest.get("version") == 1 and (asset_entries or assets_by_id):
            raise HTTPException(400, "Version 1 Maps sessions cannot contain image assets")
        if {asset_id for _, asset_id in asset_entries} != referenced or set(assets_by_id) != referenced:
            raise HTTPException(400, "Maps session assets do not match the manifest")
        result = dict(job.result or {})
        output_dir = Path(str(result.get("outputDir") or ""))
        output_dir.mkdir(parents=True, exist_ok=True)
        preview_dir = Path(str(result.get("previewDir") or output_dir / "previews"))
        tile_root = cache_root()
        imported_previews = {name for _, name in preview_entries}
        created_tiles: list[Path] = []
        with tempfile.TemporaryDirectory(prefix=".session-import-", dir=output_dir) as staging_raw:
            staging = Path(staging_raw)
            staged_previews = staging / "previews"
            staged_tiles = staging / "tile-cache"
            staged_assets = staging / "assets"
            staged_previews.mkdir()
            try:
                for info, name in preview_entries:
                    with archive.open(info) as src, (staged_previews / name).open("wb") as dest:
                        shutil.copyfileobj(src, dest)
                for info, rel in tile_entries:
                    staged = staged_tiles / rel
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, staged.open("wb") as dest:
                        shutil.copyfileobj(src, dest)
                for info, asset_id in asset_entries:
                    with archive.open(info) as src:
                        payload, width, height, version = _decode_png(_read_limited(src))
                    meta = assets_by_id[asset_id]
                    if (meta.width, meta.height, meta.version) != (width, height, version):
                        raise HTTPException(400, "Maps session asset metadata does not match its image")
                    staged_assets.mkdir(exist_ok=True)
                    (staged_assets / f"{asset_id}.png").write_bytes(payload)
            except zipfile.BadZipFile as exc:
                raise HTTPException(400, "Maps session archive is corrupt") from exc
            try:
                for _, rel in tile_entries:
                    dest = tile_root / rel
                    if dest.exists():
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    staged = staged_tiles / rel
                    with tempfile.NamedTemporaryFile(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent, delete=False) as temp:
                        temp_path = Path(temp.name)
                    try:
                        shutil.copyfile(staged, temp_path)
                        temp_path.replace(dest)
                    finally:
                        temp_path.unlink(missing_ok=True)
                    created_tiles.append(dest)
            except Exception:
                for created in created_tiles:
                    created.unlink(missing_ok=True)
                raise
            remap = {old_id: uuid.uuid4().hex for _info, old_id in asset_entries}
            installed_assets = staging / "installed-assets"
            installed_assets.mkdir()
            for old_id, new_id in remap.items():
                shutil.copyfile(staged_assets / f"{old_id}.png", installed_assets / f"{new_id}.png")
            asset_root = Path(str(result.get("outputDir") or "")) / "assets"
            previous_assets = staging / "previous-assets"
            if asset_root.exists():
                asset_root.replace(previous_assets)
            try:
                installed_assets.replace(asset_root)
            except Exception:
                if previous_assets.exists():
                    previous_assets.replace(asset_root)
                for created in created_tiles:
                    created.unlink(missing_ok=True)
                raise
            previous_previews = staging / "previous-previews"
            if preview_dir.exists():
                preview_dir.replace(previous_previews)
            try:
                staged_previews.replace(preview_dir)
            except Exception:
                if previous_previews.exists():
                    previous_previews.replace(preview_dir)
                shutil.rmtree(asset_root, ignore_errors=True)
                if previous_assets.exists():
                    previous_assets.replace(asset_root)
                for created in created_tiles:
                    created.unlink(missing_ok=True)
                raise
            _clear_derived_maps_output(result, clear_preview=False)
    dumped = _dump_document(doc)
    if asset_entries:
        for slide in dumped["slides"]:
            for view in [slide, *([slide["cg"]] if isinstance(slide.get("cg"), dict) else [])]:
                for church in view.get("churches") or []:
                    if church.get("assetId") in remap:
                        church["assetId"] = remap[church["assetId"]]
        dumped["assets"] = [{**asset.model_dump(), "id": remap[asset.id]} for asset in doc.assets]
    for slide in dumped["slides"]:
        slide.pop("movieMov", None)
        slide.pop("movieDuration", None)
        if slide.get("stillPng") not in imported_previews:
            slide.pop("stillPng", None)
        if isinstance(slide.get("cg"), dict):
            slide["cg"].pop("movieMov", None)
            slide["cg"].pop("movieDuration", None)
            if slide["cg"].get("stillPng") not in imported_previews:
                slide["cg"].pop("stillPng", None)
    dumped["links"] = coerce_link_kinds(dumped["slides"], dumped["links"])
    result.update(dumped)
    result["previewFiles"] = {"maps": sorted(imported_previews)}
    result["isolateDefaultVersion"] = isolate_default_version
    _bump_legacy_isolate(result)
    return result, {"tiles": len(tile_entries), "previews": len(imported_previews)}


def _run_export(job, export_lw: bool, export_cg: bool, export_dsk: bool = False) -> dict[str, Any]:
    from obed_edom.maps_keynote import export_maps_job

    return export_maps_job(job, export_lw=export_lw, export_cg=export_cg, export_dsk=export_dsk)


@router.post("")
def create_maps() -> dict:
    job = _runner().submit("maps", _run_maps, feature="maps")
    return _runner().public_dict(job)


@router.post("/{job_id}/assets")
async def upload_asset(job_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    payload, width, height, version = _decode_png(_read_limited(file.file))
    asset_id = uuid.uuid4().hex
    def register(result: dict[str, Any]) -> dict[str, Any]:
        path = _asset_path(result, asset_id); temp = path.with_suffix(".tmp")
        temp.write_bytes(payload); temp.replace(path)
        result["assets"] = [*(result.get("assets") or []), {"id": asset_id, "version": version, "width": width, "height": height}]
        return result
    updated = _mutate_document(job_id, None, register)
    result = dict(updated["result"] or {})
    return {
        "asset": {"id": asset_id, "version": version, "width": width, "height": height},
        "stateRevision": result.get("stateRevision"),
        "document": _dump_document(_parse_document(result)),
    }


@router.get("/{job_id}/assets/{asset_id}.png")
def get_asset(job_id: str, asset_id: str):
    job = _job_or_404(job_id)
    result = dict(job.result or {})
    if asset_id not in {str(row.get("id") or "") for row in (result.get("assets") or [])}:
        raise HTTPException(404, "Unknown Maps asset")
    path = _asset_path(result, asset_id)
    if not path.is_file():
        raise HTTPException(404, "Maps asset is unavailable")
    return FileResponse(path, media_type="image/png", headers={"Content-Disposition": f'inline; filename="{asset_id}.png"'})


@router.get("/tiles/countries")
def tile_cache_countries() -> list[dict[str, str]]:
    return cache_country_rows()


@router.get("/tiles/{rest:path}")
def get_cached_tile(rest: str):
    try:
        rel = normalize_rel(rest)
    except ValueError as exc:
        raise HTTPException(400, "Invalid tile path") from exc
    try:
        path = fetch_and_cache(rel)
    except Exception as exc:
        raise HTTPException(502, f"Tile fetch failed: {exc}") from exc
    return FileResponse(
        path,
        media_type=media_type_for(rel),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/tile-cache/plan")
def plan_tiles(payload: TilePrefetchBody) -> dict[str, Any]:
    if payload.rels is not None:
        raise HTTPException(400, "rels is not supported for tile-cache/plan")
    rels: list[str] = []
    capped = False
    cameras_total = 0
    cameras_used = 0
    if payload.countries:
        z = DEFAULT_COUNTRY_MAXZOOM if payload.maxzoom is None else int(payload.maxzoom)
        rels.extend(rels_for_countries(payload.countries, maxzoom=z))
    if payload.cameras:
        z = DEFAULT_CAMERA_MAXZOOM if payload.maxzoom is None else int(payload.maxzoom)
        plan = camera_tile_plan(
            [cam.model_dump() for cam in payload.cameras],
            width=payload.width,
            height=payload.height,
            maxzoom=z,
            terrain=payload.terrain,
        )
        rels.extend(plan["rels"])
        capped = plan["capped"]
        cameras_total = plan["cameras"]
        cameras_used = plan["camerasUsed"]
    unique = list(dict.fromkeys(normalize_rel(rel) for rel in rels))
    cached = sum(1 for rel in unique if cache_path(rel).is_file())
    return {
        "ok": True,
        "rels": unique,
        "tiles": len(unique),
        "cached": cached,
        "capped": capped,
        "cameras": cameras_total,
        "camerasUsed": cameras_used,
    }


@router.post("/tile-cache/prefetch")
def prefetch_tiles(payload: TilePrefetchBody) -> dict[str, Any]:
    if payload.rels is not None:
        if payload.countries or payload.cameras:
            raise HTTPException(400, "rels cannot be combined with countries or cameras")
        if len(payload.rels) > MAX_PREFETCH_BATCH:
            raise HTTPException(400, f"rels batch cannot exceed {MAX_PREFETCH_BATCH}")
        try:
            batch = [normalize_rel(rel) for rel in payload.rels]
        except ValueError as exc:
            raise HTTPException(400, "Invalid tile path") from exc
        stats = prefetch_rels(batch)
        stats["ok"] = True
        return stats
    rels: list[str] = []
    if payload.countries:
        z = DEFAULT_COUNTRY_MAXZOOM if payload.maxzoom is None else int(payload.maxzoom)
        rels.extend(rels_for_countries(payload.countries, maxzoom=z))
    if payload.cameras:
        z = DEFAULT_CAMERA_MAXZOOM if payload.maxzoom is None else int(payload.maxzoom)
        rels.extend(
            rels_for_cameras(
                [cam.model_dump() for cam in payload.cameras],
                width=payload.width,
                height=payload.height,
                maxzoom=z,
                terrain=payload.terrain,
            )
        )
    stats = prefetch_rels(rels)
    stats["ok"] = True
    return stats


@router.get("/tile-cache")
def tile_cache_get() -> dict[str, int]:
    return cache_stats()


@router.delete("/tile-cache")
def tile_cache_clear() -> dict[str, int]:
    return clear_tile_cache()


@router.get("/{job_id}/session")
def save_session(job_id: str):
    job = _job_or_404(job_id)
    _require_idle(job)
    path = _write_session_archive(job)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/{job_id}/session")
async def load_session(job_id: str, file: UploadFile = File(...)) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    previous_status = job.status
    job.status = "running"

    def import_uploaded() -> tuple[dict[str, Any], dict[str, int]]:
        with tempfile.NamedTemporaryFile(suffix=".obedmaps") as uploaded:
            total = 0
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > SESSION_MAX_BYTES:
                    raise HTTPException(413, "Maps session is too large")
                uploaded.write(chunk)
            uploaded.flush()
            return _read_session_archive(job, uploaded.name)

    try:
        result, imported = await run_in_threadpool(import_uploaded)
    except Exception:
        job.status = previous_status
        raise
    finally:
        await file.close()
    job.status = "done"
    job.error = None
    payload = _mutate_document(job_id, None, lambda _latest: result)
    payload["sessionImport"] = imported
    return payload


@router.post("/{job_id}/state")
def save_state(job_id: str, payload: dict[str, Any]) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("document"), dict):
        raise HTTPException(400, "Maps saves require a document envelope")
    incoming = payload["document"]
    expected = payload.get("expectedRevision")
    if not isinstance(expected, int):
        raise HTTPException(400, "expectedRevision must be an integer")
    def apply(result: dict[str, Any]) -> dict[str, Any]:
      keep = (
        "defaultStyle",
        "crop",
        "exportLw",
        "exportCg",
        "exportDsk",
        "hiddenLayers",
        "cachedCountries",
        "assets",
        "slides",
        "links",
        "retiredLinks",
      )
      merged = {key: result.get(key) for key in keep}
      for key in keep:
        if key in incoming:
            merged[key] = incoming[key]
      merged["assets"] = result.get("assets") or []
      doc = _validate_asset_document(_parse_document(merged), result)
      dumped = _dump_document(doc)
      dumped["links"] = coerce_link_kinds(dumped["slides"], dumped["links"])
      result.update(dumped)
      return result
    return _mutate_document(job_id, expected, apply)


@router.post("/{job_id}/png")
async def post_png(
    job_id: str,
    request: Request,
    slideId: str | None = Query(None),
    plateId: str | None = Query(None),
    kind: str = Query("thumb"),
    audience: Literal["lw", "cg"] = Query("lw"),
    variant: str | None = Query(None),
) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    result = dict(job.result or {})
    slides = list(result.get("slides") or [])
    ids = {str(slide.get("id")) for slide in slides}
    body = await _read_limited_request(request)
    if not body:
        raise HTTPException(400, "PNG body required")
    if kind not in {"thumb", "still", "plate"}:
        raise HTTPException(400, "kind must be thumb, still, or plate")
    _validate_raster(body)
    output_dir = Path(str(result.get("outputDir") or ""))
    if kind == "plate":
        if not plateId:
            raise HTTPException(400, "plateId is required for kind=plate")
        safe_plate = _safe_name(plateId)
        folder = output_dir / "plates"
        plate_name = safe_plate if audience != "cg" or safe_plate.endswith("-cg") else f"{safe_plate}-cg"
        path = folder / plate_filename(plate_name)
        _write_atomic(path, body)
        return _runner().public_dict(job)
    if not slideId:
        raise HTTPException(400, "slideId is required")
    landing_base = slideId[: -len("__landing")] if slideId.endswith("__landing") else None
    landing_ok = landing_base in ids and kind == "still" and variant != "country" if landing_base else False
    if slideId not in ids and not landing_ok:
        raise HTTPException(400, "slideId is not in this deck")
    safe = _safe_name(slideId)
    if audience == "cg":
        safe = f"{Path(safe).stem}_CG{Path(safe).suffix}"
    if not safe.endswith(".png"):
        safe = f"{safe}.png"
    if kind == "still":
        if variant is not None and variant != "country":
            raise HTTPException(400, "variant must be country")
        folder = output_dir / "stills"
        name = Path(safe).name
        if variant == "country":
            name = f"{Path(name).stem}-country{Path(name).suffix}"
        _write_atomic(folder / name, body)
        return _runner().public_dict(job)
    folder = Path(str(result.get("previewDir") or ""))
    path = folder / Path(safe).name
    _write_atomic(path, body)
    next_slides = []
    names = list((result.get("previewFiles") or {}).get("maps") or [])
    if safe not in names:
        names.append(safe)
    for slide in slides:
        item = dict(slide)
        if item.get("id") == slideId:
            if audience == "cg" and isinstance(item.get("cg"), dict):
                item["cg"] = {**item["cg"], "stillPng": safe}
            else:
                item["stillPng"] = safe
        next_slides.append(item)
    result["slides"] = next_slides
    files = dict(result.get("previewFiles") or {})
    files["maps"] = names
    result["previewFiles"] = files
    def publish(latest: dict[str, Any]) -> dict[str, Any]:
        fresh_slides = list(latest.get("slides") or [])
        fresh_names = list((latest.get("previewFiles") or {}).get("maps") or [])
        if safe not in fresh_names: fresh_names.append(safe)
        for item in fresh_slides:
            if item.get("id") == slideId:
                if audience == "cg" and isinstance(item.get("cg"), dict): item["cg"] = {**item["cg"], "stillPng": safe}
                else: item["stillPng"] = safe
        latest["slides"] = fresh_slides; latest["previewFiles"] = {**(latest.get("previewFiles") or {}), "maps": fresh_names}
        return latest
    return _mutate_document(job_id, None, publish)


@router.post("/{job_id}/frame")
async def post_frame(
    job_id: str,
    request: Request,
    slideId: str | None = Query(None),
    index: int = Query(...),
    count: int = Query(...),
    fps: int = Query(30),
    audience: Literal["lw", "cg"] = Query("lw"),
) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    result = dict(job.result or {})
    slides = list(result.get("slides") or [])
    ids = {str(slide.get("id")) for slide in slides}
    if not slideId or slideId not in ids:
        raise HTTPException(400, "slideId is not in this deck")
    if not 1 <= count <= 20000:
        raise HTTPException(400, "count must be between 1 and 20000")
    if not 0 <= index < count:
        raise HTTPException(400, "index must be between 0 and count - 1")
    if not 1 <= fps <= 60:
        raise HTTPException(400, "fps must be between 1 and 60")
    body = await _read_limited_request(request)
    if not body:
        raise HTTPException(400, "Frame body required")
    _validate_raster(body)
    content_type = request.headers.get("content-type", "")
    output_dir = Path(str(result.get("outputDir") or ""))
    from obed_edom.maps_movie import write_frame, write_frames_meta

    write_frame(output_dir, slideId, index, body, content_type, audience)
    write_frames_meta(output_dir, slideId, fps=fps, count=count, audience=audience)
    return {"ok": True, "index": index, "count": count}


@router.get("/{job_id}/export-plan")
def export_plan(job_id: str) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    result = inherit_hidden_layers(dict(job.result or {}))
    slides = list(result.get("slides") or [])
    links = list(result.get("links") or [])
    plan = maps_export_plan(slides, links)
    payload = {"links": plan["links"], "stills": plan["stills"], "plates": plan["plates"]}
    if any(isinstance(slide.get("cg"), dict) for slide in slides):
        cg = split_cg_export_plan(slides, links)
        payload["cg"] = {
            "links": cg["links"], "stills": cg["stills"], "plates": cg["plates"],
            "affectedSlideIds": cg["affectedSlideIds"],
        }
    return payload


@router.post("/{job_id}/bootstrap-csv")
async def bootstrap_csv(
    job_id: str,
    file: UploadFile | None = File(None),
    csv_text: str | None = Form(None),
    replace: bool = Form(False),
    targetSlideId: str | None = Form(None),
    audience: Literal["lw", "cg"] = Form("lw"),
) -> dict:
    job = _job_or_404(job_id)
    if job.status == "running":
        raise HTTPException(409, "Maps job is already running")
    text = csv_text or ""
    if file is not None:
        text = (await file.read()).decode("utf-8")
    if not text.strip():
        raise HTTPException(400, "CSV is empty")
    try:
        if targetSlideId:
            updated = _runner().rerun(
                job_id,
                lambda j, raw=text, sid=targetSlideId, aud=audience: _run_pin_bootstrap(j, raw, sid, aud),
            )
        else:
            updated = _runner().rerun(job_id, lambda j, raw=text, rep=replace: _run_bootstrap(j, raw, rep))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not updated:
        raise HTTPException(404, "Unknown maps job")
    return _runner().public_dict(updated)


@router.get("/geocode")
def geocode_get(q: str = "") -> dict:
    try:
        return geocode(q, wait=False)
    except GeocodeError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/ne/admin0")
def ne_admin0() -> JSONResponse:
    return JSONResponse(load_admin0(), headers={"Cache-Control": "public, max-age=86400"})


@router.get("/ne/places")
def ne_places() -> JSONResponse:
    return JSONResponse(load_places(), headers={"Cache-Control": "public, max-age=86400"})


@router.post("/{job_id}/export")
def export_maps(job_id: str, payload: ExportBody | None = None) -> dict:
    job = _job_or_404(job_id)
    result = job.result or {}
    export_lw = result.get("exportLw", True) if payload is None or payload.exportLw is None else payload.exportLw
    export_cg = result.get("exportCg", True) if payload is None or payload.exportCg is None else payload.exportCg
    export_dsk = result.get("exportDsk", False) if payload is None or payload.exportDsk is None else payload.exportDsk
    if not export_lw and not export_cg and not export_dsk:
        raise HTTPException(400, "At least one export target must be on")
    try:
        from obed_edom import maps_keynote as _maps_keynote  # noqa: F401
    except ImportError as exc:
        raise HTTPException(501, "Maps Keynote export is not available yet") from exc
    try:
        updated = _runner().rerun(job_id, lambda j, lw=export_lw, cg=export_cg, dsk=export_dsk: _run_export(j, lw, cg, dsk))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not updated:
        raise HTTPException(404, "Unknown maps job")
    return _runner().public_dict(updated)


@router.post("/{job_id}/cancel")
def cancel_maps_export(job_id: str) -> dict:
    job = _job_or_404(job_id)
    if job.feature != "maps":
        raise HTTPException(404, "Unknown maps job")
    cancelled = _runner().cancel(job_id)
    if not cancelled:
        raise HTTPException(404, "Unknown maps job")
    return _runner().public_dict(cancelled)

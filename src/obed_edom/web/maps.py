"""Maps tab API. P2 (is_backdrop / HEVC / score_resize / map_remap) is deferred."""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from obed_edom.maps_geo import (
    GeocodeError,
    camera_dict,
    clamp_cg_shift,
    find_country,
    geocode,
    geometry_bbox,
    infer_hop_kind,
    load_admin0,
    load_places,
    parse_maps_query,
    sea_overview_camera,
)
from obed_edom.maps_keynote import coerce_link_kinds, maps_export_plan, plate_filename, split_cg_export_plan
from obed_edom.maps_tiles import (
    DEFAULT_CAMERA_MAXZOOM,
    DEFAULT_COUNTRY_MAXZOOM,
    cache_country_rows,
    cache_root,
    cache_stats,
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

SESSION_VERSION = 1
SESSION_MAX_FILES = 100_000
SESSION_MAX_BYTES = 2 * 1024 * 1024 * 1024

DIR_KEYS = {"outputDir", "workDir", "previewDir", "stem", "previews", "previewFiles"}
STYLE_IDS = ("positron", "liberty", "bright", "dark", "fiord", "buildings3d")
MapsStyleId = Literal["positron", "liberty", "bright", "dark", "fiord", "buildings3d"]
MapsCropId = Literal["wall", "center+cg"]
MapsLayerFilterId = Literal[
    "roads", "roadnames", "shields", "pois", "rail", "buildings", "labels", "boundaries"
]
MapsHopKind = Literal["morph", "movie", "dissolve", "cut"]
MapsPinKind = Literal["dot", "dropPin"]
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


class MapsCgOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: MapsCamera
    style: MapsStyleId
    highlights: list[str] = Field(default_factory=list)
    churches: list[MapsChurch] = Field(default_factory=list)
    stillPng: str | None = None
    movieMov: str | None = None
    movieDuration: float | None = None


class MapsSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    style: MapsStyleId
    camera: MapsCamera
    highlights: list[str] = Field(default_factory=list)
    churches: list[MapsChurch] = Field(default_factory=list)
    stillPng: str | None = None
    movieMov: str | None = None
    movieDuration: float | None = None
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

    def dumped(self) -> dict[str, Any]:
        data = self.model_dump(by_alias=True)
        movie_only = ("easing", "route", "easeIn", "easeOut", "flyZoom")
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
    hiddenLayers: list[MapsLayerFilterId] = Field(default_factory=lambda: ["roadnames"])
    cachedCountries: list[str] = Field(default_factory=list)

    @field_validator("hiddenLayers", mode="before")
    @classmethod
    def _hidden_layers(cls, value: object) -> object:
        if value is None:
            return ["roadnames"]
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

    @field_validator("exportLw", "exportCg", "exportDsk")
    @classmethod
    def _bool(cls, value: bool) -> bool:
        return bool(value)

    @model_validator(mode="after")
    def _one_export(self) -> MapsDocument:
        if not self.exportLw and not self.exportCg and not self.exportDsk:
            raise ValueError("At least one export target must be on")
        return self


class TilePrefetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    countries: list[str] = Field(default_factory=list)
    cameras: list[MapsCamera] = Field(default_factory=list)
    maxzoom: int | None = None
    width: float = 7680
    height: float = 1080


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


def _dump_document(doc: MapsDocument) -> dict[str, Any]:
    return {
        "defaultStyle": doc.defaultStyle,
        "crop": doc.crop,
        "exportLw": doc.exportLw,
        "exportCg": doc.exportCg,
        "exportDsk": doc.exportDsk,
        "hiddenLayers": list(doc.hiddenLayers),
        "cachedCountries": list(doc.cachedCountries),
        "slides": [slide.model_dump() for slide in doc.slides],
        "links": [link.dumped() for link in doc.links],
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
        "slides",
        "links",
    )
    body = {key: cleaned[key] for key in keep if key in cleaned}
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
        "defaultStyle": "positron",
        "crop": "center+cg",
        "hiddenLayers": ["roadnames"],
        "cachedCountries": [],
        "slides": [
            {
                "id": "s1",
                "title": "Southeast Asia",
                "style": "positron",
                "camera": camera,
                "highlights": [],
                "churches": [],
                "cgShiftX": 0,
                "cgShiftY": 0,
            }
        ],
        "links": [],
    }


def _run_maps(job) -> dict[str, Any]:
    return _seed_result(job.id)


def _next_slide_id(slides: list[dict[str, Any]]) -> str:
    used = {str(slide.get("id") or "") for slide in slides}
    index = 1
    while f"s{index}" in used:
        index += 1
    return f"s{index}"


def _row_slide(row: dict[str, str], slide_id: str) -> dict[str, Any]:
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
    result = dict(job.result or {})
    if replace:
        _clear_derived_maps_output(result)
    slides = [] if replace else list(result.get("slides") or [])
    links = [] if replace else list(result.get("links") or [])
    for row in _parse_csv(csv_text):
        slide = _row_slide(row, _next_slide_id(slides))
        if slides:
            prev = slides[-1]
            links.append(
                {
                    "from": prev["id"],
                    "to": slide["id"],
                    "kind": infer_hop_kind(prev, slide),
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
    doc = _parse_document(result)
    path = _session_path(job)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    manifest = {
        "format": "obed-edom-maps",
        "version": SESSION_VERSION,
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
            elif destination != "manifest.json":
                raise HTTPException(400, "Maps session contains an unknown archive path")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Maps session manifest is missing or invalid") from exc
        if manifest.get("format") != "obed-edom-maps" or manifest.get("version") != SESSION_VERSION:
            raise HTTPException(400, "Unsupported Maps session format")
        doc = _parse_document(manifest.get("document") or {})
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
            previous_previews = staging / "previous-previews"
            if preview_dir.exists():
                preview_dir.replace(previous_previews)
            try:
                staged_previews.replace(preview_dir)
            except Exception:
                if previous_previews.exists():
                    previous_previews.replace(preview_dir)
                for created in created_tiles:
                    created.unlink(missing_ok=True)
                raise
            _clear_derived_maps_output(result, clear_preview=False)
    dumped = _dump_document(doc)
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
    return result, {"tiles": len(tile_entries), "previews": len(imported_previews)}


def _run_export(job, export_lw: bool, export_cg: bool, export_dsk: bool = False) -> dict[str, Any]:
    from obed_edom.maps_keynote import export_maps_job

    return export_maps_job(job, export_lw=export_lw, export_cg=export_cg, export_dsk=export_dsk)


@router.post("")
def create_maps() -> dict:
    job = _runner().submit("maps", _run_maps, feature="maps")
    return _runner().public_dict(job)


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


@router.post("/tile-cache/prefetch")
def prefetch_tiles(payload: TilePrefetchBody) -> dict[str, Any]:
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
            shutil.copyfileobj(file.file, uploaded)
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
    updated = _runner().update_result(job_id, result)
    if not updated:
        raise HTTPException(404, "Unknown maps job")
    payload = _runner().public_dict(updated)
    payload["sessionImport"] = imported
    return payload


@router.post("/{job_id}/state")
def save_state(job_id: str, payload: dict[str, Any]) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    result = dict(job.result or {})
    incoming = payload if isinstance(payload, dict) else {}
    keep = (
        "defaultStyle",
        "crop",
        "exportLw",
        "exportCg",
        "exportDsk",
        "hiddenLayers",
        "cachedCountries",
        "slides",
        "links",
    )
    merged = {key: result.get(key) for key in keep}
    for key in keep:
        if key in incoming:
            merged[key] = incoming[key]
    doc = _parse_document(merged)
    dumped = _dump_document(doc)
    dumped["links"] = coerce_link_kinds(dumped["slides"], dumped["links"])
    result.update(dumped)
    updated = _runner().update_result(job_id, result)
    if not updated:
        raise HTTPException(404, "Unknown maps job")
    return _runner().public_dict(updated)


@router.post("/{job_id}/png")
async def post_png(
    job_id: str,
    request: Request,
    slideId: str | None = Query(None),
    plateId: str | None = Query(None),
    kind: str = Query("thumb"),
    audience: Literal["lw", "cg"] = Query("lw"),
) -> dict:
    job = _job_or_404(job_id)
    _require_idle(job)
    result = dict(job.result or {})
    slides = list(result.get("slides") or [])
    ids = {str(slide.get("id")) for slide in slides}
    body = await request.body()
    if not body:
        raise HTTPException(400, "PNG body required")
    if kind not in {"thumb", "still", "plate"}:
        raise HTTPException(400, "kind must be thumb, still, or plate")
    output_dir = Path(str(result.get("outputDir") or ""))
    if kind == "plate":
        if not plateId:
            raise HTTPException(400, "plateId is required for kind=plate")
        safe_plate = _safe_name(plateId)
        folder = output_dir / "plates"
        folder.mkdir(parents=True, exist_ok=True)
        plate_name = safe_plate if audience != "cg" or safe_plate.endswith("-cg") else f"{safe_plate}-cg"
        path = folder / plate_filename(plate_name)
        path.write_bytes(body)
        return _runner().public_dict(job)
    if not slideId:
        raise HTTPException(400, "slideId is required")
    if slideId not in ids:
        raise HTTPException(400, "slideId is not in this deck")
    safe = _safe_name(slideId)
    if audience == "cg":
        safe = f"{Path(safe).stem}_CG{Path(safe).suffix}"
    if not safe.endswith(".png"):
        safe = f"{safe}.png"
    if kind == "still":
        folder = output_dir / "stills"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / Path(safe).name).write_bytes(body)
        return _runner().public_dict(job)
    folder = Path(str(result.get("previewDir") or ""))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(safe).name
    path.write_bytes(body)
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
    updated = _runner().update_result(job_id, result)
    if not updated:
        raise HTTPException(404, "Unknown maps job")
    return _runner().public_dict(updated)


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
    if index < 0:
        raise HTTPException(400, "index must be >= 0")
    if count < 1:
        raise HTTPException(400, "count must be >= 1")
    if not 1 <= fps <= 60:
        raise HTTPException(400, "fps must be between 1 and 60")
    body = await request.body()
    if not body:
        raise HTTPException(400, "Frame body required")
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
    result = job.result or {}
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

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from obed_edom.paths import output_root
from obed_edom.watercolour import MAX_ENCODED_BYTES, WatercolourError, WatercolourOptions, convert, decode_image, grabcut_mask

router = APIRouter(prefix="/api/watercolour", tags=["watercolour"])
MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 100 * 1024 * 1024


def _runner():
    from obed_edom.web.app import RUNNER

    return RUNNER


def _read_limited(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(min(1024 * 1024, MAX_ENCODED_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > MAX_ENCODED_BYTES:
            raise HTTPException(413, "Each photo must be 20 MB or smaller")
        chunks.append(chunk)


def _mask_for(image, spec: dict[str, Any] | None):
    if not spec or not spec.get("transparent"):
        return None
    rect = spec.get("rect")
    if rect is None and image.getchannel("A").getextrema()[0] < 255:
        return image.getchannel("A")
    if not isinstance(rect, list) or len(rect) != 4:
        raise WatercolourError("Transparent landmark output needs a foreground rectangle")
    foreground = spec.get("foreground") if isinstance(spec.get("foreground"), list) else []
    background = spec.get("background") if isinstance(spec.get("background"), list) else []
    return grabcut_mask(image, tuple(float(value) for value in rect), foreground=foreground, background=background)


def _run_batch(job, staged: list[tuple[str, Path]], options: WatercolourOptions, masks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = Path(str((job.result or {}).get("outputDir") or output_root() / ".watercolour" / job.id))
    originals, results = root / "originals", root / "results"
    originals.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    job.result = {"outputDir": str(root), "originalDir": str(originals), "resultDir": str(results), "items": rows}
    try:
      for index, (name, path) in enumerate(staged):
        if job.cancelled(): break
        stem = f"{index:02d}-{Path(name).stem or 'photo'}"; original_path = originals / f"{stem}.png"
        try:
            raw = path.read_bytes(); image = decode_image(raw)
            temp = original_path.with_suffix(".tmp"); image.save(temp, "PNG", optimize=False); temp.replace(original_path)
            spec = masks.get(str(index)) or masks.get(name)
            transparent = bool(spec and spec.get("transparent"))
            payload, size = convert(raw, WatercolourOptions(**{**options.__dict__, "transparent": transparent, "paper": not transparent}), _mask_for(image, spec))
            result_name = f"{stem}-watercolour.png"
            result_path = results / result_name; temp = result_path.with_suffix(".tmp"); temp.write_bytes(payload); temp.replace(result_path)
            rows.append({"id": uuid.uuid4().hex, "name": name, "original": original_path.name, "result": result_name, "width": size[0], "height": size[1], "transparent": transparent, "status": "done"})
        except (OSError, WatercolourError, ValueError, TypeError, cv2.error) as exc:
            rows.append({"id": uuid.uuid4().hex, "name": name, "status": "error", "error": str(exc)})
        finally:
            path.unlink(missing_ok=True)
    finally:
      for _name, path in staged: path.unlink(missing_ok=True)
      shutil.rmtree(staged[0][1].parent if staged else root / ".uploads", ignore_errors=True)
    return dict(job.result)


@router.post("")
async def start_watercolour(files: list[UploadFile] = File(...), wash_softness: float = Form(0.65), ink_amount: float = Form(0.42), masks: str = Form("{}")) -> dict:
    if not files or len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"Choose between one and {MAX_BATCH_FILES} photos")
    if len(masks.encode("utf-8")) > 256 * 1024:
        raise HTTPException(413, "Mask settings exceed the 256 KB limit")
    try:
        mask_specs = json.loads(masks)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Mask settings are invalid") from exc
    if not isinstance(mask_specs, dict):
        raise HTTPException(400, "Mask settings are invalid")
    if any(not isinstance(value, dict) for value in mask_specs.values()):
        raise HTTPException(400, "Mask settings are invalid")
    staged_root = output_root() / ".watercolour" / ".uploads" / uuid.uuid4().hex
    staged_root.mkdir(parents=True, exist_ok=False)
    staged: list[tuple[str, Path]] = []
    total = 0
    try:
        for index, upload in enumerate(files):
            payload = _read_limited(upload)
            total += len(payload)
            if total > MAX_BATCH_BYTES:
                raise HTTPException(413, "This batch exceeds the 100 MB upload limit")
            path = staged_root / f"{index:02d}.upload"
            path.write_bytes(payload)
            staged.append((Path(upload.filename or f"photo-{index + 1}").name, path))
    except Exception:
        shutil.rmtree(staged_root, ignore_errors=True)
        raise
    finally:
        for upload in files:
            await upload.close()
    options = WatercolourOptions(wash_softness=wash_softness, ink_amount=ink_amount)
    job = _runner().submit("watercolour", lambda job: _run_batch(job, staged, options, mask_specs), feature="watercolour")
    return _runner().public_dict(job)


@router.post("/{job_id}/cancel")
def cancel_watercolour(job_id: str) -> dict:
    job = _runner().get(job_id)
    if not job or job.feature != "watercolour":
        raise HTTPException(404, "Unknown Watercolour job")
    cancelled = _runner().cancel(job_id)
    return _runner().public_dict(cancelled)


@router.post("/{job_id}/items/{item_id}/add-to-map/{maps_job_id}/{slide_id}")
def add_to_map(job_id: str, item_id: str, maps_job_id: str, slide_id: str) -> dict:
    source_job = _runner().get(job_id)
    if not source_job or source_job.feature != "watercolour":
        raise HTTPException(404, "Unknown Watercolour job")
    item = next((row for row in (source_job.result or {}).get("items") or [] if row.get("id") == item_id), None)
    if not item or item.get("status") != "done" or item.get("transparent") is not True:
        raise HTTPException(400, "Only completed transparent Watercolour results can be added to a map")
    name = str(item.get("name") or "Landmark").rsplit(".", 1)[0]
    source = _result_file(job_id, item_id, "result")
    from obed_edom.web import maps
    payload, width, height, version = maps._decode_png(source.read_bytes())
    asset_id = uuid.uuid4().hex
    def append(result: dict[str, Any]) -> dict[str, Any]:
        slide = next((row for row in result.get("slides") or [] if row.get("id") == slide_id), None)
        if not slide: raise HTTPException(404, "Unknown Maps slide")
        path = maps._asset_path(result, asset_id)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(payload)
        temp.replace(path)
        churches = list(slide.get("churches") or []); used = {str(church.get("id") or "") for church in churches}; n = 1
        while f"p{n}" in used: n += 1
        camera = slide.get("camera") or {}
        churches.append({"id": f"p{n}", "name": name, "lat": float(camera.get("lat") or 0), "lon": float(camera.get("lon") or 0), "kind": "landmark", "color": "#c44a42", "showLabel": True, "assetId": asset_id, "assetVersion": version, "assetWidth": width, "assetHeight": height, "size": 180, "opacity": 1})
        slide["churches"] = churches; result["assets"] = [*(result.get("assets") or []), {"id": asset_id, "version": version, "width": width, "height": height}]; return result
    return maps._mutate_document(maps_job_id, None, append)


def _result_file(job_id: str, item_id: str, key: str) -> Path:
    job = _runner().get(job_id)
    if not job or job.feature != "watercolour":
        raise HTTPException(404, "Unknown Watercolour job")
    row = next((item for item in (job.result or {}).get("items", []) if item.get("id") == item_id), None)
    if not row or not row.get(key):
        raise HTTPException(404, "Watercolour image is unavailable")
    path = Path(str((job.result or {}).get("originalDir" if key == "original" else "resultDir") or "")) / str(row[key])
    if not path.is_file():
        raise HTTPException(404, "Watercolour image is unavailable")
    return path


@router.get("/{job_id}/items/{item_id}/original")
def watercolour_original(job_id: str, item_id: str):
    return FileResponse(_result_file(job_id, item_id, "original"), media_type="image/png")


@router.get("/{job_id}/items/{item_id}/result")
def watercolour_result(job_id: str, item_id: str):
    return FileResponse(_result_file(job_id, item_id, "result"), media_type="image/png", filename="watercolour.png")


@router.get("/{job_id}/download")
def watercolour_download(job_id: str):
    job = _runner().get(job_id)
    if not job or job.feature != "watercolour":
        raise HTTPException(404, "Unknown Watercolour job")
    result = job.result or {}
    rows = [row for row in result.get("items", []) if row.get("status") == "done" and row.get("result")]
    if not rows:
        raise HTTPException(404, "No Watercolour results are available")
    root = Path(str(result.get("outputDir") or ""))
    archive_path = root / "watercolour-results.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            path = _result_file(job_id, str(row["id"]), "result")
            archive.write(path, str(row["result"]))
    return FileResponse(archive_path, media_type="application/zip", filename="watercolour-results.zip")

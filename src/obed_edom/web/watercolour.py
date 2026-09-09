from __future__ import annotations

import base64
import binascii
import io
import json
import math
import shutil
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image

from obed_edom.paths import output_root
from obed_edom.watercolour import MAX_ENCODED_BYTES, WatercolourError, WatercolourOptions, convert, decode_image, grabcut_mask, render

router = APIRouter(prefix="/api/watercolour", tags=["watercolour"])
MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 100 * 1024 * 1024
PREVIEW_MAX_SIDE = 360
SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "watercolour-sample.jpg"


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


MASK_FIELD_MAX_BYTES = 1024 * 1024
MASK_FIELD_MAX_PIXELS = 4 * 1024 * 1024


def _decode_mask_field(spec: dict[str, Any], key: str) -> Image.Image | None:
    value = spec.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WatercolourError("Mask settings are invalid")
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WatercolourError("Mask settings are invalid") from exc
    if len(payload) > MASK_FIELD_MAX_BYTES:
        raise WatercolourError("Mask settings are invalid")
    try:
        buffer = io.BytesIO(payload)
        probe = Image.open(buffer)
        probe.verify()
        buffer.seek(0)
        mask = Image.open(buffer)
        mask.load()
    except Exception as exc:
        raise WatercolourError("Mask settings are invalid") from exc
    if mask.width * mask.height > MASK_FIELD_MAX_PIXELS:
        raise WatercolourError("Mask settings are invalid")
    return mask.convert("L")


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
    keep_mask = _decode_mask_field(spec, "keepMask")
    remove_mask = _decode_mask_field(spec, "removeMask")
    return grabcut_mask(
        image,
        tuple(float(value) for value in rect),
        foreground=foreground,
        background=background,
        keep_mask=keep_mask,
        remove_mask=remove_mask,
    )


def _scale_spec(spec: dict[str, Any] | None, factor: float, size: tuple[int, int]) -> dict[str, Any] | None:
    if not spec or not spec.get("transparent"):
        return None
    width, height = size

    def scale_point(point: Any) -> list[float]:
        if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point):
            raise WatercolourError("Mask settings are invalid")
        x, y = point
        return [min(max(round(x * factor), 0), width - 1), min(max(round(y * factor), 0), height - 1)]

    scaled: dict[str, Any] = {
        "transparent": True,
        "foreground": [scale_point(point) for point in (spec.get("foreground") or [])],
        "background": [scale_point(point) for point in (spec.get("background") or [])],
    }
    if spec.get("keepMask") is not None:
        scaled["keepMask"] = spec.get("keepMask")
    if spec.get("removeMask") is not None:
        scaled["removeMask"] = spec.get("removeMask")
    if spec.get("maskSize") is not None:
        scaled["maskSize"] = spec.get("maskSize")
    rect = spec.get("rect")
    if rect is not None:
        if not isinstance(rect, list) or len(rect) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect):
            raise WatercolourError("Mask settings are invalid")
        x, y, w, h = rect
        sx = min(max(round(x * factor), 0), width - 2)
        sy = min(max(round(y * factor), 0), height - 2)
        scaled["rect"] = [sx, sy, min(max(2, round(w * factor)), width - sx), min(max(2, round(h * factor)), height - sy)]
    return scaled


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
    if len(masks.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPException(413, "Mask settings exceed the 2 MB limit")
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


@lru_cache(maxsize=1)
def _sample() -> Image.Image:
    return decode_image(SAMPLE_PATH.read_bytes())


def _preview(image: Image.Image, wash_softness: float, ink_amount: float, spec: dict[str, Any] | None = None) -> Response:
    if not 0 <= wash_softness <= 1 or not 0 <= ink_amount <= 1:
        raise HTTPException(400, "Watercolour controls must be between zero and one")
    preview = image.copy()
    preview.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.LANCZOS)
    factor = preview.width / image.width
    try:
        mask = _mask_for(preview, _scale_spec(spec, factor, preview.size))
    except (WatercolourError, cv2.error) as exc:
        raise HTTPException(400, str(exc)) from exc
    transparent = mask is not None or bool(spec and spec.get("transparent"))
    output = io.BytesIO()
    options = WatercolourOptions(wash_softness=wash_softness, ink_amount=ink_amount, transparent=transparent, paper=not transparent)
    render(preview, options, mask).save(output, "PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/preview")
def watercolour_preview(wash_softness: float = 0.65, ink_amount: float = 0.42) -> Response:
    return _preview(_sample(), wash_softness, ink_amount)


@router.post("/preview")
async def watercolour_preview_upload(
    file: UploadFile = File(...), wash_softness: float = Form(0.65), ink_amount: float = Form(0.42), mask: str = Form("{}")
) -> Response:
    try:
        raw = _read_limited(file)
    finally:
        await file.close()
    try:
        image = decode_image(raw)
    except WatercolourError as exc:
        raise HTTPException(400, str(exc)) from exc
    if len(mask.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPException(413, "Mask settings exceed the 2 MB limit")
    try:
        spec = json.loads(mask)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Mask settings are invalid") from exc
    if not isinstance(spec, dict):
        raise HTTPException(400, "Mask settings are invalid")
    return _preview(image, wash_softness, ink_amount, spec)


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

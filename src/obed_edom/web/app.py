from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, StrictInt
from obed_edom.baseline import (
    deck_digest,
    deck_slide_digests,
    delete_pairing,
    load_pairing,
    reuse_slots,
    save_pairing,
    slot_dict,
    wall_thumb_dir,
)
from obed_edom.diagnostics import DiagnosticsWriter
from obed_edom.diff_keynotes import (
    record_flag,
    compare_inspects,
    realign_gaps,
    slide_catalog,
    slots_from_pairs,
)
from obed_edom.dsk_assemble import (
    DEFAULT_DSK_LAYOUT_NAMES,
    DEFAULT_TEXT_SLIDE_WORDS,
    AssemblyRefusal,
    SlideDecision,
    assemble_dsk_deck,
    check_layout_import_preconditions,
)
from obed_edom.dsk_live import (
    DEFAULT_TRANSPARENT_LAYOUT_NAMES,
    guard_out_dir,
    keynote_running,
    owned_alpha_safe_layout,
    quit_and_wait_for_exit,
)
from obed_edom.dsk_movie_export import (
    _ffprobe,
    export_dsk_slide_clips,
    export_slide_clips,
    movie_crop_plans_from_compiled,
    movies_stacked,
    visible_movie_rects,
)
from obed_edom.dsk_plan import Band, ItemId, classify_deck, fit_slide
from obed_edom.dsk_review import (
    ReviewValidationError,
    apply_editable_review,
    build_review,
    compile_review,
)
from obed_edom.iwa_builds import deck_builds
from obed_edom.iwa_geometry import compose_deck_geometry
from obed_edom.map_remap import CENTRE_PANEL_RECT, LW_WALL_SIZE, Rect, item_rect
from obed_edom.dsk_stage_export import (
    export_stage_pngs,
    read_manifest,
    stage_counts,
    write_manifest,
)
from obed_edom.html_preview import (
    PreviewError,
    apply_preview,
    cleanup_preview,
    inject_player_diagnostics,
    propose_preview,
    registered_export_root,
    safe_export_file,
)
from obed_edom.framing import (
    AUTO,
    DEFERRED,
    PINNED,
    Decision,
    FramingReuse,
    build_preview_thumbs,
    load_framings,
    normalize_decision,
    propose_framings,
    reuse_framings,
    save_framings,
    template_framing_digests,
)
from obed_edom.inspect import (
    complete_cached_wall_payload,
    diff_work_dir,
    inspect_keynote,
    inspect_keynote_checker,
    preview_media_type,
    preview_pngs,
)
from obed_edom.map_remap import (
    expand_slide_range,
    format_slide_range,
    is_lw_wall,
    navigator_numbering,
    resolve_slides,
    to_document_range,
)
from obed_edom.models import Flag
from obed_edom.offline_inspect import offline_wall_payload
from obed_edom.offline_write import OfflineHidesAborted
from obed_edom.outline_check import (
    SemanticOutlineError,
    correspondence,
    corroborate,
    load_playlist,
    outline_report,
    rows_for_slots,
    slots_from_cues,
)
from obed_edom.outline_check import visible as visible_slides
from obed_edom.paths import (
    ensure_export_dir,
    export_destination,
    find_repo_root,
    output_root,
    resolve_export_destination,
    validate_export_dir,
)
from obed_edom.resolve_drop import resolve_dropped_keynote
from obed_edom.pipeline import generate
from obed_edom.remap_keynote import (
    acquire_wall_payload,
    offline_read_mode,
    remap_and_inspect,
)
from obed_edom.settings import load_settings, save_settings
from obed_edom.validate import validate_inspect
from obed_edom.web.jobs import (
    Job,
    JobRunner,
    default_output_root,
    preview_names,
    serialize_flags,
)

RUNNER = JobRunner()
ROOT = find_repo_root()
UPLOADS = default_output_root() / ".uploads"
DASHBOARD_DIST = ROOT / "dashboard" / "dist"


class JobPatch(BaseModel):
    result: dict[str, Any]


class RenameBody(BaseModel):
    name: str


class RelocateBody(BaseModel):
    folder: str | None = None
    path: str | None = None
    leftPath: str | None = None
    rightPath: str | None = None
    destPath: str | None = None
    destPathCg: str | None = None
    destPathDsk: str | None = None


class DiffSlotsBody(BaseModel):
    slots: list[dict[str, Any]] | None = None
    pairs: list[dict[str, Any]] | None = None


class FramingsBody(BaseModel):
    """`{wallIndex, state, templateSlide}` per answered page. A group confirm is several entries."""

    decisions: list[dict[str, Any]] | None = None
    exportDir: str | None = None
    offlineHides: str | None = None


class DskDecisionsBody(BaseModel):
    """`{slide, include, action, anchor, keepSide, clip, videosOnly}` per proposed page."""

    decisions: list[dict[str, Any]] | None = None
    exportDir: str | None = None
    # Version 2 writes a deliberately narrow editable envelope.  The proposal's
    # source/media/capability metadata remains server-authoritative.
    review: dict[str, Any] | None = None
    baseRevision: StrictInt | None = None
    dskTemplate: str | None = None


class SettingsBody(BaseModel):
    reuseThreshold: float | None = None
    reusePairings: bool | None = None
    reusePreviews: bool | None = None
    defaultExportDir: str | None = None
    highlightColour: str | None = None
    lwTemplate: str | None = None
    dskTemplate: str | None = None


OPENABLE_SUFFIXES = {".key", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".mov", ".mp4"}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _require_local_origin(request: Request) -> None:
    """Reject cross-origin calls to filesystem-touching endpoints; same-origin/no-origin requests pass."""
    origin = request.headers.get("origin")
    if not origin:
        return
    host = urlsplit(origin).hostname
    if host not in _LOCAL_HOSTS:
        raise HTTPException(403, "Forbidden origin")


class SpaStaticFiles(StaticFiles):
    """HTML must revalidate, or a browser keeps serving an index that names deleted hashed assets."""

    def file_response(self, full_path, stat_result, scope, status_code: int = 200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="Obed-Edom dashboard")
    from obed_edom.web.live import live_router

    app.include_router(live_router(RUNNER))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return load_settings()

    @app.put("/api/settings")
    def put_settings(payload: SettingsBody) -> dict:
        current = load_settings()
        if payload.reuseThreshold is not None:
            current["reuseThreshold"] = payload.reuseThreshold
        if payload.reusePairings is not None:
            current["reusePairings"] = payload.reusePairings
        if payload.reusePreviews is not None:
            current["reusePreviews"] = payload.reusePreviews
        if payload.defaultExportDir is not None:
            current["defaultExportDir"] = payload.defaultExportDir
        if payload.highlightColour is not None:
            current["highlightColour"] = payload.highlightColour
        if payload.lwTemplate is not None:
            current["lwTemplate"] = payload.lwTemplate
        if payload.dskTemplate is not None:
            current["dskTemplate"] = payload.dskTemplate
        try:
            return save_settings(current, validate_dir=payload.defaultExportDir is not None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/choose-file")
    def choose_file(prompt: str = Form("Select a Keynote file")) -> dict:
        script = _picker_script(f'choose file with prompt "{_as_escape(prompt)}"')
        proc = subprocess.run(
            ["osascript", "-"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise HTTPException(400, (proc.stderr or proc.stdout or "Cancelled").strip())
        path = (proc.stdout or "").strip()
        if not path:
            raise HTTPException(400, "No file selected")
        return {"path": path, "name": Path(path).name}

    @app.post("/api/choose-folder")
    def choose_folder(
        prompt: str = Form("Select the output folder"),
        default_location: str = Form(""),
    ) -> dict:
        folder = ""
        loc = default_location.strip()
        if loc:
            candidate = Path(loc).expanduser()
            if candidate.is_dir() and candidate.is_absolute():
                folder = str(candidate)
        script = _picker_script(f'choose folder with prompt "{_as_escape(prompt)}"', folder)
        proc = subprocess.run(
            ["osascript", "-"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise HTTPException(400, (proc.stderr or proc.stdout or "Cancelled").strip())
        path = (proc.stdout or "").strip().rstrip("/")
        if not path:
            raise HTTPException(400, "No folder selected")
        return {"path": path, "name": Path(path).name}

    @app.post("/api/choose-save")
    def choose_save(
        prompt: str = Form("Export Keynote"),
        default_name: str = Form("untitled.key"),
        default_location: str = Form(""),
    ) -> dict:
        loc = default_location.strip()
        if loc:
            candidate = Path(loc).expanduser()
            if not candidate.is_dir():
                loc = ""
        script = _choose_save_script(prompt, default_name, loc)
        proc = subprocess.run(
            ["osascript", "-"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "Cancelled").strip()
            if "cancel" in msg.lower():
                return {"cancelled": True}
            raise HTTPException(400, msg)
        path = (proc.stdout or "").strip()
        if not path:
            raise HTTPException(400, "No file selected")
        return {"path": path, "name": Path(path).name, "cancelled": False}

    @app.post("/api/resolve-drop")
    def resolve_drop(name: str = Form(...), size: int | None = Form(None)) -> dict:
        found = resolve_dropped_keynote(name, size)
        if not found:
            raise HTTPException(
                404,
                "Could not resolve that drop to a path on this Mac. Use Choose on this Mac.",
            )
        return {"path": str(found), "name": found.name}

    @app.post("/api/reveal", dependencies=[Depends(_require_local_origin)])
    def reveal(path: str = Form(...)) -> dict:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(404, f"Not found: {path}")
        subprocess.run(["open", "-R", str(target)], check=False)
        return {"ok": True}

    @app.post("/api/open", dependencies=[Depends(_require_local_origin)])
    def open_path(path: str = Form(...)) -> dict:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(404, f"Not found: {path}")
        suffix = target.suffix.lower()
        if suffix not in OPENABLE_SUFFIXES or (target.is_dir() and suffix != ".key"):
            raise HTTPException(400, f"Not an openable artifact: {path}")
        subprocess.run(["open", str(target)], check=False)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs(kind: str | None = None, feature: str | None = None) -> dict:
        return {"jobs": [RUNNER.public_dict(j) for j in RUNNER.list(kind, feature)]}

    @app.delete("/api/jobs")
    def delete_all_jobs() -> dict:
        return {"ok": True, "deleted": RUNNER.delete_all(purge=True)}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(job)

    @app.patch("/api/jobs/{job_id}")
    def patch_job(job_id: str, payload: JobPatch) -> dict:
        existing = RUNNER.get(job_id)
        if not existing:
            raise HTTPException(404, "Unknown job")
        if existing.feature == "maps":
            raise HTTPException(409, "Maps jobs use POST /api/maps/{id}/state")
        if existing.feature == "watercolour":
            raise HTTPException(400, "Watercolour jobs cannot be patched directly")
        if existing.kind == "html-preview" or existing.feature == "html-preview":
            raise HTTPException(409, "HTML preview jobs cannot be patched directly")
        job = RUNNER.update_result(job_id, payload.result)
        if not job:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(job)

    @app.patch("/api/jobs/{job_id}/name")
    def rename_job(job_id: str, payload: RenameBody) -> dict:
        existing = RUNNER.get(job_id)
        if not existing:
            raise HTTPException(404, "Unknown job")
        try:
            if existing.feature == "maps":
                from obed_edom.web.maps import rename_job_folder  # noqa: PLC0415

                job = rename_job_folder(job_id, payload.name)
            else:
                job = RUNNER.rename(job_id, payload.name)
        except KeyError:
            raise HTTPException(404, "Unknown job") from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (RuntimeError, FileExistsError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return RUNNER.public_dict(job)

    @app.post("/api/jobs/{job_id}/relocate")
    def relocate_job(job_id: str, payload: RelocateBody) -> dict:
        existing = RUNNER.get(job_id)
        if existing and existing.feature == "maps":
            raise HTTPException(409, "Maps jobs use POST /api/maps/{id}/state")
        try:
            job = RUNNER.relocate(
                job_id,
                folder=payload.folder,
                path=payload.path,
                left_path=payload.leftPath,
                right_path=payload.rightPath,
                dest_path=payload.destPath,
                dest_path_cg=payload.destPathCg,
                dest_path_dsk=payload.destPathDsk,
            )
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not job:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(job)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict:
        if not RUNNER.delete(job_id, purge=True):
            raise HTTPException(404, "Unknown job")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/previews/{deck}/{filename}")
    def job_preview(job_id: str, deck: str, filename: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "No previews")
        previews = (job.result or {}).get("previews") or {}
        folder = previews.get(deck) or job.result.get("previewDir")
        if not folder:
            raise HTTPException(404, "No previews")
        path = _safe_file(Path(folder), filename)
        return FileResponse(path, media_type=preview_media_type(path))

    @app.get("/api/jobs/{job_id}/evidence/{filename}")
    def job_evidence(job_id: str, filename: str):
        job = RUNNER.get(job_id)
        folder = (job.result or {}).get("evidenceDir") if job else None
        if not folder:
            raise HTTPException(404, "No evidence")
        path = _safe_file(Path(folder), filename)
        return FileResponse(path, media_type=preview_media_type(path))

    @app.get("/api/jobs/{job_id}/diagnostics")
    def job_diagnostics(job_id: str):
        job = RUNNER.get(job_id)
        path = _trusted_diagnostics_path(job, job_id)
        if not job or path is None:
            raise HTTPException(404, "No diagnostics")
        date = time.strftime("%Y-%m-%d", time.localtime(job.created_at))
        return FileResponse(
            path,
            media_type="application/x-ndjson",
            filename=f"sermon-diagnostics-{date}-{job_id}.jsonl",
        )

    @app.post("/api/jobs/{job_id}/diagnostics/reveal")
    def job_diagnostics_reveal(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        path = _trusted_diagnostics_path(job, job_id)
        if not job or path is None:
            raise HTTPException(404, "No diagnostics")
        try:
            subprocess.run(["open", "-R", str(path)], check=False)
        except OSError:
            raise HTTPException(500, "Could not reveal the file")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/file/{kind}")
    def job_file(job_id: str, kind: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "No result")
        mapping = {
            "lw": job.result.get("lwKey"),
            "dsk": job.result.get("dskKey"),
            "cued": job.result.get("cuedDocx"),
            "review": job.result.get("reviewPath"),
        }
        path = mapping.get(kind)
        if not path:
            raise HTTPException(404, "File not available")
        return FileResponse(path)

    @app.post("/api/generate")
    async def generate_endpoint(
        files: list[UploadFile] = File(...),
        lw_template: str = Form(""),
        dsk_template: str = Form(""),
        export_dir: str = Form(""),
    ) -> dict:
        lw_path = Path(lw_template.strip()).expanduser() if lw_template.strip() else None
        dsk_path = Path(dsk_template.strip()).expanduser() if dsk_template.strip() else None
        seed_result: dict[str, Any] = {}
        if export_dir.strip():
            try:
                seed_result["exportDir"] = str(validate_export_dir(export_dir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if lw_path is None and dsk_path is None:
            raise HTTPException(400, "At least one Keynote template is required (LW, DSK, or both).")
        if lw_path is not None and not lw_path.exists():
            raise HTTPException(400, f"LW template not found: {lw_template}")
        if dsk_path is not None and not dsk_path.exists():
            raise HTTPException(400, f"DSK template not found: {dsk_template}")
        saved: list[Path] = []
        batch = UPLOADS / str(uuid4())[:8]
        batch.mkdir(parents=True, exist_ok=True)
        for upload in files:
            name = Path(upload.filename or "outline.docx").name
            if not name.lower().endswith(".docx"):
                raise HTTPException(400, f"Expected .docx, got {name}")
            dest = batch / name
            dest.write_bytes(await upload.read())
            saved.append(dest)
        jobs = []
        for path in saved:
            job = RUNNER.submit(
                "generate",
                lambda j, p=path, lw=lw_path, dsk=dsk_path: _run_generate(j, p, lw, dsk),
                feature="generate",
                result=dict(seed_result) if seed_result else None,
            )
            jobs.append(job.to_dict())
        return {"jobs": jobs}

    def _outline_arg(raw: str) -> Path | None:
        if not (raw or "").strip():
            return None
        outline = Path(raw.strip()).expanduser()
        if not outline.exists():
            raise HTTPException(400, f"Outline not found: {raw}")
        suffix = outline.suffix.lower()
        if suffix not in {".docx", ".pdf"}:
            raise HTTPException(400, f"Expected a .docx or .pdf outline, got {outline.name}")
        try:
            load_playlist(outline)
        except SemanticOutlineError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Could not read {outline.name}: {exc}") from exc
        return outline

    @app.post("/api/diff")
    def diff_endpoint(
        left_path: str = Form(...),
        right_path: str = Form(...),
        left_label: str = Form("LW"),
        right_label: str = Form("Other"),
        outline_path: str = Form(""),
        lw_final: str = Form("true"),
        fresh: str = Form("false"),
    ) -> dict:
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        if not left.exists() or not right.exists():
            raise HTTPException(400, "Both Keynote paths must exist")
        outline = _outline_arg(outline_path)
        start_fresh = _form_flag(fresh)
        final = _form_flag(lw_final)
        job = RUNNER.submit(
            "diff",
            lambda j, a=left, b=right, la=left_label, lb=right_label, fr=start_fresh, o=outline, fin=final: (
                _run_diff(j, a, b, la, lb, fresh=fr, outline=o, lw_final=fin)
            ),
            feature="check",
        )
        return job.to_dict()

    @app.post("/api/outline")
    def outline_endpoint(path: str = Form(...), export_dir: str = Form("")) -> dict:
        outline = _outline_arg(path)
        if outline is None:
            raise HTTPException(400, "An outline .docx or .pdf is required.")
        seed_result: dict[str, Any] = {}
        if export_dir.strip():
            try:
                seed_result["exportDir"] = str(validate_export_dir(export_dir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        job = RUNNER.submit(
            "outline",
            lambda j, p=outline: _run_outline(j, p),
            feature="check",
            result=dict(seed_result) if seed_result else None,
        )
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/outline.pdf")
    def outline_pdf(job_id: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "No result")
        path = (job.result or {}).get("outlineReport")
        if not path or not Path(path).is_file():
            raise HTTPException(404, "No outline report")
        return FileResponse(path, media_type="application/pdf", filename=Path(path).name)

    @app.post("/api/diff/{job_id}/slots")
    def save_diff_slots(job_id: str, payload: DiffSlotsBody) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        pairs = payload.pairs or result.get("pairs") or []
        if payload.slots is not None:
            result["slots"] = payload.slots
            pairs = _pairs_from_catalog(result, payload.slots)
        else:
            result["slots"] = [
                {
                    "leftIndex": p.get("leftIndex"),
                    "rightIndex": p.get("rightIndex"),
                    "rightIndexes": p.get("rightIndexes")
                    if p.get("rightIndexes") is not None
                    else ([p["rightIndex"]] if p.get("rightIndex") is not None else []),
                }
                for p in pairs
            ]
        result["pairs"] = pairs
        result["phase"] = "match"
        _remember_pairing(job, result, source="operator", force=True)
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result

    @app.post("/api/diff/{job_id}/check")
    def start_diff_check(job_id: str, payload: DiffSlotsBody = Body(default=DiffSlotsBody())) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if payload and (payload.slots is not None or payload.pairs is not None):
            save_diff_slots(job_id, payload)
        try:
            updated = RUNNER.rerun(job_id, _run_diff_check)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(updated)

    @app.get("/api/diff/{job_id}/image/{side}/{filename}")
    def diff_image(job_id: str, side: str, filename: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "No diff")
        folders = {
            "left": job.result["leftPreviews"],
            "right": job.result["rightPreviews"],
            "heat": job.result["heatDir"],
        }
        folder = folders.get(side)
        if not folder:
            raise HTTPException(404, "Unknown side")
        path = _safe_file(Path(folder), filename)
        return FileResponse(path, media_type=preview_media_type(path))

    @app.post("/api/validate-keynote")
    def validate_keynote(
        path: str = Form(...),
        export: str = Form("false"),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        slides: str = Form(""),
        feature: str = Form("inspect"),
        outline_path: str = Form(""),
        lw_final: str = Form("true"),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        tag = (
            feature
            if feature in {"dsk", "dsk-export", "resize", "inspect", "dsk-aux", "check"}
            else "inspect"
        )
        outline = _outline_arg(outline_path)
        final = _form_flag(lw_final)
        try:
            sel = resolve_slides(spec=slides or None, range_from=range_from, range_to=range_to)
        except ValueError as err:
            raise HTTPException(400, str(err))
        job = RUNNER.submit(
            "inspect",
            lambda j, p=key, ex=do_export, sl=sel, o=outline, fin=final: _run_inspect(
                j, p, ex, sl, outline=o, lw_final=fin
            ),
            feature=tag,
        )
        return job.to_dict()

    @app.post("/api/dsk")
    def start_dsk(
        path: str = Form(...),
        reference_deck: str = Form(""),
        dsk_template: str = Form(""),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        slides: str = Form(""),
        content_only: str = Form("true"),
        text_slide_words: str = Form(""),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        raw_reference = reference_deck.strip()
        reference = Path(raw_reference).expanduser() if raw_reference else None
        if reference is not None and not reference.exists():
            raise HTTPException(400, f"Reference deck not found: {raw_reference}")
        try:
            sel = resolve_slides(spec=slides or None, range_from=range_from, range_to=range_to)
        except ValueError as err:
            raise HTTPException(400, str(err))
        words: int | None = None
        if text_slide_words.strip():
            try:
                words = int(text_slide_words)
            except ValueError:
                raise HTTPException(400, f"Bad text_slide_words: {text_slide_words!r}")
        do_content_only = _form_flag(content_only)
        template_path = _resolve_dsk_layout_donor(dsk_template, key, reference, content_only=do_content_only)
        job = RUNNER.submit(
            "dsk",
            lambda j, p=key, r=reference, t=template_path, sl=sel, co=do_content_only, w=words: (
                _run_dsk_propose(j, p, r, t, sl, co, w)
            ),
            feature="dsk",
        )
        return job.to_dict()

    @app.get("/api/dsk/{job_id}/thumb/{filename}")
    def dsk_thumb(job_id: str, filename: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        raw = str((job.result or {}).get("thumbDir") or "")
        if not raw:
            raise HTTPException(404, "Job has no thumbnails")
        path = _safe_file(Path(raw), filename)
        return FileResponse(path, media_type=preview_media_type(path))

    @app.post("/api/dsk/{job_id}/decisions")
    def save_dsk_decisions(job_id: str, payload: DskDecisionsBody) -> dict:
        if payload.review is not None or payload.baseRevision is not None:
            return _save_v2_dsk_review(job_id, payload)
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        _apply_dsk_decisions(result, payload.decisions)
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result

    @app.post("/api/dsk/{job_id}/apply")
    def apply_dsk(job_id: str, payload: DskDecisionsBody = Body(default=DskDecisionsBody())) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if payload.review is not None or payload.baseRevision is not None:
            with RUNNER.job_lock(job_id):
                current = RUNNER.get(job_id)
                result = dict((current.result if current else None) or {})
                key = Path(str(result.get("path") or "")).expanduser()
                if not key.exists():
                    raise HTTPException(400, "The FW deck has moved since proposing.")
                if keynote_running():
                    raise HTTPException(409, "Close Keynote before running a DSK job (strictly serial).")
                if (payload.dskTemplate or "").strip():
                    _validate_dsk_template(payload.dskTemplate, key, content_only=bool(result.get("contentOnly")))
                _save_v2_dsk_review(job_id, payload)
                fresh = RUNNER.get(job_id)
                result = dict((fresh.result if fresh else None) or {})
                result, _ = _resolve_apply_dsk_template(job_id, result, payload.dskTemplate)
                try:
                    updated = RUNNER.rerun(job_id, lambda j, r=result: _run_dsk_apply(j, r))
                except RuntimeError as exc:
                    raise HTTPException(409, str(exc)) from exc
                if not updated:
                    raise HTTPException(404, "Unknown job")
                return RUNNER.public_dict(updated)
        if payload and payload.decisions is not None:
            save_dsk_decisions(job_id, payload)
        job = RUNNER.get(job_id)
        result = dict((job.result if job else None) or {})
        if payload and payload.exportDir is not None and payload.exportDir.strip():
            try:
                result["exportDir"] = str(validate_export_dir(payload.exportDir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            seeded = RUNNER.update_result(job_id, result)
            if seeded:
                result = dict(seeded.result or result)
        result, _ = _resolve_apply_dsk_template(job_id, result, payload.dskTemplate if payload else None)
        key = Path(str(result.get("path") or "")).expanduser()
        if not key.exists():
            raise HTTPException(400, "The FW deck has moved since proposing.")
        if keynote_running():
            raise HTTPException(409, "Close Keynote before running a DSK job (strictly serial).")
        try:
            updated = RUNNER.rerun(job_id, lambda j, r=result: _run_dsk_apply(j, r))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(updated)

    @app.post("/api/dsk/export")
    def start_dsk_export(
        path: str = Form(...),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        slides: str = Form(""),
        export_dir: str = Form(""),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        try:
            sel = resolve_slides(spec=slides or None, range_from=range_from, range_to=range_to)
        except ValueError as err:
            raise HTTPException(400, str(err))
        resolved_export_dir = ""
        if export_dir.strip():
            try:
                resolved_export_dir = str(validate_export_dir(export_dir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        job = RUNNER.submit(
            "dsk-export",
            lambda j, p=key, sl=sel, ed=resolved_export_dir: _run_dsk_export_propose(j, p, sl, ed),
            feature="dsk-export",
        )
        return job.to_dict()

    @app.post("/api/dsk/export/{job_id}/decisions")
    def save_dsk_export_decisions(job_id: str, payload: DskDecisionsBody) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        _apply_dsk_decisions(result, payload.decisions)
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result

    @app.post("/api/dsk/export/{job_id}/apply")
    def apply_dsk_export(
        job_id: str, payload: DskDecisionsBody = Body(default=DskDecisionsBody())
    ) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if payload and payload.decisions is not None:
            save_dsk_export_decisions(job_id, payload)
        job = RUNNER.get(job_id)
        result = dict((job.result if job else None) or {})
        key = Path(str(result.get("path") or "")).expanduser()
        if not key.exists():
            raise HTTPException(400, "The DSK deck has moved since proposing.")
        if keynote_running():
            raise HTTPException(409, "Close Keynote before running a DSK job (strictly serial).")
        try:
            updated = RUNNER.rerun(job_id, lambda j, r=result: _run_dsk_export_apply(j, r))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(updated)

    @app.post("/api/html-preview")
    def start_html_preview(
        path: str = Form(...),
        expected_digest: str = Form(""),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        expected = expected_digest.strip() or None
        job = RUNNER.submit(
            "html-preview",
            lambda j, p=key, d=expected: _run_html_preview_propose(j, p, d),
            feature="html-preview",
        )
        return job.to_dict()

    @app.post("/api/html-preview/{job_id}/apply")
    def apply_html_preview(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.kind != "html-preview":
            raise HTTPException(404, "Unknown job")
        result = dict(job.result)
        key = Path(str(result.get("path") or "")).expanduser()
        if not key.exists():
            raise HTTPException(400, "The deck has moved since proposing the preview.")
        if keynote_running():
            raise HTTPException(409, "Close Keynote before exporting a build preview (strictly serial).")
        try:
            updated = RUNNER.rerun(job_id, lambda j, r=result: _run_html_preview_apply(j, r))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(updated)

    @app.post("/api/html-preview/{job_id}/cleanup")
    def cleanup_html_preview(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        if not job or job.kind != "html-preview":
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        try:
            info = cleanup_preview(job.id, job.result or {})
        except PreviewError as exc:
            raise HTTPException(400, str(exc)) from exc
        result = dict(job.result or {})
        result.update(
            {
                "phase": "cleaned",
                "exportRoot": None,
                "manifest": None,
                "needsExport": True,
                "reused": False,
                "bytes": 0,
            }
        )
        updated = RUNNER.update_result(job_id, result)
        payload = RUNNER.public_dict(updated) if updated else result
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["cleanup"] = info
        return payload

    @app.get("/api/html-preview/{job_id}/player")
    @app.get("/api/html-preview/{job_id}/player/{rel_path:path}")
    def html_preview_player(job_id: str, rel_path: str = ""):
        job = RUNNER.get(job_id)
        if not job or job.kind != "html-preview" or not job.result:
            raise HTTPException(404, "Unknown job")
        if str((job.result or {}).get("phase") or "") != "ready":
            raise HTTPException(409, "Build preview is not ready")
        try:
            root = registered_export_root(job.result, job.id)
            relative = rel_path or "index.html"
            if relative.endswith("/"):
                relative = f"{relative}index.html"
            path = safe_export_file(root, relative)
        except PreviewError as exc:
            raise HTTPException(404, str(exc)) from exc
        if Path(relative).name.lower() == "index.html":
            body = inject_player_diagnostics(path.read_text(encoding="utf-8"))
            return HTMLResponse(body, headers={"Cache-Control": "no-cache"})
        response = FileResponse(path, media_type=_player_media_type(path))
        if path.suffix.lower() in {".html", ".htm"}:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.post("/api/resize")
    def resize_keynote(
        path: str = Form(...),
        template_path: str = Form(""),
        gold_path: str = Form(""),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        slides: str = Form(""),
        export: str = Form("true"),
        include_lists: str = Form("false"),
        # Form field `validate` would shadow BaseModel.validate; alias keeps the wire name.
        run_validation: str = Form("true", alias="validate"),
        export_dir: str = Form(""),
        offline_hides: str = Form(""),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        hides = _offline_hides_field(offline_hides)
        resolved_export_dir = ""
        if export_dir.strip():
            try:
                resolved_export_dir = str(validate_export_dir(export_dir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        raw_template = (template_path or gold_path).strip()
        if not raw_template:
            raise HTTPException(400, "CG template .key is required.")
        template = Path(raw_template).expanduser()
        if not template.exists():
            raise HTTPException(400, f"CG template not found: {raw_template}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        do_lists = include_lists.lower() in {"1", "true", "yes", "on"}
        do_validate = run_validation.lower() in {"1", "true", "yes", "on"}
        try:
            sel = resolve_slides(
                spec=slides or None,
                range_from=range_from,
                range_to=range_to,
            )
        except ValueError as err:
            raise HTTPException(400, str(err))
        job = RUNNER.submit(
            "resize",
            lambda j, p=key, t=template, sl=sel, ex=do_export, lists=do_lists, va=do_validate, ed=resolved_export_dir, oh=hides: (
                _run_resize_propose(j, p, t, sl, ex, lists, va, export_dir=ed, offline_hides=oh)
            ),
            feature="resize",
        )
        return job.to_dict()

    @app.get("/api/resize/{job_id}/thumb/{which}/{filename}")
    def resize_thumb(job_id: str, which: str, filename: str):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        key = {"wall": "wallThumbDir", "template": "templateThumbDir"}.get(which)
        if not key:
            raise HTTPException(400, "Expected wall or template")
        raw = str((job.result or {}).get(key) or "")
        if not raw:
            raise HTTPException(404, f"Job has no {which} thumbnails")
        folder = Path(raw)
        path = (folder / Path(filename).name).resolve()
        try:
            path.relative_to(folder.resolve())
        except ValueError:
            raise HTTPException(400, "Bad filename") from None
        if not path.is_file():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(path, media_type=preview_media_type(path))

    @app.post("/api/resize/{job_id}/framings")
    def save_resize_framings(job_id: str, payload: FramingsBody) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        decisions = _decisions_from_body(payload, result)
        save_framings(
            result["path"],
            result["templatePath"],
            list(result.get("wallDigests") or []),
            str(result.get("templateDigest") or ""),
            decisions,
            template_digests=list(result.get("templateDigests") or []),
            job_id=job_id,
        )
        authoritative = payload.decisions is not None
        by_index = {d.wall_index: d.as_dict() for d in decisions}
        for page in result.get("pages") or []:
            saved = by_index.get(page["index"])
            if saved:
                page["decision"] = saved
            elif authoritative:
                page["decision"] = None
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result

    @app.post("/api/resize/{job_id}/apply")
    def apply_resize(job_id: str, payload: FramingsBody = Body(default=FramingsBody())) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        result = dict(job.result)
        key = Path(str(result.get("path") or "")).expanduser()
        template = Path(str(result.get("templatePath") or "")).expanduser()
        if not key.exists() or not template.exists():
            raise HTTPException(400, "The wall deck or template has moved since proposing.")
        hides = _offline_hides_field(payload.offlineHides) or result.get("offlineHides")
        if message := _unclosed_output_message():
            raise HTTPException(409, message)
        export_dir: str | None = None
        resolved_export_dir: str | None = None
        if payload and payload.exportDir is not None:
            if payload.exportDir:
                try:
                    resolved_export_dir = str(validate_export_dir(payload.exportDir))
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                export_dir = payload.exportDir
            else:
                proposal_export_dir = result.get("proposalExportDir")
                if proposal_export_dir:
                    resolved_export_dir = proposal_export_dir
                else:
                    try:
                        resolved_export_dir = str(resolve_export_destination(None))
                    except ValueError as exc:
                        raise HTTPException(400, str(exc)) from exc
        if payload and payload.decisions is not None:
            save_resize_framings(job_id, payload)
        if payload and payload.exportDir is not None:
            job = RUNNER.get(job_id)
            current = dict((job.result if job else None) or {})
            if export_dir:
                current["exportDir"] = export_dir
            else:
                current.pop("exportDir", None)
            current["resolvedExportDir"] = resolved_export_dir
            RUNNER.update_result(job_id, current)
        job = RUNNER.get(job_id)
        result = dict((job.result if job else None) or {})
        if "offlineHidesAborted" in result:
            result.pop("offlineHidesAborted")
            RUNNER.update_result(job_id, result)
        overrides = _overrides_from_result(result)
        side_content = _side_content_slides_from_result(result)
        raw_range = result.get("slideRange")
        sel = frozenset(int(n) for n in raw_range) if raw_range else None
        do_export = bool(result.get("export", True))
        do_lists = bool(result.get("includeLists", False))
        do_validate = bool(result.get("validate", True))
        try:
            updated = RUNNER.rerun(
                job_id,
                lambda j, p=key, t=template, sl=sel, ex=do_export, lists=do_lists, ov=overrides, side=side_content, va=do_validate, oh=hides: (
                    _run_resize(j, p, t, sl, ex, lists, ov, side, va, offline_hides=oh)
                ),
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not updated:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(updated)

    from obed_edom.web.maps import router as maps_router
    from obed_edom.web.watercolour import router as watercolour_router

    app.include_router(maps_router)
    app.include_router(watercolour_router)

    if DASHBOARD_DIST.is_dir():
        app.mount("/", SpaStaticFiles(directory=str(DASHBOARD_DIST), html=True), name="ui")

    return app


_PLAYER_MEDIA_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".wasm": "application/wasm",
    ".pdf": "application/pdf",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
}


def _player_media_type(path: Path) -> str:
    return _PLAYER_MEDIA_TYPES.get(path.suffix.lower(), preview_media_type(path))


def _run_html_preview_propose(job: Job, path: Path, expected_digest: str | None) -> dict[str, Any]:
    job.log(f"Inspecting {path.name} for a build preview…")
    return propose_preview(path, expected_digest=expected_digest, job_id=job.id, log=job.log)


def _run_html_preview_apply(job: Job, proposal: dict[str, Any]) -> dict[str, Any]:
    job.log("Preparing the HTML player…")
    return apply_preview(proposal, job_id=job.id, log=job.log)


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _choose_save_script(prompt: str, default_name: str, default_location: str = "") -> str:
    """AppleScript for the standard save panel (`choose file name`)."""
    name = Path(default_name).name or "untitled.key"
    loc = (default_location or "").strip()
    resolved = Path(loc).expanduser() if loc else None
    return _picker_script(
        f'choose file name with prompt "{_as_escape(prompt)}" default name "{_as_escape(name)}"',
        str(resolved) if resolved and resolved.is_absolute() else "",
    )


def _picker_script(choose: str, default_location: str = "") -> str:
    """Host a chooser in the frontmost app (the operator's browser), which owns the panel."""
    lines = ["set hostApp to (path to frontmost application as text)"]
    if default_location:
        lines.append(f'set defaultLoc to POSIX file "{_as_escape(default_location)}"')
        choose += " default location defaultLoc"
    lines += [
        "tell application hostApp",
        "    activate",
        "    with timeout of 86400 seconds",
        f"        set chosen to {choose}",
        "    end timeout",
        "end tell",
        "POSIX path of chosen",
    ]
    return "\n".join(lines)


def _diagnostics_path(job_id: str) -> Path:
    """Canonical diagnostics file location — does not create any directories."""
    return output_root() / ".diff" / job_id / "diagnostics.jsonl"


def _trusted_diagnostics_path(job: Job | None, job_id: str) -> Path | None:
    """The job's `diagnosticsPath`, only if it is the diagnostics file `_run_diff_check`
    actually wrote — `result` is client-patchable via PATCH /api/jobs/{id}."""
    raw = (job.result or {}).get("diagnosticsPath") if job else None
    if not raw:
        return None
    expected = _diagnostics_path(job_id).resolve()
    candidate = Path(raw)
    if candidate.is_symlink():
        return None
    try:
        resolved_parent = candidate.parent.resolve()
    except OSError:
        return None
    if resolved_parent / candidate.name != expected or not expected.is_file():
        return None
    return expected


def _safe_file(folder: Path, filename: str) -> Path:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(404, "Invalid path")
    folder = folder.resolve()
    path = (folder / filename).resolve()
    if path.is_file() and (path.parent == folder or folder in path.parents):
        return path
    matches = [p for p in folder.rglob(filename) if p.is_file()]
    if len(matches) == 1:
        return matches[0]
    raise HTTPException(404, filename)


def _run_generate(
    job: Job, docx: Path, lw_template: Path | None, dsk_template: Path | None
) -> dict[str, Any]:
    job.log(f"Generating from {docx.name}…")
    if lw_template:
        job.log(f"LW template: {lw_template.name}.")
    else:
        job.log("Skipping LW (no template).")
    if dsk_template:
        job.log(f"DSK template: {dsk_template.name}.")
    else:
        job.log("Skipping DSK (no template).")
    result = generate(
        docx,
        lw_template=lw_template,
        dsk_template=dsk_template,
        output_dir=ensure_export_dir(export_destination(job)),
    )
    lw_prev = result.output_dir / "previews" / "lw"
    dsk_prev = result.output_dir / "previews" / "dsk"
    job.log(f"Output {result.output_dir}")
    previews: dict[str, str] = {}
    preview_files: dict[str, list[str]] = {"lw": [], "dsk": []}
    if result.lw_key:
        previews["lw"] = str(lw_prev)
        preview_files["lw"] = preview_names(lw_prev)
    if result.dsk_key:
        previews["dsk"] = str(dsk_prev)
        preview_files["dsk"] = preview_names(dsk_prev)
    return {
        "stem": docx.stem.replace(" ", "_"),
        "source": str(docx),
        "outputDir": str(result.output_dir),
        "lwKey": str(result.lw_key) if result.lw_key else None,
        "dskKey": str(result.dsk_key) if result.dsk_key else None,
        "cuedDocx": str(result.cued_docx) if result.cued_docx else None,
        "reviewPath": str(result.review_path) if result.review_path else None,
        "previews": previews,
        "previewFiles": preview_files,
        "flags": serialize_flags(result.flags),
        "lwCount": len(result.lw_slides) if result.lw_key else 0,
        "dskCount": len(result.dsk_slides) if result.dsk_key else 0,
        "lwTemplate": str(lw_template) if lw_template else None,
        "dskTemplate": str(dsk_template) if dsk_template else None,
        **_carried_export_dir(job),
    }


def _carried_export_dir(job: Job) -> dict[str, Any]:
    """`{"exportDir": ..., "resolvedExportDir": ..., "proposalExportDir": ...}`
    carried from `job.result`.

    Keys are present only when they have a truthy value — never a `None`
    `exportDir`, matching maps' `_run_export`.
    """
    current = job.result or {}
    out: dict[str, Any] = {}
    export_dir = current.get("exportDir")
    if export_dir:
        out["exportDir"] = export_dir
    resolved_export_dir = current.get("resolvedExportDir")
    if resolved_export_dir:
        out["resolvedExportDir"] = resolved_export_dir
    proposal_export_dir = current.get("proposalExportDir")
    if proposal_export_dir:
        out["proposalExportDir"] = proposal_export_dir
    return out


def _form_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _slots_from_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pair in pairs:
        rights = pair.get("rightIndexes")
        if rights is None:
            ri = pair.get("rightIndex")
            rights = [] if ri is None else [ri]
        out.append(slot_dict(pair.get("leftIndex"), list(rights), float(pair.get("score") or 0)))
    return out


def _remember_pairing(job: Job, result: dict[str, Any], *, source: str, force: bool = False) -> None:
    left = result.get("leftPath")
    right = result.get("rightPath")
    if not left or not right:
        return
    slots = result.get("slots") or _slots_from_pairs(result.get("pairs") or [])
    save_pairing(
        "diff",
        left,
        right,
        list(result.get("leftDigests") or []),
        list(result.get("rightDigests") or []),
        slots,
        source=source,
        job_id=job.id,
        force=force,
    )


def _log_inspect(job: Job, name: str, payload: dict[str, Any]) -> None:
    timing = payload.get("_timing") or {}
    if payload.get("_cached"):
        digest_s = timing.get("digest")
        extra = f" ({digest_s:.1f}s hash)" if isinstance(digest_s, (int, float)) else ""
        job.log(f"Reused cached inspect of {name}{extra}.")
        return
    parts = []
    if "jxa" in timing:
        parts.append(f"read {timing['jxa']:.1f}s")
    elif "read" in timing:
        parts.append(f"offline read {timing['read']:.1f}s")
    if "export" in timing:
        parts.append(f"export {timing['export']:.1f}s")
    extra = f" ({', '.join(parts)})" if parts else ""
    job.log(f"Inspected {name}{extra}.")


def _deck_of(label: str, payload: dict[str, Any]) -> str:
    if re.search(r"\b(LW|GW|LED|FW)\b", label or "", re.I):
        return "lw"
    if re.search(r"\bDSK\b", label or "", re.I):
        return "dsk"
    return "lw" if float(payload.get("slideWidth") or 0) >= 3000 else "dsk"


def _run_diff(
    job: Job,
    left: Path,
    right: Path,
    left_label: str,
    right_label: str,
    *,
    fresh: bool = False,
    outline: Path | None = None,
    lw_final: bool = True,
) -> dict[str, Any]:
    settings = load_settings()
    work = diff_work_dir(job.name)
    heat_dir = work / "heat"
    heat_dir.mkdir(parents=True, exist_ok=True)
    if fresh:
        delete_pairing("diff", left, right)

    job.log(f"Inspecting {left.name} (read-only)…")
    left_payload = inspect_keynote_checker(left, export_dir=work / "left")
    _log_inspect(job, left.name, left_payload)
    left_dir = Path(left_payload.get("previewDir") or work / "left")
    left_n = len(preview_pngs(left_dir))
    if left_n:
        job.log(f"Exported {left_n} LW preview PNG(s).")
    else:
        job.log(left_payload.get("exportError") or "LW preview export produced no PNGs.")

    job.log(f"Inspecting {right.name} (read-only)…")
    right_payload = inspect_keynote_checker(right, export_dir=work / "right")
    _log_inspect(job, right.name, right_payload)
    right_dir = Path(right_payload.get("previewDir") or work / "right")
    right_n = len(preview_pngs(right_dir))
    if right_n:
        job.log(f"Exported {right_n} {right_label} preview PNG(s).")
    else:
        job.log(right_payload.get("exportError") or f"{right_label} preview export produced no PNGs.")

    left_digests = deck_slide_digests(left_payload)
    right_digests = deck_slide_digests(right_payload)
    reuse_report = None
    slots = None

    left_deck = _deck_of(left_label, left_payload)
    right_deck = _deck_of(right_label, right_payload)
    playlist = None
    if outline is not None:
        playlist, _paragraphs = load_playlist(outline)
        job.log(
            f"Read {playlist.count('lw')} LW and {playlist.count('dsk')} DSK cues "
            f"from {outline.name}."
        )
        job.log(
            "LW is marked finalised, so it outranks the outline on wording."
            if lw_final
            else "LW is not finalised, so the outline leads on wording."
        )

    if settings["reusePairings"] and not fresh:
        baseline = load_pairing("diff", left, right)
        if baseline:
            reused = reuse_slots(
                baseline, left_digests, right_digests, float(settings["reuseThreshold"])
            )
            if reused:
                job.log(
                    f"Reusing {reused.carried} pairing(s) from an earlier run "
                    f"({reused.changed} changed, {reused.added} added, {reused.removed} removed)…"
                )
                t_gaps = time.perf_counter()
                left_size = (
                    float(left_payload.get("slideWidth") or 0),
                    float(left_payload.get("slideHeight") or 0),
                )
                right_size = (
                    float(right_payload.get("slideWidth") or 0),
                    float(right_payload.get("slideHeight") or 0),
                )
                filled = realign_gaps(
                    reused.slots,
                    left_payload.get("slides") or [],
                    right_payload.get("slides") or [],
                    left_pngs=preview_pngs(left_dir),
                    right_pngs=preview_pngs(right_dir),
                    left_size=left_size,
                    right_size=right_size,
                )
                slots = slots_from_pairs(filled)
                job.log(f"Filled changed gaps in {time.perf_counter() - t_gaps:.1f}s.")
                reuse_report = {key: value for key, value in reused.as_dict().items() if key != "slots"}
            else:
                job.log("Earlier pairing no longer matches this content; starting fresh.")

    if slots is None and playlist is not None:
        lw_payload = left_payload if left_deck == "lw" else right_payload
        dsk_payload = right_payload if right_deck == "dsk" else left_payload
        seeded = slots_from_cues(
            playlist,
            slide_catalog(lw_payload.get("slides") or [], {}),
            slide_catalog(dsk_payload.get("slides") or [], {}),
            left_deck=left_deck,
        )
        if seeded:
            slots = seeded
            job.log(f"Seeded {len(seeded)} pair(s) from the outline cues.")

    job.log("Matching slides…")
    t_match = time.perf_counter()
    compared = compare_inspects(
        left_payload,
        right_payload,
        left_dir,
        right_dir,
        heat_dir,
        left_label=left_label,
        right_label=right_label,
        slots=slots,
        check=False,
    )
    job.log(f"Matched slides in {time.perf_counter() - t_match:.1f}s.")
    inspect_left = work / "left-inspect.json"
    inspect_right = work / "right-inspect.json"
    inspect_left.write_text(json.dumps(left_payload), encoding="utf-8")
    inspect_right.write_text(json.dumps(right_payload), encoding="utf-8")
    flags = compared.pop("flags")
    pairs = compared["pairs"]
    if playlist is not None:
        _attach_outline_rows(playlist, pairs)
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    result = {
        "leftPath": str(left),
        "rightPath": str(right),
        "leftLabel": left_label,
        "rightLabel": right_label,
        "outlinePath": str(outline) if outline else None,
        "lwFinal": bool(lw_final),
        "leftDeck": left_deck,
        "rightDeck": right_deck,
        "phase": "match",
        "sameType": compared.get("sameType"),
        "leftPreviews": str(left_dir),
        "rightPreviews": str(right_dir),
        "heatDir": str(heat_dir),
        "evidenceDir": str(work / "evidence"),
        "workDir": str(work),
        "outputDir": str(work),
        "leftInspect": str(inspect_left),
        "rightInspect": str(inspect_right),
        "leftPngs": [p.name for p in preview_pngs(left_dir)],
        "rightPngs": [p.name for p in preview_pngs(right_dir)],
        "heatPngs": [p.name for p in preview_pngs(heat_dir)],
        "leftCatalog": compared.get("leftCatalog") or [],
        "rightCatalog": compared.get("rightCatalog") or [],
        "leftDigests": left_digests,
        "rightDigests": right_digests,
        "summary": compared,
        "pairs": pairs,
        "slots": _slots_from_pairs(pairs),
        "flags": serialize_flags(flags),
    }
    if reuse_report:
        result["reuse"] = reuse_report
    source = "operator" if reuse_report and reuse_report.get("source") == "operator" else "auto"
    _remember_pairing(job, result, source=source, force=True)
    return result


def _pairs_from_catalog(result: dict[str, Any], slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    left = {int(s["index"]): s for s in (result.get("leftCatalog") or []) if s.get("index") is not None}
    right = {int(s["index"]): s for s in (result.get("rightCatalog") or []) if s.get("index") is not None}
    left_label = result.get("leftLabel") or "LW"
    right_label = result.get("rightLabel") or "DSK"
    pairs = []
    for i, slot in enumerate(slots):
        li = slot.get("leftIndex")
        ris = slot.get("rightIndexes")
        if ris is None:
            ri = slot.get("rightIndex")
            ris = [] if ri is None else [ri]
        ris = [int(x) for x in ris if x is not None]
        ls = left.get(int(li)) if li is not None else None
        found = [(idx, right.get(idx)) for idx in ris]
        rights = [rec for _, rec in found if rec]
        ris = [idx for idx, rec in found if rec]
        rs = rights[0] if rights else None
        pair = {
            "index": i,
            "number": i + 1,
            "leftIndex": int(li) if li is not None else None,
            "rightIndex": int(ris[0]) if ris else None,
            "rightIndexes": ris,
            "leftNumber": (ls or {}).get("number") if ls else None,
            "rightNumber": (rs or {}).get("number") if rs else None,
            "rightNumbers": [r.get("number") for r in rights],
            "leftSkipped": bool((ls or {}).get("skipped")),
            "rightSkipped": any(bool(r.get("skipped")) for r in rights),
            "leftPng": (ls or {}).get("png"),
            "rightPng": (rs or {}).get("png"),
            "rightPngs": [r.get("png") for r in rights],
            "leftText": (ls or {}).get("text") or "",
            "rightText": "\n".join(r.get("text") or "" for r in rights),
            "score": slot.get("score") or 0,
            "flags": [],
        }
        if ls is None:
            pair["missing"] = left_label
        elif not rights:
            pair["missing"] = right_label
        pairs.append(pair)
    return pairs


def _run_diff_check(job: Job) -> dict[str, Any]:
    result = dict(job.result or {})
    left_inspect = Path(result.get("leftInspect") or "")
    right_inspect = Path(result.get("rightInspect") or "")
    if not left_inspect.is_file() or not right_inspect.is_file():
        raise FileNotFoundError("Match pass inspect JSON is missing; run Match again.")
    left_payload = json.loads(left_inspect.read_text(encoding="utf-8"))
    right_payload = json.loads(right_inspect.read_text(encoding="utf-8"))
    slots = slots_from_pairs(result.get("pairs") or [])
    job.log("Checking wording, photos, and house style…")
    # Canonical, server-owned location — never derived from the (client-patchable)
    # `result["workDir"]`.
    diag_path = _diagnostics_path(job.id)
    diag = None
    try:
        diag = DiagnosticsWriter(diag_path)
    except OSError:
        job.log("Could not open diagnostics file; continuing without it.")
    t_check = time.perf_counter()
    diag_committed = False
    try:
        compared = compare_inspects(
            left_payload,
            right_payload,
            Path(result["leftPreviews"]),
            Path(result["rightPreviews"]),
            Path(result["heatDir"]),
            left_label=str(result.get("leftLabel") or "LW"),
            right_label=str(result.get("rightLabel") or "Other"),
            slots=slots,
            check=True,
            diag=diag,
            diag_context={"jobId": job.id},
        )
        job.log(f"Checked pairs in {time.perf_counter() - t_check:.1f}s.")
        flags = compared.pop("flags")
        pairs = compared["pairs"]
        outline_flags = _apply_outline(job, result, compared, pairs, diag=diag)
        if diag is not None:
            diag_committed = diag.commit()
    finally:
        if diag is not None and not diag_committed:
            diag.close()
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    if diag is not None:
        if diag_committed:
            job.log(f"Wrote diagnostics for {len(pairs)} pair(s).")
            if diag.error:
                job.log(f"Some diagnostics records were dropped ({diag.error}).")
        elif diag.error:
            job.log(
                f"Diagnostics were incomplete and have been discarded "
                f"({diag.error}); the previous diagnostics file is unchanged."
            )
    result.update(
        {
            "phase": "checked",
            "diagnosticsPath": str(diag_path) if diag_committed else None,
            "sameType": compared.get("sameType"),
            "heatPngs": [p.name for p in preview_pngs(Path(result["heatDir"]))],
            "leftCatalog": compared.get("leftCatalog") or result.get("leftCatalog") or [],
            "rightCatalog": compared.get("rightCatalog") or result.get("rightCatalog") or [],
            "summary": compared,
            "pairs": pairs,
            "flags": serialize_flags(flags),
            "outlineFlags": serialize_flags(outline_flags),
        }
    )
    return result


def _attach_outline_rows(playlist, pairs: list[dict]) -> list:
    rows = rows_for_slots(playlist, slots_from_pairs(pairs))
    for pair, row in zip(pairs, rows):
        pair["outlineRow"] = (
            None
            if row is None
            else {"index": row.index, "tags": row.tags, "script": row.script, "paragraph": row.paragraph}
        )
    return rows


def _apply_outline(
    job: Job,
    result: dict[str, Any],
    compared: dict[str, Any],
    pairs: list[dict],
    *,
    diag: DiagnosticsWriter | None = None,
) -> list[Flag]:
    raw = result.get("outlinePath")
    if not raw or not Path(raw).is_file():
        return []
    try:
        playlist, _paragraphs = load_playlist(Path(raw))
    except Exception as exc:  # noqa: BLE001
        job.log(f"Could not read the outline cues: {exc}")
        return []

    left_deck = result.get("leftDeck") or "lw"
    right_deck = result.get("rightDeck") or "dsk"
    catalogs: dict[str, list[dict]] = {}
    for deck, key in ((left_deck, "leftCatalog"), (right_deck, "rightCatalog")):
        catalog = compared.get(key) or result.get(key) or []
        if catalog and deck not in catalogs:
            catalogs[deck] = catalog

    job.log("Checking the outline cues against the decks…")
    flags = correspondence(playlist, catalogs)
    for flag in flags:
        record_flag(diag, flag, None)

    rows = _attach_outline_rows(playlist, pairs)
    for pair, row in zip(pairs, rows):
        if row is None or not row.script:
            continue
        lw_text = pair.get("leftRendered" if left_deck == "lw" else "rightRendered") or ""
        dsk_text = pair.get("rightRendered" if right_deck == "dsk" else "leftRendered") or ""
        number = pair.get("leftNumber") if left_deck == "lw" else pair.get("rightNumber")
        found = corroborate(
            row.script,
            lw_text,
            dsk_text,
            location=f"{result.get('leftLabel') or 'LW'} slide {number}",
            slide=number,
            typed=bool(pair.get("typed", True)),
            lw_final=bool(result.get("lwFinal", True)),
        )
        if found:
            pair.setdefault("flags", []).extend(found)
            for flag in found:
                record_flag(diag, flag, pair.get("index"))
    return flags


def _run_outline(job: Job, path: Path) -> dict[str, Any]:
    job.log(f"Reading cues from {path.name}…")
    report = outline_report(path)
    job.log(
        f"{report['lwCues']} LW and {report['dskCues']} DSK cues across "
        f"{len(report['rows'])} advance(s)."
    )
    job.log("Checking scripture references and house style…")
    dest_dir = default_output_root() / ".outline" / job.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = export_destination(job) / f"{path.stem}_findings.pdf"
    written = _write_outline_pdf(job, dest, report)
    return {
        **report,
        "kind": "outline",
        "outputDir": str(dest_dir),
        "outlineReport": str(written) if written else None,
        **_carried_export_dir(job),
    }


def _write_outline_pdf(job: Job, dest: Path, report: dict[str, Any]) -> Path | None:
    from obed_edom.report import write_outline_findings  # noqa: PLC0415

    ensure_export_dir(dest.parent)
    try:
        return write_outline_findings(dest, report)
    except Exception as exc:  # noqa: BLE001
        job.log(f"Could not write the findings PDF ({exc}).")
        return None


def _run_inspect(
    job: Job,
    path: Path,
    export: bool,
    slide_range: frozenset[int] | None,
    *,
    outline: Path | None = None,
    lw_final: bool = True,
) -> dict[str, Any]:
    job_dir = default_output_root() / ".inspect" / job.name if export else None
    job.log(f"Inspecting {path.name} (read-only, no save)…")
    payload = inspect_keynote(path, export_dir=job_dir, slide_range=slide_range)
    _log_inspect(job, path.name, payload)
    preview_path = Path(payload.get("previewDir") or job_dir) if job_dir else None
    names = preview_names(preview_path) if preview_path else []
    if preview_path and names:
        job.log(f"Exported {len(names)} preview PNG(s).")
    elif job_dir:
        job.log(payload.get("exportError") or "Preview export produced no PNGs.")
    evidence_dir = (job_dir / "evidence") if job_dir else None
    flags = validate_inspect(
        payload,
        location_prefix=path.name,
        previews=preview_pngs(preview_path) if preview_path else None,
        evidence_dir=evidence_dir,
    )
    preview_dir = str(preview_path) if preview_path else None
    deck = _deck_of(path.name, payload)
    outline_flags = _check_single_deck_outline(
        job, outline, payload, deck, flags, lw_final=lw_final
    )
    return {
        "path": str(path),
        "outlinePath": str(outline) if outline else None,
        "lwFinal": bool(lw_final),
        "deck": deck,
        "outputDir": str(job_dir) if job_dir else None,
        "evidenceDir": str(evidence_dir) if evidence_dir else None,
        "slideWidth": payload.get("slideWidth"),
        "slideHeight": payload.get("slideHeight"),
        "slideCount": payload.get("slideCount"),
        "exported": payload.get("exported"),
        "previews": {"lw": preview_dir, "dsk": None} if preview_dir else None,
        "previewFiles": {"lw": names, "dsk": []} if names else {"lw": [], "dsk": []},
        "previewDir": preview_dir,
        "previewFileNames": names,
        "flags": serialize_flags(flags),
        "outlineFlags": serialize_flags(outline_flags),
    }


def _check_single_deck_outline(
    job: Job,
    outline: Path | None,
    payload: dict[str, Any],
    deck: str,
    flags: list[Flag],
    *,
    lw_final: bool = True,
) -> list[Flag]:
    if outline is None:
        return []
    try:
        playlist, _paragraphs = load_playlist(outline)
    except Exception as exc:  # noqa: BLE001
        job.log(f"Could not read the outline cues: {exc}")
        return []
    slides = payload.get("slides") or []
    catalog = slide_catalog(slides, {})
    job.log(
        f"Checking {playlist.count(deck)} {deck.upper()} cue(s) against "
        f"{len(visible_slides(catalog))} slide(s)."
    )
    out = correspondence(playlist, {deck: catalog})

    rows = [row for row in playlist.rows if getattr(row, deck) is not None]
    for row, slide in zip(rows, visible_slides(catalog)):
        if not row.script:
            continue
        text = slide.get("text") or ""
        found = corroborate(
            row.script,
            text if deck == "lw" else "",
            text if deck == "dsk" else "",
            location=f"{deck.upper()} slide {slide.get('number')}",
            slide=slide.get("number"),
            typed=bool(text.strip()),
            lw_final=lw_final,
        )
        for flag in found:
            flags.append(flag if flag.deck == "outline" else replace(flag, deck=deck))
    return out


def _decisions_from_body(payload: FramingsBody, result: dict[str, Any]) -> list[Decision]:
    """Unparseable entries are dropped rather than guessed."""
    if payload.decisions is not None:
        rows = payload.decisions
    else:
        rows = [p.get("decision") or {} for p in result.get("pages") or []]
    out: list[Decision] = []
    for raw in rows:
        decision = normalize_decision(raw)
        if decision is not None:
            out.append(decision)
    return out


def _overrides_from_result(result: dict[str, Any]) -> dict[int, int]:
    overrides: dict[int, int] = {}
    for page in result.get("pages") or []:
        decision = normalize_decision(page.get("decision") or {})
        if decision is None or decision.state != PINNED or decision.template_slide is None:
            continue
        overrides[int(page["slide"])] = int(decision.template_slide)
    return overrides


def _side_content_slides_from_result(result: dict[str, Any]) -> set[int]:
    slides: set[int] = set()
    for page in result.get("pages") or []:
        decision = normalize_decision(page.get("decision") or {})
        if decision is not None and decision.keep_side_content:
            slides.add(int(page["slide"]))
    return slides


def _assert_range_within_deck(name: str, total: int, slide_range: Any) -> None:
    if not slide_range or not total:
        return
    beyond = sorted(n for n in slide_range if n > total)
    if not beyond:
        return
    plural = "s" if total != 1 else ""
    raise RuntimeError(
        f"{name} has {total} slide{plural}, but the range asks for slide "
        f"{format_slide_range(frozenset(beyond))}. Check the deck or the slide range."
    )


def _complete_cached_wall_payload(payload: dict[str, Any] | None) -> bool:
    """Compatibility wrapper for the shared cache completeness check."""
    return complete_cached_wall_payload(payload)


def _assert_range_within_navigator(name: str, payload: dict[str, Any], slide_range: Any) -> None:
    if not slide_range:
        return
    total = sum(1 for slide in payload["slides"] if not slide.get("skipped"))
    beyond = sorted(n for n in slide_range if n > total)
    if not beyond:
        return
    plural = "s" if total != 1 else ""
    raise RuntimeError(
        f"{name} shows {total} slide{plural} in Keynote, but the range asks for slide "
        f"{format_slide_range(frozenset(beyond))}. Check the deck or the slide range."
    )


def _dsk_output_dir(fw_deck: Path) -> Path:
    return default_output_root() / fw_deck.stem / "dsk"


def _dsk_preview_thumbs(job: Job, path: Path, payload: dict[str, Any]) -> dict[int, str]:
    """Preview thumbnails for a DSK propose. A cache miss launches Keynote to export
    previews; that launch is quit again here so the following apply's strictly-serial
    Keynote gate does not 409. A Keynote the operator already had open is left alone."""
    was_running = keynote_running()
    thumbs = build_preview_thumbs(path, payload, log=job.detail)
    if not was_running and keynote_running():
        job.log("Quitting the Keynote launched for preview export…")
        out_dir = _dsk_output_dir(path)
        out_dir.mkdir(parents=True, exist_ok=True)
        quit_and_wait_for_exit(path.stem, path.name, out_dir)
    return thumbs


def _dsk_decision_defaults(page: dict[str, Any], content_only: bool) -> dict[str, Any]:
    include = page.get("category") != "empty" and not (content_only and page.get("isText"))
    return {
        "slide": page["slide"],
        "include": include,
        "action": "both" if page.get("needsClip") else "in_deck",
        "anchor": "auto",
        "keepSide": False,
        "clip": None,
        "videosOnly": False,
    }


def _apply_dsk_decisions(result: dict[str, Any], decisions: list[dict[str, Any]] | None) -> None:
    """Merges operator decisions onto proposed pages; a text page can never be
    included while `contentOnly` is set, regardless of what the body says."""
    content_only = bool(result.get("contentOnly"))
    authoritative = decisions is not None
    by_slide = {int(d["slide"]): d for d in (decisions or []) if d.get("slide") is not None}
    for page in result.get("pages") or []:
        number = int(page["slide"])
        current = page.get("decision") or _dsk_decision_defaults(page, content_only)
        raw = by_slide.get(number)
        if raw is not None:
            current = {**current, **{k: v for k, v in raw.items() if k in current}}
        elif authoritative:
            current = _dsk_decision_defaults(page, content_only)
        if content_only and page.get("isText"):
            current["include"] = False
        current["videosOnly"] = bool(current.get("videosOnly")) and bool(page.get("canVideosOnly"))
        page["decision"] = current


def _dsk_videos_only_flags(cls: Any, slide: dict[str, Any] | None, crop: Rect) -> tuple[bool, bool]:
    """`(canVideosOnly, stackedMovies)` for one proposed page. A slide can go
    videos-only when every movie it counts is a kept top-level item — a movie nested in
    a group is out of reach. Stacked follows the assembler's own `movies_stacked` on the
    rects visible inside `crop` (the centre panel, or the whole wall with Keep side)."""
    movie_ids = {item for item in cls.kept if item[0] == "movie"}
    if cls.is_text or not movie_ids or cls.movie_count != len(movie_ids):
        return False, False
    rects = {
        (item["kind"], item["kindIndex"]): item_rect(item)
        for item in (slide or {}).get("items") or []
        if (item.get("kind"), item.get("kindIndex")) in movie_ids
    }
    return True, movies_stacked(visible_movie_rects(rects, crop))


def _dsk_keep_side_from_result(result: dict[str, Any]) -> set[int]:
    slides: set[int] = set()
    for page in result.get("pages") or []:
        decision = page.get("decision") or {}
        if decision.get("include") and decision.get("keepSide"):
            slides.add(int(page["slide"]))
    return slides


def _resolve_dsk_compiled_targets(
    path: Path,
    compiled: Sequence[Any],
    decisions: Mapping[int, SlideDecision],
) -> tuple[Any, ...]:
    if not compiled:
        return ()
    payload = offline_wall_payload(path)
    slides = {int(slide["number"]): slide for slide in payload.get("slides") or []}
    all_numbers = frozenset(slides)
    lw_classes = {cls.number: cls for cls in classify_deck(path, payload=payload)}
    fw_classes = {
        cls.number: cls
        for cls in classify_deck(path, payload=payload, include_side=all_numbers)
    }
    resolved: list[Any] = []
    for composition in compiled:
        number = int(composition.layout_slide)
        decision = decisions[number]
        cls = (fw_classes if composition.source_mode == "fw" else lw_classes)[number]
        kept = cls.kept
        if composition.content_mode == "video":
            kept = tuple(item_id for item_id in kept if item_id[0] == "movie")
        frame = composition.output_frame
        fitted = fit_slide(
            slides[number].get("items") or [],
            Band(frame.y + frame.h, frame.h, frame.x, frame.x + frame.w, 1),
            kept=kept,
            include_side=composition.source_mode == "fw",
            anchor=decision.anchor,
        )
        media = tuple(
            replace(
                entry,
                target_rect=fitted.get(entry.source_item, entry.target_rect)
                if entry.source_slide == number
                else entry.target_rect,
            )
            for entry in composition.media
        )
        resolved.append(replace(composition, media=media))
    return tuple(resolved)


def _dsk_archive_ids(path: Path) -> dict[tuple[int, str, int], str]:
    """Best-effort archive identities for v2 occurrences.

    Test payloads and old/offline-only installations can lack IWA decoding.  The
    planner retains a deterministic unresolved identity in that case, but a real
    decode always supplies the drawable archive id.
    """
    try:
        records = compose_deck_geometry(path)
    except Exception:  # Optional IWA reader / synthetic test payload.
        return {}
    return {
        (number + 1, str(record["kind"]), int(record["kindIndex"])): str(record["id"])
        for number, entries in records.items()
        for record in entries
        if record.get("kind") in {"movie", "image"}
    }


def _dsk_build_records(path: Path) -> dict[int, dict[str, Any]]:
    try:
        return deck_builds(path)
    except Exception:
        return {}


def _dsk_magic_move_transitions(
    path: Path,
    records: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[int, str | None]:
    result: dict[int, str | None] = {}
    for number, entry in (records if records is not None else _dsk_build_records(path)).items():
        attrs = ((entry.get("transition") or {}).get("attributes") or {})
        anim = attrs.get("animationAttributes") or {}
        result[number] = str(anim.get("effect") or attrs.get("databaseEffect") or "")
    return result


def _dsk_review_result(result: dict[str, Any]) -> dict[str, Any] | None:
    review = result.get("review")
    return review if isinstance(review, dict) else None


def _save_v2_dsk_review(job_id: str, payload: DskDecisionsBody) -> dict:
    """Serialized optimistic v2 save.  The job lock covers revision read/write."""
    if payload.review is None or payload.baseRevision is None:
        raise HTTPException(400, "Version 2 saves require review and baseRevision")
    if isinstance(payload.baseRevision, bool) or payload.baseRevision < 0:
        raise HTTPException(400, "baseRevision must be a non-negative integer")
    with RUNNER.job_lock(job_id):
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        stored = _dsk_review_result(result)
        if stored is None:
            raise HTTPException(409, "This is a version 1 DSK review; save it through the legacy path.")
        current_revision = int(stored.get("revision") or 0)
        if payload.baseRevision != current_revision:
            raise HTTPException(409, "This review changed in another window; reload before saving.")
        path = Path(str(stored.get("source", {}).get("path") or result.get("path") or ""))
        try:
            actual = deck_digest(path)
        except Exception as exc:
            raise HTTPException(409, f"Could not verify the source deck: {exc}") from exc
        if actual != stored.get("source", {}).get("fingerprint"):
            raise HTTPException(409, "The source deck changed since this review was proposed.")
        try:
            merged = apply_editable_review(stored, payload.review)
        except ReviewValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        merged["revision"] = current_revision + 1
        result["review"] = merged
        result["reviewMode"] = "v2"
        if payload.exportDir is not None and payload.exportDir.strip():
            try:
                result["exportDir"] = str(validate_export_dir(payload.exportDir))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        # These mirrors make the response easy for a v2 client while `pages` keeps
        # the existing v1 dashboard and apply path backward compatible.
        result.update({key: merged[key] for key in ("schemaVersion", "revision", "source", "canvas", "safeArea", "defaults", "compositions")})
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result


def _require_dsk_template_field(raw: str, *, reason: str | None = None) -> Path:
    stripped = (raw or "").strip()
    if not stripped:
        raise HTTPException(
            400,
            detail={
                "field": "dskTemplate",
                "message": reason
                or "Choose the DSK template (.key) — the lower-thirds deck that supplies the DSK layouts.",
            },
        )
    template_path = Path(stripped).expanduser()
    if not template_path.exists():
        raise HTTPException(
            400,
            detail={
                "field": "dskTemplate",
                "message": f"DSK template not found at {stripped}. Choose it again with “Choose on this Mac”.",
            },
        )
    return template_path.resolve()


def _validate_dsk_template(raw: str, fw_deck: Path, *, content_only: bool, reason: str | None = None) -> Path:
    template_path = _require_dsk_template_field(raw, reason=reason)
    layout_names = DEFAULT_TRANSPARENT_LAYOUT_NAMES if content_only else DEFAULT_DSK_LAYOUT_NAMES
    try:
        check_layout_import_preconditions(
            fw_deck, layout_template=template_path, layout_names=layout_names
        )
    except AssemblyRefusal as exc:
        raise HTTPException(400, detail={"field": "dskTemplate", "message": str(exc)}) from exc
    return template_path


def _resolve_dsk_layout_donor(
    raw_template: str, fw_deck: Path, reference: Path | None, *, content_only: bool
) -> Path | None:
    """The deck that donates the DSK layouts, in order: none when `fw_deck` already owns an
    alpha-safe transparent layout, else the reference deck when it can donate one, else the
    template. The full (text) path always needs the template."""
    if not content_only:
        return _validate_dsk_template(raw_template, fw_deck, content_only=False)
    names = DEFAULT_TRANSPARENT_LAYOUT_NAMES
    if owned_alpha_safe_layout(fw_deck, names) is not None:
        return None
    if reference is not None:
        try:
            check_layout_import_preconditions(fw_deck, layout_template=reference, layout_names=names)
            return reference.resolve()
        except (ValueError, OSError, KeyError, zipfile.BadZipFile):
            pass
    reason = (
        f"Choose the DSK template (.key): {fw_deck.name} has no transparent "
        f"{names[0]!r} layout and no reference deck supplies one."
    )
    return _validate_dsk_template(raw_template, fw_deck, content_only=True, reason=reason)


def _resolve_apply_dsk_template(
    job_id: str, result: dict[str, Any], override: str | None
) -> tuple[dict[str, Any], Path | None]:
    """An explicit apply-time template is honoured as the donor; otherwise the proposal's."""
    raw_override = (override or "").strip()
    if not raw_override:
        if "dskTemplate" not in result:
            return result, _require_dsk_template_field("")
        stored = str(result.get("dskTemplate") or "")
        if not stored and result.get("contentOnly"):
            return result, None
        return result, _require_dsk_template_field(stored)
    fw_deck = Path(str(result.get("path") or "")).expanduser()
    template_path = _validate_dsk_template(raw_override, fw_deck, content_only=bool(result.get("contentOnly")))
    result = dict(result)
    result["dskTemplate"] = str(template_path)
    seeded = RUNNER.update_result(job_id, result)
    if seeded:
        result = dict(seeded.result or result)
    return result, template_path


def _run_dsk_propose(
    job: Job,
    path: Path,
    reference_deck: Path | None,
    dsk_template: Path | None,
    slide_range: frozenset[int] | None,
    content_only: bool,
    text_slide_words: int | None,
) -> dict[str, Any]:
    words = text_slide_words if text_slide_words is not None else DEFAULT_TEXT_SLIDE_WORDS
    mode = "content-only (skips text slides)" if content_only else "full"
    job.set_progress(1, 3, "Reading the deck")
    job.log(f"Reading {path.name} for the DSK generator ({mode})…")
    payload = offline_wall_payload(path)
    wall = (payload.get("slideWidth"), payload.get("slideHeight"))
    if wall not in {(7680.0, 1080.0), (7680, 1080)}:
        raise ValueError(
            f"Source canvas is {wall[0]}x{wall[1]}; DSK generation requires a 7680x1080 FW deck."
        )
    _assert_range_within_deck(path.name, int(payload.get("slideCount") or 0), slide_range)
    all_numbers = [int(s["number"]) for s in payload["slides"]]
    numbers = sorted(expand_slide_range(slide_range) or set(all_numbers))
    classes = {c.number: c for c in classify_deck(path, payload=payload, text_slide_words=words)}
    side_classes = {
        c.number: c
        for c in classify_deck(
            path, payload=payload, text_slide_words=words, include_side=frozenset(all_numbers)
        )
    }
    job.set_progress(2, 3, "Making slide previews")
    thumbs = _dsk_preview_thumbs(job, path, payload)
    job.log(f"Made {len(thumbs)} slide preview(s).")
    fingerprint = deck_digest(path)
    thumb_dir = wall_thumb_dir(fingerprint)
    slides_by_number = {int(s["number"]): s for s in payload["slides"]}
    pages: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    job.set_progress(3, 3, "Building the review")
    for number in numbers:
        cls = classes.get(number)
        if cls is None:
            continue
        if cls.category == "empty":
            skipped.append({"slide": number, "reason": "empty"})
            continue
        is_text = bool(cls.is_text)
        if is_text:
            skipped.append({"slide": number, "reason": "text"})
            job.detail(f"slide {number}: skipped (text slide; content-only)")
        slide = slides_by_number.get(number)
        can_videos_only, stacked_movies = _dsk_videos_only_flags(cls, slide, CENTRE_PANEL_RECT)
        _side_can, stacked_keep_side = _dsk_videos_only_flags(
            side_classes.get(number, cls), slide, Rect(0.0, 0.0, *LW_WALL_SIZE)
        )
        page = {
            "slide": number,
            "thumb": thumbs.get(number),
            "category": cls.category,
            "buildCount": cls.build_count,
            "movieCount": cls.movie_count,
            "isText": is_text,
            "skipReason": "text" if is_text else None,
            "needsClip": cls.category in {"movie", "mixed"},
            "canVideosOnly": can_videos_only,
            "stackedMovies": stacked_movies,
            "stackedMoviesKeepSide": stacked_keep_side,
        }
        page["decision"] = _dsk_decision_defaults(page, content_only)
        pages.append(page)
    build_records = _dsk_build_records(path)
    review = build_review(
        path=str(path),
        fingerprint=fingerprint,
        payload=payload,
        classes=classes,
        thumbs=thumbs,
        selected=numbers,
        archive_ids=_dsk_archive_ids(path),
        stacked={int(page["slide"]): bool(page.get("stackedMovies")) for page in pages},
        stacked_fw={int(page["slide"]): bool(page.get("stackedMoviesKeepSide")) for page in pages},
        transitions=_dsk_magic_move_transitions(path, build_records),
        builds=build_records,
        side_classes=side_classes,
        content_only=content_only,
    )
    return {
        "phase": "review",
        "path": str(path),
        "referenceDeck": str(reference_deck) if reference_deck else None,
        "dskTemplate": str(dsk_template) if dsk_template else "",
        "contentOnly": content_only,
        "textSlideWords": words,
        "slideRange": sorted(slide_range) if slide_range else None,
        "thumbDir": str(thumb_dir),
        "pages": pages,
        "skipped": skipped,
        "review": review,
        **{key: review[key] for key in ("schemaVersion", "revision", "source", "canvas", "safeArea", "defaults", "compositions")},
    }


def _run_dsk_apply(job: Job, proposal: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(proposal.get("path") or "")).expanduser()
    if "dskTemplate" not in proposal:
        raise ValueError("Missing DSK template; re-propose to choose one.")
    raw_dsk_template = str(proposal.get("dskTemplate") or "")
    dsk_template = Path(raw_dsk_template).expanduser() if raw_dsk_template else None
    reference_raw = proposal.get("referenceDeck")
    reference_deck = Path(reference_raw).expanduser() if reference_raw else None
    content_only = bool(proposal.get("contentOnly"))
    words = int(proposal.get("textSlideWords") or DEFAULT_TEXT_SLIDE_WORDS)
    pages = proposal.get("pages") or []
    review = (
        proposal.get("review")
        if proposal.get("reviewMode") == "v2" and isinstance(proposal.get("review"), dict)
        else None
    )
    compiled = compile_review(review) if review is not None else ()
    review_by_id = {
        str(comp["id"]): comp for comp in ((review or {}).get("compositions") or [])
    }
    if review is not None:
        included = [
            {
                "slide": comp.layout_slide,
                "category": str(review_by_id.get(comp.id, {}).get("category") or ""),
                "needsClip": any(media.source_item[0] == "movie" for media in comp.media),
                "decision": {"clip": None},
            }
            for comp in compiled
        ]
    else:
        included = [p for p in pages if (p.get("decision") or {}).get("include")]
    if not included:
        raise AssemblyRefusal(
            "No slides selected to assemble; check Include on at least one page."
        )
    decisions: dict[int, SlideDecision] = {}
    if review is not None:
        include_side = {comp.layout_slide for comp in compiled if comp.source_mode == "fw"}
        for comp in compiled:
            has_movie = any(media.source_item[0] == "movie" for media in comp.media)
            decisions[comp.layout_slide] = SlideDecision(
                slide=comp.layout_slide,
                action="both" if has_movie else "in_deck",
                anchor=comp.alignment,
                keep_side=comp.source_mode == "fw",
                videos_only=comp.content_mode == "video",
            )
    else:
        include_side = _dsk_keep_side_from_result(proposal)
        for page in included:
            decision = page["decision"]
            number = int(page["slide"])
            action = "both" if decision.get("clip") or page.get("needsClip") else "in_deck"
            decisions[number] = SlideDecision(
                slide=number,
                action=action,
                anchor=str(decision.get("anchor") or "auto"),
                keep_side=number in include_side,
                videos_only=bool(decision.get("videosOnly")) and bool(page.get("canVideosOnly")),
            )
    if review is not None:
        compiled = _resolve_dsk_compiled_targets(path, compiled, decisions)
    raw_export = str(proposal.get("exportDir") or "").strip()
    if raw_export:
        try:
            out_dir = validate_export_dir(raw_export)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    else:
        out_dir = _dsk_output_dir(path)
        out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{path.stem}_DSK.key"
    src_dir = out_dir / "src"

    clip_slides = sorted(int(p["slide"]) for p in included if p.get("needsClip"))
    movie_plans = movie_crop_plans_from_compiled(compiled) if review is not None else ()
    operator_clips: dict[int, Path] = {}
    if review is None:
        for page in included:
            raw_clip = (page.get("decision") or {}).get("clip")
            if raw_clip:
                operator_clips[int(page["slide"])] = Path(raw_clip).expanduser()
    missing_clip_slides = [] if review is not None else [n for n in clip_slides if n not in operator_clips]
    needs_clip_export = bool(movie_plans) or bool(missing_clip_slides)
    apply_steps = 3 if needs_clip_export else 2
    apply_step = 0

    nested_clips: dict[int, dict[ItemId, Path]] = {}
    clips_by_occurrence: dict[str, Path] = {}
    clip_sizes: dict[str, tuple[int, int]] = {}
    clip_crops: dict[int, dict[ItemId, Rect]] = {}
    bare_clips: dict[int, set[ItemId]] = {}
    if operator_clips:
        classes = {c.number: c for c in classify_deck(path, payload=offline_wall_payload(path))}
        for number, clip_path in operator_clips.items():
            movie_ids = sorted(item for item in classes[number].kept if item[0] == "movie")
            if not movie_ids:
                raise ValueError(f"Slide {number}: operator-supplied clip but no movie item found")
            if len(movie_ids) > 1:
                raise ValueError(
                    f"Slide {number}: operator-supplied clip cannot cover {len(movie_ids)} kept "
                    "movies; supply one clip per movie item instead"
                )
            nested_clips.setdefault(number, {})[movie_ids[0]] = clip_path
            try:
                probe_width, probe_height, _fps, _duration = _ffprobe(clip_path)
            except Exception as exc:
                raise ValueError(f"Slide {number}: could not probe operator-supplied clip {clip_path}: {exc}") from exc
            if probe_width <= 0 or probe_height <= 0:
                raise ValueError(f"Slide {number}: operator-supplied clip {clip_path} has zero dimensions")
            clip_sizes[str(clip_path)] = (probe_width, probe_height)

    tmp_src_dir: Path | None = None
    publish_journal: list[_PublishedClip] = []
    stale_src_clips: set[str] = set()
    try:
        if movie_plans:
            tmp_src_dir = out_dir / f".src-{uuid4().hex}"
            guard_out_dir(tmp_src_dir, path)
            source_slides = sorted({plan.source_slide for plan in movie_plans})
            apply_step += 1
            job.set_progress(
                apply_step,
                apply_steps,
                "Exporting video clips",
                detail=(
                    f"{len(movie_plans)} clip(s) from slide(s) {source_slides} — Keynote renders "
                    "each one; this can take a few minutes."
                ),
            )
            job.log(f"Exporting {len(movie_plans)} video clip(s) from slide(s) {source_slides}…")
            clip_results = export_slide_clips(
                path,
                source_slides,
                tmp_src_dir,
                movie_plans=movie_plans,
                layout_template=dsk_template,
                log=job.detail,
            )
            for clip in clip_results:
                if clip.occurrence_id is None:
                    raise ValueError("A compiled clip export returned without an occurrence id")
                clips_by_occurrence[clip.occurrence_id] = clip.path
                nested_clips.setdefault(clip.slide, {})[clip.movie_id] = clip.path
                clip_sizes[str(clip.path)] = (clip.width, clip.height)
                if clip.crop_rect is not None:
                    clip_crops.setdefault(clip.slide, {})[clip.movie_id] = clip.crop_rect
                if clip.bare:
                    bare_clips.setdefault(clip.slide, set()).add(clip.movie_id)
        elif missing_clip_slides:
            tmp_src_dir = out_dir / f".src-{uuid4().hex}"
            guard_out_dir(tmp_src_dir, path)
            apply_step += 1
            job.set_progress(
                apply_step,
                apply_steps,
                "Exporting video clips",
                detail=(
                    f"{len(missing_clip_slides)} clip(s) from slide(s) {missing_clip_slides} — "
                    "Keynote renders each one; this can take a few minutes."
                ),
            )
            job.log(f"Exporting {len(missing_clip_slides)} video clip(s) from slide(s) {missing_clip_slides}…")
            clip_results = export_slide_clips(
                path,
                missing_clip_slides,
                tmp_src_dir,
                per_movie=True,
                include_side=include_side & set(missing_clip_slides),
                layout_template=dsk_template,
                log=job.detail,
            )
            for clip in clip_results:
                nested_clips.setdefault(clip.slide, {})[clip.movie_id] = clip.path
                clip_sizes[str(clip.path)] = (clip.width, clip.height)
                if clip.crop_rect is not None:
                    clip_crops.setdefault(clip.slide, {})[clip.movie_id] = clip.crop_rect
                if clip.bare:
                    bare_clips.setdefault(clip.slide, set()).add(clip.movie_id)

        apply_step += 1
        job.set_progress(apply_step, apply_steps, "Assembling the DSK deck")
        job.log(f"Assembling {out_path.name}…")
        result = assemble_dsk_deck(
            path,
            out_path,
            decisions=decisions,
            reference_deck=reference_deck,
            clips=nested_clips,
            clip_sizes=clip_sizes,
            clip_crops=clip_crops,
            bare_clips=bare_clips,
            compiled_compositions=compiled,
            compiled_clips=clips_by_occurrence,
            text_slide_words=words,
            content_only=content_only,
            layout_template=dsk_template,
            log=job.detail,
        )
        apply_step += 1
        job.set_progress(apply_step, apply_steps, "Finishing outputs")
        clip_order: dict[int, list[ItemId]] = {
            number: list(item_clips) for number, item_clips in result.clips_inserted.items()
        }
        existing_manifest = read_manifest(out_dir, deck=result.path)
        previous_src_clips: set[str] = set()
        for entry in ((existing_manifest or {}).get("slides") or {}).values():
            previous_src_clips.update(str(rel) for rel in entry.get("srcClips") or [])
        published = _publish_generator_clips(
            job,
            result.path,
            src_dir,
            result.clips_inserted,
            result.ordinals,
            publish_journal,
            tmp_src_dir,
            order=clip_order,
        )
        categories = {
            result.ordinals[n]: str(p.get("category") or "")
            for p in included
            for n in [int(p["slide"])]
            if n in result.ordinals
        }
        compiled_by_layout = {comp.layout_slide: comp for comp in compiled}
        composition_metadata: dict[int, dict[str, Any]] = {}
        for source_slide, ordinal in result.ordinals.items():
            comp = compiled_by_layout.get(source_slide)
            if comp is None:
                continue
            actual_media_rects = {
                occurrence_id: result.clip_rects.get(source_slide, {}).get(item_id)
                for item_id, occurrence_id in result.clip_occurrences.get(source_slide, {}).items()
            }
            composition_metadata[ordinal] = {
                "composition_id": comp.id,
                "source_slides": list(comp.source_slides),
                "layout_slide": comp.layout_slide,
                "frame": {
                    "x": comp.output_frame.x,
                    "y": comp.output_frame.y,
                    "width": comp.output_frame.w,
                    "height": comp.output_frame.h,
                },
                "media": [
                    {
                        "occurrence_id": media.occurrence_id,
                        "asset_id": media.asset_id,
                        "source_slide": media.source_slide,
                        "source_item": list(media.source_item),
                        "target_rect": {
                            "x": (actual_media_rects.get(media.occurrence_id) or media.target_rect).x,
                            "y": (actual_media_rects.get(media.occurrence_id) or media.target_rect).y,
                            "width": (actual_media_rects.get(media.occurrence_id) or media.target_rect).w,
                            "height": (actual_media_rects.get(media.occurrence_id) or media.target_rect).h,
                        },
                        "viewport": dict(media.viewport),
                    }
                    for media in comp.media
                ],
            }
        new_manifest_path = write_manifest(
            out_dir,
            result.path,
            [],
            categories=categories,
            source_slides={o: n for n, o in result.ordinals.items()},
            composition_metadata=composition_metadata,
            src_clips=published,
            generator=True,
            existing=existing_manifest,
        )
        new_manifest = json.loads(new_manifest_path.read_text())
        current_src_clips: set[str] = set()
        for entry in (new_manifest.get("slides") or {}).values():
            current_src_clips.update(str(rel) for rel in entry.get("srcClips") or [])
        stale_src_clips = previous_src_clips - current_src_clips
        _discard_publish_backups(publish_journal)
    except Exception:
        _rollback_published_clips(job, publish_journal)
        raise
    finally:
        if tmp_src_dir is not None and tmp_src_dir.is_dir():
            shutil.rmtree(tmp_src_dir, ignore_errors=True)
            job.detail(f"Removed clip export dir {tmp_src_dir}")
    if stale_src_clips:
        _delete_managed_src_clips(job, out_dir, src_dir, stale_src_clips)
    job.log(f"Wrote {result.path.name} ({len(result.slides_kept)} slide(s)).")
    return {
        "phase": "done",
        "path": str(path),
        "deckPath": str(result.path),
        "slidesKept": list(result.slides_kept),
        "ordinals": result.ordinals,
        "clips": published,
        "skipped": proposal.get("skipped") or [],
        "warnings": list(result.warnings),
        "overflows": list(result.overflows),
        "sizeBytes": result.size_bytes,
        "wallS": result.wall_s,
        "pages": pages,
        "contentOnly": content_only,
        "dskTemplate": str(dsk_template) if dsk_template else "",
        **({"review": review, "reviewMode": "v2"} if review is not None else {}),
        **({"exportDir": str(out_dir)} if raw_export else {}),
    }


@dataclass
class _PublishedClip:
    """One clip written by `_publish_generator_clips`. `backup` is the sibling a
    pre-existing managed destination was renamed to before being overwritten, or
    `None` for a destination that did not previously exist."""

    dest: Path
    backup: Path | None


def _publish_generator_clips(
    job: Job,
    deck: Path,
    src_dir: Path,
    clips: Mapping[int, Mapping[ItemId, Path]],
    ordinals: Mapping[int, int],
    journal: list[_PublishedClip],
    movable_root: Path | None,
    *,
    order: Mapping[int, Sequence[ItemId]],
) -> dict[int, list[str]]:
    """Renames/moves each inserted movie's clip into `src_dir` as
    `<DSK stem>.NNN.MM.src.mov` (NNN = DSK ordinal, MM = 1-based movie order within
    the slide, by `order[fw_slide]` -- visual left-to-right order, matching the
    ClipResult and manifest `srcClips` order). Only a clip whose parent resolves to
    `movable_root` (this run's freshly exported intermediates) is moved; every other
    source, including an operator-supplied clip that happens to sit inside `src_dir`,
    is copied so the caller's original file is never touched. `src_dir` is created
    only if absent; a symlinked `src_dir` or destination, or a destination whose
    resolved parent is not `src_dir` itself, is refused, and every destination is
    preflighted before any file is written. A pre-existing managed destination is
    renamed to a `.prev-<uuid>` sibling before being overwritten, so a mid-run
    failure can restore it; each write (and its backup, if any) is appended to
    `journal` as soon as it lands, so the caller can roll back a partial run.
    Returns DSK ordinal -> the ordered `src/<name>` relative paths for
    `manifest.json`'s `srcClips`."""
    if src_dir.is_symlink():
        job.log(f"Refusing to publish clips: {src_dir} is a symlink")
        raise ValueError(f"Refusing to publish through symlinked directory: {src_dir}")
    if not src_dir.is_dir():
        src_dir.mkdir(parents=True)
    src_dir_real = src_dir.resolve()
    movable_root_real = movable_root.resolve() if movable_root is not None else None
    published: dict[int, list[str]] = {}
    plan: list[tuple[Path, Path]] = []
    for fw_slide, movies in clips.items():
        ordinal = ordinals.get(fw_slide)
        if ordinal is None:
            continue
        names: list[str] = []
        for movie_index, movie_id in enumerate(order[fw_slide], start=1):
            src = Path(movies[movie_id])
            name = f"{deck.stem}.{ordinal:03d}.{movie_index:02d}.src.mov"
            dest = src_dir / name
            if dest.is_symlink():
                job.log(f"Refusing to publish clip: {dest} is a symlink")
                raise ValueError(f"Refusing to publish through symlinked destination: {dest}")
            if dest.resolve().parent != src_dir_real:
                job.log(f"Refusing to publish clip: {dest} resolves outside {src_dir_real}")
                raise ValueError(f"Refusing to publish {dest}: resolved parent is not {src_dir_real}")
            if src.resolve() != dest.resolve():
                plan.append((src, dest))
            names.append(f"src/{name}")
        published[ordinal] = names
    for src, dest in plan:
        backup: Path | None = None
        if dest.exists():
            backup = dest.with_name(f"{dest.name}.prev-{uuid4().hex}")
            os.replace(dest, backup)
        try:
            if movable_root_real is not None and src.resolve().parent == movable_root_real:
                os.replace(src, dest)
            else:
                shutil.copy2(src, dest)
        except Exception:
            if backup is not None:
                os.replace(backup, dest)
            raise
        journal.append(_PublishedClip(dest=dest, backup=backup))
    return published


def _rollback_published_clips(job: Job, journal: list[_PublishedClip]) -> None:
    """Undoes every entry in `journal`: unlinks the new write and, if a
    pre-existing destination was backed up, restores it."""
    for entry in reversed(journal):
        try:
            if entry.dest.is_file() or entry.dest.is_symlink():
                entry.dest.unlink()
        except OSError:
            pass
        if entry.backup is not None:
            try:
                os.replace(entry.backup, entry.dest)
            except OSError:
                pass
    if journal:
        job.log(f"Rolled back {len(journal)} clip publish(es) from this failed run")


def _discard_publish_backups(journal: list[_PublishedClip]) -> None:
    """Deletes the backups recorded in `journal` once the run they belong to has
    committed successfully."""
    for entry in journal:
        if entry.backup is not None:
            try:
                entry.backup.unlink()
            except OSError:
                pass


def _delete_managed_src_clips(
    job: Job, out_dir: Path, src_dir: Path, stale_rel_paths: Iterable[str]
) -> None:
    """Deletes `src/<name>` files under `src_dir` named by `stale_rel_paths` (a
    `srcClips` value collected before an overwrite) that are no longer referenced.
    Rejects any entry that is not a bare two-part `src/<name>` path, resolves
    outside `out_dir`, or passes through a symlink, matching the Exporter's
    `src/` cleanup safety rules. Best-effort: called only after the new manifest
    has committed, so a per-file failure is logged and skipped, never raised."""
    out_dir_real = out_dir.resolve()
    if src_dir.is_symlink():
        job.log(f"Skipping src/ cleanup: {src_dir} is a symlink")
        return
    to_delete: list[Path] = []
    seen: set[Path] = set()
    for rel in stale_rel_paths:
        rel_path = Path(str(rel))
        if len(rel_path.parts) != 2 or rel_path.parts[0] != "src" or ".." in rel_path.parts:
            job.log(f"Skipping suspicious srcClips entry {rel!r}")
            continue
        candidate = src_dir / rel_path.parts[1]
        if candidate.is_symlink():
            job.log(f"Skipping symlinked path component for {rel!r}")
            continue
        try:
            candidate_real = candidate.resolve()
            candidate_real.relative_to(out_dir_real)
        except ValueError:
            job.log(f"Skipping {rel!r}: resolves outside the output directory")
            continue
        if candidate.is_file() and candidate_real not in seen:
            seen.add(candidate_real)
            to_delete.append(candidate)
    deleted: list[Path] = []
    for f in to_delete:
        try:
            f.unlink()
            deleted.append(f)
        except OSError as exc:
            job.log(f"Failed to delete stale Generator clip {f}: {exc}")
    if deleted:
        job.log(
            f"Deleted {len(deleted)} orphaned Generator clip(s): "
            + ", ".join(f.name for f in deleted)
        )


def _dsk_export_action(category: str) -> str:
    return "clip" if category in {"movie", "mixed"} else "stage"


def _run_dsk_export_propose(
    job: Job, path: Path, slide_range: frozenset[int] | None, export_dir: str = ""
) -> dict[str, Any]:
    job.log(f"Reading {path.name} for the DSK exporter…")
    payload = offline_wall_payload(path)
    _assert_range_within_deck(path.name, int(payload.get("slideCount") or 0), slide_range)
    all_numbers = [int(s["number"]) for s in payload["slides"]]
    numbers = sorted(expand_slide_range(slide_range) or set(all_numbers))
    wall = (payload.get("slideWidth"), payload.get("slideHeight"))
    is_stage_deck = wall in {(1920.0, 1080.0), (1920, 1080)}
    is_fw_deck = is_lw_wall(float(wall[0] or 0), float(wall[1] or 0))
    classes = {c.number: c for c in classify_deck(path, payload=payload)}
    thumbs = _dsk_preview_thumbs(job, path, payload)
    thumb_dir = wall_thumb_dir(deck_digest(path))
    pages: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for number in numbers:
        cls = classes.get(number)
        if cls is None:
            continue
        if cls.category == "empty":
            skipped.append({"slide": number, "reason": "empty"})
            continue
        action = _dsk_export_action(cls.category)
        page = {
            "slide": number,
            "thumb": thumbs.get(number),
            "category": cls.category,
            "buildCount": cls.build_count,
            "movieCount": cls.movie_count,
            "isText": bool(cls.is_text),
            "skipReason": None,
            "needsClip": action == "clip",
        }
        page["decision"] = {
            "slide": number,
            "include": True,
            "action": action,
            "anchor": "auto",
            "keepSide": False,
            "clip": None,
        }
        pages.append(page)
    return {
        "phase": "review",
        "path": str(path),
        "isStageDeck": is_stage_deck,
        "isFwDeck": is_fw_deck,
        "slideRange": sorted(slide_range) if slide_range else None,
        "thumbDir": str(thumb_dir),
        "pages": pages,
        "skipped": skipped,
        **({"exportDir": export_dir} if export_dir else {}),
    }


def _run_dsk_export_apply(job: Job, proposal: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(proposal.get("path") or "")).expanduser()
    pages = proposal.get("pages") or []
    included = [p for p in pages if (p.get("decision") or {}).get("include")]
    if not included:
        raise ValueError("No slides selected to export; check Include on at least one page.")
    if not proposal.get("isStageDeck"):
        raise ValueError(
            f"{path.name} is not a 1920x1080 DSK deck; stage PNG export needs a DSK-sized deck."
        )
    deck_dir = path.parent
    raw_export = str(proposal.get("exportDir") or "").strip()
    if raw_export:
        try:
            out_dir = validate_export_dir(raw_export)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    else:
        out_dir = deck_dir
    src_dir = deck_dir / "src"
    categories = {int(p["slide"]): str(p.get("category") or "") for p in included}
    clip_slides = sorted(
        int(p["slide"]) for p in included if _dsk_export_action(categories[int(p["slide"])]) == "clip"
    )
    stage_slides = sorted(int(p["slide"]) for p in included if int(p["slide"]) not in set(clip_slides))
    existing = read_manifest(deck_dir, deck=path)

    clips: dict[int, Path] = {}
    if clip_slides:
        job.log(f"Exporting clip(s) for movie slide(s) {clip_slides} to {out_dir}…")
        for clip in export_dsk_slide_clips(path, clip_slides, out_dir, log=job.log):
            clips[clip.slide] = clip.path
        job.log(f"Exported {len(clip_slides)} clip(s).")

    assets: list = []
    if stage_slides:
        job.log(f"Exporting stage PNGs for slide(s) {stage_slides} to {out_dir}…")
        expected_stage_counts = stage_counts(path, stage_slides)
        assets = export_stage_pngs(
            path,
            stage_slides,
            out_dir,
            expected_stage_counts=expected_stage_counts,
            categories=categories,
            clips=clips,
            write_manifest=False,
            log=job.log,
        )
        job.log(f"Exported {len(assets)} stage PNG(s).")
    deck_dir_real = deck_dir.resolve()
    out_dir_real = out_dir.resolve()
    to_delete: list[Path] = []
    seen: set[Path] = set()
    if src_dir.is_symlink():
        job.log(f"Skipping src/ cleanup: {src_dir} is a symlink")
    else:
        for entry in ((existing or {}).get("slides") or {}).values():
            for rel in entry.get("srcClips") or []:
                rel_path = Path(str(rel))
                if len(rel_path.parts) != 2 or rel_path.parts[0] != "src" or ".." in rel_path.parts:
                    job.log(f"Skipping suspicious srcClips entry {rel!r}")
                    continue
                candidate = src_dir / rel_path.parts[1]
                if candidate.is_symlink():
                    job.log(f"Skipping symlinked path component for {rel!r}")
                    continue
                try:
                    candidate_real = candidate.resolve()
                    candidate_real.relative_to(deck_dir_real)
                except ValueError:
                    job.log(f"Skipping {rel!r}: resolves outside the deck directory")
                    continue
                if candidate.is_file() and candidate_real not in seen:
                    seen.add(candidate_real)
                    to_delete.append(candidate)
    same_dir = out_dir_real == deck_dir_real
    write_manifest(
        out_dir,
        path,
        assets,
        categories=categories,
        clips=clips,
        existing=existing if same_dir else None,
        drop_src=True,
    )
    if not same_dir:
        write_manifest(
            deck_dir, path, [], categories=categories, existing=existing, drop_src=True
        )
    if to_delete:
        deleted: list[Path] = []
        for f in to_delete:
            try:
                f.unlink()
                deleted.append(f)
            except OSError as exc:
                job.log(f"Could not delete Generator intermediate clip {f}: {exc}")
        if deleted:
            job.log(
                f"Deleted {len(deleted)} Generator intermediate clip(s): "
                + ", ".join(f.name for f in deleted)
            )

    sequence = sorted(
        [a.path.name for a in assets] + [c.name for c in clips.values()],
    )
    return {
        "phase": "done",
        "path": str(path),
        "pngDir": str(out_dir),
        "pngs": [a.path.name for a in assets],
        "clips": {n: c.name for n, c in sorted(clips.items())},
        "sequence": sequence,
        "skipped": proposal.get("skipped") or [],
        "exportedClips": clip_slides,
        **({"exportDir": str(out_dir)} if raw_export else {}),
    }


_UNCLOSED_LOCK = threading.Lock()
_unclosed_outputs: list[str] = []


def _unclosed_output_message() -> str | None:
    """Set when an offline-hides fallback may have left an output open in Keynote; only a
    dashboard restart clears it."""
    with _UNCLOSED_LOCK:
        names = ", ".join(dict.fromkeys(Path(path).name for path in _unclosed_outputs))
    return f"Close {names} in Keynote, then restart the dashboard." if names else None


def _offline_hides_field(raw: str | None) -> str | None:
    """The dashboard may only switch offline hides off; blank keeps the env default."""
    value = (raw or "").strip().lower()
    if not value:
        return None
    if value != "off":
        raise HTTPException(400, f"offline_hides must be blank or 'off', not {raw!r}.")
    return value


def _run_resize_propose(
    job: Job,
    path: Path,
    template: Path,
    slide_range: frozenset[int] | None,
    export: bool,
    keep_side_panels: bool = False,
    validate: bool = True,
    export_dir: str = "",
    offline_hides: str | None = None,
) -> dict[str, Any]:
    typed = slide_range
    label = format_slide_range(slide_range)
    scope = f"slide {label}" if label else "every slide"
    job.log(f"Reading {path.name} and {template.name} to propose framings ({scope})…")
    full_wall = acquire_wall_payload(
        path, slide_range=None, mode=offline_read_mode(), say=job.log
    )
    if slide_range:
        _assert_range_within_navigator(path.name, full_wall, slide_range)
    template_data = inspect_keynote(template)
    numbering = ""
    if slide_range:
        slide_range = to_document_range(full_wall, slide_range)
        numbering = navigator_numbering(full_wall)
        if slide_range != expand_slide_range(typed):
            job.log(
                f"Range {format_slide_range(typed)} is Keynote's numbering; "
                f"that is document position {format_slide_range(slide_range)}."
            )
    if numbering:
        job.log(numbering)
    if slide_range:
        wall = {
            **full_wall,
            "slides": copy.deepcopy(
                [
                    slide
                    for slide in full_wall["slides"]
                    if slide["number"] in (slide_range or frozenset())
                ]
            ),
        }
    else:
        wall = full_wall
    _assert_range_within_deck(path.name, int(wall.get("slideCount") or 0), slide_range)
    full_context = full_wall
    settings = load_settings()
    reuse = FramingReuse()
    if settings["reusePairings"]:
        record = load_framings(path, template)
        reuse = reuse_framings(
            record,
            deck_slide_digests(full_context),
            deck_digest(template),
            template_framing_digests(template_data),
        )
        if reuse.carried:
            job.log(
                f"Carried {reuse.carried} earlier framing decision(s) onto this deck"
                + (
                    f", dropped {reuse.dropped} that could not be matched to the current "
                    "page or template framing"
                    if reuse.dropped
                    else ""
                )
                + "."
            )
        elif reuse.dropped and reuse.template_changed:
            job.log(
                f"The template changed, so {reuse.dropped} saved framing decision(s) "
                "could not be matched to the current template framing and are being re-offered."
            )
        if reuse.unpinned:
            job.log(
                f"Kept the side-content choice on {reuse.unpinned} page(s) whose pinned "
                "framing could not be matched; those framings are being re-offered."
            )
        if reuse.resurfaced:
            job.log(
                f"The template changed, so {len(reuse.resurfaced)} page(s) you deferred are "
                "worth another look: " + ", ".join(str(i + 1) for i in reuse.resurfaced[:10]) + "."
            )
    proposal = propose_framings(
        path,
        template,
        slide_range=slide_range,
        wall_payload=wall,
        full_wall_payload=full_context,
        template_payload=template_data,
        keep_side_panels=keep_side_panels,
        side_content_slides=reuse.side_content_slides(),
        log=job.log,
    )
    decisions = {index: d.as_dict() for index, d in reuse.decisions.items()}
    for page in proposal["pages"]:
        saved = decisions.get(page["index"])
        page["decision"] = saved or {
            "wallIndex": page["index"],
            "state": DEFERRED if page["noUsableFraming"] else AUTO,
            "templateSlide": None,
        }
        page["resurfaced"] = page["index"] in set(reuse.resurfaced)
    resolved_export_dir = str(resolve_export_destination(export_dir or None))
    return {
        "phase": "framing",
        "path": str(path),
        "templatePath": str(template),
        "includeLists": keep_side_panels,
        "validate": validate,
        "export": export,
        **({"exportDir": export_dir} if export_dir else {}),
        **({"offlineHides": offline_hides} if offline_hides else {}),
        "resolvedExportDir": resolved_export_dir,
        "proposalExportDir": resolved_export_dir,
        **proposal,
        "slideRange": sorted(slide_range) if slide_range else None,
        "slideRangeTyped": sorted(expand_slide_range(typed) or []) or None,
        "numberingNote": numbering or proposal.get("numberingNote") or "",
        "templateChanged": reuse.template_changed,
        "resurfaced": reuse.resurfaced,
    }


def _run_resize(
    job: Job,
    path: Path,
    template: Path,
    slide_range: frozenset[int] | None,
    export: bool,
    keep_side_panels: bool = False,
    framing_overrides: dict[int, int] | None = None,
    side_content_slides: set[int] | None = None,
    validate: bool = True,
    offline_hides: str | None = None,
) -> dict[str, Any]:
    dest_dir = default_output_root() / ".resize" / job.name
    resolved_export_dir = (job.result or {}).get("resolvedExportDir")
    export_root = Path(resolved_export_dir) if resolved_export_dir else export_destination(job)
    dest = export_root / f"{path.stem}_CG.key"
    export_dir = dest_dir / "previews" if export else None
    label = format_slide_range(slide_range)
    scope = f"slide {label}" if label else "every slide"
    job.log(f"Remapping {path.name} → 1920×1080 ({scope})…")
    job.log(f"CG template (16:9 layouts copied onto the wall copy): {template.name}.")
    if not keep_side_panels and not side_content_slides:
        job.log("Side-panel content dropped (whitelist a slide in the framing review to keep it).")
    if message := _unclosed_output_message():
        raise RuntimeError(message)
    ensure_export_dir(dest.parent)
    if offline_hides:
        job.log("Offline hides switched off for this run.")
    try:
        info = remap_and_inspect(
            path,
            dest,
            template=template,
            slide_range=slide_range,
            keep_side_panels=keep_side_panels,
            export_dir=export_dir,
            framing_overrides=framing_overrides,
            side_content_slides=side_content_slides,
            validate=validate,
            offline_hides=offline_hides,
            log=job.log,
        )
    except OfflineHidesAborted as exc:
        needs_fresh_output = bool(getattr(exc, "needs_fresh_output", False))
        if needs_fresh_output:
            with _UNCLOSED_LOCK:
                _unclosed_outputs.append(str(dest))
        job.result = {
            **(job.result or {}),
            "offlineHides": "off",
            "offlineHidesAborted": {
                "reason": exc.reason,
                "detail": getattr(exc, "detail", ""),
                "needsFreshOutput": needs_fresh_output,
                "outputPath": str(dest),
            },
        }
        raise
    inspect = info.get("inspect") or {}
    names = list(info.get("previewFiles") or [])
    if export_dir and not names:
        names = preview_names(export_dir)
    if export_dir and names:
        job.log(f"Exported {len(names)} CG preview PNG(s).")
    payload = info.get("payload") or {
        "path": str(dest),
        "slideWidth": inspect.get("slideWidth"),
        "slideHeight": inspect.get("slideHeight"),
        "slides": [],
    }
    flags = validate_inspect(payload, location_prefix=dest.name) if validate else []
    counts = info.get("counts") or {}
    applied = info.get("applied")
    missed = info.get("missed")
    job.log(f"Wrote {dest.name}: applied {applied}, missed {missed}.")
    score = info.get("templateScore") or info.get("goldScore") or {}
    return {
        "phase": "resized",
        "path": str(path),
        "outputDir": str(dest_dir),
        "destPath": str(dest),
        **_carried_export_dir(job),
        "templatePath": str(template),
        "slideWidth": inspect.get("slideWidth") or info.get("width"),
        "slideHeight": inspect.get("slideHeight") or info.get("height"),
        "slideCount": inspect.get("slideCount"),
        "exported": inspect.get("exported"),
        "previews": {"lw": str(export_dir) if export_dir else None, "dsk": None},
        "previewFiles": {"lw": names, "dsk": []},
        "previewDir": str(export_dir) if export_dir else None,
        "previewFileNames": names,
        "recipe": info.get("recipe"),
        "counts": counts,
        "applied": applied,
        "missed": missed,
        "includeLists": keep_side_panels,
        "validate": validate,
        "templateScore": score,
        "flags": serialize_flags(flags),
        "framingReport": info.get("framingReport") or [],
        "fittedSlides": info.get("fittedSlides") or [],
        "offFrame": info.get("offFrame") or [],
        "placements": info.get("placements") or [],
        "placementSource": info.get("placementSource") or "",
        "skippedSlidesLeftAlone": info.get("skippedSlidesLeftAlone") or [],
    }


app = create_app()

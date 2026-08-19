from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sermon_slides.diff_keynotes import compare_inspects
from sermon_slides.inspect import diff_work_dir, inspect_keynote, preview_pngs
from sermon_slides.paths import find_repo_root
from sermon_slides.pipeline import generate
from sermon_slides.slide_map import load_masters
from sermon_slides.validate import validate_inspect
from sermon_slides.web.jobs import Job, JobRunner, preview_names, serialize_flags

RUNNER = JobRunner()
ROOT = find_repo_root()
UPLOADS = ROOT / "output" / ".uploads"
DASHBOARD_DIST = ROOT / "dashboard" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Sermon slides dashboard")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/templates")
    def templates() -> dict:
        masters = load_masters()
        dsk = masters.get("dsk") or {}
        rel = dsk.get("template") or ""
        return {
            "dskTemplate": rel,
            "dskTemplatePath": str(ROOT / rel) if rel else "",
        }

    @app.post("/api/choose-file")
    def choose_file(prompt: str = Form("Select a Keynote file")) -> dict:
        script = (
            f'set theFile to choose file with prompt "{_as_escape(prompt)}"\n'
            "POSIX path of theFile"
        )
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

    @app.post("/api/reveal")
    def reveal(path: str = Form(...)) -> dict:
        target = Path(path).expanduser()
        if not target.exists():
            raise HTTPException(404, f"Not found: {path}")
        subprocess.run(["open", "-R", str(target)], check=False)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs(kind: str | None = None) -> dict:
        return {"jobs": [j.to_dict() for j in RUNNER.list(kind)]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        return job.to_dict()

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
        return FileResponse(path, media_type="image/png")

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
    async def generate_endpoint(files: list[UploadFile] = File(...)) -> dict:
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
            job = RUNNER.submit("generate", lambda j, p=path: _run_generate(j, p))
            jobs.append(job.to_dict())
        return {"jobs": jobs}

    @app.post("/api/diff")
    def diff_endpoint(
        left_path: str = Form(...),
        right_path: str = Form(...),
        left_label: str = Form("LW"),
        right_label: str = Form("Other"),
    ) -> dict:
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        if not left.exists() or not right.exists():
            raise HTTPException(400, "Both Keynote paths must exist")
        job = RUNNER.submit(
            "diff",
            lambda j, a=left, b=right, la=left_label, lb=right_label: _run_diff(j, a, b, la, lb),
        )
        return job.to_dict()

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
        return FileResponse(_safe_file(Path(folder), filename), media_type="image/png")

    @app.post("/api/validate-keynote")
    def validate_keynote(
        path: str = Form(...),
        export: str = Form("false"),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        job = RUNNER.submit(
            "inspect",
            lambda j, p=key, ex=do_export, rf=range_from, rt=range_to: _run_inspect(j, p, ex, rf, rt),
        )
        return job.to_dict()

    @app.post("/api/dsk")
    def dsk_stub() -> JSONResponse:
        return JSONResponse(
            {"detail": "DSK generation is not implemented yet. Validation still runs on the chosen files."},
            status_code=501,
        )

    @app.post("/api/resize")
    def resize_stub() -> JSONResponse:
        return JSONResponse(
            {
                "detail": "CG resize is not implemented yet. Validation still runs on the chosen Keynote."
            },
            status_code=501,
        )

    if DASHBOARD_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(DASHBOARD_DIST), html=True), name="ui")

    return app


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


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


def _run_generate(job: Job, docx: Path) -> dict[str, Any]:
    job.log(f"Generating from {docx.name}…")
    result = generate(docx)
    lw_prev = result.output_dir / "previews" / "lw"
    dsk_prev = result.output_dir / "previews" / "dsk"
    job.log(f"Output {result.output_dir}")
    return {
        "stem": docx.stem.replace(" ", "_"),
        "source": str(docx),
        "outputDir": str(result.output_dir),
        "lwKey": str(result.lw_key) if result.lw_key else None,
        "dskKey": str(result.dsk_key) if result.dsk_key else None,
        "cuedDocx": str(result.cued_docx) if result.cued_docx else None,
        "reviewPath": str(result.review_path) if result.review_path else None,
        "previews": {"lw": str(lw_prev), "dsk": str(dsk_prev)},
        "previewFiles": {
            "lw": preview_names(lw_prev),
            "dsk": preview_names(dsk_prev),
        },
        "flags": serialize_flags(result.flags),
        "lwCount": len(result.lw_slides),
        "dskCount": len(result.dsk_slides),
    }


def _run_diff(job: Job, left: Path, right: Path, left_label: str, right_label: str) -> dict[str, Any]:
    work = diff_work_dir(job.id)
    left_dir = work / "left"
    right_dir = work / "right"
    heat_dir = work / "heat"
    job.log(f"Inspecting {left.name} (read-only)…")
    left_payload = inspect_keynote(left, export_dir=left_dir)
    job.log(f"Inspecting {right.name} (read-only)…")
    right_payload = inspect_keynote(right, export_dir=right_dir)
    job.log("Comparing text and pixels…")
    compared = compare_inspects(
        left_payload,
        right_payload,
        left_dir,
        right_dir,
        heat_dir,
        left_label=left_label,
        right_label=right_label,
    )
    flags = compared.pop("flags")
    pairs = compared["pairs"]
    return {
        "leftPath": str(left),
        "rightPath": str(right),
        "leftLabel": left_label,
        "rightLabel": right_label,
        "leftPreviews": str(left_dir),
        "rightPreviews": str(right_dir),
        "heatDir": str(heat_dir),
        "leftPngs": [p.name for p in preview_pngs(left_dir)],
        "rightPngs": [p.name for p in preview_pngs(right_dir)],
        "heatPngs": [p.name for p in preview_pngs(heat_dir)],
        "summary": compared,
        "pairs": pairs,
        "flags": serialize_flags(flags),
    }


def _run_inspect(
    job: Job,
    path: Path,
    export: bool,
    range_from: int | None,
    range_to: int | None,
) -> dict[str, Any]:
    export_dir = None
    if export:
        export_dir = ROOT / "output" / ".inspect" / job.id
    slide_range = None
    if range_from is not None and range_to is not None:
        slide_range = (range_from, range_to)
    job.log(f"Inspecting {path.name} (read-only, no save)…")
    payload = inspect_keynote(path, export_dir=export_dir, slide_range=slide_range)
    flags = validate_inspect(payload, location_prefix=path.name)
    preview_dir = str(export_dir) if export_dir else None
    names = preview_names(export_dir) if export_dir else []
    return {
        "path": str(path),
        "slideWidth": payload.get("slideWidth"),
        "slideHeight": payload.get("slideHeight"),
        "slideCount": payload.get("slideCount"),
        "exported": payload.get("exported"),
        "previews": {"lw": preview_dir, "dsk": None} if preview_dir else None,
        "previewFiles": {"lw": names, "dsk": []} if names else {"lw": [], "dsk": []},
        "previewDir": preview_dir,
        "previewFileNames": names,
        "flags": serialize_flags(flags),
    }


app = create_app()

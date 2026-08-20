from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from obed_edom.diff_keynotes import compare_inspects, slots_from_pairs
from obed_edom.inspect import diff_work_dir, inspect_keynote, preview_pngs
from obed_edom.paths import find_repo_root
from obed_edom.resolve_drop import resolve_dropped_keynote
from obed_edom.pipeline import generate
from obed_edom.slide_map import load_masters
from obed_edom.validate import validate_inspect
from obed_edom.web.jobs import Job, JobRunner, preview_names, serialize_flags, visual_result

RUNNER = JobRunner()
ROOT = find_repo_root()
UPLOADS = ROOT / "output" / ".uploads"
DASHBOARD_DIST = ROOT / "dashboard" / "dist"


class JobPatch(BaseModel):
    result: dict[str, Any]


class RelocateBody(BaseModel):
    folder: str | None = None
    path: str | None = None
    leftPath: str | None = None
    rightPath: str | None = None


class DiffSlotsBody(BaseModel):
    slots: list[dict[str, Any]] | None = None
    pairs: list[dict[str, Any]] | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Obed-Edom dashboard")
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

    @app.post("/api/choose-folder")
    def choose_folder(prompt: str = Form("Select the output folder")) -> dict:
        script = (
            f'set theFolder to choose folder with prompt "{_as_escape(prompt)}"\n'
            "POSIX path of theFolder"
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
        path = (proc.stdout or "").strip().rstrip("/")
        if not path:
            raise HTTPException(400, "No folder selected")
        return {"path": path, "name": Path(path).name}

    @app.post("/api/resolve-drop")
    def resolve_drop(name: str = Form(...), size: int | None = Form(None)) -> dict:
        found = resolve_dropped_keynote(name, size)
        if not found:
            raise HTTPException(
                404,
                "Could not resolve that drop to a path on this Mac. Use Choose on this Mac.",
            )
        return {"path": str(found), "name": found.name}

    @app.post("/api/reveal")
    def reveal(path: str = Form(...)) -> dict:
        target = Path(path).expanduser()
        if not target.exists():
            raise HTTPException(404, f"Not found: {path}")
        subprocess.run(["open", "-R", str(target)], check=False)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs(kind: str | None = None, feature: str | None = None) -> dict:
        return {"jobs": [RUNNER.public_dict(j) for j in RUNNER.list(kind, feature)]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = RUNNER.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(job)

    @app.patch("/api/jobs/{job_id}")
    def patch_job(job_id: str, payload: JobPatch) -> dict:
        job = RUNNER.update_result(job_id, payload.result)
        if not job:
            raise HTTPException(404, "Unknown job")
        return RUNNER.public_dict(job)

    @app.post("/api/jobs/{job_id}/relocate")
    def relocate_job(job_id: str, payload: RelocateBody) -> dict:
        try:
            job = RUNNER.relocate(
                job_id,
                folder=payload.folder,
                path=payload.path,
                left_path=payload.leftPath,
                right_path=payload.rightPath,
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
            job = RUNNER.submit("generate", lambda j, p=path: _run_generate(j, p), feature="generate")
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
            feature="diff",
        )
        return job.to_dict()

    @app.post("/api/visual")
    def visual_endpoint(
        left_path: str = Form(...),
        right_path: str = Form(...),
    ) -> dict:
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        if not left.is_dir() or not right.is_dir():
            raise HTTPException(400, "Both paths must be folders of preview PNGs")
        job = RUNNER.submit(
            "visual",
            lambda j, a=left, b=right: visual_result(a, b),
            feature="visual",
        )
        return job.to_dict()

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
        return FileResponse(_safe_file(Path(folder), filename), media_type="image/png")

    @app.post("/api/validate-keynote")
    def validate_keynote(
        path: str = Form(...),
        export: str = Form("false"),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        feature: str = Form("inspect"),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        tag = feature if feature in {"dsk", "resize", "inspect", "dsk-aux", "check"} else "inspect"
        job = RUNNER.submit(
            "inspect",
            lambda j, p=key, ex=do_export, rf=range_from, rt=range_to: _run_inspect(j, p, ex, rf, rt),
            feature=tag,
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
    left_n = len(preview_pngs(left_dir))
    if left_n:
        job.log(f"Exported {left_n} LW preview PNG(s).")
    else:
        job.log(left_payload.get("exportError") or "LW preview export produced no PNGs.")
    job.log(f"Inspecting {right.name} (read-only)…")
    right_payload = inspect_keynote(right, export_dir=right_dir)
    right_n = len(preview_pngs(right_dir))
    if right_n:
        job.log(f"Exported {right_n} {right_label} preview PNG(s).")
    else:
        job.log(right_payload.get("exportError") or f"{right_label} preview export produced no PNGs.")
    job.log("Matching slides…")
    compared = compare_inspects(
        left_payload,
        right_payload,
        left_dir,
        right_dir,
        heat_dir,
        left_label=left_label,
        right_label=right_label,
        check=False,
    )
    inspect_left = work / "left-inspect.json"
    inspect_right = work / "right-inspect.json"
    inspect_left.write_text(json.dumps(left_payload), encoding="utf-8")
    inspect_right.write_text(json.dumps(right_payload), encoding="utf-8")
    flags = compared.pop("flags")
    pairs = compared["pairs"]
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    return {
        "leftPath": str(left),
        "rightPath": str(right),
        "leftLabel": left_label,
        "rightLabel": right_label,
        "phase": "match",
        "sameType": compared.get("sameType"),
        "leftPreviews": str(left_dir),
        "rightPreviews": str(right_dir),
        "heatDir": str(heat_dir),
        "leftInspect": str(inspect_left),
        "rightInspect": str(inspect_right),
        "leftPngs": [p.name for p in preview_pngs(left_dir)],
        "rightPngs": [p.name for p in preview_pngs(right_dir)],
        "heatPngs": [p.name for p in preview_pngs(heat_dir)],
        "leftCatalog": compared.get("leftCatalog") or [],
        "rightCatalog": compared.get("rightCatalog") or [],
        "summary": compared,
        "pairs": pairs,
        "flags": serialize_flags(flags),
    }


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
    )
    flags = compared.pop("flags")
    pairs = compared["pairs"]
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    result.update(
        {
            "phase": "checked",
            "sameType": compared.get("sameType"),
            "heatPngs": [p.name for p in preview_pngs(Path(result["heatDir"]))],
            "leftCatalog": compared.get("leftCatalog") or result.get("leftCatalog") or [],
            "rightCatalog": compared.get("rightCatalog") or result.get("rightCatalog") or [],
            "summary": compared,
            "pairs": pairs,
            "flags": serialize_flags(flags),
        }
    )
    return result


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
    names = preview_names(export_dir) if export_dir else []
    if export_dir and names:
        job.log(f"Exported {len(names)} preview PNG(s).")
    elif export_dir:
        job.log(payload.get("exportError") or "Preview export produced no PNGs.")
    flags = validate_inspect(payload, location_prefix=path.name)
    preview_dir = str(export_dir) if export_dir else None
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

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from obed_edom.baseline import (
    deck_slide_digests,
    delete_pairing,
    folder_digests,
    load_pairing,
    pair_index_gaps,
    reuse_slots,
    save_pairing,
    slot_dict,
)
from obed_edom.diff_keynotes import compare_inspects, realign_gaps, slots_from_pairs
from obed_edom.inspect import diff_work_dir, inspect_keynote, preview_inspect, preview_media_type, preview_pngs
from obed_edom.map_remap import MVP_MAP_SLIDE, format_slide_range, resolve_slides
from obed_edom.paths import find_repo_root
from obed_edom.resolve_drop import resolve_dropped_keynote
from obed_edom.pipeline import generate
from obed_edom.remap_keynote import remap_and_inspect
from obed_edom.settings import load_settings, save_settings
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


class SettingsBody(BaseModel):
    reuseThreshold: float | None = None
    reusePairings: bool | None = None
    reusePreviews: bool | None = None


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
        return save_settings(current)

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
        return FileResponse(path, media_type=preview_media_type(path))

    @app.get("/api/jobs/{job_id}/evidence/{filename}")
    def job_evidence(job_id: str, filename: str):
        """Cropped pictures of the object a geometry finding is about."""
        job = RUNNER.get(job_id)
        folder = (job.result or {}).get("evidenceDir") if job else None
        if not folder:
            raise HTTPException(404, "No evidence")
        path = _safe_file(Path(folder), filename)
        return FileResponse(path, media_type=preview_media_type(path))

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
    ) -> dict:
        lw_path = Path(lw_template.strip()).expanduser() if lw_template.strip() else None
        dsk_path = Path(dsk_template.strip()).expanduser() if dsk_template.strip() else None
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
            )
            jobs.append(job.to_dict())
        return {"jobs": jobs}

    @app.post("/api/diff")
    def diff_endpoint(
        left_path: str = Form(...),
        right_path: str = Form(...),
        left_label: str = Form("LW"),
        right_label: str = Form("Other"),
        fresh: str = Form("false"),
    ) -> dict:
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        if not left.exists() or not right.exists():
            raise HTTPException(400, "Both Keynote paths must exist")
        start_fresh = _form_flag(fresh)
        job = RUNNER.submit(
            "diff",
            lambda j, a=left, b=right, la=left_label, lb=right_label, fr=start_fresh: _run_diff(
                j, a, b, la, lb, fresh=fr
            ),
            feature="diff",
        )
        return job.to_dict()

    @app.post("/api/visual")
    def visual_endpoint(
        left_path: str = Form(...),
        right_path: str = Form(...),
        fresh: str = Form("false"),
    ) -> dict:
        left = Path(left_path).expanduser()
        right = Path(right_path).expanduser()
        if not left.is_dir() or not right.is_dir():
            raise HTTPException(400, "Both paths must be folders of preview images")
        start_fresh = _form_flag(fresh)
        job = RUNNER.submit(
            "visual",
            lambda j, a=left, b=right, fr=start_fresh: _run_visual(j, a, b, fresh=fr),
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
        _remember_pairing(job, result, source="operator", force=True)
        updated = RUNNER.update_result(job_id, result)
        return RUNNER.public_dict(updated) if updated else result

    @app.post("/api/visual/{job_id}/slots")
    def save_visual_slots(job_id: str, payload: DiffSlotsBody) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if job.status == "running":
            raise HTTPException(409, "Job is already running")
        result = dict(job.result)
        if payload.slots is None and payload.pairs is None:
            raise HTTPException(400, "slots or pairs required")
        if payload.slots is not None:
            result["slots"] = payload.slots
            rebuilt = visual_result(
                Path(str(result.get("leftPath") or "")),
                Path(str(result.get("rightPath") or "")),
                str(result.get("leftLabel") or "LW"),
                str(result.get("rightLabel") or "DSK"),
                slots=payload.slots,
            )
            result["pairs"] = rebuilt["pairs"]
            result["leftCatalog"] = rebuilt.get("leftCatalog") or result.get("leftCatalog")
            result["rightCatalog"] = rebuilt.get("rightCatalog") or result.get("rightCatalog")
        else:
            result["pairs"] = payload.pairs
            result["slots"] = _slots_from_pairs(payload.pairs or [])
        result["phase"] = "visual"
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

    @app.post("/api/visual/{job_id}/check")
    def start_visual_check(job_id: str, payload: DiffSlotsBody = Body(default=DiffSlotsBody())) -> dict:
        job = RUNNER.get(job_id)
        if not job or not job.result:
            raise HTTPException(404, "Unknown job")
        if payload and (payload.slots is not None or payload.pairs is not None):
            save_visual_slots(job_id, payload)
        try:
            updated = RUNNER.rerun(job_id, _run_visual_check)
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
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        tag = feature if feature in {"dsk", "resize", "inspect", "dsk-aux", "check"} else "inspect"
        try:
            sel = resolve_slides(spec=slides or None, range_from=range_from, range_to=range_to)
        except ValueError as err:
            raise HTTPException(400, str(err))
        job = RUNNER.submit(
            "inspect",
            lambda j, p=key, ex=do_export, sl=sel: _run_inspect(j, p, ex, sl),
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
    def resize_keynote(
        path: str = Form(...),
        template_path: str = Form(""),
        gold_path: str = Form(""),
        range_from: int | None = Form(None),
        range_to: int | None = Form(None),
        slides: str = Form(""),
        export: str = Form("true"),
        include_lists: str = Form("false"),
    ) -> dict:
        key = Path(path).expanduser()
        if not key.exists():
            raise HTTPException(400, f"Not found: {path}")
        raw_template = (template_path or gold_path).strip()
        if not raw_template:
            raise HTTPException(400, "CG template .key is required.")
        template = Path(raw_template).expanduser()
        if not template.exists():
            raise HTTPException(400, f"CG template not found: {raw_template}")
        do_export = export.lower() in {"1", "true", "yes", "on"}
        do_lists = include_lists.lower() in {"1", "true", "yes", "on"}
        try:
            sel = resolve_slides(
                spec=slides or None,
                range_from=range_from,
                range_to=range_to,
                default=(MVP_MAP_SLIDE, MVP_MAP_SLIDE),
            ) or frozenset({MVP_MAP_SLIDE})
        except ValueError as err:
            raise HTTPException(400, str(err))
        job = RUNNER.submit(
            "resize",
            lambda j, p=key, t=template, sl=sel, ex=do_export, lists=do_lists: _run_resize(
                j, p, t, sl, ex, lists
            ),
            feature="resize",
        )
        return job.to_dict()

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
        only_provided=True,
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
    }


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
    kind = "visual" if job.feature == "visual" or job.kind == "visual" else "diff"
    slots = result.get("slots") or _slots_from_pairs(result.get("pairs") or [])
    save_pairing(
        kind,
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
    if "export" in timing:
        parts.append(f"export {timing['export']:.1f}s")
    extra = f" ({', '.join(parts)})" if parts else ""
    job.log(f"Inspected {name}{extra}.")


def _run_diff(
    job: Job,
    left: Path,
    right: Path,
    left_label: str,
    right_label: str,
    *,
    fresh: bool = False,
) -> dict[str, Any]:
    settings = load_settings()
    work = diff_work_dir(job.id)
    heat_dir = work / "heat"
    heat_dir.mkdir(parents=True, exist_ok=True)
    if fresh:
        delete_pairing("diff", left, right)

    job.log(f"Inspecting {left.name} (read-only)…")
    left_payload = inspect_keynote(left, export_dir=work / "left")
    _log_inspect(job, left.name, left_payload)
    left_dir = Path(left_payload.get("previewDir") or work / "left")
    left_n = len(preview_pngs(left_dir))
    if left_n:
        job.log(f"Exported {left_n} LW preview PNG(s).")
    else:
        job.log(left_payload.get("exportError") or "LW preview export produced no PNGs.")

    job.log(f"Inspecting {right.name} (read-only)…")
    right_payload = inspect_keynote(right, export_dir=work / "right")
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
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    result = {
        "leftPath": str(left),
        "rightPath": str(right),
        "leftLabel": left_label,
        "rightLabel": right_label,
        "phase": "match",
        "sameType": compared.get("sameType"),
        "leftPreviews": str(left_dir),
        "rightPreviews": str(right_dir),
        "heatDir": str(heat_dir),
        "evidenceDir": str(work / "evidence"),
        "workDir": str(work),
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


def _run_visual(job: Job, left: Path, right: Path, *, fresh: bool = False) -> dict[str, Any]:
    settings = load_settings()
    if fresh:
        delete_pairing("visual", left, right)
    job.log("Reading preview folders…")
    t0 = time.perf_counter()
    left_digests = folder_digests(left)
    right_digests = folder_digests(right)
    job.log(f"Hashed previews in {time.perf_counter() - t0:.1f}s.")
    reuse_report = None
    slots = None
    if settings["reusePairings"] and not fresh:
        baseline = load_pairing("visual", left, right)
        if baseline:
            reused = reuse_slots(
                baseline, left_digests, right_digests, float(settings["reuseThreshold"])
            )
            if reused:
                slots = pair_index_gaps(reused.slots)
                reuse_report = {key: value for key, value in reused.as_dict().items() if key != "slots"}
                job.log(
                    f"Reusing {reused.carried} pairing(s) from an earlier run "
                    f"({reused.changed} changed, {reused.added} added, {reused.removed} removed)."
                )
            else:
                job.log("Earlier pairing no longer matches these folders; starting fresh.")
    result = visual_result(left, right, slots=slots)
    result["leftDigests"] = left_digests
    result["rightDigests"] = right_digests
    result["slots"] = _slots_from_pairs(result.get("pairs") or [])
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
    t_check = time.perf_counter()
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
    job.log(f"Checked pairs in {time.perf_counter() - t_check:.1f}s.")
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


def _run_visual_check(job: Job) -> dict[str, Any]:
    result = dict(job.result or {})
    left = Path(str(result.get("leftPath") or result.get("leftPreviews") or ""))
    right = Path(str(result.get("rightPath") or result.get("rightPreviews") or ""))
    if not left.is_dir() or not right.is_dir():
        raise FileNotFoundError("Preview folders are missing; choose them again.")
    work = ROOT / "output" / ".visual" / job.id
    heat_dir = work / "heat"
    heat_dir.mkdir(parents=True, exist_ok=True)
    job.log("Reading previews and checking wording, photos, and house style…")
    t0 = time.perf_counter()
    left_payload = preview_inspect(left)
    right_payload = preview_inspect(right)
    slots = slots_from_pairs(result.get("pairs") or [])
    compared = compare_inspects(
        left_payload,
        right_payload,
        left,
        right,
        heat_dir,
        left_label=str(result.get("leftLabel") or "LW"),
        right_label=str(result.get("rightLabel") or "DSK"),
        slots=slots,
        check=True,
    )
    job.log(f"Checked pairs in {time.perf_counter() - t0:.1f}s.")
    flags = compared.pop("flags")
    pairs = compared["pairs"]
    for pair in pairs:
        pair["flags"] = serialize_flags(pair.get("flags") or [])
    result.update(
        {
            "phase": "checked",
            "sameType": compared.get("sameType"),
            "leftPreviews": str(left),
            "rightPreviews": str(right),
            "heatDir": str(heat_dir),
            "evidenceDir": str(work / "evidence"),
            "workDir": str(work),
            "heatPngs": [p.name for p in preview_pngs(heat_dir)],
            "leftCatalog": compared.get("leftCatalog") or result.get("leftCatalog") or [],
            "rightCatalog": compared.get("rightCatalog") or result.get("rightCatalog") or [],
            "summary": compared,
            "pairs": pairs,
            "slots": _slots_from_pairs(pairs),
            "flags": serialize_flags(flags),
        }
    )
    return result


def _run_inspect(
    job: Job,
    path: Path,
    export: bool,
    slide_range: frozenset[int] | None,
) -> dict[str, Any]:
    job_dir = ROOT / "output" / ".inspect" / job.id if export else None
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
    return {
        "path": str(path),
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
    }


def _run_resize(
    job: Job,
    path: Path,
    template: Path,
    slide_range: frozenset[int],
    export: bool,
    include_lists: bool = False,
) -> dict[str, Any]:
    dest_dir = ROOT / "output" / ".resize" / job.id
    dest = dest_dir / f"{path.stem}_CG.key"
    export_dir = dest_dir / "previews" if export else None
    job.log(f"Remapping {path.name} → 1920×1080 (slide {format_slide_range(slide_range)})…")
    job.log(f"CG template (16:9 layouts copied onto the wall copy): {template.name}.")
    if not include_lists:
        job.log("Church-name text hidden (enable the list checkbox to pack them at the template size).")
    info = remap_and_inspect(
        path,
        dest,
        template=template,
        slide_range=slide_range,
        include_lists=include_lists,
        export_dir=export_dir,
        log=job.log,
    )
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
    flags = validate_inspect(payload, location_prefix=dest.name)
    counts = info.get("counts") or {}
    applied = info.get("applied")
    missed = info.get("missed")
    job.log(f"Wrote {dest.name}: applied {applied}, missed {missed}.")
    score = info.get("templateScore") or info.get("goldScore") or {}
    return {
        "path": str(path),
        "destPath": str(dest),
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
        "includeLists": include_lists,
        "templateScore": score,
        "flags": serialize_flags(flags),
    }


app = create_app()

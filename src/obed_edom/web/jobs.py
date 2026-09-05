from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from obed_edom.inspect import preview_media
# Aliased: `output_root` is also a parameter name in this module.
from obed_edom.paths import output_root as default_output_root
from obed_edom.validate import flag_dict


@dataclass
class Job:
    id: str
    kind: str
    feature: str = ""
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.feature:
            self.feature = self.kind

    def log(self, message: str) -> None:
        self.logs.append(message)
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "feature": self.feature,
            "status": self.status,
            "logs": self.logs[-80:],
            "error": self.error,
            "result": self.result,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind") or "job"),
            feature=str(data.get("feature") or data.get("kind") or "job"),
            status=str(data.get("status") or "done"),
            logs=list(data.get("logs") or []),
            error=data.get("error"),
            result=data.get("result"),
            created_at=float(data.get("createdAt") or time.time()),
            updated_at=float(data.get("updatedAt") or time.time()),
        )


class JobRunner:
    def __init__(self, session_dir: Path | None = None, output_root: Path | None = None) -> None:
        self._output_root = Path(output_root) if output_root else default_output_root()
        self._session_dir = Path(session_dir) if session_dir else self._output_root / ".sessions"
        self._jobs: dict[str, Job] = {}
        self._fns: dict[str, Callable[[Job], dict[str, Any]]] = {}
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._load_sessions()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def submit(self, kind: str, fn: Callable[[Job], dict[str, Any]], *, feature: str | None = None) -> Job:
        job = Job(id=str(uuid.uuid4())[:8], kind=kind, feature=feature or kind)
        with self._cv:
            self._jobs[job.id] = job
            self._fns[job.id] = fn
            self._queue.append(job.id)
            self._cv.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def rerun(self, job_id: str, fn: Callable[[Job], dict[str, Any]]) -> Job | None:
        with self._cv:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status == "running":
                raise RuntimeError("Job is already running")
            job.status = "queued"
            job.error = None
            job.updated_at = time.time()
            self._fns[job.id] = fn
            self._queue.append(job.id)
            self._cv.notify()
        return job

    def list(self, kind: str | None = None, feature: str | None = None) -> list[Job]:
        jobs = list(self._jobs.values())
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        if feature:
            jobs = [j for j in jobs if j.feature == feature]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def public_dict(self, job: Job) -> dict[str, Any]:
        data = job.to_dict()
        data["artifacts"] = artifact_status(job, self._output_root)
        return data

    def save(self, job: Job) -> None:
        if job.status not in {"done", "error"}:
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_file(job.id)
        path.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")

    def update_result(self, job_id: str, result: dict[str, Any]) -> Job | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        job.result = result
        job.updated_at = time.time()
        self.save(job)
        return job

    def relocate(
        self,
        job_id: str,
        *,
        folder: str | None = None,
        path: str | None = None,
        left_path: str | None = None,
        right_path: str | None = None,
    ) -> Job | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        result = dict(job.result or {})
        if folder:
            result = bind_generate_folder(result, Path(folder).expanduser())
        if path:
            result["path"] = str(Path(path).expanduser())
        if left_path:
            result["leftPath"] = str(Path(left_path).expanduser())
        if right_path:
            result["rightPath"] = str(Path(right_path).expanduser())
        return self.update_result(job_id, result)

    def delete(self, job_id: str, *, purge: bool = True) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if not job:
            return False
        self._session_file(job_id).unlink(missing_ok=True)
        if purge:
            self._purge_artifacts(job)
        return True

    def delete_all(self, *, purge: bool = True) -> int:
        ids = [job.id for job in self.list() if job.status in {"done", "error"}]
        deleted = 0
        for job_id in ids:
            if self.delete(job_id, purge=purge):
                deleted += 1
        return deleted

    def _session_file(self, job_id: str) -> Path:
        return self._session_dir / f"{job_id}.json"

    def _load_sessions(self) -> None:
        if not self._session_dir.is_dir():
            return
        for path in self._session_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                job = Job.from_dict(data)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if job.status not in {"done", "error"}:
                continue
            self._jobs[job.id] = job

    def _purge_artifacts(self, job: Job) -> None:
        result = job.result or {}
        candidates: list[Path] = []
        output_dir = result.get("outputDir")
        if output_dir:
            candidates.append(Path(output_dir))
        preview_dir = result.get("previewDir")
        if preview_dir:
            candidates.append(Path(preview_dir))
        work_dir = result.get("workDir")
        if work_dir:
            candidates.append(Path(work_dir))
        left = result.get("leftPreviews")
        if left and job.feature != "visual":
            candidates.append(Path(left).parent)
        from obed_edom.baseline import cache_root as _cache_root  # noqa: PLC0415

        root = self._output_root.resolve()
        # Never purge the warm cache (rebuild is ~1h of Keynote). Honour OBED_EDOM_CACHE_DIR even inside output/.
        cache_root = _cache_root().resolve()
        seen: set[Path] = set()
        for path in candidates:
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved == root or resolved in seen:
                continue
            try:
                resolved.relative_to(cache_root)
                continue
            except ValueError:
                pass
            seen.add(resolved)
            if resolved.is_dir():
                shutil.rmtree(resolved, ignore_errors=True)
            elif resolved.is_file():
                resolved.unlink(missing_ok=True)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                fn = self._fns.pop(job_id, None)
            if not job or not fn:
                continue
            job.status = "running"
            job.log("Started.")
            try:
                job.result = fn(job)
                job.status = "done"
                job.log("Finished.")
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.error = str(exc)
                job.log(f"Error: {exc}")
            job.updated_at = time.time()
            self.save(job)


def serialize_flags(flags) -> list[dict]:
    return [flag_dict(f) for f in flags]


def _exists(path_str: str | None) -> bool:
    return bool(path_str) and Path(path_str).expanduser().exists()


def artifact_status(job: Job, output_root: Path) -> dict[str, Any]:
    result = job.result or {}
    checks: list[tuple[str, str | None]] = [
        ("output folder", result.get("outputDir")),
        ("LW.key", result.get("lwKey")),
        ("DSK.key", result.get("dskKey")),
        ("cued outline", result.get("cuedDocx")),
        ("review.pdf", result.get("reviewPath")),
        ("preview dir", result.get("previewDir")),
        ("source Keynote", result.get("path")),
        ("CG Keynote", result.get("destPath")),
        ("left Keynote", result.get("leftPath")),
        ("right Keynote", result.get("rightPath")),
        ("left previews", result.get("leftPreviews")),
        ("right previews", result.get("rightPreviews")),
        ("visual diff", result.get("heatDir")),
    ]
    previews = result.get("previews") or {}
    if isinstance(previews, dict):
        checks.append(("LW previews", previews.get("lw")))
        checks.append(("DSK previews", previews.get("dsk")))
    missing = [label for label, path in checks if path and not _exists(str(path))]
    suggested: str | None = None
    stem = result.get("stem")
    output_dir = result.get("outputDir")
    if stem and output_dir and not _exists(str(output_dir)):
        candidate = Path(output_root) / str(stem)
        if candidate.is_dir():
            suggested = str(candidate)
    return {"ok": not missing, "missing": missing, "suggestedPath": suggested}


def bind_generate_folder(result: dict[str, Any], folder: Path) -> dict[str, Any]:
    folder = folder.expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a folder: {folder}")
    updated = dict(result)
    updated["outputDir"] = str(folder)
    stem = str(updated.get("stem") or folder.name)

    def first_existing(candidates: list[Path]) -> str | None:
        for path in candidates:
            if path.exists():
                return str(path)
        return None

    updated["lwKey"] = first_existing(
        [folder / f"{stem}_LW.key", *sorted(folder.glob("*_LW.key"))]
    ) or updated.get("lwKey")
    updated["dskKey"] = first_existing(
        [folder / f"{stem}_DSK.key", *sorted(folder.glob("*_DSK.key"))]
    ) or updated.get("dskKey")
    updated["cuedDocx"] = first_existing(
        [folder / f"{stem}_CUED.docx", *sorted(folder.glob("*_CUED.docx"))]
    ) or updated.get("cuedDocx")
    updated["reviewPath"] = first_existing(
        [folder / "review.pdf", *sorted(folder.glob("review.pdf"))]
    ) or updated.get("reviewPath")
    lw_prev = folder / "previews" / "lw"
    dsk_prev = folder / "previews" / "dsk"
    prev = updated.get("previews")
    prev = prev if isinstance(prev, dict) else {}
    updated["previews"] = {
        "lw": str(lw_prev) if lw_prev.is_dir() else prev.get("lw"),
        "dsk": str(dsk_prev) if dsk_prev.is_dir() else prev.get("dsk"),
    }
    updated["previewFiles"] = {
        "lw": preview_names(lw_prev),
        "dsk": preview_names(dsk_prev),
    }
    return updated


def preview_names(folder: Path) -> list[str]:
    return [p.name for p in preview_media(folder)]

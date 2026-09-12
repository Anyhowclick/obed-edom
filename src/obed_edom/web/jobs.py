from __future__ import annotations

import json
import os
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
from obed_edom.web.job_names import generate_job_name, normalise_job_name

# Id-derived private roots whose basename follows job.name (see JobRunner.rename).
_ID_DERIVED_ROOTS = (".maps", ".watercolour", ".resize", ".diff", ".outline", ".inspect")


@dataclass
class Job:
    id: str
    kind: str
    feature: str = ""
    name: str = ""
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _cancelled: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.feature:
            self.feature = self.kind

    def log(self, message: str) -> None:
        self.logs.append(message)
        self.updated_at = time.time()

    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "feature": self.feature,
            "name": self.name,
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
            name=str(data.get("name") or data["id"]),
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
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._job_locks: dict[str, threading.Lock] = {}
        self._deleted_ids: set[str] = set()
        self._deleted_names: set[str] = set()
        self._cv = threading.Condition(self._lock)
        self._load_sessions()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def submit(
        self,
        kind: str,
        fn: Callable[[Job], dict[str, Any]],
        *,
        feature: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Job:
        with self._cv:
            job_id = self._new_job_id()
            job_name = self._new_job_name()
            job = Job(id=job_id, kind=kind, feature=feature or kind, name=job_name, result=result)
            self._jobs[job.id] = job
            self._fns[job.id] = fn
            self._queue.append(job.id)
            self._cv.notify()
        return job

    def _new_job_id(self) -> str:
        while True:
            job_id = self._generate_job_id()
            if job_id not in self._jobs and job_id not in self._deleted_ids:
                return job_id

    @staticmethod
    def _generate_job_id() -> str:
        return str(uuid.uuid4())[:8]

    def _new_job_name(self) -> str:
        taken = {job.name.lower() for job in self._jobs.values()} | self._deleted_names
        for _ in range(200):
            candidate = generate_job_name(taken)
            if not self._name_folder_exists(candidate):
                return candidate
            taken.add(candidate.lower())
        return f"{candidate}-{uuid.uuid4().hex[:6]}"

    def _name_folder_exists(self, name: str) -> bool:
        for root_name in _ID_DERIVED_ROOTS:
            if (self._output_root / root_name / name).exists():
                return True
        return False

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def rerun(self, job_id: str, fn: Callable[[Job], dict[str, Any]]) -> Job | None:
        with self._cv:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job_id in self._running or job.status == "running":
                raise RuntimeError("Job is already running")
            job.status = "queued"
            job.error = None
            job._cancelled.clear()
            job.updated_at = time.time()
            self._fns[job.id] = fn
            self._queue.append(job.id)
            self._cv.notify()
        return job

    def cancel(self, job_id: str) -> Job | None:
        with self._cv:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status not in {"queued", "running"}:
                return job
            if job.cancelled():
                return job
            job._cancelled.set()
            if job.status == "queued":
                job.status = "error"
                job.error = "Export cancelled."
                job.log("Cancelled.")
            else:
                job.log("Cancelling.")
            self._cv.notify_all()
        if job.status == "error":
            with self._job_lock(job_id):
                self.save(job)
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

    def _job_lock(self, job_id: str) -> threading.Lock:
        with self._lock:
            lock = self._job_locks.get(job_id)
            if lock is None:
                lock = self._job_locks[job_id] = threading.Lock()
            return lock

    def save(self, job: Job) -> None:
        if job.status not in {"done", "error"}:
            return
        with self._lock:
            if job.id in self._deleted_ids:
                return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_file(job.id)
        temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
            os.replace(temp, path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def update_result(self, job_id: str, result: dict[str, Any]) -> Job | None:
        with self._job_lock(job_id):
            with self._lock:
                if job_id not in self._jobs:
                    return None
                job = self._jobs[job_id]
            previous_result, previous_updated_at = job.result, job.updated_at
            job.result = result
            job.updated_at = time.time()
            try:
                self.save(job)
            except Exception:
                job.result, job.updated_at = previous_result, previous_updated_at
                raise
        return job

    def relocate(
        self,
        job_id: str,
        *,
        folder: str | None = None,
        path: str | None = None,
        left_path: str | None = None,
        right_path: str | None = None,
        dest_path: str | None = None,
        dest_path_cg: str | None = None,
        dest_path_dsk: str | None = None,
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
        if dest_path:
            result["destPath"] = str(Path(dest_path).expanduser())
        if dest_path_cg:
            result["destPathCg"] = str(Path(dest_path_cg).expanduser())
        if dest_path_dsk:
            result["destPathDsk"] = str(Path(dest_path_dsk).expanduser())
        return self.update_result(job_id, result)

    def is_name_taken(self, name: str, *, exclude_job_id: str | None = None) -> bool:
        lowered = name.lower()
        with self._lock:
            for job in self._jobs.values():
                if job.id != exclude_job_id and job.name.lower() == lowered:
                    return True
            return lowered in self._deleted_names

    def set_name(self, job_id: str, name: str) -> Job:
        """Assign an already-validated name and save. Used directly by feature-specific
        rename flows (e.g. maps, which moves its folder inside `maps_commit`)."""
        with self._job_lock(job_id):
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            previous_name, previous_updated_at = job.name, job.updated_at
            job.name = name
            job.updated_at = time.time()
            try:
                self.save(job)
            except Exception:
                job.name, job.updated_at = previous_name, previous_updated_at
                raise
        return job

    def rename(self, job_id: str, raw_name: str) -> Job:
        """Generic rename for the id-derived folders owned directly by jobs.py
        (resize/diff/outline/inspect/watercolour). Maps jobs are renamed through
        `maps.rename_job_folder`, which stages the folder move via `maps_commit`."""
        with self._job_lock(job_id):
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status in {"queued", "running"} or job_id in self._running:
                raise RuntimeError("Job is still running")
            name = normalise_job_name(raw_name)
            if name == job.name.lower():
                return job
            if self.is_name_taken(name, exclude_job_id=job_id):
                raise FileExistsError(f"A job named '{name}' already exists")
            result = dict(job.result or {})
            old_dir = self._id_derived_dir(result)
            new_dir: Path | None = None
            if old_dir is not None and old_dir.name == job.name:
                new_dir = old_dir.parent / name
                if new_dir.exists():
                    raise FileExistsError(f"A folder named '{name}' already exists")
                os.replace(old_dir, new_dir)
                result = rewrite_result_paths(result, old_dir, new_dir)
                if result.get("stem") == job.name:
                    result["stem"] = name
            previous_name, previous_result, previous_updated_at = job.name, job.result, job.updated_at
            job.name = name
            job.result = result
            job.updated_at = time.time()
            try:
                self.save(job)
            except Exception:
                job.name, job.result, job.updated_at = previous_name, previous_result, previous_updated_at
                if new_dir is not None and old_dir is not None:
                    os.replace(new_dir, old_dir)
                raise
        return job

    def _id_derived_dir(self, result: dict[str, Any]) -> Path | None:
        output_dir = result.get("outputDir")
        if not output_dir:
            return None
        candidate = Path(output_dir)
        root = self._output_root.resolve()
        for root_name in _ID_DERIVED_ROOTS:
            private_root = (root / root_name).resolve()
            try:
                resolved = candidate.resolve()
                resolved.relative_to(private_root)
            except (OSError, ValueError):
                continue
            if resolved.parent == private_root:
                return candidate
        return None

    def delete(self, job_id: str, *, purge: bool = True) -> bool:
        with self._job_lock(job_id):
            with self._lock:
                job = self._jobs.pop(job_id, None)
                if job is not None:
                    self._deleted_ids.add(job_id)
                    self._deleted_names.add(job.name.lower())
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
        geocode_root = (self._output_root / ".geocode").resolve()
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
            try:
                resolved.relative_to(geocode_root)
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
                if job and fn and not job.cancelled():
                    self._running.add(job_id)
                    job.status = "running"
                    job.log("Started.")
                else:
                    job = None
            if not job or not fn:
                continue
            result: dict[str, Any] | None = None
            error: str | None = None
            try:
                result = fn(job)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            finally:
                with self._job_lock(job_id):
                    with self._cv:
                        previous_result, previous_status = job.result, job.status
                        if job.cancelled():
                            job.status = "error"
                            job.error = "Export cancelled."
                            job.log("Cancelled.")
                        elif error is not None:
                            job.status = "error"
                            job.error = error
                            job.log(f"Error: {error}")
                        else:
                            job.result = result
                            job.status = "done"
                            job.log("Finished.")
                        self._running.discard(job_id)
                        job.updated_at = time.time()
                    try:
                        self.save(job)
                    except Exception as exc:  # noqa: BLE001
                        if error is None and not job.cancelled():
                            job.result = previous_result
                            job.status = "error"
                            job.error = str(exc)
                            job.log(f"Error: {exc}")


def rewrite_result_paths(result: dict[str, Any], old_dir: Path, new_dir: Path) -> dict[str, Any]:
    """Recursively replace absolute-path strings rooted at `old_dir` with `new_dir`.

    Relative filenames (e.g. `stillPng`, `previewFiles` entries) are untouched by
    construction: only strings equal to or prefixed by `str(old_dir)` are rewritten.
    """
    old_str, new_str = str(old_dir), str(new_dir)
    prefix = old_str + os.sep

    def rewrite(value: Any) -> Any:
        if isinstance(value, str):
            if value == old_str:
                return new_str
            if value.startswith(prefix):
                return new_str + value[len(old_str):]
            return value
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    return rewrite(result)


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
        ("left Keynote", result.get("leftPath")),
        ("right Keynote", result.get("rightPath")),
        ("left previews", result.get("leftPreviews")),
        ("right previews", result.get("rightPreviews")),
        ("visual diff", result.get("heatDir")),
    ]
    if job.feature == "maps":
        if result.get("destPath"):
            checks.append(("Map Keynote", result.get("destPath")))
        if result.get("destPathCg"):
            checks.append(("CG Keynote", result.get("destPathCg")))
        if result.get("destPathDsk"):
            checks.append(("DSK Keynote", result.get("destPathDsk")))
    else:
        checks.append(("CG Keynote", result.get("destPath")))
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

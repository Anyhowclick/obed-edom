from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sermon_slides.validate import flag_dict


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def log(self, message: str) -> None:
        self.logs.append(message)
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "logs": self.logs[-80:],
            "error": self.error,
            "result": self.result,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._fns: dict[str, Callable[[Job], dict[str, Any]]] = {}
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def submit(self, kind: str, fn: Callable[[Job], dict[str, Any]]) -> Job:
        job = Job(id=str(uuid.uuid4())[:8], kind=kind)
        with self._cv:
            self._jobs[job.id] = job
            self._fns[job.id] = fn
            self._queue.append(job.id)
            self._cv.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        jobs = list(self._jobs.values())
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

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


def serialize_flags(flags) -> list[dict]:
    return [flag_dict(f) for f in flags]


def preview_names(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.png")) + sorted(folder.glob("*.PNG"))
    if not files:
        files = sorted(p for p in folder.rglob("*.png") if p.is_file())
    return [p.name for p in files]

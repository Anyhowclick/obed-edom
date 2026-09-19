"""Local live presentation routes, separate from review-preview lifetime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from obed_edom.html_preview import (
    PreviewError,
    file_sha256,
    load_header,
    registered_export_root,
    safe_export_file,
)
from obed_edom.live_runtime import PLAYER_SHA256, RUNTIME_VERSION
from obed_edom.live_session import LiveSessionService


class StartBody(BaseModel):
    previewJobId: str = Field(min_length=1, max_length=200)
    displayId: str | None = None


class CommandBody(BaseModel):
    requestId: str = Field(min_length=1, max_length=200)
    operation: Literal["advance", "goTo", "hide", "show", "stop"]
    slide: int | None = Field(default=None, strict=True)


def _same_origin(request: Request) -> None:
    host = request.headers.get("host", "")
    if urlsplit("http://" + host).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "Live controls require a local dashboard host.")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != host:
        raise HTTPException(403, "Live controls require the dashboard origin.")


def live_router(runner, *, service=None, host_factory=None, displays=None) -> APIRouter:
    from obed_edom.live_host import LiveOutputHost, list_displays

    sessions = service or LiveSessionService()
    make_host = host_factory or LiveOutputHost
    get_displays = displays or list_displays
    lock = RLock()
    roots: dict[str, Path] = {}

    @asynccontextmanager
    async def lifespan(_app):
        yield
        current = sessions.state()
        if current and current["status"] != "stopped":
            sessions.command(current["sessionId"], uuid4().hex, "stop")

    router = APIRouter(
        prefix="/api/live", dependencies=[Depends(_same_origin)], lifespan=lifespan,
    )

    @router.get("")
    def state():
        return sessions.state()

    @router.get("/displays")
    def display_list():
        return [
            {
                "id": str(display.display_id),
                "name": "Main display" if display.primary else f"Display {display.display_id}",
                "width": display.width,
                "height": display.height,
                "x": display.x,
                "y": display.y,
                "primary": display.primary,
            }
            for display in get_displays()
        ]

    @router.get("/decks")
    def decks():
        rows = []
        for job in runner.list(kind="html-preview"):
            result = job.result or {}
            if job.status != "done" or result.get("phase") != "ready":
                continue
            try:
                registered_export_root(result, job.id)
            except PreviewError:
                continue
            rows.append({
                "previewJobId": job.id,
                "name": Path(result.get("path", "")).stem,
                "slides": len(result.get("slides", [])),
                "sourceDigest": result.get("sourceDigest"),
            })
        return rows

    @router.post("")
    def start(body: StartBody):
        with lock:
            current = sessions.state()
            if current and current["status"] != "stopped":
                raise HTTPException(409, "Stop the active session before loading another deck.")
            job = runner.get(body.previewJobId)
            if not job or job.kind != "html-preview" or job.status != "done":
                raise HTTPException(404, "Prepared preview job not found.")
            result = job.result or {}
            if result.get("phase") != "ready":
                raise HTTPException(409, "Prepare the HTML preview before loading live output.")
            try:
                root = registered_export_root(result, job.id)
                digest = file_sha256(safe_export_file(root, "assets/player/main.js"))
                if digest != PLAYER_SHA256 or digest != (result.get("manifest") or {}).get("playerDigest"):
                    raise ValueError("This player version is not supported for live controls.")
                header, _ = load_header(root)
                width, height = header.get("slideWidth", 0), header.get("slideHeight", 0)
                if not width or not height or abs(width / height - 16 / 9) > 0.001:
                    raise ValueError("Live output currently requires a prepared 16:9 deck.")
                if header.get("showMode") != 0:
                    raise ValueError("Live output requires manual presentation mode.")
                slides = [dict(row) for row in result.get("slides", [])]
                if any(row.get("unsupportedMedia") for row in slides):
                    raise ValueError("This deck contains unsupported media.")
                host = make_host(root, slides, display_id=int(body.displayId) if body.displayId else None)
                identity = {
                    "sourceDigest": result["sourceDigest"],
                    "playerDigest": digest,
                    "runtimeRevision": RUNTIME_VERSION,
                    "slides": slides,
                    "output": {**host.output, "canvas": {"width": width, "height": height}},
                }
                loaded = sessions.start(
                    host, export_key=result["exportKey"], export_root=root, identity=identity,
                )
                roots.clear()
                roots[loaded["sessionId"]] = root
                return loaded
            except (PreviewError, ValueError, OSError, RuntimeError) as exc:
                raise HTTPException(409, str(exc)) from exc

    @router.post("/{session_id}/commands")
    def command(session_id: str, body: CommandBody):
        return sessions.command(session_id, body.requestId, body.operation, body.slide)

    @router.get("/{session_id}/thumbnail/{ordinal}")
    def thumbnail(session_id: str, ordinal: int):
        with lock:
            current = sessions.state()
            if not current or current["sessionId"] != session_id or current["status"] == "stopped":
                raise HTTPException(404, "Session is no longer current.")
            slide = next((row for row in current["slides"] if row.get("originalOrdinal") == ordinal), None)
            if not slide or slide.get("skipped") or not slide.get("exportedUuid"):
                raise HTTPException(404, "Slide thumbnail is unavailable.")
            try:
                path = safe_export_file(roots[session_id], f"assets/{slide['exportedUuid']}/thumbnail.jpeg")
            except (PreviewError, KeyError) as exc:
                raise HTTPException(404, "Slide thumbnail is unavailable.") from exc
            return FileResponse(path, media_type="image/jpeg")

    return router

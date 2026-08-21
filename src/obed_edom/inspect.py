from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from obed_edom.map_remap import slides_for_plan
from obed_edom.paths import find_repo_root

INSPECT_JS = Path(__file__).resolve().parent / "inspect_keynote.js"


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def export_applescript(key_path: Path, export_dir: Path) -> str:
    """Same export shape generate uses: POSIX file + slide images PNG."""
    key = _as_escape(str(Path(key_path).resolve()))
    dest = _as_escape(str(Path(export_dir).resolve()))
    return "\n".join(
        [
            'tell application "Keynote"',
            '  using terms from application "Keynote"',
            f'    set theDoc to open POSIX file "{key}"',
            f'    set exportFolder to POSIX file "{dest}"',
            "    export theDoc to exportFolder as slide images with properties {image format:PNG, skipped slides:false}",
            "    try",
            "      close theDoc saving no",
            "    end try",
            "  end using terms from",
            "end tell",
        ]
    )


def export_slide_images(key_path: Path, export_dir: Path) -> str | None:
    """Export PNG previews. Returns an error string, or None on success."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    script = export_applescript(key_path, export_dir)
    subprocess.run(["open", "-a", "Keynote"], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if preview_pngs(export_dir):
        return None
    err = (proc.stderr or proc.stdout or "").strip() or "Keynote did not write PNG previews."
    if proc.returncode != 0:
        return f"Preview export failed: {err}"
    return err


def inspect_keynote(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
) -> dict[str, Any]:
    """Open a .key read-only, dump text/bounds, optionally export PNGs, close without saving."""
    key_path = Path(key_path).expanduser().resolve()
    if not key_path.exists():
        raise FileNotFoundError(f"Keynote not found: {key_path}")
    if export_dir:
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
    plan: dict[str, Any] = {"path": str(key_path), "close": True, "save": False}
    if export_dir:
        plan["exportDir"] = str(Path(export_dir).resolve())
    wanted = slides_for_plan(slide_range)
    if wanted:
        plan["slides"] = wanted
        plan["range"] = [wanted[0], wanted[-1]]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(INSPECT_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Keynote inspect failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or "")
        )
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("Keynote inspect returned no JSON.")
    payload = json.loads(raw)
    if export_dir:
        pngs = preview_pngs(Path(export_dir))
        if pngs:
            payload["exported"] = True
        else:
            fallback_err = export_slide_images(key_path, Path(export_dir))
            payload["exported"] = bool(preview_pngs(Path(export_dir)))
            if not payload["exported"]:
                payload["exportError"] = fallback_err or payload.get("exportError") or ""
    return payload


PREVIEW_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PREVIEW_VIDEO_SUFFIXES = {".mov"}
PREVIEW_MEDIA_SUFFIXES = PREVIEW_IMAGE_SUFFIXES | PREVIEW_VIDEO_SUFFIXES

_PREVIEW_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mov": "video/quicktime",
}


def preview_media_type(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    return _PREVIEW_MEDIA_TYPES.get(ext, "application/octet-stream")


def preview_media(folder: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    """Preview stills and QuickTime movies in a folder (JPEG/PNG/.mov)."""
    allowed = {s.lower() for s in (suffixes or PREVIEW_MEDIA_SUFFIXES)}
    if not folder.is_dir():
        return []

    def collect(paths: list[Path]) -> list[Path]:
        seen: set[str] = set()
        out: list[Path] = []
        for path in sorted(paths, key=lambda p: p.name.lower()):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
        return out

    files = collect(list(folder.iterdir()))
    if files:
        return files
    return collect([p for p in folder.rglob("*") if p.is_file()])


def preview_pngs(folder: Path) -> list[Path]:
    return preview_media(folder, suffixes={".png"})


def _walk_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        yield item
        yield from _walk_items(item)


def slide_plain_text(slide: dict) -> str:
    parts: list[str] = []
    for item in _walk_items(slide):
        text = (item.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def all_plain_text(payload: dict) -> str:
    return "\n\n".join(slide_plain_text(s) for s in payload.get("slides") or [])


def highlighted_markup(slide: dict) -> str:
    """Approximate *highlighted* wrapping from colour runs when available."""
    chunks: list[str] = []
    for item in slide.get("items") or []:
        runs = item.get("runs") or []
        if not runs:
            text = item.get("text") or ""
            if text:
                chunks.append(text)
            continue
        buf: list[str] = []
        for run in runs:
            text = run.get("text") or ""
            if _looks_highlight(run.get("color")):
                buf.append(f"*{text}*")
            else:
                buf.append(text)
        chunks.append("".join(buf))
    return "\n".join(chunks)


def _looks_highlight(color: list | None) -> bool:
    if not color or len(color) < 3:
        return False
    r, g, b = color[0], color[1], color[2]
    # Keynote RGB is often 0–65535. Yellow/gold highlight is high R+G, low B.
    scale = 65535 if max(r, g, b) > 255 else 255
    rn, gn, bn = r / scale, g / scale, b / scale
    return rn > 0.7 and gn > 0.45 and bn < 0.45


def diff_work_dir(job_id: str) -> Path:
    root = find_repo_root() / "output" / ".diff" / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root

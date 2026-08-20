from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from obed_edom.paths import find_repo_root

INSPECT_JS = Path(__file__).resolve().parent / "inspect_keynote.js"


def inspect_keynote(
    key_path: Path | str,
    *,
    export_dir: Path | str | None = None,
    slide_range: tuple[int, int] | None = None,
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
    if slide_range:
        plan["range"] = [int(slide_range[0]), int(slide_range[1])]
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
    return json.loads(raw)


def preview_pngs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.png")) + sorted(folder.glob("*.PNG"))
    if not files:
        files = sorted(p for p in folder.rglob("*.png") if p.is_file())
    return files


def slide_plain_text(slide: dict) -> str:
    parts: list[str] = []
    for item in slide.get("items") or []:
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

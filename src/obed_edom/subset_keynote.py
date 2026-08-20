from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

SUBSET_JS = Path(__file__).resolve().parent / "subset_keynote.js"


def subset_keynote(source: Path | str, dest: Path | str, slides: list[int]) -> Path:
    """Copy a Keynote then delete every slide not in `slides` (1-based). Needs Keynote.app."""
    source = Path(source).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        raise FileNotFoundError(source)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    subprocess.run(["ditto", str(source), str(dest)], check=True)
    plan = {"dest": str(dest), "slides": [int(n) for n in slides]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        plan_path = handle.name
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", str(SUBSET_JS), plan_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(plan_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("Keynote subset failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    if not dest.exists():
        raise RuntimeError("Keynote subset produced no file:\n" + (proc.stdout or "") + (proc.stderr or ""))
    return dest

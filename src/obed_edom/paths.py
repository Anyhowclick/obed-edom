from __future__ import annotations

import os
from pathlib import Path


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2], Path.cwd(), *Path.cwd().parents]
    for path in candidates:
        if (path / "pyproject.toml").is_file() and (path / "src" / "obed_edom").is_dir():
            return path
    return Path.cwd()


def output_root() -> Path:
    """Overridable via `OBED_EDOM_OUTPUT_ROOT`. Every writer must come through here."""
    override = (os.environ.get("OBED_EDOM_OUTPUT_ROOT") or "").strip()
    return Path(override).expanduser() if override else find_repo_root() / "output"


def template_path(relative: str) -> Path:
    return find_repo_root() / relative


def resolve_keynote_template(path: str | Path | None) -> Path:
    """Resolve an explicit .key path (absolute, or repo-relative)."""
    shown: Path = Path("(none)")
    if path:
        raw = Path(str(path)).expanduser()
        shown = raw
        if raw.exists():
            return raw.resolve()
        if not raw.is_absolute():
            rel = template_path(str(path))
            shown = rel
            if rel.exists():
                return rel.resolve()
    raise FileNotFoundError(
        f"Template not found: {shown}. Drop an LW and/or DSK Keynote template in the "
        "dashboard, or pass --lw-template and/or --dsk-template."
    )


def select_deck_template(path: str | Path | None) -> Path | None:
    """Resolve a deck template, or None to skip that deck."""
    if not path:
        return None
    return resolve_keynote_template(path)

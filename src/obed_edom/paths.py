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


_PRIVATE_ROOT_NAMES = (
    ".maps",
    ".watercolour",
    ".resize",
    ".diff",
    ".outline",
    ".inspect",
    ".uploads",
    ".sessions",
    ".geocode",
)


def validate_export_dir(raw: str | Path) -> Path:
    """Resolve an owner-chosen export destination, rejecting private working roots."""
    from obed_edom.baseline import cache_root  # noqa: PLC0415

    resolved = Path(str(raw)).expanduser()
    if not resolved.is_absolute():
        raise ValueError(f"Export directory must be an absolute path: {raw}")
    resolved = resolved.resolve()

    output = output_root().resolve()
    for root_name in _PRIVATE_ROOT_NAMES:
        private_root = output / root_name
        try:
            resolved.relative_to(private_root)
        except ValueError:
            pass
        else:
            raise ValueError(f"Export directory cannot be inside {private_root}")

    try:
        resolved.relative_to(cache_root().resolve())
    except ValueError:
        pass
    else:
        raise ValueError(f"Export directory cannot be inside {cache_root()}")

    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Export directory is not a directory: {resolved}")

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create export directory {resolved}: {exc}") from exc

    return resolved


def export_destination(job) -> Path:
    """Job override, else the operator default, else `output_root()`.

    Falls back to `output_root()` (and sets `job.result["exportDirFallback"]`)
    when the chosen directory has since vanished or turned into a file.
    """
    from obed_edom.settings import load_settings  # noqa: PLC0415

    result = getattr(job, "result", None)
    override = (result or {}).get("exportDir")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        if result is not None:
            result.pop("exportDir", None)
            result["exportDirFallback"] = True
        return output_root()

    default_dir = (load_settings().get("defaultExportDir") or "").strip()
    if default_dir:
        candidate = Path(default_dir)
        if candidate.is_dir():
            return candidate

    return output_root()


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

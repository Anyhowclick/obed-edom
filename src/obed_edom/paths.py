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


def _within_root(resolved: Path, root: Path) -> bool:
    """True if `resolved` is `root` or inside it, tolerating case-insensitive volumes."""
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        pass
    root_cf = str(root).rstrip(os.sep).lower()
    cand_cf = str(resolved).lower()
    if cand_cf == root_cf or cand_cf.startswith(root_cf + os.sep):
        return True
    try:
        return resolved.exists() and root.exists() and os.path.samefile(resolved, root)
    except OSError:
        return False


def _check_export_dir_safe(resolved: Path) -> None:
    """Raise if `resolved` (already absolute + resolved) falls inside a private working root."""
    from obed_edom.baseline import cache_root  # noqa: PLC0415

    output = output_root().resolve()
    for root_name in _PRIVATE_ROOT_NAMES:
        private_root = output / root_name
        if _within_root(resolved, private_root):
            raise ValueError(f"Export directory cannot be inside {private_root}")

    if _within_root(resolved, cache_root().resolve()):
        raise ValueError(f"Export directory cannot be inside {cache_root()}")


def validate_export_dir(raw: str | Path) -> Path:
    """Resolve an owner-chosen export destination, rejecting private working roots."""
    resolved = Path(str(raw)).expanduser()
    if not resolved.is_absolute():
        raise ValueError(f"Export directory must be an absolute path: {raw}")
    resolved = resolved.resolve()

    _check_export_dir_safe(resolved)

    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Export directory is not a directory: {resolved}")

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create export directory {resolved}: {exc}") from exc

    return resolved


def ensure_export_dir(path: str | Path) -> Path:
    """Re-resolve and re-validate an export directory immediately before a deliverable write.

    Defends against a symlink swapped into place after the original `validate_export_dir`
    (or `export_destination`) call approved the path.
    """
    resolved = Path(str(path)).expanduser().resolve()
    _check_export_dir_safe(resolved)
    if not resolved.is_dir():
        raise ValueError(f"Export directory is no longer a directory: {resolved}")
    return resolved


def export_destination(job) -> Path:
    """Job override, else the operator default, else `output_root()`.

    Raises `ValueError` with an actionable message when a chosen directory (override or
    default) has since vanished or turned into a file — the export should fail rather than
    silently redirect into `output_root()`.
    """
    from obed_edom.settings import load_settings  # noqa: PLC0415

    result = getattr(job, "result", None)
    override = (result or {}).get("exportDir")
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            return candidate
        raise ValueError(
            f"Export folder {candidate} no longer exists — pick another in Settings / Export to…"
        )

    default_dir = (load_settings().get("defaultExportDir") or "").strip()
    if default_dir:
        candidate = Path(default_dir)
        if candidate.is_dir():
            return candidate
        raise ValueError(
            f"Export folder {candidate} no longer exists — pick another in Settings / Export to…"
        )

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

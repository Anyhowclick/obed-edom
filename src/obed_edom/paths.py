from __future__ import annotations

from pathlib import Path


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2], Path.cwd(), *Path.cwd().parents]
    for path in candidates:
        if (path / "pyproject.toml").is_file() and (path / "src" / "obed_edom").is_dir():
            return path
    return Path.cwd()


def template_path(relative: str) -> Path:
    return find_repo_root() / relative


def resolve_keynote_template(
    path: str | Path | None,
    *,
    fallback_rel: str | None = None,
) -> Path:
    """Prefer an explicit .key path; otherwise the repo-relative masters.yaml default."""
    tried: list[Path] = []
    if path:
        raw = Path(str(path)).expanduser()
        tried.append(raw)
        if raw.exists():
            return raw.resolve()
        if not raw.is_absolute():
            rel = template_path(str(path))
            tried.append(rel)
            if rel.exists():
                return rel.resolve()
    if fallback_rel:
        fb = template_path(fallback_rel)
        tried.append(fb)
        if fb.exists():
            return fb.resolve()
    shown = tried[-1] if tried else Path("(none)")
    raise FileNotFoundError(
        f"Template not found: {shown}. Drop an LW and/or DSK Keynote template in the "
        "dashboard, or pass --lw-template and/or --dsk-template."
    )


def select_deck_template(
    path: str | Path | None,
    *,
    fallback_rel: str | None = None,
    allow_fallback: bool = True,
) -> Path | None:
    """Resolve a deck template, or None to skip that deck."""
    if path:
        return resolve_keynote_template(path)
    if not allow_fallback or not fallback_rel:
        return None
    try:
        return resolve_keynote_template(None, fallback_rel=fallback_rel)
    except FileNotFoundError:
        return None

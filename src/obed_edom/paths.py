from __future__ import annotations

from pathlib import Path


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2], Path.cwd(), *Path.cwd().parents]
    for path in candidates:
        if (path / "Default Templates").is_dir():
            return path
    return Path.cwd()


def template_path(relative: str) -> Path:
    return find_repo_root() / relative

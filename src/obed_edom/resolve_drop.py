from __future__ import annotations

import subprocess
from pathlib import Path


def package_size(path: Path) -> int:
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    total = 0
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
    return total


def pick_drop_path(name: str, size: int | None, candidates: list[Path]) -> Path | None:
    """Choose a unique filesystem path for a dropped Keynote name."""
    want = Path(name).name.lower()
    hits = [Path(p) for p in candidates if Path(p).name.lower() == want and Path(p).exists()]
    if size and size > 0:
        sized: list[Path] = []
        for path in hits:
            try:
                actual = package_size(path)
            except OSError:
                continue
            slack = max(4096, int(size * 0.05))
            if abs(actual - size) <= slack:
                sized.append(path)
        if len(sized) == 1:
            return sized[0]
        if sized:
            hits = sized
    if len(hits) == 1:
        return hits[0]
    prefer = [p for p in hits if "Diff-Checker" in str(p)]
    if len(prefer) == 1:
        return prefer[0]
    return None


def mdfind_name(name: str, onlyin: Path | None = None) -> list[Path]:
    safe = Path(name).name.replace('"', "")
    if not safe:
        return []
    cmd = ["mdfind"]
    if onlyin:
        cmd.extend(["-onlyin", str(onlyin)])
    cmd.append(f'kMDItemFSName == "{safe}"c')
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=8)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[Path] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line:
            out.append(Path(line))
    return out


def resolve_dropped_keynote(name: str, size: int | None = None) -> Path | None:
    home = Path.home()
    candidates = mdfind_name(name, onlyin=home)
    return pick_drop_path(name, size, candidates)

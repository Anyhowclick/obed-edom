#!/usr/bin/env python3
"""Build the `p2-loop` gate fixture: a copy of the P2 adversarial export with Keynote's
Repeat -> Loop key (`"loopMode":"looping"`, the only change such an export carries) spliced
into the named movies, byte-for-byte everywhere else.

Reads `output/fixtures/p2-recovery/html-adversarial` or its binary-counter copy `output/fixtures/p2-binary`
(never written; every source file's sha is asserted equal before and after) and writes
`output/fixtures/p2-loop` in the main checkout. A source `fixture.json` is copied with a `loop` key
added. Refuses to overwrite an existing fixture unless `--force`.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom import live_continuity  # noqa: E402
from obed_edom.fixture_paths import fixture  # noqa: E402

TREES = ("html-player", "html-unmodified")
FILES = ("asset-replace.json",)
LOOP_OBJECT_IDS = ("6BB39942", "CBACAF27", "F9AFED1B", "98D59E27", "E4728E7D")
LOOP_KEY = ',"loopMode":"looping"'
EXPECTED_PLAN_SHA256 = {
    "off": "866de785864ad19b11ecd8cdfb4ad1729798ccf9f1764aa59718de03034ba7a5",
    "on": "d860a09f4f6a8e24a81e2ad0c3b37bc8a3f2b4ce3947836ca315671031870131",
}
RECORD = "loop-splice.json"
MANIFEST = "fixture.json"
LOOP_FRAMES = 1381

MOVIE_OBJECT = re.compile(r'"movie":\{[^{}]*\}')
JSONP = re.compile(r"\A(\w+\(\s*)(.*?)(\s*\)\s*)\Z", re.DOTALL)


class FixtureError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_shas(source: Path) -> dict[str, str]:
    paths = [source / name for name in FILES]
    if (source / MANIFEST).is_file():
        paths.append(source / MANIFEST)
    for tree in TREES:
        paths.extend(sorted(p for p in (source / tree).rglob("*") if p.is_file()))
    missing = [str(p) for p in paths if not p.is_file()]
    if missing or not all((source / tree).is_dir() for tree in TREES):
        raise FixtureError(f"source is incomplete: {missing or [str(source / t) for t in TREES]}")
    return {str(p.relative_to(source)): sha256_file(p) for p in paths}


def _movie_nodes(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("movie"), dict):
            yield node
        for value in node.values():
            yield from _movie_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _movie_nodes(item)


def _target(node: dict[str, Any], object_ids: tuple[str, ...]) -> str | None:
    object_id = node.get("objectID")
    prefix = object_id.split("-")[0] if isinstance(object_id, str) else None
    return prefix if prefix in object_ids else None


def _split(text: str, jsonp: bool) -> tuple[str, str, str, Any]:
    if not jsonp:
        return "", text, "", json.loads(text)
    match = JSONP.match(text)
    if match is None:
        raise FixtureError("not a jsonp wrapper")
    head, payload, tail = match.groups()
    wrapper = json.loads(payload)
    if not isinstance(wrapper, dict) or set(wrapper) != {"name", "json"}:
        raise FixtureError("jsonp payload is not {name, json}")
    return head, payload, tail, wrapper["json"]


def splice_text(text: str, object_ids: tuple[str, ...], *, jsonp: bool = False) -> tuple[str, list[str]]:
    """Insert `LOOP_KEY` before the closing brace of each targeted flat `"movie":{...}` object."""
    _, _, _, data = _split(text, jsonp)
    nodes = list(_movie_nodes(data))
    matches = list(MOVIE_OBJECT.finditer(text))
    if len(matches) != len(nodes):
        raise FixtureError(f"{len(matches)} flat movie object(s) in the text, {len(nodes)} movie node(s) parsed")
    touched: list[str] = []
    pieces: list[str] = []
    cursor = 0
    for node, match in zip(nodes, matches):
        if json.loads(match.group(0)[len('"movie":'):]) != node["movie"]:
            raise FixtureError(f"movie object at offset {match.start()} is not its node's movie in parse order")
        prefix = _target(node, object_ids)
        if prefix is None:
            continue
        if "loopMode" in node["movie"]:
            raise FixtureError(f"movie {prefix} already carries loopMode")
        pieces.extend([text[cursor:match.end() - 1], LOOP_KEY])
        cursor = match.end() - 1
        touched.append(prefix)
    pieces.append(text[cursor:])
    return "".join(pieces), touched


def check_splice(before: str, after: str, object_ids: tuple[str, ...], *, jsonp: bool = False) -> None:
    """The semantic diff is exactly the added key on the targeted movies (F1's shape)."""
    head, _, tail, expected = _split(before, jsonp)
    expected = copy.deepcopy(expected)
    for node in _movie_nodes(expected):
        if _target(node, object_ids):
            node["movie"]["loopMode"] = "looping"
    after_head, _, after_tail, actual = _split(after, jsonp)
    if actual != expected or (after_head, after_tail) != (head, tail):
        raise FixtureError("spliced file differs from its source by more than the loop key")
    if len(after.encode()) - len(before.encode()) != len(LOOP_KEY) * sum(
        1 for node in _movie_nodes(expected) if _target(node, object_ids)
    ):
        raise FixtureError("spliced file grew by other than the inserted keys")


def slide_files(tree: Path) -> list[Path]:
    header = json.loads((tree / "assets" / "header.json").read_text())
    files = []
    for uuid in header["slideList"]:
        for suffix in (".json", ".jsonp"):
            files.append(tree / "assets" / uuid / f"{uuid}{suffix}")
    return files


def splice_tree(tree: Path, root: Path, object_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    records = []
    found: dict[str, list[str]] = {}
    for path in slide_files(tree):
        jsonp = path.suffix == ".jsonp"
        before = path.read_bytes().decode("utf-8")
        after, touched = splice_text(before, object_ids, jsonp=jsonp)
        if not touched:
            continue
        check_splice(before, after, object_ids, jsonp=jsonp)
        path.write_bytes(after.encode("utf-8"))
        for prefix in touched:
            found.setdefault(prefix, []).append(path.name)
        records.append({
            "path": str(path.relative_to(root)), "objectIds": touched,
            "preSha256": hashlib.sha256(before.encode()).hexdigest(), "postSha256": sha256_file(path),
        })
    for path in slide_files(tree):
        if path.suffix == ".jsonp":
            payload = _split(path.read_bytes().decode("utf-8"), True)[3]
            if payload != json.loads(path.with_suffix(".json").read_bytes()):
                raise FixtureError(f"{path.relative_to(root)} payload differs from its .json")
    wrong = {prefix: files for prefix, files in found.items() if len(files) != 2}
    missing = sorted(set(object_ids) - set(found))
    if wrong or missing:
        raise FixtureError(f"{tree.name}: each movie must be spliced in one .json and one .jsonp; wrong={wrong} missing={missing}")
    return records


def load_slides(export_root: Path) -> list[dict[str, Any]]:
    header = json.loads((export_root / "assets" / "header.json").read_text())
    return [
        {"originalOrdinal": index + 1, "playerIndex": index, "exportedUuid": slide, "skipped": False}
        for index, slide in enumerate(header["slideList"])
    ]


def _resolve(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise FixtureError(f"{relative!r} escapes {root}")
    return path


def read_manifest(source: Path) -> dict[str, Any] | None:
    path = source / MANIFEST
    if not path.is_file():
        return None
    manifest = json.loads(path.read_bytes())
    frames = [movie.get("frames") for movie in manifest.get("movies") or []]
    if not frames or any(f != LOOP_FRAMES for f in frames):
        raise FixtureError(f"{path}: movie frames {frames} are not the loop period {LOOP_FRAMES}")
    if "loop" in manifest:
        raise FixtureError(f"{path} already carries a loop key")
    return manifest


def plan_shas(export_root: Path) -> dict[str, str]:
    """Both flag states' runtime-plan shas, whether or not the allowlist admits them yet."""
    slides = load_slides(export_root)
    real = live_continuity.plan_signature
    shas: dict[str, str] = {}
    for name, gl in (("off", False), ("on", True)):
        seen: list[str] = []

        def record(runtime: dict[str, Any]) -> str:
            seen.append(real(runtime))
            return seen[-1]

        plan = live_continuity.derive_plan(export_root, slides, resolver=_resolve, gl_replay=gl)
        if isinstance(plan, live_continuity.Unsupported):
            raise FixtureError(f"{export_root.name} does not derive (gl_replay={gl}): {plan.reason}")
        with mock.patch.object(live_continuity, "plan_signature", record):
            runtime = plan.to_runtime()
        if len(seen) != 1:
            reason = runtime.reason if isinstance(runtime, live_continuity.Unsupported) else "signature not taken once"
            raise FixtureError(f"{export_root.name} runtime has no signature (gl_replay={gl}): {reason}")
        shas[name] = seen[0]
    return shas


def build(
    source: Path, dest: Path, *, force: bool = False, object_ids: tuple[str, ...] = LOOP_OBJECT_IDS,
    expected_shas: dict[str, str] | None = EXPECTED_PLAN_SHA256,
) -> dict[str, Any]:
    source, dest = source.resolve(), dest.resolve()
    if dest == source or source in dest.parents or dest in source.parents:
        raise FixtureError(f"destination {dest} overlaps the read-only source {source}")
    if dest.exists() and not force:
        raise FixtureError(f"{dest} exists; pass --force to rebuild it")
    manifest = read_manifest(source)
    before = source_shas(source)
    partial = dest.with_name(dest.name + ".partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    try:
        for name in FILES:
            shutil.copy2(source / name, partial / name)
        files = []
        for tree in TREES:
            shutil.copytree(source / tree, partial / tree)
            files.extend(splice_tree(partial / tree, partial, object_ids))
        shas = {tree: plan_shas(partial / tree) for tree in TREES}
        if shas[TREES[0]] != shas[TREES[1]]:
            raise FixtureError(f"the two trees derive different plans: {shas}")
        if expected_shas is not None and shas[TREES[0]] != expected_shas:
            raise FixtureError(f"derived plan shas {shas[TREES[0]]} are not the pinned {expected_shas}")
        after = source_shas(source)
        if after != before:
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            raise FixtureError(f"read-only source changed during the build: {changed}")
        record = {
            "source": str(source), "sourceSha256": before, "sourceUnchanged": True,
            "objectIds": list(object_ids), "loopKey": LOOP_KEY, "files": files,
            "planSha256": shas[TREES[0]],
        }
        (partial / RECORD).write_text(json.dumps(record, indent=2) + "\n")
        if manifest is not None:
            manifest["replaced"] = [r for r in manifest.get("replaced") or [] if Path(r["path"]).parts[0] in TREES]
            manifest["loop"] = {"objectIds": list(object_ids), "planSha256": shas[TREES[0]]}
            (partial / MANIFEST).write_text(json.dumps(manifest, indent=1))
        if dest.exists():
            shutil.rmtree(dest)
        partial.rename(dest)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return record


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=fixture("p2-recovery") / "html-adversarial")
    parser.add_argument("--dest", type=Path, default=fixture("p2-loop"))
    parser.add_argument("--force", action="store_true", help="replace an existing destination")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        record = build(args.source, args.dest, force=args.force)
    except FixtureError as exc:
        print(f"loop fixture: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"dest": str(args.dest.resolve()), "files": len(record["files"]), "planSha256": record["planSha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

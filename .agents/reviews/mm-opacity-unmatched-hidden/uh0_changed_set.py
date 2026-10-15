#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


EXPECTED = {
    ("f2350147870865e13a6a4e588c1d3b06f50ed18204520b4283dc8f67e0717b66", 7),
    ("f2350147870865e13a6a4e588c1d3b06f50ed18204520b4283dc8f67e0717b66", 8),
}


def _load_candidate(repo: Path):
    spec = importlib.util.spec_from_file_location("candidate_live_runtime_tests", repo / "tests/test_live_runtime.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_base(repo: Path, base: str) -> tuple[dict, str]:
    source = subprocess.run(
        ["git", "show", f"{base}:tests/test_live_runtime.py"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "def _chain_opacity(parent, node: dict):\n    if parent is None:\n        return None\n    value = _node_opacity(node)" not in source:
        raise RuntimeError(f"{base} does not contain the expected pre-zero _chain_opacity mirror")
    namespace = {
        "__file__": str(repo / "tests/test_live_runtime.py"),
        "__name__": "base_live_runtime_tests",
    }
    exec(compile(source, namespace["__file__"], "exec"), namespace)
    return namespace, hashlib.sha256(source.encode()).hexdigest()


def _export_jsons(root: Path) -> list[Path]:
    exports = sorted({header.parent.parent for header in root.rglob("assets/header.json")})
    return [path for export in exports for path in sorted((export / "assets").glob("*/*.json"))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--old-f2", type=Path, required=True)
    parser.add_argument("--current-f2", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path[:0] = [str(repo), str(repo / "src")]
    candidate = _load_candidate(repo)
    base, base_sha = _load_base(repo, args.base)

    source_paths = {
        "main_output_fixtures": _export_jsons(candidate.MAIN_OUTPUT / "fixtures"),
        "old_f2": _export_jsons(args.old_f2.resolve()),
        "current_f2": _export_jsons(args.current_f2.resolve()),
    }
    seen: set[str] = set()
    changes = []
    effect_count = leaf_count = 0
    source_counts = {}
    for source_name, paths in source_paths.items():
        source_effects = source_leaves = 0
        for path in paths:
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            for effect in candidate._effects(data):
                if effect["type"] != "transition" or effect["name"] not in candidate.EB_EFFECTS:
                    continue
                fingerprint = candidate._effect_fingerprint(effect)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                base_rows = base["_opacity_rows"](effect)
                candidate_rows = candidate._opacity_rows(effect)
                if len(base_rows) != len(candidate_rows) or any(
                    len(old_row) != len(new_row) for old_row, new_row in zip(base_rows, candidate_rows)
                ):
                    raise RuntimeError(f"mirror topology changed for {fingerprint}")
                leaves = len(base_rows[0])
                effect_count += 1
                leaf_count += leaves
                source_effects += 1
                source_leaves += leaves
                for slot in range(leaves):
                    before = [row[slot][2] for row in base_rows]
                    after = [row[slot][2] for row in candidate_rows]
                    if before != after:
                        changes.append(
                            {
                                "fingerprint": fingerprint,
                                "slot": slot,
                                "base": before,
                                "candidate": after,
                                "first_source": source_name,
                            }
                        )
        source_counts[source_name] = {
            "json_files": len(paths),
            "new_distinct_effects": source_effects,
            "new_distinct_leaves": source_leaves,
        }

    actual = {(entry["fingerprint"], entry["slot"]) for entry in changes}
    status = "PASS" if actual == EXPECTED and changes else "INCONCLUSIVE" if not changes else "FAIL"
    report = {
        "status": status,
        "base": {"revision": subprocess.run(["git", "rev-parse", f"{args.base}^{{commit}}"], cwd=args.repo, check=True, capture_output=True, text=True).stdout.strip(), "test_source_sha256": base_sha},
        "candidate_test_source_sha256": hashlib.sha256((repo / "tests/test_live_runtime.py").read_bytes()).hexdigest(),
        "sources": source_counts,
        "distinct_effects": effect_count,
        "distinct_leaves": leaf_count,
        "expected": [{"fingerprint": fingerprint, "slot": slot} for fingerprint, slot in sorted(EXPECTED)],
        "changes": changes,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

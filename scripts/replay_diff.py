"""Re-run the checker over a saved diff job and summarise the findings.

Usage: python scripts/replay_diff.py output/.diff/<job-id> [--pairs]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from obed_edom.diff_keynotes import compare_inspects


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    work = Path(sys.argv[1])
    show_pairs = "--pairs" in sys.argv
    left = json.loads((work / "left-inspect.json").read_text())
    right = json.loads((work / "right-inspect.json").read_text())
    result = compare_inspects(
        left,
        right,
        work / "left",
        work / "right",
        work / "heat-replay",
        left_label="LW",
        right_label="DSK",
        check=True,
    )
    flags = result["flags"]
    print(f"{len(flags)} flags over {len(result['pairs'])} pairs\n")
    by_rule = Counter(f.rule or f.category for f in flags)
    for rule, count in by_rule.most_common():
        print(f"{count:4d}  {rule}")
    print()
    by_sev = Counter(f.severity for f in flags)
    print("severity:", dict(by_sev))
    print()
    for flag in flags:
        if flag.severity in {"error", "warning"}:
            head = flag.message.split("\n")[0]
            print(f"[{flag.severity:7}] {flag.rule:22} {flag.location or '-':28} {head[:120]}")
    if show_pairs:
        print("\npairs:")
        for pair in result["pairs"]:
            print(
                f"  LW {pair.get('leftNumber')} <-> DSK {pair.get('rightNumbers') or pair.get('rightNumber')}"
                f"  score={pair.get('score'):.2f}" if pair.get("score") is not None else ""
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

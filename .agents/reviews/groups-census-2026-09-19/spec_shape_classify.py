"""Bucket the OBED_DUMP_SPECS group dump per offline_groups.plan todo 1."""
import json, sys
from collections import Counter

rows = [json.loads(l) for l in open(sys.argv[1])]
print(f"group specs seen by writer: {len(rows)}")
print("needs_keynote:", Counter(r["needs_keynote"] for r in rows))
missed = [r for r in rows if r["needs_keynote"] == "group-residual"]
print(f"group-residual misses: {len(missed)}")

def bucket(r):
    s = r["spec"]; u = r["union"]
    if s.get("children"):
        return "c-children"
    w, h = s.get("w"), s.get("h")
    if w is None and h is None:
        return "a-translate(no w/h)"
    if abs(float(w) - u[2]) <= 0.5 and abs(float(h) - u[3]) <= 0.5:
        return "a-translate(w/h==union)"
    return "b-scaled"

b = Counter(bucket(r) for r in missed)
print("buckets:", dict(b))
seed = Counter((r["bulk_read_slide"], r["have_reported"]) for r in missed)
print("(slide bulk-read, group seed row present):", dict(seed))
print("slides by bucket:")
for k in sorted(b):
    print(" ", k, sorted({r["slide"] for r in missed if bucket(r) == k}))
a = [r for r in missed if bucket(r).startswith("a")]
print(f"\nPASS bar >=20 translate-only: {'PASS' if len(a) >= 20 else 'STOP'} ({len(a)})")

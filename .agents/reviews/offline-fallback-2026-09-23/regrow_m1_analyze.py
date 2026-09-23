"""m1 analysis: effective anchor, b_h, width delta, slide make-up, h_new predictability, fallback timing."""
import json, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, ".agents/reviews/offline-fallback-2026-09-23")
from regrow_m0_census import rows as census_rows

DUMP, LOG = "output/regrow-m1/regrow_specs.jsonl", "output/regrow-m1/run.log"
WALL = "/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key"
CG_PREV = "output/groups-measure/Full_Report_Card_CG.key"

dump = [json.loads(l) for l in open(DUMP)]
missed = [d for d in dump if d["missed"]]
print(f"autosize text specs dumped: {len(dump)}; grow-height misses: {len(missed)}")
print("missed by valign x halign:", Counter((d["valign"], d["halign"]) for d in missed))
print("missed by role:", Counter(d["spec"].get("role") for d in missed))

def cls(d):
    dy = d["stored"][1] - d["rep"][1]; h = d["rep"][3]
    for name, want in (("top", 0.0), ("middle", h / 2), ("bottom", h)):
        if abs(dy - want) <= 1.0: return name
    return f"other(dy={dy:.1f},h={h:.1f})"
print("\n(1) effective vertical anchor (stored.y - rep.y) by style valign:")
for k, n in sorted(Counter((d["valign"], cls(d)) for d in missed).items()): print("  ", k, n)

print("\n(2) b_h = (stored.x - rep.x)/rep.w by halign:")
by = defaultdict(list)
for d in missed: by[d["halign"]].append((d["stored"][0] - d["rep"][0]) / d["rep"][2] if d["rep"][2] else float("nan"))
for k, v in by.items(): print(f"   {k}: n={len(v)} min={min(v):.3f} max={max(v):.3f}")

print("\n(3) stored.w - rep.w:", Counter(round(d["stored"][2] - d["rep"][2], 1) for d in missed).most_common(5))
print("    spec.w / rep.w:", Counter(round(d["spec"]["w"] / d["rep"][2], 2) for d in missed).most_common(6))

log = open(LOG).read()
per = {int(m.group(1)): int(m.group(2)) for m in re.finditer(r"Offline-write slide (\d+): applied=\d+ missed=(\d+)", log)}
gh = Counter(d["slide"] for d in missed)
only = [s for s, n in gh.items() if per.get(s) == n]
print(f"\n(4) grow-height slides: {len(gh)}; slides whose ONLY misses are grow-height: {len(only)} -> {sorted(only)}")
print("    specs on those slides:", sum(gh[s] for s in only))
print("\n(5)", re.search(r"M1-TIMING.*", log).group(0) if "M1-TIMING" in log else "no timing line")
print("   ", re.search(r"Offline-write fallback reasons:.*", log).group(0))

wall = {r["id"]: r for r in census_rows(WALL)}
prev = {r["id"]: r for r in census_rows(CG_PREV)}
print("\n(6) h_new predictability: spec.h vs post-fallback nh (actual laid-out height), by role/halign")
rows_out = []
for d in missed:
    k = d["objId"]; p = prev.get(k); w = wall.get(k); s = d["spec"]
    if not p: rows_out.append((d["slide"], d["kindIndex"], "NO-JOIN")); continue
    rows_out.append((d["slide"], d["kindIndex"], s.get("role"), d["halign"], d["valign"],
        round(s.get("h", 0), 1), round(p["nh"], 1), round(s.get("h", 0) - p["nh"], 1),
        round(s["w"], 1), round(p["w"], 1), round(s.get("y", 0), 1), round(p["y"], 1),
        round(w["nh"], 1) if w else None, s.get("fontSize"), d["text"][:20]))
print("slide ki role halign valign spec.h nh_actual dh spec.w w_actual spec.y y_actual wall_nh font text")
for r in rows_out: print("  ", *r)
ok = [r for r in rows_out if len(r) > 3 and abs(r[7]) <= 1.0]
print(f"\n|spec.h - nh_actual| <= 1px: {len(ok)} of {len([r for r in rows_out if len(r) > 3])}")
print("dh distribution:", Counter(r[7] for r in rows_out if len(r) > 3).most_common(8))

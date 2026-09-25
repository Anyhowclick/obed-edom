#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir>   (runs host gate x3 then P2 arms, serially, from a clean pinned worktree)
G=$1; O=$2; PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python; mkdir -p $O; cd $G || exit 1
export PYTHONPATH=$G/src; F=$G/output/p2-recovery/html-adversarial
echo "commit $(git rev-parse --short HEAD) dirty=$(git status --porcelain | grep -v '^??' | wc -l | tr -d ' ')"
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha', js_sha256())"
summ(){ python3 - "$1" "$2" <<'PYEOF'
import json,sys
d=json.load(open(sys.argv[1]));print(sys.argv[2]+":",d.get("status"),d.get("error"),d.get("statusReasons"))
arms=dict(d.get("arms") or {}); arms["attach"]=d.get("attach") or {}
for k,a in arms.items(): print("  ",k,(a.get("continuity") or {}).get("mode"),(a.get("continuity") or {}).get("scale"),{n:(a.get(n) or {}).get("verdict") for n in ("continue1to2","restart2to3","continue3to4","stageFit")})
for p,v in (d.get("visible") or {}).items(): print("  ",p,(v.get("continuity") or {}).get("mode"),[(s.get("originalOrdinal"),s.get("verdict")) for s in v.get("slides") or []])
PYEOF
}
# Pre-registered expectation per P2 arm: "RED [| MAY]" -- MATCH iff RED <= observed red <= RED+MAY, all 15 findings
# reported, and the injected core sha equals the arm's (variant sha for --core-variant, else today's). "RECORD" = no set.
expect(){ $PY - "$@" <<'PYEOF'
import re,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
log,spec,args=sys.argv[1],sys.argv[2],sys.argv[3:]
text=open(log,encoding="utf-8",errors="replace").read()
found=re.findall(r"^- ([A-Za-z0-9]+): \*\*(True|False)\*\*",text,re.M)
red={n for n,v in found if v=="False"}
core=re.search(r"injected core sha256: ([0-9a-f]{64})",text)
variant=next((a.split("=",1)[1] for a in args if a.startswith("--core-variant=")),None) or next((args[i+1] for i,a in enumerate(args[:-1]) if a=="--core-variant"),None)
want_sha=variant_sha(variant) if variant else js_sha256()
sha_ok=bool(core) and core.group(1)==want_sha
print(f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}")
print(f"    findings {len(found)}/15; observed red: {sorted(red) or '{}'}")
if spec=="RECORD":
    print("    expected red: (none pre-registered) -> RECORDED" + ("" if sha_ok and len(found)==15 else " MISMATCH"))
    sys.exit()
must,_,may=spec.partition("|")
must,may=set(must.split()),set(may.split())
ok=sha_ok and len(found)==15 and must<=red<=must|may
print(f"    expected red: {sorted(must) or '{}'}" + (f" may: {sorted(may)}" if may else "") + f" -> {'MATCH' if ok else 'MISMATCH'}")
PYEOF
}
for V in 2560x1440 1600x1000 1920x1080; do
  $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json > $O/host-$V.log 2>&1; summ $O/host-$V.json "HOST $V"
done
# Host red arms (probe-owned pre-registered sets, keyed in the probe by the P2 off-plan sha): printed next to the observed set.
host_red(){ n=$(echo "$*" | tr -d ' '); $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 1920x1080 --artifact $O/host-red$n.json "$@" > $O/host-red$n.log 2>&1; python3 - "$O/host-red$n.json" "$*" <<'PYEOF'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception as e: print(f"[HOST {sys.argv[2]}] no artifact ({e}) -> MISMATCH"); sys.exit()
exp,got=d.get("expectedRedSet"),d.get("redSet")
verdict="RECORDED" if exp=="record" else ("MATCH" if isinstance(got,list) and got==exp and d.get("status")=="pass" else "MISMATCH")
print(f"[HOST {sys.argv[2]}] {d.get('redArm')} status={d.get('status')} expectedCoreSha256={d.get('expectedCoreSha256')}")
print(f"    expected red: {exp}\n    observed red: {got} -> {verdict}")
for o,c in ((d.get("arm") or {}).get("census") or {}).items():
    if c.get("unexpectedVideos") or c.get("duplicateVideos"): print(f"    slide {o}: unexpected={[v.get('src') for v in c.get('unexpectedVideos') or []]} duplicates={len(c.get('duplicateVideos') or [])}")
PYEOF
}
host_red --core-variant stash-any; host_red --strip bridge@8; host_red --strip retire@2; host_red --strip restart@6; host_red --strip glReplay@2 --gl-replay auto
run_p2(){ spec=$1; shift; n=$(echo "$*" | tr -d ' '); $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable "$@" > "$O/p2$n.log" 2>&1; echo "[P2 $*] $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$F/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$F/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; expect "$O/p2$n.log" "$spec" "$@"; }
V12="blackSurvivesAfter1to2 emptyCanvasAfter1to2 overlappingArtworkComposedAfter1to2"
run_p2 "" --wait-profile fast; run_p2 "continueThroughMovingMagicMove3to4" --wait-profile fast --disable-bridge34; run_p2 "" --wait-profile slow
run_p2 "noStrayVideo" --wait-profile fast --core-variant stash-any
run_p2 "continueThroughMovingMagicMove3to4 freezeControlCaughtByCounter" --wait-profile fast --strip bridge@8
run_p2 "refusedCarry1to2 | $V12" --wait-profile fast --strip glReplay@2
run_p2 RECORD --wait-profile fast --strip restart@6
run_p2 "" --wait-profile fast --gl-replay auto
run_p2 "glReplayCarry1to2 | $V12" --wait-profile fast --gl-replay auto --strip glReplay@2
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2; echo DONE

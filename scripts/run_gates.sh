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
# Every check below prints its evidence and returns nonzero on failure; FAIL counts them and the script exits nonzero
# at the end (a failing arm never stops the later arms).
FAIL=0; fail(){ FAIL=$((FAIL+1)); echo "    GATE FAILED: $1"; }
# Pre-registered expectation per P2 arm: the EXACT complete red set (space-separated ids, "" = none). MATCH iff
# observed red == that set, all 15 findings reported, source unchanged, `success` True exactly when the set is empty,
# and the injected core sha equals the arm's (variant sha for --core-variant, else today's). "RECORD" registers no set:
# it prints the observed set and succeeds only when those integrity checks pass; it is never a pass of the arm.
expect(){ $PY - "$@" <<'PYEOF'
import re,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
log,spec,args=sys.argv[1],sys.argv[2],sys.argv[3:]
try: text=open(log,encoding="utf-8",errors="replace").read()
except OSError as e: print(f"    no log ({e}) -> MISMATCH"); sys.exit(1)
found=re.findall(r"^- ([A-Za-z0-9]+): \*\*(True|False)\*\*",text,re.M)
red={n for n,v in found if v=="False"}
core=re.search(r"injected core sha256: ([0-9a-f]{64})",text)
success=re.search(r"^success: \*\*(True|False)\*\*",text,re.M)
unchanged=re.search(r"^Source unchanged: \*\*True\*\*",text,re.M)
variant=next((a.split("=",1)[1] for a in args if a.startswith("--core-variant=")),None) or next((args[i+1] for i,a in enumerate(args[:-1]) if a=="--core-variant"),None)
want_sha=variant_sha(variant) if variant else js_sha256()
sha_ok=bool(core) and core.group(1)==want_sha
count_ok=len(found)==15 and len({n for n,_ in found})==15
print(f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}")
print(f"    findings {len(found)}/15; source unchanged {bool(unchanged)}; success {success.group(1) if success else None}; observed red: {sorted(red) or '{}'}")
integrity=sha_ok and count_ok and bool(unchanged) and bool(success)
if spec=="RECORD":
    print(f"    expected red: (none registered) -> {'RECORDED' if integrity else 'MISMATCH'}")
    sys.exit(0 if integrity else 1)
want=set(spec.split())
ok=integrity and red==want and (success.group(1)=="True")==(not want)
print(f"    expected red: {sorted(want) or '{}'} -> {'MATCH' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
PYEOF
}
for V in 2560x1440 1600x1000 1920x1080; do
  $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json > $O/host-$V.log 2>&1 || fail "HOST $V exit $?"; summ $O/host-$V.json "HOST $V"
done
# Host red arms (probe-owned pre-registered sets, keyed in the probe by the P2 off-plan sha): printed next to the observed
# set. MATCH iff status pass and redSet == expectedRedSet; RECORDED iff status recorded on a "record" arm; both also need
# no `unknown` and expectedCoreSha256 == the arm's sha.
host_red(){ n=$(echo "$*" | tr -d ' '); $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 1920x1080 --artifact $O/host-red$n.json "$@" > $O/host-red$n.log 2>&1; rc=$?; $PY - "$O/host-red$n.json" "$rc" "$@" <<'PYEOF'
import json,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
path,rc,args=sys.argv[1],int(sys.argv[2]),sys.argv[3:]
label=" ".join(args)
try: d=json.load(open(path))
except Exception as e: print(f"[HOST {label}] no artifact ({e}) -> MISMATCH"); sys.exit(1)
variant=args[args.index("--core-variant")+1] if "--core-variant" in args else None
want_sha=variant_sha(variant) if variant else js_sha256()
exp,got,status,unknown=d.get("expectedRedSet"),d.get("redSet"),d.get("status"),d.get("unknown")
sha_ok=d.get("expectedCoreSha256")==want_sha
clean=sha_ok and not unknown and isinstance(got,list)
if exp=="record":
    ok=clean and status=="recorded" and rc==0; verdict="RECORDED" if ok else "MISMATCH"
else:
    ok=clean and status=="pass" and rc==0 and isinstance(exp,list) and got==exp; verdict="MATCH" if ok else "MISMATCH"
print(f"[HOST {label}] {d.get('redArm')} status={status} exit={rc} expectedCoreSha256={d.get('expectedCoreSha256')} ({'MATCH' if sha_ok else 'MISMATCH'} {want_sha}) unknown={unknown}")
print(f"    expected red: {exp}\n    observed red: {got} -> {verdict}")
for o,c in ((d.get("arm") or {}).get("census") or {}).items():
    if c.get("unexpectedVideos") or c.get("duplicateVideos"): print(f"    slide {o}: unexpected={[v.get('src') for v in c.get('unexpectedVideos') or []]} duplicates={len(c.get('duplicateVideos') or [])}")
sys.exit(0 if ok else 1)
PYEOF
}
for A in "--core-variant stash-any" "--strip bridge@8" "--strip retire@2" "--strip restart@6" "--strip glReplay@2 --gl-replay auto"; do
  host_red ${=A} || fail "HOST red $A"
done
run_p2(){ spec=$1; shift; n=$(echo "$*" | tr -d ' '); $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable "$@" > "$O/p2$n.log" 2>&1; rc=$?; echo "[P2 $*] exit=$rc $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$F/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$F/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; expect "$O/p2$n.log" "$spec" "$@" || fail "P2 $*"; }
run_p2 "" --wait-profile fast; run_p2 "continueThroughMovingMagicMove3to4" --wait-profile fast --disable-bridge34; run_p2 "" --wait-profile slow
run_p2 "noStrayVideo" --wait-profile fast --core-variant stash-any
run_p2 "continueThroughMovingMagicMove3to4 freezeControlCaughtByCounter" --wait-profile fast --strip bridge@8
# The two glReplay strips stay RECORD until the coordinator registers the exact observed set from the first gate run.
run_p2 RECORD --wait-profile fast --strip glReplay@2
run_p2 RECORD --wait-profile fast --strip restart@6
run_p2 "" --wait-profile fast --gl-replay auto
run_p2 RECORD --wait-profile fast --gl-replay auto --strip glReplay@2
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2; echo "DONE failed=$FAIL"
exit $(( FAIL > 0 ))

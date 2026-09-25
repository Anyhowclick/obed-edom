#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir> [--allow-record]   (runs host gate x3, host red arms, then P2 arms,
# serially, from a clean pinned worktree). Exits nonzero when any gate FAILED, or when a RECORD arm is PENDING
# registration unless --allow-record (discovery runs only) is passed.
G=$1; O=$2; ALLOW_RECORD=0; [[ "$3" == "--allow-record" ]] && ALLOW_RECORD=1
PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python; mkdir -p $O; cd $G || exit 1
export PYTHONPATH=$G/src; F=$G/output/p2-recovery/html-adversarial
if (( ALLOW_RECORD )); then
  echo "################################################################################"
  echo "## --allow-record: DISCOVERY RUN. RECORD arms are not gated; this is NOT a pass. ##"
  echo "################################################################################"
fi
echo "commit $(git rev-parse --short HEAD) dirty=$(git status --porcelain | grep -v '^??' | wc -l | tr -d ' ')"
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha', js_sha256())"
summ(){ python3 - "$1" "$2" <<'PYEOF'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception as e: print(f"{sys.argv[2]}: no artifact ({e})"); sys.exit(1)
print(sys.argv[2]+":",d.get("status"),d.get("error"),d.get("statusReasons"))
arms=dict(d.get("arms") or {}); arms["attach"]=d.get("attach") or {}
for k,a in arms.items(): print("  ",k,(a.get("continuity") or {}).get("mode"),(a.get("continuity") or {}).get("scale"),{n:(a.get(n) or {}).get("verdict") for n in ("continue1to2","restart2to3","continue3to4","stageFit")})
for p,v in (d.get("visible") or {}).items(): print("  ",p,(v.get("continuity") or {}).get("mode"),[(s.get("originalOrdinal"),s.get("verdict")) for s in v.get("slides") or []])
sys.exit(0 if d.get("status")=="pass" else 1)
PYEOF
}
# Every check prints its evidence and returns 0 (MATCH), 3 (RECORDED: integrity held, no set registered) or anything
# else (FAILED). FAIL / PENDING count them; a failing arm never stops the later arms.
FAIL=0; PENDING=0
fail(){ FAIL=$((FAIL+1)); echo "    GATE FAILED: $1"; }
tally(){ case $1 in 0) ;; 3) PENDING=$((PENDING+1)); echo "    PENDING REGISTRATION: $2";; *) fail "$2";; esac; }
# Pre-registered expectation per P2 arm: the EXACT complete red set (space-separated ids, "" = none). MATCH iff
# observed red == that set, all 15 findings reported, source unchanged, `success` True exactly when the set is empty,
# the process exit agrees (0 when the set is empty, 1 otherwise), and the injected core sha equals the arm's (variant
# sha for --core-variant, else today's). A finding rendered `**False** (inconclusive)` is never red: any inconclusive
# finding fails the arm's integrity. Under --gl-replay auto `glReplayCarry1to2` must be present and `refusedCarry1to2`
# absent (the reverse otherwise), so the GL path cannot be skipped silently. "RECORD" registers no set: it prints the
# observed set and returns 3 only when those integrity checks hold (exit 0 or 1).
expect(){ $PY - "$@" <<'PYEOF'
import re,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
log,rc,spec,args=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4:]
try: text=open(log,encoding="utf-8",errors="replace").read()
except OSError as e: print(f"    no log ({e}) -> MISMATCH"); sys.exit(1)
found=re.findall(r"^- ([A-Za-z0-9]+): \*\*(True|False)\*\*(?: \(([^)]*)\))?",text,re.M)
inconclusive=sorted(n for n,_,verdict in found if verdict=="inconclusive")
red={n for n,v,verdict in found if v=="False" and verdict!="inconclusive"}
ids={n for n,_,_ in found}
auto="--gl-replay" in args and args[args.index("--gl-replay")+1:][:1]==["auto"] or "--gl-replay=auto" in args
slot_ok=("glReplayCarry1to2" in ids and "refusedCarry1to2" not in ids) if auto else ("refusedCarry1to2" in ids and "glReplayCarry1to2" not in ids)
core=re.search(r"injected core sha256: ([0-9a-f]{64})",text)
success=re.search(r"^success: \*\*(True|False)\*\*",text,re.M)
unchanged=re.search(r"^Source unchanged: \*\*True\*\*",text,re.M)
variant=next((a.split("=",1)[1] for a in args if a.startswith("--core-variant=")),None) or next((args[i+1] for i,a in enumerate(args[:-1]) if a=="--core-variant"),None)
want_sha=variant_sha(variant) if variant else js_sha256()
sha_ok=bool(core) and core.group(1)==want_sha
count_ok=len(found)==15 and len(ids)==15
exit_ok=(rc==0)==(success is not None and success.group(1)=="True") and rc in (0,1)
print(f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}")
print(f"    exit {rc}; findings {len(found)}/15; source unchanged {bool(unchanged)}; success {success.group(1) if success else None}; 1->2 slot {'glReplayCarry1to2' if auto else 'refusedCarry1to2'} {'OK' if slot_ok else 'WRONG'}; inconclusive: {inconclusive or '{}'}; observed red: {sorted(red) or '{}'}")
integrity=sha_ok and count_ok and bool(unchanged) and bool(success) and exit_ok and slot_ok and not inconclusive
if spec=="RECORD":
    print(f"    expected red: (none registered) -> {'RECORDED' if integrity else 'MISMATCH'}")
    sys.exit(3 if integrity else 1)
want=set(spec.split())
ok=integrity and red==want and rc==(1 if want else 0)
print(f"    expected red: {sorted(want) or '{}'} -> {'MATCH' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
PYEOF
}
for V in 2560x1440 1600x1000 1920x1080; do
  $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json > $O/host-$V.log 2>&1 || fail "HOST $V exit $?"; summ $O/host-$V.json "HOST $V" || fail "HOST $V status"
done
# Host red arms (probe-owned pre-registered sets, keyed in the probe by the P2 off-plan sha). The artifact contract is
# checked in full: every key present and typed, redArm equal to the label the CLI arguments imply, expectedCoreSha256
# the arm's sha, `unknown` an empty list, the census stray/duplicate multiset reconciled with redSet, and the red and
# expected multisets equal (Counter). A "record" arm returns 3 only when all of that holds with status recorded.
host_red(){ n=$(echo "$*" | tr -d ' '); $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 1920x1080 --artifact $O/host-red$n.json "$@" > $O/host-red$n.log 2>&1; rc=$?; $PY - "$O/host-red$n.json" "$rc" "$@" <<'PYEOF'
import json,sys
from collections import Counter
sys.path.insert(0,"scripts")
from continuity_core_variants import parse_strip, variant_sha
from obed_edom.live_continuity_js import js_sha256
path,rc,args=sys.argv[1],int(sys.argv[2]),sys.argv[3:]
label=" ".join(args)
try: d=json.load(open(path))
except Exception as e: print(f"[HOST {label}] no artifact ({e}) -> MISMATCH"); sys.exit(1)
problems=[]
def strs(v): return isinstance(v,list) and all(isinstance(x,str) for x in v)
variant=args[args.index("--core-variant")+1] if "--core-variant" in args else None
strip=parse_strip(args[args.index("--strip")+1]) if "--strip" in args else None
want_arm=f"core:{variant}" if variant else f"strip:{strip[0]}"+("" if strip[1] is None else f"@{strip[1]}")
want_sha=variant_sha(variant) if variant else js_sha256()
status,arm_label,exp,got,unknown,sha=(d.get(k) for k in ("status","redArm","expectedRedSet","redSet","unknown","expectedCoreSha256"))
arm=d.get("arm"); census=arm.get("census") if isinstance(arm,dict) else None
for key in ("status","redArm","expectedRedSet","redSet","unknown","expectedCoreSha256"):
    if key not in d: problems.append(f"missing {key}")
if not isinstance(status,str): problems.append("status not a string")
if arm_label!=want_arm: problems.append(f"redArm {arm_label!r} != {want_arm!r}")
if sha!=want_sha: problems.append(f"expectedCoreSha256 {sha!r} != {want_sha}")
if not strs(unknown): problems.append("unknown not a list of strings")
elif unknown: problems.append(f"unknown {unknown}")
if not strs(got): problems.append("redSet not a list of strings")
if not (exp=="record" or strs(exp)): problems.append("expectedRedSet neither 'record' nor a list of strings")
if not (isinstance(census,dict) and census and all(isinstance(c,dict) for c in census.values())): problems.append("arm.census missing or malformed")
elif strs(got):
    strays=[r for r in got if r.startswith("stray:")]; dups=[r for r in got if r.startswith("duplicate:")]
    want_dups=[]; pool=list(strays)
    for o,c in sorted(census.items()):
        vids,dv=c.get("unexpectedVideos"),c.get("duplicateVideos")
        if not (isinstance(vids,list) and isinstance(dv,list)): problems.append(f"census slide {o} lacks unexpectedVideos/duplicateVideos"); continue
        want_dups+=[f"duplicate:slide{o}:{x.get('label') if isinstance(x,dict) else None}" for x in dv]
        for v in vids:
            src=str((v or {}).get("src") or "").lower()
            hit=next((r for r in pool if r.startswith(f"stray:slide{o}:") and (r.split(":",2)[2]=="unknown" or r.split(":",2)[2] in src)),None)
            if hit is None: problems.append(f"census stray on slide {o} ({src}) not in redSet")
            else: pool.remove(hit)
    if pool: problems.append(f"redSet strays with no census video: {pool}")
    if Counter(dups)!=Counter(want_dups): problems.append(f"redSet duplicates {sorted(dups)} != census {sorted(want_dups)}")
if exp=="record":
    ok=not problems and status=="recorded" and rc==0; verdict="RECORDED" if ok else "MISMATCH"
else:
    ok=not problems and status=="pass" and rc==0 and Counter(got)==Counter(exp); verdict="MATCH" if ok else "MISMATCH"
print(f"[HOST {label}] {arm_label} status={status} exit={rc} expectedCoreSha256={sha} (want {want_sha}) unknown={unknown}")
print(f"    expected red: {exp}\n    observed red: {got} -> {verdict}")
for p in problems: print(f"    contract: {p}")
for o,c in sorted((census or {}).items()):
    if isinstance(c,dict) and (c.get("unexpectedVideos") or c.get("duplicateVideos")): print(f"    slide {o}: unexpected={[(v or {}).get('src') for v in c.get('unexpectedVideos') or []]} duplicates={len(c.get('duplicateVideos') or [])}")
sys.exit((3 if exp=="record" else 0) if ok else 1)
PYEOF
}
for A in "--core-variant stash-any" "--strip bridge@8" "--strip retire@2" "--strip restart@6" "--strip glReplay@2 --gl-replay auto"; do
  host_red ${=A}; tally $? "HOST red $A"
done
run_p2(){ spec=$1; shift; n=$(echo "$*" | tr -d ' '); $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable "$@" > "$O/p2$n.log" 2>&1; rc=$?; echo "[P2 $*] exit=$rc $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$F/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$F/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; expect "$O/p2$n.log" "$rc" "$spec" "$@"; tally $? "P2 $*"; }
run_p2 "" --wait-profile fast; run_p2 "continueThroughMovingMagicMove3to4" --wait-profile fast --disable-bridge34; run_p2 "" --wait-profile slow
run_p2 "noStrayVideo" --wait-profile fast --core-variant stash-any
run_p2 "continueThroughMovingMagicMove3to4 freezeControlCaughtByCounter" --wait-profile fast --strip bridge@8
# The two glReplay strips stay RECORD until the coordinator registers the exact observed set from the first gate run.
run_p2 RECORD --wait-profile fast --strip glReplay@2
run_p2 RECORD --wait-profile fast --strip restart@6
run_p2 "" --wait-profile fast --gl-replay auto
run_p2 RECORD --wait-profile fast --gl-replay auto --strip glReplay@2
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2; echo "DONE failed=$FAIL pending=$PENDING"
if (( ALLOW_RECORD && PENDING )); then echo "## --allow-record: $PENDING RECORD arm(s) left ungated -- DISCOVERY RUN, NOT A PASS ##"; fi
(( FAIL == 0 && (PENDING == 0 || ALLOW_RECORD) ))

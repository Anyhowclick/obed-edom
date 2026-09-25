#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir> [--allow-record]   (runs host gate x3, host red arms, then P2 arms,
# serially, from a clean pinned worktree). Exits nonzero when any gate FAILED, or when a RECORD arm is PENDING
# registration unless --allow-record (discovery runs only) is passed.
G=$1; O=$2; ALLOW_RECORD=0; [[ "$3" == "--allow-record" ]] && ALLOW_RECORD=1
PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python; mkdir -p $O; cd $G || exit 1
export PYTHONPATH=$G/src; F=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("p2-recovery"))')/html-adversarial
Q=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("qual-decks"))')
[[ -d $F ]] || { echo "no P2 fixture at $F"; exit 1; }
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
# Pre-registered expectation per P2 arm: the EXACT complete red set and the EXACT complete inconclusive set
# (space-separated ids, "" = none). MATCH iff observed red == the red set, observed inconclusive == the inconclusive
# set, all 15 findings reported, source unchanged, `success` True exactly when both sets are empty, the process exit
# agrees (0 then, 1 otherwise), and the injected core sha equals the arm's (variant sha for --core-variant, else
# today's). A finding rendered `**False** (inconclusive)` is never red. Under --gl-replay auto `glReplayCarry1to2` must be present and `refusedCarry1to2`
# absent (the reverse otherwise), so the GL path cannot be skipped silently. The report's `Core variant:` / `Strip:` header
# lines must name the arm's own arguments ("none" when not passed), and a strip arm's injected plan sha must differ from
# the unstripped plan's (`build_continuity_plan`). "RECORD" registers no set: it prints the observed sets and returns 3
# only when those integrity checks hold with no inconclusive finding (exit 0 or 1).
expect(){ $PY - "$@" <<'PYEOF'
import hashlib,json,re,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
from obed_edom.p2_verdict import build_continuity_plan
log,rc,spec,inc_spec,args=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4],sys.argv[5:]
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
def arg(name): return next((a.split("=",1)[1] for a in args if a.startswith(name+"=")),None) or next((args[i+1] for i,a in enumerate(args[:-1]) if a==name),None)
variant,strip=arg("--core-variant"),arg("--strip")
head_core=re.search(r"^Core variant: (\S+) · injected core sha256: ",text,re.M)
head_strip=re.search(r"^Strip: (\S+) · injected plan sha256: ([0-9a-f]{64})$",text,re.M)
unstripped=hashlib.sha256(json.dumps(build_continuity_plan("--disable-bridge34" not in args)).encode()).hexdigest()
header_ok=(bool(head_core) and head_core.group(1)==(variant or "none") and bool(head_strip) and head_strip.group(1)==(strip or "none")
           and (strip is None or head_strip.group(2)!=unstripped))
want_sha=variant_sha(variant) if variant else js_sha256()
sha_ok=bool(core) and core.group(1)==want_sha
count_ok=len(found)==15 and len(ids)==15
exit_ok=(rc==0)==(success is not None and success.group(1)=="True") and rc in (0,1)
print(f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}")
print(f"    header core {head_core.group(1) if head_core else None} strip {head_strip.group(1) if head_strip else None} plan sha {head_strip.group(2) if head_strip else None} (unstripped {unstripped}) {'OK' if header_ok else 'WRONG'}")
print(f"    exit {rc}; findings {len(found)}/15; source unchanged {bool(unchanged)}; success {success.group(1) if success else None}; 1->2 slot {'glReplayCarry1to2' if auto else 'refusedCarry1to2'} {'OK' if slot_ok else 'WRONG'}; inconclusive: {inconclusive or '{}'}; observed red: {sorted(red) or '{}'}")
integrity=sha_ok and count_ok and bool(unchanged) and bool(success) and exit_ok and slot_ok and header_ok
if spec=="RECORD":
    recorded=integrity and not inconclusive
    print(f"    expected red: (none registered) -> {'RECORDED' if recorded else 'MISMATCH'}")
    sys.exit(3 if recorded else 1)
want,want_inc=set(spec.split()),set(inc_spec.split())
ok=integrity and red==want and set(inconclusive)==want_inc and rc==(1 if want or want_inc else 0)
print(f"    expected red: {sorted(want) or '{}'}; expected inconclusive: {sorted(want_inc) or '{}'} -> {'MATCH' if ok else 'MISMATCH'}")
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
# host_red runs on P2; `HOST_DECK=Dn host_red ...` runs the same arm on an S0 deck (its html-unmodified export is both
# fixture and original index: the qual decks need no asset replacement).
host_red(){ n=${HOST_DECK:-}$(echo "$*" | tr -d ' '); fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ -n ${HOST_DECK:-} ]]; then fix=$Q/$HOST_DECK/html-unmodified; idx=$fix/index.html; fi
  $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --viewport 1920x1080 --artifact $O/host-red$n.json "$@" > $O/host-red$n.log 2>&1; rc=$?; $PY - "$O/host-red$n.json" "$rc" "$@" <<'PYEOF'
import json,sys
from collections import Counter
sys.path.insert(0,"scripts")
from continuity_core_variants import parse_strip, strip_label, variant_sha
from obed_edom.live_continuity_js import js_sha256
path,rc,args=sys.argv[1],int(sys.argv[2]),sys.argv[3:]
label=" ".join(args)
try: d=json.load(open(path))
except Exception as e: print(f"[HOST {label}] no artifact ({e}) -> MISMATCH"); sys.exit(1)
problems=[]
def strs(v): return isinstance(v,list) and all(isinstance(x,str) for x in v)
variant=args[args.index("--core-variant")+1] if "--core-variant" in args else None
strip=parse_strip(args[args.index("--strip")+1]) if "--strip" in args else None
want_arm=f"core:{variant}" if variant else strip_label(*strip)
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
# S0 deck arms (plan §3.4 Q3): every (deck, arm) the probe's RED_ARM_EXPECTATIONS registers, RECORD ones included.
DECK_ARMS=(
  "D1 --strip bridge@2" "D1 --strip bridge@4" "D1 --strip pin@6"
  "D2 --strip bridge@2" "D2 --strip restart@4" "D2 --strip pin@6" "D2 --strip bridge@8"
  "D3 --strip pin@2" "D3 --strip bridge@2" "D3 --strip retire@4" "D3 --strip pin@4" "D3 --strip bridge@6"
  "D4 --core-variant wrong-instance" "D4 --core-variant fifo-reuse" "D4 --strip bridge@3" "D4 --strip pin@5"
  "D5 --core-variant stash-any" "D5 --core-variant fifo-reuse" "D5 --strip pin@2" "D5 --strip pin@4"
  "D6 --strip bridge@2" "D6 --strip retire@8"
)
for DA in "${DECK_ARMS[@]}"; do
  d=${DA%% *}; A=${DA#* }; HOST_DECK=$d host_red ${=A}; tally $? "HOST red $d $A"
done
run_p2(){ spec=$1; inc=$2; shift 2; n=$(echo "$*" | tr -d ' '); $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable "$@" > "$O/p2$n.log" 2>&1; rc=$?; echo "[P2 $*] exit=$rc $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$F/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$F/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; expect "$O/p2$n.log" "$rc" "$spec" "$inc" "$@"; tally $? "P2 $*"; }
# run_p2 "<expected red>" "<expected inconclusive>" <args>
run_p2 "" "" --wait-profile fast; run_p2 "continueThroughMovingMagicMove3to4" "" --wait-profile fast --disable-bridge34; run_p2 "" "" --wait-profile slow
# Registered post hoc from discovery r2 (8ac39a42), seen in r1 too: the stray WA0125 overlay paints at authored
# (109,795,485x273) on slide 4, overlapping the bridged movie's slide-4 rect (327,709,1266x356), so the variant itself
# corrupts the 3->4 measurement.
run_p2 "noStrayVideo continueThroughMovingMagicMove3to4" "freezeControlCaughtByCounter" --wait-profile fast --core-variant stash-any
# Registered post hoc from r2: with the bridge stripped from the injected plan the freeze bracket is skipped (True).
run_p2 "continueThroughMovingMagicMove3to4" "" --wait-profile fast --strip bridge@8
# Registered post hoc from discovery r2 (8ac39a42); r1 and r2 agree.
run_p2 "noStrayVideo refusedCarry1to2" "" --wait-profile fast --strip glReplay@2
# Registered post hoc from r2: the bridge stays in the plan, and the un-retired decoder breaks the 3->4 carry (the host
# arm agrees: red only on the b2to3 carry).
run_p2 "continueThroughMovingMagicMove3to4" "freezeControlCaughtByCounter" --wait-profile fast --strip restart@6
run_p2 "" "" --wait-profile fast --gl-replay auto
# Registered post hoc from r2.
run_p2 "glReplayCarry1to2 noStrayVideo" "" --wait-profile fast --gl-replay auto --strip glReplay@2
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2; echo "DONE failed=$FAIL pending=$PENDING"
if (( ALLOW_RECORD && PENDING )); then echo "## --allow-record: $PENDING RECORD arm(s) left ungated -- DISCOVERY RUN, NOT A PASS ##"; fi
(( FAIL == 0 && (PENDING == 0 || ALLOW_RECORD) ))

#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir> [--allow-record] [--tier dev|full]   (runs the host gates, host red arms
# and P2 arms through one queue, GATE_JOBS at a time (1..5, default 3; 1 = serial), from a clean pinned worktree, into a
# missing or empty <outdir>). --tier full (default) runs everything; --tier dev runs the 1920x1080 and 1600x1000 host
# gates and the P2 fast, --disable-bridge34 and --gl-replay auto arms, and is never a qualification pass.
# GATE_JOBS above 3 is allowed but loudly unqualified. A round refuses to start when the 1-minute load average exceeds
# GATE_MAX_START_LOAD (default 4), when OBED_H264_PATTERN_CACHE is set, or when the H.264 pattern cache cannot be
# prewarmed and re-read as a sha-verified hit for every duration, or when the load has not settled under the limit
# GATE_SETTLE_S (default 300) after the prewarm. Nothing is ever retried.
# Exit: 0 full pass; 10 dev pass; 1 when any gate FAILED, or a RECORD arm is PENDING registration unless --allow-record
# (discovery runs only); 2 when refused before anything runs.
GATE_JOBS=${GATE_JOBS:-3}
[[ $GATE_JOBS == [1-5] ]] || { echo "GATE_JOBS must be an integer in 1..5, got '$GATE_JOBS'" >&2; exit 2; }
GATE_MAX_START_LOAD=${GATE_MAX_START_LOAD:-4}
[[ $GATE_MAX_START_LOAD == <->(|.<->) ]] || {
  echo "GATE_MAX_START_LOAD must be a non-negative number, got '$GATE_MAX_START_LOAD'" >&2; exit 2; }
(( $# >= 2 )) || { echo "usage: run_gates.sh <gate-worktree> <outdir> [--allow-record] [--tier dev|full]" >&2; exit 2; }
G=${1:A}; O=${2:A}; ALLOW_RECORD=0; TIER=full; shift 2
while (( $# )); do
  case $1 in
    --allow-record) ALLOW_RECORD=1;;
    --tier) TIER=$2; shift;;
    *) echo "unknown argument '$1'" >&2; exit 2;;
  esac; shift
done
[[ $TIER == (dev|full) ]] || { echo "--tier must be dev or full, got '$TIER'" >&2; exit 2; }
if [[ -e $O && ( ! -d $O || -n "$(ls -A -- $O)" ) ]]; then
  echo "outdir $O exists and is not an empty directory; pass a fresh one (nothing under it is ever removed)" >&2; exit 2
fi
# Host gate arms per viewport (owner decision 2026-10-09): the attach arm is pinned to 1920x1080 whatever --viewport
# says, so it runs once, in the 1920x1080 gate, with the B and Voff controls; C runs at 2560x1440 and 1600x1000 (the
# host red arm --strip bridge@8 is the same removal at 1920x1080, checked stricter).
ARM_NAMES=(A B C V Voff attach)
typeset -A HOST_SKIP=(2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C)
if [[ $TIER == dev ]]; then HOST_VIEWPORTS=(1920x1080 1600x1000); else HOST_VIEWPORTS=(2560x1440 1600x1000 1920x1080); fi
for host_arm in $ARM_NAMES; do
  gates_running_arm=0
  for viewport in $HOST_VIEWPORTS; do
    (( ${${(s:,:)HOST_SKIP[$viewport]}[(Ie)$host_arm]} )) || gates_running_arm=$((gates_running_arm+1))
  done
  (( gates_running_arm )) || {
    echo "host arm $host_arm runs in no $TIER-tier host gate; every arm (null controls included) must run once a round" >&2; exit 2; }
done
if [[ $TIER == full ]]; then
  HOST_RED_ARMS=("--core-variant stash-any" "--strip bridge@8" "--strip retire@2" "--strip restart@6" "--strip glReplay@2 --gl-replay auto")
else
  HOST_RED_ARMS=()
fi
# Carry-cover gate (rubber band, 2026-10-10): P2's 3->4 bridge carry screencast; the GL poster must not show beyond the
# moving overlay. Full tier only: "<expected status> [probe args]" -- the default core must pass, today's linear overlay
# (red, --core-variant linear-bridge) and a hidden overlay (null, --carry-cover-null) must fail.
CARRY_COVER_ARMS=("pass" "fail --core-variant linear-bridge" "fail --carry-cover-null")
[[ $TIER == full ]] || CARRY_COVER_ARMS=()
# P2 arms: p2 <tier> "<expected red>" "<expected inconclusive>" <args>; tier dev runs in both tiers, full only in full.
# --skip-freeze-bracket goes on every arm but the two positive bracket arms, which must run it. As in P2 itself, the flag
# is refused on any arm that is not a red arm (--core-variant, --strip, --disable-bridge34) unless it is a DOM
# --wait-profile slow arm: a positive --gl-replay auto arm runs the bracket whatever its wait profile.
P2_ARMS=()
p2(){ [[ $TIER == full || $1 == dev ]] && P2_ARMS+=("${(j: :)${(@q)@[2,-1]}}"); }
p2 dev "" "" --wait-profile fast
p2 dev "continueThroughMovingMagicMove3to4" "" --wait-profile fast --disable-bridge34 --skip-freeze-bracket
p2 full "" "" --wait-profile slow --skip-freeze-bracket
# Registered post hoc from discovery r2 (8ac39a42), seen in r1 too: the stray WA0125 overlay paints at authored
# (109,795,485x273) on slide 4, overlapping the bridged movie's slide-4 rect (327,709,1266x356), so the variant itself
# corrupts the 3->4 measurement.
p2 full "noStrayVideo continueThroughMovingMagicMove3to4" "" --wait-profile fast --core-variant stash-any --skip-freeze-bracket
# Registered post hoc from discovery r2 (8ac39a42); r1 and r2 agree.
p2 full "noStrayVideo refusedCarry1to2" "" --wait-profile fast --strip glReplay@2 --skip-freeze-bracket
# Registered post hoc from r2: the bridge stays in the plan, and the un-retired decoder breaks the 3->4 carry (the host
# arm agrees: red only on the b2to3 carry).
p2 full "continueThroughMovingMagicMove3to4" "" --wait-profile fast --strip restart@6 --skip-freeze-bracket
p2 dev "" "" --wait-profile fast --gl-replay auto
# Registered post hoc from r2.
p2 full "glReplayCarry1to2 noStrayVideo" "" --wait-profile fast --gl-replay auto --strip glReplay@2 --skip-freeze-bracket
for p2_declaration in "${P2_ARMS[@]}"; do
  p2_words=("${(@Q)${(z)p2_declaration}}"); p2_args=("${(@)p2_words[3,-1]}")
  (( ${p2_args[(Ie)--skip-freeze-bracket]} )) || continue
  (( ${p2_args[(Ie)--core-variant]} || ${p2_args[(Ie)--strip]} || ${p2_args[(Ie)--disable-bridge34]} )) && continue
  gl_flag_at=${p2_args[(Ie)--gl-replay]}; wait_flag_at=${p2_args[(Ie)--wait-profile]}
  gl_auto=0; (( gl_flag_at )) && [[ ${p2_args[gl_flag_at+1]} == auto ]] && gl_auto=1
  wait_slow=0; (( wait_flag_at )) && [[ ${p2_args[wait_flag_at+1]} == slow ]] && wait_slow=1
  if (( gl_auto || ! wait_slow )); then
    echo "P2 ${p2_args[*]}: --skip-freeze-bracket on a positive freeze-bracket arm is refused" >&2; exit 2
  fi
done
if (( ${+OBED_H264_PATTERN_CACHE} )); then
  echo "OBED_H264_PATTERN_CACHE is set ('$OBED_H264_PATTERN_CACHE'); a round needs the shared H.264 pattern cache so no" \
    "P2 arm encodes during a timed capture -- unset it. No run launched." >&2; exit 2
fi
load1(){ local avg; avg=(${=$(sysctl -n vm.loadavg 2>/dev/null)}); [[ ${avg[2]} == <->(|.<->) ]] && print -r -- ${avg[2]}; }
START_LOAD=$(load1) || { echo "cannot read the 1-minute load average (sysctl -n vm.loadavg); no run launched" >&2; exit 2; }
if (( START_LOAD > GATE_MAX_START_LOAD )); then
  echo "1-minute load average $START_LOAD exceeds GATE_MAX_START_LOAD=$GATE_MAX_START_LOAD; a loaded host reddens timed" \
    "runs. Let it settle and start again (or set GATE_MAX_START_LOAD). No run launched." >&2; exit 2
fi
PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python; cd $G || exit 1; mkdir -p $O
export PYTHONPATH=$G/src; F=$G/output/p2-recovery/html-adversarial
if (( ALLOW_RECORD )); then
  echo "################################################################################"
  echo "## --allow-record: DISCOVERY RUN. RECORD arms are not gated; this is NOT a pass. ##"
  echo "################################################################################"
fi
if [[ $TIER == dev ]]; then
  echo "################################################################################"
  echo "## DEV TIER -- NOT A QUALIFICATION PASS (a passing dev round exits 10, never 0) ##"
  echo "################################################################################"
fi
if (( GATE_JOBS > 3 )); then
  echo "################################################################################"
  echo "## WARNING: GATE_JOBS=$GATE_JOBS. GATE_JOBS>3 is NOT qualified on this machine (2026-10-09: 5-wide pushed the P2 slide-3 restart observation to 0.479 s vs the 0.35 s limit and reddened 3->4)"
  echo "################################################################################"
fi
echo "load average (1 min) at start $START_LOAD (GATE_MAX_START_LOAD $GATE_MAX_START_LOAD)"
echo "commit $(git rev-parse --short HEAD) dirty=$(git status --porcelain | grep -v '^??' | wc -l | tr -d ' ')"
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha', js_sha256())"
# A host gate passes only with status pass, skippedArms exactly the arms run_gates skipped, every other arm present and
# every skipped arm absent; a skipped arm prints "skipped by flag" and never counts as a pass.
summ(){ python3 - "$1" "$2" "$3" <<'PYEOF'
import json,sys
names=("A","B","C","V","Voff","attach")
want_skip=[n for n in names if n in sys.argv[3].split(",")]
try: d=json.load(open(sys.argv[1]))
except Exception as e: print(f"{sys.argv[2]}: no artifact ({e})"); sys.exit(1)
print(sys.argv[2]+":",d.get("status"),d.get("error"),d.get("statusReasons"))
arms=dict(d.get("arms") or {})
if isinstance(d.get("attach"),dict): arms["attach"]=d["attach"]
for k,a in arms.items(): print("  ",k,(a.get("continuity") or {}).get("mode"),(a.get("continuity") or {}).get("scale"),{n:(a.get(n) or {}).get("verdict") for n in ("continue1to2","restart2to3","continue3to4","stageFit")})
for p,v in (d.get("visible") or {}).items(): print("  ",p,(v.get("continuity") or {}).get("mode"),[(s.get("originalOrdinal"),s.get("verdict")) for s in v.get("slides") or []])
def present(n):
    holder=d if n=="attach" else d.get("visible") if n in ("V","Voff") else d.get("arms")
    return isinstance((holder if isinstance(holder,dict) else {}).get(n),dict)
problems=[] if d.get("skippedArms")==want_skip else [f"skippedArms {d.get('skippedArms')!r} != {want_skip}"]
for n in names:
    if n in want_skip: print("  ",n,"skipped by flag")
    if present(n)==(n in want_skip): problems.append(f"{n} {'present though skipped' if present(n) else 'missing'}")
for p in problems: print("    inventory:",p)
sys.exit(0 if d.get("status")=="pass" and not problems else 1)
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
# the unstripped plan's (`build_continuity_plan`). The `Freeze bracket:` header line must read "skipped
# (--skip-freeze-bracket)" exactly when the arm passes that flag, else "skipped (bridge disabled)" under
# --disable-bridge34, else "run". "RECORD" registers no set: it prints the observed sets and returns 3
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
head_freeze=re.search(r"^Freeze bracket: (.+)$",text,re.M)
want_freeze="skipped (--skip-freeze-bracket)" if "--skip-freeze-bracket" in args else "skipped (bridge disabled)" if "--disable-bridge34" in args else "run"
header_ok=(bool(head_core) and head_core.group(1)==(variant or "none") and bool(head_strip) and head_strip.group(1)==(strip or "none")
           and (strip is None or head_strip.group(2)!=unstripped) and bool(head_freeze) and head_freeze.group(1)==want_freeze)
want_sha=variant_sha(variant) if variant else js_sha256()
sha_ok=bool(core) and core.group(1)==want_sha
count_ok=len(found)==15 and len(ids)==15
exit_ok=(rc==0)==(success is not None and success.group(1)=="True") and rc in (0,1)
print(f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}")
print(f"    header core {head_core.group(1) if head_core else None} strip {head_strip.group(1) if head_strip else None} plan sha {head_strip.group(2) if head_strip else None} (unstripped {unstripped}) freeze bracket {head_freeze.group(1) if head_freeze else None!r} (want {want_freeze!r}) {'OK' if header_ok else 'WRONG'}")
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
# Every run (host gates, host red arms, P2 arms) goes through one queue, GATE_JOBS at a time (1..5, default 3;
# GATE_JOBS=1 runs them serially), launched in the listed order. <outdir> starts empty; each run runs in its own process
# group and atomically writes <name>.rc as "<round nonce> <exit>"; a missing .rc or one from another round fails its
# check. The checks run and print in the listed order once every run has finished. Exit, HUP, INT or TERM stops the running groups (TERM, then KILL after 5 s).
NONCE="$$-$(date +%s)-$RANDOM"; PIDS=(); echo "round nonce $NONCE"
zmodload zsh/parameter
stop_jobs(){ local s g n live=(); for s in $jobstates; do [[ $s == running:* ]] && live+=(${${(s.:.)${s#*:*:}}%%=*}); done; (( ${#live} )) || return 0
  for g in $live; do kill -TERM -$g $g 2>/dev/null; done
  for n in {1..20}; do for g in $live; do kill -0 -$g 2>/dev/null && break; done || break; sleep 0.25; done
  for g in $live; do kill -KILL -$g $g 2>/dev/null; done; }
trap stop_jobs EXIT; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
JOB='out=$1 nonce=$2; shift 2; "$@" > "$out.log" 2>&1; rc=$?; print -r -- "$nonce $rc" > "$out.rc.tmp" && mv -f "$out.rc.tmp" "$out.rc"'
queue(){ local out=$1; shift
  while (( ${#PIDS} >= GATE_JOBS )); do wait $PIDS[1] 2>/dev/null; shift PIDS; done
  $PY -c 'import os,sys; os.setpgrp(); os.execv(sys.argv[1], sys.argv[1:])' /bin/zsh -fc "$JOB" job "$out" "$NONCE" "$@" &
  PIDS+=($!); }
status_of(){ local s; s=$(<"$1.rc") 2>/dev/null || { echo missing; return; }; [[ $s == "$NONCE "<-> ]] && echo ${s#"$NONCE "} || echo "stale($s)"; }
# Fill the disposable H.264 pattern cache before any timed run, so no P2 arm's ffmpeg encode overlaps a capture: every
# duration needs a cache key, and a second lookup must be a sha-verified hit of the same entry, else no run launches.
$PY - "$F/html-unmodified" <<'PYEOF' || { echo "H.264 pattern prewarm FAILED; no run launched"; exit 2; }
import sys
from pathlib import Path
sys.path.insert(0,"scripts")
from p2_recovery_html_dissolve_live import prewarm_h264_patterns
root=Path(sys.argv[1])
first=prewarm_h264_patterns(root)
if not first: sys.exit(f"no Untitled.mov-*.mov under {root}")
for r in first: print(f"h264 pattern prewarm {r['seconds']}s: {'cache hit' if r['source']=='cache' else r['source']} key={r.get('cacheKey')}")
def usable(r): return r.get("source") in ("cache","encoded") and all(isinstance(r.get(k),str) and r[k] for k in ("cacheKey","sha256"))
unusable=[r.get("seconds") for r in first if not usable(r)]
if unusable: sys.exit(f"no usable pattern cache key for {unusable} s; later P2 arms would encode during timed captures")
second={r.get("seconds"):r for r in prewarm_h264_patterns(root)}
for r in first:
    again=second.get(r["seconds"]) or {}
    if not (again.get("source")=="cache" and again.get("cacheKey")==r["cacheKey"] and again.get("sha256")==r["sha256"]):
        sys.exit(f"pattern cache re-lookup for {r['seconds']} s is not a sha-verified hit of the prewarmed entry: {again or None}")
    print(f"h264 pattern cache verified {r['seconds']}s: hit key={again['cacheKey']} sha256={again['sha256']}")
PYEOF
GATE_SETTLE_S=${GATE_SETTLE_S:-300}
[[ $GATE_SETTLE_S == <-> ]] || { echo "GATE_SETTLE_S must be a whole number of seconds, got '$GATE_SETTLE_S'" >&2; exit 2; }
settle_deadline=$((SECONDS + GATE_SETTLE_S))
while LAUNCH_LOAD=$(load1) && (( LAUNCH_LOAD > GATE_MAX_START_LOAD )); do
  (( SECONDS >= settle_deadline )) && {
    echo "1-minute load average $LAUNCH_LOAD still exceeds GATE_MAX_START_LOAD=$GATE_MAX_START_LOAD ${GATE_SETTLE_S}s after" \
      "the prewarm; no timed run launched." >&2; exit 2; }
  sleep $(( settle_deadline - SECONDS < 5 ? settle_deadline - SECONDS : 5 ))
done
[[ -n $LAUNCH_LOAD ]] || { echo "cannot read the 1-minute load average (sysctl -n vm.loadavg); no run launched" >&2; exit 2; }
echo "load average (1 min) at launch $LAUNCH_LOAD"
for V in $HOST_VIEWPORTS; do
  queue $O/host-$V $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json ${HOST_SKIP[$V]:+--skip-arms} ${HOST_SKIP[$V]}
done
check_host(){ rc=$(status_of $O/host-$1); [[ $rc == 0 ]] || fail "HOST $1 exit $rc"; summ $O/host-$1.json "HOST $1" "${HOST_SKIP[$1]}" || fail "HOST $1 status"; }
# Host red arms (probe-owned pre-registered sets, keyed in the probe by the P2 off-plan sha). The artifact contract is
# checked in full: every key present and typed, redArm equal to the label the CLI arguments imply, expectedCoreSha256
# the arm's sha, `unknown` an empty list, the census stray/duplicate multiset reconciled with redSet, and the red and
# expected multisets equal (Counter). A "record" arm returns 3 only when all of that holds with status recorded.
run_host_red(){ n=$(echo "$*" | tr -d ' '); queue $O/host-red$n $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 1920x1080 --artifact $O/host-red$n.json "$@"; }
check_host_red(){ n=$(echo "$*" | tr -d ' '); rc=$(status_of $O/host-red$n)
  [[ $rc == <-> ]] || { echo "[HOST $*] no fresh status ($rc) -> MISMATCH"; return 1; }
  $PY - "$O/host-red$n.json" "$rc" "$@" <<'PYEOF'
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
for A in $HOST_RED_ARMS; do run_host_red ${=A}; done
# A carry-cover run matches only with this round's exit (0 for pass, 1 for fail), a carry-cover artifact whose status is
# the expected one, whose control and core variant are the ones its arguments imply, and whose installed continuity core
# sha is that variant's (else today's). Inconclusive, error, no artifact, a missing or stale status: FAILED, never pending.
run_cc(){ shift; n=$(echo "$*" | tr -d ' ')
  queue $O/carry-cover$n $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport 1920x1080 --carry-cover --artifact $O/carry-cover$n.json "$@"; }
check_cc(){ label=${(j: :)@[2,-1]}; n=${label// /}; $PY - "$O/carry-cover$n.json" "$(status_of $O/carry-cover$n)" "$@" <<'PYEOF' || fail "CARRY-COVER ${label:-green}"
import json,sys
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
from obed_edom.live_continuity_js import js_sha256
path,rc,want,args=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4:]
variant=args[args.index("--core-variant")+1] if "--core-variant" in args else None
control="null" if "--carry-cover-null" in args else "red" if variant else "green"
label=" ".join(args) or "green"
try: want_sha=variant_sha(variant) if variant else js_sha256()
except Exception as e: print(f"[CARRY-COVER {label}] no expected core sha ({e}) exit={rc}"); sys.exit(1)
try: d=json.load(open(path))
except Exception as e: print(f"[CARRY-COVER {label}] no artifact ({e}) exit={rc}"); sys.exit(1)
d=d if isinstance(d,dict) else {}
sha=(d.get("continuity") or {}).get("sha256") if isinstance(d.get("continuity"),dict) else None
print(f"[CARRY-COVER {label}] control={d.get('control')} status={d.get('status')} (want {want}) exit={rc} core sha {sha} (want {want_sha})")
for r in d.get("reasons") or []: print(f"    {r}")
if d.get("error"): print(f"    error: {d['error']}")
problems=[]
if d.get("kind")!="live-continuity-probe-carry-cover": problems.append(f"not a carry-cover artifact (kind={d.get('kind')!r})")
if d.get("control")!=control: problems.append(f"control {d.get('control')!r} != {control!r}")
if d.get("coreVariant")!=variant: problems.append(f"coreVariant {d.get('coreVariant')!r} != {variant!r}")
if sha!=want_sha or d.get("coreSha256")!=want_sha: problems.append("installed core sha is not the arm's")
if d.get("status")!=want: problems.append(f"status {d.get('status')!r} != {want!r}")
if rc!=("0" if want=="pass" else "1"): problems.append(f"exit {rc} does not agree with {want}")
for p in problems: print(f"    MISMATCH: {p}")
sys.exit(1 if problems else 0)
PYEOF
}
for A in $CARRY_COVER_ARMS; do run_cc ${=A}; done
# Each P2 arm runs in its own --out-dir.
run_p2(){ shift 2; n=$(echo "$*" | tr -d ' ')
  queue "$O/p2$n" $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable --out-dir "$O/p2$n" "$@"; }
check_p2(){ spec=$1; inc=$2; shift 2; n=$(echo "$*" | tr -d ' '); rc=$(status_of "$O/p2$n"); echo "[P2 $*] exit=$rc $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$O/p2$n/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$O/p2$n/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; if [[ $rc == <-> ]]; then expect "$O/p2$n.log" "$rc" "$spec" "$inc" "$@"; else echo "    no fresh status ($rc) -> MISMATCH"; false; fi; tally $? "P2 $*"; }
for A in "${P2_ARMS[@]}"; do run_p2 "${(@Q)${(z)A}}"; done
wait
for V in $HOST_VIEWPORTS; do check_host $V; done
for A in $HOST_RED_ARMS; do check_host_red ${=A}; tally $? "HOST red $A"; done
for A in $CARRY_COVER_ARMS; do check_cc ${=A}; done
for A in "${P2_ARMS[@]}"; do check_p2 "${(@Q)${(z)A}}"; done
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2
echo "load average (1 min) at start $START_LOAD, at launch $LAUNCH_LOAD, at end $(load1 || echo unreadable); wall ${SECONDS}s"
echo "DONE tier=$TIER failed=$FAIL pending=$PENDING"
if (( ALLOW_RECORD && PENDING )); then echo "## --allow-record: $PENDING RECORD arm(s) left ungated -- DISCOVERY RUN, NOT A PASS ##"; fi
(( FAIL == 0 && (PENDING == 0 || ALLOW_RECORD) )); rc=$?
if [[ $TIER == dev ]]; then echo "## DEV TIER -- NOT A QUALIFICATION PASS (exit $(( rc ? 1 : 10 ))) ##"; exit $(( rc ? 1 : 10 )); fi
exit $rc

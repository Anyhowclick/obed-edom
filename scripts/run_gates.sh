#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir> [--allow-record] [--tier dev|full]   (runs the host gates, host red arms,
# Pass G, Pass G red, paint control, carry-cover and P2 arms through one queue, GATE_JOBS at a time (1..5, default 3; 1 = serial), from a clean pinned worktree, into a
# missing or empty <outdir>). --tier full (default) runs everything; --tier dev runs the 1920x1080 and 1600x1000 host
# gates and the P2 fast, --disable-bridge34 and --gl-replay auto arms, and is never a qualification pass.
# GATE_JOBS above 3 is allowed but loudly unqualified. A round refuses to start when the 1-minute load average exceeds
# GATE_MAX_START_LOAD (default 4), when OBED_H264_PATTERN_CACHE is set, or when the H.264 pattern cache cannot be
# prewarmed and re-read as a sha-verified hit for every duration, or when the load has not settled under the limit
# GATE_SETTLE_S (default 300) after the prewarm. Nothing is ever retried.
# Exit: 0 full pass; 10 dev pass; 1 when any gate FAILED, or a RECORD arm is PENDING registration unless --allow-record
# (discovery runs only); 2 when refused before anything runs. Paint census findings (DONE findings=N) never change it.
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
# S0 deck arms (plan §3.4 Q3): every (deck, arm) the probe's RED_ARM_EXPECTATIONS registers, run as host red arms at
# 1920x1080 on the deck's own export (HOST_DECK). Full tier only.
DECK_ARMS=(
  "D1 --strip bridge@2" "D1 --strip bridge@4" "D1 --strip pin@6"
  "D2 --strip bridge@2" "D2 --strip restart@4" "D2 --strip pin@6" "D2 --strip bridge@8"
  "D3 --strip pin@2" "D3 --strip bridge@2" "D3 --strip retire@4" "D3 --strip pin@4" "D3 --strip bridge@6"
  "D4 --core-variant wrong-instance" "D4 --core-variant fifo-reuse" "D4 --strip bridge@3" "D4 --strip pin@5"
  "D5 --core-variant stash-any" "D5 --core-variant fifo-reuse" "D5 --strip pin@2" "D5 --strip pin@4"
  "D6 --strip bridge@2" "D6 --strip retire@8"
)
# Painted-instrument red arm (S2 instrument plan §4/§5, §3.11): the pin hold off on D5. Prediction, PENDING owner
# sign-off (first registration; probe-owned RED_ARM_EXPECTATIONS, not measured on the landed core until V3): red set
# exactly (b0to1 A carry, b1to2 A carry), each with a longest unpainted run of at least 60 frames (decision 3; ~108
# expected at 1920x1080). Source (older core, trace wraps on): main checkout output/evidence/s2-dev/pingap/r9-D5-seq.json
# (108 frames / 1813 ms at layer16 opacity 0; 107 / 1834 ms at layer78). Until the probe registers it the arm reads
# unregistered and FAILS.
# TODO(decision 11): add "D2 --core-variant no-pin-hold" (D2 b2to3, ~108; pingap r10-D2-seq.json) and
# "D3 --core-variant no-pin-hold" (D3 b0to1 A, ~108; pingap c7-D3seq-ctl.json) only after V3 measures them.
DECK_ARMS+=("D5 --core-variant no-pin-hold")
[[ $TIER == full ]] || DECK_ARMS=()
# Pass G (plan §3.4 Q3; owner 2026-10-10): the plan-derived go-to gate, armed + null control, on P2 and each S0 deck.
# Full tier only.
PASSG_FIXTURES=(P2 D1 D2 D3 D4 D5 D6)
[[ $TIER == full ]] || PASSG_FIXTURES=()
# Pass G red (S2 instrument plan §3.9/§5, §3.11): "<deck> <probe args>", the advance legs scored per frame under a core
# variant. Prediction, PENDING owner sign-off (first registration; probe-owned PASSG_RED_EXPECTATIONS, measured on the
# landed core only at V3): D1 no-pin-hold reds exactly the (1,3,4) leg's b2to3 carry, longest unpainted run at least
# 60 frames (decision 3; ~108 expected), and leaves (2,1,2) and (1,2,3) green. Source (older core, trace wraps on):
# main checkout output/evidence/s2-dev/pingap/r1-a2g3-1080.json (108/1814), r3-g3from1-1080.json (108/1811),
# r4-g3from4-1080.json (108/1811), c1-a2g3-1080-ctl.json (108/1813), r7-a2g3-1440.json (2560: 108/1817); r5-g2-1080.json
# and c6-g1-ctl-*.json 0. The pre-pin-hold core red runs once outside this script (decision 7). Full tier only.
PASSG_RED_ARMS=("D1 --core-variant no-pin-hold")
[[ $TIER == full ]] || PASSG_RED_ARMS=()
# Painted-instrument positive control (S2 instrument plan §3.10/§4/§5): "<deck> <N:VARIANT:PHASE@SCENE[:late]>". The
# injected N-frame hide must read as exactly the injected seq set on the target carry and nowhere else; N=0 is the
# injector's null (armed, nothing hidden, every count 0). The late timing makes the pre-paint phase load-bearing.
# Full tier only.
PAINT_CONTROL_ARMS=("D5 6:ancestor-opacity:pin@2" "D5 6:ancestor-opacity:pin@2:late" "D5 0:ancestor-opacity:pin@2")
[[ $TIER == full ]] || PAINT_CONTROL_ARMS=()
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
# Re-registered on core v6 (owner-approved 2026-10-09; S1 set "noStrayVideo continueThroughMovingMagicMove3to4"). The
# stashed slide-1 untitled.mov remounts across the refused 1->2 boundary (15 carry events in the retire zone) and
# lingers, as in the v6 host set (slide-1 retire plus strays on slides 2-4); the WA0125 overlay still paints on slide 4
# over the bridged movie's rect and corrupts the 3->4 measurement. Evidence (main checkout): rebased head
# output/evidence/s2-dev/p2-4a2ea70f/, identical on the pre-rebase control output/evidence/s2-dev/p2ctrl-089a0393/ (a
# v6-core change, not #238). That run's inconclusive freeze-bracket finding is gone: this arm skips the bracket.
p2 full "refusedCarry1to2 overlayRemovedOnLeave preserveDidNotBlockRestart continueThroughMovingMagicMove3to4 noStrayVideo" "" --wait-profile fast --core-variant stash-any --skip-freeze-bracket
# Re-registered on core v6 (owner-approved 2026-10-09: re-register, not an instrument change; S1 set "noStrayVideo
# refusedCarry1to2"). preserveDidNotBlockRestart is an INSTRUMENT FALSE RED: every negative clause is clean (empty pool
# census, zero carries in the zone, no reuse after the boundary); only the positive "never pooled" route fails, because
# with the entry stripped v6 never names slide 1's decoder, so no preserve-refused note fires (refusalEventsN 0, baseline
# 2). noStrayVideo is green: v6 no longer FIFO-pools an unnamed decoder. Evidence (main checkout):
# output/evidence/s2-dev/p2-4a2ea70f/, identical on the pre-rebase control output/evidence/s2-dev/p2ctrl-089a0393/.
p2 full "refusedCarry1to2 preserveDidNotBlockRestart" "" --wait-profile fast --strip glReplay@2 --skip-freeze-bracket
# Re-registered on core v6 (owner-approved 2026-10-09; S1 set "continueThroughMovingMagicMove3to4"): all green. Slide 2's
# source is retired at 2 and never carried, so the restart@6 entry is inert under v6, as the host arm's v6 set () says.
# This arm therefore no longer shows that P2 depends on the restart entry. Evidence (main checkout):
# output/evidence/s2-dev/p2-4a2ea70f/, identical on the pre-rebase control output/evidence/s2-dev/p2ctrl-089a0393/.
p2 full "" "" --wait-profile fast --strip restart@6 --skip-freeze-bracket
p2 dev "" "" --wait-profile fast --gl-replay auto
# Re-registered on core v6 (owner-approved 2026-10-09; S1 set "glReplayCarry1to2 noStrayVideo"): the same mechanism as
# the GL-off --strip glReplay@2 arm (preserveDidNotBlockRestart an instrument false red; noStrayVideo green). Evidence
# (main checkout): output/evidence/s2-dev/p2-4a2ea70f/; not re-run on the pre-rebase control
# output/evidence/s2-dev/p2ctrl-089a0393/ (same mechanism as the GL-off arm, which was).
p2 full "glReplayCarry1to2 preserveDidNotBlockRestart" "" --wait-profile fast --gl-replay auto --strip glReplay@2 --skip-freeze-bracket
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
export PYTHONPATH=$G/src; F=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("p2-recovery"))')/html-adversarial
Q=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("qual-decks"))')
[[ -d $F ]] || { echo "no P2 fixture at $F; no run launched" >&2; exit 2; }
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
# Every run (host gates, host red arms, Pass G, P2 arms) goes through one queue, GATE_JOBS at a time (1..5, default 3;
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
check_host(){ rc=$(status_of $O/host-$1); [[ $rc == 0 ]] || fail "HOST $1 exit $rc"; summ $O/host-$1.json "HOST $1" "${HOST_SKIP[$1]}" || fail "HOST $1 status"
  paint_report $O/host-$1.json "HOST $1"; }
# Host red arms (probe-owned pre-registered sets, keyed in the probe by the P2 off-plan sha). The artifact contract is
# checked in full: every key present and typed, redArm equal to the label the CLI arguments imply, expectedCoreSha256
# the arm's sha, `unknown` an empty list, the census stray/duplicate multiset reconciled with redSet, and the red and
# expected multisets equal (Counter). A "record" arm returns 3 only when all of that holds with status recorded.
# run_host_red runs on P2; `HOST_DECK=Dn run_host_red ...` runs the same arm on an S0 deck (its html-unmodified export is
# both fixture and original index: the qual decks need no asset replacement). check_host_red takes the same HOST_DECK.
run_host_red(){ n=${HOST_DECK:-}$(echo "$*" | tr -d ' '); fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ -n ${HOST_DECK:-} ]]; then fix=$Q/$HOST_DECK/html-unmodified; idx=$fix/index.html; fi
  queue $O/host-red$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --viewport 1920x1080 --artifact $O/host-red$n.json "$@"; }
check_host_red(){ n=${HOST_DECK:-}$(echo "$*" | tr -d ' '); rc=$(status_of $O/host-red$n)
  [[ $rc == <-> ]] || { echo "[HOST ${HOST_DECK:+$HOST_DECK }$*] no fresh status ($rc) -> MISMATCH"; return 1; }
  $PY - "$O/host-red$n.json" "$rc" "$@" <<'PYEOF'
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
sampler=arm.get("sampler") if isinstance(arm,dict) else None
if not (isinstance(sampler,dict) and sampler.get("schema")==2 and isinstance(sampler.get("selfCheck"),dict) and sampler["selfCheck"].get("ok") is True):
    problems.append("arm.sampler is not schema 2 with selfCheck.ok")
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
  local r=$?; paint_report "$O/host-red$n.json" "HOST ${HOST_DECK:+$HOST_DECK }$*"; return $r; }
for A in $HOST_RED_ARMS; do run_host_red ${=A}; done
for DA in "${DECK_ARMS[@]}"; do d=${DA%% *}; A=${DA#* }; HOST_DECK=$d run_host_red ${=A}; done
# A Pass G run passes only with this round's exit 0 and a Pass G artifact whose top-level status is pass; anything else
# (fail, inconclusive, error, no artifact, a missing or stale status) is FAILED, never pending.
run_passg(){ fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ $1 != P2 ]]; then fix=$Q/$1/html-unmodified; idx=$fix/index.html; fi
  queue $O/passG-$1 $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --pass G --artifact $O/passG-$1.json; }
check_passg(){ $PY - "$O/passG-$1.json" "$1" "$(status_of $O/passG-$1)" <<'PYEOF' || fail "PASSG $1"
import json,sys
path,name,rc=sys.argv[1:]
try: d=json.load(open(path))
except Exception as e: print(f"[PASSG {name}] no artifact ({e}) exit={rc}"); sys.exit(1)
d=d if isinstance(d,dict) else {}
print(f"[PASSG {name}] status={d.get('status')} exit={rc}")
if d.get("pass")!="G": print(f"    not a Pass G artifact (pass={d.get('pass')!r})")
for r in d.get("reasons") or []: print(f"    {r}")
if d.get("error"): print(f"    error: {d['error']}")
sys.exit(0 if rc=="0" and d.get("pass")=="G" and d.get("status")=="pass" else 1)
PYEOF
  paint_report "$O/passG-$1.json" "PASSG $1"; }
for P in $PASSG_FIXTURES; do run_passg $P; done
# Painted-instrument report (S2 instrument plan §5), report only: per scored carry its unpainted/partial/double/substitute
# frames and longest run, each sampler's schema and selfCheck, and every paint census entry, which is a finding whatever
# its class (endOfShow included; decision 8) and is appended to <outdir>/paint-findings.txt for the DONE line.
paint_report(){ $PY - "$1" "$2" "$O/paint-findings.txt" <<'PYEOF'
import json,sys
path,label,sink=sys.argv[1:]
try: d=json.load(open(path))
except Exception: sys.exit(0)
d=d if isinstance(d,dict) else {}
def entries():
    for k,a in (d.get("arms") if isinstance(d.get("arms"),dict) else {}).items(): yield f"arm {k}",a
    for k in ("attach","arm"): yield k,d.get(k)
    for s in ("armed","nullControl"):
        sess=d.get(s) if isinstance(d.get(s),dict) else {}
        yield s,sess
        for dest in sess.get("destinations") or []:
            dest=dest if isinstance(dest,dict) else {}
            yield f"{s} goTo {dest.get('fromOrdinal')}->{dest.get('toOrdinal')} advance",dest.get("advanceCarry")
def run_of(p): r=p.get("longestRun"); return r.get("frames") if isinstance(r,dict) else r
with open(sink,"a") as out:
    for where,e in entries():
        if not isinstance(e,dict): continue
        s=e.get("sampler")
        if isinstance(s,dict): print(f"    [{label}] {where} sampler schema={s.get('schema')} selfCheck.ok={(s.get('selfCheck') or {}).get('ok') if isinstance(s.get('selfCheck'),dict) else None}")
        scored=list(e.items())+list((e.get("verdicts") if isinstance(e.get("verdicts"),dict) else {}).items())
        for vid,v in scored:
            p=v.get("paint") if isinstance(v,dict) else None
            if isinstance(p,dict): print(f"    [{label}] {where} {vid} paint {p.get('status')} unpainted={p.get('unpaintedFrames')} partial={p.get('partialFrames')} double={p.get('doubleFrames')} substitute={p.get('substituteFrames')} longestRun={run_of(p)}")
        census=e.get("paintCensus") if isinstance(e.get("paintCensus"),dict) else {}
        for f in census.get("findings") or []:
            f=f if isinstance(f,dict) else {"entry":f}
            line=f"{label} | {where} | {f.get('class')} | {json.dumps({k:v for k,v in f.items() if k!='class'},sort_keys=True,default=str)[:300]}"
            print(f"    FINDING {line}"); out.write(line+"\n")
PYEOF
}
# A Pass G red run matches only with this round's exit 0, a Pass G artifact whose redArm is the variant's label, whose
# expectedCoreSha256 and both sessions' installed core sha are the variant's, whose registered red set is a list equal
# (Counter) to the observed one, whose `unknown` is an empty list and whose status is pass; when the artifact carries a
# paintFloor, every red leg verdict's longest unpainted run must reach it. An unregistered set, inconclusive, error, no
# artifact, a missing or stale status: FAILED, never pending.
run_passg_red(){ n=$1$(echo "${@[2,-1]}" | tr -d ' '); fix=$Q/$1/html-unmodified
  queue $O/passG-red$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $fix/index.html --pass G --artifact $O/passG-red$n.json "${@[2,-1]}"; }
check_passg_red(){ n=$1$(echo "${@[2,-1]}" | tr -d ' '); $PY - "$O/passG-red$n.json" "$(status_of $O/passG-red$n)" "$@" <<'PYEOF' || fail "PASSG-RED $*"
import json,sys
from collections import Counter
sys.path.insert(0,"scripts")
from continuity_core_variants import variant_sha
path,rc,deck,args=sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4:]
label=" ".join([deck,*args])
variant=args[args.index("--core-variant")+1] if "--core-variant" in args else None
try: want_sha=variant_sha(variant)
except Exception as e: print(f"[PASSG-RED {label}] no expected core sha ({e}) exit={rc}"); sys.exit(1)
try: d=json.load(open(path))
except Exception as e: print(f"[PASSG-RED {label}] no artifact ({e}) exit={rc}"); sys.exit(1)
d=d if isinstance(d,dict) else {}
def strs(v): return isinstance(v,list) and all(isinstance(x,str) for x in v)
def sha_of(s): c=(d.get(s) or {}).get("continuity") if isinstance(d.get(s),dict) else None; return c.get("sha256") if isinstance(c,dict) else None
exp,got,unknown,floor=d.get("expectedRedSet"),d.get("redSet"),d.get("unknown"),d.get("paintFloor")
print(f"[PASSG-RED {label}] {d.get('redArm')} status={d.get('status')} exit={rc} expectedCoreSha256={d.get('expectedCoreSha256')} (want {want_sha}) unknown={unknown}")
print(f"    expected red: {exp}\n    observed red: {got}")
for r in d.get("statusReasons") or d.get("reasons") or []: print(f"    {r}")
if d.get("error"): print(f"    error: {d['error']}")
problems=[]
if d.get("kind")!="live-continuity-probe-pass-g" or d.get("pass")!="G": problems.append(f"not a Pass G artifact (kind={d.get('kind')!r}, pass={d.get('pass')!r})")
if d.get("redArm")!=f"core:{variant}": problems.append(f"redArm {d.get('redArm')!r} != {'core:'+str(variant)!r}")
if d.get("expectedCoreSha256")!=want_sha: problems.append("expectedCoreSha256 is not the variant's")
for s in ("armed","nullControl"):
    if sha_of(s)!=want_sha: problems.append(f"{s} installed core sha {sha_of(s)!r} is not the variant's")
if not strs(exp): problems.append("expectedRedSet is not a registered list of ids")
if not strs(got): problems.append("redSet not a list of strings")
elif strs(exp) and Counter(got)!=Counter(exp): problems.append(f"red set {sorted(got)} != registered {sorted(exp)}")
if not strs(unknown): problems.append("unknown not a list of strings")
elif unknown: problems.append(f"unknown {unknown}")
if d.get("status")!="pass": problems.append(f"status {d.get('status')!r} != 'pass'")
if rc!="0": problems.append(f"exit {rc} != 0")
if floor is not None:
    legs={}
    for dest in (d.get("armed") or {}).get("destinations") or [] if isinstance(d.get("armed"),dict) else []:
        ac=(dest or {}).get("advanceCarry") if isinstance(dest,dict) else None
        for vid,v in ((ac or {}).get("verdicts") or {}).items() if isinstance(ac,dict) else []:
            if isinstance(v,dict) and isinstance(v.get("paint"),dict): legs.setdefault(vid,[]).append(v["paint"])
    if not isinstance(floor,int) or isinstance(floor,bool): problems.append(f"paintFloor {floor!r} is not a frame count")
    else:
        for red in got if strs(got) else []:
            spec=red.split(":",1)[1] if ":" in red else red
            if spec=="destination": continue
            runs=[p.get("longestRun") for p in legs.get(spec,[])]
            runs=[r.get("frames") if isinstance(r,dict) else r for r in runs]
            if not runs or not all(isinstance(r,int) and r>=floor for r in runs): problems.append(f"{red} longest unpainted run {runs} below the {floor}-frame floor")
for p in problems: print(f"    MISMATCH: {p}")
sys.exit(1 if problems else 0)
PYEOF
  paint_report "$O/passG-red$n.json" "PASSG-RED $*"; }
for PR in "${PASSG_RED_ARMS[@]}"; do run_passg_red ${=PR}; done
# A paint control run matches only with this round's exit 0 and a paint-control artifact whose control is the arm's,
# whose core is today's, whose sampler is schema 2 with selfCheck ok, whose injector fired and hid exactly N ticks on a
# consecutive seq set, whose target carry reads exactly that set (unpaintedSeqs; partialSeqs for ancestor-half, with no
# unpainted frame) with every other count 0, whose red set is exactly the target (empty for N=0), whose `unknown` is an
# empty list and whose status is pass. Inconclusive, error, no artifact, a missing or stale status: FAILED, never pending.
pc_name(){ print -r -- "$1-${2//:/_}"; }
run_paint_control(){ n=$(pc_name $1 $2); fix=$Q/$1/html-unmodified
  queue $O/paint-control$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $fix/index.html --viewport 1920x1080 --paint-control $2 --artifact $O/paint-control$n.json; }
check_paint_control(){ n=$(pc_name $1 $2); $PY - "$O/paint-control$n.json" "$(status_of $O/paint-control$n)" "$1" "$2" <<'PYEOF' || fail "PAINT-CONTROL $1 $2"
import json,sys
sys.path.insert(0,"scripts")
from obed_edom.live_continuity_js import js_sha256
path,rc,deck,spec=sys.argv[1:]
label=f"{deck} {spec}"
parts=spec.split(":"); n=int(parts[0]); variant=parts[1]
try: d=json.load(open(path))
except Exception as e: print(f"[PAINT-CONTROL {label}] no artifact ({e}) exit={rc}"); sys.exit(1)
d=d if isinstance(d,dict) else {}
def ints(v): return isinstance(v,list) and all(isinstance(x,int) and not isinstance(x,bool) for x in v)
rec=d.get("controlRecord") if isinstance(d.get("controlRecord"),dict) else {}
arm=d.get("arm") if isinstance(d.get("arm"),dict) else {}
target=d.get("targetVerdictId")
tv=arm.get(target) if isinstance(target,str) and isinstance(arm.get(target),dict) else {}
paint=tv.get("paint") if isinstance(tv.get("paint"),dict) else {}
sampler=arm.get("sampler") if isinstance(arm.get("sampler"),dict) else {}
self_ok=isinstance(sampler.get("selfCheck"),dict) and sampler["selfCheck"].get("ok") is True
hidden=rec.get("hiddenSeqs")
half=variant=="ancestor-half"
seen,other=(paint.get("partialSeqs"),"unpaintedFrames") if half else (paint.get("unpaintedSeqs"),"partialFrames")
print(f"[PAINT-CONTROL {label}] control={d.get('control')} status={d.get('status')} exit={rc} target={target} fired={rec.get('fired')} hiddenTicks={rec.get('hiddenTicks')} (want {n})")
print(f"    injected seqs: {hidden}\n    {'partial' if half else 'unpainted'} seqs on target: {seen}")
print(f"    paint {paint.get('status')} unpainted={paint.get('unpaintedFrames')} partial={paint.get('partialFrames')} double={paint.get('doubleFrames')} substitute={paint.get('substituteFrames')}; redSet={d.get('redSet')} unknown={d.get('unknown')}")
for r in d.get("statusReasons") or []: print(f"    {r}")
if d.get("error"): print(f"    error: {d['error']}")
problems=[]
if d.get("kind")!="live-continuity-probe-paint-control": problems.append(f"not a paint-control artifact (kind={d.get('kind')!r})")
if d.get("control")!=spec: problems.append(f"control {d.get('control')!r} != {spec!r}")
if d.get("expectedCoreSha256")!=js_sha256(): problems.append("expectedCoreSha256 is not today's core")
if sampler.get("schema")!=2 or not self_ok: problems.append("arm.sampler is not schema 2 with selfCheck.ok")
if rec.get("fired") is not True: problems.append("injector never fired")
if rec.get("hiddenTicks")!=n: problems.append(f"hiddenTicks {rec.get('hiddenTicks')!r} != {n}")
if not (ints(hidden) and len(hidden)==n and hidden==list(range(hidden[0],hidden[0]+n)) if n else hidden==[]): problems.append(f"injected seqs {hidden!r} are not {n} consecutive ticks")
if not ints(seen) or seen!=hidden: problems.append(f"target seq set {seen!r} != injected {hidden!r}")
for k in (other,"doubleFrames","substituteFrames"):
    if paint.get(k)!=0: problems.append(f"target {k} {paint.get(k)!r} != 0")
if d.get("redSet")!=([target] if n else []): problems.append(f"redSet {d.get('redSet')!r} != {[target] if n else []!r}")
if d.get("unknown")!=[]: problems.append(f"unknown {d.get('unknown')!r} not an empty list")
if d.get("status")!="pass": problems.append(f"status {d.get('status')!r} != 'pass'")
if rc!="0": problems.append(f"exit {rc} != 0")
for p in problems: print(f"    MISMATCH: {p}")
sys.exit(1 if problems else 0)
PYEOF
}
for PC in "${PAINT_CONTROL_ARMS[@]}"; do run_paint_control ${=PC}; done
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
for DA in "${DECK_ARMS[@]}"; do d=${DA%% *}; A=${DA#* }; HOST_DECK=$d check_host_red ${=A}; tally $? "HOST red $d $A"; done
for P in $PASSG_FIXTURES; do check_passg $P; done
for PR in "${PASSG_RED_ARMS[@]}"; do check_passg_red ${=PR}; done
for PC in "${PAINT_CONTROL_ARMS[@]}"; do check_paint_control ${=PC}; done
for A in $CARRY_COVER_ARMS; do check_cc ${=A}; done
for A in "${P2_ARMS[@]}"; do check_p2 "${(@Q)${(z)A}}"; done
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2
echo "load average (1 min) at start $START_LOAD, at launch $LAUNCH_LOAD, at end $(load1 || echo unreadable); wall ${SECONDS}s"
FINDINGS=0; [[ -f $O/paint-findings.txt ]] && FINDINGS=$(wc -l < $O/paint-findings.txt | tr -d ' ')
(( FINDINGS )) && echo "paint census findings by class (report only): $(cut -d'|' -f3 $O/paint-findings.txt | tr -d ' ' | sort | uniq -c | awk '{printf "%s=%s ", $2, $1}')"
echo "DONE tier=$TIER failed=$FAIL pending=$PENDING findings=$FINDINGS"
if (( ALLOW_RECORD && PENDING )); then echo "## --allow-record: $PENDING RECORD arm(s) left ungated -- DISCOVERY RUN, NOT A PASS ##"; fi
(( FAIL == 0 && (PENDING == 0 || ALLOW_RECORD) )); rc=$?
if [[ $TIER == dev ]]; then echo "## DEV TIER -- NOT A QUALIFICATION PASS (exit $(( rc ? 1 : 10 ))) ##"; exit $(( rc ? 1 : 10 )); fi
exit $rc

#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir> [--allow-record] [--tier dev|full]   (runs the host gates, host red arms,
# Pass G, Pass G red, paint control, carry-cover (P2 and D1) and P2 arms through one queue, GATE_JOBS at a time (1..5, default 3; 1 = serial), from a clean pinned worktree, into a
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
# S0 deck arms (plan §3.4 Q3): every (deck, arm) gate_checks.py's RED_ARM_EXPECTATIONS registers, run as host red arms at
# 1920x1080 on the deck's own export (HOST_DECK). Full tier only. The `no-pin-hold` arms are the painted instrument's
# red arms (S2 instrument plan §4/§5, §3.11; decision 11), registered 2026-10-12 (owner) with a paintFloor of 60
# (decision 3): D2 b2to3 A (108), D3 b0to1 A (107), D5 b0to1 + b1to2 A (108 / 223); D4 reads no red and is not run.
# Source: main checkout output/evidence/s2-dev/instr-v-277c720b/stage1/V3/{D2,D3,D5}-red-npH.json.
DECK_ARMS=(
  "D1 --strip bridge@2" "D1 --strip bridge@4" "D1 --strip pin@6"
  "D2 --strip bridge@2" "D2 --strip restart@4" "D2 --strip pin@6" "D2 --strip bridge@8"
  "D2 --core-variant no-pin-hold"
  "D3 --strip pin@2" "D3 --strip bridge@2" "D3 --strip retire@4" "D3 --strip pin@4" "D3 --strip bridge@6"
  "D3 --core-variant no-pin-hold"
  "D4 --core-variant wrong-instance" "D4 --core-variant fifo-reuse" "D4 --strip bridge@3" "D4 --strip pin@5"
  "D5 --core-variant stash-any" "D5 --core-variant fifo-reuse" "D5 --strip pin@2" "D5 --strip pin@4"
  "D5 --core-variant no-pin-hold"
  "D6 --strip bridge@2" "D6 --strip retire@8"
)
[[ $TIER == full ]] || DECK_ARMS=()
# Pass G (plan §3.4 Q3; owner 2026-10-10): the plan-derived go-to gate, armed + null control, on P2 and each S0 deck.
# Full tier only.
PASSG_FIXTURES=(P2 D1 D2 D3 D4 D5 D6)
[[ $TIER == full ]] || PASSG_FIXTURES=()
# Pass G red (S2 instrument plan §3.9/§5, §3.11): "<deck> <probe args>", the advance legs scored per frame under a core
# variant. Registered 2026-10-12 (owner; gate_checks.py's PASSG_RED_EXPECTATIONS, paintFloor 60): D1 no-pin-hold reds
# exactly the (1,3,4) leg's b2to3 carry (longest unpainted run 229) and that leg's destination (the slide-4 rect stays
# unpainted past arrival), and leaves (2,1,2) and (1,2,3) green. Source: main checkout
# output/evidence/s2-dev/instr-v-277c720b/stage1/V3/D1-passG-red-npH.json. The pre-pin-hold core red runs once outside
# this script (decision 7). Full tier only.
PASSG_RED_ARMS=("D1 --core-variant no-pin-hold")
[[ $TIER == full ]] || PASSG_RED_ARMS=()
# Paint-floor registrations and enforcement live in gate_checks.py. Any paintFloor carried by an arm must hold for
# every exact registered red carry.
# Painted-instrument positive control (S2 instrument plan §3.10/§4/§5): "<deck> <N:VARIANT:PHASE@SCENE[:late]>". The
# injected N-frame hide must read as exactly the injected seq set on the target carry and nowhere else; N=0 is the
# injector's null (armed, nothing hidden, every count 0). The late timing makes the pre-paint phase load-bearing.
# Full tier only.
PAINT_CONTROL_ARMS=("D5 6:ancestor-opacity:pin@2" "D5 6:ancestor-opacity:pin@2:late" "D5 0:ancestor-opacity:pin@2")
[[ $TIER == full ]] || PAINT_CONTROL_ARMS=()
# Carry-cover gate (rubber band, 2026-10-10; D1 with the GL clock, 2026-10-11): every bridge carry screencast on P2 and
# D1; the GL poster must not show beyond the moving overlay. Full tier only: "<deck> <expected status> [probe args]" --
# the default core must pass with every bridge on Keynote's GL clock; the red (P2: today's linear overlay,
# --core-variant linear-bridge; D1: today's performance.now() clock, --core-variant no-gl-clock, every bridge on the
# fallback) and a hidden overlay (null, --carry-cover-null) must fail.
CARRY_COVER_ARMS=("P2 pass" "P2 fail --core-variant linear-bridge" "P2 fail --carry-cover-null"
                  "D1 pass" "D1 fail --core-variant no-gl-clock" "D1 fail --carry-cover-null")
[[ $TIER == full ]] || CARRY_COVER_ARMS=()
# Stage B texture-feed registrations (§5.3): "deck expectation-label probe args". Each ordinary/control capture selects
# its relevant A or attach arm; core variants already run one red arm. Expectations live in gate_checks.py, so the
# shell queue contains no duplicated verdict table. Alpha is repaired into this round's outdir before any timed run.
MM_FEED_ARMS=(
  "D7 feed-on-2560 --mm-feed on --viewport 2560x1440 --skip-arms B,C,V,Voff,attach"
  "D7 feed-on-1600 --mm-feed on --viewport 1600x1000 --skip-arms B,C,V,Voff,attach"
  "D7 feed-on-1920 --mm-feed on --viewport 1920x1080 --skip-arms B,C,V,Voff,attach"
  "D7 from-only --mm-feed on --feed-variant from-only --skip-arms B,C,V,Voff,attach"
  "D7 no-linger --mm-feed on --feed-tamper no-linger --skip-arms B,C,V,Voff,attach"
  "D7 interim-delay --mm-feed on --core-variant interim-delay"
  "D7 startup-moved-decoder --core-variant startup-moved-decoder"
  "D7 attach-once --mm-feed off --feed-dwell 5 --skip-arms A,B,C,V,Voff"
  "D7s feed-on-2560 --mm-feed on --viewport 2560x1440 --skip-arms B,C,V,Voff,attach"
  "D7s feed-on-1600 --mm-feed on --viewport 1600x1000 --skip-arms B,C,V,Voff,attach"
  "D7s feed-on-1920 --mm-feed on --viewport 1920x1080 --skip-arms B,C,V,Voff,attach"
  "D7s from-only --mm-feed on --feed-variant from-only --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-on-2560 --mm-feed on --viewport 2560x1440 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-on-1600 --mm-feed on --viewport 1600x1000 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-on-1920 --mm-feed on --viewport 1920x1080 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-off-2s --mm-feed off --feed-dwell 2 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-off-5s --mm-feed off --feed-dwell 5 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK feed-off-12s --mm-feed off --feed-dwell 12 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK attach-once --mm-feed off --feed-dwell 5 --skip-arms A,B,C,V,Voff"
  "Alpha_DSK hold-upload-killed --mm-feed off --hold-upload-kill-switch --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK ordinal --feed-tamper ordinal --feed-tamper-scene 10 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK after-feed --feed-tamper after-feed --feed-tamper-scene 10 --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK from-only --mm-feed on --feed-variant from-only --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK overlay-ride --core-variant overlay-ride"
  "Alpha_DSK startup-moved-decoder --core-variant startup-moved-decoder"
  "Alpha_DSK settle-on-stage --core-variant settle-on-stage"
  "Alpha_DSK no-pause --mm-feed off --core-variant no-pause"
  "Alpha_DSK mm-opacity-off --mm-opacity off --skip-arms B,C,V,Voff,attach"
  "Alpha_DSK strip-bridge14-movie2 --strip bridge@14:movie2"
)
[[ $TIER == full ]] || MM_FEED_ARMS=()
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
expect(){ $PY scripts/gate_checks.py expect "$1" "$2" AUTO "headless Chrome" "$3" "$4" "${@[5,-1]}"; }
# Every run goes through one queue, GATE_JOBS at a time, refilled whenever any slot opens; the launch section below
# starts the long groups first. Each run has its own process group and atomically writes <name>.rc as "<round
# nonce> <exit>"; a missing .rc or one from another round fails its check. Checks run in their own order once every
# run has finished. Exit, HUP, INT or TERM stops the running groups (TERM, then KILL after 5 s).
NONCE="$$-$(date +%s)-$RANDOM"; echo "round nonce $NONCE"
zmodload zsh/parameter
zmodload zsh/datetime
zmodload zsh/zselect
stop_jobs(){ local s g n live=(); for s in $jobstates; do [[ $s == running:* ]] && live+=(${${(s.:.)${s#*:*:}}%%=*}); done; (( ${#live} )) || return 0
  for g in $live; do kill -TERM -$g $g 2>/dev/null; done
  for n in {1..20}; do for g in $live; do kill -0 -$g 2>/dev/null && break; done || break; sleep 0.25; done
  for g in $live; do kill -KILL -$g $g 2>/dev/null; done; }
trap stop_jobs EXIT; trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM
JOB='out=$1 nonce=$2; shift 2; "$@" > "$out.log" 2>&1; rc=$?; print -r -- "$nonce $rc" > "$out.rc.tmp" && mv -f "$out.rc.tmp" "$out.rc"'
queue(){ local out=$1 N; shift
  while true; do
    N=${#${(M)${(v)jobstates}:#running:*}}
    (( N < GATE_JOBS )) && break
    zselect -t 1
  done
  $PY -c 'import os,sys; os.setpgrp(); os.execv(sys.argv[1], sys.argv[1:])' /bin/zsh -fc "$JOB" job "$out" "$NONCE" "$@" &
}
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
settle_deadline=$((EPOCHREALTIME + GATE_SETTLE_S))
Q=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("qual-decks"))')
ALPHA_SOURCE=$($PY -c 'from obed_edom.fixture_paths import fixture; print(fixture("alpha-dsk-textures"))')
ALPHA_GATE=$O/alpha-dsk-repaired
QUAL_B_SOURCE=${QUAL_B_SOURCE:-"$HOME/Desktop/Convert wall to 16x9 CGs/Continuity/strip2"}
if (( ${#MM_FEED_ARMS} )); then
  [[ -d $QUAL_B_SOURCE/D7-html && -d $QUAL_B_SOURCE/D7s-html ]] || {
    echo "D7/D7s qualification exports are missing under QUAL_B_SOURCE=$QUAL_B_SOURCE; no run launched" >&2; exit 2; }
  $PY - "$QUAL_B_SOURCE" "$O" "$G/scripts/gate_checks.py" <<'PYEOF' || { echo "D7/D7s qualification export staging FAILED; no run launched"; exit 2; }
import ast,hashlib,json,shutil,struct,sys
from pathlib import Path
from obed_edom import preview_textures
from obed_edom.live_continuity import Unsupported,_referenced_movies,derive_plan,plan_signature
source,out,gate_source=map(Path,sys.argv[1:])
names={"D7_PLAN_SHA256","D7S_PLAN_SHA256","D7_COUNTER_MDAT_SHA256"}
pins={}
identities={}
for node in ast.parse(gate_source.read_text()).body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in names:
        pins[node.targets[0].id]=ast.literal_eval(node.value)
def mdat_sha(path):
    data=path.read_bytes()
    offset=0
    payloads=[]
    while offset<len(data):
        size,kind=struct.unpack_from(">I4s",data,offset)
        head=8
        if size==1: size=struct.unpack_from(">Q",data,offset+8)[0]; head=16
        elif size==0: size=len(data)-offset
        if size<head or offset+size>len(data): raise ValueError("invalid top-level atom size")
        if kind==b"mdat": payloads.append(data[offset+head:offset+size])
        offset+=size
    if len(payloads)!=1: raise ValueError(f"{len(payloads)} top-level mdat atoms, expected exactly 1")
    return hashlib.sha256(payloads[0]).hexdigest()
for deck,pin_name in (("D7","D7_PLAN_SHA256"),("D7s","D7S_PLAN_SHA256")):
    dest=out/f"{deck}-html"
    shutil.copytree(source/f"{deck}-html",dest)
    header=json.loads((dest/"assets/header.json").read_text())
    slides=[{"originalOrdinal":i+1,"playerIndex":i,"exportedUuid":uuid,"skipped":False}
            for i,uuid in enumerate(header["slideList"])]
    referenced=_referenced_movies(dest,slides,resolver=lambda base,relative:base/relative)
    counter_shas={}
    for key in sorted(referenced):
        wanted=pins["D7_COUNTER_MDAT_SHA256"].get(key)
        for movie in referenced[key]:
            relative=movie.relative_to(dest).as_posix() if movie is not None else key
            if movie is None or not movie.is_file():
                raise SystemExit(f"{deck} referenced counter movie {relative} is missing; no run launched")
            try: actual=mdat_sha(movie)
            except (ValueError,struct.error) as exc:
                raise SystemExit(f"{deck} counter movie {relative} refused: {exc}; no run launched") from exc
            if actual!=wanted:
                raise SystemExit(f"{deck} counter movie {relative} mdat payload sha256 {actual} does not match pinned {wanted} (QUAL_B_SOURCE must hold the strip2 two-strip exports); no run launched")
            counter_shas[relative]=actual
    hits=preview_textures.json_hits(dest,slides)
    if hits:
        raise SystemExit(f"{deck} feed fixture refused: {'; '.join(hits)}")
    identities[deck]={"exportRoot":str(dest.resolve()),
        "headerSha256":hashlib.sha256((dest/"assets/header.json").read_bytes()).hexdigest(),
        "counterMdatSha256":dict(sorted(counter_shas.items())),
        "slideJson":[{"originalOrdinal":slide["originalOrdinal"],"exportedUuid":slide["exportedUuid"],
          "sha256":hashlib.sha256((dest/"assets"/slide["exportedUuid"]/(slide["exportedUuid"]+".json")).read_bytes()).hexdigest()}
         for slide in slides]}
    plan=derive_plan(dest,slides,resolver=lambda base,relative:base/relative)
    if isinstance(plan,Unsupported):
        raise SystemExit(f"{deck} runtime plan is unavailable ({plan.reason}); no run launched")
    runtime=plan.to_runtime()
    if isinstance(runtime,Unsupported):
        raise SystemExit(f"{deck} runtime plan is unavailable ({runtime.reason}); no run launched")
    actual,wanted=plan_signature(runtime),pins[pin_name]
    if actual!=wanted:
        raise SystemExit(f"{deck} runtime plan sha256 {actual} does not match pinned {wanted}; no run launched")
    print("Qualification B fixture",dest,"plan sha256",actual)
control=source/"q7-fixtures/D7-unrepaired"
control_root=control/"html-player"
if not control_root.is_dir():
    raise SystemExit(f"D7 unrepaired refusal control is missing at {control_root}")
control_header=json.loads((control_root/"assets/header.json").read_text())
control_slides=[{"originalOrdinal":i+1,"playerIndex":i,"exportedUuid":uuid,"skipped":False}
                for i,uuid in enumerate(control_header["slideList"])]
control_hits=preview_textures.json_hits(control_root,control_slides)
if not control_hits:
    raise SystemExit("D7 unrepaired refusal control unexpectedly passes preview_textures.json_hits")
identities["D7-unrepaired-refusal"]={"exportRoot":str(control_root.resolve()),"hits":control_hits,
    "headerSha256":hashlib.sha256((control_root/"assets/header.json").read_bytes()).hexdigest(),
    "slideJson":[{"originalOrdinal":slide["originalOrdinal"],"exportedUuid":slide["exportedUuid"],
      "sha256":hashlib.sha256((control_root/"assets"/slide["exportedUuid"]/(slide["exportedUuid"]+".json")).read_bytes()).hexdigest()}
     for slide in control_slides]}
(out/"feed-fixture-identities.json").write_text(json.dumps(identities,indent=2)+"\n")
PYEOF
  $PY - "$ALPHA_SOURCE" "$ALPHA_GATE" "$QUAL_B_SOURCE/q7-fixtures/Alpha/html-unmodified" <<'PYEOF' || { echo "Alpha texture repair FAILED; no run launched"; exit 2; }
import json,shutil,sys
from pathlib import Path
from obed_edom import preview_textures
from obed_edom.live_continuity import _referenced_movies,codec_report
source,dest,complete=map(Path,sys.argv[1:])
if not complete.is_dir():
    raise SystemExit(f"Alpha complete export donor is missing at {complete}")
manifest=json.loads((source/"manifest.json").read_text())
shutil.copytree(source/"html-unmodified",dest)
resolver=lambda base,relative:base/relative
referenced=_referenced_movies(dest,manifest["slides"],resolver=resolver)
if not referenced:
    raise SystemExit("Alpha fixture references no movies")
missing=sorted({path for paths in referenced.values() for path in paths if path is not None and not path.is_file()})
outside=[path for path in missing if not path.resolve().is_relative_to(dest.resolve())]
if outside:
    raise SystemExit(f"Alpha fixture references missing movie(s) outside {dest}: {', '.join(map(str,outside))}")
donors={}
for path in sorted(complete.rglob("*")):
    if path.is_file(): donors.setdefault(path.name,path)
absent=sorted({path.name for path in missing if path.name not in donors})
if absent:
    raise SystemExit(f"Alpha complete export donor {complete} is missing needed movie file name(s): {', '.join(absent)}")
for path in missing:
    path.parent.mkdir(parents=True,exist_ok=True)
    relative=complete/path.relative_to(dest)
    shutil.copy2(relative if relative.is_file() else donors[path.name],path)
print(f"Alpha movies restored {len({path.name for path in missing})}")
record=preview_textures.repair_textures(dest,manifest["slides"],player_digest=manifest["playerDigest"],log=print)
if not record.get("repaired"):
    raise SystemExit("Alpha repair changed no textures; the registered fixture is not the unrepaired input")
if preview_textures._detect(preview_textures._load(dest,manifest["slides"]),preview_textures._Renderer()):
    raise SystemExit("Alpha repair left detector hits")
unreadable=[entry["asset"] for entry in codec_report(dest,manifest["slides"],resolver=resolver) if entry["codec"] is None]
if unreadable:
    raise SystemExit(f"Alpha repaired fixture has unreadable or mixed movie assets: {', '.join(unreadable)}")
print("Alpha repaired fixture",dest)
PYEOF
fi
while LAUNCH_LOAD=$(load1) && (( LAUNCH_LOAD > GATE_MAX_START_LOAD )); do
  remaining=$((settle_deadline - EPOCHREALTIME))
  (( remaining <= 0 )) && {
    echo "1-minute load average $LAUNCH_LOAD still exceeds GATE_MAX_START_LOAD=$GATE_MAX_START_LOAD ${GATE_SETTLE_S}s after" \
      "the prewarm; no timed run launched." >&2; exit 2; }
  sleep $(( remaining < 5 ? remaining : 5 ))
done
[[ -n $LAUNCH_LOAD ]] || { echo "cannot read the 1-minute load average (sysctl -n vm.loadavg); no run launched" >&2; exit 2; }
echo "load average (1 min) at launch $LAUNCH_LOAD"
check_host(){ rc=$(status_of $O/host-$1); [[ $rc == 0 ]] || fail "HOST $1 exit $rc"; summ $O/host-$1.json "HOST $1" "${HOST_SKIP[$1]}" || fail "HOST $1 status"
  paint_report $O/host-$1.json "HOST $1"; }
# Host red arms (gate_checks.py pre-registered sets, keyed by plan sha, arm and GL mode). The artifact contract is
# checked in full: every key present and typed, redArm equal to the label the CLI arguments imply, expectedCoreSha256
# the arm's sha, `unknown` an empty list, the census stray/duplicate multiset reconciled with redSet, and the red and
# expected multisets equal (Counter), and the paint floor second guard. A "record" arm returns 3 only when all of that
# holds with status recorded.
# run_host_red runs on P2; `HOST_DECK=Dn run_host_red ...` runs the same arm on an S0 deck (its html-unmodified export is
# both fixture and original index: the qual decks need no asset replacement). check_host_red takes the same HOST_DECK.
run_host_red(){ n=${HOST_DECK:-}$(echo "$*" | tr -d ' '); fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ -n ${HOST_DECK:-} ]]; then fix=$Q/$HOST_DECK/html-unmodified; idx=$fix/index.html; fi
  queue $O/host-red$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --viewport 1920x1080 --artifact $O/host-red$n.json "$@"; }
check_host_red(){ n=${HOST_DECK:-}$(echo "$*" | tr -d ' '); rc=$(status_of $O/host-red$n)
  [[ $rc == <-> ]] || { echo "[HOST ${HOST_DECK:+$HOST_DECK }$*] no fresh status ($rc) -> MISMATCH"; return 1; }
  $PY scripts/gate_checks.py check_host_red "$O/host-red$n.json" "$rc" AUTO "headless Chrome" "$@"
  local r=$?; paint_report "$O/host-red$n.json" "HOST ${HOST_DECK:+$HOST_DECK }$*"; return $r; }
# A Pass G run passes only with this round's exit 0 and a Pass G artifact whose top-level status is pass; anything else
# (fail, inconclusive, error, no artifact, a missing or stale status) is FAILED, never pending.
run_passg(){ fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ $1 != P2 ]]; then fix=$Q/$1/html-unmodified; idx=$fix/index.html; fi
  queue $O/passG-$1 $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --pass G --artifact $O/passG-$1.json; }
check_passg(){ $PY scripts/gate_checks.py check_passg "$O/passG-$1.json" "$(status_of $O/passG-$1)" "$1" "headless Chrome" || fail "PASSG $1"
  paint_report "$O/passG-$1.json" "PASSG $1"; }
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
            yield f"{s} leg G{dest.get('fromOrdinal')}-{dest.get('toOrdinal')}-{dest.get('advanceTo')}",dest.get("advanceCarry")
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
# (Counter) to the observed one, whose `unknown` is an empty list and whose status is pass, and whose paintFloor holds
# (the paint floor second guard above). An unregistered set, inconclusive, error, no
# artifact, a missing or stale status: FAILED, never pending.
run_passg_red(){ n=$1$(echo "${@[2,-1]}" | tr -d ' '); fix=$Q/$1/html-unmodified
  queue $O/passG-red$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $fix/index.html --pass G --artifact $O/passG-red$n.json "${@[2,-1]}"; }
check_passg_red(){ n=$1$(echo "${@[2,-1]}" | tr -d ' ')
  $PY scripts/gate_checks.py check_passg_red "$O/passG-red$n.json" "$(status_of $O/passG-red$n)" AUTO "headless Chrome" "$1" "${@[2,-1]}" || fail "PASSG-RED $*"
  paint_report "$O/passG-red$n.json" "PASSG-RED $*"; }
# A paint control run matches only with this round's exit 0 and a paint-control artifact whose control is the arm's,
# whose core is today's, whose sampler is schema 2 with selfCheck ok, whose injector fired and hid exactly N ticks on a
# consecutive seq set, whose target carry reads exactly that set (unpaintedSeqs; partialSeqs for ancestor-half, with no
# unpainted frame) with every other count 0, whose red set is exactly the target (empty for N=0), whose `unknown` is an
# empty list and whose status is pass. The injector record must pass paint_instrument.control_record_problem and the
# target's paint score PAINT_SCORE_FIELDS (the probe's own schemas): a missing integrity field is never "no problem".
# Inconclusive, error, no artifact, a missing or stale status: FAILED, never pending.
pc_name(){ print -r -- "$1-${2//:/_}"; }
run_paint_control(){ n=$(pc_name $1 $2); fix=$Q/$1/html-unmodified
  queue $O/paint-control$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $fix/index.html --viewport 1920x1080 --paint-control $2 --artifact $O/paint-control$n.json; }
check_paint_control(){ n=$(pc_name $1 $2); $PY scripts/gate_checks.py check_paint_control "$O/paint-control$n.json" "$(status_of $O/paint-control$n)" "$2" "headless Chrome" "$1" || fail "PAINT-CONTROL $1 $2"; }
# A carry-cover run matches only with this round's exit (0 for pass, 1 for fail), a carry-cover artifact whose status is
# the expected one, whose fixture is its deck's, whose control and core variant are the ones its arguments imply, whose
# installed continuity core sha is that variant's (else today's), and, but on the null arm, whose bridges are non-empty
# and each rode the arm's clock (fallback under no-gl-clock, else gl). Inconclusive, error, no artifact, a missing or
# stale status: FAILED, never pending. cc_fixture gives a deck's fixture and original index (P2's as run_host_red's).
cc_fixture(){ fix=$F/html-player; idx=$F/html-unmodified/index.html
  if [[ $1 != P2 ]]; then fix=$Q/$1/html-unmodified; idx=$fix/index.html; fi; }
run_cc(){ cc_fixture $1; n=${1:#P2}$(echo "${@[3,-1]}" | tr -d ' ')
  queue $O/carry-cover$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $idx --viewport 1920x1080 --carry-cover --artifact $O/carry-cover$n.json "${@[3,-1]}"; }
check_cc(){ cc_fixture $1; label=${(j: :)@[3,-1]}; n=${1:#P2}${label// /}; label=${${1:#P2}:+$1 }${label:-green}
  $PY scripts/gate_checks.py check_cc "$O/carry-cover$n.json" "$(status_of $O/carry-cover$n)" AUTO "headless Chrome" "$label" "$2" "$fix" AUTO "${@[3,-1]}" || fail "CARRY-COVER $label"; }
# Texture-feed gates accept the probe's normal 0/1 exit only when every registered per-verdict expectation matches.
# `from-only` is entry-sensitive: a crossfade (`feed.to` non-null) must red feedLive, while a single-texture entry stays
# green. The artifact keeps the complete producer and scorer records for exact-frame review.
mm_feed_fixture(){ fix=$O/$1-html; [[ $1 == Alpha_DSK ]] && fix=$ALPHA_GATE; }
run_mm_feed(){ local deck=$1 label=$2; shift 2; mm_feed_fixture $deck
  local n=$deck-$label
  queue $O/mm-feed-$n $PY -u scripts/live_continuity_probe.py --fixture $fix --original-index $fix/index.html \
    --viewport 1920x1080 --artifact $O/mm-feed-$n.json "$@"; }
check_mm_feed(){ local deck=$1 label=$2; shift 2; local n=$deck-$label rc=$(status_of $O/mm-feed-$deck-$label)
  $PY scripts/gate_checks.py check_mm_feed "$O/mm-feed-$n.json" "$rc" "$label" "headless Chrome" "$deck" || fail "MM-FEED $deck $label"
  paint_report "$O/mm-feed-$n.json" "MM-FEED $deck $label"; }
# Each P2 arm runs in its own --out-dir.
run_p2(){ shift 2; n=$(echo "$*" | tr -d ' ')
  queue "$O/p2$n" $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable --out-dir "$O/p2$n" "$@"; }
check_p2(){ spec=$1; inc=$2; shift 2; n=$(echo "$*" | tr -d ' '); rc=$(status_of "$O/p2$n"); echo "[P2 $*] exit=$rc $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; r=$O/p2$n/report.json; [[ "$*" == *"--gl-replay auto"* ]] && r=$O/p2$n/gl-replay/report.json; cp $r "$O/p2$n.report.json" 2>/dev/null; if [[ $rc == <-> ]]; then expect "$O/p2$n.log" "$rc" "$spec" "$inc" "$@"; else echo "    no fresh status ($rc) -> MISMATCH"; false; fi; tally $? "P2 $*"; }
for A in "${P2_ARMS[@]}"; do [[ $A == *--skip-freeze-bracket* ]] || run_p2 "${(@Q)${(z)A}}"; done
for P in $PASSG_FIXTURES; do run_passg $P; done
for V in $HOST_VIEWPORTS; do
  queue $O/host-$V $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json ${HOST_SKIP[$V]:+--skip-arms} ${HOST_SKIP[$V]}
done
for PR in "${PASSG_RED_ARMS[@]}"; do run_passg_red ${=PR}; done
for A in "${MM_FEED_ARMS[@]}"; do run_mm_feed ${=A}; done
for A in "${P2_ARMS[@]}"; do [[ $A == *--skip-freeze-bracket* ]] && run_p2 "${(@Q)${(z)A}}"; done
for A in $HOST_RED_ARMS; do run_host_red ${=A}; done
for DA in "${DECK_ARMS[@]}"; do d=${DA%% *}; A=${DA#* }; HOST_DECK=$d run_host_red ${=A}; done
for A in $CARRY_COVER_ARMS; do run_cc ${=A}; done
for PC in "${PAINT_CONTROL_ARMS[@]}"; do run_paint_control ${=PC}; done
wait
for V in $HOST_VIEWPORTS; do check_host $V; done
for A in $HOST_RED_ARMS; do check_host_red ${=A}; tally $? "HOST red $A"; done
for DA in "${DECK_ARMS[@]}"; do d=${DA%% *}; A=${DA#* }; HOST_DECK=$d check_host_red ${=A}; tally $? "HOST red $d $A"; done
for P in $PASSG_FIXTURES; do check_passg $P; done
for PR in "${PASSG_RED_ARMS[@]}"; do check_passg_red ${=PR}; done
for PC in "${PAINT_CONTROL_ARMS[@]}"; do check_paint_control ${=PC}; done
for A in $CARRY_COVER_ARMS; do check_cc ${=A}; done
for A in "${MM_FEED_ARMS[@]}"; do check_mm_feed ${=A}; done
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

#!/bin/zsh
# h-bulk-seed-read live A/B (PR #255). Protocol: .agents/plans/pass1_profile.plan.md § "Live gate".
#   driver.sh live    P0 cache prime, A1, B1, pair-1 gate, then B2, A2 (Keynote; ~50 min; early stop)
#   driver.sh o1      null-control line diffs (Keynote-free, light)
#   driver.sh o2      ID-insensitive deck diffs (Keynote-free, CPU-heavy)
#   driver.sh report  S / Whole / load per run
# Run unsandboxed from any cwd. Decks + logs go to the main checkout's visible output/ (Keynote cannot open .claude/ paths).
# FAKE=1 swaps every Keynote step for a synthetic log (control-flow dry run; point OUT at a scratch dir).
set -o pipefail
W=/Users/anyhowclick/Desktop/work/obed-edom
OUT=${OUT:-$W/output/seed-read-ab}
SRC="/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs"
A=$W/.claude/worktrees/seed-ab-A
B=$W/.claude/worktrees/seed-ab-B
A_SHA=f4a44ca081a3f49dbd2f1b33d35aa0d6114940d1
B_SHA=10aedaa2b7d065ac012c81b4fc93145e915ad8da
RUNS=(A1 B1 B2 A2)
export OBED_EDOM_CACHE_DIR="$OUT/cache"
PROG="$OUT/progress.log"
mkdir -p "$OUT"

say() { print -r -- "[$(date +%T)] $*" | tee -a "$PROG"; }
die() { say "ABORT: $*"; exit 1; }

guard() {
  local end=$(( $(date +%s) + ${GUARD_S:-600} )) l
  while :; do
    l=$(sysctl -n vm.loadavg | awk '{print $2}')
    awk -v l="$l" 'BEGIN{exit !(l<4)}' && { say "load $l < 4"; return 0; }
    if [ $(date +%s) -ge $end ]; then
      awk -v l="$l" 'BEGIN{exit !(l>=8)}' && { say "LOAD ABORT: still $l after deadline"; return 1; }
      say "LOAD WARN: $l (4-8) after deadline, proceeding"; return 0
    fi
    sleep 15
  done
}

preflight() {
  [ "$(git -C $A rev-parse HEAD)" = "$A_SHA" ] || die "A not at $A_SHA"
  [ "$(git -C $B rev-parse HEAD)" = "$B_SHA" ] || die "B not at $B_SHA"
  [ -x $A/.venv/bin/obed-edom ] && [ -x $B/.venv/bin/obed-edom ] || die "worktree venv missing (uv sync --frozen --all-extras --all-groups)"
  for r in $RUNS; do [ ! -e "$OUT/$r.log" ] || die "$OUT/$r.log exists: move old results aside first"; done
  [ ! -e "$OUT/out.key" ] || die "stale $OUT/out.key"
  local free_gb=$(df -g "$OUT" | awk 'NR==2{print $4}')
  [ "$free_gb" -ge 80 ] || die "only ${free_gb} GB free (need ~60 GB peak)"
  [ -n "$FAKE" ] && return 0
  if pgrep -x Keynote >/dev/null; then
    [ "$KEYNOTE_OK" = 1 ] || die "Keynote is running: the owner must confirm 0 open documents, then rerun with KEYNOTE_OK=1 (never probe it via osascript)"
    say "Keynote running; owner confirmed 0 documents (KEYNOTE_OK=1)"
  fi
}

p0() {
  mkdir -p "$OUT/cache"
  if [ ! -d "$OUT/cache/deck_digest" ]; then
    cp -Rp $W/.cache/{deck_digest,pairings,template_stat,settings.json} "$OUT/cache/" || die "cache copy failed"
  fi
  if [ -n "$FAKE" ]; then
    print -r -- fake > "$OUT/sha.before"
    mkdir -p "$OUT/cache/inspect"; print -r -- '{"reader":"offline"}' > "$OUT/cache/inspect/fake.v5.k15.4.json"
    print -r -- '{}' > "$OUT/cache/template_stat/fake.v1.k15.4.json"
  else
    shasum -a 256 "$SRC/Full_Report_Card_Wall.key" "$SRC/Base_CG_Assets.key" > "$OUT/sha.before" || die "sha.before failed"
    guard || exit 1
    say "P0 start: fresh 15.4 two-tier source read + template stat into $OUT/cache"
    (cd $A && SRC="$SRC" uv run --no-sync python -c "
import os
from pathlib import Path
from obed_edom.remap_keynote import acquire_wall_payload, offline_read_mode
from obed_edom.keynote import read_template_stat_sizes
s = Path(os.environ['SRC'])
p = acquire_wall_payload(s / 'Full_Report_Card_Wall.key', slide_range=None, mode=offline_read_mode(), say=print)
print('P0 wall', p['reader'], len(p['slides']))
print('P0 template stat', len(read_template_stat_sizes(s / 'Base_CG_Assets.key')))
" 2>&1 | tee "$OUT/P0.log") || die "P0 failed (see P0.log)"
  fi
  local wall=$(ls "$OUT"/cache/inspect/*.k15.4.json 2>/dev/null | head -1)
  [ -n "$wall" ] || die "P0 left no *.k15.4.json wall payload"
  python3 -I -c "import json,sys; sys.exit(json.load(open(sys.argv[1])).get('reader') != 'offline')" "$wall" || die "P0 wall payload reader is not offline"
  ls "$OUT"/cache/template_stat/*.k15.4.json >/dev/null 2>&1 || die "P0 left no 15.4 template stat"
  say "P0 done: $(basename $wall)"
}

remap() {
  if [ -n "$FAKE" ]; then
    [ "$FAKE_FAIL" = "$1" ] && { print -r -- "[+   10.0s] Traceback: fake failure"; return 1; }
    local s=${(P)${:-FAKE_S_$1}:-150}
    print -r -- "[+    3.0s] Read Full_Report_Card_Wall.key from cached offline payload — skipped the Keynote source read."
    print -r -- "[+  200.0s] Offline-write: bulk live seed read of 104 slide(s)…"
    printf '[+ %7.1fs] Offline-write: bulk seed read done; patching members.\n' $(( 200.0 + s ))
    printf '[+ %7.1fs] Applied 3822 objects, missed 0.\n' $(( 450.0 + s ))
    : > "$OUT/out.key"; : > "$OUT/$1-pass1.key"
    return 0
  fi
  OBED_DEBUG_PASS1_SNAPSHOT="$OUT/$1-pass1.key" uv run --no-sync obed-edom remap "$SRC/Full_Report_Card_Wall.key" \
    --template "$SRC/Base_CG_Assets.key" --slides 1-129,135-143,145-155 --no-export --out "$OUT/out.key"
}

run() {
  [ ! -e "$OUT/out.key" ] || { say "$1: stale out.key"; return 1; }
  guard || return 1
  uptime > "$OUT/$1.uptime"
  say "$1 start ($2)"
  (cd "$2" && remap "$1" 2>&1 | tee "$OUT/$1.log" >/dev/null) || { say "$1 FAILED (deck left at out.key, log $1.log)"; return 1; }
  mv "$OUT/out.key" "$OUT/$1-final.key" || return 1
  say "$1 done: S=$(S $1) Whole=$(Wh $1)"
}

S() { awk 'match($0, /^\[\+ *[0-9.]+s\]/) { t = substr($0, 3, RLENGTH - 4) + 0 } /Offline-write: bulk live seed read of/ { a = t; na++ } /Offline-write: bulk seed read done/ { if (na == 1) b = t; nb++ } END { if (na != 1 || nb != 1 || b == "") { print "S: bad seed-read markers in " FILENAME > "/dev/stderr"; exit 1 } printf "%.1f", b - a }' "$OUT/$1.log"; }
Wh() { grep -oE '^\[\+ *[0-9.]+s\]' "$OUT/$1.log" | tail -1 | tr -d '[+ s]'; }
gate() { awk -v a="$(S $1)" -v b="$(S $2)" -v n="$3" 'BEGIN { d = a - b; printf "%s S(A)=%s S(B)=%s saving %.1f s\n", n, a, b, d; exit !(a != "" && b != "" && d >= 60) }' | tee -a "$PROG"; }

live() {
  preflight
  say "LIVE start (FAKE=${FAKE:-0}) A=$A_SHA B=$B_SHA"
  p0
  if run A1 $A && run B1 $B && gate A1 B1 pair1; then
    say "pair 1 PASSED the S gate; running pair 2"
    run B2 $B && run A2 $A && gate A2 B2 pair2
    say "pair 2 finished rc=$?"
  else
    say "EARLY STOP: run failure or pair-1 gate FAIL — record and stop"
  fi
  if [ -z "$FAKE" ]; then
    shasum -a 256 "$SRC/Full_Report_Card_Wall.key" "$SRC/Base_CG_Assets.key" | diff - "$OUT/sha.before" >/dev/null \
      && say "sources unchanged" || say "SOURCE CHANGED: sha differs from sha.before"
  fi
  report
  say "LIVE end"
}

report() {
  for r in $RUNS; do
    [ -e "$OUT/$r.log" ] || continue
    say "$r S=$(S $r 2>/dev/null) Whole=$(Wh $r) load=$(awk -F'load averages: ' '{print $2}' "$OUT/$r.uptime")"
  done
}

o1() {
  local NC='^(Read .* from cached|Applied [0-9]|Pass 1 census:|Offline hides|Offline-write|Stat zorder detail:|Card-border stroke:|Builds follow source:)'
  norm() { sed -E 's/^\[\+ *[0-9.]+s\] //; s/, [0-9.]+s\.$/./' "$1" | grep -E "$NC" | grep -v 'snapshot written'; }
  for r in B1 B2 A2; do
    [ -e "$OUT/$r.log" ] || continue
    diff <(norm "$OUT/A1.log") <(norm "$OUT/$r.log") > "$OUT/O1-$r.diff" && say "O1 $r identical to A1" || say "O1 $r DIFFERS (see O1-$r.diff)"
  done
  grep -h 'Pass 1 unattributed' "$OUT"/{A1,B1,B2,A2}.log 2>/dev/null
  grep -hE 'Bulk geometry:|needs the `iwa` extra' "$OUT"/{A1,B1,B2,A2}.log 2>/dev/null
}

o2() {
  for p in "A1 A2" "A1 B1" "A2 B2"; do
    local l=${p% *} r=${p#* }
    [ -e "$OUT/$l-final.key" ] && [ -e "$OUT/$r-final.key" ] || continue
    say "O2 $l vs $r"
    (cd $B && uv run --no-sync python scripts/deck_decode_diff.py "$OUT/$l-final.key" "$OUT/$r-final.key" --json "$OUT/O2-$l-$r.json" | tail -1 | tee -a "$PROG")
  done
  python3 -I -c "import json,re,sys,os; k=lambda f:{re.sub(r'[0-9A-Fa-f-]{8,}','#',d['key']) for d in json.load(open(f))['diffs']}; n=k(sys.argv[1]); [print(f, sorted(k(f)-n) or 'within null') for f in sys.argv[2:] if os.path.exists(f)]" "$OUT"/O2-A1-A2.json "$OUT"/O2-A1-B1.json "$OUT"/O2-A2-B2.json | tee -a "$PROG"
}

case "$1" in
  live|o1|o2|report) "$1" ;;
  *) print "usage: $0 live|o1|o2|report"; exit 2 ;;
esac

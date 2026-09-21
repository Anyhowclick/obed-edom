#!/bin/zsh
# usage: run_gates.sh <gate-worktree> <outdir>   (runs host gate x3 then P2 x3, serially, from a clean pinned worktree)
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
for V in 2560x1440 1600x1000 1920x1080; do
  $PY -u scripts/live_continuity_probe.py --fixture $F/html-player --original-index $F/html-unmodified/index.html --viewport $V --artifact $O/host-$V.json > $O/host-$V.log 2>&1; summ $O/host-$V.json "HOST $V"
done
run_p2(){ n=$(echo "$*" | tr -d ' '); $PY scripts/p2_recovery_html_adversarial.py --reuse-export --disposable "$@" > "$O/p2$n.log" 2>&1; echo "[P2 $*] $(grep -m1 '^success' "$O/p2$n.log") True=$(grep -cE '^- [A-Za-z0-9]+: \*\*True\*\*' "$O/p2$n.log") False: $(grep -oE '^- [A-Za-z0-9]+: \*\*False\*\*' "$O/p2$n.log" | tr '\n' ' ')"; cp $F/report.json "$O/p2$n.report.json" 2>/dev/null; }
run_p2 --wait-profile fast; run_p2 --wait-profile fast --disable-bridge34; run_p2 --wait-profile slow
$PY -c "from obed_edom.live_continuity_js import js_sha256; print('runtime sha at end', js_sha256())"
pgrep -fl obed-live-chrome | cut -c1-80 | head -2; echo DONE

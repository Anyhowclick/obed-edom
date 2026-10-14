# Review live5 fold r4 (Opus 5.5 high), 2026-10-14 — 0 blocker/major; ready for a fresh live run at both rates

r3 major fixed: each DSK attempt is a fresh placement session (new adapter, LiveOutputHost, CDP transport, hook, page, recording,
snapshots, attempt-N dir); retry only on the exact sole "N mid frames < 5"; no masking (fatal reaches the wrapper; every attempt's
calibration rescored PASS; every attempt MATCH with coverage off; last attempt scored with coverage on); offline --score expands
attempts without double counting; old DSK dirs without attempts → INCONCLUSIVE. W3 sound. 10 targeted tests passed.
Lows (not folded, stop rule): offline score_placement_runs skips a listed-but-missing attempt (:3991) — add INCONCLUSIVE row;
placement_gates drops missing attempt paths before the evidence check (:3236; every-attempt check still fails); genuine attempt
mismatch labelled INCONCLUSIVE not FAIL (:2126); attempts scored without identity (:2118; no effect for DSK); timing_summary omits
DSK attempt script time (:2340/:3864); ForwardOnlyHost proves one session per attempt, not page freshness (live_host.py read);
session calibration kept when opaque-off model fails (:3637-3645; gate INVALID anyway).

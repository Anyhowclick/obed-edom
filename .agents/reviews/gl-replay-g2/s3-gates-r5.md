# G2 headless gates — round 5, PR-citable (2026-09-22, module rev cad2d318, js sha 985afeb1…, stub seam, 1920×1080, 28 arms)

Results `output/live-visible-content/g2/r5/<arm>/result.json`, `gates-r5.json` (provenance, per-arm sha/duration/viewport/seam/result,
uptime/pgrep per batch; 3 Chromes for core + gate-6 lanes, 2 for Q3; load 3.3–8.4).

| Gate | Verdict | Numbers |
|---|---|---|
| 1 install order | PASS | 245 wrapped at install, first `getContext('webgl')` t=86.7 ms |
| 2 full 1→2 | PASS | settleGapMs 100.8, settleToHashMs 99.2; frameLen 88, 0 GL errors, occluded 20/128, `programsDistinct` true, `restOpacity [1,0,1,1,1]`; real oracle LIVE (n=24), paused control DEAD; flag-off HTML byte-identical |
| 3 opacity | PASS, all sub-assertions | clean (29,177,0) · patched (9,52,0) · ablation (0,0,0) · identity equal · rest (29,177,0); residual ≤0.46/ch; write-back readback `[1,0,1,1,1]`; clean pixels immediately after stand-down; positive control detected |
| 4 hand-back | PASS (stub-seam) | settled 2 / P2c / P3 / P4: max|Δ| outside rects∪slot4 = 0 |
| 5 Q3 soak | PASS (2×492 s concurrent) | rvfc→raf at end-of-media, `iter` 2749→27953 (3601/min), 0 GL errors, heap 9.85–10.87 MB flat, dropped 0/1381; `loseContext()` ⇒ `contextLost` by minute 2, `fromEvent`, write-back skipped by reason, hand-off ok |
| 6 fail-closed | PASS 19/20 | every forceable reason stands down as itself, handle unpublished, artifact parity for all 19 incl. `glError` (N4 fixed); `writebackFailed` (D3) secondary by design |

No new defects. Not measured in G2: the real G3 seam (re-run gates 2/4 + Q0b n=2 after G3), one continuous 20-min soak, OBS/CEF,
viewports other than 1920×1080. Opus r1 finding 4 never reproduced (settleToHashMs 99.2 ms).

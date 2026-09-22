# G2 headless gates — round 4 (2026-09-22, module rev e1af6fc7, js sha 39bb40eb…, stub seam, 1920×1080, 28 arms)

Results `output/live-visible-content/g2/r4/<arm>/result.json`, `gates-r4.json` (provenance + per-arm sha/duration/viewport/seam/result,
uptime/pgrep per batch; Q3 sessions run as 2 concurrent Chromes under the new 3-Chrome allowance; the 20.7 load spike was a
concurrent pytest run, rAF rate unchanged at 3601 iter/min).

| Gate | Verdict | Key numbers |
|---|---|---|
| 1 install order | PASS | 245 wrapped at install, first `getContext('webgl')` t=71 ms, arm on `0-canvas` |
| 2 full 1→2 | PASS | settleGapMs 99.8, settleToHashMs 99.8; frameLen 88, 0 GL errors, occluded 20/128; `programsDistinct` true; real oracle LIVE (n=24), paused control DEAD; flag-off HTML byte-identical |
| 3 opacity | PASS, all sub-assertions | clean (29,177,0), patched (9,52,0), ablation (0,0,0), identity equal, rest (29,177,0), residual ≤0.46/ch; write-back readback `[1,0,1,1,0.2947]`→`[1,0,1,1,1]`; clean pixels immediately after stand-down; positive control detected |
| 4 hand-back | PASS (stub-seam) | settled 2 / P2c / P3 / P4: max|Δ| outside rects∪slot4 = 0 |
| 5 Q3 soak | PASS (2×8.2 min) | rvfc→raf at end-of-media, `iter` 2757→27963, 0 GL errors, heap 9.8–10.8 MB flat, dropped frames 0/1381; `loseContext()` ⇒ `contextLost` within a minute, write-back skipped by reason |
| 6 fail-closed | PARTIAL 18/20 | 18 reasons stand down as themselves with full artifact parity; **N4 regression**: `debugForceFail='glError'` no longer fires because `requireGlClean` is only called with `ok=false` after a real failure; D3 `writebackFailed` secondary by design |

N4 fix + gate-6 `glError` arm re-run recorded in r5. Stub-seam throughout; OBS/CEF and other viewports not measured; Q3 = two
8-min sessions, not one continuous 20-min soak.

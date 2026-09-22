# G2 headless gates — round 3 (2026-09-22, module rev f4905aaf, js sha 9c5e6379…, stub seam, 1920×1080, 28 arms)

Results `output/live-visible-content/g2/r3/<arm>/result.json`, `gates-r3.json` (git-ignored). Load 1.7–2.9, no other Chrome.

| Gate | Verdict | Key numbers |
|---|---|---|
| 2 full 1→2 | PASS | settleGapMs 98.3, settleToHashMs 101.3; frameLen 88, 0 GL errors, occluded 20/128; **`programsDistinct` true on the real deck**; real oracle LIVE (n=24), paused control DEAD; flag-off HTML byte-identical |
| 3 opacity | PASS, all sub-assertions | clean (29,177,0); patched (9,52,0); fresh ablation (0,0,0); `only:4,value:0` equal; `rest` (29,177,0); residual ≤0.46/ch; `debug.programs()` live `[1,0,1,1,0.2947]` → after write-back `[1,0,1,1,1]`; pixels clean immediately after stand-down (N3 fixed); positive control detected; unproven slot replays opaque, LIVE |
| 4 hand-back | PASS (stub-seam) | max|Δ| outside rects∪slot4 = 0 at settled 2 / P2c / P3 / P4; P1 246 = playing-movie capture noise |
| 5 Q3 soak | PASS (2×8 min) | `loopMode` rvfc→raf at end-of-media (46.03 s), `iter` keeps advancing 2817→28023 (≈60 fps); 0 GL errors; heap 9.97–10.69 MB flat; handle-video dropped frames {0/1381}; session 2 `loseContext()` ⇒ `contextLost` stand-down within a minute, `fromEvent: true`, write-back skipped, hand-off `{ok, n:1, retired:[2]}` (N1, N2 fixed) |
| 6 fail-closed | PASS 19/20 | every forceable reason stands down as itself, handle unpublished, artifact parity 19/20 incl. `glError`; `writebackFailed` (D3) is a secondary reason and not standalone-forceable by design |

No new defects. Opus r1 finding 4 still not reproduced (settleToHashMs 98–101 ms). Codex r1 fixes (glError helper, canvas-shape predicate,
contextLost exemption by reason, write-back `prev` restore, wrapper install verification, G1b transition-event slot) land AFTER this
round ⇒ one more pass of gates 2/3/6 (+ Q3) on the final sha before the PR is called ready. Still stub-seam; OBS/CEF and other
viewports not measured.

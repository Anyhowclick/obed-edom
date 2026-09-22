# G2 headless gates — round 1 (2026-09-22, module rev c145afb8, js sha c13d6787…, stub seam)

Harness: `output/live-visible-content/g2/{common,stub,g2_flow,analyse,html_parity}.py` (git-ignored), copied from
`alt-pooled`; module injected by the PRODUCT host (`_continuity_scripts` override), never `Runtime.evaluate`. Load 3.3→6.6, no
other headless Chrome. Stub seam: faithful `setKeepWarm`/`note`/`release == remountAll`/`carried` (pooled never-mounted);
approximated: pool-but-never-mount zone, instance selection by captured SIZE (core zeroes x/y on detached elements), sibling
retire, `__obedRect` destination stamp.

| Gate | Verdict | Key numbers |
|---|---|---|
| 1 install order | PASS | 245 wrapped at install, `main.js` absent at install, first `getContext('webgl')` t=90.8 ms, arm on `0-canvas` |
| 2 full 1→2 | PASS | `glreplay-arm`→`glreplay-live`; settleGapMs 100.0, settleToHashMs 99.9; frameLen 88, 0 GL errors, occluded 20/128, `opacityUnproven []`, no `posterAmbiguous`; real `INPAGE_LIVENESS_JS` + `inpage_oracle_result` = LIVE (n=24), paused control DEAD (A4 proven); flag-off control: no handle, no notes, injected HTML byte-identical to pristine |
| 3 opacity | PASS (2 sub-assertions NOT-RUN) | ROI {810,690,300×80}; clean (29,177,0) = opacity plan §0; patched (9,52,0); ablated (0,0,0); predicted (8.55,52.16,0), residual ≤0.46/ch; α=0 identity byte-equal; positive control α≈1 detected (residual 20.5/124.8). NOT-RUN: fresh per-draw ablation, post-write-back `progOpacityBefore` readback (no debug hook) |
| 4 hand-back parity | PASS (stub-seam) | max|Δ| outside rects = 0 at P1/P3/P4 and at settled 2 once `slotRects[4]` excluded; Q0b n=2: one painting `<video>` after build 1, zero `remount-*` while LIVE, hand-off `{ok, n:2, retired:[2]}`; counter monotonic within LIVE, restart after build 1 not shown across the stand-down |
| 5 Q3 | NOT-RUN | held for the fixed module; needs two ~9-min sessions |
| 6 fail-closed | PARTIAL | 19/20 reasons stand down as their reason; artifact parity holds for 14 pre-LIVE reasons, FAILS for contextLost/frameLengthChanged/unflaggedPlayerCall/canvasRemoved/glError (cause D1); `writebackFailed` not forceable |

Defects: **D1 (high, open)** `replayFrame({only:-1})` issues no `uniform1f` (`opts.only != null` true for −1) ⇒ program 4 keeps
the identity probe's sticky Opacity 0 ⇒ unproven slot replays transparent; oracle DEAD. **D3 (low)** `writebackFailed` has no
standalone path. D2 (reason clobbered by detail) fixed in c145afb8. Opus r1 finding 1 reproduced at acbd4946; finding 4 NOT
reproduced (settleToHashMs 99–116 ms at both revisions).
Re-run after fixes: gates 2, 3, 4, 6; after G3: gate 4 + Q0b on the real seam; gate 5 not yet run.

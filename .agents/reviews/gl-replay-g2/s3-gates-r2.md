# G2 headless gates — round 2 (2026-09-22, module rev 8a5ad703, js sha aeaaea6f…, stub seam)

Results `output/live-visible-content/g2/r2/<arm>/result.json`, `gates-r2.json` (git-ignored). Load 1.8–7.7, no other Chrome.

| Gate | Verdict | Key numbers |
|---|---|---|
| 2 full 1→2 | PASS | arm→live; settleGapMs 100.5, settleToHashMs 99.8; frameLen 88, 0 GL errors, occluded 20/128, `restOpacity [1,0,1,1,1] == opacityAfterProofs`; real oracle LIVE (n=24), paused control DEAD; flag-off control byte-identical |
| 3 opacity | PASS (all sub-assertions run via `API.debug`) | fresh ablation (0,0,0); `only:4,value:0` byte-equal; `rest` (29,177,0); patched (9,52,0); residual ≤0.46/ch; write-back readback slot 4 0.2947→1; positive control detected; D1 fixed (unproven slot replays opaque, oracle LIVE) |
| 4 hand-back | PASS (stub-seam) | max|Δ| outside rects∪slot4 = 0 at settled 2/P2c/P3/P4; Q0b n=2 one painting video after build 1, zero remount-* while LIVE; P1 246 = capture-timing noise on a playing movie |
| 6 fail-closed | PARTIAL | 19/20 stand down as their reason; parity 18/20 (late-stage four fixed); `glError` fails (N3), `writebackFailed` not standalone (D3) |
| 5 Q3 soak | FAIL | 2×8 min; 0 GL errors; heap flat 9.87–10.44 MB; dropped frames not captured (harness read DOM video); N1 + N2 below |

**N1 (high, open)** rVFC chain stops at end-of-media (`ended:true` at 46.03 s): `iter` froze at 1281, state LIVE, handle
published, no stand-down, `sample(n)` can never resolve. **N2 (high, open)** the only `contextLost` check lives in the tick
guards and there is no `webglcontextlost` listener: with the loop dead, `loseContext()` produced NO stand-down for 7 min.
**N3 (low, open)** stand-down restores uniforms/poster but never redraws, so a stand-down after a tick's replay leaves the
patched frame composited ((9,52,0) vs (29,177,0)); a `replayFrame({rest:true})` on a live context closes it and gate 6's
`glError` parity. D3 unchanged. Opus r1 finding 4 still not reproduced (settleToHashMs 99.8–116.3 ms).
Re-run after fixes: gates 2, 3, 5, 6 on the final sha; gates 2/4 + Q0b on the real G3 seam.

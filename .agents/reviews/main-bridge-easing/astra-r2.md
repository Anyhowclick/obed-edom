All three r1 classes are closed within the qualified export/runtime scope. **No new reachable correctness class found.** Static review only; no tests run.

1. **Closed class · MAJOR (prior severity) — Unchecked bridge timing.**  
   [live_continuity.py:1390](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/src/obed_edom/live_continuity.py:1390)  
   **Evidence:** Qualification now checks transition start, carried-slot identity, every motion-bearing group, and every motion leaf throughout the single-child chain. Missing easing, offsets, or duration mismatches produce a refusal that prevents runtime admission. Multiple groups are inspected; branching chains fail closed.  
   **Fix:** Implemented; no further change required for this class.

2. **Closed class · MAJOR (prior severity) — Exposure-selected alignment hides lag.**  
   [live_continuity_probe.py:6304](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/scripts/live_continuity_probe.py:6304)  
   **Evidence:** The painted counter determines alignment independently of exposure. Scoring compares both reads; disagreement between optimistic and pessimistic verdicts produces INCONCLUSIVE. Installing the sampler before advancing supports the intended ordering of the next tick’s pre-read before the bridge update. The delayed-overlay regression addresses the original mechanism.  
   **Fix:** Implemented.

3. **Closed class · MAJOR (prior severity) — Aggregate counts conceal missing coverage.**  
   [live_continuity_probe.py:6358](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/scripts/live_continuity_probe.py:6358)  
   **Evidence:** Coverage now bounds gaps throughout the window, including both edges, and checks minimum frame count, discarded share, and sampler cadence. Concentrated captures and extended dropouts cannot pass merely by supplying enough frames elsewhere.  
   **Fix:** Implemented.

4. **Edge case · MINOR — The sync bar creates a content blind spot.**  
   [live_continuity_probe.py:6299](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/main-bridge-easing/scripts/live_continuity_probe.py:6299)  
   **Evidence:** The topmost bar overwrites 96×4 viewport pixels, and the unconditional mask excludes underlying deck content there. Exposure confined to that area is unobservable. P2’s qualified bridge stays well below it, so this does not invalidate the current gate.  
   **Fix:** Before admitting intersecting geometry, place the bar outside the measured trajectory or return INCONCLUSIVE on collision.

The fixture restoration is honest: the complete restored transition matches the available real P2 export after texture sanitization. Exact duration equality compares exported numbers directly; inspected real motion groups/leaves consistently use `0 / 1.5 / EaseInEaseOut`. No concrete legitimate-export rejection was found. Composed ancestor/descendant motion remains an exotic shape, unsupported by the inspected export evidence.

The bar adds paint and sampling work; static review cannot establish zero timing perturbation. I found no concrete false-PASS mechanism from that overhead or its z-order.

Standards: no actionable findings. Spec: three closed classes, one nonblocking MINOR edge case.

**Verdict: APPROVE — all three r1 MAJOR classes closed; no new blocking finding.**
Reviewed HEAD `0217ed7a`, including code fold `f51f70d7`.

| Round 4 item | Status | In-memory verification |
|---|---|---|
| 1 — impossible video measurements | **CLOSED** | `eff=-1` and width `-480` now produce INCONCLUSIVE in DX-1 and CEF. Intact overlay remains FAIL/MISMATCH. |
| 2 — insufficient lifecycle coverage | **CLOSED** | Original goto/back reproductions at action `596 ms`, removal `608 ms`, now produce INCONCLUSIVE: `2 mid frames < 6`. Same result at the new timing. All four `minMid` overrides are removed. |

**The 1.3-second timing still satisfies §9.1’s “mid-dissolve” action.** It interrupts the 1.5-second fade with 200 ms remaining. The screenshot coverage band is a separate requirement. Both adequately covered interrupted captures returned MATCH; actions beyond the observed transition returned INCONCLUSIVE.

Hide/hide-screen remain INCONCLUSIVE at the stated cadence. That unresolved capture issue does not produce a false pass.

No new demonstrated false pass or independent standards finding. **136 callable scorer cases passed in memory**; one filesystem-dependent case was not run. The broader **279 passed, 1 skipped** remains implementer-reported.

**APPROVE**
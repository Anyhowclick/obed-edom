# Critique r3 — `keynote_live_cef_placement.plan.md` rev 3 (091a366c)

Reviewer: Claude Opus 5.5 (plan critic r3, final round). Read-only. Scope reviewed: `git diff d72238ac 091a366c` plus the
rev 3 sections it touches (§2.2, §2.3, §2.5, §5, §6, §7, §8, §9, §10).

## r2 closure check

| r2 # | Status | Evidence in rev 3 |
|---|---|---|
| 1 | closed | §2.2 Persistence defines the baseline as the OBS-saved `AK.json`, or the normalized seed when OBS has not saved. It compares a normalized graph with a field-justified allowlist. Clean quit is authoritative; the after-cleanup read counts only when its mtime postdates the last removal. §5 Persistence row and §8 O5 match. |
| 2 | closed | §2.2: step 0 pins the exact response for an unconfigured DeckLink preview output. Only that response passes; any other error or timeout fails. The duplication seed is conditional on the step-0 moving gate, with readback from disk plus behavior. No invented runtime API. §6 and §7 match. |
| 3 | closed | §2.3 and §2.5: a runtime failure suppresses automatic probes for that engine launch identity. A manual retry does not clear the suppression; a new launch does. §5 `life-cal-*` and §6 rows cover it. |
| 4 | closed | §2.5: renewal runs on a host-owned timer thread, starting at the first probe grant and stopping in `stop()`. The lock wait counts against the renewal budget, and `leaseLapsed` is logged on a miss. Anchors `live_host.py:653` (`call`), `:654` (`with self._lock`) and `:661` (15 s default) are correct. |
| 5 | closed | §2.5 takes option (b): a script-only constructor mode that the product router never passes. A Node row verifies fixed mode and expiry. Product knowledge mode rejects `frac`. |
| 6 | closed | §2.2, §8 and §9 now state that the backup is unreachable by managed launches. No backup mutation is added. |

No fold regressions in safety, scope or Chrome policy. Chrome remains indefinite `snap` only, and no product Chrome probe or
lease has re-entered. The only addition is a script-only constructor argument, which r2 offered as option (b).

## Findings

### 1. low — edge case: derive the persistence allowlist from the no-transaction null
§2.2 Persistence, §5 Persistence/worker row.

**Evidence:** when no pre-transaction OBS save exists, the baseline is the seeded file (`managed_obs.py:157`). The post-quit
OBS save then carries OBS-added keys that are absent from the baseline, not "present in both", so the example allowlist
wording does not cover them.

§5 already runs a no-transaction null through the same launch and clean-quit flow. That null shows exactly the differences
OBS introduces without any probe.

**Fix wording** (append to §2.2 Persistence): "The allowlist is the normalized diff observed in the no-transaction null run
(same launch, same quit path); a candidate run fails on any difference beyond the null's, field by field."

This needs no re-review.

## Counts
blocker 0 · major 0 · medium 0 · low 1

## Verdict
**READY.** All r1 and r2 findings are closed in substance. The single low may be folded in the implementation contract
freeze without another critique round.

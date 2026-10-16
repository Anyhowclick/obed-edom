# Critique r2: predraw-geometry.plan.md

**Verdict: NOT READY.** 0 blocker, 0 major, 3 medium, 3 low. Every fix below is a wording change, so r3 should only need to confirm them.

## r1 findings: are they folded?

All r1 findings are folded except D3, which is only partly folded (see N3).

| r1 | Status | Where in r2 |
|---|---|---|
| B1 | Folded | Design 3; plan lines 36-37. Only visible samples are folded, a frame with no visible sample emits 0, and a null from a visible sample is sticky. Visibility is the opacity-aware `visible()` (`mm_feed_instrument.py:117-120`). The plan's test list now includes "hidden post-hide movement ignored". |
| M1 | Folded | Step 0 gates all later work, with an owner stop above 1 px. |
| M2 | Folded | Aggregate branch in `mm_feed_control_aggregate_problems`, plus two `MM_FEED_ARMS` lines with the heredoc unchanged. The checker already calls the aggregate (`run_gates.sh:767`). |
| M3 | Folded | 6 positives and 4 controls; old/new comparison on fresh producers; 320 kept. |
| D1, D2, D4, L1, L2, L3, L5, L6 | Folded | |
| D3 | Partly folded | See N3. |
| L4 | Folded, then overshot | See N2. |

## New issues

### N1 (medium): the new contract rule refuses a whole report over one thrown draw

The rule is "A context with recorded draws must have a finite completion timestamp" (plan line 64). Test 4 adds a matching "timing consistency" case.

- Contexts carry no draw count. The rule would have to infer one from `frames[].draws`.
- That counter is incremented before the original call (`mm_feed_instrument.py:264` happens before `:273`).
- Design 4 says a thrown draw does not stamp `firstDrawAt`.
- So a single thrown draw makes the whole report fail the contract. Every under-artwork carry then reads None (`live_continuity_probe.py:4355-4373`), even though the only consequence the plan intends is "no exemption".
- r1 rejected this inference for the same reason.

**Fix:**
- Delete the second sentence of the `firstDrawAt` contract row.
- In Test 4, replace "timing consistency" with "`firstDrawAt` < `createdAt` rejected".
- Keep the scorer rule (plan line 39): a null or out-of-order `firstDrawAt` grants no exemption.

### N2 (medium): refusing all v1 reports goes beyond L4 and forces fixture churn

The plan now says "require version 2 at ingestion, and always refuse v1 reports" (plan line 66), and Test 4 says "Update producer fixtures deliberately to v2".

- Requiring the two new keys already refuses every real v1 file, because no v1 producer emits them. L4 only asked the plan to say so.
- Explicit v1 refusal adds nothing. It does force three v1 producer fixtures over to v2:
  - `tests/test_live_continuity_probe.py:12295`
  - `tests/test_live_continuity_probe.py:12524`
  - `tests/test_live_evidence_contract.py:347`
- A v2 fixture must carry `browserFrames`, `handbacks` covering every closed context (`live_evidence_contract.py:901-911`), and `frameIndex`/`frameTimestamp`/`generation`/`visit` throughout.
- It also flips `evidenceVersion==2` strict hand-back on the normalized record (`:947-952`). That can move unrelated leaf assertions, such as the test at `test_live_continuity_probe.py:12386`.

**Fix:**
- Replace the first sentence of plan line 66 with: "Keep the existing v1/v2 branching and require both new keys in every version. This refuses every real v1 file and every older v2 file, because neither producer emits them."
- In Test 4, replace "unconditional v1 refusal. Update producer fixtures deliberately to v2" with: "add the two new keys to the existing producer fixtures, and assert that deleting either key is refused".

### N3 (medium): D3 is only half folded; there is no environment setup for 3.12 or the dashboard

- This worktree has no `.venv`. A bare `uv run` builds an environment without the extras or xdist. The documented symptoms are about 187 `ModuleNotFoundError` failures, or `-n auto` rejected as an unrecognized argument (memory: worktree-env-setup).
- `dashboard/node_modules` may also be missing, or lack `tsc`.
- Step 0's `uv run python scripts/live_continuity_probe.py` needs the same environment.

**Fix:** under "Coordination and evidence", before `uv run python --version`, add as one heavy step:

```sh
uv sync --frozen --all-extras --all-groups --python 3.12
(cd dashboard && npm ci)
```

Then add: "Run pytest with `-rs`. Report the skip counts; a fresh worktree skips about 70 extra tests unless the main checkout's git-ignored fixtures are linked."

## Low

- **L-a. Step 0 needs no throwaway wrapper.** The permanent `authoredSrcRect` and `feed_specs_for` change has no effect on scoring: continuity's `srcRect` is untouched, and the contract ignores extra keys (`_fields`, `live_evidence_contract.py:115-120`).
  - **Fix:** land that two-line probe change in Step 0. Delete the "temporary session-scratch probe wrapper" paragraph and the "During Step 0 use the scratch wrapper" sentence.
- **L-b. The departure-early-hide expectation is too strong.** The row for D7 departure-early-hide reads "True, exempt True for its bounded prefix". `exempt` still depends on `preDrawMs` ≤ 320.
  - **Fix:** change the row to "True; 0 exempted visible samples; exempt True when the timing bounds hold".
- **L-c. A line-number citation is stale.** The plan cites `.agents/skills/obed-edom/SKILL.md:42-59` for the suite commands. The xdist command is at `:50`, and the dashboard commands are at `:43-46`.
  - **Fix:** cite `:43-50`.

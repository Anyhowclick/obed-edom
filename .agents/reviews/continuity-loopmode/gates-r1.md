# Looping movies (`loopMode`) headless gates r1 (2026-09-24)

Plan: `.agents/plans/keynote_live_continuity_loopmode.plan.md` rev 2, §5. Branch `claude/continuity-loopmode`.

**Verdict:** L0, L1, L2 and L4 PASS. L5 (managed OBS) is pending the OD-2 merge (WS-C). One measured residual (OQ-4(a)),
below.

## Provenance
- Gate worktrees: `.claude/worktrees/loop-gate-pr` (detached, `21944ddb` → `229e409b` → `96eb6d68`) and
  `.claude/worktrees/loop-gate-main` (detached, `bd9ae9f4`), clean at start and end, fixture symlink to main-checkout
  `output/p2-recovery/html-adversarial`. One headless Chrome at a time; `uptime` per take in the logs (load 4–28).
  No Keynote, no OBS.
- Shas: core `e9338aff…` at start and end of every L4 run, identical on PR and main; both JS modules byte-unchanged
  vs `bd9ae9f4`. `output/p2-loop` built by `scripts/loop_fixture.py` from `output/p2-recovery/html-adversarial`
  (source shas asserted unchanged): `loopMode: "looping"` on objectIDs `6BB39942`, `CBACAF27`, `F9AFED1B`, `98D59E27`,
  `E4728E7D` in 16 files; plan shas off `3dc67558…`, on `2ba6fbed…` (allowlisted in `21944ddb`).
- Evidence (git-ignored): main checkout `output/evidence/loop-gates/` — `l4-{pr,main,final}.txt`, `l1/`, `l2/` (r1), `l2r2/`,
  `diag/` (`codex/` not retained); driver `output/evidence/loop-gates/l2.sh`.

## Results

| Gate | Verdict | Numbers |
|---|---|---|
| L0 unit | PASS | Full suite at `cc270631`: 7543 passed / 88 skipped / 1 xfailed; `test:ui` 305/305; `test:maps` 542 + 2. KB at `bd9ae9f4`: `possible mask: <movie node>.movie.loopMode` |
| L4 P2 regression | PASS | `run_gates.sh` at `21944ddb` and at `96eb6d68` both line-for-line identical to `bd9ae9f4`: host 3 viewports, P2 fast/slow 14/14, `--disable-bridge34` red only on `continueThroughMovingMagicMove3to4` |
| L1 host on `p2-loop` (`229e409b`) | PASS | `qualified`, every verdict equal to the P2 host run at 2560/1600/1920; `--gl-replay auto` Vgl 4/4 True. CvC: 1920 take 2 identical. KB: `bd9ae9f4` exits 1 ("does not derive a continuity plan") |
| L2 CvC | 0 | `--rescore` of the three `bd9ae9f4` host artifacts: strict == wrap-aware == stored, all arms |
| L2 sweep (`96eb6d68`, re-scored at `cc270631`) | PASS | 3→4: 6/6 offsets carried (−200, 0, 375, 750, 1125, 1700 ms). 1→2 (G2 armed): every offset carried in ≥ 1 valid take; 0 FAIL. Page errors 0 |
| L2 KB | FAIL (required) | Non-looping P2 fixture, same pre-seek, 1to2 and 3to4: "no wrap was recorded" |

## Harness defects found by the gates (fixed before the verdict)
- `229e409b` r1: every armed 1→2 take failed — the recorder window came from the page sampler, which never sees the
  detached carried `<video>`. Fixed in `96eb6d68` (window = seek + 1 s → last destination read).
- r1 3to4_750 failed on one row: at the wrap the browser's loop seek drops `readyState` to 1 for one sample and the
  core's `footprintOwnerDecoderId` (requires ≥ 2) answers `via: 'none'`. The wrap-aware scorer excuses exactly that
  row (finite readyState < 2, same-element owned neighbours; `wrapOwnerExcused`). The r2 take did not hit it.

## Residual (OQ-4(a), reported, not fixed)
6 of 16 armed 1→2 takes are INVALID (wrap 150–210 ms later than planned): the carried decoder presents no new frame
for ≈ 180–220 ms about 300 ms after the press. Below `MAX_STALL_S` (0.3 s). Seen only with the loop point within
≈ 2 s of the press; 0/8 takes (3 looping, 5 non-looping) with the wrap 3 s after the press showed a gap > 100 ms.
On air: at most a brief hitch of the movie during a 1→2 Magic Move that coincides with a loop wrap.

## Reviews
Codex (gpt-5.6-sol) r1 on `21944ddb`: 4 major + 1 minor + 2 nits folded (`229e409b`); the "allowlisted before L5"
blocker is sequencing — the PR waits for L5. r2 on `96eb6d68`: 1 medium + 2 low folded (`cc270631`). r3 on `cc270631`:
all folds closed, no spec findings; two standards nits (stale plan progress, duplicated test helper) fixed.

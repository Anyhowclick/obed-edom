# S1 (instrument first): gate record

Plan: `.agents/plans/keynote_live_continuity_generalisation.plan.md` §3 S1, §4. Branch `claude/cranky-williamson-31f272`.
Every final gate ran at merge commit **`421b4f39`** (S1 + origin/main through #235), from a detached worktree with the
P2 fixture symlinked. Product runtime files (`live_continuity_js.py`, `live_gl_replay_js.py`, `live_continuity.py`,
`live_host.py`, `live_runtime.py`) are byte-identical to origin/main, and the core sha is unchanged
(`e9338aff…01fa4`). Evidence (git-ignored, main checkout): `output/evidence/s1-gates/{r1-331f944d,r2-8ac39a42,r3-421b4f39}/`.

## Result: PASS (`run_gates.sh` → `DONE failed=0 pending=0`, load 14 → 8)

| Gate | Arm | Result |
|---|---|---|
| G-S1b host | 2560×1440, 1600×1000, 1920×1080: A/B/C + attach + V/Voff, plan-generated verdicts | pass ×3 |
| G-S1b P2 | fast, slow, `--gl-replay auto` | 15/15, success True; auto has `glReplayCarry1to2` present and True |
| P2 oracle | `--disable-bridge34` | red exactly {continueThroughMovingMagicMove3to4} |
| G-S1c stray | host `--core-variant stash-any` | red exactly {stray:slide4:vid-20250608-wa0125.mp4} (variant core sha `907a19aa…`) |
| G-S1c stray | P2 `--core-variant stash-any` | red {noStrayVideo, continueThroughMovingMagicMove3to4}, inconclusive {freezeControlCaughtByCounter} ¹ |
| G-S1d | host `--strip bridge@8` / `retire@2` / `restart@6` / `glReplay@2 --gl-replay auto` | exact match each ² |
| G-S1d | P2 `--strip bridge@8` / `glReplay@2` / `restart@6`, auto `--strip glReplay@2` | exact match each ² |
| G-S1a rescore | l4-final host ×3 (pre-S1 artifacts) | re-derivable 12/12 reproduced; 4 not re-derivable (INCONCLUSIVE: no raw evidence retained) |
| G-S1a rescore | r3 host ×3 | 16/16 reproduced |
| Suites (at 421b4f39) | pytest `-n 4`, `test:ui`, `test:maps` | 8395 passed / 88 skipped / 1 xfailed / 0 failed; 305/305; 542+2 |

¹ The stray WA0125 overlay paints at authored (109,795,485×273) on slide 4. That overlaps the bridged movie's slide-4
rect (327,709,1266×356), so the variant itself corrupts the 3→4 measurement. This was seen in r1, r2 and r3.

² Registered **post hoc** from discovery run r2 (`8ac39a42`, `--allow-record`), then confirmed unchanged in r3:
- host `restart@6` = {b2to3 carry};
- P2 `glReplay@2` = {noStrayVideo, refusedCarry1to2};
- P2 `restart@6` = {continue3to4} + inconclusive {freeze};
- P2 auto `glReplay@2` = {glReplayCarry1to2, noStrayVideo};
- the slide-2 stray added to host `glReplay@2` after r1.

Everything else was pre-registered before any live run.

## Rounds
- **r1 (`331f944d`, discovery; load 140–154):** it found that "exactly one `retire-boundary`" (a Codex r1 rule)
  contradicts the core. The core emits `preserve-refused`, so the rule was fixed to the core's documented contract.
  The extra P2 restart reds and the host `restart2to3=None` were a load artefact plus an instrument defect (the restart
  window missed the ~2 s dissolve), both fixed.
- **r2 (`8ac39a42`, discovery, `--allow-record`):** all host arms and P2 baselines matched. It recorded the remaining
  sets, and showed a stripped bridge must skip the freeze bracket like `--disable-bridge34` (fixed in `d31acefc`).
- **r3 (`421b4f39`, final, after merging main #232–#235 incl. MM opacity's patched `main.js`):** all MATCH; the patch
  shifted no registered set.

## Reviews
- **Codex `gpt-5.6-sol` r1:** 11 findings, all folded.
- **Codex r2:** closure pass plus 4 new findings, all folded.
- **Opus r3** (fallback; Codex quota exhausted): N1–N3 folded, the medium items folded.
- **Decisions to carry forward:**
  - `noStrayVideo` is stray-only (R1-9 closed by narrowing; presence stays with refusedCarry/glReplayCarry,
    deliberateRestart2to3 and continueThroughMovingMagicMove3to4).
  - Retire = ≥1 `preserve-refused|retire-boundary` note in `[atScene-1, next transition scene)`, no carry notes, plus a
    positive hand-back of the player's `<objectID>-video` from settled samples.
  - Legacy P2 scoring only for the pinned P2 / p2-loop plan shas.
  - Verdict ids `b{from}to{to}:{asset}#{src}->{asset}#{dst}:{kind}`.

# Live continuity generalisation: S2 handover (2026-09-25, owner away on vacation)

Plan (source of truth): `.agents/plans/keynote_live_continuity_generalisation.plan.md`, rev 2 + S0, owner-approved.
- **S1** merged as #237 (`2ee95223`); its gate record is `.agents/reviews/continuity-generalisation/s1-gates-r1.md`.
- **S2** is on branch **`claude/continuity-generalisation-s2`**, pushed as a backup with **no PR** (owner, 2026-09-25).
  Do not merge; nothing in it is qualified.

## Resume r1 (2026-09-25 night, 20:15–22:00): READ THIS FIRST
- **Rebased onto main `45290c5f` (#238, hand-back geometry).** The branch **`claude/continuity-generalisation-s2`** was
  synced to the rebased head (owner, 2026-09-25) and is still the one S2 branch, with no PR. The pre-rebase head was
  `51023b1e`, which the gate worktree `s2-gate-089a0393` keeps for A/B. The interim branch
  `claude/keynote-live-continuity-resume-8d49da` was deleted from the remote.
  - Conflicts: two, trivial (the `fixture` import and a docstring in `managed_obs_qualify.py` and its test).
  - Follow-up commit `4a2ea70f` routes #238's new `p2-binary` paths through `fixture()`. Without it the S2 guard
    `test_fixture_paths` fails.
  - #238 touches only the player patch (`live_runtime.py` R6–R8). The continuity core is unchanged (`9c4fc61f`). One
    functional interaction: R8 preloads scene B+1 before a Magic Move, near where the core detects teardown.
- **Rebased again onto main `6fc85b78` (#239) and then `6742b9fd` (#240), both docs-only, after the runs.** `4a2ea70f` is now `e1345b38`; its `src/`,
  `scripts/`, `tests/` and `dashboard/` are byte-identical (`git diff --quiet`). Every result and evidence directory
  below named `4a2ea70f` stands for `e1345b38`.
- **Suites green at `4a2ea70f`:** pytest 8698 passed, 89 skipped, 1 xfailed, 0 failed; `test:ui` 305/305; `test:maps`
  542 + 2, 0 failed.
- **P2 harness arms at `4a2ea70f`** (`run_gates.sh` P2 section only; evidence in main checkout
  `output/evidence/s2-dev/p2-4a2ea70f/`): `DONE failed=4 pending=0`.
  - **MATCH (the §3.4 Q2 table equals main's):**
    - fast and slow: 14 unique checks (the "15" counts `preserveDidNotBlockRestart` twice);
    - `--disable-bridge34`: red exactly on continueThroughMovingMagicMove3to4;
    - `--strip bridge@8`;
    - `--gl-replay auto`.
    - Slide-3 restart clock (fast) is t = 0.094 s, inside main's stock band (limit 0.35 s), so R8 costs no margin here.
  - **MISMATCH × 4, all in registrations made on the S1 core. None is registered yet.**
    - `--core-variant stash-any`:
      - Extra reds `refusedCarry1to2`, `overlayRemovedOnLeave` and `preserveDidNotBlockRestart`; freeze still
        inconclusive.
      - The stashed slide-1 `untitled.mov` remounts across the refused 1→2 boundary (15 carry events in the retire zone)
        and lingers.
      - Matches the v6 host set (slide-1 retire plus strays on slides 2–4).
    - `--strip restart@6`:
      - Now **all green**; the registration expected red on 3→4 plus inconclusive freeze.
      - Matches the v6 host set `()` and its reason in `RED_ARM_EXPECTATIONS`: slide 2's source is retired at 2 and
        never carried, so the entry is inert.
      - Consequence: this arm no longer shows that P2 depends on the restart entry.
    - `--strip glReplay@2` (GL off and `--gl-replay auto`):
      - `noStrayVideo` turns green and `preserveDidNotBlockRestart` turns red.
      - The red is an **instrument false red**. Every negative clause is clean: empty pool census, zero carries in the
        zone, no reuse after the boundary.
      - Only the "never pooled" positive route fails: `refusalEventsN` is 0, against 2 at baseline. With the entry
        stripped, v6 never names slide 1's decoder, so it emits no `preserve-refused` note.
      - `noStrayVideo` is green because v6 no longer FIFO-pools an unnamed decoder.
  - **Decision needed before any re-registration:**
    - `stash-any` and `restart@6`: re-register to the v6 sets, with the reasons above.
    - `glReplay@2`: either re-register with `preserveDidNotBlockRestart` red, or teach the check that "nothing named
      the key, so no note can fire". **Rec: re-register.** The instrument change would also touch main's S1 check.
- **R8 control:** the four mismatching arms were re-run on the pre-rebase gate worktree `s2-gate-089a0393` (same core).
  Evidence: `output/evidence/s2-dev/p2ctrl-089a0393/`. Result: `stash-any`, `strip glReplay@2` (off) and `strip restart@6`
  give **identical** red sets pre-rebase. The P2 registration mismatches are therefore v6-core changes and have nothing
  to do with #238. The auto-mode `glReplay@2` arm was not re-run because it has the same mechanism.
- **Decks at 2560×1440 on the rebased head** (`4a2ea70f`; evidence `output/evidence/s2-dev/decks-4a2ea70f/`):
  - Results: D2 and D3 pass. D1, D4 and D6 fail in arm C (bridges stripped). D5 fails in `attach`, which is forced to
    1920.
  - The round was stopped early to run the controls. **The 1600×1000 round and Pass G have not run.** The partial
    `ABORTED-D1-1600x1000.*` is void.
  - **New finding: an intermittent one-frame detach of the carried decoder at the `Playing` onset (leans R8; not
    proven).**
    - Every failure has the same signature: one rAF sample where `document.querySelectorAll('video')` is **empty**,
      the first `Playing` sample of the transition.
    - Everything else about the carry is clean: same element, smooth clock, no owner or rect mismatch.
    - A synchronous re-home can't be seen between frames, so the decoder was really out of the DOM across a frame
      boundary. That is a real one-frame blink.
  - **Scan of every deck artifact** (empty samples flanked by non-empty ones):

    | Head | Deck runs | Runs with an empty sample at `Playing` onset |
    |---|---|---|
    | Pre-rebase (i1–i4 + control D1 @ 2560) | 25 | **0** (only 2 at `SettingUpScene`, in pre-fix i2/i3 D6) |
    | Rebased, 2560 round | 6 | **6** |
    | Rebased, D1 repeat | 1 | 0 |

  - Not load: i4 ran at load 24–40 and stayed clean. Not viewport: D5's attach arm runs at 1920. Intermittent: the D1
    repeat passed.
  - Hypothesis: the player's teardown removes the decoder's container, and the core re-homes the decoder a task later.
    #238's R8 (`loadScene(B+1)` before a Magic Move) adds work at transition start, which pushes the re-home past a
    frame.
  - **Interleaved A/B** (D4 @ 2560, 4 runs per head alternating, 21:15–21:31; `output/evidence/s2-dev/ab-r8-D4/`):
    rebased 1/4 (rebased-3, arm C `b1to2`, same signature); pre-rebase 0/4.
  - **Totals: rebased 7/11, pre-rebase 0/29.** Six of the rebased hits fell in one cluster (the 20:52–21:03 round);
    outside it the rebased head is 1/5.
  - Verdict: **it leans toward #238/R8 but is not proven.** The cluster is unexplained. That round ran right after the
    nine P2 arms, at load 6–11, with nothing else running.
  - **Link to #238's documented R8 limit** (owner pointer; `keynote_live_handback_geometry.plan.md` §R8 and SKILL "R8
    preloads the destination slide only when…"):
    - An automatic-play MM with no idle stop before it is never preloaded and stays stock.
    - Engagement is timing-dependent.
    - Slide g+1's render now runs in the idle **before** the move, so a fast advance can overlap it with the MM's first
      frames. That case is **UNVERIFIED** in #238.
    - In every D deck, each slide runs `movie-start` (`automaticPlay: true`) and then an on-click MM
      (`automaticPlay: false`). So every D-deck MM has an idle stop and R8 can engage. Whether it does depends on whether
      the g+1 render finishes before the probe's click.
    - That matches an intermittent, clustered failure better than a constant cost. All failures sit at the MM's
      `Playing` onset, mostly in arm C, where the bridge is stripped and the decoder stays inside the player's MM
      subtree.
    - Test: log R8 engagement per MM next to the blink, e.g. `mixFactor` as `mm_opacity_probe` does, or `slideCache[g+1]`
      ready at MM setup. If the blink occurs only with engagement or overlap, R8's timing is the cause.
  - Next session: a larger interleaved A/B (≥ 10 per head). Better still, a direct test: the rebased head with R8's
    third replacement dropped, since `mm_opacity` off removes R6–R8 together. Instrument the core's re-home with
    `performance.now()` against the rAF timestamps to see the gap directly.
  - **Fix direction (not started):** re-home in the same task as the teardown, e.g. a MutationObserver or a hook on the
    player's removal, rather than on the next tick. Or keep the decoder outside the player's torn-down subtree. Decide
    after the A/B.
- **Next, in order:**
  1. **The one-frame detach.** Pin down the cause (see the A/B verdict above). Then fix it in the core (the sha changes,
     so every red-arm variant sha re-derives), and re-run the dev loop on D1–D6 at 1920 and 2560.
  2. The owner's registration decision above; register with the reasons, citing the pre-rebase control.
  3. Finish step 2: the 1600×1000 round and Pass G for D1–D6.
  4. Step 3: a full `run_gates.sh` without `--allow-record` on the rebased head.
  5. Step 4, review. The list below is otherwise unchanged.
- The scratch runners used tonight (a P2-only slice of `run_gates.sh`, the deck loop and the A/B) were one-offs in the
  session scratchpad. Nothing in the repo changed apart from `4a2ea70f` and this handover.

## State at the stop (2026-09-25 evening)
- **Head:** `claude/continuity-generalisation-s2`, core v6, sha `9c4fc61f…` since `089a0393`. The branch is pushed; there
  is no PR.
- **Unit suites green at `089a0393`:** pytest 8548 passed, 88 skipped, 1 xfailed, 0 failed; `test:ui` and `test:maps`
  were green at the S2.0 head.
- **Dev loop i4 (1920×1080, headless):** P2 and all six S0 decks D1–D6 pass on the host probe.
- **Host-only discovery round (`g1h-089a0393`, `--allow-record`, P2 arms skipped at the owner's call to free the machine
  for another session's OBS run):**
  - P2 host gate passes at 3 viewports.
  - All 16 registered host/deck red arms MATCH.
  - Both required reds fire: P2 stash-any turns the WA0125 slide-4 stray red, and D4 `wrong-instance` turns the far
    copy's carry red. `fifo-reuse` on D4 turns the same carry red, so today's FIFO pick would carry the wrong copy.
  - 11 record-only arms were registered after the fact (see commit).
  - Evidence (main checkout): `output/evidence/s2-dev/{i1..i4,g1h}-*`.
- **P2 harness on the S2 core:** last run at i2 (`bd51641f`): fast 15/15, `--disable-bridge34` red exactly on
  `continueThroughMovingMagicMove3to4`, `--gl-replay auto` success. It has **not** been run on core `9c4fc61f`.

## Done in S2
- **S2.0 fixtures** (`31723253`…`c1782ce0`). Every fixture resolves through `obed_edom.fixture_paths.fixture(name)` to
  `<main checkout>/output/fixtures/<name>`. The coordinator moved the eight fixtures there on 2026-09-25 and left
  **compatibility symlinks** at `output/<name>` for sessions in flight; delete them once nothing cites the old paths.
  Worktrees need nothing symlinked.
- **WS-D derivation v2** (`786f0b9f` contract, `8f70c061` fixtures, `4f21e558`, `66eb56c3`, `d0062744`):
  - schema-2 per-instance plans and min-centre-distance pairing;
  - refusals R1–R8 (per boundary, except R3/R5, which refuse the deck);
  - a mid-deck `none` transition counts as a cut;
  - the `loops` annex is deleted;
  - the allowlist is re-pinned to P2 off/on, p2-loop off/on and D1–D6.
- **WS-R core v6** (`7930797b`, `c069c424`, `8207b263`): objectID carry, pooled ∪ held candidates, and every F5 name
  kept. GL replay is byte-identical.
- **WS-P** (`cce28d0f`, `339850bc`, `92f85abf`): P2 injects schema 2, host `notCarried` is reported per instance with an
  R-code, and the README/SKILL contract text is updated.
- **WS-G probe** (`51bc925d`, `d63b12fd`, `2c8b9aa0`, `15ab0a96`): the probe reads schema 2, core variants are
  re-anchored, S0 deck red arms are in `run_gates.sh`, and the i1 instrument defects are fixed.

## Dev loop
- **i1** (`8207b263`, 1920×1080, headless; evidence in main checkout `output/evidence/s2-dev/i1-8207b263/`):
  - P2 host passes, P2 fast is 15/15, and `--disable-bridge34` is red exactly on continueThroughMovingMagicMove3to4.
  - Every D deck failed. WS-G split the failures into three instrument defects (fixed in `15ab0a96`) and five core bugs:
    - **RT-A:** the next bridge's motion starts one scene early, on arrival at the settled slide.
    - **RT-B:** a retire zone opens one scene early.
    - **RT-C:** `footprintOwnerDecoderId` returns null when an unplanned same-asset sibling is on the slide (D5).
    - **RT-D:** the facade stub keeps painting beside the carried decoder.
    - **RT-E:** a pin after a held bridge is frozen on screen (probably under the WebGL canvas).
- **i2** (`bd51641f`, core `6b0db51e`):
  - P2, D1 and D4 pass. P2 harness: fast 15/15, `--disable-bridge34` exact, `--gl-replay auto` success.
  - Two more core bugs were fixed in `1556e7f1`, `6f6f5f5d` and `3ce02bd6`:
    - pinned decoders started the next move early;
    - D5 slide 3 froze under the destination poster (a regression from the RT-D fix).
  - Retire hand-back moves to the start of the outgoing transition (plan contract, coordinator decision). Handing back
    there lets the raw player's WebGL fade-out draw the ending movie; holding it through the move would pop at the cut.
- **i3** (`3ce02bd6`):
  - P2, D1, D4 and D5 pass.
  - Probe fix `ec2d4523`: the retire zone is placed by page time, not by hash.
  - Core fixes `1c9831d1`, `089a0393` and `cef5a946` (core `9c4fc61f`):
    - a pin's snap-back after the move;
    - a held pin frozen through the next bridge;
    - D6's retire landing at the cut.
- **Key model fact (WS-R, from `main.js` `updateNavigationButtons`):** while idle at the end of a scene the hash
  already shows the NEXT scene index, so `#atScene-1` appears both at rest and during the transition. The core
  therefore detects the transition start from the player's teardown or its second `replaceState` write of the same
  index. The probe places windows by sampled time and `sceneId`, never by hash.
- **i4** (`089a0393`, core `9c4fc61f`, 1920×1080): **P2 and D1–D6 all PASS.**


## Findings to carry
- **P2 output is inside the shared fixture tree:**
  - `runs/`, `report.json` and `html-disposable` sit under `fixture("p2-recovery")/html-adversarial[/gl-replay]`.
  - Two concurrent P2 runs from different sessions trample each other (collision with the "build-1 GL→DOM geometry"
    session, 2026-09-25 18:00).
  - Needed: a per-run output directory outside the fixture (and a lock).
  - Until then, **one P2 run machine-wide**.

## Open decisions for the owner
- **Plan §4 strip locality vs chains.** Several arms, registered after the fact from g1h (`90c0bcc6`), turn red beyond
  their own boundary:
  - D2 `strip:restart@4`: also 2→3 and 3→4, plus duplicates on slides 3 and 4 and a stray on slide 5;
  - D3 `strip:pin@4`: also 2→3, a duplicate on slide 3 and a stray on slide 4;
  - D1 `pin@6` and D4 `pin@5`: red only as a duplicate, never as the pin carry itself.

  Removing one link from a chain legitimately cascades. Options:
  - (a) amend §4 to "red on its boundary, plus the documented cascade of that chain";
  - (b) score strip locality only on single-link arms.

  **Rec (a).** WS-G's locality test currently skips these 11 arms.
- **P2 output inside the shared fixture tree** (see Findings): approve a per-run output directory plus a lock for P2.

## Last full suite
Green at `089a0393` (8548 passed). `90c0bcc6` changed only the probe registrations; the probe file passes (1013), but
the full suite was deferred because another session was running a load-sensitive OBS gate. Run it first on return.

## Remaining to finish S2 (in order)
1. **P2 harness arms on the current core.** Run `run_gates.sh`'s P2 section (fast, slow, `--disable-bridge34`,
   stash-any, strips, auto). Re-register the P2 `run_p2` sets **only** where the v6 core legitimately changed them, each
   with a written reason. Plan §3.4 Q2 requires P2's table to equal main's S1 table, so any difference is a finding
   first.
2. **Decks at all 3 viewports and visible passes** (only 1920 ran), plus the D decks' plan-derived go-to arm (pass G).
3. **Full `run_gates.sh` round without `--allow-record`:** it must end `failed=0 pending=0`. It confirms the post-hoc
   registrations.
4. **Review:** Codex `gpt-5.6-sol` if its quota has reset, else Opus (OQ-12). Send the whole S2 diff since `2ee95223`.
5. **The ONE re-qualification (plan §3.4):**
   - Q2 P2 oracle, interleaved with main; Q3 host + decks; Q4 G2 seam; Q5 loop L1/L2 plus D6.
   - Q6 managed OBS at 25 and 30, all arms. **Needs the owner's OBS go.**
   - Q7 real-OBS attach on D1 + D4, plus the **owner's eyeball** in Keyer mode on D1–D5.
6. **Allowlist:** at the gate commit keep only the passing decks (§3.4), then open the S2 PR. **Never merge without the
   owner.**
7. **Housekeeping:**
   - Delete the `output/<name>` compatibility symlinks once no session uses the old paths.
   - Remove the gate worktree `s2-gate-089a0393` once its commit lands.
   - Fix the P2-output-in-fixture hazard (see Findings).

## Agents
All S2 implementer agents (WS-D, WS-R, WS-P, WS-G) were stopped at wrap-up; their final reports are summarised above.
Nothing is left running.

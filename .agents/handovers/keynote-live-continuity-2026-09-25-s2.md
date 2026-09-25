# Live continuity generalisation: S2 handover (2026-09-25, owner away on vacation)

Plan (source of truth): `.agents/plans/keynote_live_continuity_generalisation.plan.md`, rev 2 + S0, owner-approved.
- **S1** merged as #237 (`2ee95223`); its gate record is `.agents/reviews/continuity-generalisation/s1-gates-r1.md`.
- **S2** is on branch **`claude/continuity-generalisation-s2`**, pushed as a backup with **no PR** (owner, 2026-09-25).
  Do not merge; nothing in it is qualified.

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

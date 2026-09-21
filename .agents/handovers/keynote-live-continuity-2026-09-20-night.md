# Handover — Alpha Keynote live continuity, state at 2026-09-20 22:45

Supersedes the "where things are" table in `keynote-live-continuity-2026-09-20.md` (its "Paid-for facts", "Commands"
and gotchas still hold). Owner rules unchanged: accuracy and code quality over speed · plan first · never weaken a gate ·
minimal natspec, no inline comments in src · no merge / auto-merge without the owner · hands off Keynote · ask before a
window on the external monitor · port 9222 / OBS only on the owner's word. Roster: Opus plans, Sonnet implements, Codex
`gpt-5.6-sol` reviews — this session escalated the freeze-control fix round to Opus after two Sonnet rounds failed review.
Relay rule (owner, 2026-09-20): a verbatim go relayed by the owner's courier session is accepted for reversible
implementation work; never for merges, destructive actions, Keynote/OBS, or config.

## Where things are (verified 2026-09-20 ~22:05 with `git worktree list` / `gh pr list`)
| Branch | What | PR |
|---|---|---|
| `main` (`c3e9a6be`+) | #158 (all Alpha Keynote work), #177 (research results + plans), #178/#180 (vendored skills) MERGED today | — |
| `feat/p2-freeze-control-3to4` | freeze negative control re-bracketed at 3→4 — IN PROGRESS, see §1 | none yet (open after Codex PASS + gate round) |
| `claude/keynote-live-plans-round2` | docs: paint-oracle decisions, go-to repair plan, GL-replay arming plan, this handover | none yet — open a docs PR |
| `fix/maps-failing-tests` (#179), `fix/plan-report-and-live-verify-seams` | other sessions' work — not ours | #179 |

Worktrees: `friendly-sammet-32dab4` (docs branch; git-ignored `output/live-visible-content/alt-*` = ALL research harnesses
+ evidence; fixture copy) · `freeze-3to4` (implementation; private fixture copy under `output/`) · `gate-runner` (detached
`8521bdc5`, code == #158 merge; re-pin to the freeze branch tip for the gate round; own fixture bank) ·
`decklink-field-test-2ad808` · two worktrees owned by other sessions. Do NOT delete `friendly-sammet-32dab4`,
`gate-runner` or `freeze-3to4` (un-versioned fixture data / evidence). `agent-consolidated` and `skills-vendor` were retired.
Main checkout: on `main`, venv synced — ALWAYS `uv sync --frozen --all-extras --all-groups` (a plain sync strips pytest +
keynote-parser). An untracked `.agents/research/keynote_alpha_p2_owner_review_2026-09-16.md` lives there (owner's).

## 1. Freeze control at 3→4 — OPEN, not green
Plan `.agents/plans/p2_freeze_control_3to4.plan.md` (owner decisions recorded: 8a report-only, 8b `skipped` under
bridge-off, 8c hash-only trigger = inconclusive). Commits on the branch: A `24b1f579` (measured-footprint ROI + scorer null
control), B `2e5b15dd` (capture), C `40ad2392` (scorer), r1 fixes `794d124b`, reviews `96f3b275`.
Codex r1 FAIL → fixed → **Codex r2 FAIL** (`.agents/reviews/freeze-3to4/codex-r{1,2}.md`): arm() resolves the owner
before `armedRect` is set (cannot arm); trigger has no advance causality and mixes Python/browser clocks, 0.375 s window
indefensible (linear motion ⇒ >1 px in ~5 ms); `flipWindowDecodable` ignores `index is None` and the scorer trusts it;
release off by one; A1/A2 not on B's split schedule; `coverTracksFootprint` cannot see a one-frame lag at 60 Hz (≈1.4
px/frame < 2 px tol); capture helpers untested; main-run Transition-C lost its bound owner.
LESSON: both rounds wrote the injected JS without ever executing it. Round-3 brief makes the fixer DEVELOP AGAINST A REAL
HEADLESS RUN and return measured evidence (arm ok, trigger delay in rAFs, cover residuals, flip sample table), every new
constant traceable to a measurement. Biggest unknown, still unanswered: does the counter decode MID-MOVE through the
measured ROI at all? If not, the honest verdict is INCONCLUSIVE.
STATE AT CLOSE: see "Close-out" at the bottom.
NEXT: verify the round-3 diff yourself (blast radius, no constant changed, `_freeze_control_blocks_success` and finding
13's pass untouched, tests) → Codex r3 → on PASS re-pin `gate-runner` to the tip and run `run_gates.sh` (≈13 min; expect
fast 14/14, slow 14/14, bridge-off 13/14 with freeze `skipped`) → open the integration PR. Owner merges.

## 2. Open owner-raised bugs / defects (symptom · expected · evidence)
1. **Go-to freezes movies on air.** After ANY go-to (fwd/skip/back; the host has no `previous`) the destination's movies
   are static posters until the next advance; looks like a normal still. Expected: movies play on arrival as they do
   after an advance. Measured in the product path (runtime v4, continuity on or off): research doc "Follow-up probes
   P1–P4" (P4), evidence `output/live-visible-content/alt-followup/p4-*`. Cause: the digit+Enter go-to calls the player's
   `jumpToSlide(n)` with `automaticPlay` false. Plan (owner said OK to plan the host-side fix):
   `.agents/plans/keynote_live_goto_autoplay.plan.md` — DRAFT, 3 owner decisions inside (player-faithful arrival rule vs
   movie-start only; +0.3–1 s go-to latency; v2 via `jumpToSlide(n,true)`).
2. **Carried movie invisible on a WebGL-settled slide** (baseline refuses the carry ⇒ slide 2's movie is dead by design).
   Expected: live movie with later artwork still in front. Research qualified GL replay with caveats (3 viewports,
   pixel-clean hand-back); rule for when the window exists is known (WebGL-listed transition onto a slide whose first
   pending event is click-driven). Plan `.agents/plans/keynote_live_gl_replay_arming.plan.md` — DRAFT + coordinator review
   §9: the POOLED decoder as texture source and the stand-down hand-off are unmeasured (being measured, see §3); owner
   decisions D1–D5 inside. Owner decided: no opacity patch in v1, plan the general per-draw fix after.
3. **Player paints wrapper-opacity artwork opaque on WebGL-settled slides** (α0.29 green square flat green until the first
   build). Third-party player defect (`main.js` seeds `parentOpacity` from the stage root only). Evidence: research doc
   "Opacity disagreement" + P3. No fix planned for v1 by owner decision.
4. `freezeControlCaughtByCounter` inconclusive ⇒ P2 `success` False on `main` — §1.
5. From the earlier handover, still open: `scripts/p2_alpha_spike.py:260` sends `nativeVirtualKeyCode`; owner HDMI eyeball
   at 2560×1440; native easing parity at 3→4; generalisation plan; HEVC at the receiver.

## 3. Research status (all written up in `.agents/plans/keynote_live_alternatives_research.md`, merged via #177)
Done today: hand-back, outside-player compositing, opacity code-read, per-`clear` qualification at 3 viewports, go-to
jumps, follow-up probes P1–P4, paint-oracle E0 headless (CORRECTION recorded: the gate's real burst profile is sound; the
misread needs unspaced captures over a WebGL-only repaint). Paint-oracle plan `.agents/plans/keynote_live_paint_oracle.plan.md`:
owner answered D-a…D-e (A default, land the in-page oracle now, disagreement = inconclusive-and-fail, attach arm first,
FULL re-qualification in the same PR) — code waits on the OBS attach measurement.
Both late peers REPORTED and are written up in the research doc: **real OBS (CEF 127, Metal GPU)** — GL replay FEASIBLE
(3/3 sessions, controls correct, stand-down 1.4–3.9 ms), paint-oracle attach arm GREEN (D-d satisfied ⇒ paint-oracle code
unblocked), hole-punch pixel-clean, go-to freeze CONFIRMED on the real output path; **pooled decoder** — the runtime's
existing pool (200 ms keep-warm `play()`) is a live texture source headless; hand-off at stand-down CLEAN-WITH-CAVEATS
(the player creates NO `<video>` at build 1 ⇒ hand-off is `tryRemount`; pool is asset-keyed ⇒ sibling must be retired per
instance; remount footprint must be the DESTINATION rect). **ONE open measurement before G3:** the product pool's
keep-warm variant was not tested inside OBS CEF (a bare attach→remove dies there, as it does headless). Arming plan §9–§10.
OBS authorisation was for that session only; the page was returned to `about:blank#program`.

## 4. What the owner does next
- Tomorrow: author the decks listed in the GL-replay plan §6 Q4 (no-build destination · two movies · equal-size posters ·
  masked movie · the baseline's no-overlap positive control), 1920×1080, grating-with-counter movie.
- Decide: go-to plan's 3 questions; GL-replay D1–D5; docs PR for `claude/keynote-live-plans-round2`.
- DeckLink venue test 2026-10-10 (`decklink-field-test-runbook.md`).

## Close-out (filled at stop time)
Stopped 2026-09-20 22:45 on the owner's instruction. **Freeze control is NOT green.**
- Branch `feat/p2-freeze-control-3to4` tip **`32d866e1` = WIP, pushed, NOT reviewed (Codex r3 pending), NOT gated.** The
  coordinator only quick-checked it: two files touched, `py_compile` OK, 263 unit tests pass. Review it properly first.
- Round 3 (Opus, developed against live headless runs; evidence git-ignored in worktree `freeze-3to4`:
  `output/scratch-freeze/*/snapshot.json`, `output/e2e-fast.log`, `output/e2e-bridgeoff.log`, scratch drivers
  `output/scratch_*.py`). Fixer's reported live numbers (NOT independently verified): arm ok at `#7` in every run; trigger
  1 rAF / 57–60 ms after the advance; cover residual 0.000 px after an rAF hand-off (so `COVER_TRACK_TOL_PX` 2.0 → 0.5);
  **the counter DOES decode mid-move** (positive arm 51,54,56,|58|,61,63,65,70,72,74 ⇒ ok; frozen arm constant stale index,
  `freezeRunAtCut` 10–11). End-to-end fast 13/14 (`continueThroughMovingMagicMove3to4` True, freeze inconclusive, `success`
  False); bridge-off: only that finding red, freeze `skipped`.
- **Honest INCONCLUSIVE 5/5 on `noPreAdvanceDeparture` — a PLAN PREMISE ERROR, owner design decision needed:**
  `keepThroughBridge` creates its motion marker and starts the 1.5 s interpolation on ARRIVAL at `#7`, not on the `#7→#8`
  advance; headless produces no frames at rest, so the motion only materialises on the next frame (≈100 ms before the
  advance keydown). Options: re-bracket the hold on the advance INTO `#7`, or gate on the marker's own start. **CHECK
  FIRST, unverified and possibly an on-air defect:** does the carried movie visibly start translating while the deck is
  still settled on slide 3, before the operator advances? If yes that is a runtime bug, not an instrument problem.
- Also unsatisfiable as written: `allInHoldMeasured` / `everyInHoldStale` during the fast part of the move (rect moves
  ≈28 px per 50 ms sample, before/after reads cannot agree within `FOOTPRINT_COUPLE_TOL_PX`); the flip ± 6 window is measured.
- New paid-for facts: the player ignores keys unless `document.hasFocus()` — headless only a `Page.captureScreenshot`
  grants it; the player QUEUES presses it cannot honour and replays them later. Drain is now screenshot-then-one-press,
  deadline 8 s → 20 s (an existing wait value changed — have Codex r3 confirm it is not a gate threshold).
- At 22:41 no headless Chrome with a profile dir was running; nothing was killed by the coordinator. OBS was left running
  by the owner's session; its page is back at `about:blank#program`.
- Open PRs from this session: #182 (docs, owner merges). No integration PR for the freeze control yet.

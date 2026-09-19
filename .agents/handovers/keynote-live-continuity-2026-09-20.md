# Handover — Alpha Keynote live continuity, state at 2026-09-20 ~01:30 (Mac powers off 02:00)

Owner rules (AGENTS.md wins): accuracy and code quality over speed · plan first for anything complex · never
weaken a gate · minimal natspec, no inline comments in src · no merge / auto-merge without an explicit owner
request · hands off Keynote · ask before putting a window on the external monitor · headless Chrome only for
agent runs. Roster this round: Opus plans AND implements (owner, 2026-09-19), Codex `gpt-5.6-sol` reviews.

## Where things are
- **PR [#175](https://github.com/Anyhowclick/obed-edom/pull/175)** = ONE consolidated PR onto #158's branch
  (`feat/keynote-alpha-p2-html-mm`), head `claude/keynote-live-continuity-next`. It contains the presenter branch
  (incl. the other session's real-OBS fixes, DeckLink runbook, generalisation brief), Codex's deferred work and I3.
  Not merged; do not merge without the owner's go.
- Worktree for this branch: `.claude/worktrees/friendly-sammet-32dab4`.
- **Gate worktree** `.claude/worktrees/gate-runner` (detached, own 198 MB copy of the P2 export bank under
  `output/p2-recovery/html-adversarial`). ALL browser gates run from there, pinned to a commit, so implementers
  editing the branch worktree cannot change the bytes under test. Runner:
  `run_gates.sh <gate-worktree> <outdir>` — copy kept at `output/live-continuity-i3/run_gates.sh` in the branch
  worktree. **One browser user at a time**: a concurrent headless Chrome broke an arm's stage fit mid-run
  (the window fell back to the laptop display size) — the `stageFit` check caught it.
- **Kept on purpose (morning DeckLink field test, runbook `.agents/handovers/decklink-field-test-runbook.md`):**
  branch `claude/keynote-live-planning-handover-4e550b` + worktree `pr158-handover-findings-4366b9` (code frozen
  at `62e1ab7`), branch/worktree `claude/decklink-field-test-2ad808`. Also kept: `worktree-agent-a69e…` /
  `agent-consolidated` (uncommitted P2 qualification work, owner said hold & bundle).
- Deleted 2026-09-19 (bundled first → `output/branch-cleanup-2026-09-19/*.bundle` + `tips.txt` in the MAIN
  checkout): 5 stale `claude/*`, 2 `worktree-agent-*`, both `codex/*` (+ remote `codex/live-continuity-deferred`,
  + the `live-continuity-deferred` worktree; its evidence → `output/live-continuity-deferred-evidence/`).
  Main checkout is now on `main` (the venv is an editable install of it ⇒ ALWAYS `PYTHONPATH=<worktree>/src`).

## Commits on top of the presenter tip `e25912e`
`ee97861` I3 scaled-stage mapping (runtime v3) · `dfd1c13` merge of the presenter tip · `3245a17` I5 codec report +
UI codec warnings + README security posture + `ContinuityPlan.slide_instances` · `05cd26a` pure liveness scorers +
plan · `a8bab1d` probe visible-content passes V/Voff · `073546d` `keepAtSlot` re-attach hardening + diagnosis.

## Gates
- `dfd1c13` (runtime `7288246d…ceff`), clean worktree: P2 fast 14/14 · slow 14/14 · bridge-off RED only on
  `continueThroughMovingMagicMove3to4`; host gate PASS @1920×1080, 2560×1440, letterboxed 1600×1000; red controls
  in pattern. New probe vs the v2 runtime @2560×1440 = RED (I3 red-without-the-fix).
- `a8bab1d` (same runtime bytes) with the NEW visible-content passes @1920×1080: arms A/B/C/attach unchanged-green,
  **V slide 2 RED** (`untitled.mov#1` liveFrac 0.484, dead column bands 12–15, dead row bands 6–7), V slides 1/3/4
  green, no strays; Voff slide 1 green, slide 2 fully dead, 3/4 green ⇒ the instrument sees both the defect and the
  raw-export defect and is not always-red. Overall probe status is therefore `fail` — **a true red, by design**.
- `073546d` (hardening, new runtime bytes): see "State at close" below.

## THE open problem — the carried movie is invisible on the fixture's slide 2 (owner decision D3)
Plan + diagnosis: `.agents/plans/keynote_live_visible_content.plan.md` (§5). On a Magic-Move-settled slide the
player paints the whole slide with ONE stage-wide WebGL canvas and leaves the DOM layer tree at opacity 0; the
runtime remounts the continuing `<video>` into that tree, where it decodes but cannot paint. Every older gate was
green because they check geometry / identity / clock, never pixels; the burnt-in counter P2 reads was coming from a
stray 663×186 copy of the second `Untitled.mov` instance (a separate defect: modulo footprint fallback). Hiding the
poster, z-index and translateZ are measured no-ops. Mounting at stage/body level works but paints the movie over the
slide's green square (P2 Finding 2 would go red on slide 2). **Owner decided 2026-09-20: BASELINE first, then the SPIKE** (plan §6).
Baseline = refuse (fail-closed) when later-authored artwork overlaps the carried movie on the destination slide or
the movie is masked, otherwise carry with a visible-target remount / stage-level overlay; retire the same-asset
second instance by plan geometry. The current fixture's 1→2 becomes a refusal fixture; a positive-control deck (no
overlap) and a masked-movie deck must be authored by the owner — how the export encodes a movie mask is unmeasured.
Spike = feed the live decoder into the player's WebGL texture (correct z-order, masks, easing), research only,
first question: does the player redraw at rest on a settled WebGL slide? **Nothing of either is started.**
Then, per the plan: S3 (gate P2 Finding 1 on `footprintFullyLive`), S5 (visible-target remount + retire the
same-asset second instance by plan geometry + key the footprint fallback), full re-qualification, Codex.
Evidence (ignored, branch worktree): `output/live-visible-content/` (screenshots, `diag*.json`, RED artifact).

## Other open items
- `scripts/p2_alpha_spike.py:260` still sends `nativeVirtualKeyCode` (stalls macOS Chrome's UI thread). The P2 gate
  drives keys through it, so change it only together with a P2 gate run; do not mix with a runtime change.
- "Dead advance-rejection branch" is NOT dead (end-of-deck state; proven, left alone) — closed.
- Owner HDMI eyeball at 2560×1440 (ask first) · real-OBS re-run on runtime v3 · DeckLink fill/key + HEVC at the
  receiver (codec report now warns) · native easing parity for the 3→4 move · generalisation
  (`.agents/plans/keynote_live_continuity_generalisation.md`).
- 6 maps Python tests + 6 maps UI tests are red on pristine `main` — not this work.

## Commands
`PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python`, always `PYTHONPATH=<worktree>/src`.
Unit: `$PY -m pytest tests/test_live_api.py tests/test_live_session.py tests/test_live_host.py tests/test_live_runtime.py tests/test_live_continuity.py tests/test_live_continuity_js.py tests/test_live_continuity_probe.py tests/test_live_codec.py tests/test_p2_adversarial.py tests/test_html_alpha_probe.py -q`.
Gates: `git -C .claude/worktrees/gate-runner checkout --detach <sha>` then `run_gates.sh` (≈45 min: host ×3
viewports incl. V/Voff, then P2 fast / bridge-off / slow). After every browser run `pgrep -fl obed-live-chrome`
must be empty; kill only what you started.

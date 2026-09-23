# Handover — Alpha Keynote live continuity, state at 2026-09-20 17:30

> **Where-things-are table SUPERSEDED** by the 2026-09-20 night handover (PR #182, since pruned); current state: `keynote-live-continuity-2026-09-23-g5.md`. Paid-for facts, commands and gotchas below still hold.

Owner rules (AGENTS.md wins): accuracy and code quality over speed · plan first for anything complex · never
weaken a gate · minimal natspec, no inline comments in src · no merge / auto-merge without an explicit owner
request · hands off Keynote · ask before putting a window on the external monitor · headless Chrome only for
agent runs. Roster this round: Opus plans AND implements (owner, 2026-09-19), Codex `gpt-5.6-sol` reviews.

## Where things are (the ONE list — verified with `git worktree list` / `gh pr list`, 2026-09-20 ~17:30)
| Branch | What | PR |
|---|---|---|
| `main` | — | — |
| `feat/keynote-alpha-p2-html-mm` | EVERYTHING Alpha Keynote: P2 probe, presenter, I3, I5 codec, visible-content gate, baseline (runtime v4), plans, handovers. `main` merged in 2026-09-20 (Hall of Witnesses conflict resolved, all entries kept) ⇒ **MERGEABLE / CLEAN** | **#158 (draft) → main** — owner merges |
| `claude/dsk-generator-alignment-options-97c5aa` | unrelated DSK Generator work (another session) | #176 (draft) → main |

#175 is MERGED into #158 (`31b566a`); `claude/keynote-live-continuity-next` and `claude/keynote-live-baseline` are deleted
(local + remote, fully contained). Code on #158 is byte-identical to the gated `3a17401` for `src scripts tests dashboard`
apart from what the merge of `main` brought in (live + preview suites re-run on the merge: 950 passed).
Worktrees: `friendly-sammet-32dab4` (now on the #158 branch; its ignored `output/` holds the gate evidence, a fixture copy
and the research harness) · `gate-runner` (detached on the #158 tip; ALL browser gates run from here; own 198 MB copy of
the git-ignored H.264 fixture bank) · `decklink-field-test-2ad808` (detached) · `pr158-handover-findings-4366b9` (DSK
branch). `agent-consolidated` was RETIRED 2026-09-20 (its diff was byte-identical to `c567fefd`, already on `main`). Do NOT delete `friendly-sammet-32dab4` or `gate-runner` — the fixture copies are not in git.
Safety bundles of every deleted branch: MAIN checkout `output/branch-cleanup-2026-09-19/`.
The main checkout is on `main` and the venv is an editable install of it ⇒ ALWAYS `PYTHONPATH=<worktree>/src`.
Gate runner: `run_gates.sh <gate-worktree> <outdir>` (copy in `output/live-continuity-i3/`); one full round ≈ 13 min;
**one browser user at a time** for gates. Next DeckLink venue test: 2026-10-10 (`decklink-field-test-runbook.md`).
**Queued for the next session (owner, 2026-09-20):** the GL-replay hand-back experiment + Peer 2 — briefs ready in
`.agents/plans/keynote_live_alternatives_research.md`.

## NEW since the overnight close — a possible path past the overlap refusal (research, not product)
Brief + status log: `.agents/plans/keynote_live_alternatives_research.md`. Owner asked two peers to look for
alternatives after the WebGL-texture spike died. **Peer 1 (7 min, time-boxed): GL command-stream REPLAY is ALIVE.**
Measured headless on the fixture's settled slide 2: the player's Magic-Move frames are `clear`-delimited and exactly 88
GL calls each; replaying the LAST frame at rest is pixel-exact (identical screenshot sha, GL error 0, 0.03 ms/frame) —
the player's programs/buffers/uniforms/textures persist; uploading the live `<video>` into the movie's texture
(identified by its upload signature: canvas 960×276, RGBA, flipY + premultiply) and replaying shows the **live movie
across the full rect WITH the green square still in front**, advancing between shots. No minified names; both
structural assumptions are runtime-assertable ⇒ can fail closed to the baseline `retire`. The player's frames are NOT
rAF-driven (so "keep the player drawing" via rAF is dead). **Unmeasured = the real work:** hand-back when the player
draws again (next transition; a BUILD on the settled slide), restoring the poster texture before yielding, what
schedules the player's frames, swapping during the move itself (would give native easing), two movies / equal-sized
posters, scaled stage, OBS CEF. **Peer 2 (compositing outside the player: occluder cut-out, CSS hole-punch) was NOT
started** — brief ready in the same file. **Next experiment:** an rVFC-driven replay loop on settled slide 2 for ~5 s,
then (a) advance to slide 3 and (b) fire a build on slide 2 — detect the player's first own GL call, stand down within
one frame, restore the poster, compare slide 3 byte-for-byte with a control run. Harness (ignored):
`output/live-visible-content/alt-inplayer/replay.py`. Owner: queued for the next session.

## Two lines of work
**A. PR #175 tip `74e0a59`** (runtime v3, sha `fb9e771e…602d`) — I3 scaled stage · I5 codec report + UI warnings ·
visible-content gate (V/Voff, 12-shot burst, DOM instance evidence) · `keepAtSlot` re-attach + per-frame liveness ·
CDP sockets accept large screenshots · README security posture. Gates from the clean worktree: P2 fast 14/14 · slow
14/14 · bridge-off red only on `continueThroughMovingMagicMove3to4` (run at `6bee983`, same runtime + P2 bytes);
host gate @1920×1080 / 2560×1440 / 1600×1000 = every arm in pattern, `stageFit` green, **V slide 2 RED at every
viewport — a TRUE red by design** (the carried movie is invisible there). Codex: I3 r1→r3 PASS; follow-ups r1 FAIL → r2 PASS.

**B. Baseline branch `claude/keynote-live-baseline`** (runtime v4) — owner decision 2026-09-20 "baseline, then spike".
Plan: `.agents/plans/keynote_live_baseline.plan.md`. Implemented I1–I5: `derive_plan` reads the destination slide's
draw slots and refuses PER BOUNDARY when later-authored artwork is drawn above the carried movie (runtime action
`retire`; the fixture's 1→2 is refused — green square, draw slot 6; allowlist signature `bafe26ca…`), refuses the
WHOLE deck on unreadable slot shapes or a possible movie mask (deep closed vocabulary measured from the real export;
the mask encoding itself is still UNMEASURED); runtime retire zone `[atScene−1, next restart/bridge)` with
`preserve-refused` / `retire-boundary` notes; probe expectations derived from the plan (`refusedXtoY` positive verdict,
live/dead rects); host + presenter surface `notCarried`; P2 re-scope (`refusedCarry1to2`, never-pooled evidence with a
real pool census, `footprintFullyLive` at 3→4). NOT done on purpose: I6/S5b (visible-target remount, instance
admission by plan geometry, keyed footprint fallback) — unprovable on pixels until the owner authors a no-overlap deck.
**Gates at the tip `3a17401`** (clean worktree, runtime v4 sha `f3d0c5e4…3f2e`; identical verdicts at `a4f455d`): host gate **PASS** @1920×1080 / 2560×1440 / 1600×1000 —
arms A/C/attach `continue1to2` False + `refused1to2` True, 2→3 restart green, 3→4 carried (C red at 3→4 only), V and
Voff green on every slide (slide 2 "dead, as expected"; slides 1/3/4 live). P2 fast and slow: **13 of 14 True**, the only
not-True is the parked `freezeControlCaughtByCounter` (inconclusive ⇒ `success` False); `--disable-bridge34` additionally
reds ONLY `continueThroughMovingMagicMove3to4`. 914 unit tests. Codex baseline r1 FAIL (1 blocker, 3 majors) → fixed →
r2 FAIL (3 narrower majors: stale movie identity on asset re-assignment, frozen-composite content validity, census
attribution) → fixed → **r3 PASS** (`.agents/reviews/live-baseline/`). Evidence (ignored): `output/live-baseline/`.

## What the owner needs to do / decide
1. Review `.agents/plans/keynote_live_baseline.plan.md` and the baseline branch; say whether to fold it into PR #175.
2. Author (agents never touch Keynote) the decks specified in that plan §5: (i) positive control — a movie continuing
   through a geometry-static Magic Move, a moving/scaling Magic Move and a dissolve with NOTHING drawn above it on the
   destination slides; (ii) a masked movie crossing a Magic Move (to measure the mask encoding); (iii) optional
   overlap-after-build. Use the existing grating-with-counter test movie.
3. `freezeControlCaughtByCounter` must be re-bracketed at the 3→4 boundary (its 1→2 premise died with the refusal). It is
   reported `inconclusive`, which keeps P2 `success` False on the baseline branch — honest, not a regression.
4. Spike verdict: waiting for the PLAYER to redraw is dead (no render at rest, no clean forced redraw) — but replaying
   its last GL frame ourselves works (see "NEW" above). Unexplored alternative noted in `keynote_live_visible_content.plan.md` §7: a static "occluder cut-out"
   canvas over the stage-level overlay, which could turn the overlap refusal into a carry for opaque artwork.

## Paid-for facts (measured on the real player — do not re-derive)
- A Magic-Move-settled slide is painted by ONE stage-wide WebGL canvas (`#0-canvas`); the DOM layer tree is at opacity 0,
  so an in-layer `<video>` decodes but cannot paint. After a dissolve the DOM tree paints normally. The WebGL canvas
  draws only during the move (≈250 `drawElements`/s) and never at rest; it is gone on the next dissolve slide.
- The player NEVER fires `hashchange`. During a transition the hash equals `atScene − 1` for the whole move and the
  slide's videos are detached THERE; the hash reaches `atScene` only ~2 s later.
- `elementsFromPoint` never returns the video (pointer-events none) — useless as a paint oracle. Use
  `checkVisibility({checkOpacity,checkVisibilityCSS})` + the ancestor-opacity product.
- A detached `<video>` reports literal viewport (0,0), not the stage origin. 2560×1440 has stage origin (0,0) and cannot
  reveal offset bugs — always include the letterboxed 1600×1000 arm.
- `websockets` caps a message at 1 MiB: 2560×1440 PNG screenshots crossed it ⇒ "Program browser CDP connection failed"
  ~1 session in 4 (fixed: 64 MiB). The fixture movie flips state every frame ⇒ an n-shot liveness burst reads a healthy
  movie dead with p = 2·0.5ⁿ (5 shots 6 %, measured; now 12).
- The export's draw order is exact: each event's `baseLayer.layers` is back-to-front, one wrapper per object; the movie's
  `objectID` equals its slot child's. A Keynote HTML export stores one copy of each movie per slide folder.
- P2's harness injected a plan naming the slide-3-only clip; that alone made the runtime pool and remount it on slide 4.
  The injected plan must equal `derive_plan(...).to_runtime()` in full.

## Other open items
- `scripts/p2_alpha_spike.py:260` still sends `nativeVirtualKeyCode` (stalls macOS Chrome's UI thread). The P2 gate drives
  keys through it, so change it only together with a P2 gate run; do not mix with a runtime change.
- The pre-existing `onHash` retry inside `scheduleRemount` is dead code (the player never fires `hashchange`); harmless,
  left alone. `P.poolKeys` is only refreshed inside `note()` and can lag after an eviction (read `snapshot()` instead).
- Owner HDMI eyeball at 2560×1440 (ask first) · real-OBS re-run on runtime v3/v4 · DeckLink fill/key + HEVC at the
  receiver (the codec report now warns) · native easing parity for the 3→4 move · generalisation
  (`.agents/plans/keynote_live_continuity_generalisation.md`; `retire` is its first slice).
- 6 maps Python tests + 6 maps UI tests are red on pristine `main` — not this work.
- The 03:00 power-off on 2026-09-20 did NOT happen (uptime unbroken); both the owner's `pmset` event and this session's
  detached timer are gone. Cause not investigated.

## Commands
`PY=/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python`, always `PYTHONPATH=<worktree>/src`.
Unit: `$PY -m pytest tests/test_live_api.py tests/test_live_session.py tests/test_live_host.py tests/test_live_runtime.py tests/test_live_continuity.py tests/test_live_continuity_js.py tests/test_live_continuity_probe.py tests/test_live_codec.py tests/test_p2_adversarial.py tests/test_html_alpha_probe.py -q`.
Gates: `git -C .claude/worktrees/gate-runner checkout --detach <sha>` then `run_gates.sh` (≈13 min: host ×3
viewports incl. V/Voff ≈ 2 min each, then P2 fast / bridge-off / slow ≈ 2 min each). After every browser run `pgrep -fl obed-live-chrome`
must be empty; kill only what you started.

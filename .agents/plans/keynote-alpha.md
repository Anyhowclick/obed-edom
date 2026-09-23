# Keynote alpha — index (P1 preview · P2 alpha/MM probe · P3 export)

Single index for the Keynote-alpha workstream. Consolidates the former `keynote_alpha.plan.md`,
`step1-ownership-contracts.md`, the `keynote-alpha-html-*` handovers, and the Step-1/Step-2 Codex
review rounds (all deleted 2026-09-19 — recoverable from git history). **Lessons live in
`.agents/HALL_OF_WITNESSES.md`; durable contracts/rule-IDs live in `.agents/skills/obed-edom/SKILL.md`;
the code is the source of truth.** One sub-doc kept: [`../research/kpf_renderer_probe_2026-09-12.md`].

## Scope & delivery order
1. **P1 — on-demand build preview** in the dashboard deck-review flow (Apple's exported-HTML player).
   **Shipped.** (`dashboard` `BuildPreview` component.)
2. **P2 — alpha-capture / Magic-Move feasibility probe.** A gate, not an assumption: an offline
   adversarial probe with real output + an honest RED stop-line. **DONE — all findings green, shipping
   in PR #158** (`feat/keynote-alpha-p2-html-mm`). Details below.
3. **P3 — transparent animation export** in DSK→Exporter. **NOT STARTED / gated** behind P2 + an owner
   asset-timing contract. Do not wire until P2 lands and the contract is settled. (P3 exploration is a
   separate workstream/session — not covered here.)

## P2 status — the probe & its findings
Offline, no Keynote: `scripts/p2_recovery_html_adversarial.py` (`--reuse-export --disposable
--wait-profile fast|slow`), scorers in `src/obed_edom/html_alpha_probe.py`, MM/restart bridge +
preserve in `scripts/p2_recovery_html_dissolve_live.py`.
**Both flags are mandatory, every run.** `--disposable` swaps in the disposable movie assets: the
deck's ORIGINAL HEVC does not decode in headless Chrome, so without it the probe scores black frames
and reds findings for the wrong reason. Omitting `--reuse-export` triggers a full bake, which DELETES
`output/p2-recovery/html-adversarial/` — every previous run's evidence with it. **14 findings GREEN on both wait profiles**
(`success:True`), covered by `tests/test_p2_adversarial.py` and `tests/test_html_alpha_probe.py`.

The findings, grouped:
- **Pre-cut composition** — `emptyCanvasPre`, `blackSentinelOpaquePre`, `greenTranslucentPre`,
  `sourceUnchanged`.
- **Finding 1 — 1→2 continuity** (`continueThroughMagicMove1to2`): the movie plays through the 1→2
  Magic Move on ONE stable footprint decoder (identity + rVFC clock + burnt-in counter), composition
  correct after the cut (`blackSurvivesAfter1to2`, `overlappingArtworkComposedAfter1to2`,
  `emptyCanvasAfter1to2`, `overlayRemovedOnLeave`).
- **Finding 3 — 2→3 restart** (`deliberateRestart2to3`, `preserveDidNotBlockRestart`, `reachedSlide3`):
  the movie restarts on a genuinely fresh decoder across the 2→3 dissolve.
- **3→4 moving Magic Move** (`continueThroughMovingMagicMove3to4`): movie continuity through a
  translate+scale MM — see the corrected model below.
- **Freeze negative control** (`freezeControlCaughtByCounter`): qualifies the counter gate — see below.

## Corrected model (the hard-won truths — do not regress)
- **The 1→2 movie is a live `<video>` at the footprint**, NOT a fed 2D canvas. The player remounts it
  through the MM; the fix is a measure-correct remount + per-rAF footprint pin (`keepAtFootprint`).
  Earlier "poster-write / canvas-feed / deck-texid" models were fictions.
- **Transitions are stored under the OUTGOING slide** (apply a transition on slide N ⇒ it is N→N+1).
  The earlier "incoming slide" claim was wrong and mislabeled the deck texids (which are provenance-only,
  gated by nothing).
- **Deck `Minimal Alpha_DSK` (4 slides), movie1 = Untitled.mov on all.** Transitions: **1→2 =
  motion-path MM** (movie geometry STATIC — that is why Finding 1's static `MOVIE_ROI` pin is correct,
  by luck not robustness); **2→3 = dissolve** (movie RESTARTS — Finding 3); **3→4 = motion-path MM**
  where movie1 **translates + scales ×1.32** (on-screen ≈ (198,795,952,268) → (327,709,1266,356)).
- **3→4 is authored continuity ("Play movie across slides" ON), but the HTML export RESTARTS the movie**
  (fresh decoder from time 0 — authored `automaticPlay`/movie build) whenever a Magic Move changes the
  movie's geometry (it honors play-across only when geometry is unchanged, as at 1→2). **This is an
  Apple Keynote HTML-export bug — filed.** The preserve **3→4 bridge** repairs it (carries the slide-3
  decoder, moving+scaling, past the #6 retire into slide 4, suppressing the export's fresh element); the
  gate proves the repair fired and goes RED without it (`--disable-bridge34`).

## Instrument design (why the green is trustworthy)
- **Fail-closed, counter/clock/identity based.** Gated checks are aliasing-immune: a burnt-in frame
  COUNTER (`score_composited_index_run`), rVFC `presentedMediaTime`, and footprint-owner IDENTITY —
  never a raw pixel-MAE (which aliases on the two-state grating). Ownership binds to ONE decoder resolved
  at the footprint (IoU), no fallbacks; ties/ambiguity fail closed.
- **Honest-gate discipline:** a green you cannot trace to the fix is a red. Every positive control has a
  matching red-without-the-fix demonstration (`--disable-bridge34`).
- **Freeze negative control** (`freezeControlCaughtByCounter`, Arm A): an A-B-A bracket on the MOVING
  3→4 Magic Move (re-bracketed off the static 1→2, whose carry the baseline refuses — there is no
  carried movie to freeze there; see PR #187) injects a partial
  stale cover, re-tracked every rAF through the translate+scale, over the counter while the decoder stays LIVE, so
  `index_run` goes RED ("freeze run at cut") while rVFC stays green — isolating the RED to the counter,
  proving the gate is not vacuous. Two-tier scorer: hold-INTEGRITY failures → `inconclusive`;
  gate/isolation/positives → `pass`/`fail` only once integrity holds. Fresh Chrome per bracket run (the
  player's SPA hash only establishes on a first navigation).

## Accepted residuals (fixture-scoped / deferred — not blocking)
- Footprint ownership is geometric (IoU), not paint-order/opacity-aware — backstopped by the composite
  counter, same-movie instances, and fail-closed ties.
- Strict boundary parsing is bypassed by `_norm_hash` prefix-normalisation — unreachable in production
  (player emits clean `#N`); closing needs raw-hash pipeline re-plumbing.
- ~~Freeze control uses state-based (not per-screenshot) cover attestation~~ — CLOSED by the 3→4
  re-bracket: the MOVING-footprint control attests PER FRAME (a CRC'd badge frame decoded from every
  capture, whose painted rect must agree with the page's own log for that frame, plus a per-rAF cover
  hit-test, cover-tracks-footprint check and a bounded rAF/poll gap). Absence of any of it is
  INCONCLUSIVE, never green.
- Arm B (decoder-pause control) deferred — Arm A is sufficient; B would separately certify `rvfcAdvance`.
- `_decode_index_patch` returns 0 for a flat-black ROI — a false-RED source (fails closed, not a
  false-pass); could return None outside the counter alphabet.

## Pointers & next
- **Code:** `scripts/p2_recovery_html_adversarial.py`, `scripts/p2_recovery_html_dissolve_live.py`,
  `src/obed_edom/html_alpha_probe.py`; tests `tests/test_p2_adversarial.py`,
  `tests/test_html_alpha_probe.py`. **PR #158** (`feat/keynote-alpha-p2-html-mm`).
- **Contracts / rule-IDs:** `.agents/skills/obed-edom/SKILL.md`. **Lessons:** `.agents/HALL_OF_WITNESSES.md`.
- **Renderer probe (kept):** `.agents/research/kpf_renderer_probe_2026-09-12.md` — settled native stage
  PNGs are the working alpha path; there is NO scriptable intermediate animation frame (P3 animated
  transparent movies stay blocked on that renderer).
- **Next:** merge PR #158; then P3 (gated, separate) and the MM z-order-flip validation follow-up
  (scoped to build after P2 lands).

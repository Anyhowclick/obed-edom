# Keynote live — go-to leaves movies frozen: host-side auto-play repair (PLAN)

Status: DRAFT for owner review — no code written. Drafted 2026-09-20 by an Opus planner (read-only). Parent: `keynote_live_alternatives_research.md` §"Go-to jumps", §"Follow-up probes P1–P4" (P4).

## 1. Problem
After any `goTo` (forward / skip / back — the host has no `previous`), the destination slide's movies are frozen posters: 0 `<video>`, movie-rect liveness 0.000 at +1 s and +6 s; one `advance` → 0.99+. Identical with continuity v4 qualified and off. The player's go-to lands at `IdleAtInitialState`, before the slide's auto `apple:movie-start` build, and never fires it. On air this looks like a normal still.

## 2. Measured in the player (`main.js`, code-read this session — new, decides §1 semantics)
- `jumpToSlide(A,B)` @2351987: `null==B && (B=!1); this.jumpToScene(C,B)`.
- Digit/Enter keyboard path @2345044 calls `this.jumpToSlide(this.digitAccumulator)` — **B undefined ⇒ false**. That is the whole defect: the host drives go-to with digits+Enter.
- `advanceToNextSlide` @2350369 **and** the hyperlink go-to @2361168 both compute `e = events[sceneIndexFromSlideIndex(dest)].automaticPlay` and pass it to `jumpToSlide`. ⇒ the player's OWN "arrive at a slide" rule.
- `currentSceneDidComplete` @2357683 then chains: while `events[nextSceneIndex].automaticPlay`, it fires the next build itself.

⇒ **Semantics (answers the brief's Q1, not a judgement call):** arriving at slide N must play the **leading run of `automaticPlay: true` events at N**, whatever their effect name — not `apple:movie-start` specifically, and never the first non-`automaticPlay` event. This is exactly what the same player does when you *advance* onto N, and what Keynote shows when you jump in a live show. Fixture: slides 1/3/4 have a leading auto run (1, 2, 1 events); slide 2 has none (3 click-driven `dissolve-character` builds stay pending).
- Because the player chains, **one `advance` fires the entire leading run**. The run length is needed to decide *whether* to fire and to keep counters honest, not to count keystrokes.

## 3. Design

### 3.1 Runtime (`live_runtime.py`, `RUNTIME_VERSION` 1 → 2; player SHA unchanged)
`snapshot()` gains two read-only fields computed from `controller.script.events` — the player's own data, no export re-parse:
- `autoPlayRunLength`: from the index the player would fire next (`nextSceneIndex`, or the initial-state equivalent), the count of consecutive events with `automaticPlay` truthy; `null` if `script`/`events` is unreadable.
- `autoPlayRunKinds`: their `name`s (evidence for logs/gate; lets the gate assert "no click-driven build in the run").
Still observation-only: no command is issued from the injected bytes.

### 3.2 Host (`live_host.py`)
- `_execute("goTo")` keeps digits+Enter and the qualified-mode `__OBED_P2_PRESERVE__.clear()` exactly as today, then (new, after the existing ack) **settles** via `_wait_settled(expected_slide=…)`, and only then reads `autoPlayRunLength`.
- If `runLength >= 1` and `canAdvance` and not busy → issue **one** `advance` through the existing advance path (key or click per `_advance_mode`, so attach/OBS mode is covered for free), then `_wait_settled` again for the chained run. If `runLength == 0` → do nothing (slide 2 case: its three builds stay pending).
- **Fail-closed:** `autoPlayRunLength is null`, runtime < 2, `canAdvance` false, settle timeout, or `PlayerCommandRejected: busy` on the auto advance ⇒ **fire nothing**, return the settled observation, and surface `autoPlayDeferred: "movies idle until next advance"` (§3.4). Never raise: a go-to that worked must not become an error.
- **Idempotence:** the repair is inside the single `goTo` execution, under `session.adapter_lock`; there is no second entry point and no retry loop. A goTo that lands mid-transition already rejects as busy before any of this.
- **Operator advance during the auto-fire:** `live_session._run_command` already refuses a second command while `session.inflight` is set, so an operator press during the repair is rejected with the existing "A player command is already in progress." — the repair is bounded by `timeout_s` and ends in ≤ ~1 settle + 1 advance.
- `capabilities()["goTo"]["semantics"]` becomes `"restart-at-initial-state+autoplay"` when the repair is armed, stays `"restart-at-initial-state"` when fail-closed. `_log_execute` records `autoPlayRunLength`, `autoPlayRunKinds`, `autoPlayFired`, `autoPlayDeferredReason`.

### 3.3 Continuity runtime v4
Nothing changes in `live_continuity_js.py`. Its zones are hash/scene-index driven and the auto-fired events are **within-slide `buildIn` events** — they cross no `atScene` restart/bridge boundary, so pool, retire zone, `notCarried` and bridge interpolation see the same scene sequence they would after a manual advance. Ordering is preserved: `clear()` still runs before the jump, the auto advance after it, so post-clear decoders remount under the new generation as normal. The gate (§5) proves this rather than asserting it: arm A runs qualified.

### 3.4 Operator-facing state
The auto-fire consumes real scenes, so counters must not skew silently. `PlayerObservation`/`sceneId` already report the player's true index — after the repair the reported scene is the end of the auto run, which is the truth. Added, surfaced through `live_session._apply` → `/api/live` → `LivePresenter`:
- `status` stays `busy` for the whole `goTo` (single in-flight command), so the dashboard never shows an interactive "ready" mid-repair.
- `autoPlayDeferred` (string | null) rendered as a presenter note: "Movies idle until next advance" — the §5 fail-closed path and the only place the operator is asked to act.
- Deck-list / "Go" buttons unchanged.

## 4. Mechanism options considered
| | Option | Verdict |
|---|---|---|
| a | **Host fires one `advance` after settle, gated on `autoPlayRunLength ≥ 1`** | **RECOMMENDED.** Reuses the tested key/click delivery, ack, settle, busy and continuity-clear discipline; works identically in attach mode; cannot consume a click-driven build because the run length is read from the player's own `events`. |
| b | `UC.jumpToSlide(n, true)` (names are unminified and reachable) | Rejected for v1: turns the pinned observation runtime into a command surface, bypasses ack/settle and the `clear()` ordering, and the `true` is a single boolean we would still have to derive. Keep documented as the fallback if (a) is ever shown to consume a visible build. |
| c | Presenter-only warning | Kept, but only as the fail-closed path (§3.2), not the fix. |

## 5. The GATE — new probe pass `G` in `scripts/live_continuity_probe.py`
Its own host session (no rAF sampler; screenshots would perturb it), modelled on the existing `V`/`Voff` visible-content passes.
- **Matrix:** goTo 2, 3, 4 from slide 1 (forward + skip), goTo 1 from slide 3 (back), goTo 3 from slide 4 (back, skip).
- **Liveness:** 8 screenshots ≥ 360 ms apart (never a rapid burst — three independent reproductions of the CDP burst defect), scored with the existing `liveness_mask` at the plan-derived authored movie rects mapped through `stageMap`.
- **Assertions per destination:** every rect the plan expects LIVE reads live; every DEAD-expected rect reads dead (instrument neither blind nor always-red); `document.querySelectorAll('video').length > 0`.
- **No click-driven build consumed:** goTo 2 must land with its three `dissolve-character` builds still pending — **scene-index evidence** (`sceneId` == slide 2's first scene, `autoPlayRunLength == 0`, `autoPlayFired == false`) **and pixel evidence** (the characters' region matches the slide's initial state, and a following `advance` changes it).
- **Null control:** `OBED_LIVE_GOTO_AUTOPLAY=off` (host env, same shape as `CONTINUITY_ENV`) ⇒ every goTo destination reads liveFrac ≈ 0.000, reproducing today's defect. RED is required; a green null control fails the pass.
- **Viewports:** 1920×1080, 2560×1440, 1600×1000 (letterboxed origin ≠ 0), plus one **attach-mode** arm (click advance path).
- Artifact keeps per-destination `autoPlayRunLength/Kinds/Fired`, all 8 shot timestamps, and liveFrac per rect.

## 6. Work split (disjoint files)
- **Stream A — runtime**: `src/obed_edom/live_runtime.py` (+`tests/test_live_runtime.py`). Deliverable: `autoPlayRunLength`/`autoPlayRunKinds`, version 2.
- **Stream B — host**: `src/obed_edom/live_host.py` (+`tests/test_live_host.py`). Depends on A's field name only; can start against a fake snapshot.
- **Stream C — session/API/dashboard**: `src/obed_edom/live_session.py`, `src/obed_edom/web/live.py`, `dashboard/src/live/LivePresenter.tsx`, `dashboard/src/live/api.ts` (+`tests/test_live_session.py`, `tests/test_live_api.py`, dashboard tests). `autoPlayDeferred` passthrough + presenter note.
- **Stream D — gate**: `scripts/live_continuity_probe.py` (+`tests/test_live_continuity_probe.py`); land the null-control RED artifact **before** B merges.
- Unit tests: run-length at initial/final state, run of 0/1/2, unreadable `events` ⇒ null; host fires 0 or 1 advance, fail-closed on busy/timeout/null, attach click path, `goToSemantics` string, log fields; session surfaces `autoPlayDeferred` and stays `busy` for the whole goTo; API/dashboard render the note.
- Commands: `uv run pytest tests/test_live_runtime.py tests/test_live_host.py tests/test_live_session.py tests/test_live_api.py tests/test_live_continuity_probe.py` · `npm --prefix dashboard test` · gate: `uv run python scripts/live_continuity_probe.py --pass G --viewport 1920x1080` (repeat 2560x1440, 1600x1000, `--attach`), and once with `OBED_LIVE_GOTO_AUTOPLAY=off`.
- **Codex review brief outline:** (i) is "leading run of `automaticPlay`" the right arrival semantics given `advanceToNextSlide`/hyperlink-goto @2350369/@2361168 and the chain @2357683? (ii) can the single auto `advance` ever consume a click-driven build (run-length race between settle and fire)? (iii) fail-closed completeness; (iv) continuity v4 coherence argument in §3.3; (v) gate strength — spacing, null control, no-consumption evidence; (vi) counter honesty.

## 7. Risks + owner decisions
- **R1** Run length read at settle, fired a moment later — a self-chaining player could move between them. Mitigation: re-read the snapshot immediately before the advance and abort (fail-closed) if it changed. Cheap; do it.
- **R2** An auto build that is a *visible animation* (not a movie start) now plays on arrival. This is the player's own arrival behaviour and what Keynote shows; the fixture has only movie-starts, so the gate cannot prove the general case. **Owner decision 1:** accept the player-faithful rule, or restrict v1 to `apple:movie-start` (narrower, but diverges from the player and would leave other auto builds frozen).
- **R3** Extra ~0.3–1 s in `goTo` latency. **Owner decision 2:** acceptable?
- **R4** Runtime version bump changes injected bytes ⇒ hash-pinned tests move; off/unsupported HTML must stay byte-identical.
- **Owner decision 3:** ship (a) now and keep (b) `jumpToSlide(n,true)` unbuilt, or plan (b) in parallel as a v2 that removes the visible initial-state flash entirely?

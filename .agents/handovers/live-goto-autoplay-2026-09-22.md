# Handover: live go-to auto-play + on-air digit box, state at 2026-09-22 (night)

Owner rules unchanged: no merge without an explicit request; Opus plans / Sonnet implements / Codex reviews; hands off
Keynote unless the owner says it is free.

## Where things are (verified on `origin/main` `de8cc24c`)
| Item | State |
|---|---|
| #203 go-to auto-play | MERGED (`2286a7c8`). Plan + implementation record: `.agents/plans/keynote_live_goto_autoplay.plan.md` §8. |
| #205 digit box on air | MERGED (`de8cc24c`). `#slideNumberControl` hidden in both output CSS variants. |
| Worktrees / branches | `go-to-autoplay-fix-719a2e` trashed + pruned; both feature branches deleted locally and on origin. |
| Full suites on the #205 tree | pytest 5556 passed / 94 skipped / 1 xfailed (`uv run --all-extras pytest tests/ -n auto --dist loadfile`, ~105–140 s); `test:ui` 222; `test:maps` 542 + perf 2. |

## What shipped
- **Runtime v2** (`live_runtime.py`, still observation-only): `autoPlayRunLength` / `autoPlayRunKinds` (the leading
  `automaticPlay` run from the player's own `events`) and `slideNumberShowing`.
- **Host** (`live_host.py`): after a go-to settles, a run of 1 or more gets one ordinary advance, after an R1 re-read.
  - Failure before dispatch: note "Movies idle until next advance".
  - Failure after dispatch: logged `delivery unknown` / `settle unconfirmed`, with no note.
  - Nothing raises after the go-to ack.
  - `OBED_LIVE_GOTO_AUTOPLAY=off` turns the repair off; this is the null control.
  - Click mode waits (bounded) for the slide-number overlay to close before any click (`_await_click_target`).
- **Session / presenter**:
  - Sticky `autoPlayDeferred`: set by a go-to, cleared by an advance.
  - `go_to_target_reached` completes a go-to whose auto run ends busy on a later slide.
- **Gate G**: `scripts/live_continuity_probe.py --pass G [--viewport WxH | --attach]`. Pass
  `--fixture <main>/output/p2-recovery/html-adversarial/html-player --original-index <main>/output/p2-recovery/html-adversarial/html-unmodified/index.html`
  from a worktree. It fails closed on missing evidence. Last run: all four arms PASS, null control RED.

## Owner-raised bugs from this round
- Go-to froze movies: FIXED (#203).
- Digit box on air ~0.5 s per go-to (10/10 captures): FIXED (#205).
- No open owner-raised bug remains from this round.

## Accepted residuals and open leads
- A physical/out-of-band input between the R1 re-read and the host's advance could race it. The v2 answer is a guarded
  in-page advance, the `jumpToSlide(n,true)` family, which the owner deferred.
- The fixture's auto builds are all `apple:movie-start`. A visible auto animation on arrival follows the rule but is not
  gated. Gate it when a deck with one exists.
- **Unverified lead:** the player's `handleClickEvent` ignores clicks whose target is a `<video>`
  (`"video"!==A.target.nodeName`, main.js ≈2342260). In click/attach mode, `click_stage()` clicks the stage centre, so
  a playing movie covering the centre may swallow operator advances.
  - Not observed on the fixture.
  - Reproduce first: a deck with a centred movie, attach mode, advance while it plays.
- Headless Chrome only. No HDMI receiver or alpha-compositing qualification is claimed for either PR.

## Gotchas
- A fresh worktree needs `--all-extras` (or see `worktree-env-setup`); plain `uv run pytest` lacks `keynote_parser`.
- A probe pass that screenshots must `execute("show")` first. A fresh host sits behind `#obed-output-black`, and gate
  G's first red was all-black frames.
- Host execute logs are at `output/.html-preview/live-logs/*.jsonl`. `goTo` records carry `autoPlayRunLength`, `Kinds`,
  `Fired` and `DeferredReason`.

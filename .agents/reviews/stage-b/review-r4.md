# Stage B review r4 — Opus 5.5 high, commit c047e271

Round 4. Owner folds all severities through r5. Scope: `git diff 51ee3be2 c047e271`. Reviewer confirmed: targeted
suites green (149 probe/contract/host/managed-OBS feed+hold+instrument+pre-navigation tests). I re-ran the rebuilt
Node end-to-end test with every verdict printed, both as committed and with the claims moved to their real time
(before the move's GL context).

## r3 findings
| r3 | Status | Evidence |
|---|---|---|
| Major 1 size overwrite | **closed** | `mm_feed_instrument.py:201-202` keeps the regular `size`, adds `uploadedSize`; e2e asserts `[100,100]` / `[160,90]` |
| Major 2 coverage window | **closed** | `:495-498` selects uploads by `frameN ∈ move frames`; e2e `framesFed == 4`, `feedLive True` |
| Major 3 null-serial departures | **closed** | `wrap()` patches `S.departures` (`:186`); contract `serial: _id_or_null` (`contract:807`); e2e asserts `departures[0].serial == 1` |
| Major 4 capture coordinates | **closed** | `capture()` maps UV/strip to intrinsic size with footprint in leaf texels (`:142-144`); e2e uses a 160×90 decoder and a 960×270 counter (counter reads decode) |
| Med 1 managed OBS install | **closed** | public `LiveOutputHost(pre_navigation_scripts=)` registered right after `transport.start()` (`host:1356-1357`); probe `feed_host_kwargs` and `managed_obs_qualify.py:516-517`; `drive_and_sample` raises if the instrument is absent (`probe:1880-1881`) |
| Med 2 e2e fakes | **partially** | Upload-backed GL fake, source-rect 2D context, real True/False assertions, bootstrap path exercised. Printed verdicts: alpha `feedLive` True, broken False, counter True; rider/labels/artwork as asserted. But the claims run after `getContext`, which hides Major 1, and there is still no hold-path case (Medium 3). |
| Med 3 missing pause → red | **closed** | `:766` red only when `clockStill is False`; `clockStill` is None when unreadable (`:544-545`) |
| Med 4 seam property lookup | **closed** (plan frozen block) |
| Med 5 tamper target | **partially** | Scene 10 is correct for the full plan (fed scenes 10/12/14); Python raises when nothing is patched (`probe:1721-1722`); JS `applied` flag and `verdict_records` return `unavailable` (`:386-395`). The new 600-frame cap breaks after-feed (Medium 1). |
| Lows 1–6 | **closed** | `ordinal → holdFrame False` (`probe:355`); visits now None (`probe:3667-3671`); `rectMatchesFact` (`:337`); variant sha of the JS body with the shipped fallback (`probe:1745-1760`); gap-limit provenance comment (`:13`); public pre-navigation hook. Visit claims are only partially handled: see Major 1. |

## Blocker
None.

## Major
1. **(new; same class as r3 Major 3: attribution evidence stamped too early)** `mm_feed_instrument.py:323` (claim
   wrapper) and `:474-483`. A claim row takes `serial` from `moveFor(decoder)` at claim time. Per §2.1 the module claims at
   idle on the source slide, before departure and before the move's context exists. So the serial is null (first move
   of that decoder) or the previous move's serial (chain @10 → @12). `wrap()` patches media and departures but not claims.
   `claims_complete` then fails, `mode` becomes `"unavailable"`, `feedLive` is None, and `score_under_artwork` returns
   None for every continuously fed carry.
   Reproduced: in the end-to-end test, moving `seam.claim` before `canvas.getContext('webgl')` gives every entry
   `mode unavailable` / `feedLive None`, and the producer contract fails (`mmFeed.claims.entry.serial`). The committed
   test claims after `getContext`, which hides this.
   Fix:
   - In the claim and stand-down wrappers, record `serial: move && move.atScene === entry.atScene ? move.serial : null`.
   - In `wrap()`, patch null serials in `S.claims` and `S.standDowns` with the same `entryId`/`atScene` rule as media
     and departures.
   - Contract: `claims`/`standDowns` `serial: _id_or_null`, with `verdict_records` treating a still-null serial as
     incomplete.
   - Move the e2e test's claims before `getContext`, plus a chain case where the decoder's previous move has another
     `atScene`.

## Medium
1. **(new, silent control expiry)** `:316`. `afterFeedTamper` gives up after 600 rAF ticks (about 10 s at 60 Hz) counted
   from bootstrap at page load. With `FIRST_CLICK_DWELL_S` 3 s plus about 1.8–3.3 s per advance, scene 10 (player 6) is
   reached well after 10 s. `applied` stays false, every record becomes `unavailable`, and the registered `after-feed`
   control can never run.
   Fix: drop the attempt cap. Start polling only once `scene() === tamper.atScene - 1`. Mark the tamper failed when the
   target move's context finishes without a trigger.
2. **(plan deviation: producer contract no longer validated)** `probe:4207-4215`. `score_verdicts` no longer calls
   `contract.mm_feed_report` / `contract.feed_verdict_record`. They now run only in tests, contrary to §5.3
   ("`score_verdicts` validates records before scoring"). The per-entry `complete` flags cover attribution but not field
   shapes; the scorers' own type checks are fail-closed, so this is not a false verdict today.
   Fix: restore validation with per-entry scope:
   - `mm_feed_report` errors → every feed entry None (not the whole arm);
   - `feed_verdict_record` errors for one record → that entry None;
   - P2/restart/retire verdicts unaffected;
   - or amend §5.3 in the plan if the owner prefers the `complete` model.
3. **(fakes still hide a path)** The e2e test has no departure/one-shot case. The exact-hold path (ring captures at
   intrinsic size, `holdMatch`, the move-anchored pause, `departurePauseBeforeMove`) is never exercised end to end, and
   r3 Major 4 lived in that path. `broken` goes red only through coverage, never through a read.
   Fix: add a departure case:
   - the decoder plays ≥ 3 distinct frames on the source slide, the hold pause precedes `getContext`, one video upload
     of the paused decoder in frame 1, poster-only draws after;
   - assert `holdFrame True`, `posterHold True`;
   - assert the kill-switch variant (no video upload) → `holdFrame False`;
   - add a continuous entry whose uploads exist but whose GL shows the poster → `feedLive False` via the reads.

## Low
1. (edge) A pre-departure stand-down (`js:2305`, accepted) followed by the departure one-shot upload scores `standDown`
   with `reuploadAfterStandDown True` → `holdFrame` red for the legitimate `once` path.
   Fix: only count re-uploads after a stand-down whose `t` is ≥ the move's first frame; an earlier stand-down scores as
   a departure hold.
2. `report()` silently drops media rows still `serial: null` (`:352`). A dropped hold-window row then reads as absent,
   not as partial.
   Fix: report the dropped count and set `media_complete` false when it is non-zero for the entry's `atScene`.

## Scorer inventory — how missing/ambiguous input scores (after this fold)
| Scorer | Missing / unreadable | Ambiguous | Partial / unattributed | Problem |
|---|---|---|---|---|
| `score_feed_live` | mode None/unavailable, reads, bound, < 2 presented, gap → None | dSep < floor → None | `complete` false → None | early-stamped claims make every continuous move `unavailable` (Major 1) |
| `score_no_rider_above_canvas` | unreadable → None | — | coverage / `complete` → None | — |
| `score_labels_over_feed` | none/null slope → None unless a readable red | low spread → None | coverage / `complete` → None | — |
| `score_hold_frame` | bound, target, reads, re-upload census, overflow → None | margin < constant → None | `complete` → None | pre-departure stand-down + once → red (L1); no e2e coverage (M3) |
| `score_poster_hold` | fields, overflow, dropped callback, unreadable clock → None | — | `complete` → None | missing pause → None unless the clock moved (fixed) |
| `score_artwork_above` | `v` absent / no rows → None | — | `complete` → None | — |
| `verdict_records` | tamper not applied → all `unavailable` | — | visits → None | after-feed cap expires (M1); contract not run (M2) |

Evidence-as-verdict sweep: no scorer turns missing or partial evidence into green or red any more. The remaining
defects are fail-closed None paths that stop positive arms (Major 1) or a registered control (Medium 1) from scoring.

Verdict: not ready — one major (claim attribution makes every continuous carry None). Counts: blocker 0, major 1,
medium 3, low 2.

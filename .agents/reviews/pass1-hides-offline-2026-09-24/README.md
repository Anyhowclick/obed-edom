# Pass-1 hides offline — live gate record (2026-09-24)

Plan: `.agents/plans/pass1_hides_offline.plan.md` (§Oracles, §Gate, todo `f-live-gate`).

- **A:** `origin/main` b3127ed5. Its remap code is identical to the branch's merge base; main's newer commits touch only GL-replay and live-probe code.
- **B:** branch `claude/pass1-hides-offline` at ebd5c01b (the code at e218607f plus a docstring change).
- **Setup:** both run from detached, pinned worktrees that share one `.cache`.
- **Benchmark:** `obed-edom remap Full_Report_Card_Wall.key --template Base_CG_Assets.key --slides 1-129,135-143,145-155 --no-export`, every run writing to the same `--out`, with `OBED_DEBUG_PASS1_SNAPSHOT` set.
- **Machine:** Keynote was used only by this session. The load average was 5–7 throughout.

## Pre-step (Opus O10 #6): B subset in verify mode, on a Keynote-saved post-pass-1 deck

`--slides 1-60,118-125`. Three runs:

| Run | Commit | Result |
|---|---|---|
| 1 | c37d924a | Read a stale cache (no `needsKeynote`): 44 slides deferred, 485 hides, 0 refused. Fixed in 7ceaa47b (stale-cache check). |
| 2 | 7ceaa47b | 60 deferred. The post-save writer refused the 16 image-twin slides: source-space geometry never matches the resized deck (x/4, y/4+405). The run aborted as designed, with no wrong deletion and the source unchanged. |
| 3 | e218607f (decision 7, id identity) | 61 deferred (only 122 excluded, builds). **679 hides, 0 refused**, verify passed, 22.6 s. Pass 1 took 70 s (JS hides stage 1.0 s) vs run 1's 94 s (16.9 s). |

Measured on run 2's saved deck: 68/68 slide ids and 2,105/2,105 surviving drawable ids and UUIDs were unchanged across Keynote's save, and per-kind order was identical. That measurement led to decision 7.

## O4 — interleaved A/B pairs (full benchmark)

| Run | Mode | Whole run | Pass 1 (runJxa) | JS hides stage | Offline stage |
|---|---|---|---|---|---|
| p1-A | main | 505 s | 159.0 s | 82.1 s | — |
| p1-B | verify | **442 s** | **74.7 s** | 1.2 s | 130 slides, 941 hides, 0 refused, 46 orphan data, 26.3 s |
| p2-B | on | **435 s** | **74.7 s** | 1.1 s | 130 slides, 941 hides, 0 refused, 46 orphan data, 23.0 s |
| p2-A | main | 523 s | 177.4 s | 99.0 s | — |

- **Savings:** the whole run saved 63 s (pair 1) and 88 s (pair 2); the gate is ≥ 45 s. `runJxa` saved 84 s and 103 s; the gate is ≥ 60 s. The offline stage took ≤ 30 s. **PASS.**
- **Excluded before deferral:** slide 122 only (6 hides with builds).

## O1 — null-control lines (identical in all four runs)

- `Applied 3822, missed 0`
- The census line (2875 specs, 947 hides)
- The fallback reasons (text-grow-height-width 88, group-residual 83, masked-media 57, group-child-scale 6)
- `Card-border stroke: 18316959 0.25 → 3.0 (83 refs)`
- The stat z-order detail (83 slides, 173/325 raised, 0 refused)
- `Builds follow source: 0 kept …`
- The warning that slide 122 lost 6 builds. This appears on main as well: its hides are deleted in both A and B.

**PASS.**

## O2/O3 — ID-insensitive deck comparison (`scripts/deck_decode_diff.py` at 2f2eea88)

The first pass showed the checker was blind to three kinds of per-run Keynote churn:
- template slides were labelled by member name;
- the order of the `builds` list varies between runs;
- `st-`/`mt-` thumbnails get UUID names.

The A-vs-A null gave 152 differing slides. The checker was fixed in 2f2eea88, and positive controls confirm it still reports real changes.

| Comparison | Differing slides |
|---|---|
| Null, snapshots: p1-A vs p2-A | 0 |
| Null, final decks: p1-A vs p2-A | 0 |
| **O3, snapshots: p1-A vs p1-B (after the offline delete)** | **0** |
| **O3, final decks: p1-A vs p1-B** | **0** |

- **Non-slide differences:** only the null's classes (renamed template members, thumbnails, Document/ShowArchive/ViewState/Properties timestamps, instructionalTextMap).
- **In the B snapshot only:** 5 `ParagraphStyleArchive`s that Keynote's delete would have garbage-collected. This is the style-GC class the plan expected, and they are gone in B's final deck.

**PASS.**

## Forced per-slide fallback (live AppleScript session)

`--slides 15-17`, verify mode, `OBED_DEBUG_HIDES_REFUSE=16`.
- Slide 16 was refused (order proven), and its **21 hides were deleted by the AppleScript fallback session**.
- The exact-path document bind and the confirmed close worked in real Keynote.
- 13 hides were deleted offline on slides 15 and 17.
- The run completed: `Applied 73, missed 0`.

**PASS.**

## Owner checks (pending)

- Magic Move playback of 2–3 transitions, `p2-B-final.key` vs `p2-A-final.key`. Slides 16→17 lose their MM partners in both, from the pre-existing planner rule (todo `followup-mm-leftovers`).
- Keynote opens the B final deck with no repair prompt.

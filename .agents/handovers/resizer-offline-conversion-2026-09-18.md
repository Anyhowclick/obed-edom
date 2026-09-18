# Resizer handover — offline text + offset-crop conversion (2026-09-18)

This round turned the offline-write path from "converts ~0 text, origin crops only" into "all text +
origin & offset crops offline," each live-validated. Two Fable peers (analysis + adversary) drove the
diagnosis. Plans of record: `.agents/plans/offline_text_middle_anchor.plan.md` (merged #165),
`.agents/plans/offline_maskcrop_offset.plan.md` (PR #166). Verify PR/branch/merge state on GitHub.

## What shipped / is up for review

1. **Middle-anchor text reposition — MERGED (#164), promoted to default.**
   The prior "middle text BLOCKED on Δh" was a **mis-diagnosis** (two-peer finding): the 174px that
   scared the team off middle boxes was the deck's one **right-aligned** box under the shipped absolute
   `pos_x` — not Δh. Fix: `_text_fields` position-only path writes BOTH axes as anchor-cancelling deltas
   off the live seed; dropped the `top_anchored` refusal; then (after a live gate) dropped the `laid_out`
   gate entirely (pass 1 zeroes naturalSize on 136/136 autosize boxes, and admitting them is safe). Sole
   remaining gate = a trustworthy live seed. Live-validated: 137 boxes, text max Δ0.98px, PASS.

2. **Masked axis-aligned OFFSET crops — PR #166, live-validated, default-off.**
   `_masked_media_fields` was already exact for any axis-aligned mask; new `_is_axis_aligned_crop` admits
   any within-frame crop at any offset behind opt-in `OBED_OFFLINE_MASKCROP_OFFSET` (requires
   `OBED_OFFLINE_MASKCROP`). The unproven bit was Keynote's offset-crop **redistribution across a reopen**,
   so the gate was a PIXEL check (frame-match ≠ correct region). Live run (subset 4,57,70,123): masked
   fallback 6→1 (5 offset crops converted; 1 rotated/cross-member), frame verify image Δ0.48px, and the
   per-region pixel-diff vs the AppleScript oracle = best-fit shift ≤1px (sub-pixel resampling, not a wrong
   region). Redistribution SOUND. **Promote-to-default is the owner's next call** (fold `_is_axis_aligned_crop`
   into `OBED_OFFLINE_MASKCROP`, leaving only rotated/cross-member refused).

## Full-deck benchmark (2026-09-18, increments ON, no --validate)

`obed-edom remap Full_Report_Card_Wall.key --slides 1-129,135-143,145-155` with
`OBED_OFFLINE_TEXT=on OBED_OFFLINE_MASKCROP=on OBED_OFFLINE_MASKCROP_OFFSET=on OBED_OFFLINE_WRITE=on`,
from a detached worktree at the offset-crop branch tip. **~15 min** (deck finalized ~9.5 min in; ~22 min
was the pre-increment benchmark → ~1/3 faster from the lighter fallback pass). 3822 objects applied, 0
missed. **Fallback 704 → 146:** `text-autosize` 427→0, `masked-media` 188→57, `group-residual` 83 +
`group-child-scale` 6 unchanged. Z-order clean (`Refused/Unresolved/Lost/Gui = 0`). Output kept for owner
inspection: `~/Desktop/Full_Report_Card_offline_CG.key` (6.3GB). Inspect notes: slide 122 lost 6
apple:twist-and-scale builds (object no longer on that slide); 5 card captions stepped 10→9pt to fit.
Ran without `--validate`, so no object-by-object live verify — a verified full pass is available on request.

## Open follow-ups

- **Promote offset crops to default** (owner call) — mirrors the text promote; then masked misses = only
  rotated + cross-member.
- **Groups (89 = group-residual 83 + group-child-scale 6)** — the remaining fallback family and the real
  **wall-time lever**: the AppleScript fallback pass stays alive for groups (they need live layout).
  Text + all crops are done; deleting the pass now hinges on groups. Harder (live layout).
- **PR #166 merge** — owner call (not merged).
- **`-1712` transient** — the first offset-crop run died on a pass-1 AppleEvent timeout (deck loaded,
  not the dialog hang); a plain retry cleared it, and the full-deck pass-1 ran fine. If it recurs, the
  knob is the pass-1 AppleEvent timeout in `_run_jxa` / `osascript_runner`.

## Method note

Two Fable peers in series (analysis then adversarial review) caught what one round of Codex + 415 tests
had missed: the 174px mis-attribution and the phantom `laid_out`/`nw>0` gate. The adversary's independent
per-label FFT matcher (with positive/null controls) is the reusable oracle for text placement; the
per-region pixel-diff vs the AppleScript baseline is the oracle for crop correctness. Scratchpad evidence:
`dh_middle_analysis.md`, `dh_middle_review.md`, the runbooks, and `run_*.log` in `~/Desktop/textrepos-run/`.

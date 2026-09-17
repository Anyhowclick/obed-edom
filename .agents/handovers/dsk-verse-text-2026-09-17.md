# DSK verse/text handover — 2026-09-17

Resume point for the verse/text resizing work, un-benched 2026-09-17 after the image/video path
shipped + live-verified (clip timing, PR #151 merged). Plan of record: `.agents/plans/dsk.plan.md`
(§2 rules, §3 facts, §4 open items, §5 live recipe). Roster: Opus plans, Sonnet implements,
GPT-5.6 Sol (Codex) reviews; main session coordinates + runs live Keynote.

## State of the engine
The verse/text engine (layouts L1–L4, split engine, refit, two-column D1/D1b, style, pill) is
code-complete + deeply offline-tested + fully wired end-to-end (`plan_assembly → refit → style →
pill`), reachable via `content_only=False`. The shipped call passes `content_only=True`, so text
slides are pre-filtered. First live exercise happened this session (text-r1, below).

## In review — PR #155 (`claude/dsk-split-cap-12`, OPEN)
§4 item 12 (multi-box split correctness): `_slot_one_part_fit` builds the 50pt-capped runs ONCE
for both wrap-height and emission, gated by `_pack_split_lines`' ≤3-line/`_SPLIT_TOL` budget;
refuse-not-shrink when capped 45pt overflows; `SplitPart.scale`/`slot_capped` keep the cap through
the `--text-fit shrink` refit. Claude planned, Sonnet impl, Codex r1/r2 folded
(`.agents/reviews/dsk-split-cap/`). Full suite green apart from the 3 pre-existing maps failures.
Not merged.

## Owner-raised / discovered open bugs (symptom → expected → evidence)
1. **item 8 — pill z-order refuses on group-verse slides (LIVE-CONFIRMED text-r1).**
   Symptom: `pill write refused: slide 1: badge 17548232 has no z-order anchor` generating GW5.
   Root cause: GW5's badge (`TSWP.ShapeInfoArchive`) is a group child but its `super.parent` is
   None, so `_z_order_anchor` (`dsk_pill.py:390`) can't walk badge → owning group (`17548203`,
   which IS the sole `ownedDrawables` entry) → returns None → refuse (`dsk_pill.py:567`).
   Expected: the pill inserts directly below the group anchor in `drawablesZOrder` (§1.4 z-order).
   Fix (two options): (a) the assembly sets the group-child badge's `super.parent` to its group,
   or (b) `_z_order_anchor` resolves group membership via the group's own child list when the
   parent pointer is absent. THIS BLOCKS the live text pass — slide 1 aborts the whole pill pass
   before the other 8 slides. Evidence: `~/Desktop/dsk-d4-work/evidence-text-r1/DIAGNOSIS.md`,
   the refused deck `~/Desktop/dsk-d4-work/wt-text/output/Sermon_PK_GW/dsk/Sermon_PK_GW_DSK.refused.key`.
2. **item 27 — joint slot fit shrinks a too-long verse instead of splitting (owner-banked).**
   Symptom: natural GW17 (no `--split`) → `stack_t 0.39`, 27.3pt lead / 33.1pt emphasis, no split
   (verified in-session via `plan_assembly`). Expected: §2:67 — a verse needing >3 lines SPLITS
   to slot-authoritative 45pt parts. The item-12 cap fix only bites forced (`--split`) splits.
   Fix: cap the JOINT-fit measurement (`~dsk_assemble.py:1838/1877`) and route a failed joint slot
   candidate to per-box splitting instead of `fit_text_stack` (`~:1924`). Moves the acceptance
   decks; needs a live run. Evidence: plan §4 item 27.

## Live text acceptance — text-r1 (first ever; PARTIAL)
Ran the dashboard generate with `content_only=false` on a fresh GW copy, subset slides
`5,13,44,46,50-53,57`. The text GUI path RAN LIVE through assembly + refit + style (all 9 slides
anchored; D1b point-layout verified for 44/46/50 per item 11; style applied 5; Keynote peak 2.5GB,
quit clean), then REFUSED at the pill pass (item 8 above). Fail-safe worked: refused, kept
`.refused.key`, source GW deck byte-untouched. So the live text path is largely working — item 8
is the one blocker found so far; the other 8 slides' pills are unverified (never reached).

## Next steps, in order
1. Fix item 8 (pill z-order anchor for group-child badges); re-run text-r1 to clear the pill pass
   and see the remaining 8 slides. Small, well-characterized.
2. item 27 (joint-fit split-vs-shrink) — its own slice, moves acceptance, needs a live run.
3. Full live text acceptance (all GW text slides), accept generated geometry/sizes vs the gold
   `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key`.

## Live-run notes (this session)
- Dashboard UNSANDBOXED: `PYTHONPATH=<detached-worktree>/src <main>/.venv/bin/python -m obed_edom
  dashboard --no-browser`. Text generate = `POST /api/dsk` with `content_only=false` +
  `slides=<spec>` → `/api/dsk/<id>/apply`. Layout slots import automatically (default
  `layout_policy="import"` + `DEFAULT_LAYOUT_TEMPLATE` = `~/Desktop/Default Templates/2026_Lower-Thirds (ENG).key`, present).
- The "Keynote Creator Studio" new-presentation dialog gotcha still applies — the owner's theme
  preference kept it from popping this session (no hang).
- The propose "slide N: skipped (text slide; content-only)" log is PREVIEW-only and its string is
  stale; decisions are `include=True` when `content_only=false`.
- Artifacts kept: detached worktree `~/Desktop/dsk-d4-work/wt-text` (@0195df4, PR #155 tip),
  round copy `~/Desktop/dsk-d4-work/text-r1/`, `~/Desktop/dsk-d4-work/evidence-text-r1/`. Prune the
  worktree + round after item 8 is fixed and text-r1 re-run.

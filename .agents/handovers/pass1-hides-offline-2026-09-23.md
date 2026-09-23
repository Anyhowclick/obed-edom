# Handover — pass-1 hides → offline delete (2026-09-23)

Plan: `.agents/plans/pass1_profile.plan.md`, todo **`h-hides-offline`** (pending, next). Measurements:
`.agents/reviews/pass1-profile-2026-09-23/README.md` (runs 1–8). Owner focus: `obed-edom remap` wall time.

## Where things stand

- **Merged or in review:**
  - #213: the stage timer, and the z-order read-back fix that took the run from 785 s to 584 s.
  - PR #216: the attrs round-trip lever. It is up for the owner to merge. It took attrs from about 100 s to about 19 s, and the null control was identical across two interleaved A/B pairs.
- **Current ranking** (FRC, `--slides 1-129,135-143,145-155 --no-export`, about 545–560 s per run):
  1. pass-1 hides, about 82–118 s
  2. the bulk live seed read, about 150 s (todo `h-bulk-seed-read`, pending, separate)
  3. the AppleScript fallback session, 81 s (parked regrow work)
  4. stat-finalize, 44 s
  5. layouts, 39 s (below gate)
- **Keynote-side hide batching is DROPPED (owner decision).**
  - A one-event bulk delete needs either a contiguous index range or a `whose` clause, and Keynote items expose no stable marker to filter on.
  - Wrapping a slide's deletes in one script body still sends one delete event per object.
  - Revisit only if Apple's scripting dictionary improves. Do not re-propose it.

## The lever: delete hide targets offline

- **Today:** `deleteHides` (`remap_keynote.js`) deletes 947 objects, one AppleEvent each (about 122 ms). It runs per slide after attrs, highest index first.
- **Idea:** skip those deletes in pass 1. After the pass-1 save, remove the objects in the IWA writer: take them out of the slide's `drawablesZOrder`/`ownedDrawables` and delete the object archives.

**Questions for the planner, to answer from the code before building:**

1. **Where the offline delete must run.** Every later stage already assumes "source − hides" indexing. `iwa_write.expected_base_counts` (py:226) refuses a slide whose saved counts differ. Several stages open the deck in Keynote after pass 1 and address objects by kind index: the bulk live seed read, the AppleScript fallback session, and stat-finalize. So the offline delete has to land after the pass-1 save and before the first of those stages.
2. **Order against the existing offline geometry write** (`offline_write.run_offline_write`). Decide between one decode and re-encode or two. Remember the per-slide-decode trap: #213's 183 s came from a helper decoding the whole deck once per slide.
3. **What else points at a hidden object**, all of which must be cleaned up consistently:
   - builds and animations on the slide (`builds[]`)
   - group membership: a hide can be a group child
   - masks
   - text-wrap references
   - `dataReferences` (images and movies)

   Keynote does this cleanup for free today.
4. **Hides the offline path cannot address** (unaddressable kinds such as table, chart or audio; the one full-JXA slide). Keep these on the Keynote delete, the way offline slides fall back per slide today.
5. **The opacity-0 fallback** in `deleteHides` (used when a delete throws). Say what the offline equivalent is, or refuse that slide.

## Oracles (all proven usable 2026-09-23)

- **Null control:** identical `Applied 3822 … missed 0`, census, fallback line and `Stat zorder detail`.
- **Deck equality:**
  - Keynote's save is **not byte-deterministic**: main-vs-main matches CRC on 1 of 155 slides.
  - Use the **ID-insensitive** decode instead: per slide, the multiset of objects with `identifier`, `objectReferences`, `dataReferences` and `randomNumberSeed` dropped.
  - Positive control: a pass-1 snapshot vs the final deck gives 148 differing slides.
  - The script is not in the repo. Rebuild it in about 30 lines with `keynote_parser.codec.IWAFile.from_buffer(...).to_dict()`, or promote it to `scripts/` as part of this work.
  - Compare the offline-deleted deck to the Keynote-deleted deck after pass 1, via `OBED_DEBUG_PASS1_SNAPSHOT`, which works because the deck is a zip. Expect IWA member removals and archive changes beyond slides, such as `Index/Document.iwa` and data files, and diff them deliberately.
- **Live A/B:** run interleaved pairs (A,B then B,A). A cold Keynote under load inflated one baseline 5×. Record `uptime` per run.
  - Driver: a detached `origin/main` worktree that symlinks this worktree's `.cache`, so both sides plan from the same cached input.
  - Command: `uv run obed-edom remap "<Desktop>/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key" --template ".../Base_CG_Assets.key" --out <shared>/deck.key --slides 1-129,135-143,145-155 --no-export`.
  - Write every run's deck to one shared path. Snapshots only need to live until they are diffed.

## Working rules the owner has set (see memory and `README.md`)

- **Roster:** planners in series, a Sonnet implementer, Codex GPT-5.6 Sol review (`codex exec -m gpt-5.6-sol -s read-only -o out.md "$(cat prompt.md)" < /dev/null`). Ask Codex to classify its findings, and refute a finding with a measurement rather than skipping it.
- **Keynote is shared with the AK / GL-replay sessions.** Get the owner's go, or a peer's all-clear message, before any live run. Tell the peers when you are done.
- **No CI:** run the full suites locally for any code PR (pytest `-n auto --dist loadfile`, `node tests/*.test.js`, dashboard `test:ui` and `test:maps`). First run `uv sync --all-extras --all-groups` and `npm ci`.
- **Never merge.** Send old decks to the Trash once they are recorded.

## Other open resizer items (unchanged, for completeness; source `cg_resizer.plan.md` / `offline_groups.plan.md`)

- `h-bulk-seed-read` (150 s) is pending.
- `design-offline-attrs` is now likely below gate: attrs is 19 s.
- Masked-media increments 2 and 3 are open.
- Grow-height regrow is parked.
- A text item that gets no transform is left at 0.25× with a full-size font.
- The Myanmar 25 pt labels overflow their pills. Pill sizing is the operator's job.
- The "73 skipped slides" are unexplained.
- `constellation-cluster-affine` is blocked on the owner.

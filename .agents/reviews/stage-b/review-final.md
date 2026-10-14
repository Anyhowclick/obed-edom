# Stage B docs + harness review — Opus 5.5 high, commit b02192ab

Scope: `git diff fcb00330 b02192ab` (73efd4aa docs, b02192ab full-suite fixes). I checked the docs against the code at
b02192ab: host env and constants, core/module versions and pins, the probe CLI, instrument constants, and
`run_gates.sh` order.

## Hold the PR for
Medium 1 (posterHold wording) and Medium 2 (staging after the load/settle gate). Both are small. The other items can
follow, but Medium 3 is needed before any Q3 qualification run.

## Blocker
None.

## Major
None.

## Medium
1. **(docs vs host vs plan: the `posterHold` mode is the planned path, not the outcome)**
   README "Movie continuity" (`OBED_LIVE_MM_FEED` paragraph and `B-res-1`), SKILL "Feed eligibility and reporting".

   What the host emits: `output.continuity.posterHold[].mode` is `exact` whenever an entry has a bound `feed` and the
   one-shot is eligible, and `baked` otherwise (`live_host.py`, `_poster_hold_lines`). It is computed once, before
   navigation, and never updated.

   Runtime outcomes therefore never reach host output or the badge:
   - first-draw binding mismatch;
   - `once` refused or killed;
   - stand-down;
   - context loss, i.e. `unavailable`.

   Those live only in the page's `__OBED_MM_FEED__.entries[src.objectId].hold` (`exact|baked|unavailable|null`), as the
   implementer noted. The owner can see "exact" under the badge while the screen shows the baked poster.

   Where the wording is wrong:
   - README `B-res-1` says the baked path "reports why" and a mid-move stand-down "reports an unavailable path". Neither
     is reported in host output.
   - Plan §2.1 Host promises per-entry lines with "exact hold vs baked fallback vs unavailable rendering path".

   The SKILL's `mode: exact|baked` is literally right but doesn't say it is the planned path.

   Fix (wording, now): in the README and SKILL, say `posterHold.mode` is the planned path (`exact` = a qualified
   one-shot will be requested, `baked` = no unique binding or no qualified upload path, with the planned reason), and
   that the runtime outcome per entry, including `unavailable`, is in the page's `__OBED_MM_FEED__.entries[].hold` and
   the probe evidence. Rephrase `B-res-1`'s "reports" accordingly, and amend plan §2.1 Host to match.

   Follow-up (owner's choice): have `observe()` read `__OBED_MM_FEED__.entries` and update `posterHold[].mode`/`reason`
   from the runtime `hold`, so the badge shows `baked` or `unavailable` when it happens.

   Related, in the README "Poster hold fallback" bullet: "carries the exact frame on screen when the move starts"
   overstates Phase 0. The upload was the last presented frame 38/40 and one frame newer 2/40; the SKILL already says
   the zero-tolerance gate is owner-gated. Say "the frame on screen at move start (one frame newer in rare cases)".
2. **(gate discipline: heavy staging after the load gate)** `scripts/run_gates.sh:338-367`. The D7/D7s `copytree`
   from `QUAL_B_SOURCE` and the Alpha `preview_textures.repair_textures` now run after the load-average settle loop
   (`:330-337`) and immediately before the first timed arms are queued.

   `repair_textures` detects, renders/verifies the textures and rewrites JSON/PDF. That is CPU and IO the settle gate no
   longer covers, so the first host arms (timing-sensitive paint, cadence and gap verdicts) can start on a loaded
   machine. That is what the gate exists to prevent.

   Fix: run the Stage B staging after the prewarm and **before** the load/settle loop. Or, if it must stay where it is,
   re-run the settle loop after staging. Either keeps the refusal ordering the new test asserts (prewarm events, then
   refusal).
3. **(gate input integrity)** `run_gates.sh:341-350`. The D7/D7s qualification exports are now staged from an unpinned
   folder (`QUAL_B_SOURCE`, default `~/Desktop/Convert wall to 16x9 CGs/Continuity`) and only checked for existence.
   The owner-V4-confirmed D7/D7s are pinned only in the test fixtures (12fe972b, "plan pins"), and nothing ties the
   staged exports to them. A re-export or edit there would be qualified silently. `MM_FEED_READ_EXPECTATIONS` are keyed
   by deck name, not plan sha.
   Fix:
   - In the staging step, derive each staged export's runtime plan and compare `plan_signature` with the pinned
     D7/D7s plan shas from the fixture tests (lift them to probe constants like `ALPHA_DSK_PLAN_SHA256`); refuse to
     launch on mismatch.
   - Document `QUAL_B_SOURCE` in the SKILL's gate section.

## Low
1. `run_gates` dev-tier timeout 20 → 40 s (`tests/test_run_gates.py:766-767`): fine as a fix. Note that the 25 feed
   arms add about 3.7 s per stub round, so check the other `timeout=20` cases that run the full arm list for headroom.
2. The `hang` stub in `test_run_gates.py` now installs TERM/INT/HUP handlers and exits 0 with marker cleanup. The
   survivor census and teardown remain the global `pgrep -fl` / `pkill -f tmp_path` (the coordinator's revert holds).
   The stub's clean exit means a teardown that only signals the parent no longer leaves a detectable survivor through
   the child's own handler. The child does still get TERM, so this is acceptable, but a comment saying the census
   deliberately stays global would prevent a repeat.

## Checked accurate
- **SKILL:**
  - `CONTINUITY_VERSION` 7, `__OBED_P2_PRESERVE__.version` 10;
  - schema-2 Stage B keys and `feed` shape;
  - seam v1 fields and continuous-only `claim`;
  - module API: `MM_FEED_VERSION`, builder signature, pinned sha `f1fe0dd6…` (matches the code), writable page API,
    `entries` keyed by `src.objectId` and fields;
  - page script order and `pre_navigation_scripts`;
  - renderer predicate (OBS/CEF first, `QUALIFIED_SNAP_MAJORS` = 154), `MM_FEED_MANAGED_OBS = False`, `mm_feed="on"` /
    `mm_feed_qualify_once`, attach rules;
  - `OBED_LIVE_MM_FEED=off|auto`;
  - probe CLI (`--mm-feed`, `--feed-tamper`, `--feed-tamper-scene`, `--feed-variant`, `--hold-upload-kill-switch` with
    `--mm-feed off`);
  - verdict list;
  - provisional constants 2.5 / 50 / 6 / 1;
  - F5 note kinds `poster-hold`/`poster-resume`.
- **README:**
  - the env var: blank → `auto`, case/space-insensitive, other values refuse (`live_host.py:1301-1304`);
  - `mmFeed {mode, reason?, version, sha256}`;
  - the overlap lift condition;
  - "more than one ordinary overlay movie" as the deck-wide refusal;
  - the tone-curve residual;
  - one ordinary overlay bridge per boundary.
- **`test_preview_textures` round trip:** comparing with sizes normalised, plus pinned draw / drawCount / ordinals, plus
  a size check against the repaired JSON's asset dimensions, is the right relaxation. It is not tautological: the
  sizes are read from `payload.assets`, independent of `_feed_binding`.
- **Stage B lookups after the gates:** the refusal test confirms that a missing `QUAL_B_SOURCE` fails before any timed
  run and only when feed arms are requested (the dev tier is unaffected).

Counts: blocker 0, major 0, medium 3 (hold for 1 and 2), low 2.

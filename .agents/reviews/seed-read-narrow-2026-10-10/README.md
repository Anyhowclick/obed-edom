# Text-only seed read — gate record (2026-10-10)

Plan: `.agents/plans/pass1_profile.plan.md`, todo `h-bulk-seed-read`, § "h-bulk-seed-read — design".
Branch: `claude/resizer-optimizations-7cae67`, based on main `f4a44ca0`.
Change: the offline writer's live seed read (`offline_write._patch_offline_slides` → `inspect.bulk_geometry` → `bulk_geometry.js`)
reads only `_OFFLINE_SOFT_SEED_KINDS` (text) through a keyword-only, opt-in `kinds` argument. Python validates it and raises
`ValueError` before osascript runs; the JS only filters. Every other caller sends no `kinds` key, so its plan JSON is byte-identical.

## Reviews
- **Design advisor** (one Opus, extra-high effort; the owner asked for a second opinion on the API shape): ENDORSE-WITH-CHANGES.
  Adopted: validation moved from JS into Python, and four test cases tightened.
- **Codex r1** (GPT-6 Astra, high effort, while the owner's banked resets last): APPROVE-WITH-NITS. No production defect.
  - EDGE CASE: `kinds=["text", None]` raised `TypeError` while the error message was built. Folded: the message now sorts with `key=str`, and a `non_string_member` case was added.
  - NEW CLASS ×2 (plan script): `set -- $p` does not split words in zsh; `tee`/`mv`/`S()` did not enforce a successful run or the early stop. Both are fixed in the plan, and the timing helpers were smoke-tested on synthetic logs (complete, incomplete, 60 s boundary, below gate).
  - CLOSED CLASS ×4: the masked-media seed is dead (`as_dict` x/y); no unintended narrowing elsewhere; the error-cap exception is tracked as `seed-error-cap-guard`; the tests guard the change.

## Keynote-free proof
- **P1 (tests).**
  - Targeted files: `test_bulk_read.py` + `test_offline_write.py` + `test_iwa_write.py` → 468 passed, 1 skipped (local write-gate bank only).
  - `node tests/bulk_geometry.test.js` → 23 passing. A copy of the JS without the filter line fails the first new test.
  - Full suite, Python 3.12.12: `pytest tests/ -n auto --dist worksteal` → **8992 passed, 28 skipped, 1 xfailed, 0 failed** (293.7 s, under shared load).
  - Full suite, 3.10.10 floor: **8992 passed, 28 skipped, 1 xfailed, 0 failed** (239.9 s). The skip list matches 3.12 exactly.
  - Dashboard: `npm ci`, then `test:ui` → 44 files and 320 tests passed; `test:maps` (including `test:perf`) → exit 0.
  - The fresh worktree's cache skips the 11 two-tier tests in `test_offline_inspect.py` ("no exact-bytes JXA payload cached"), and those tests exercise `bulk_geometry_fn` doubles. They were re-run against a COPY of the main `.cache` (`inspect`, `deck_digest`, `template_stat`): `test_offline_inspect.py` + `test_propose_two_tier.py` → 78 passed, 1 skipped (no Base_CG_Assets payload banked), 1 xfailed (the same xfail as the full suite).
- **P2 (consumer equivalence on the real deck).**
  - Inputs: the source deck `Full_Report_Card_Wall.key`, decoded in 3.9 s; specs from the banked plan `output/bank/2026-09-21/text-mask-default-flip/B_flagged.run.json`; a four-kind seed built from the cached Keynote 15.4 JXA wall payload.
  - Shape: offline 148 slides, soft 104. With the full seed: 0 refused, 3231 edited objects, 190 missed, 0 soft fallbacks.
  - **Full seed vs text-only seed: differing slides `[]`.**
  - Positive controls: dropping the text rows changes 104 slides (= every soft slide); a media spec with `x=None` makes 103 slides differ.
  - P2 tests the consumer on production-shaped specs and records. It does not cover post-pass-1 deck state; O1/O2 in the live gate cover that.

## Live gate
PENDING owner go. Protocol: see the plan's "### Live gate" (P0 primes a dedicated cache; interleaved A1, B1, then B2, A2; early stop after pair 1).

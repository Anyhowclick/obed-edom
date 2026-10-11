# Text-only seed read — gate record (2026-10-10)

Plan: `.agents/plans/pass1_profile.plan.md`, todo `h-bulk-seed-read` (Done table); design, protocol and review log: `git show 245fe021:.agents/plans/pass1_profile.plan.md` § "h-bulk-seed-read — design".
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

The owner gave the go on 2026-10-10 and then moved the run to the next day. The protocol is the design's "### Live gate" (`git show 245fe021:.agents/plans/pass1_profile.plan.md`), implemented by `driver.sh` in this folder.

**Setup (done 2026-10-10, no Keynote used).**
- Pinned, detached worktrees, each with its own venv synced (`uv sync --frozen --all-extras --all-groups`):
  - `.claude/worktrees/seed-ab-A` at `f4a44ca0` (the PR base; `bulk_geometry` has no `kinds`);
  - `.claude/worktrees/seed-ab-B` at `10aedaa2` (the PR code; has `kinds`).
- `driver.sh` writes decks and logs to the main checkout's `output/seed-read-ab/`, a visible path, and keeps a dedicated `OBED_EDOM_CACHE_DIR` there.
  - P0 copies `deck_digest`, `pairings`, `template_stat` and `settings.json` from the main `.cache`, then primes the Keynote 15.4 two-tier wall read and template stat.
  - The banked JXA payloads in the main `.cache` are never written.
- Preflight refuses to start if:
  - A or B is not at its pinned SHA, or a worktree venv is missing;
  - results already exist, or a stale `out.key` is present;
  - less than 80 GB is free;
  - Keynote is running and the owner has not confirmed 0 documents (`KEYNOTE_OK=1`). It never probes Keynote with osascript.
- A load guard runs before P0 and before each run. It waits up to 10 min for the 1-minute load to drop below 4. At the deadline it aborts if load is ≥ 8 and logs `LOAD WARN` if load is between 4 and 8.
- **FAKE dry run** (`FAKE=1`, synthetic logs, scratch `OUT`): every path behaved as specified.
  - Pass: both pairs ran and O1 lines were identical.
  - Pair-1 saving 50 s: early stop, no pair 2.
  - B1 failure: stopped, with `out.key` left for inspection.
  - Existing results: refused.
  - Bad argument: usage message.
- Machine state at setup: no `OBED_*`, `PYTHONPATH` or `UV_*` overrides in the environment; 455 GB free; Keynote not running.

**Live session (2026-10-11, 14:15–15:01).**
- The owner said Keynote was free; the active Alpha Keynote session granted a quiet window from 14:16 until "free now".
- Keynote was not running at start. The run was `driver.sh live`, unsandboxed.
- Every run used the same `--out`, `--slides 1-129,135-143,145-155` and `--no-export`, with `OBED_DEBUG_PASS1_SNAPSHOT` set.
- **P0 (14:16–14:22):** a fresh two-tier wall read under Keynote 15.4 (`reader offline`, 155 slides) and the template stat (`975689e1….v1.k15.4.json`), both into the dedicated cache.
- Pass-1 census, the same in all four runs: 2894 specs, 928 hides. This drifted from the 2026-09 figure of 947 because of the fresh 15.4 read; the gate compares runs within this session only.

| run | code | 1-min load at start | S, seed read (s) | Whole (s) |
|---|---|---:|---:|---:|
| A1 | f4a44ca0 (all four kinds) | 3.94 | 160.3 | 490.5 |
| B1 | 10aedaa2 (text only) | 3.71 | **41.1** | **344.0** |
| B2 | 10aedaa2 (text only) | 3.98 | **41.5** | **367.5** |
| A2 | f4a44ca0 (all four kinds) | 3.77 | 160.2 | 479.6 |

- **S gate (≥ 60 s in both pairs):** pair 1 saved 119.2 s and pair 2 saved 118.7 s. The stage re-check passes too: S(A) = 160.3 and 160.2 s, both ≥ 60. **PASS.** The read is 74% shorter.
- **Whole-run gate (≥ 30 s in both pairs):** pair 1 saved 146.5 s and pair 2 saved 112.1 s. **PASS.** The cost did not move into the fallback session; the fallback line is identical across runs.
- **O1 null control: B1, B2 and A2 are each identical to A1** (163 normalised lines). The matching lines include:
  - `Applied 3822, missed 0`;
  - the census line;
  - the offline-hides summary;
  - all 148 `Offline-write slide N` lines;
  - `Offline-write fallback: 95 slide(s) (236 spec(s))`, with reasons text-grow-height-width 90, group-needs-keynote:group-residual 83, masked-media 57, group-child-scale 6;
  - `Stat zorder detail` (83 slides, 173/325 raised);
  - `Card-border stroke … (83 refs)`;
  - `Builds follow source`.
- No `Bulk geometry:` error or note line and no "needs the `iwa` extra" line appeared in any run, so the allowed-difference clause was never needed.
- Pass-1 unattributed time: JS 0.1 s (≤ 2 s) and osascript/launch 0.7–0.8 s (≤ 15 s) in every run.
- **Sources unchanged:** the SHA-256 of `Full_Report_Card_Wall.key` and `Base_CG_Assets.key` matches before and after.
- Afterwards Keynote was left running with 0 documents (remap never quits it).
- **O2, ID-insensitive deck diff** (`scripts/deck_decode_diff.py` on the final decks, 15:02, inside the Alpha Keynote session's window):

  | pair | differences | differing slides |
  |---|---:|---|
  | A1 vs A2 (null) | 70 | none |
  | A1 vs B1 | 56 | none |
  | A2 vs B2 | 67 | none |

  - After normalising ids, the A-vs-B non-slide key classes are **within the A1-vs-A2 null**: `Index/Document`, `TemplateSlide*` members, `ViewState`, `DocumentMetadata`, `CalculationEngine`, `Metadata/Properties` and `DocumentIdentifier`, the `st-<uuid>` thumbnail, and the Document `dataReferences`/`externalReferences`/`objectUuidMapEntries`.
  - These are the same per-run Keynote churn classes the hides-offline gate recorded. **PASS.**
- **GATE: GREEN.** S, Whole, O1, O2 and sources all pass in both interleaved pairs. The text-only seed read cuts the seed-read stage from ≈160 s to ≈41 s, and the whole Full-wall remap by ≈112–147 s, with byte-equivalent slide output.
- Clean-up: the run decks (12 × ~6.7 GB; finals and pass-1 snapshots) were trashed after O2 was recorded. Logs, `progress.log` and the O2 JSONs stay in the main checkout's `output/seed-read-ab/`, which is git-ignored.

**Runbook.**
1. Ask the active Alpha Keynote session for a ~50 min quiet window (it has compute priority).
2. Check `pgrep -x Keynote`. If it is running, ask the owner to confirm 0 documents.
3. Run `zsh .agents/reviews/seed-read-narrow-2026-10-10/driver.sh live`, UNSANDBOXED, as one background call. Watch `output/seed-read-ab/progress.log` with a Monitor (`tail -f`, filtered to stage, ABORT, FAILED, STOP and WARN lines).
4. Run `driver.sh o1`, which is light.
5. Run `driver.sh o2`, which is CPU-heavy, so only inside a CPU window.
6. Record S, Whole and load for each run in this file. Trash the decks with `/usr/bin/trash` once the diffs are recorded.

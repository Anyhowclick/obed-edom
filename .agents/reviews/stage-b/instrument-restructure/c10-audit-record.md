# C10 audit: pins and movie provenance (offline, 2026-10-17)

Plan §8. The work was read-only and offline: no browser, Keynote or pin edit, run at `nice 19` while the MM-FEED session held the run window.
- Code: `claude/stage-b-mmfeed-fix` @ `5664e960`, which is `claude/stage-b-arch` plus the fix, with its `derive_plan`, `plan_signature`, `_referenced_movies` and `codec_report`.
- Sources: `~/Desktop/Convert wall to 16x9 CGs/Continuity/`.
- Method: for each export, same as `run_gates.sh` D7/D7s staging:
  - check `preview_textures.json_hits`;
  - derive the runtime plan sha and compare it against the probe pins;
  - list every movie a non-skipped slide references;
  - record file sha256, bytes, codec and fps.
- Media identity: the mdat payload sha256, plus the moov sha256 with the mvhd/tkhd/mdhd creation and modification times zeroed.

## D7 / D7s (done)

| Export | Plan sha | Pin | `json_hits` | counter-a media (mdat) | counter-b media (mdat) | copies → identities |
|---|---|---|---|---|---|---|
| `D7-html` (single strip) | `0e2570925a56…` | `D7_PLAN_SHA256` | 0 | `65da5343ce…` | `f9a6201a6d…` | 4+4 → 1+1 |
| `D7s-html` (single strip) | `3d1a0bd159e0…` | `D7S_PLAN_SHA256` | 0 | `65da5343ce…` | `f9a6201a6d…` | 3+3 → 1+1 |
| `strip2/D7-html` | `0e2570925a56…` | `D7_PLAN_SHA256` | 0 | `71659a979a…` | `b37ffd9302…` | 4+4 → 1+1 |
| `strip2/D7s-html` | `3d1a0bd159e0…` | `D7S_PLAN_SHA256` | 0 | `71659a979a…` | `b37ffd9302…` | 3+3 → 1+1 |
| `q7-fixtures/D7-unrepaired/html-player` | `0e2570925a56…` | `D7_PLAN_SHA256` | **1** (refusal control holds) | `65da5343ce…` | `f9a6201a6d…` | 4+4 → 1+1 |

All movies are `avc1` at 30.0 fps. `strip2/q7-fixtures` is a symlink to `../q7-fixtures`, so staging with `QUAL_B_SOURCE=strip2` finds the refusal control.

**Findings**
1. **The pins are unchanged.** Every repaired export derives its pinned plan sha, and the unrepaired control is still refused by `json_hits`. No pin edit is needed.
2. **A movie-only change leaves the plan sha equal.** The single-strip and strip2 exports derive the same D7 and D7s plan shas, but their counter movies differ (different mdat). This is the case plan §8 describes. Today nothing in staging tells them apart.
   - `run_gates.sh` still defaults `QUAL_B_SOURCE` to the top-level (single-strip) folder.
   - A round without `QUAL_B_SOURCE=strip2` reads the shifted `counterLayout` (x=704) on movies that have no strip there.
   - Per the MM-FEED diagnosis null, the scorer then falls back to Alpha reads, and the feed verdict comes out a spurious False instead of a refusal.
   - Sent to the MM-FEED session (2026-10-17) as a staging guard for the fix branch: refuse unless the counter-movie media identity matches strip2.
3. **File sha256 is not a usable movie identity across copies.** Within one export, the copies of a movie differ only in 6 bytes: the mvhd/tkhd/mdhd timestamps, which Keynote stamps per copy. Their mdat and normalized moov are identical.
   - Within each export, every copy of each movie collapses to one media identity.
   - C10's "hash served movie bytes once per unique file" still holds as a record of exact served bytes. But a *comparison* across exports (old vs derived pin, or "changed movie bytes" reds) must use media identity, or every re-export looks changed.

## Alpha (done)
Same steps as `run_gates.sh` Alpha staging, on a scratch copy:
- source `output/fixtures/alpha-dsk-textures`, donor `q7-fixtures/Alpha/html-unmodified`;
- restore the referenced movies;
- `repair_textures`, then `_detect` and `json_hits`;
- plan sha against `ALPHA_DSK_PLAN_SHA256`;
- `codec_report` and media identity.

| Step | Result |
|---|---|
| Unrepaired export | plan sha `3baebab35009…` (≠ pin), `json_hits` 6 |
| Movies restored from the donor | 5: `Full_Report_Card_Wall_DSK.001.01/.02.h264.mov`, `Untitled-H264.mov`, `VID-20250608-WA0121.mp4`, `VID-20250608-WA0125.mp4` |
| Repair | repaired; detector hits 0; `json_hits` 0 |
| Repaired plan sha | `c9e546551300…` = **`ALPHA_DSK_PLAN_SHA256`** |
| Codecs | all `avc1`; fps 29.855 / 29.892 / 29.958 / 29.937 / 29.978 |
| Media identity | each asset's copies (1, 1, 3, 2, 4) collapse to one mdat identity; wa0121 and wa0125 have 2 and 3 distinct file shas (timestamps only) |

**Findings**
4. **The Alpha pin holds**, and the Stage T repair is required: the unrepaired export derives a different plan.
5. **Alpha's staged movies are not identity-pinned.** They are restored by file name from the donor. Swapping the donor would change test content while the plan sha stays equal, the same gap D7 had before the strip2 guard (`adfeb552`, `D7_COUNTER_MDAT_SHA256`).
   - Recommendation for the C10 code step (P identity, G pins after C5): record the per-asset mdat identity in `feed_fixture_identity` for every feed fixture.
   - Pin the 5 Alpha donor mdat identities next to `ALPHA_DSK_PLAN_SHA256`, and refuse staging on a mismatch.
   - The Alpha movies are the real deck's, so the pin records them; it doesn't change them.

## Status
The audit is complete, and no pin edit is needed. What's left of C10 is code, after C5: per-asset media identity in `feed_fixture_identity`, the Alpha mdat pins, and missing or unreadable referenced media refusing qualification.

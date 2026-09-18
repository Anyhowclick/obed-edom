Verdict: not all fail-open paths are closed. I found five substantive gaps and one defensive contract mismatch.

1. **[P1] Footprint ownership does not prove the decoder is painted.**  
   [p2_recovery_html_dissolve_live.py:490](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:490) checks readiness, key, bounding box, and IoU, but not element/ancestor opacity, visibility, clipping, or paint order. An advancing D1 hidden behind an oversized D2 can still be selected as owner; D1 satisfies identity/rVFC while visible motion and the index patch come from D2. The top-level gate does not link those pixels back to D1. This preserves a same-key handoff false pass.

2. **[P1] Strict boundary parsing is bypassed before the gate.**  
   `_norm_hash` prefix-normalizes `#1junk` to `#1` at [p2_recovery_html_dissolve_live.py:1758](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:1758). Both boundary hashes and sample hashes are normalized before `liveContinuity1to2`, including [p2_recovery_html_adversarial.py:1438](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1438) and [p2_recovery_html_adversarial.py:1302](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:1302). Therefore `_strict_hash_num` never sees the junk in production. Its regex at [p2_recovery_html_adversarial.py:713](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:713) also accepts bare `"1"` despite documenting `#<digits>`. The new unit test only exercises the gate directly, not this real normalization path.

3. **[P1] IoU ≥ 0.6 still admits meaningful partial and oversized owners.**  
   At [p2_recovery_html_dissolve_live.py:500](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:500):

   - A 60%-width, full-height partial video has IoU `0.60` and passes.
   - A uniformly 125%-scaled video containing the footprint has IoU `0.64` and passes.
   - A 160%-width, full-height video has IoU `0.625` and passes.

   Candidates are then ranked by raw overlap, not IoU, at [p2_recovery_html_dissolve_live.py:508](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_dissolve_live.py:508). An oversized sibling containing the footprint can beat a slightly offset intended owner and be selected uniquely. The 75%-uniform case is closed, but the broader scale/geometry class is not.

4. **[P2] The restart upper bound still passes by absence.**  
   At [p2_recovery_html_adversarial.py:455](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:455), missing or malformed `restart_min_hash` becomes `None`; [line 462](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:462) then disables the upper bound. I directly confirmed a D1 sample at `#2` plus another at `#99` passes when the bound is omitted or `"bad"`. The production caller currently supplies `SLIDE3_MIN_HASH`, but the supposedly fail-closed function itself is not fail-closed.

5. **[P2] A cumulative rVFC rewind can be split into tolerated steps.**  
   [p2_recovery_html_adversarial.py:747](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:747) checks only adjacent backward deltas. I confirmed `10.00 → 9.96 → 9.92 → 10.10` passes: net `+0.10`, worst adjacent step `-0.04`, despite an accumulated `-0.08` rewind. Compare each value against the running maximum if the intended tolerance is “never regress more than 0.05 from any previously presented time.”

6. **[P3] “Both crossing IDs” is implemented as first and last of any-length list.**  
   [p2_recovery_html_adversarial.py:478](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/scripts/p2_recovery_html_adversarial.py:478) accepts `["D", "OTHER", "D"]`. The current producer emits exactly two IDs at [html_alpha_probe.py:1234](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/src/obed_edom/html_alpha_probe.py:1234), so this is not presently reachable through that producer, but `len == 2 and all(...)` would match the stated contract.

The ordinary D1→D2 crossing handoff is now closed, as are null ownership, missing rVFC, sibling-clock substitution, restart-window samples when the bound is supplied, and a single large `10→1` rewind.

The 2→3 restart path is not regressed by `_presented_time_advances`: a fresh decoder progressing monotonically `0→0.4` passes, while `10→1` fails. All 19 pure `liveContinuity1to2` tests passed when invoked directly. Full pytest could not start because the read-only environment provides no writable temporary directory. No files were changed.
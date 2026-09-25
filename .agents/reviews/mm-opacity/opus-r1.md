# MM opacity: Opus review r1

Scope: `git diff origin/main...HEAD`, code commits `6b9acd21..f6a87ee8`, reviewed against the plan
`keynote_live_mm_opacity.plan.md` rev 4 (including the §9 Q0b results). The review was read-only. I ran no OBS, Keynote or browser.

**What I checked myself.**
- On the real `main.js` (sha `e9b2fad4`), I re-ran the anchor and replacement counts.
- I ran `node --check` on the patched player.
- I did my own Python census of all 26 distinct Magic Move effects under `output/`.
- I ran the 7 touched test files: 780 passed, 0 skipped (the REAL-gated and IWA tests ran too).

## Reviewer brief (plan §11)

| # | Question | Answer |
|---|---|---|
| 1 | Anchors / replacements unique on pinned bytes | **Yes.** Each of R1–R4 has `count(before) == 1` and `count(after) == 0` on the raw bytes, and `count(after) == 1` / `count(before) == 0` after patching. `__obed`/`obedOpacity` occur 0 times in stock. No `after` contains a later `before`. `node --check` passes. `textureInfoFromEffect(` occurs 3× (the definition, `setupTexture`, the recursion). `renderFrameWithContext(` occurs 2×. `new eB(` occurs 2×. |
| 2 | Legacy arithmetic exactly today's | **Yes.** R3 runs after today's `T`/lerp and R4 after today's `w`. Both override only when `null != e.obedOpacity`, so `0` is honoured and `undefined`/`null` fall through. `e` is never reassigned in `renderFrameWithContext`. In R4, `e` is `this.texture`. `parentOpacity` is untouched. |
| 3 | Can a chain get the wrapper's model value instead of its animated value | **Not on any export on disk**, and not on the one-level group shape the player itself reads. **One latent path exists** (F4): an opacity animation nested in a group inside a group is invisible to `__obedNodeOpacity`, so that node's *model* value is used. |
| 4 | `off` serves today's bytes on every path | **Yes** for the host (`patch_player(mm_opacity=False)` gives the hook only, pinned by tests on HDMI, attach and managed). **Yes** for P2: GL-off arms serve stock from disk, and the GL arm serves hook-only, the same as `origin/main`. **Yes** for managed: the `mm-off` / `*-mmoff` sessions pass `mm_opacity="off"`. The freeze-bracket `gl_auto` fix is correct: before, `main_js is not None` would have turned GL on in non-GL arms under `--mm-opacity auto`. |
| 5 | Every threshold traces to a measurement or in-run CvC | **Mostly.** MIN_SLOT_DRAWS 20, SETTLE_TOL 1, erosion 4 + ceil(1.99), CvC ≤ 2, τ/τ_key in-run, `occludedBands` 0/20 and unproven sets all trace to plan §10 or Q0b. **Exceptions:** managed `EXPECTED_STATS["on"]` is headless-only (Q0c has no recorded result, F6), and MO-2's rate-30 take has no in-run CvC (F7). |

## Findings (ranked)

### F1: bug / gate-integrity, HIGH. MO-3 (`--arm mmo-cef`) can never PASS: its driver drops the settle ROI and the movie masks
`scripts/managed_obs_qualify.py:607`. `mo3_script` calls `setLabel(label, cfg)` with the bare `mm_opacity_probe.PLAN` config.
For `mm12` that is only `{settleFromMs, roiOrdinal}`. The headless driver merges
`extra = {"mm12": {"roi": settle_roi(), "masks": movie_masks(...)}}` (`mm_opacity_probe.py:585`), but the managed one does not.

Effects in CEF:
- The logger never reads `B`/`P`, so `run_problems` reports "settle ROI pair missing" and "settle hash has no movie mask" for every arm.
- Every MO-1/MO-4/MO-5 inside MO-3 is therefore INCONCLUSIVE, and the `MO-3` check "== PASS" fails.
- It fails closed, but the only CEF run of the instrument is wasted.
- The driver also reads `hashAfter` with a plain `s.ev(HASH_JS)` (`:621`), not `wait_for_hash`. Commit `dc5e04a1` added that wait precisely because G2 moves the hash after settle, so GL-auto `mm12` can also trip "hash … expected".

No test drives `mo3_script`'s `setLabel` payload: `test_managed_obs_qualify.py:392–460` only feeds hand-made records to the scorer.

**Fix:**
- Factor the per-step loop of `run_arm` into one `mm_opacity_probe.drive(evaluate, execute, settle, live_state, screenshot, extra)` and call it from both drivers.
- In managed, build `extra` from `settle_roi()` plus `movie_masks(runtime)`. Take `runtime` from the host's `_continuity_runtime_plan`, or from `armed["slotRects"][armed["movieSlot"]]` and `armed["instanceRect"]` through `gl_mask`.
- Add a unit test that captures the `setLabel` JSON for `mm12` and asserts that `roi` and `masks` are present.

### F2: test quality, MEDIUM. The real-bytes behavioural test covers only the P2 1→2 tree, so the mirror's fallback branches are never checked against the bytes
`tests/test_live_runtime.py:309`.

The Node run on the extracted real methods uses only `effect_1_to_2.json`. On that tree:
- wrappers are either "model" or "const both";
- the only fallback exercised is a leaf `hidden` animation (slot 1);
- R4 is exercised once (slot 3).

The following branches are cross-checked only in the Python mirror, never in the patched JS:
- wrapper fade (`from ≠ to`);
- non-`both` constant;
- two opacity animations;
- `initialState.hidden`;
- a `null` propagating through two levels;
- a textured root;
- a leaf fade under a translucent constant wrapper (decision 5 residual);
- non-finite / throwing nodes.

Plan §5 claims "the mirror is backed by the Node behavioural test … so it cannot drift from the bytes". That holds only for the branches the fixture visits.

**Fix:** parametrize `_run_extracted` over about 8 small synthetic trees, one per branch above, and assert `patched == [[new …]] from _mirror` and `stock == [[old …]]` for each.

### F3: gate-integrity / coverage, MEDIUM (verify). The P2 non-GL arms may not exercise the patch at all
`scripts/p2_recovery_html_adversarial.py:604–612, 666`.

Under `--mm-opacity auto` the fast, slow and bridge-off arms now serve hook plus MM patch. They still launch `p2_alpha_spike.ChromeCdp`, which passes `--disable-gpu` (`p2_alpha_spike.py:146`). If WebGL is unavailable there, the player takes its CSS Magic Move path and the patch is inert.

Two problems follow:
- Plan §8's expected "slide-2 screenshot score" movement would not appear.
- MO-6 would read "unchanged" for the wrong reason.

Separately, `off` serves stock with no hook while `auto` serves hook plus MM, so an MO-6 delta in those arms cannot be attributed to MM alone.

**Fix:**
- Record `WEBGL_AVAILABLE_JS` (it already exists) per arm in `report.mainJs`.
- State in the gate record whether each arm drew Magic Move through `eB`.
- If attribution matters, compare `auto` against a GL-off run served `patch_player(raw, mm_opacity=False)`, not against stock.

### F4: edge case, LOW–MEDIUM. A nested animation group makes `__obedNodeOpacity` fall back to the model value (the only α² path)
`src/obed_edom/live_runtime.py:11–17`.

The node rule flattens only one level (`Q[e].property ? [Q[e]] : Q[e].animations`). An `opacity` animation in a group inside a group is not seen. `g` stays null, and the node returns `B.opacity` (the model value). For a wrapper shaped like slot 4 (model 0.2947, animated 1 → 1) whose animation is nested one level deeper, the leaf would draw at α².

There are 0 nested groups across the 26 on-disk effects (my census), and the player's own leaf renderer reads only `animations[0].animations`. So this is latent.

**Fix:** treat any `t[i]` that has no `property` but has `animations` as unexpressible, e.g. `…:"hidden"===t[i].property||!t[i].property&&t[i].animations?(C=2):0`. Mirror the change in `_node_opacity` and add one synthetic tree for it to F2's set. This keeps "faithful or unchanged" true by construction, not only by census.

### F5: gate-integrity, LOW–MEDIUM. The plan says the `live_continuity_probe` KB arms get `mm_opacity="off"`; the code leaves them unchanged
Plan §8 table, row 1: "KB arms pass `mm_opacity="off"`". `scripts/live_continuity_probe.py:1697, 1792, 2375, 3267` all build `LiveOutputHost(…, gl_replay=…)` with no `mm_opacity`, so every probe arm, the KB arms included, now runs patch-on. §9 says "W6 not needed", but only because of the `occludedBands` assertion; the §8 KB-arm line was not addressed.

**Fix:** either pass `mm_opacity="off"` in the KB arms whose premise is the opaque square, or amend §8 with the reason no KB arm depends on it. Then confirm this in MO-6.

### F6: gate-integrity, LOW. Managed `EXPECTED_STATS["on"]` (`occludedBands` 0, unproven `[{4, rest-opacity}]`) is traced to headless Q0b only
`scripts/managed_obs_qualify.py:119`. The check label says "headless r2 / Q0b". Q0c (the logger in CEF) has no recorded result in §9.

The patch-off value 20/128 was measured in CEF under OD-2; the patch-on value 0 has not been. It will be checked by M1 on the first g2 take, but a mismatch would read as a product FAIL rather than an unmeasured expectation.

**Fix:** record Q0c, or the first M1 `g2` take with its KB, in §9 before relying on M1's `occludedBands` check.

### F7: gate-integrity, LOW. The MO-2 rate-30 take has no in-run CvC, and a docstring misstates how τ is set
`scripts/managed_obs_qualify.py:1270–1271`. The docstring says the rate-25 CvC "sets tau for both". In fact:
- τ and τ_key are computed per run from that rate's own sessions (`mmo_tau`, `mmo_key`);
- the rate-25 CvC is only a pass/fail precondition;
- the rate-30 τ has no control-vs-control of its own.

Plan §10 ("CvC pair at g2/25") allows this, but the docstring overstates it.

**Fix:** reword it as "the rate-25 CvC gates both takes; τ is per take". Optionally add `g2-on-2` at 30 (one session).

### F8: gate-integrity, LOW. `sequences_match` accepts a fade whose values are wrong but whose direction and end value match
`scripts/mm_opacity_probe.py:269`. For non-constant sequences only the direction and the final value are compared, because of rAF timing. A fade wrongly scaled by a constant (for example 0.5 → 0 instead of 1 → 0) would pass MO-1 "othersMatchTwin".

`ordinal_sequences` (`:249`) also silently drops frames whose draw count differs from the widest frame.

**Fix:**
- Also require `max(ca) == max(cb)` and `min(ca) == min(cb)`. The fade's endpoints are timing-independent once the move has played through.
- Count the dropped narrow frames and report them as a problem when there are any.

### F9: gate-integrity, LOW. The MO-4 forced stand-down and the patch-off `occludedBands` 20 are not in the headless MO-4 scorer
Plan §10 MO-4 lists these facts:
- "a forced stand-down (`debugForceFail` seed) replays at α_eff = α";
- "with patch off every G2 fact equals gates-r2/OD-2 (… 20/128)".

`score_mo4` checks rest and unproven only. `occludedBands` appears in `detail` but is not asserted. No arm seeds a stand-down.

**Fix:** add `occludedBandsOn == 0` and `occludedBandsOff == 20` checks. Either add a `standdown` arm (seed `debugForceFail`, assert that the replayed slot-4 `Opacity` == α), or record in the plan that this item is dropped.

### F10: test quality, LOW. Two P2 tests assert source text, not behaviour
- `tests/test_p2_adversarial_gl_replay.py:853` checks `"_served_main_js(player_dir, gl_auto=gl_auto, mm_opacity=mm_opacity)" in src`.
- `:864` checks `"gl_auto=gl_auto)" in src`.

A formatting change breaks them, and a wrong-but-similar call passes them.

**Fix:** for the freeze bracket, monkeypatch `drv._chrome` to record `gl_auto` and raise, then call `_run_freeze_bracket(..., main_js=b"x", gl_auto=False)` and assert that the recorded value is `False`. For the report test, cover `_served_main_js`'s meta, which is already done, and drop the source assertion.

### F11: M3 / process / docs, LOW
- `managed_obs_qualify.py:1031`: "g2-off-S T alpha (patch on, GL replay off)" is report-only. It is the one direct CEF measurement of the fix with G2 absent (it should read 75 ± 3). Enforce it as an M3 check, since the `mm-off` KB beside it already FAILs by construction.
- Plan §5 line 160 says "0 unexpressible chains". I count **51 of 110 `eB` leaves legacy**, all through a leaf `hidden` animation (every fade carries one). No wrapper is unexpressible. The outcome is unchanged, but the sentence is wrong. Fix it to "0 unexpressible wrappers; 51 leaves legacy through a leaf `hidden` animation".
- The branch is behind `origin/main` by #230 (the managed-OBS false exit), so the two-dot `git diff origin/main..HEAD` shows its files as reverted. Rebase before the PR. The three-dot diff is clean and does not overlap #230.
- The docs pass (README, SKILL, runbook, hall, D2 line) is still to do, per the plan's order.

### Style, no findings
- Natspec is minimal, and there are no inline comments in `src/` or the new scripts: only `# noqa`, plus the test-only comment blocks, which the style rules allow.
- The injected JS is strict-mode clean: every name is `var`-declared, a parameter or a method; there are no implicit globals; `catch(E)` is used.
- **Nit:** R2 re-evaluates `__obedChainOpacity(X,A)` once per child. It is setup-time only and deterministic, so leave it.

## Also verified (no finding)
- **`X` undefined vs null.** `undefined` occurs only at the root, where the root is valued as `1·root`, exactly the value legacy uses. Via R1 a textured root gets `null`, i.e. legacy. `null` propagates through R1 and R2 to every descendant. `0` is a legal faithful value.
- **Hidden and multi-animation fallbacks.** `initialState.hidden` → `null`. A `hidden` animation sets `C=2`, and a later opacity animation keeps `C>1`. Two opacity animations → `C>1` → `null`. A missing `from`/`to` or a non-number throws or fails `typeof` → `null`.
- **`kpfLayer` is `new VB(baseLayer)`**, which shares `initialState`, so the root node value equals the `parentOpacity` legacy passes.
- **Host precedence and refusal.**
  - The constructor wins over the env, and the env is trimmed and case-insensitive.
  - An invalid env raises after the GL-replay check and before the log, the server and CDP.
  - An invalid constructor value raises in `__init__`.
  - A missing anchor surfaces as a `LiveHostError` before any resource is created.
  - `output.mmOpacity` reports the sha of the bytes actually served.
- **Harness verdicts.**
  - `mm_opacity_probe.gate` gives INCONCLUSIVE when the CvC is missing or not PASS, or when any KB is missing or not FAIL. VOID passes through. `score_all` ranks FAIL > INCONCLUSIVE > VOID > PASS, and anything other than PASS exits 1.
  - The KBs really fail. The α² splice gives 0.0868 on slot 4 through the real node rule (Node test). Patch-off gives 1 on slot 4 and a settle residual ≫ 1.
  - MO-2 fails closed on a missing series, τ = None, or a KB that does not fail.
  - The premise check (S_off vs DOM > τ) blocks a self-inflating τ.

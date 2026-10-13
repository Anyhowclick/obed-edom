# Critique r1 — `keynote_live_cef_placement.plan.md` rev 1 (db11b278)

Reviewer: Claude Opus 5.5 (plan critic r1). Read-only. Owner answers relayed 2026-10-13 are applied: **O2 = NO** (Chrome
keeps its knowledge grant, decision 16 stands, r13 #3 stays open), **O3 = YES**, **O1 = include only if bounded and needed**.

Anchor check: every `file:line` in §1.1 and §6 was read at db11b278. All resolve to the cited seam. The exceptions are
imprecise rather than wrong; see #14. The evidence claims in §1.2 match the READMEs and REPORT.md. The rev 16 "144 100 B" and
the rev 17 `:1140` sha prefix are confirmed.

## Findings

### 1. major — scope (O2 = NO): remove every Chrome migration and Chrome product probe
§0, §2.3 ¶1, §2.4 (DPR 1.5 text), §2.5, §3 ¶2, §4 r13 #3 row, §5 `probe-*` / `iso-hdmi`, §6 host bullet, §7 W4, §8 O2.
Evidence: the owner answered O2 = NO. The plan still carries Chrome probe/lease work:
- §2.3 "For host-launched Chrome, use a second target of the same browser".
- §5 `probe-*` "qualified Chrome → snap" and `iso-hdmi`.
- §6 "connected GPU fallback" rows.
- §7 W4 "Isolated Chrome target … Implement O2 policy".
- §3 "migrate launched Chrome … to the shared probe lease".

The channel also needs an explicit split. `live_host.py:56` grants `snap` with no expiry. A probe lease must apply only to
probe-derived values.

**Fix wording:**
- §2.3: replace ¶1 with "Launched Chrome keeps its rev-17 knowledge grant unchanged (decision 16; O2 = NO). This PR adds no
  Chrome probe target, lease or migration. r13 #3 stays open in the handover with its residual."
- §2.5: "The extended updater takes `(token, value, ms)`. A host-knowledge `snap` (launched Chrome) is set without expiry,
  exactly as today. Every probe-derived value (`frac`, or `snap` from a CEF probe) carries a lease of at most 15 s. The Node
  tamper rows cover both modes."
- Delete `iso-hdmi`, the Chrome row of `probe-*`, the §6 "connected GPU fallback" rows, the §3 migration sentence and W4's
  "isolated Chrome target".
- Keep one harness-only Chrome positive control in W6 (`scripts/`), not product code. Wording: "harness Chrome runs the probe
  page via CDP screenshot → classifier must return `snap`." This proves the classifier can emit both rules.
- §2.5 recalibrate: "Capability `recalibrate` is supported only on managed-OBS sessions. HDMI/headless and external `obs-cdp`
  report it unsupported, with a reason."

### 2. major — new class: CEF lease renewal has no decided evidence source
§2.5 ¶3. Evidence: the plan says "do not blindly renew a lease from no observations. Qualify an OBS-supported fingerprint
route or expire and re-probe". CEF has no browser-target `SystemInfo` (`live_host.py:1253` uses `browser_call`, which needs
`_browser_ws_url`, and attach mode has none). Rev 16 renewed on UA + DPR (+ SystemInfo "where the browser target answers").

If no route qualifies, the plan leaves two outcomes:
- `frac` dies 15 s after each probe, so the feature is effectively absent.
- The probe repeats every ≤15 s, toggling Studio Mode on air indefinitely. §9 itself forbids this disguised as renewal.

The design outcome is therefore undecided. Note that OBS browser hardware acceleration is global and needs an OBS restart.
The engine launch identity already invalidates on that restart. The only uncovered path is a CEF GPU-process fallback, the
same residual class as r13 #3.

**Fix wording:** add owner question **O4** and pick a default. "CEF lease renewal: renew only on the same CDP
connection/context and the same managed engine launch identity (pid + launch date, `ManagedObs` ready generation), with UA
and `devicePixelRatio` re-read and unchanged. An unchanged-fingerprint CEF GPU fallback is a stated residual, as for Chrome
r13 #3. Recommend accept. The alternative, periodic re-probe, is rejected for on-air cost and contamination exposure."
Remove "or expire and re-probe" as an open fork.

### 3. major — edge case: the "nothing persisted" rule will likely trip on OBS's own saves, and the plan ignores `_seed`
§2.2 last ¶, §9 ¶1. Evidence:
- `managed_obs.py:908-921`: `_seed` rewrites `basic/scenes/AK.json` from `render_tree` before **every** launch. Crash
  leftovers in `AK.json` can therefore never be loaded by a managed launch.
- OBS saves the scene collection on scene/source add/remove. This is expected behavior, not verified here. A mid-transaction
  save of `AK-Calibrate` is then near-certain.
- The plan's own rule ("If temporary objects are saved during a transaction … report a blocking feasibility gap") would then
  block the PR at implementation time.
- `AK.json.bak` is not rewritten by `_seed` (only the files in `render_tree`; `DECKLINK_PROPS` is unlinked when absent).

**Fix wording:**
- Make it step 0 of the implementation order: "measure the persisted `AK.json`/`AK.json.bak` during, after cleanup and after a
  clean quit, in one transaction."
- State: "`_seed` (`managed_obs.py:913`) rewrites `AK.json` before every launch. `_seed` also removes or rewrites
  `AK.json.bak`, so no persisted leftover can reach a later launch."
- Pre-state a conditional owner question **O5**: "If OBS writes the temporary objects to `AK.json` mid-transaction and the
  verified post-cleanup save and post-quit file are clean, does that satisfy 'nothing persisted'?" Do not discover this as a
  blocker after implementation.
- Delete "recover only positively owned leftovers before the next session"; reseed already does this.

### 4. major — new class: on-air Studio Mode toggle can disturb the live Program page, and static-program gates cannot see it
§2.2 Primary, §2.3 ¶3, §5 iso/Program-wire rows. Evidence: entering Studio Mode with OBS's default scene duplication cuts
program to a private duplicate of `AK`; leaving it cuts back. The shared `Program` browser source may get hide/show
callbacks. obs-browser then flips page visibility, which pauses rAF and can stall a playing movie. Feasibility measured the
hidden visibility on a non-showing source (README row "Studio Mode turned off again": hidden).

Recording C was a **static** program (REPORT.md:21, :23). Byte-identical frames there cannot detect a paused rAF or video,
yet §2.3 permits on-air recalibration. The owner would see a stutter or stopped movie during Recalibrate.

**Fix wording:**
- Add to `iso-obs-preview` and `iso-obs-offcanvas`: "During every transaction the host records, through its existing CDP
  connection to the Program page, `visibilitychange` count, max rAF gap and each playing video's `currentTime`
  monotonicity/advance. Requirements: zero visibility events, rAF gap ≤ 2 frame periods, no video stall beyond one frame."
- Null: no transaction. Positive: `SetSceneItemEnabled(Program)` off/on in a scratch run must FAIL.
- Also evaluate seeding `SceneDuplicationMode=false` in the managed `user.ini` (`render_tree`, W3) so Studio Mode never swaps
  program to a duplicate. Read it back before enabling Studio Mode.

### 5. medium — edge case: classifier wording can reject every GPU result
§2.4 Classifier, §5 `probe-*`. Evidence: "reject contradictory maps, disagreeing poses, intermediate shares" reads as global.
On the GPU path, the identity map leaves the correct rule only partly clean. p2like's grey ramp (14 mid-grey steps of 16)
plus two mid-tone patches cover roughly 15–19 % of pixels (`genvid.py` Q4/Q5). That share is intermediate for identity, so
a global rejection makes the GPU path always "unknown".

**Fix wording:** use rev 16's rule. "A map is consistent for a pose iff one rule ≤ 2 % and the other ≥ 20 %. Grant iff
exactly one map is consistent for both poses with the same rule. An intermediate share disqualifies only that map. Any second
map consistent with a different rule → unknown." Add a `probe-*` row: GPU capture scored with identity yields intermediate
shares and the GPU map still grants.

### 6. medium — design: fallback should be a qualification-time choice, not a runtime fall-through on air
§2.2 Fallback ¶2. Evidence: "after verified primary cleanup, create the calibration scene reference in `AK`" means any
runtime preview failure leads to a program-graph mutation on air. A preview failure could be a transient timeout, freshness
miss or load. Feasibility ranks off-canvas as needing "stronger mutation and cleanup guards" (REPORT.md:70).

**Fix wording:** "The placement is selected per pinned OBS version at qualification (preview if `iso-obs-preview` passes,
else off-canvas). At runtime a failed preview transaction → invalid (stock movie), never an automatic off-canvas attempt
in the same or a later run."

### 7. medium — design: where the OBS transaction runs relative to the `ManagedObs` worker is unspecified
§2.1 ¶3, §7 W3. Evidence:
- `ManagedObs._run` (`managed_obs.py:608`) runs liveness only when the queue is empty.
- A 15 + 5 s calibration job on that worker would stall OBS-exit, DeckLink-inactive and page-lost detection for 20 s.
- It would also queue Release/quit behind it.

Running calibration off the worker instead races quit/restart unless a shared engine generation and mutex are defined.

**Fix wording:** "The calibration transaction runs on its own bounded thread with its own `ObsWebsocket`. It holds an
engine-generation token taken from `ManagedObs` under its lock. Quit/restart/setup set a cancel flag, wait at most the
5 s cleanup budget for the transaction's verified cleanup, then proceed. Calibration never runs as a `_submit` job, and
liveness keeps running throughout. A generation change aborts without grant." Add one row to the W3 transaction table.

### 8. medium — owner question O1: recommendation with cost (owner asked for include/exclude)
§3 ¶2, §4 r13 #1, §8 O1. Evidence:
- `patch_rendering` (`live_runtime.py:324`) applies `_MM_OPACITY_REPLACEMENTS`.
- That set includes `_DISSOLVE_METHODS`, i.e. `__obedFreezeTake` (`:200`).
- Build Preview serves it (`html_preview.py:144`).

So the plan's O1-deferred branch ("do not add `frac` to the non-host executable variant") **already requires** splitting the
rendering variant's take from the live variant's. The split is unavoidable either way. The only increment of "include" is
removing the take entirely from `patch_rendering` and adding forged rows to the existing `m-raw-prod`/`m-preview-prod` arms
(`dissolve_probe.py:330-331`).

Files are all already in W1/W6: `live_runtime.py` (split + re-pin `SUPPORTED_PLAYERS[*][2]` for both players),
`tests/test_live_runtime.py:312` (intentional rewrite: rendering = live minus hook **minus take**),
`scripts/dissolve_probe.py`, `tests/test_dissolve_probe.py`. There is no `html_preview.py` change.

**Recommendation: INCLUDE**, in this bounded form. **Fix wording:** "O1 (owner: include if bounded). `patch_rendering`
omits the freeze take (no `__obedFreezeTake`/D3 entry). Cross-fade/cut unchanged. Re-pin both rendering digests. Raw/preview
forgery rows (assignment and non-configurable getter, `snap` and `frac`) → no holder. Deferring would cost the same split
without closing r13 #1."

### 9. medium — scope (O2 = NO): W5 Chrome rows must be harness-only
§2.7 ¶1, §5 W5 row. Evidence: "two fresh launches each of headless GPU/software". The handover W5 names headless
`LiveOutputHost`. With no product Chrome probe target (#1), these rows need an evidence-only path.

**Fix wording:** "W5's Chrome GPU/`--disable-gpu` rows run in a W6 harness script (CDP screenshot of the probe page in a
harness-launched Chrome). No product Chrome probe target or grant is added for W5."

### 10. medium — scope: Chrome 18-cell matrix re-run is not justified by this PR
§5 Geometry/foreground. Evidence: rev 17 DX-1 left the DPR arms INCONCLUSIVE at merge (handover:100-102). If the `frac`
branch is additive, the snap arithmetic is unchanged. Requiring the full Chrome DPR×origin×clip matrix turns those known
INCONCLUSIVEs into new blocking work.

**Fix wording:** "Chrome regression = the DX-1 arms that passed at merge, re-run on the new bytes, plus `wrongrule-chrome`.
W1 proves by byte inspection that the `snap` path's draw/admission bytes are unchanged apart from the shared `pl` admission
test. The 18-cell matrix runs only if they changed. Prior DPR 1.5 INCONCLUSIVEs stay recorded, not waived."

### 11. low — design: the first-probe trigger is not stated
§2.5. Evidence: invalidation triggers and recalibrate are listed. Session start is not, unlike rev 16 §3.3 "host start".
**Fix wording:** "A managed-OBS host probes once the first program context is granted-eligible (before or after Take
output, never blocking it), then on reload/reconnect/engine change and on `recalibrate`."

### 12. low — gate over-claim (theoretical): alpha "during mutation and cleanup"
§5 Alpha integrity. Evidence: screenshots cost ≥ 90 ms (REPORT.md:83). Sampling cannot prove a transient, and the recording
drops alpha. A visible transient changes RGB too and is caught by the recording. An alpha-only flash needs black content.
**Fix wording:** "sampled before/install/each capture/cleanup/restore; the transient alpha-only residual is stated, not gated
(cost: an alpha-preserving recorder)."

### 13. low — gate cost (theoretical): sleep/suspension row in `life-cal-*`
§2.5 ¶4, §5 `life-cal-*`. Evidence: a live sleep/wake run is costly. The safe path is already defined: when revocation cannot
be delivered, wait for a reconnect revoke and never assume expiry.
**Fix wording:** "Expiry is never inferred from host time. The fake-clock unit row covers it. No live sleep/wake gate."

### 14. low — anchor precision
§1.1 F1, F9, F11.
- `pyproject.toml:57` is the `[tool.setuptools.package-data]` header; the list is `:58`.
- `managed_obs.py:132` is `render_tree`; `RecQuality Lossless` is about `:144`.
- F1 "redraws foreground": the take draws foreground canvases into the backing after the alpha scan (`live_runtime.py:148-150`).

**Fix:** correct the line numbers and the verb.

### 15. low — simplification: DPR 1.5 erosion text is moot
§2.4. Evidence: under O2 = NO only CEF is probed, and `frac` requires DPR 1. Fractional erosion handling adds code and test
rows for no reachable case. **Fix wording:** "The probe requires DPR 1; any other DPR → unknown."

### 16. low — edge case: preconditions before entering Studio Mode
§2.2 ¶1. Evidence: `render_tree` seeds `current_transition: "Cut"`. A non-Cut transition or an active DeckLink preview output
would turn the Studio Mode toggle or the preview into visible output.
**Fix wording:** "Before enabling Studio Mode, read back the current transition = Cut and no DeckLink preview output active.
Otherwise → no probe."

## Owner questions
- O1–O3 are answered.
- Add **O4** (CEF renewal evidence/residual, #2).
- Add **O5**, conditional (transient mid-transaction save, #3).
- Both are answerable yes/no with a stated recommendation.

## Counts
blocker 0 · major 4 · medium 6 · low 6

## Verdict
**CHANGES REQUIRED.**

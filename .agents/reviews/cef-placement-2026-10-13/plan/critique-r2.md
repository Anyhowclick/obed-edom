# Critique r2 — `keynote_live_cef_placement.plan.md` rev 2 (d72238ac)

Reviewer: Claude Opus 5.5 (plan critic r2). Read-only. Scope reviewed: `git diff db11b278 d72238ac` plus the full rev 2.
Owner decisions O1–O5 (§8) applied as given.

## r1 closure check

| r1 # | Status | Note |
|---|---|---|
| 1 | closed | No Chrome product probe, lease, migration or `iso-hdmi` remains. Chrome is harness-only (§2.3, §2.7, §5, §7). The knowledge-vs-probe channel is explicit (§2.5). Recalibrate is managed-only. |
| 2 | closed | O4 inputs are fixed; the periodic re-probe fork is removed (§2.5). |
| 3 | closed, with a new defect | Step 0 and the `_seed` fact are in. The `.bak` refutation is correct: `_seed` writes only `render_tree` files (`managed_obs.py:148-165`, `:914-923`). My r1 fix proposed adding that behavior, not claiming it. The new comparison rule is defective: see #1 below. |
| 4 | closed, with an edge case | The moving-program gate, null and positive are present. The duplication-setting readback route is undefined: see #2. |
| 5–8 | closed | Wording is exact. O1 is bounded to W1/W6 files, and `html_preview.py:144` is unchanged. |
| 9–10 | closed | |
| 11–15 | closed | |
| 16 | closed, with an edge case | "unreadable → no probe" conflates an absent DeckLink preview output with an unreadable one: see #2. |

New anchors verified at d72238ac:
- `live_runtime.py:147-149`
- `live_host.py:705`, `:708`, `:1253`. `_browser_ws_url` is set only on the launch path, at `:591`.
- `managed_obs.py:116`, `:146`, `:148`, `:150`, `:157`, `:165`, `:168`, `:607`, `:889`, `:914`, `:920`
- `pyproject.toml:58`
- handover `:34`
- `dissolve_probe.py:330`
- `html_preview.py:144`

All are correct.

## Findings

### 1. medium — edge case (fold regression of r1 #3): "complete parsed state identical" is unattainable and has no defined baseline or save point
§2.2 Persistence, §5 Persistence/worker, §8 O5.

**Evidence:**
- The pre-probe `AK.json` is the file `_seed` wrote (`managed_obs.py:157`, `_scene_collection` `:96-120`) unless OBS has re-saved it since launch. OBS's own save adds and normalizes fields: `prev_ver`, private settings, preview/studio keys and module blocks. A post-cleanup OBS save will therefore differ from the seeded baseline even with zero leftovers.
- The off-canvas fallback adds an item to `AK`. That bumps the scene's `settings.id_counter` (seeded `1`, `:113`), which stays bumped after removal.
- obs-websocket offers no explicit "save collection" request I know of. "After cleanup" therefore depends on whether OBS happens to save on removal. A stale mid-transaction save can still be the latest file.

As written, the gate fails closed on every run, and blocks both placements on a false failure.

**Fix wording:** "Baseline = the parsed `AK.json` as saved by OBS before the transaction (step 0 records whether a pre-transaction save exists; if not, the seeded file normalized by the same parser). Compare a normalized scene graph: the set of sources and scenes with their ids/uuids/names/settings, each scene's items with transforms/visibility/order, `current_scene`, `current_program_scene`, transitions. Ignore an explicit allowlist that step 0 must justify field by field (e.g. `id_counter` monotonic increase, OBS-added keys present in both). The authoritative checkpoint is after clean quit; the after-cleanup read is authoritative only if its mtime postdates the last removal, otherwise diagnostic."

### 2. medium — edge case: precondition readbacks need defined routes and an "absent ≠ unreadable" rule
§2.2 ¶1–2, §6 managed transaction table.

**Evidence:**
- **DeckLink preview output.** "No DeckLink preview output active … otherwise no probe, including when either check is unreadable." When no preview output was ever configured, a status request for it is expected to return not-found. That is plausibly obs-websocket's resource-not-found code, the same class REPORT.md:86 saw for `RemoveInput`, but this is unverified. Under the plan's wording, that normal case reads as unreadable, so the probe never runs.
- **SceneDuplicationMode.** "Read back its effective value before enabling Studio Mode" names no route. I know of no obs-websocket request exposing this UI setting; this is unverified. A required readback with no route also means "no probe".

**Fix wording:**
- "Step 0 records the exact response for an unconfigured DeckLink preview output. That response (and only it) means absent = pass. Any other error or timeout = unreadable = no probe."
- "Seed `SceneDuplicationMode=false` only if step 0 shows the default duplicates and fails the moving-program gate. Its 'readback' is the seeded `user.ini` value verified on disk after launch plus the step-0 behavioral result. Do not require a runtime API readback unless step 0 finds one."

### 3. medium — new class: a runtime moving-program failure can repeat on air through automatic re-probes
§2.3 ¶2 ("A failure revokes and prevents qualification for on-air use"), §2.5 triggers.

**Evidence:**
- "Prevents qualification" is a development-time outcome.
- At runtime, §2.5 re-probes automatically on reload/reconnect/engine change.
- A transaction that observed a visibility event or stall on air has already disturbed the program. The next automatic trigger repeats the Studio toggle, and the owner would see repeated stutters.

**Fix wording:** "A runtime moving-program or isolation failure revokes, records the reason, and disables automatic probes for that engine launch identity; only an operator `recalibrate` may retry. A new engine launch re-enables them."

### 4. low — edge case: renewal thread ownership and CDP lock contention unspecified
§2.5 O4, §7 W4.

**Evidence:** `ChromeCdp.call` holds `_lock` for the whole reply wait, with a default 15 s deadline (`live_host.py:653-662`). A renewal queued behind a slow call can miss the 15 s lease, and the freeze then silently skips. This fails closed but is visible as an occasional jump. Session observation is UI-poll driven (`live_session.py:237-244`), so it cannot be the renewal clock.

**Fix wording:** "W4: renewal runs on a host-owned timer thread, started on the first grant and stopped in `stop()`. It uses `evaluate_in` with a deadline below the remaining lease. A missed renewal lets the lease lapse and is logged (`leaseLapsed`), never extended."

### 5. low — edge case: `wrongrule-chrome` forcing route vs "mode fixed at installation"
§2.5 ¶2, §5 `m-snap-cef` row.

**Evidence:**
- Knowledge mode (Chrome) is defined as "`snap` without expiry". Whether it accepts `frac` at all is unstated.
- "A harness may use probe mode for `wrongrule-chrome`" implies a product parameter that selects probe mode on a Chrome host. That would be a new product surface.

**Fix wording:** pick one.
- (a) "Knowledge mode accepts `snap` indefinitely and any value with a lease ≤ 15 s via the token. `wrongrule-chrome` forces leased `frac` through that path."
- (b) "The mode is a `LiveOutputHost` constructor argument used only by `scripts/`. The product router never passes it."

Add one Node row for the chosen form.

### 6. low — simplification: the `AK.json.bak` residual is unreachable
§2.2 Persistence, §8 O5, §9 ¶1.

**Evidence:** `_seed` writes a fresh, valid `AK.json` before every managed launch (`managed_obs.py:889`, `:920-921`). OBS falls back to `.bak` only when the primary is damaged, so a managed launch never reads the backup.

**Fix wording:** "`AK.json.bak` may hold mid-transaction state. It is unreachable by managed launches because `_seed` writes a valid primary first; record it, no mutation."

## Counts
blocker 0 · major 0 · medium 3 · low 3

## Verdict
**CHANGES REQUIRED.** Three mediums to fold, per the rounds 1–3 rule. No majors or blockers.

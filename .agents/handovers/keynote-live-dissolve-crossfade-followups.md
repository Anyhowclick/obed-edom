# Dissolve cross-fade — follow-ups (handover)

**2026-10-12; landed in #262 (`c6f37e5e`) 2026-10-13.** Patch: `claude/keynote-live-dissolve-crossfade`, plan `.agents/plans/keynote_live_dissolve_crossfade.plan.md`
(rev 17, cited as §n). It ships D1–D4 under `mm_opacity` (§0, §4); the movie freeze only on the host-launched, qualified
Chrome (`LiveOutputHost`, Chrome 154, GPU compositing; §3.3, decision 15). Everything below is deliberately **not** in that PR.
Evidence kept (main checkout, git-ignored, pruned 2026-10-13): `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` —
`q0b-2026-10-11/runs/decision_record_q0b1.json` (the `--decision` input of every DX run), `dx1-2026-10-12/dx1_paced.py` (the
load-paced DX-1 runner), `cef-frac-2026-10-12/` and `q0bbis-2026-10-12/` (README, results, probe scripts: CEF placement and
W5), `hidpi-2026-10-12/` (README, scripts: scaled stages). Everything else was removed.

## CEF/OBS placement — follow-up PR (decision 15; §13.1)

Today managed OBS/CEF keeps the movie jump (`output.placement.reason = "attached"`): CEF 127 draws the video quad unsnapped
(x 109.352), so the snapped holder misses by up to 183 LSB there (§8.6). Full design: rev 16's §3.3 and §9 (`41ef609b`).
1. **First: the 5-minute OBS feasibility check.** Does `GetSourceScreenshot` render a browser source that is not on program
   (a dedicated `AK-Calibrate` scene / `AK-Probe` source)? If not, re-plan the isolation gate before anything else.
2. **Placement probe:** isolated probe target/source; program-capture gate with cleanup on every exit; the shipped clip
   (`p2like.mp4`, sha256 `7b7d66b5…`); rev 16's classifier (tone maps {identity, GPU analytic}, inner mask, max over channels,
   both poses, ≤ 2 % / ≥ 20 %); lease, keep-alive and invalid / probing / valid lifecycle; operator `recalibrate`
   (`web/live.py`, `live_session.py`, presenter UI); reconnect re-probe.
3. **The `frac` take draw:** snapped underlay plus CEF 127's unsnapped quad (`fdrawu`, +186 B), DPR 1 and integer stage origin
   only; its grant value joins `snap` in this PR's channel.
4. **CEF acceptance:** `m-snap-cef[clip]`, `nooffset[x|y]`, wrong-rule controls through the privileged channel, `iso-*`,
   `probe-*`, `life-cal-*`, CEF DSK 7→8 cost with the extra draw, CEF `hevc10` / Keynote-HEVC tone.
5. **W5's tone-path map** on the same probe (recorded first, applied only after its own qualification).

## Open review items not folded (GPT-6 Astra r13 on rev 17; owner: no rev 18, discover after implementation)

Source: GPT-6 Astra r13 on rev 17 (plan §14). Both remain open in the merged bytes.
- **r13 #1 — raw/preview forgery (major).** Raw export and Build Preview have no host channel, so page code assigning
  `window.__obedPlacement = "snap"` (or a non-configurable getter returning it) on an unqualified engine (e.g. a manually
  configured CEF source) enables the freeze with Chrome's snapped rule. Proposed fix: no executable freeze entry point outside
  the host rendering variant; production raw/preview controls that forge `snap` both ways and require no holder.
- **r13 #3 — stale grant after an unobserved GPU fallback (medium).** Chrome falling back to software between `observe()`
  samples leaves `snap` granted until the next successful observation, **with CDP connected too** (not only disconnected, as
  §3.3 "Residual" states); tagged H.264 keeps the qualified tuple on both paths, so the tuple guard does not stop it. No
  guaranteed bound. Owner decision 16 keeps the lease dropped; a lease would bound, not remove, the window.

## Tone decision record (rev 12; unchanged in rev 17)

`Q` = `["bt709/bt709/bt709/false"]` · `L` = identity (owner decision 10, §12; §3.2 "Tone"). Q0b 1 found software compositing
(`--disable-gpu`) live == snapshot for the same tagged tuple, while GPU compositing carries the `BT709_APPLE` step (mid-grey
128 → 139), so the tuple cannot select `L` (§1.4). The GPU mid-tone step at
the freeze is a known limit; Q5 stays open until W5 reports.

## W5 — host-side compositing-path calibration feasibility (non-blocking; needed before Q5 closes)

Scratch + evidence only, whenever a browser window is free (§11 W5 row, §12.10). Question: can the host, at startup, identify
the compositing path and its map (qualified path + tuple → `L`, unknown → identity) from compositor-painted pixels? Headless
`LiveOutputHost` (GPU, `--disable-gpu`) and managed OBS (acceleration on/off), two fresh launches each; the tone movie paused
in an off-screen-safe calibration slot, CDP screenshot / `GetSourceScreenshot` vs `drawImage`. Record repeatability, GPU vs
software distinguishability for one tuple and invalidation on GPU-state change, with a go/no-go; on go, the player-boundary
change it needs goes to the owner. No page-side heuristics. Decision 13/15: the map may ride the CEF placement follow-up's probe (item 5 above).

## Scaled stages (decision 12; open)

Fix A admits DPR 1, 1.5 and 2 at stage scale 1. Stage scale ≠ 1 and nested scales still skip (today's jump): an output not
1920 CSS px wide (2560×1440 or 1280×720 at DSF 1); fix A at stage 4/3 still reads 162 / 9.3 % on P2 (§13). A future model
needs a per-chain rule and must solve `object-fit: contain` in local units first (§13 anisotropic `contain` bug). Evidence:
`hidpi-2026-10-12/`.

## (a) Bridged / held decoder over the outgoing transition — owner Q6, separate PR after S2

- **When:** after S2 (`claude/s2-detach-fix`, plan cites `d88584eb`) merges to `main`. Nothing is asked of S2's in-flight
  branch (§6.2 S2 row, §12.6).
- **Symptom:** on P2-measured plans (`QUALIFIED_PLAN_SHA256`, `live_continuity.py:627`, `:895`), P2 slide 4's terminal
  Dissolve shows main's bridged movie at full strength, **stock and patched alike**. `keepAtSlot`
  (`live_continuity_js.py:1056`) keeps the 3→4 bridged decoder in `#body` (outside the scene) at opacity 1, re-attached
  and playing, while the hash is ≥ slide 4; `slotLive` (`:1007`) has no transition condition (§1.4). It also keeps D4 from
  admitting that slide's freeze (§6.2 continuity row). S2 likewise holds its restarting decoder at opacity 1 through
  P2 2→3's Dissolve, over D4's fading snapshot (§1.4, §6.2 S2 row).
- **Expected:** at the outgoing transition start, main's bridged decoder and S2's held decoder stop painting, so D4
  snapshots the current frame and that copy fades with the slide like any other admitted movie. Fresh-decoder restarts
  stay intact.
- **Gate:** make the `m-bridge` arm of `scripts/dissolve_probe.py` blocking (today reported only, expected FAIL; its
  stock twin `m-bridge-off` is the FAIL control: §9.1 table, §9.2). Stock P2 4→end confirming the bridge is Q0b item 5 (§9.0).
- **Code:** `src/obed_edom/live_continuity_js.py` (`keepAtSlot`, `slotLive`) on `main`; S2's hold as merged.

## (b) G2 use of a qualified `L` — optional, separate follow-up

G2 GL replay has the same untoned midtone step at takeover as D4's freeze (§1.4 tone path, §6.2 G2 row; README "During a
show:" already names the G2 step). A qualified `L` (W5 go plus owner decision) could serve both. Move
`managed_obs_qualify.EXPECTED_STATS` only with an independent diagnosis. Only worth doing once W5 qualifies a non-identity `L`.

## (c) F2 — other CSS transitions and smart/action builds

Other CSS transitions the player special-cases and smart/action builds (0 on disk today; fill-less behaviour unknown):
a separate PR with an owner Q-deck (owner decision 3, §12; §5 table; §13 out of scope).

## Qualification — re-running the gates, and what is still INCONCLUSIVE

- **Re-run** (unsandboxed, on AC power — battery + Low Power Mode throttles capture below the mid-frame minimum; send "need
  window" to peer sessions first; keep the raw run dirs until any review of them closes). From a worktree pinned to the commit
  under test, with `D=<that worktree>`, `E=<main>/output/evidence/s2-dev/dissolve-alpha-2026-10-11`:
  - DX-1: `PYTHONPATH=$D/src <main>/.venv/bin/python $E/dx1-2026-10-12/dx1_paced.py <out> <scratch> $E/q0b-2026-10-11/runs/decision_record_q0b1.json grant-chrome,grant-attach,channel-predefined,life-grant-reload,opaque-off,off,noblend,on,on2,m-paused,m-off,m-on,m-hold,m-raw,m-raw-prod,m-preview-prod`,
    then `scripts/dissolve_probe.py --score <out> --decision <same>`. It waits for load < 3.5 per arm; an arm INCONCLUSIVE only
    for capture coverage ("N mid frames < 6") is retired (move its run dir out) and re-run.
  - DX-2: `scripts/managed_obs_qualify.py --arm dissolve --out <out> --decision <same>` (`--score` does not re-score dissolve
    sessions; call `managed_obs_qualify.dissolve_gates` on the saved run instead).
- **DX-1 checks outside the F3 scope, still INCONCLUSIVE at merge:** reference capture ("null timing while paused": all
  `m-snap*`, `m-tone`), the DPR arms (window opens 1920×993), `m-geo*`, `life-*`, cut, `overlay` (`m-bridge-off` is the S2
  bridge, item (a)). Never dry-run: `m-geo-*`, hide rows (need per-frame screencast cadence), D2, `m-tone-twin`, the crop A/B.

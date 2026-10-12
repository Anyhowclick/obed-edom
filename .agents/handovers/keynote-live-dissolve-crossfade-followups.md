# Dissolve cross-fade — follow-ups (handover)

**2026-10-11.** Patch: `claude/keynote-live-dissolve-crossfade`, plan `.agents/plans/keynote_live_dissolve_crossfade.plan.md`
(rev 12, cited as §n). It ships D1–D4 under `mm_opacity` (§0, §4). Everything below is deliberately **not** in that PR.
Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored).

## Tone decision record (rev 12)

`Q` = `["bt709/bt709/bt709/false"]` · `L` = identity (owner decision 10, §12; §3.2 "Tone"). Q0b 1 found software compositing
(`--disable-gpu`) live == snapshot for the same tagged tuple, while GPU compositing carries the `BT709_APPLE` step (mid-grey
128 → 139), so the tuple cannot select `L` (§1.4; `keynote-live-dissolve-crossfade-2026-10-12.md`). The GPU mid-tone step at
the freeze is a known limit; Q5 stays open until W5 reports.

## W5 — host-side compositing-path calibration feasibility (non-blocking; needed before Q5 closes)

Scratch + evidence only, whenever a browser window is free (§11 W5 row, §12.10). Question: can the host, at startup, identify
the compositing path and its map (qualified path + tuple → `L`, unknown → identity) from compositor-painted pixels? Headless
`LiveOutputHost` (GPU, `--disable-gpu`) and managed OBS (acceleration on/off), two fresh launches each; the tone movie paused
in an off-screen-safe calibration slot, CDP screenshot / `GetSourceScreenshot` vs `drawImage`. Record repeatability, GPU vs
software distinguishability for one tuple and invalidation on GPU-state change, with a go/no-go; on go, the player-boundary
change it needs goes to the owner. No page-side heuristics.

## Hi-DPI investigation hook — geometry beyond the guard (decision 12, reversed; open)

The take skips (today's baked-frame jump) unless DSF 1, `kx` = `ky` = 1, stage scale 1, integer stage origin and
translation-only scene transforms (§3.2 "Geometry guard", §12.12, §13). The investigator's model (DPR, stage scale, nested
transforms, pixel phase, clipping) replaces exactly that guard and `sn`/`ww`/`hh`/`dx`…`dh`; the full-backing alpha scan,
exterior proof, clipping and foreground preservation stay mandatory (§9.1 "Geometry classes"). Evidence will land in the main
checkout's `output/evidence/s2-dev/dissolve-alpha-2026-10-11/hidpi-2026-10-12/` (not yet created).

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

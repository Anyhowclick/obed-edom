# Dissolve cross-fade — follow-ups (handover)

**2026-10-11.** Patch: `claude/keynote-live-dissolve-crossfade`, plan `.agents/plans/keynote_live_dissolve_crossfade.plan.md`
(rev 9, cited as §n). It ships D1–D4 under `mm_opacity` (§0, §4). Everything below is deliberately **not** in that PR.
Evidence: main checkout `output/evidence/s2-dev/dissolve-alpha-2026-10-11/` (git-ignored).

## Q0b decision record

`Q` = _TBD (coordinator)_ · `L` = _TBD (coordinator)_ — §9.0 item 1, criteria §12.5.

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

## (b) G2 use of the tone map `L` — optional, separate follow-up

G2 GL replay has the same untoned midtone step at takeover that D4's `L` removes for the freeze (§1.4 tone path, §6.2 G2
row; README "During a show:" already names the G2 step). `L` could serve it. Move `managed_obs_qualify.EXPECTED_STATS` only
with an independent diagnosis. Only worth doing if Q0b records a non-identity `L`.

## (c) F2 — other CSS transitions and smart/action builds

Other CSS transitions the player special-cases and smart/action builds (0 on disk today; fill-less behaviour unknown):
a separate PR with an owner Q-deck (owner decision 3, §12; §5 table; §13 out of scope).

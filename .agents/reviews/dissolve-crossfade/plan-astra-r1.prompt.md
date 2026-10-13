NON-INTERACTIVE. Do not propose a plan, do not ask for approval, do not edit any file. You are the CRITIQUE pass on a written implementation plan. Read files, verify claims, and output findings only.

# Target
Plan under review (uncommitted, on disk):
/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md
Repo worktree (origin/main 1589d096): /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851
Main checkout (git-ignored fixtures/evidence): /Users/anyhowclick/Desktop/work/obed-edom/output/

# What the plan is for
Keynote's HTML export player (main.js, sha-pinned players e9b2fad4… and 17c0c938…) draws `apple:dissolve` with its CSS renderer: only the OUTGOING slide layer animates opacity 1→0 (EaseInEaseOut); the INCOMING layer sits underneath at opacity 1. Keynote's export bakes a full-slide black fill into each slide texture, so the outgoing texture normally hides the incoming one. When the outgoing texture has transparent areas (background fill stripped, or a deck without a fill) the incoming slide pops in at full strength from the first frame. The Alpha Keynote live presenter renders on a transparent page for OBS keying. The plan proposes an in-memory, sha-pinned `patch_player` replacement (owner rule: never modify main.js on disk; anchors count-checked exactly once; unknown players refused) that fades the incoming layer 0→1 with the same timing and composites exactly (target: premultiplied result = (1−e)·P_out + e·P_in, i.e. Keynote-on-black equivalence), plus scope, interplay with existing patches/continuity/GL replay/managed-OBS qualifier/run_gates, and acceptance (headless gate with null + positive controls, owner real-OBS check, minimal tests).

Owner's target, from the Keynote app: a normal cross-fade (incoming fades in, outgoing colours kept).

# Independent root-cause verification (another agent, headless Chrome 154; raw data in
/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-brave-goodall-bd9851/b73583c5-a781-4361-83a3-305e83ee5b51/scratchpad/rootcause/)
- `jC` GL list @2368254 (17c0c938) / @2368216 (e9b2fad4) has no `apple:dissolve`; transitions route in `renderEffects` base-layer branch @2312816; @2314117 is the object-build path. Player shift: +19 B after 2331092, +38 B after 2331363.
- The fade is in the export JSON (outgoing opacity 1→0 EaseInEaseOut fillMode both; incoming no animation), applied as a CSS keyframe animation on the `layer6-opacity` wrapper; EaseInEaseOut → `ease-in-out` (@2282229).
- Pop-in condition = fill-less outgoing texture, not page transparency: Keynote PDFs + transparent page = no pop-in; stripped PDFs + opaque black body = pop-in.
- Incoming 0→1 alone dips overlap alpha to 1−e+e² (0.749 at mid); plus-lighter on the outgoing layer + `isolation:isolate` on the parent measured exact in Chrome 154. CEF 127 (OBS 32.2.2) untested.
- One sampled frame had the incoming layer at opacity 1 before the player's setTimeout attached the animation.

# Your job
Verify the plan against primary sources and find what is wrong, missing, unproven or over-built. Check at least:
1. Every main.js anchor/offset the plan cites: occurs exactly once in BOTH players (main checkout output/fixtures/keynote-player-17c0c938/main.js and output/fixtures/p2-recovery/html-adversarial/html-unmodified/assets/player/main.js), does not overlap or reorder against the existing replacements in src/obed_edom/live_runtime.py (`_MM_OPACITY_REPLACEMENTS`), and the replacement code is correct JS for the minified context (variable names, `this`, scoping, every path that creates/animates/tears down the layers: normal play, skip/fast-forward, interruption, go-to/jump, automatic play, loop, end of show, repeated dissolves).
2. The compositing arithmetic and its preconditions: what the additive blend mixes with (page background, the host's hide cover, continuity pins/bridges/overlays, <video> elements, GL canvases, sibling layers), stacking-context/isolation correctness, 8-bit quantisation tolerance, and whether it stays exact when the outgoing slide is opaque (no regression on today's exact case) and in opaque (screen/HDMI) output.
3. Browser support claims (CEF/Chromium 127 in OBS 32.2.2; headless Chrome 154; any `--disable-gpu`/software-compositing gate arm): is evidence cited, and is the plan's fallback sound if unsupported?
4. Switch/pin design: knob precedence, pin matrix with mm_opacity, patch_rendering (dashboard preview) and the paint oracle, the output report key, RUNTIME_VERSION, refusal behaviour — consistent with src/obed_edom/live_host.py, live_runtime.py, html_preview.py, html_alpha_probe.py and the SKILL contract (.agents/skills/obed-edom/SKILL.md "Magic Move opacity").
5. Scope: survey of other CSS-rendered effects (transitions and builds) — is the classification evidenced, and is anything with the same occlusion assumption left out without saying so?
6. Interplay: S2 (branch claude/s2-detach-fix — read via git refs only), GL replay, continuity core, managed_obs_qualify EXPECTED_STATS, run_gates.sh arms, pinned shas in tests — what breaks or must be re-run that the plan misses.
7. Acceptance: does each gate check FAIL its known-bad (null control shows the pop-in) and pass a positive control; integrity failures INCONCLUSIVE (fail closed); deck choice actually exercises incoming-only and overlap areas; curve tolerances justified; owner OBS check concrete. Tests minimal (max coverage, fewest tests, parametrized) yet sufficient.
8. Owner questions: only ones whose answer changes the design, each with a recommendation; flag missing ones and ones the code could settle.
9. Implementation streams split by DISJOINT files; nothing touches main.js on disk; nothing writes fixtures.

# Output format
A numbered list of findings, most severe first. For each: **Severity** (blocker / major / minor / nit), **Class** (new class / closed class / edge case), plan section, the claim, the evidence you checked (file:line or byte offset, command output summary), and the exact fix wording you recommend. Then a short list of plan claims you verified as correct (so the folder knows what NOT to touch). End with a one-line verdict: ready for owner review after fixes / needs another planning pass.

# Live continuity — from a one-deck allowlist to generally accepted transitions

Brief for a peer session. Written 2026-09-19. Owner priority: **not urgent, but the main road to
real decks.** Parent plan: [`keynote_live_continuity.plan.md`](keynote_live_continuity.plan.md) ·
P2 model: [`keynote-alpha.md`](keynote-alpha.md) · handover with tonight's history:
[`../handovers/keynote-live-continuity-2026-09-19.md`](../handovers/keynote-live-continuity-2026-09-19.md).

## The issue in one paragraph
The live host can carry a playing movie through Keynote Magic Moves (the raw HTML export restarts or
freezes it). The owner approved policy **3a: "bridge every geometry-changing Magic Move where the same
movie continues."** Review and real-OBS testing showed the shared runtime
(`src/obed_edom/live_continuity_js.py`, extracted from the P2 probe) cannot carry that policy out safely:
it was developed against ONE deck shape and encodes that shape. A different deck could derive a
valid-looking plan, be reported `continuity: qualified`, and get a **wrong repair on air** — worse than
the raw player's restart. So `ContinuityPlan.to_runtime()` currently fails closed unless the runtime
plan's signature is in `QUALIFIED_PLAN_SHA256` (`src/obed_edom/live_continuity.py`) — today exactly one
entry, the P2 fixture deck `Minimal Alpha_DSK`. Every other deck plays on the raw player with
`continuity: unsupported — deck shape is not yet qualified`. **The goal of this work is to make 3a true
and retire the allowlist.**

## Why the runtime is not generic (evidence)
| # | Limitation | Where | What goes wrong on another deck |
|---|---|---|---|
| 1 | Pools decoded movies and remounts them; until 2026-09-19 it pooled EVERY movie. Now filtered to plan-named movies (`stash` → `movieAssetKey`), but lifecycle is still implicit | `stash`, `scheduleRemount`, `tryRemount` | Seen for real in OBS on the fixture: the slide-3-only clip WA0125 was remounted on slide 4 at the fallback footprint (109,795). A planned movie that legitimately ENDS at some slide has no "retire here" boundary either |
| 2 | Only the FIRST restart and the FIRST bridge are honoured; after the bridge, any pooled matching source is bridged to that first rect without consulting `movieKey` | boundary lookups (`restartMinHash`/`slide4MinHash`-style helpers reading `OBED_PLAN.boundaries`), `bridgeTo34`, `keepAtSlot` | A second Magic Move later in the deck lands at the first move's rectangle; a restart authored after a bridge is silently carried instead |
| 3 | "Pin" is one implicit zone before the first boundary, at ONE static footprint per movie | `keepAtFootprint`, plan shape (`movies[k].footprint`) | A pin needed after a restart, or a movie whose resting rect differs per slide, cannot be expressed (the 3→4 in-move bug came from this: during the move the video was pinned at the slide-1 footprint) |
| 4 | Two instances of the same asset are told apart by DOM/pool order (`pool.get(key).shift()`), not by the geometry the plan chose | reuse path in the `createElement`→`setAttribute('src')` policy | The stray copy can be carried. The fixture's slide 1 really has two `Untitled.mov` instances and only works because its order is stable |
| 5 | Motion through a bridge is a LINEAR src→dst interpolation over the export's duration; Keynote animates inside WebGL with its own easing, so there is no DOM rect to follow | runtime v2 motion code | A sliver of the player's frozen poster can show at the leading edge mid-move; curved motion paths / rotation are unsupported |
| 6 | Geometry is authored-pixel, viewport must equal the canvas | in-page viewport gate in `live_host.py` | Nothing qualifies on a 2560×1440 HDMI display until scaled-stage mapping (plan increment I3) |
| 7 | No "Play movie across slides" flag exists in the export, so intent is inferred | `derive_plan` | A deck deliberately authored to RESTART at a Magic Move would be carried (accepted residual under 3a — keep it visible in the capability report) |

Gates did not catch #1 because neither the P2 gate nor the host gate checks for movies that should NOT
be on a slide. That is the first instrument gap to close (below).

## Target design
1. **Boundary-specific runtime.** Replace "implicit pin zone + first restart + first bridge" with a list
   the runtime walks by scene index: for each boundary and each planned movie INSTANCE an explicit action
   `pin | bridge | restart | retire`, with the rects it needs (`srcRect`, `dstRect`), `durationSeconds`,
   and the instance's identity. Nothing un-planned is ever touched. `derive_plan` already produces
   per-boundary `pin/bridge/restart` with src/dst rects; add `retire` (asset absent on the far side) and
   per-instance identity, and make `to_runtime()` a near-1:1 mapping.
2. **Instance identity by geometry, not order.** The plan names which instance continues (rect on the
   near side, rect on the far side); reuse selects the pooled decoder whose last measured rect matches,
   and refuses (raw player for that boundary) when ambiguous.
3. **Per-slide resting rects** so pin/keep uses the rect of the CURRENT slide, never a deck-global footprint.
4. **Structural refusals stay the safety net** (already in `derive_plan`/`to_runtime`): rotation or
   non-identity affine, nested video layers, unknown transition kinds, >1 movie changing geometry in one
   move, ambiguous instances, missing duration. Extend rather than relax.
5. **Retire the allowlist last.** Order: (a) land the boundary-specific runtime with the fixture still
   green; (b) author 3–5 small qualification decks that each isolate one shape (two Magic Moves in a row;
   restart after a bridge; movie that ends mid-deck while another continues; two instances of one asset
   where the far one continues; pin after a restart; movie entering at a Magic Move); (c) add each
   qualified plan signature to the allowlist as it passes; (d) once the structural refusals plus the
   expanded gates cover every shape the allowlist was protecting against, delete the allowlist and let
   3a stand on refusals alone. Owner decides when (d) happens.

## Instrument work that must come with it (no green without a red control)
- **Stray-movie check** in BOTH gates: on every settled slide, the set of visible, connected `<video>`
  elements (and their rects) must equal what the plan/export says is on that slide. Red control: disable
  the `stash` plan filter and show the gate catches WA0125 on slide 4.
- **Per-boundary verdicts generated from the plan** in `scripts/live_continuity_probe.py` (today the three
  boundaries are hard-wired): continuity / restart / retire scored for every boundary the plan declares,
  with the existing strict criteria (identity, runtime owner agreement, windowed clock advance,
  accumulated stall, phase-ordered rect path, landing rect, expected continuity mode per arm).
- **A red arm per action type**: strip one boundary of each kind from the runtime plan (probe-only
  monkeypatch, as arm C does for the bridge) and require exactly that verdict to go red.
- The **P2 gate remains the oracle for the shared bytes**: after any change to
  `live_continuity_js.py` run `scripts/p2_recovery_html_adversarial.py --reuse-export --disposable`
  with `--wait-profile fast` and `slow` (14/14 True) and `--disable-bridge34` (RED only on
  `continueThroughMovingMagicMove3to4`). The P2 scripts inject their own fixture plan — if the plan
  shape changes, update that injection in the same commit and keep P2's thresholds untouched.
- Real-OBS check (attach mode) found two defects the headless gates missed on 2026-09-19. Keep a short
  real-OBS pass in the acceptance list for anything that changes what is visible.

## Constraints and house rules
Accuracy and code quality over speed · keep it simple, no new frameworks · match local style · **no
inline comments in src unless essential** (the JS keeps comments that encode hard-won model facts) ·
never weaken a gate or loosen a threshold to get green — a red under a stricter scorer is a finding ·
headless Chrome only unless the owner gives a go for a visible window or the monitor · never launch
Keynote; source decks untouched; qualification decks are authored by the owner and exported to HTML ·
no merge / force-push without the owner · plan first for anything with more than one valid approach.

## Pointers
- Runtime + plan shape docstring: `src/obed_edom/live_continuity_js.py` (`CONTINUITY_VERSION`, `js_sha256()`).
- Derivation + translation + allowlist: `src/obed_edom/live_continuity.py`; tests
  `tests/test_live_continuity.py` (trimmed export fixture under `tests/fixtures/live_continuity/`).
- Host injection + modes (`qualified | unsupported | off`, reasons, `OBED_LIVE_CONTINUITY`,
  viewport gate, `ready` read-back): `src/obed_edom/live_host.py`; tests `tests/test_live_host.py`.
- Host gate: `scripts/live_continuity_probe.py` (+ `tests/test_live_continuity_probe.py`, pure scorers).
- Fixture export (H.264 movies): `output/p2-recovery/html-adversarial/{html-player,html-unmodified}` in the
  presenter worktree (ignored; the old `keynote-parser-module-error-*` worktree copy no longer exists).
- Commands, gotchas (macOS `nativeVirtualKeyCode` stall, atomic add+commit, headless height quirk):
  the handover linked at the top.

## Definition of done
`to_runtime()` has no signature allowlist; a deck is `qualified` exactly when every boundary of every
planned movie instance is expressible and unambiguous, otherwise `unsupported` with the specific
boundary and reason; both gates score every declared boundary plus stray-movie absence, each with a red
control; the fixture and the owner's qualification decks pass headless, in real OBS, and at the owner's
eye on the receiver; README and the capability report say plainly what is and is not carried.

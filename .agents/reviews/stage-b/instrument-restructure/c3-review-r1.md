# C3 review r1 (2026-10-16)

Diff: `1a421de2..a54861e8` (V `f56837a3`, P `a54861e8`). Implementer: Codex GPT-5.6 Sol high.
Reviewers: three Opus 5.5 high lenses (acceptance/false passes; phases/mounts/clocks; tests/isolation/contract), plus a
coordinator fresh-capture differential. Every major/blocker below was reproduced by executing a script (old 1a421de2 vs
HEAD on the same rows), so execution served as the adversarial verification. Scripts: `/private/tmp/claude-501/c3-review/`.

## Coordinator differential (fresh captures)
10 headless captures on base code (D1 null, D1 later-decode-loss injection, D2/D3/D5 no-pin-hold, D1 strip bridge@2,
D2 strip pin@6, D3 strip bridge@6, D7 feed-on null, P2 null), each rescored by base and C3 `score_arm` on identical rows:
65 verdicts, 22 changed. Registered reds became None (D2/D3/D5 no-pin-hold, D2 strip pin@6, P2 refused 1→2), and clean
nulls lost passes (D1 b2to3 True → None). The later-decode-loss red (D1 b0to1) stayed False.

## Findings
| # | Sev | Class | Finding | Fold |
|---|---|---|---|---|
| C1 | blocker | new | Source = `(transition or atScene) - 1` ignores `spec.sourceScene`: transition-less carries lose their settled source (registered reds → None; multi-scene source defects False → True) | source range `[sourceScene, Sc]` |
| A1 | blocker | new | Decode loss after the mount's first decode is excluded as cold start (False → True) | start at the first settled source row ≥ the mount's first decode |
| A2/Ph3 | blocker | new | Replacement on the settled source hidden by per-decoder starts (False → True) | ground at a non-surviving predecessor's start, report `replacedFrom` |
| Ph1 | major | new | Only the latest contiguous source visit counts; defects in earlier visits vanish | union of source rows |
| C2 | major | new | Alpha feed-on b6to7/b7to8 `missingSamples` inside the evidenced GL interval (from the Stage B coordinator's C1 matrix; pre-existing) | excuse absent rows in GL (`glExcusedMissing`) |
| Ph4 | medium | new | Non-finite readyState before the start silently moves it | INCONCLUSIVE |
| Ph5 | medium | edge | goTo `IdleAtInitialState` source → None with a misleading reason | specific reason |
| Ph6/T | medium | gap | `entryColdStart` lacks the visible-undecoded fields | add them |
| T | medium | gap | Core rule untested: drop `busy is False` survives all tests; test names and assertions disagree | extend the parameterization |
| A4 | medium | new | Force-wrap gains a chain clip | no clip on force-wrap |
| A5 | low | — | `decode_loss` in scope; not exempt in GL | exempt in GL |
| A6 | low | edge | Busy-less historical rows → None (missing evidence) | accepted, consistent with plan |
| Ph7/Ph8/A7 | low | closed | Dead fields, an O(n²) loop, the `chain_clip`/`pad_s` params, the third `window_bounds` return | delete |
| Ph9/T | low | — | `verdicts: None` crash; mixed int/str ids in `entryColdStart` | `or ()`, str keys |
| Ph10 | low | — | `videoWidth>0` gate dropped | restore `decoded_anywhere` |

Confirmed clean: `entryColdStart` is isolated from verdicts/combine/status/gates/OBS/replay. The `nextSceneId` contract
patch is correct. Crossing/unplaced, chain clip, GL segments and forced-seek arithmetic match the old code.

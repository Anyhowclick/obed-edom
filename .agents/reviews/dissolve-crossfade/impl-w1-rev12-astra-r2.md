**CHANGES REQUIRED**

| R1 finding | Status | Verification |
|---|---|---|
| 1. Shadow invariant | **NOT CLOSED** | Original controls are caught, but allowlist and stripped-read bypasses survive. |
| 2. Exterior-proof coverage | **CLOSED** | Fixed-pseudo and isolated witness guard-removal mutations fail on both players. |
| 3. Terminal alpha pixel | **CLOSED** | `j<d.length-4` fails `dpr1_lastPixelTransparent` on both players. |
| 4. Fractional horizontal origin | **CLOSED** | Removing `||R.left%1` fails `stageFractionalOriginX` on both players. |

Finding 1 remains **Major** at [the allowlist and unconditional stripping](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:438). Both expressions evade `_shadow_tokens`:

```js
h['attach'+('boxShadow').slice(3)]({mode:'closed'})
h['attach'+('!n.shadowRoot&&(').slice(3,9).replace('s','S')]({mode:'closed'})
```

Each was inserted **in memory** into the checked P2 export, creating a host and assigning a fixed, full-viewport overlay to its closed root. Both mutations pass the complete source-invariant test on **both players**. Node independently confirms both expressions invoke `attachShadow({mode:'closed'})`.

The exact-once assertion protects only on/rendering players; export and host sources receive unconditional stripping. Neither bypass uses character codes or base64, so the stated residual is incomplete. Exceptions need to be constrained to verified occurrences and contexts.

Verification: **125 passed, 0 skipped, 12.45 s**, using an in-memory Node-file adapter with conftest disabled for the read-only environment. All **260 baseline rows** pass; **17 guard mutations** fail on each player. No new findings beyond the unresolved R1 finding.
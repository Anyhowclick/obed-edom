**APPROVE** — freeze-trigger changes `d0b94981..dcd5b9e4`, reviewed at pinned `dcd5b9e4`; checkout HEAD differs.

- **R3 MINOR: CLOSED** — `src/obed_edom/p2_verdict.py:3502,3506`. Both branches now allow timestamp equality. The 90 ms tie passes; a marker 0.1 ms earlier remains inconclusive. **Fix verified; CLASSIFICATION: closed class.**
- **Equality safety confirmed for captured evidence.** An earlier poll that could observe the fresh marker records it synchronously (`scripts/p2_recovery_html_adversarial.py:1349–1355`). Equal timestamps cannot defer that observation. The deadline remains derived from `marker.started + latency`, independently of the marker’s reported frame (`p2_verdict.py:3509–3515`), and the trigger-frame limit remains enforced (`:3885`). Equality adds no late-trigger allowance.
- **New defects in `dcd5b9e4`: none found.** No open standards or correctness findings in the reviewed freeze-trigger change set.

Validation: **21 pinned trigger cases passed**, plus direct equality/strictly-earlier checks for both bracket branches. No files edited.
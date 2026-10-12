NON-INTERACTIVE. Do not propose a plan or ask for approval; produce the critique directly.

Critique plan rev 17 of the Obed-Edom dissolve cross-fade patch: `.agents/plans/keynote_live_dissolve_crossfade.plan.md` (repo = current directory; `git diff 95c55e45 642e1746 -- .agents/plans/` = rev 15 → 17; `git show 642e1746` = rev 16 → 17). Your r12 critique of rev 15: `.agents/reviews/dissolve-crossfade/plan-astra-r12.md` (rev 16 folded it, uncritiqued). Rev 17 evidence: /Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-rev17-2026-10-12/README.md (Node only: 285-row harness on real extracted player code, grant channel tamper checks under `vm`).

Context: owner decision 15 (§12) SPLIT the work. This PR ships the movie freeze only on the Chrome that `LiveOutputHost` launches, qualified by CDP `Browser.getVersion` major 154 plus GPU compositing, granted through a host-only, page-unforgeable per-document channel (`window.__obedPlacement`, only value `"snap"`). CEF/OBS, attach mode, other versions, software compositing and any failure skip (today's jump) with the reason in `output.placement`. The startup placement probe, `frac` draw, output isolation gate, OBS calibrate scene, recalibrate command, CEF clip matrix and W5 tone map move to a follow-up PR (§13.1). Decision 14: raw / Build Preview no longer freeze. Do not re-litigate decisions 13–15.

Task:
(1) Each r12 finding: CLOSED, NOT CLOSED, or MOVED (out of this PR by decision 15, and §13.1 carries it) — with plan-section evidence. A MOVED item that still leaves a reachable false admission in THIS PR is NOT CLOSED.
(2) Planner's re-check list — judge each, finding only with a concrete scenario:
  a. lease and keep-alive dropped; residual = an automatic transition while CDP is disconnected after an unobserved GPU→software fallback;
  b. the grant also requires GPU compositing (how it is detected; what if it changes after the grant);
  c. pin major 154 vs the exact build;
  d. `cef-skip` as a hard FAIL in DX-2; CEF media/tone sessions removed from DX-2;
  e. integer left/top kept as pure narrowing (no admission it widens);
  f. DX-3 split: freeze checked on the HDMI host (owner-run), cross-fade/jump in OBS;
  g. context-bound commit (`uniqueContextId`) vs `ChromeCdp` event plumbing that exists in `src/obed_edom/live_host.py` today — is the W6 design implementable without new CDP infrastructure the plan does not list?
  h. open defaults: major 154 only; automatic re-grant after renderer crash + reload.
(3) Closing sweep over the CLASSES r12 found (flag integrity, lifecycle, acceptance coverage, scope) as they apply to the GRANT now; report a new finding ONLY with a concrete scenario showing a false admission (freeze where the snapped rule is not proven) or a false pass.
Findings: severity, CLASS (new class / closed class / edge case), plan section, scenario, exact fix wording. One-line verdict: READY FOR IMPLEMENTATION or CHANGES REQUIRED.

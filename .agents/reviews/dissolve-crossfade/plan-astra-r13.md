**CHANGES REQUIRED**

Rev 17 resolves the scope split, but the grant still has two admission holes and an understated lifecycle limit. W6 also needs explicit CDP transport work.

I re-ran the channel’s Node checks and verified all four candidate digests. Using the extracted rev-17 methods in the supplied DOM harness, I reproduced the missing-channel bypass below. These checks do not establish browser qualification.

**Disposition of each r12 finding**

| r12 finding | Status | Plan-section evidence |
|---|---|---|
| 1. Flag integrity | **NOT CLOSED** | §3.3 protects the getter **after host initialization**, but §§3.1–3.2 still trust the string returned by `window.__obedPlacement`. Raw/preview pages intentionally lack that protection. Finding 1 below. |
| 2. Output isolation | **MOVED** | §3.3 performs no pixel probe; §13.1 items 1–2 carry the separate source, program-capture gate and cleanup. No remaining probe leaks onto program in this PR. |
| 3. Classifier specification | **MOVED** | No classifier participates in this PR’s admission. §13.1 item 2 carries the shipped clip, tone treatment, mask, channel aggregation and two-pose thresholds, referencing rev 16. |
| 4. Calibration lifecycle | **NOT CLOSED** | §3.3 specifies unique-context commits and fresh-document invalidation, but its mutable GPU condition defeats the stated immutable-grant rationale. Findings 2–3 below. Probe/recalibration work moves under §13.1 item 2; grant lifecycle remains here. |
| 5. CEF fractional-draw acceptance | **MOVED** | §3.1 removes `frac`; §9.2 requires CEF to skip; §13.1 items 3–4 carry the fractional draw, clip matrix, foreground cases and wrong-offset controls. The grant bypasses below must still be fixed; moving this matrix cannot excuse CEF admission. |
| 6. Raw/preview scope regression | **CLOSED** | §12 decision 14 explicitly supersedes decision 8’s preview requirement. §§4, 9 and 9.0 require production raw/preview skips. The separate enforcement hole is finding 1, not a reason to reverse that decision. |

**Findings**

1. **Major — CLASS: closed class reopened, flag integrity.**  
   **Sections:** §§3.1–3.3, §9 production-scope controls, §10.5.

   **Scenario:** Open the patched raw/preview page without `LiveOutputHost`, on an unqualified engine—for example, as a manually configured CEF browser source. Page code assigns:

   ```js
   window.__obedPlacement = "snap";
   ```

   There is no host-installed property to reject this assignment. The take checks only the resulting string and can use Chrome’s snapped rule on CEF’s unsnapped video.

   The extracted-method reproduction returned:

   | Setup | Snapshots taken | Holders attached |
   |---|---:|---:|
   | No host initialization, property absent | 0 | 0 |
   | No host initialization, page assigns `"snap"` | 1 | 1 |

   The existing tamper checks all start **after** installing the protected channel. The production raw/preview controls test absence, not forgery.

   **Exact fix wording:**  
   > “Production raw/preview rendering must have no executable movie-freeze entry point; retain its cross-fade and cut changes. Enable that entry point only in the host rendering variant with the first-run channel installed. Update rendering parity assertions and pins accordingly. Add production raw/preview controls that assign `snap` and install a non-configurable getter returning `snap`; both must publish no holder without privileged host setup.”

2. **Major — CLASS: edge case, grant lifecycle/flag integrity.**  
   **Sections:** §3.3 context-binding round trip, §§9 and 10.5.

   **Scenario:** The documented round trip grants `snap` **before** checking conditions (a)–(c). If implemented as separate context-bound evaluations, an attached CEF document temporarily holds a real `snap` grant. An automatic transition scheduled between the grant and revoke can freeze using the wrong rule. Delaying or losing the revoke extends that interval.

   `uniqueContextId` prevents installing into the wrong document; it does not prevent page execution between CDP requests. The Node round trip passes without exercising this interleaving.

   **Exact fix wording:**  
   > “Evaluate eligibility before any operation that exposes `snap`. Ineligible documents remain invalid throughout channel verification. For eligible documents, perform grant/read/revoke/read in one synchronous, context-bound evaluation, with revocation in `finally`; only subsequently commit eligibility. Add a control that schedules an automatic transition between diagnostic CDP requests on an attached CEF document and requires no holder.”

3. **Medium — CLASS: edge case, lifecycle.**  
   **Sections:** §3.3 “Dropped” and “Residual”; §13 host-grant risk; §14 rev-17 rationale.

   **Scenario:** `observe()` reads GPU compositing as enabled. Chrome subsequently falls back to software while the document and CDP connection survive. Before the next observation, an automatic transition—or an already dispatched advance—reaches D4. The grant still reads `snap`.

   This is not necessarily stopped by the colour-tuple guard: the supplied Q0b evidence records tagged H.264 as `bt709/bt709/bt709/false` on both GPU and software paths. Thus an otherwise admissible movie can freeze on the explicitly unqualified software path.

   **CDP disconnection is unnecessary.** Also, without a lease, staleness lasts until successful observation and revocation, not for a defined maximum interval.

   **Exact fix wording:**  
   > “Version and launch ownership are immutable for the process; GPU eligibility is sampled and mutable. Any transition after an unobserved GPU fallback and before successful revocation may use a stale grant, whether CDP is connected or disconnected. Without expiry this interval has no guaranteed bound. Add connected and disconnected fallback controls, using tagged H.264 that retains the qualified tuple, and verify revocation at the next successful observation. Do not describe this as unconditional software-path exclusion or claim that both residual conditions must hold.”

   A lease could bound the stale interval; it would not eliminate the sampling race. Moving probe machinery to §13.1 does not move this current-grant limitation.

**Planner’s re-check list**

| Item | Judgment |
|---|---|
| **a. Lease/keep-alive removal** | The stated residual is too narrow. Finding 3 applies even with CDP connected. Immutable version alone does not justify an indefinitely valid GPU-dependent grant. |
| **b. GPU requirement** | Correct admission input: `SystemInfo.getInfo` → `gpu.featureStatus.gpu_compositing`, exactly `"enabled"`; missing, malformed or failed results must deny/revoke. Detection needs the browser-target connection described below. Later changes have finding 3’s sampling window. |
| **c. Major 154 versus exact build** | Keep the stated major-154 default. Evidence measures **154.0.8037.59**, not every possible 154 build, but I have no concrete within-major counterexample and therefore no new finding demanding an exact-build pin. Preserve the full product string in qualification records. |
| **d. `cef-skip` / DX-2 sessions** | Correct: §9.2 explicitly makes any bound CEF holder a FAIL and removes media/tone/`m-snap` sessions. Findings 1–2 are concrete ways to violate that requirement. Also reconcile stale §10.6, which still says the session list includes `m-snap`, with §9.2 and W3. |
| **e. Integer `left`/`top`** | Correct narrowing. It adds a rejection condition without removing another guard or changing the snapped draw. No widening scenario found. |
| **f. DX-3 split** | Correct. §9.3 checks the freeze on the HDMI host with `grant: snap`, and cross-fade plus expected movie jump in OBS. No scope finding. |
| **g. Context-bound commit versus current plumbing** | **Not implementable using the existing plumbing unchanged.** W6 must explicitly include the extensions below. |
| **h. Defaults** | Major 154 only is a coherent default. Automatic re-grant after renderer crash **and a fresh reload** is coherent provided it repeats eligibility and the document’s own channel verification; surviving process ownership alone is insufficient. Never carry the old grant or context identity forward. |

For **g**, today’s [`ChromeCdp.call()` and event router](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/live_host.py:595) receive events only while awaiting responses and discard execution-context lifecycle events. `evaluate()` has no context argument. Calling back into `call()` directly from the router would also re-enter its non-reentrant lock.

The transport connects to a **page** target, whereas Chromium restricts `SystemInfo.getInfo` to the **browser** target. The existing [`DevToolsEndpoint`](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/src/obed_edom/devtools_port.py:18) already retains that browser path, so this is bounded additional work. [Chromium SystemInfo implementation](https://raw.githubusercontent.com/chromium/chromium/main/content/browser/devtools/protocol/system_info_handler.cc)

**Exact W6 addition:**

> “Retain the verified browser endpoint and add browser-target calls for SystemInfo. Track creation, destruction and clearing of execution contexts, selecting the program main frame’s default context and retaining its `uniqueId`. Queue lifecycle work without issuing nested CDP calls under the receive lock. Send grants and revocations with `uniqueContextId`; never fall back to untargeted evaluation. Clear eligibility on context loss and test event/response interleavings, renderer crash/reload and browser-target failure through the real transport.”

The protocol supports that unique-context design; the missing piece is local transport handling. [CDP Runtime definitions](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/pdl/js_protocol.pdl)

The closing class sweep therefore leaves **flag integrity and lifecycle open**, with corresponding acceptance gaps identified above. The scope decisions themselves are resolved, and the moved CEF classifier/isolation/geometry work remains properly carried by §13.1.
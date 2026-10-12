**CHANGES REQUIRED**

I re-ran the 226 supplied Node rows and targeted counterexamples against both players. Outcomes match across players. These establish method behavior; rev-11 browser engagement remains unmeasured.

Closure assessment for [rev 11](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md):

| r8 finding | Status | Plan-section evidence |
|---|---|---|
| 1. Hidden ancestor effects | **NOT CLOSED** | §§3.1–3.2 move effects before the visibility shortcut, fixing the ordinary `div` case. The earlier tag-name exemption still bypasses those checks; finding 1 below. |
| 2. Invalid clipping witnesses / top layer | **NOT CLOSED** | HTML-only witnesses, document-level top-layer refusal, and iframe/SVG boundaries are specified in §§3.1–3.2; browser controls are scheduled in §9.0. Shadow-tree top-layer content escapes the scan; finding 2. |
| 3. Unexamined backing edges | **CLOSED** | §§3.1–3.2 read the entire backing before foreground redraw; §10 rejects transparent first/last pixels, rows and columns. The separate geometry defect below undermines the claimed 1:1 mapping. |
| 4. Geometry beyond the demonstrated model | **NOT CLOSED** | Transform, DPR and origin restrictions are explicit in §3.2, but the bytes do not enforce its assertion `kx = ky = 1`; finding 3. |
| 5. Permissive default while decision remained open | **CLOSED** | §§3.2, 9.1, 12.12 and 13 consistently choose skipping unsupported DPR/scales. DSF 2’s flat-area maximum of 5 is retained. The remaining guard defect belongs to finding 4’s geometry class. |
| 6. Foreground over-masking | **CLOSED** | §9.1 specifies independent inventory, missed/excess support checks, twins per reference geometry, and detection of a shifted holder under the production mask. §10 supplies malformed-mask controls. |
| 7. Paused references versus temporal coverage | **CLOSED** | §9.1 defines a separate reference profile, animation/opacity checks, stable pairs and distinct endpoint images; timed arms retain temporal qualification. §§9–10 include stale-reference and shifted-`perfect` controls. |
| 8. Hide/show capture qualification | **CLOSED** | §§9–9.1 require hidden-interval evidence and six distinct timestamped frames **after show**, separately for alpha/screen, with dropped-action and malformed-capture controls. |
| 9. Crop and worst-case evidence wording | **NOT CLOSED — editorial remainder** | §§8.2 and 9.0 correctly describe the missing crop experiment and remeasurement. §0 and §14’s T1 row still say “source crop measured unnecessary.” |

The closing sweep found three concrete false admissions:

1. **Major — CLASS: exterior-proof escapes — §§3.1–3.2, 10. Tag-name exemptions bypass the repaired paint checks.**

   Give an exterior `script[type="application/json"]` `display:block`, a border box at `[-60,800,40,30]`, and long, non-wrapping visible text extending across the movie. `pc()` returns true solely because it is a `SCRIPT`; the later rectangle test discards its off-stage box. The exact-method harness admits **one holder on both players**; the equivalent `DIV` rejects.

   The same shortcut preserves r8’s ancestor-effect escape: a rendered, visibility-hidden `HEAD` containing a visible off-stage clipper can project its contents into the stage with `drop-shadow(300px 0 0 red)`. The modeled case also admits on both players. These tags are hidden by default stylesheet rules, not an unconditional rendering prohibition. [HTML rendering defaults](https://html.spec.whatwg.org/multipage/rendering.html#hidden-elements)

   **Exact fix wording:** “Remove unconditional tag-name admission from `pc`. Establish non-rendering from actual rendering state; otherwise apply the same descendant-effect, generated-content and paint-family checks. Add rendered-script overflow and rendered-hidden-head/filter rejection controls, retaining default `display:none` metadata as positives.”

2. **Major — CLASS: exterior-proof escapes — §§3.1–3.2, 13. Document queries miss shadow-tree paint and top-layer membership.**

   Append a transparent, off-stage HTML `div` with an open shadow root. Inside that root, open an off-screen modal dialog with a visibly coloured `::backdrop`. The backdrop covers the stage, while `document.querySelector(":modal,…")` finds no dialog and `document.getElementsByTagName("*")` visits only the harmless host. Its rectangle does not meet the movie. The take therefore admits.

   This is a static DOM/API counterexample, **not a browser-run result**. Shadow descendants are outside the document’s ordinary descendant enumeration, while top-layer rendering escapes ancestor clipping. [DOM enumeration](https://dom.spec.whatwg.org/#concept-getelementsbytagname), [shadow-tree boundaries](https://www.w3.org/TR/css-scoping-1/#shadow-trees), [top-layer rendering](https://drafts.csswg.org/css-position-4/#top-layer)

   **Exact fix wording:** “Treat author shadow trees as unsupported paint boundaries. Reject detected shadow roots before paint shortcuts. Establish an explicit, verified no-closed-author-shadow-root invariant for supported pages, or track those roots before creation; `shadowRoot === null` is not proof of absence. Add shadow-dialog/backdrop and shadow fixed-overlay rejection controls, with an ordinary-page admission control.”

3. **Major — CLASS: geometry admitted outside the demonstrated model — §§3.1–3.2, 8.3, 10. Identity transforms do not establish unit coordinate mapping.**

   Keep DPR 1, integer origin and identity transforms. Set the outgoing live base-layer box to **960×1080** in a **1920×1080** slide, with overflow visible and the movie unchanged.

   The exact methods admit on both players:

   | | Live movie / backing | Attached holder |
   |---|---:|---:|
   | Horizontal origin | 109 | 218 |
   | Width | 952 | 1,904 |

   `kx = slideWidth / R.width = 2`. The backing is fully scanned and opaque, yet D3 attaches it at twice its width and the wrong position. This contradicts §3.2’s asserted device-pixel mapping. §8.3’s retained `baseRectUnequal` admission confirms that mismatched base extents are deliberately still accepted.

   **Exact fix wording:** “Under the provisional geometry guard, require `kx === 1 && ky === 1` in addition to DPR, transform and origin checks. Reject mismatched live base-layer extents. Add half-width and fractional-height base-rectangle rejection controls and a matching full-slide positive; permit other mappings only after demonstrating their D4-to-D3 placement and raster equivalence.”

For retained **r8-9, Minor — CLASS: evidence wording**, replace “source crop measured unnecessary” in §0 and §14 with: **“No smaller source crop exists on the measured full-content regions; no crop A/B has run. The clipped diagnostic remains required in Q0b-bis.”**

I found no additional concrete false pass in the revised capture contracts, or independent unexamined-backing-pixel admission beyond the geometry issue above. Their scheduled controls still need execution.

The four provisional defaults are sound:

- **Skip hi-DPI/scaled geometry:** Accept. This implements decision 12’s reversal without accepting the measured residuals.
- **Skip fractional letterbox origins:** Accept. It preserves the demonstrated pixel phase.
- **Real-page engagement first in Q0b-bis; miss means re-plan:** Accept. Make it explicitly first: §9.0 currently lists it as item 3. Node success does not substitute for this check.
- **View transitions as a residual only:** Accept within the stated player/host scope, where neither starts one. §13 should remain explicit that active view transitions are outside the gate’s guarantee.
---
name: Dashboard React/DOM test harness
overview: "Owner approved 2026-09-12. Decisions: Vitest + jsdom + Testing Library; tests live in `dashboard/tests-ui/`; tests-only PRs do not rebuild `dist`; no MapsTab refactor in PR 1. Three PRs: PR 1 builds the harness plus three seed regression tests (conflict-freeze, thumb-token, rename-unsaved), each of which must be shown red when its guard is reverted; PR 2 adds thumbnail + save-status coverage; PR 3 adds component + preview-sequence coverage."
todos:
  - id: pr1-harness
    content: "Harness + 3 seed tests: conflict-freeze, thumb-token, rename-unsaved; each must be shown red when its guard is reverted."
    status: done
  - id: pr2-thumb-status
    content: "Thumbnail + save-status coverage: stale-retry, reconcile, save-status pill label sequence."
    status: pending
  - id: pr3-components-preview
    content: "Component + preview-sequence coverage: JobName double-submit, export-destination freeze, isolate hop preview viewLog ordering."
    status: pending
isProject: false
---

# Dashboard React test harness — plan

## 1. Stack choice

**Chosen: Vitest 2 + jsdom + @testing-library/react + @testing-library/user-event + @testing-library/jest-dom.**

Justification against the repo's "don't reinvent existing tools" rule:

- The dashboard is already Vite 5 + `@vitejs/plugin-react` + TS 5.6. Vitest consumes `vite.config.ts` verbatim — JSX transform, path handling and ESM (`"type": "module"`) all work with zero extra config. Jest would need babel/ts-jest + ESM interop + a second module pipeline: strictly more machinery.
- `vi.mock` with hoisting and `vi.useFakeTimers()` (which patches `window.setTimeout` — exactly what MapsTab's 500 ms save and 750 ms thumb debounces use) come in-box. Under `node --test` we'd hand-roll both.
- jsdom over happy-dom: MapsTab leans on `pointer` events, `ResizeObserver`, `URL.createObjectURL`, `sessionStorage`/`localStorage` and `aria-live`. jsdom's coverage is the more boring, better-documented one; happy-dom's speed edge is irrelevant at this suite size. (Both need a `URL.createObjectURL` stub; jsdom also needs `ResizeObserver` — two lines in setup.)
- Rejected: Playwright component testing (a browser download and a second runner for something that is really unit-level), and extending `node --test` with jsdom by hand (we'd reimplement module mocking, fake timers and act() batching — the anti-pattern the rules warn about).

Coexistence: Vitest only picks up `tests-ui/**/*.test.tsx`; `test:maps` keeps globbing `tests/*.test.cjs`. The two never see each other's files. The existing `CODEX_NODE`/`tsc --module commonjs` idiom stays untouched for pure-module tests — new pure-logic tests (e.g. `commit.ts`) should still go there; only DOM/React tests go to Vitest.

New devDependencies (5): `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`.

## 2. File layout

```
dashboard/vitest.config.ts          # test: { environment: 'jsdom', setupFiles, include: ['tests-ui/**/*.test.tsx'] }
dashboard/tests-ui/setup.ts         # jest-dom, ResizeObserver/createObjectURL/matchMedia stubs, sessionStorage reset
dashboard/tests-ui/fakes/mapView.tsx    # MapView mock + handle spy registry
dashboard/tests-ui/fakes/mapsApi.ts     # scriptable api.ts mock
dashboard/tests-ui/fakes/doc.ts         # MapsDocument / Job builders
dashboard/tests-ui/renderMapsTab.tsx    # render helper: RunNavContext provider + seeded job + timers
dashboard/tests-ui/*.test.tsx
```

`tests-ui/` (sibling of `tests/`) beats `src/**/__tests__`: it keeps test-only code out of the `tsc --noEmit && vite build` surface with a single `tsconfig` exclude, and mirrors the existing top-level `tests/` convention.

Test files use a `.ui.test.tsx` suffix (e.g. `conflict-freeze.ui.test.tsx`) — several basenames collide with existing `tests/*.test.cjs` files; the CJS suite tests predicates, the `tests-ui` suite tests wiring.

## 3. Fakes

**MapView** (`vi.mock("../src/maps/MapView")`). A `forwardRef` component that renders `<div data-testid="mapview" />`, records the props it was given (`previewing`, `isolate`, `camera`, `styleId`, `crop` — these are what the preview-sequence tests assert on), publishes every render's props into an ordered `viewLog` array, and installs a handle via `useImperativeHandle`:

- `jumpTo`, `easeTo`, `flyTo`, `animateHop`, `stop` — `vi.fn()` returning resolved promises, each appending to `viewLog` so a test can assert the *sequence* (source view during fly → plain landing → crossfade).
- `getCamera` / `getCgCamera` — return a settable fake camera; `commitCamera(...)` from the fake is how a test simulates a gesture.
- `captureBlob` / `capturePreviewBlob` — return a stub `Blob` (jsdom has `Blob`), counted.
- `waitUntilIdle` — a *controllable* deferred: default auto-resolve, but `mapFake.holdIdle()` lets a test park `captureThumb` mid-flight and assert the token/gate behaviour.
- `resize` — `vi.fn()`.
- Callback triggers: `mapFake.emit.cameraCommit(cam)`, `.objectMove(id, lat, lon)`, `.objectCommit()`, `.cgShift(dx)`, `.previewAbort()` — each calls the latest prop callback inside `act()`.

Mocking the module (rather than adding an injectable-MapView prop) also keeps `maplibre-gl` from ever loading in jsdom, which is the real blocker.

**stampOsm** (`vi.mock("../src/maps/stampOsm")`) — identity passthrough. It is canvas-based and jsdom has no canvas; this is unavoidable and harmless (its logic is separately testable).

**api.ts** — `vi.mock("../src/api")` with a scriptable module rather than a fetch mock. Reason: `api.ts` is a thin fetch wrapper already covered by the Python API tests; mocking fetch would force us to re-encode its URL/JSON contract in the harness. The fake exports real `MapsStateConflictError` / `MapsStaleThumbnailError` / `MapsSaveConflictError` classes (re-exported from the real modules via `importActual`, so `instanceof` still works — this matters, `captureThumb` branches on both), plus a controller:

```
api.script.saveMapsState.conflictOnce({ document, stateRevision })
api.script.postMapsPng.staleOnce({ stateRevision })  // throws MapsStaleThumbnailError
api.script.postMapsPng.calls                          // kind/slideId/audience/revision log
api.script.renameJob.failOnce(err) / .calls
api.script.getJob.resolve(job)
```

`saveMapsState` by default bumps `stateRevision` and echoes the doc, so the happy path needs no scripting.

**Storage** — `setup.ts` installs a fresh in-memory `sessionStorage`/`localStorage` per test (jsdom's are shared across a file). Tests that care about `useSessionToggle`/`useSessionPath` seed keys before render (`obed-edom.maps.exportDir`, `MAPS_SIDE_PANELS_KEY`, `MAPS_INSPECTOR_KEY`).

**Timers** — `vi.useFakeTimers()` in each test file's `beforeEach` (not the render helper: fake timers must be installed before any module-scope code runs, which the helper can't guarantee), with helpers `await tick(500)` (save debounce) and `await tick(750)` (thumb debounce) that wrap `vi.advanceTimersByTimeAsync` in `act()`. Async/timer interleaving is the main authoring hazard here: `captureThumb` awaits `waitUntilIdle` then `captureBlob` then `postMapsPng`, so `advanceTimersByTimeAsync` (not the sync variant) plus explicit `await flushMicrotasks()` is mandatory.

**Render helper** — `renderMapsTab({ doc, job })` wraps `<MapsTab />` in `RunNavContext.Provider` with `openRun = { feature: "maps", jobId }` and pre-scripts `getJob`. This is why no MapsTab refactor is required.

## 4. Refactors needed — deliberately none in the first PR

Everything MapsTab needs is already injectable-by-mock:
- job source: context + `getJob` — controllable;
- save queue: `useRef(new MapsSaveQueue(...))`, per instance — no cross-test leak;
- MapView, stampOsm, api: module imports — `vi.mock`.

Two module-level caches *do* leak between tests and are handled via `vi.mock` in `renderMapsTab.tsx` rather than refactored: `loadAdmin0()` in `dashboard/src/maps/overlays.ts` (stubbed to resolve immediately) and `defaultExportDirRequest`/`defaultExportDirVersion` in `dashboard/src/prefs.ts` (the module is partially mocked with `importOriginal`, replacing only `useDefaultExportDir` with a stable stub so the singleton is never touched). If a third such singleton turns up, prefer the same partial-mock approach, or `vi.resetModules()`, over touching product code.

The only product change I'd consider later, and only if tests get ugly: add `data-testid` to the save-status pill and the conflict banner. Prefer querying by the existing `aria-live` text and button labels ("Reload latest", "Keep my changes") first — free, and it tests what the operator sees.

## 5. First regression tests, each tied to a past finding

**PR 1 — harness + 3 seed tests** (the three with the widest blast radius and the simplest fakes):

1. `conflict-freeze.test.tsx` — *conflict freeze does not edit the doc*. Script `saveMapsState` to conflict; assert the banner appears, then `mapFake.emit.cameraCommit(newCam)` and an object move leave `docRef`'s rendered camera unchanged (assert via the `camera` prop the MapView fake received), that `postMapsPng` is never called while frozen, and that "Reload latest" / "Keep my changes" each clear the banner and restore editing. Covers `applyLocalDoc`'s early return; the zero-POST assertion is not pinned to `captureThumb`'s own `frozen` guard in `shouldPublishThumb` — reverting `frozen: !!saveConflictRef.current` to `frozen: false` there still leaves the test green, because the token bump and the frozen `applyLocalDoc`/doc-unchanged path independently stop the capture. Pinning that specific guard is PR 2 work (see below).
2. `thumb-token.test.tsx` — *token bump on conflict*. Hold `waitUntilIdle`, fire a conflict mid-capture, release; assert no `postMapsPng`. Second case: token invalidation — `selectSlide` awaits the in-flight `captureThumb(prev)` before moving `activeRef`, so both captures target the same slide; hold idle, select the same slide again, release, assert only the newer capture's token publishes. PR 2 adds a `sameView` case: flip audience via `selectSlide(id, { audience: "cg" })` mid-capture and assert no POST for the stale view.
3. `rename-unsaved.test.tsx` — *rename persists first and preserves the doc*. Make an edit, click the JobName pencil, submit; assert `saveMapsState` is called **before** `renameJob`, and that after `mergeServerMeta` the local slides survive (the server echo must not clobber them).

Each of these three must be verified red when its corresponding guard is reverted (the freeze early-return, the `sameView`/token gate, the save-before-rename ordering), per owner instruction.

**PR 2 — thumbnail + save-status**

4. `thumb-stale-retry.test.tsx` — `postMapsPng` throws `MapsStaleThumbnailError`; assert exactly one retry, only after a successful `flush()`, and only when `saveQueue.revision >= err.stateRevision`; a second case where the flush rejects asserts zero retries; a third where the queue is behind asserts zero retries.
5. `thumb-reconcile.test.tsx` — after a successful thumb POST, `reconcileServerJob` runs; assert navigating slides mid-flight does not reconcile into the wrong slide (`shouldReconcileThumb` `sameJob` gate).
6. `save-status-pill.test.tsx` — assert the label sequence `Saved → Unsaved → Saving… → Saved` across a debounced edit, and `→ Paused` on conflict, read through the `aria-live` node.
7. Add a case (or extend `conflict-freeze.test.tsx`) that pins `captureThumb`'s own `frozen: !!saveConflictRef.current` input to `shouldPublishThumb` — a conflict that starts *after* a capture is already past its own freeze checks but before `gate()` runs, isolated from the token bump and from `applyLocalDoc`'s doc-unchanged effect.

**PR 3 — components + preview**

7. `job-name-double-submit.test.tsx` — Enter then blur on the JobName input fires `onRename` once (`savingRef` guard in `dashboard/src/components/JobName.tsx`); plus a rejecting `onRename` keeps the editor open and shows the error.
8. `export-destination-freeze.test.tsx` — `disabled` renders the locked copy and no "Export to…" button (ResizeTab finding); mount within ResizeTab if cheap, else component-level.
9. `isolate-hop-preview.test.tsx` — drive a `movie` link and assert the exact `viewLog` order: source view applied before `animateHop`, `plainIsolateTarget` landing next, crossfade last; plus an abort mid-hop (`previewRun` bump) leaves no trailing view applied.

## 6. Scripts & CI

- `"typecheck:ui": "tsc -p tests-ui --noEmit"`, `"test:ui": "npm run typecheck:ui && vitest run"`, and `"test:ui:watch": "vitest"` in `dashboard/package.json`.
- There is **no `.github/workflows`** in this repo — `test:maps` is invoked only from the agent plans and `.agents/skills/obed-edom/SKILL.md`. So "CI wiring" here means: add `npm run test:ui` next to `npm run test:maps` in SKILL.md's dashboard command block and in the plan files' command notes, with the same bundled-Node PATH prefix (`PATH=/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`). If a workflow is added later, both scripts go in one `npm test` aggregate.

## 7. Owner decision needed

The repo commits `dashboard/dist`. Adding five devDependencies changes `package-lock.json` but not `dist`; confirmed the first PR should **not** rebuild/commit `dist` (test-only change). Also confirmed `tests-ui/` over `src/**/__tests__` — keeps the build surface clean.

## Decisions 2026-09-12

Owner: harness approved. Orchestrator: tests-only PR, no dist rebuild; tests in dashboard/tests-ui/.

## Decisions

PR 1 shipped: test files use a `.ui.test.tsx` suffix (basename collisions with `tests/*.test.cjs`); `vi.useFakeTimers()` lives in each file's `beforeEach`, not the render helper; `sameView` token-invalidation coverage deferred to PR 2.

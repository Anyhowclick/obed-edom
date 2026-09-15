---
name: Dashboard React/DOM test harness — remaining coverage
overview: >-
  The Vitest/jsdom/Testing Library harness shipped in PR #99 and is established. This plan now
  tracks only missing regression coverage and the few conventions that keep the harness honest.
todos:
  - id: thumbnail-regressions
    content: >-
      Add stale retry, reconcile-to-the-correct-view, sameView invalidation, and a mutation test
      that specifically pins the frozen gate after capture has started.
    status: pending
  - id: component-regressions
    content: >-
      Cover JobName Enter+blur double submission and rejection, plus ExportDestinationRow's
      disabled/frozen state.
    status: pending
  - id: preview-sequence
    content: >-
      Drive a movie isolate hop through the MapView fake and assert source → animation → plain
      landing → crossfade order, including an aborted run with no trailing view application.
    status: pending
---

# Dashboard React/DOM test harness — remaining coverage

## Shipped foundation

PR #99 established Vitest 2, jsdom, Testing Library, `dashboard/tests-ui/`, typed MapView and API
fakes, and `npm run test:ui`. The seed conflict-freeze, thumbnail-token, and rename-unsaved tests
were each proven red when their relevant guard was reverted. Later work added save-status,
artifact/result views, manual entries, Maps controls, and other feature coverage.

Do not redesign or replace the harness. Pure logic continues to use `dashboard/tests/*.test.cjs`;
React/DOM wiring belongs in `dashboard/tests-ui/*.ui.test.tsx`.

## Remaining tests

### Thumbnail lifecycle

- A `MapsStaleThumbnailError` retries exactly once, after a successful save flush and only when
  the queue revision has reached the rejected revision. A failed flush or lagging queue does not
  retry.
- A successful thumbnail response reconciles only into the same job/view that initiated it.
- Switching audience during capture invalidates `sameView` and prevents the stale publish.
- Add a mutation-resistant case that reaches the capture gate after a conflict begins, without
  relying on the independent token bump or document-freeze guard.

### Components

- JobName Enter followed by blur invokes rename once. A rejected rename keeps editing open and
  shows the error.
- A disabled ExportDestinationRow renders locked copy and no chooser action.

### Preview sequencing

Use the existing ordered `viewLog` in the MapView fake. For a movie isolate hop, assert source
view, `animateHop`, plain isolate landing, then crossfade. Bumping the preview run during the hop
must leave no later view applied.

## Harness rules

- Use role/label queries for operator-visible behavior; add test ids only when no stable accessible
  query exists.
- Install fake timers before rendering and use async timer advancement for the save/thumbnail
  debounce chains.
- Keep MapLibre, canvas work, and preference singletons behind the existing fakes. Do not refactor
  product code merely to make these tests injectable.
- Each regression test must have an independently reversible guard or behavior that makes it fail;
  avoid positive controls that share the implementation model being tested.
- Test-only changes do not rebuild `dashboard/dist`. Any `dashboard/src/**` change does.

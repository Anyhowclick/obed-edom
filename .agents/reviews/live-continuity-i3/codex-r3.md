- BLOCKER: None.
- MAJOR: None.
- MINOR: None.

The `nearZero || nearStageOrigin` check at `src/obed_edom/live_continuity_js.py:874` correctly handles both observed detach signatures while preserving null-map fail-closed behavior. No new failure scenario beyond the accepted top-left ambiguity.

Tests at `tests/test_live_continuity_js.py:594` and `:627` meaningfully exercise the real stash/remount path, including valid-size `(0,0)`, letterboxed stage origin, identity origin, and off-origin negative control. All focused assertions passed via direct invocation; standard pytest could not initialize because the read-only environment has no writable temporary directory.

Verdict: PASS
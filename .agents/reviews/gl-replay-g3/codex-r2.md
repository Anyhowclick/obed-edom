# GL-replay G3+G4 — Codex (GPT-5.6 Sol) review, round 2 (fb6fa2bf, 2026-09-23)

## Finding

- **G34-04 residual — MINOR — EDGE CASE**  
  **Evidence:** `restorePoster()` marks success immediately after `texImage2D` returns, without checking context loss or `getError()` ([live_gl_replay_js.py:399](<src/obed_edom/live_gl_replay_js.py:399>), [live_gl_replay_js.py:412](<src/obed_edom/live_gl_replay_js.py:412>)). That result is emitted as `posterRestored` ([live_gl_replay_js.py:887](<src/obed_edom/live_gl_replay_js.py:887>), [live_gl_replay_js.py:914](<src/obed_edom/live_gl_replay_js.py:914>)). The test covers only an upload that throws ([test_live_gl_replay_js.py:2650](<tests/test_live_gl_replay_js.py:2650>)).
  
  **Failure scenario:** After video has replaced the poster texture, the restore upload returns normally but raises `INVALID_OPERATION`. WebGL leaves the texture unchanged, yet the stand-down event reports `posterRestored: true`; a subsequent cleanup replay can therefore still render the movie frame.
  
  **Exact fix:** “After the poster `texImage2D` returns, set `ok` only when the context is not lost and `g.getError() === g.NO_ERROR`; leave it false on a GL error, exception, or cleanup failure. Add a fake-GL restore mode that returns normally while setting `INVALID_OPERATION`, and assert `posterRestored === false` and that the poster texture was not restored.”

## G34-01..05 assessment

- **G34-01: correct and complete.** The facade receives the carried rect, and its observer permits swapping only under the matched authored poster parent. `beginMove(stub)` is correct: it makes `stash()` ignore the intentional removal, preventing the media-less facade from being pooled and remounted ([live_continuity_js.py:722](<src/obed_edom/live_continuity_js.py:722>), [live_continuity_js.py:1544](<src/obed_edom/live_continuity_js.py:1544>)). No regression found.

- **G34-02: correct and complete.** GL bookkeeping and authored-rect deletion are wholly guarded by `if (GL)` ([live_continuity_js.py:446](<src/obed_edom/live_continuity_js.py:446>)). Default and non-GL-retire paths remain free of GL expandos.

- **G34-03: correct and complete.** Selection requires an exact `atScene − 1` stamp; both capture paths stamp the scene, and asset changes clear both fields ([live_continuity_js.py:592](<src/obed_edom/live_continuity_js.py:592>), [live_continuity_js.py:770](<src/obed_edom/live_continuity_js.py:770>), [live_continuity_js.py:1611](<src/obed_edom/live_continuity_js.py:1611>)).

- **G34-04: partially complete.** Snapshot readback, exception-safe cleanup, and distinct WebGL2 read/draw framebuffer restoration are correct. The `posterRestored` tri-state—`true`, `false`, or `null` when unavailable/lost—is otherwise coherent. The silent-upload-error finding above remains.

- **G34-05: correct and complete.** The delimiter check precedes snapshotting and uploading ([live_gl_replay_js.py:437](<src/obed_edom/live_gl_replay_js.py:437>)). WebGL2 exposes the same `clearColor`/`clear` operations. Players using a different delimiter, such as `clearBuffer*` or a one-time `clearColor`, intentionally fail closed without an undelimited upload; the verified exported player remains supported.

No separate new defect or standards violation was found.

**Counts:** BLOCKER 0 · MAJOR 0 · MINOR 1 · NIT 0; NEW CLASS 0 · CLOSED CLASS 0 · EDGE CASE 1.

**Verdict:** Four round-one classes—G34-01, G34-02, G34-03, and G34-05—are closed without identified regressions. G34-04’s principal snapshot, cleanup, and WebGL2 failures are fixed, but the class is not fully closed because a non-throwing WebGL restore error is still misreported as successful.
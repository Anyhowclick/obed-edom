# Critique r2: Opus 5.5 high (plan r2)

Verdict: **NOT READY**, on text only. The design was confirmed and no new correctness issue was found. All findings
are folded into plan r3, a clean self-contained rewrite. The coordinator checked the folds (the critic said no third
round is needed if folded as given).

1. **MEDIUM:** the §5 A5 block still had the venv-wiping 3.10 command, `GATE_JOBS=1` ×2 and an unpinned worktree,
   and §0.4 had no concrete command. → r3 §4 A5 is replaced verbatim with the critic's pinned-worktree procedure.
2. **MEDIUM:** §3/§4 still described the r1 design (`families`, dedup/validation, three test groups), and §0.3 left
   the Node test and the snapshot field "optional". → r3 §2.3, §2.4 and §3 rewritten; both are included.
3. **MEDIUM:** there was no channel for the A2/A4 readiness evidence. → The snapshot field is mandatory: logged once
   to the host session log and read via `player.output["logPath"]`.
4. **LOW:** §6 completion, risk 1, §2.3 and the WebM/smoke section contradicted §0. → Removed in r3.
5. **LOW:** the `:372-373` reference was stale (it is `stageMap`). → Fixed to `:766-769`.
6. **LOW:** `first_h264_movie` must skip `None` paths. → Done in r3 §2.3.
7. **LOW:** test hermeticity and reuse: `delenv` in `host_with_continuity`, parametrize the GL-replay invalid-env
   test, extend `test_continuity_off_env_installs_nothing`, forward in `served_html`. → Done in r3 §3.
8. **LOW:** fresh-worktree `uv sync` plus fixture symlinks before A1/A5. → Done in r3 §4.

Nit: capturing `HTMLMediaElement.prototype.load` defends against nothing today; kept because it is harmless.

# UH-1 rendered F2 instrument

Run from any directory (one foreground process, three serially owned headless Chromes, continuity and GL replay off):

```sh
/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e/.venv/bin/python /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-inspiring-feynman-06914e/29684ee7-fbfe-46e5-9097-279cbfa06ec2/scratchpad/sol/uh1/uh1_f2.py
```

Offline preparation and pin validation only:

```sh
/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e/.venv/bin/python /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-inspiring-feynman-06914e/29684ee7-fbfe-46e5-9097-279cbfa06ec2/scratchpad/sol/uh1/uh1_f2.py --dry-run
```

Each invocation writes only below `oroot/.html-preview/uh1-runs/<stamp>/`. A browser run retains each prepared export, raw per-run JSON, timestamped page captures, target hold crops, and the aggregate `result.json`. Re-score retained evidence with `--score oroot/.html-preview/uh1-runs/<stamp>`.

To diagnose player-document selection without running the gate, load one arm and print its scene, location, frame tree, logger state, and captured page exceptions:

```sh
/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e/.venv/bin/python /private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-inspiring-feynman-06914e/29684ee7-fbfe-46e5-9097-279cbfa06ec2/scratchpad/sol/uh1/uh1_f2.py --probe-page base-live
```

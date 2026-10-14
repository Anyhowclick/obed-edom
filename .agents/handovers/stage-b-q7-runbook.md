# Stage B Q7 runbook (owner session, before Q2–Q6)

Owner decisions 2026-10-14: Q7 first, then the rest; managed OBS uses the Q6 qualification constructor flags
(`mm_feed="on"`, and `mm_feed="off"` + `mm_feed_qualify_once=True`), product defaults unchanged until Q6 passes.
Code under test: detached worktree `.claude/worktrees/stage-b-q7` at `c104d5a3`. One heavy job machine-wide.

## 0. Prepare the edited Alpha (owner)
The export must land in the Q7 worktree, never main `output/` (main's real-export censuses scan it).
```
cd /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/stage-b-q7 && PYTHONPATH=src /Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python -m obed_edom dashboard --no-browser
```
Prepare `~/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key` (the 18:19 slide-11 edit). Stage T repairs it at prepare.
Coordinator then derives its plan (expect fed bridges @10/@12/@14, two `retire ends` at player 8→9, 9→None terminal)
and builds `Continuity/q7-fixtures/Alpha/{html-player,html-unmodified}`.

## 1. Managed OBS, Keyer, projector (owner watches the program projector)
Per deck (D7, D7s, Alpha), two sessions each: `feed` (continuous) and `feed-off` (exact-frame one-shot):
```
scripts/managed_obs_qualify.py --arm feed --launch projector --fixture "<Continuity>/q7-fixtures/<deck>" --out <scratch>
```
Look for: tags/divider/labels on top during the move and once settled; the movie keeps playing through the move (feed)
or stops on the picture showing at move start, travels with the move and resumes without a restart (feed-off); D7s
sliver drawn as authored (B over A); a small midtone brightness step at departure/settle is the known tone curve.

## 2. External attach exact-frame arms (Alpha + D7)
Probe `--mm-feed off --feed-dwell 5 --skip-arms A,B,C,V,Voff` (attach Chrome). Same look-fors as feed-off.

## 3. D1 spot + press past end
In the Q7 dashboard: present D1 (unchanged behaviour), then Alpha through to the end and press past the end once.

## After Q7
Measure `holdFrame` exactness in the real move (owner item 1), re-bank the provisional instrument constants, then
Q2–Q6 per plan §5.3.

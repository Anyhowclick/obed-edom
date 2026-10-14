# live6 fix — Chrome classifier rows read INCONCLUSIVE (2026-10-14), W6

Live run on f8059380 (two 25 fps takes, live6): every CEF arm MATCHes, DSK included, but `probe-chrome-gpu: classifier` and
`probe-chrome-software: classifier` are INCONCLUSIVE in both takes. Their own records re-score PASS
(`score_placement_calibration(record["placementCalibration"], runDir)` → probe-chrome-harness PASS).
Cause: fold 4 changed `placement_gates` (scripts/managed_obs_qualify.py ~:3226-3240) to build `run_paths`/`runs` only for sessions in
`dissolve_probe.ARMS`; the Chrome probe sessions are not arms, so the Chrome loop (`runs.get(name)`) gets {} → INCONCLUSIVE.
Fix: make the Chrome classifier loop read each probe session's own `runDir/record.json` (as before fold 4), failing closed if missing.
Extend the existing placement_gates fixture/test so a Chrome probe session with a valid record scores PASS through placement_gates
(and a missing one INCONCLUSIVE). Then re-score both live6 takes offline through placement_gates on APFS clones
(`cp -cR SCR/live6/out <writable clone dir>`; the runDirs inside the run JSON point at SCR/live6/out — rewrite the prefix as
SCR/tools/rescore.py does) and report every failing check per take.
Files: scripts/managed_obs_qualify.py, tests/test_managed_obs_qualify.py only. Run tests/test_managed_obs_qualify.py at -n 2.

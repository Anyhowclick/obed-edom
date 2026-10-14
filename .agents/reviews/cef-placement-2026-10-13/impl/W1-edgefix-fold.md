# W1 fold — review edge fix r1 (2026-10-14)

Read `.agents/reviews/cef-placement-2026-10-13/review-edgefix-r1.md`. Build on the uncommitted diff (W6 owns scripts/ and
tests/test_dissolve_probe.py — do not touch). Fold M1 only: extend the existing Node case table with vrect [108.7,794.7,952,268]
(fx=fy=-0.3) asserting the right column 951, bottom row 267 and their intersection repairs with source clamped to vw-1/vh-1, plus
the top/left behaviour for that geometry. No product change unless the row exposes a bug (then fix minimally and report).
Run only tests/test_live_runtime.py at -n 2.

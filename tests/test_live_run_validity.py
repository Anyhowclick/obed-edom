from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import live_run_validity as validity  # noqa: E402
from obed_edom import managed_obs  # noqa: E402


INSTRUMENT_COST_ROWS = json.loads((REPO / "tests/fixtures/instrument_cost_rows.json").read_text())


@pytest.mark.parametrize("case", INSTRUMENT_COST_ROWS)
def test_instrument_cost_hook_row_grammar(case):
    assert set(case) == {"row", "wellFormed"}
    assert validity._well_formed_hook(case["row"]) is case["wellFormed"]


def baseline(host_kind: str) -> dict:
    row = validity.qualification(host_kind)
    assert row is not None
    environment = {
        "qualificationIdentity": host_kind,
        "gitHead": "abc123",
        "browserVersion": {"product": "Chrome/155.0.8059.79"},
        "observations": {
            "before": {"at": 1.0, "loadAverage": [1.0, 2.0, 3.0], "uptime": "up", "chromeCounts": {"owned": 1, "foreign": 0}},
            "during": {"at": 2.0, "loadAverage": [2.0, 2.0, 3.0], "uptime": "up", "chromeCounts": {"owned": 1, "foreign": 0}},
            "after": {"at": 3.0, "loadAverage": [1.0, 1.0, 2.0], "uptime": "up", "chromeCounts": {"owned": 0, "foreign": 0}},
        },
    }
    if row["engine"] == "cef":
        environment.update({
            "browserVersion": {"product": "CEF/irrelevant"},
            "obsVersion": row["obsVersion"],
            "outputRate": {"configuredHz": row["outputHz"], "observedHz": row["outputHz"]},
            "browserSourceRate": {
                "configuredHz": row["browserSourceHz"],
                "settingHz": row["browserSourceHz"],
            },
        })
    return {
        "hostKind": host_kind,
        "environment": environment,
        "instrumentCost": {
            hook: {
                "applicable": True, "installed": True,
                "count": 2, "p95": 1.5, "max": 2.0, "overBudget": 0,
            }
            for hook in validity.REQUIRED_HOOKS
        },
        "samples": [],
    }


@pytest.mark.parametrize(
    ("host_kind", "case", "expected", "reason"),
    [
        *[(host, "baseline", None, "cadence: settled-cadence statistic is open") for host in validity.QUALIFICATIONS],
        (validity.HOST_HEADLESS_CHROME, "at budget", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_HEADLESS_CHROME, "over budget", False, "cost: hook p95 exceeds"),
        (validity.HOST_HEADLESS_CHROME, "extra over budget", False, "cost: hook p95 exceeds"),
        (validity.HOST_HEADLESS_CHROME, "over budget and missing", False, "cost: hook p95 exceeds"),
        (validity.HOST_HEADLESS_CHROME, "missing hook", None, "cost: required hooks are missing"),
        (validity.HOST_HEADLESS_CHROME, "zero call", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_HEADLESS_CHROME, "inapplicable", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_HEADLESS_CHROME, "all inapplicable", None, "cost: frame.total must be applicable"),
        (validity.HOST_HEADLESS_CHROME, "uninstalled zero", None, "cost: applicable hooks were not installed"),
        (validity.HOST_HEADLESS_CHROME, "missing applicability", None, "cost: malformed hook entries"),
        (validity.HOST_HEADLESS_CHROME, "zero call nonzero cost", None, "cost: malformed hook entries"),
        (validity.HOST_HEADLESS_CHROME, "diagnostics do not gate", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_HEADLESS_CHROME, "negative p95", None, "cost: malformed hook entries"),
        (validity.HOST_HEADLESS_CHROME, "negative count high p95", None, "cost: malformed hook entries"),
        (validity.HOST_HEADLESS_CHROME, "huge p95", None, "cost: malformed hook entries"),
        (validity.HOST_HEADLESS_CHROME, "missing cost", None, "cost: instrumentCost is missing or malformed"),
        (validity.HOST_HEADLESS_CHROME, "Chrome patch update", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_HEADLESS_CHROME, "new Chrome major", False, "environment: Chrome 156.0.1.2 is outside the qualified majors (155)"),
        (validity.HOST_HEADLESS_CHROME, "old Chrome major", False, "environment: Chrome 154.0.8037.59 is outside the qualified majors (155)"),
        (validity.HOST_HEADLESS_CHROME, "missing browser", None, "environment: Chrome browserVersion.product"),
        (validity.HOST_HEADLESS_CHROME, "unparseable browser", None, "environment: Chrome browserVersion.product"),
        (validity.HOST_HEADLESS_CHROME, "HeadlessChrome", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_MANAGED_OBS_25, "CEF product", None, "cadence: settled-cadence statistic is open"),
        (validity.HOST_MANAGED_OBS_25, "wrong OBS", False, "environment: obsVersion"),
        (validity.HOST_MANAGED_OBS_30, "29.97 output", False, "environment: outputRate.observedHz"),
        (validity.HOST_MANAGED_OBS_25, "source 60", False, "environment: browserSourceRate.settingHz"),
        (validity.HOST_MANAGED_OBS_25, "missing rate", None, "environment: outputRate.observedHz is missing"),
        (validity.HOST_HEADLESS_CHROME, "identity mismatch", False, "environment: qualificationIdentity"),
        (validity.HOST_HEADLESS_CHROME, "capture host mismatch", None, "qualification: supplied qualification"),
        (validity.HOST_HEADLESS_CHROME, "qualification None", None, "qualification: supplied qualification"),
        (validity.HOST_HEADLESS_CHROME, "caller budget mismatch", None, "qualification: supplied qualification"),
        (validity.HOST_HEADLESS_CHROME, "unknown host", None, "qualification: unknown hostKind"),
        (validity.HOST_HEADLESS_CHROME, "missing host", None, "qualification: capture hostKind is missing"),
        (validity.HOST_HEADLESS_CHROME, "non-string host", None, "qualification: capture hostKind is malformed"),
        (validity.HOST_HEADLESS_CHROME, "GL replay empty intervals", None, "cadence: GL intervals unavailable (GL replay)"),
    ],
)
def test_run_validity_matrix(host_kind, case, expected, reason):
    capture = baseline(host_kind)
    row = validity.qualification(host_kind)
    assert row is not None
    if case == "at budget":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[0]].update(p95=8.0, max=8.0)
    elif case == "over budget":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[0]].update(p95=8.0001, max=8.0001)
    elif case == "extra over budget":
        capture["instrumentCost"]["feed.extra"] = {
            "applicable": True, "installed": True,
            "count": 1, "p95": 8.0001, "max": 9.0, "overBudget": 1,
        }
    elif case == "over budget and missing":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[0]].update(p95=8.0001, max=8.0001)
        del capture["instrumentCost"][validity.REQUIRED_HOOKS[1]]
    elif case == "missing hook":
        del capture["instrumentCost"][validity.REQUIRED_HOOKS[1]]
    elif case == "zero call":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]] = {
            "applicable": True, "installed": True, "count": 0, "p95": None, "max": None, "overBudget": 0,
        }
    elif case == "inapplicable":
        capture["instrumentCost"]["feed.rvfc"] = {
            "applicable": False, "installed": False, "count": 0, "p95": None, "max": None, "overBudget": 0,
        }
    elif case == "all inapplicable":
        capture["instrumentCost"] = {
            hook: {
                "applicable": False, "installed": False,
                "count": 0, "p95": None, "max": None, "overBudget": 0,
            }
            for hook in validity.REQUIRED_HOOKS
        }
    elif case == "uninstalled zero":
        capture["instrumentCost"]["feed.rvfc"] = {
            "applicable": True, "installed": False, "count": 0, "p95": None, "max": None, "overBudget": 0,
        }
    elif case == "missing applicability":
        del capture["instrumentCost"]["feed.rvfc"]["applicable"]
    elif case == "zero call nonzero cost":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]] = {
            "applicable": True, "installed": True, "count": 0, "p95": 1.0, "max": 1.0, "overBudget": 0,
        }
    elif case == "diagnostics do not gate":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]].update(max=1000.0, overBudget=2)
    elif case == "negative p95":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]]["p95"] = -1.0
    elif case == "negative count high p95":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]] = {
            "applicable": True, "installed": True, "count": -1, "p95": 50.0, "max": 50.0, "overBudget": 0,
        }
    elif case == "huge p95":
        capture["instrumentCost"][validity.REQUIRED_HOOKS[1]]["p95"] = 10**1000
    elif case == "missing cost":
        del capture["instrumentCost"]
    elif case == "Chrome patch update":
        capture["environment"]["browserVersion"]["product"] = "Chrome/155.0.8059.80"
    elif case == "new Chrome major":
        capture["environment"]["browserVersion"]["product"] = "Chrome/156.0.1.2"
    elif case == "old Chrome major":
        capture["environment"]["browserVersion"]["product"] = "Chrome/154.0.8037.59"
    elif case == "missing browser":
        del capture["environment"]["browserVersion"]
    elif case == "unparseable browser":
        capture["environment"]["browserVersion"]["product"] = "Chrome/not-a-version"
    elif case == "HeadlessChrome":
        capture["environment"]["browserVersion"]["product"] = "HeadlessChrome/155.0.8059.80"
    elif case == "CEF product":
        capture["environment"]["browserVersion"]["product"] = "HeadlessChrome/0.0.0.0"
    elif case == "wrong OBS":
        capture["environment"]["obsVersion"] = "31.0.0"
    elif case == "29.97 output":
        capture["environment"]["outputRate"]["observedHz"] = 29.97
    elif case == "source 60":
        capture["environment"]["browserSourceRate"]["settingHz"] = 60
    elif case == "missing rate":
        del capture["environment"]["outputRate"]["observedHz"]
    elif case == "identity mismatch":
        capture["environment"]["qualificationIdentity"] = validity.HOST_QUALIFIED_CHROME_ATTACH
    elif case == "capture host mismatch":
        capture["hostKind"] = validity.HOST_QUALIFIED_CHROME_ATTACH
        capture["environment"]["qualificationIdentity"] = validity.HOST_QUALIFIED_CHROME_ATTACH
    elif case == "qualification None":
        row = None
    elif case == "caller budget mismatch":
        row["costBudgetP95Ms"] = 1000
    elif case == "unknown host":
        capture["hostKind"] = "unknown"
        capture["environment"]["qualificationIdentity"] = "unknown"
        row = None
    elif case == "missing host":
        del capture["hostKind"]
        row = None
    elif case == "non-string host":
        capture["hostKind"] = []
        row = None
    elif case == "GL replay empty intervals":
        capture["glReplay"] = {"requested": "auto"}

    capture_before = copy.deepcopy(capture)
    row_before = copy.deepcopy(row)
    result = validity.run_validity(capture, row, gl_intervals=[])

    assert result["ok"] is expected
    assert any(reason in item for item in result["reasons"])
    assert set(result) == {"ok", "reasons", "measured", "policy"}
    assert set(result["measured"]) == {"cost", "environment", "cadence"}
    assert all("ok" in result["measured"][name] for name in result["measured"])
    assert set(result["measured"]["cost"]) == {
        "ok", "budgetP95Ms", "hooks", "missingHooks", "malformedHooks", "uninstalledHooks",
        "inapplicableHooks", "overBudgetHooks",
    }
    assert capture == capture_before
    assert row == row_before
    if case == "baseline":
        expected_reasons = ["cadence: settled-cadence statistic is open (owner Q2, gate 5a); measured only"]
        if host_kind == validity.HOST_QUALIFIED_CHROME_ATTACH:
            expected_reasons.insert(0, "environment: attach display/timing profile is not recorded")
        assert result["reasons"] == expected_reasons
        assert result["measured"]["environment"]["observations"] == capture["environment"]["observations"]
        if host_kind == validity.HOST_HEADLESS_CHROME:
            assert result["measured"]["environment"]["ok"] is True
    if case == "Chrome patch update":
        assert result["measured"]["environment"]["ok"] is True
        assert result["measured"]["environment"]["chromeBuild"] == "155.0.8059.80"
    if case in {"new Chrome major", "old Chrome major"}:
        assert result["measured"]["environment"]["ok"] is False
    if case in {"missing browser", "unparseable browser"}:
        assert result["measured"]["environment"]["ok"] is None
    if case == "missing browser":
        assert result["measured"]["environment"]["chromeBuild"] is None
    if case in {"at budget", "zero call", "inapplicable", "diagnostics do not gate", "HeadlessChrome", "CEF product"}:
        assert result["measured"]["cost"]["ok"] is True
    if case == "uninstalled zero":
        assert result["measured"]["cost"]["ok"] is None
        assert result["measured"]["cost"]["uninstalledHooks"] == ["feed.rvfc"]
    if case == "all inapplicable":
        assert result["measured"]["cost"]["ok"] is None
        assert result["measured"]["cost"]["inapplicableHooks"] == list(validity.REQUIRED_HOOKS)
    if case == "GL replay empty intervals":
        assert result["measured"]["cadence"]["glIntervals"] == []
        tuple_result = validity.run_validity(capture, row, gl_intervals=())
        assert tuple_result["ok"] is None
        assert "cadence: GL intervals unavailable (GL replay)" in tuple_result["reasons"]
        assert tuple_result["measured"]["cadence"]["glIntervals"] == ()
    if case == "over budget and missing":
        assert result["measured"]["cost"]["ok"] is False
    if case == "negative count high p95":
        assert result["measured"]["cost"]["ok"] is None
        assert result["measured"]["cost"]["overBudgetHooks"] == []
    if case == "caller budget mismatch":
        assert result["policy"]["costBudgetP95Ms"] == validity.COST_BUDGET_P95_MS
    if case == "CEF product":
        assert result["measured"]["environment"]["browserVersion"] == {"product": "HeadlessChrome/0.0.0.0"}
        assert "chromeBuild" not in result["measured"]["environment"]
    if host_kind in validity.QUALIFICATIONS and case not in {"unknown host", "missing host", "non-string host"}:
        assert result["policy"]["requiredHooks"] == list(validity.REQUIRED_HOOKS)
        assert result["policy"]["status"]["requiredHooks"] == validity.REQUIRED_HOOKS_POLICY_STATUS


def test_cadence_measures_whole_settled_visits_with_gl_exclusions_and_fallback():
    capture = baseline(validity.HOST_HEADLESS_CHROME)
    capture["samples"] = "not a row list"
    capture["sampleRows"] = [
        {"t": 1000, "ts": 0, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1001, "ts": 100, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1002, "ts": 110, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1003, "ts": 120, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1004, "ts": 150, "scene": 1, "busy": True, "playerState": "Playing"},
        {"t": 1005, "ts": 200, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1006, "ts": 220, "scene": 1, "busy": True, "playerState": "Idle"},
        {"t": 1007, "ts": 260, "scene": 1, "busy": False, "playerState": "Idle"},
        {"t": 1008, "ts": 300, "scene": 1, "busy": False, "playerState": "Idle"},
    ]
    gl_intervals = [{"start": 230, "end": 250}]
    capture_before = copy.deepcopy(capture)
    gl_before = copy.deepcopy(gl_intervals)

    result = validity.run_validity(
        capture, validity.qualification(validity.HOST_HEADLESS_CHROME), gl_intervals=gl_intervals,
    )
    cadence = result["measured"]["cadence"]

    assert cadence["visitCount"] == 2
    assert cadence["deltaCount"] == 5
    assert cadence["visits"] == [
        {
            "scene": 1,
            "start": 0.0,
            "end": 120.0,
            "sampleCount": 4,
            "deltaCount": 3,
            "medianMs": 10.0,
            "p95Ms": 91.0,
            "maxMs": 100.0,
            "overBoundaryCount": 1,
            "glExcludedDeltas": 0,
        },
        {
            "scene": 1,
            "start": 200.0,
            "end": 300.0,
            "sampleCount": 4,
            "deltaCount": 2,
            "medianMs": 30.0,
            "p95Ms": 39.0,
            "maxMs": 40.0,
            "overBoundaryCount": 1,
            "glExcludedDeltas": 1,
        },
    ]
    assert capture == capture_before
    assert gl_intervals == gl_before

    without_gl = validity.run_validity(capture, validity.qualification(capture["hostKind"]))
    assert without_gl["measured"]["cadence"]["glIntervals"] is None
    assert "cadence: GL intervals were not supplied" in without_gl["reasons"]

    endpoint_capture = baseline(validity.HOST_HEADLESS_CHROME)
    endpoint_capture["samples"] = [
        {"ts": ts, "scene": 2, "busy": False, "playerState": "Idle"}
        for ts in (0, 16, 250, 350, 366)
    ]
    endpoint = validity.run_validity(
        endpoint_capture,
        validity.qualification(endpoint_capture["hostKind"]),
        gl_intervals=[{"start": 20, "end": 250}],
    )["measured"]["cadence"]["visits"][0]
    assert endpoint["deltaCount"] == 3
    assert endpoint["glExcludedDeltas"] == 1
    assert endpoint["maxMs"] == 100.0

    malformed_samples = copy.deepcopy(capture)
    malformed_samples["samples"] = [{}]
    malformed = validity.run_validity(
        malformed_samples, validity.qualification(capture["hostKind"]), gl_intervals=[],
    )
    assert "cadence: sample rows are missing a finite frame time" in malformed["reasons"]

    malformed_gl = validity.run_validity(
        capture,
        validity.qualification(capture["hostKind"]),
        gl_intervals=[{"start": 2, "end": 1}],
    )
    assert "cadence: GL intervals are malformed" in malformed_gl["reasons"]
    assert malformed_gl["measured"]["cadence"]["visits"] is None


def test_visible_gl_replay_keeps_the_frozen_unavailable_interval_reason() -> None:
    capture = baseline(validity.HOST_HEADLESS_CHROME)
    capture.update(scope={"kind": "visible"}, glReplay={"requested": "auto"})
    del capture["samples"]

    result = validity.run_validity(capture, validity.qualification(capture["hostKind"]))

    assert result["ok"] is None
    assert result["measured"]["cadence"]["visits"] is None
    assert "cadence: GL intervals unavailable (GL replay)" in result["reasons"]
    assert not any("samples are missing" in reason for reason in result["reasons"])


def test_qualification_rows_do_not_drift_from_probe_or_managed_obs():
    import live_continuity_probe as probe

    assert set(validity.QUALIFICATIONS) == set(probe.HOST_KINDS)
    assert validity.QUALIFICATIONS[validity.HOST_HEADLESS_CHROME]["periodMs"] == 1000 / 60
    assert validity.QUALIFICATIONS[validity.HOST_QUALIFIED_CHROME_ATTACH]["periodMs"] == 1000 / 60
    for host_kind in (validity.HOST_HEADLESS_CHROME, validity.HOST_QUALIFIED_CHROME_ATTACH):
        assert validity.QUALIFICATIONS[host_kind]["chromeMajors"] == [155]
        assert "chromeBuild" not in validity.QUALIFICATIONS[host_kind]
    for host_kind, output_hz in (
        (validity.HOST_MANAGED_OBS_25, 25),
        (validity.HOST_MANAGED_OBS_30, 30),
    ):
        row = validity.QUALIFICATIONS[host_kind]
        assert row["outputHz"] == output_hz
        assert row["browserSourceHz"] == managed_obs.RATES[output_hz][1]
        assert row["obsVersion"] == managed_obs.PINNED_OBS
        assert row["periodMs"] == 1000 / output_hz
    for row in validity.QUALIFICATIONS.values():
        assert row["cadenceBoundaryMs"] == 2 * row["periodMs"]
        assert row["requiredHooks"] == list(validity.REQUIRED_HOOKS)
        assert validity.qualification(row["hostKind"]) == row
        assert validity.qualification(row["hostKind"]) is not row
        assert json.loads(json.dumps(validity.qualification(row["hostKind"]))) == row
    assert validity.qualification("unknown") is None
    assert validity.CADENCE_POLICY_STATUS.startswith("OPEN:")
    assert validity.HOST_ROWS_POLICY_STATUS.startswith("OPEN:")
    assert validity.LOAD_POLICY_STATUS.startswith("OPEN:")
    assert validity.REQUIRED_HOOKS_POLICY_STATUS == "frozen C2 accounting hooks"

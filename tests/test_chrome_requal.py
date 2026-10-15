from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import chrome_requal as requal  # noqa: E402

BASELINE = json.loads((REPO / ".agents/reviews/chrome155-requal/dx1-verdict.json").read_text())
VERSION = "155.0.8059.79"


def inputs(case: str) -> tuple[dict, dict[str, str | None]]:
    verdict = copy.deepcopy(BASELINE)
    products = {name: f"HeadlessChrome/{VERSION}" for name in requal.ARMS if name != "m-raw"}
    if case == "positive control":
        assert len(requal.ARMS) == 28
        assert verdict["detail"]["grant-attach"]["checks"]["grant"]["verdict"] == "FAIL"
        assert verdict["detail"]["off"]["checks"]["model"]["verdict"] == "FAIL"
        assert "m-raw" not in products
        assert verdict["detail"]["m-snap"]["checks"]["holder_pixels"]["problems"] == [
            "no L_path for the arm's compositing path"
        ]
        assert "geometry" not in verdict["detail"]["m-snap-shift"]["checks"]
    elif case == "gate regression":
        verdict["gates"]["handoff"]["verdict"] = "FAIL"
    elif case == "cell regression":
        verdict["detail"]["m-snap"]["checks"]["mask"]["verdict"] = "FAIL"
    elif case == "core mismatch":
        verdict["detail"]["on"]["outcome"] = "MISMATCH"
    elif case == "missing arm":
        del verdict["detail"]["on"]
    elif case == "missing twin product":
        del products[requal.SNAP_CELLS["m-snap"][1]]
    elif case == "missing non-raw product":
        del products["on"]
    elif case == "version mismatch":
        products["on"] = "Chrome/154.0.8037.59"
    elif case == "capture problems":
        verdict["detail"]["on"]["problems"] = ["capture dropped a frame"]
        verdict["detail"]["on"]["outcome"] = "MISMATCH"
    elif case == "untrustworthy cell FAIL":
        verdict["detail"]["m-snap"]["checks"]["mask"]["verdict"] = "FAIL"
        verdict["detail"]["m-snap"]["problems"] = ["twin: x"]
    elif case == "geometry missing":
        verdict["detail"]["m-snap"]["checks"].pop("geometry")
    elif case == "unexpected holder problems":
        verdict["detail"]["m-snap"]["checks"]["holder_pixels"]["problems"] = ["different limitation"]
    elif case == "FAIL precedence":
        verdict["gates"]["handoff"]["verdict"] = "FAIL"
        del products[requal.SNAP_CELLS["m-snap"][1]]
    return verdict, products


@pytest.mark.parametrize(
    ("case", "expected", "reason"),
    [
        ("positive control", "PASS", None),
        ("gate regression", "FAIL", "gate handoff"),
        ("cell regression", "FAIL", "m-snap"),
        ("core mismatch", "FAIL", "on"),
        ("missing arm", "INCONCLUSIVE", "on"),
        ("missing twin product", "INCONCLUSIVE", "m-snap-twin"),
        ("missing non-raw product", "INCONCLUSIVE", "on"),
        ("version mismatch", "INCONCLUSIVE", "on"),
        ("capture problems", "INCONCLUSIVE", "on"),
        ("untrustworthy cell FAIL", "INCONCLUSIVE", "m-snap"),
        ("geometry missing", "INCONCLUSIVE", "m-snap"),
        ("unexpected holder problems", "INCONCLUSIVE", "m-snap"),
        ("FAIL precedence", "FAIL", "gate handoff"),
    ],
)
def test_qualify(case, expected, reason):
    verdict, products = inputs(case)
    status, reasons = requal.qualify(verdict, products, VERSION)
    assert status == expected
    if reason is not None:
        assert any(item.startswith(reason) for item in reasons)

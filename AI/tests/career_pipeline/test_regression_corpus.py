from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_phase_zero_fixture_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate-fixtures.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "cases=40" in result.stdout


def test_p0_cases_are_explicitly_marked() -> None:
    corpus = json.loads(
        (ROOT / "contract-fixtures" / "regression-corpus.json").read_text(encoding="utf-8")
    )

    p0_ids = {case["id"] for case in corpus["cases"] if case["priority"] == "P0"}
    assert {"ROLE-001", "EXP-001", "SRC-001", "REQ-001", "FIT-001", "MAP-001"} <= p0_ids

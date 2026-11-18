"""Keep the documented requirement-change experiment executable end to end."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fulfillment_requirement_trial(tmp_path):
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/trial_fulfillment.py"), "--output", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert len(summary["records"]) == 44
    negative = json.loads((tmp_path / "negative_control-sliced-safety.json").read_text())
    assert negative["verdict"] == "FAIL"
    assert "cancel_without_refund" in negative["selection"]["model_actions"]
    assert negative["queries"][0]["trace"][-1] == "cancel_without_refund"
    flows = json.loads((tmp_path / "negative_control-sliced-flows.json").read_text())
    assert flows["verdict"] == "PASS"
    assert flows["selection"]["action_coverage"] == "executed_steps_only"

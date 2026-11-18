"""Keep the documented requirement-change experiment executable end to end."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "benchmarks/fulfillment-trial-results.json"


def _semantic_records(summary):
    # Preserve duplicate/missing cases and compare by stable case/query IDs.
    # Historical source hashes, timings and serialized byte sizes are observations.
    return sorted(
        (
            record["stage"],
            record["sliced"],
            record["selection"],
            record["verdict"],
            record["model_actions"],
            sorted(
                (query["id"], query["status"], query["states_explored"])
                for query in record["queries"]
            ),
            sorted((flow["id"], flow["passed"]) for flow in record["flows"]),
        )
        for record in summary["records"]
    )


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
    recorded = json.loads(RECORD.read_text())
    assert summary["schema"] == recorded["schema"]
    assert summary["max_states"] == recorded["max_states"]
    assert _semantic_records(summary) == _semantic_records(recorded), (
        "Fulfillment behavior changed: review the new results, then update the committed "
        "measurement record and docs/examples.md together. Do not regenerate blindly."
    )
    negative = json.loads((tmp_path / "negative_control-sliced-safety.json").read_text())
    assert negative["verdict"] == "FAIL"
    assert "cancel_without_refund" in negative["selection"]["model_actions"]
    assert negative["queries"][0]["trace"][-1] == "cancel_without_refund"
    flows = json.loads((tmp_path / "negative_control-sliced-flows.json").read_text())
    assert flows["verdict"] == "PASS"
    assert flows["selection"]["action_coverage"] == "executed_steps_only"

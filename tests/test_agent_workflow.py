"""Replay model edits from the guided agent trial, not an agent performance benchmark.

Each subprocess gets fresh loader identities after an edit. Patches affect only
temporary copies; the canonical examples and characterization remain unchanged.
Run with: uv run pytest tests/test_agent_workflow.py -q
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures/agent_workflow"


def cli(*args, code=0):
    result = subprocess.run(
        [sys.executable, "-c", "from analint.cli import app; app()", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == code, result.stdout + result.stderr
    return json.loads(result.stdout)


def check(path, *args, code=0):
    return cli("check", path, *args, "-f", "json", code=code)


def trace(path, target, *args):
    # trace's exit code reports command execution, not the property's status.
    return cli("trace", target, "-p", path, *args, "-f", "json")


@pytest.fixture
def workspace(tmp_path):
    for case in ("branch_protection", "oauth", "k8s_replicaset"):
        shutil.copytree(
            ROOT / "examples" / case,
            tmp_path / case,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    return tmp_path


def apply_patch(workspace, case):
    # Git hooks export repository paths; keep patches confined to this copy.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    patches = json.loads((FIXTURES / "changes.json").read_text())
    result = subprocess.run(
        ["git", "apply", "-"],
        input=patches[case],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("case", "hypothesis", "initial_verdict", "target", "witness_length"),
    [
        ("branch_protection", "branch_requested", "FAIL", "merge_behind_is_achievable", 5),
        ("oauth", "oauth_scoped", "PASS", "independent_codes_can_issue", 4),
        ("k8s_replicaset", "k8s_requested", "FAIL", "quota_below_usage_is_reachable", 2),
    ],
)
def test_guided_change_and_mutation_control(
    workspace, case, hypothesis, initial_verdict, target, witness_length
):
    path = workspace / case
    assert check(path, "--strict")["verdict"] == "PASS"
    proposed = check(
        path, "--what-if", FIXTURES / f"{hypothesis}.py", code=int(initial_verdict == "FAIL")
    )
    assert proposed["verdict"] == initial_verdict
    assert not proposed["load_errors"]
    assert not any(f["severity"] == "ERROR" for f in proposed["structural"])
    if initial_verdict == "FAIL":
        requested = "requested_loose_merge" if case == "branch_protection" else target
        assert any(q["id"] == requested and q["status"] == "FAIL" for q in proposed["queries"])
    # Additive hypotheses must leave the original specification unchanged.
    assert check(path, "--strict")["verdict"] == "PASS"

    apply_patch(workspace, case)
    accepted = check(path, "--strict")
    assert accepted["verdict"] == "PASS"
    assert any(q["id"] == target and q["status"] == "PASS" for q in accepted["queries"])
    witness = trace(path, target)
    assert witness["status"] == "PASS"
    assert len(witness["steps"]) == witness_length

    filename = "protocol.py" if case == "oauth" else "spec.py"
    source = path / filename
    original = source.read_text()
    if case == "branch_protection":
        mutation = original.replace("    PullRequest.approvals >= REQUIRED_APPROVALS,\n", "")
    elif case == "oauth":
        mutation = original.replace("    Key,\n", "    In,\n    Key,\n").replace(
            "        code.state == CodeState.ISSUED,\n",
            "        In(code.state, [CodeState.ISSUED, CodeState.REDEEMED]),\n",
        )
    else:
        mutation = original.replace("    pre=[live_pods < Namespace.quota],\n", "    pre=[],\n")
    assert mutation != original
    try:
        source.write_text(mutation)
        broken = check(path, "--strict", code=1)
        assert broken["verdict"] == "FAIL"
        if case == "branch_protection":
            assert any(
                q["id"] == "never_merge_underapproved" and q["status"] == "FAIL"
                for q in broken["queries"]
            )
        elif case == "oauth":
            assert any(
                q["id"] == "one_active_token_per_code" and q["status"] == "FAIL"
                for q in broken["invariants"]
            )
            counterexample = trace(path, "one_active_token_per_code")
            assert counterexample["status"] == "FAIL"
            assert len(counterexample["steps"]) == 3
        else:
            scenario = next(
                s for s in broken["scenarios"] if s["id"] == "bare_creation_over_quota_blocked"
            )
            assert not scenario["passed"]  # a broken postcondition is not an expected rejection
            assert any("postcondition" in f["message"] for f in broken["exploration"])
            compact = check(path, "--strict", "--compact", code=1)
            assert compact["schema"] == "analint.check.compact/v1"
            assert compact["verdict"] == "FAIL"
            assert compact["summary"] == broken["summary"]
            [group] = compact["exploration"]
            assert group["code"] == "transition.postcondition_violated"
            assert group["count"] == len(broken["exploration"]) > 3
            assert group["examples"] == [
                {"location": f["location"], "message": f["message"]}
                for f in broken["exploration"][:3]
            ]
    finally:
        source.write_text(original)
    assert check(path, "--strict")["verdict"] == "PASS"


def test_oauth_overstrong_hypothesis_has_independent_code_counterexample(workspace):
    path = workspace / "oauth"
    hypothesis = FIXTURES / "oauth_global.py"
    report = check(path, "--what-if", hypothesis, code=1)
    assert report["verdict"] == "FAIL"
    witness = trace(path, "global_single_active_token", "--what-if", hypothesis)
    assert witness["status"] == "FAIL"
    assert len(witness["steps"]) == 4
    # The overly broad property fails on two independent codes, not a replay.
    values = witness["final_state"]
    assert values["Token['t1'].source_code"] != values["Token['t2'].source_code"]


def test_k8s_budget_is_open_until_a_witness_is_found(workspace):
    path = workspace / "k8s_replicaset"
    apply_patch(workspace, "k8s_replicaset")
    hypothesis = workspace / "budget.py"
    adequate = (FIXTURES / "k8s_budget.py").read_text()
    hypothesis.write_text(adequate.replace("max_states=10000", "max_states=1"))
    report = check(path, "--what-if", hypothesis, code=4)
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["summary"]["queries_inconclusive"] == 1
    assert check(path, "--what-if", hypothesis, "--strict", code=1)["verdict"] == "FAIL"
    witness = trace(path, "three_pods_at_zero_quota", "--what-if", hypothesis)
    assert witness["status"] == "INCONCLUSIVE"
    assert witness["steps"] == []

    hypothesis.write_text(adequate)
    assert check(path, "--what-if", hypothesis, "--strict")["verdict"] == "PASS"
    witness = trace(path, "three_pods_at_zero_quota", "--what-if", hypothesis)
    assert witness["status"] == "PASS"
    assert len(witness["steps"]) == 6
    assert witness["final_state"]["Namespace.quota"] == 0

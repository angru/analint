"""Stable diagnostic codes and expected-rejection metadata in JSON (issue #5)."""

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from analint.cli import app
from analint.reporter.base import Code

ROOT = Path(__file__).resolve().parents[1]

SPEC = """
from analint import Action, Entity, Expect, Field, Invariant, Scenario, Set, Spec

class Record(Entity):
    ready: bool = Field(default=False)

enable = Action(pre=[Record.ready == False], effect=[Set(Record.ready, True)])
consume = Action(pre=[Record.ready == True], effect=[Set(Record.ready, False)])
negative = Scenario(action=consume, given=[Record(ready={ready})], expected=Expect.FAIL)
probe = Spec(
    id="diagnostic_probe",
    name="Diagnostic probe",
    entities=[Record],
    actions=[enable, consume],
    scenarios=[negative],
    invariants=[{invariants}],
)
"""


def _check(tmp_path, ready: bool, invariants: str = "") -> tuple[int, dict]:
    spec = tmp_path / "spec.py"
    spec.write_text(SPEC.replace("{ready}", str(ready)).replace("{invariants}", invariants))
    result = CliRunner().invoke(app, ["check", str(spec), "--format", "json"])
    return result.exit_code, json.loads(result.stdout)


def test_issue_reproduction_carries_codes_and_expected_rejection(tmp_path):
    exit_code, data = _check(tmp_path, ready=False)
    assert exit_code == 0 and data["verdict"] == "PASS"
    assert data["structural"] == [
        {
            "severity": "WARNING",
            "code": "structural.no_scenarios",
            "location": "action:enable",
            "message": "has no scenarios",
        }
    ]
    [scenario] = data["scenarios"]
    assert scenario["passed"]
    rejection, verdict_note = scenario["findings"]
    assert rejection == {
        "severity": "ERROR",
        "code": "transition.pre_failed",
        "location": "action:consume",
        "message": "PRE failed: Record.ready == True",
        "expected": True,
    }
    assert verdict_note["code"] == "scenario.expected_rejection"
    assert "expected" not in verdict_note


def test_failed_negative_scenario_is_never_marked_expected(tmp_path):
    exit_code, data = _check(tmp_path, ready=True)
    assert exit_code == 1 and data["verdict"] == "FAIL"
    [scenario] = data["scenarios"]
    assert not scenario["passed"]
    assert [f["code"] for f in scenario["findings"]] == ["scenario.not_rejected"]
    assert not any(f.get("expected") for f in scenario["findings"])


def test_rejection_in_failed_negative_scenario_is_not_expected(tmp_path):
    # the action is rejected, but the given state is already illegal: a defect
    exit_code, data = _check(
        tmp_path, ready=False, invariants="Invariant(Record.ready == True, id='always_ready')"
    )
    assert exit_code == 1
    [scenario] = data["scenarios"]
    assert not scenario["passed"]
    codes = [f["code"] for f in scenario["findings"]]
    assert "transition.pre_failed" in codes and "invariant.violated" in codes
    assert not any(f.get("expected") for f in scenario["findings"])


def test_codes_are_unique_and_documented():
    assert len(Code.__members__) == len(list(Code)), "two codes share a value"
    assert all(re.fullmatch(r"[a-z]+\.[a-z_]+", code.value) for code in Code)
    documented = set(re.findall(r"`([a-z]+\.[a-z_]+)`", (ROOT / "docs/cli.md").read_text()))
    assert {code.value for code in Code} <= documented

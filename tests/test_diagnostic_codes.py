"""Stable diagnostic codes and expected-rejection metadata in JSON (issue #5)."""

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from analint.cli import app
from analint.mcp_server import check_spec
from analint.reporter import Code, Finding, Severity
from analint.reporter.base import ValidationResult
from analint.reporter.json_reporter import result_to_dict

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


def test_existing_finding_constructor_has_an_unclassified_code():
    finding = Finding(Severity.WARNING, "extension:custom", "custom warning")
    assert finding.to_dict() == {
        "severity": "WARNING",
        "code": "finding.unclassified",
        "location": "extension:custom",
        "message": "custom warning",
    }


def test_codes_are_unique_and_documented():
    assert len(Code.__members__) == len(list(Code)), "two codes share a value"
    assert all(re.fullmatch(r"[a-z]+\.[a-z_]+", code.value) for code in Code)
    documented = set(re.findall(r"`([a-z]+\.[a-z_]+)`", (ROOT / "docs/cli.md").read_text()))
    assert {code.value for code in Code} <= documented


def test_compact_groups_keep_severity_and_expected_rejection_separate():
    result = ValidationResult("s", "S")
    code = Code.PRE_FAILED
    result.exploration_findings = [
        Finding(Severity.ERROR, "action:a", "unexpected rejection", code),
        Finding(Severity.ERROR, "action:a", "expected rejection", code, expected=True),
        Finding(Severity.WARNING, "action:a", "warning", code),
    ]
    groups = result_to_dict(result, compact=True)["exploration"]
    assert [(g["severity"], g.get("expected", False), g["count"]) for g in groups] == [
        ("ERROR", False, 1),
        ("ERROR", True, 1),
        ("WARNING", False, 1),
    ]
    assert result_to_dict(result)["exploration"] == [
        finding.to_dict() for finding in result.exploration_findings
    ]


def test_compact_check_matches_mcp_and_keeps_expected_rejection(tmp_path):
    spec = tmp_path / "spec.py"
    spec.write_text(SPEC.replace("{ready}", "False").replace("{invariants}", ""))
    args = ["check", str(spec), "-f", "json", "--compact"]
    response = CliRunner().invoke(app, args)
    assert response.exit_code == 0, response.output
    data = json.loads(response.stdout)
    assert data == check_spec(str(spec), compact=True)
    assert data["scenarios"][0]["findings"][0]["expected"] is True
    assert data["verdict"] == "PASS"

    strict = CliRunner().invoke(app, [*args, "--strict"])
    assert strict.exit_code == 1, strict.output
    assert json.loads(strict.stdout)["verdict"] == "FAIL"
    assert check_spec(str(spec))["schema"] == "analint.check/v1"


def test_compact_requires_json_format():
    result = CliRunner().invoke(app, ["check", "--compact"])
    assert result.exit_code == 2
    assert "requires --format json" in result.output

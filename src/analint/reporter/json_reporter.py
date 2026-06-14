from __future__ import annotations

import json
import sys

from analint.reporter.base import ValidationResult


def report_json(result: ValidationResult, strict: bool = False) -> None:
    json.dump(result_to_dict(result, strict), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def result_to_dict(result: ValidationResult, strict: bool = False) -> dict:
    verdict = result.effective_verdict(strict)
    return {
        "spec": {"id": result.spec_id, "name": result.spec_name},
        "verdict": verdict.value,
        "passed": verdict == "PASS",
        "load_errors": result.load_errors,
        "structural": [
            {"severity": f.severity.value, "location": f.location, "message": f.message}
            for f in result.structural_findings
        ],
        "scenarios": [
            {
                "id": sr.scenario_id,
                "name": sr.scenario_name,
                "passed": sr.passed,
                "rules": sr.rules_count,
                "findings": [
                    {"severity": f.severity.value, "location": f.location, "message": f.message}
                    for f in sr.findings
                ],
            }
            for sr in result.scenario_results
        ],
        "exploration": [
            {"severity": f.severity.value, "location": f.location, "message": f.message}
            for f in result.exploration_findings
        ],
        "queries": [
            {
                "id": qr.query_id,
                "kind": qr.kind,
                "status": qr.status,
                "states_explored": qr.states_explored,
                "trace": qr.trace,
                "findings": [
                    {"severity": f.severity.value, "location": f.location, "message": f.message}
                    for f in qr.findings
                ],
            }
            for qr in result.query_results
        ],
        "invariants": [
            {
                "id": ir.invariant_id,
                "label": ir.label,
                "status": ir.status,
                "states_explored": ir.states_explored,
                "trace": ir.trace,
                "findings": [
                    {"severity": f.severity.value, "location": f.location, "message": f.message}
                    for f in ir.findings
                ],
            }
            for ir in result.invariant_results
        ],
        "flows": [
            {
                "id": fr.flow_id,
                "passed": fr.passed,
                "actions_run": fr.actions_run,
                "trace": fr.trace,
                "findings": [
                    {"severity": f.severity.value, "location": f.location, "message": f.message}
                    for f in fr.findings
                ],
            }
            for fr in result.flow_results
        ],
        "summary": {
            "passed": result.passed_count,
            "failed": result.failed_count,
            "warnings": result.warning_count,
            "queries_passed": sum(1 for q in result.query_results if q.status == "PASS"),
            "queries_failed": sum(1 for q in result.query_results if q.status == "FAIL"),
            "queries_inconclusive": sum(
                1 for q in result.query_results if q.status == "INCONCLUSIVE"
            ),
            "invariants_passed": sum(1 for i in result.invariant_results if i.status == "PASS"),
            "invariants_failed": sum(1 for i in result.invariant_results if i.status == "FAIL"),
            "invariants_unchecked": sum(
                1 for i in result.invariant_results if i.status in ("INCONCLUSIVE", "NOT_CHECKED")
            ),
            "flows_passed": sum(1 for fr in result.flow_results if fr.passed),
            "flows_failed": sum(1 for fr in result.flow_results if not fr.passed),
        },
    }

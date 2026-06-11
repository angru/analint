from __future__ import annotations

import json
import sys

from analint.reporter.base import ValidationResult


def report_json(result: ValidationResult) -> None:
    json.dump(result_to_dict(result), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def result_to_dict(result: ValidationResult) -> dict:
    return {
        "spec": {"id": result.spec_id, "name": result.spec_name},
        "passed": not result.has_errors,
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
        "summary": {
            "passed": result.passed_count,
            "failed": result.failed_count,
            "warnings": result.warning_count,
            "queries_passed": sum(1 for q in result.query_results if q.status == "PASS"),
            "queries_failed": sum(1 for q in result.query_results if q.status == "FAIL"),
        },
    }

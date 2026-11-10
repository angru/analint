from __future__ import annotations

import json
import sys

from analint.reporter.base import Code, Finding, Severity, ValidationResult


def report_json(result: ValidationResult, strict: bool = False, *, compact: bool = False) -> None:
    json.dump(
        result_to_dict(result, strict, compact=compact), sys.stdout, ensure_ascii=False, indent=2
    )
    sys.stdout.write("\n")


def _findings(findings: list[Finding], compact: bool) -> list[dict]:
    if not compact:
        return [finding.to_dict() for finding in findings]

    groups: dict[tuple[Code, Severity, bool], dict] = {}
    for finding in findings:
        key = (finding.code, finding.severity, finding.expected)
        if key not in groups:
            groups[key] = {
                "code": finding.code.value,
                "severity": finding.severity.value,
                **({"expected": True} if finding.expected else {}),
                "count": 0,
                "examples": [],
            }
        group = groups[key]
        group["count"] += 1
        if len(group["examples"]) < 3:
            group["examples"].append({"location": finding.location, "message": finding.message})
    return list(groups.values())


def result_to_dict(
    result: ValidationResult, strict: bool = False, *, compact: bool = False
) -> dict:
    verdict = result.effective_verdict(strict)
    return {
        "schema": "analint.check.compact/v1" if compact else "analint.check/v1",
        "spec": {"id": result.spec_id, "name": result.spec_name},
        "verdict": verdict.value,
        "passed": verdict == "PASS",
        "load_errors": result.load_errors,
        "structural": _findings(result.structural_findings, compact),
        "scenarios": [
            {
                "id": sr.scenario_id,
                "name": sr.scenario_name,
                "passed": sr.passed,
                "rules": sr.rules_count,
                "findings": _findings(sr.findings, compact),
            }
            for sr in result.scenario_results
        ],
        "exploration": _findings(result.exploration_findings, compact),
        "queries": [
            {
                "id": qr.query_id,
                "kind": qr.kind,
                "status": qr.status,
                "states_explored": qr.states_explored,
                **({"elapsed_ms": round(qr.elapsed_ms, 3)} if qr.elapsed_ms is not None else {}),
                "trace": qr.trace,
                **({"slice": qr.slice} if qr.slice is not None else {}),
                **({"backend": qr.backend} if qr.backend is not None else {}),
                "findings": _findings(qr.findings, compact),
            }
            for qr in result.query_results
        ],
        "invariants": [
            {
                "id": ir.invariant_id,
                "label": ir.label,
                "status": ir.status,
                "states_explored": ir.states_explored,
                **({"elapsed_ms": round(ir.elapsed_ms, 3)} if ir.elapsed_ms is not None else {}),
                "trace": ir.trace,
                **({"slice": ir.slice} if ir.slice is not None else {}),
                **({"backend": ir.backend} if ir.backend is not None else {}),
                "findings": _findings(ir.findings, compact),
            }
            for ir in result.invariant_results
        ],
        "flows": [
            {
                "id": fr.flow_id,
                "passed": fr.passed,
                "actions_run": fr.actions_run,
                "trace": fr.trace,
                "findings": _findings(fr.findings, compact),
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
            # kept for v1 compatibility: inconclusive + not_checked
            "invariants_unchecked": sum(
                1 for i in result.invariant_results if i.status in ("INCONCLUSIVE", "NOT_CHECKED")
            ),
            "invariants_inconclusive": sum(
                1 for i in result.invariant_results if i.status == "INCONCLUSIVE"
            ),
            "invariants_not_checked": sum(
                1 for i in result.invariant_results if i.status == "NOT_CHECKED"
            ),
            "flows_passed": sum(1 for fr in result.flow_results if fr.passed),
            "flows_failed": sum(1 for fr in result.flow_results if not fr.passed),
        },
    }

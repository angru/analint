from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Finding:
    severity: Severity
    location: str
    message: str


@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_name: str
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    rules_count: int = 0


@dataclass
class QueryResult:
    query_id: str
    kind: str  # Reachable | Unreachable | AlwaysHolds | NoDeadEnd | DeadActions
    status: str = "PASS"  # PASS | FAIL | INCONCLUSIVE
    findings: list[Finding] = field(default_factory=list)
    states_explored: int = 0
    trace: list[str] | None = None  # action ids from the initial state


@dataclass
class ValidationResult:
    spec_id: str
    spec_name: str
    structural_findings: list[Finding] = field(default_factory=list)
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    query_results: list[QueryResult] = field(default_factory=list)
    exploration_findings: list[Finding] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return (
            any(f.severity == Severity.ERROR for f in self.structural_findings)
            or any(not sr.passed for sr in self.scenario_results)
            or any(qr.status == "FAIL" for qr in self.query_results)
            or any(f.severity == Severity.ERROR for f in self.exploration_findings)
            or bool(self.load_errors)
        )

    @property
    def passed_count(self) -> int:
        return sum(1 for sr in self.scenario_results if sr.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for sr in self.scenario_results if not sr.passed)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.structural_findings if f.severity == Severity.WARNING)


class Reporter(Protocol):
    def report(self, result: ValidationResult) -> None: ...

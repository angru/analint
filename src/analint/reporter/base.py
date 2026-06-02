from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Severity(str, Enum):
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
class ValidationResult:
    spec_id: str
    spec_name: str
    structural_findings: list[Finding] = field(default_factory=list)
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return (
            any(f.severity == Severity.ERROR for f in self.structural_findings)
            or any(not sr.passed for sr in self.scenario_results)
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

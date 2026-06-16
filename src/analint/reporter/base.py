from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class QueryStatus(StrEnum):
    """Outcome of a single verification query.

    PASS/FAIL/INCONCLUSIVE come from the explorer. NOT_CHECKED marks a query the
    engine could not assess at all (e.g. semantics it does not yet model) — it is
    never a silent PASS. Any string outside this set is treated fail-closed.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_CHECKED = "NOT_CHECKED"


class Verdict(StrEnum):
    """Overall outcome of a run."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


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
    status: str = QueryStatus.PASS  # one of QueryStatus; unknown values fail-closed
    findings: list[Finding] = field(default_factory=list)
    states_explored: int = 0
    trace: list[str] | None = None  # action ids from the initial state
    # the witness/counterexample state key (an internal explorer tuple); kept for
    # the trace projection and NOT serialized into the public JSON.
    witness_key: Any = None


@dataclass
class InvariantResult:
    """A world invariant verified over the reachable states of the canonical
    model. PASS — held everywhere it could be evaluated; FAIL — a reachable
    state violates it (with a trace); INCONCLUSIVE — the canonical exploration
    hit its budget; NOT_CHECKED — no canonical state space to check it against,
    or the invariant was never evaluable over it."""

    invariant_id: str
    label: str
    status: str = QueryStatus.PASS  # one of QueryStatus; unknown values fail-closed
    findings: list[Finding] = field(default_factory=list)
    states_explored: int = 0
    trace: list[str] | None = None  # action ids from the initial state to the violation


@dataclass
class FlowResult:
    """An executed multi-step flow: a journey of actions and checkpoints run
    through the transition kernel. ``passed`` is True only when every action was
    accepted and every checkpoint held; ``trace`` is the action ids that ran."""

    flow_id: str
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    actions_run: int = 0  # actions executed (checkpoints are not counted)
    trace: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    spec_id: str
    spec_name: str
    structural_findings: list[Finding] = field(default_factory=list)
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    query_results: list[QueryResult] = field(default_factory=list)
    invariant_results: list[InvariantResult] = field(default_factory=list)
    flow_results: list[FlowResult] = field(default_factory=list)
    exploration_findings: list[Finding] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """True on a hard failure. NOT a success check — ``not has_errors`` still
        holds for INCONCLUSIVE/NOT_CHECKED runs; use ``is_successful`` instead."""
        return (
            any(f.severity == Severity.ERROR for f in self.structural_findings)
            or any(not sr.passed for sr in self.scenario_results)
            or any(qr.status == "FAIL" for qr in self.query_results)
            or any(ir.status == "FAIL" for ir in self.invariant_results)
            or any(not fr.passed for fr in self.flow_results)
            or any(f.severity == Severity.ERROR for f in self.exploration_findings)
            or bool(self.load_errors)
        )

    @property
    def has_inconclusive(self) -> bool:
        """A query that hit max_states or could not be assessed proved nothing —
        it must not read as green."""
        open_statuses = (QueryStatus.INCONCLUSIVE, QueryStatus.NOT_CHECKED)
        return any(qr.status in open_statuses for qr in self.query_results) or any(
            ir.status in open_statuses for ir in self.invariant_results
        )

    @property
    def verdict(self) -> Verdict:
        """Overall three-valued verdict, aggregated fail-closed.

        PASS means no failure among the checks that actually ran — NOT that the
        whole model was exhaustively verified (excluded semantics and run
        completeness are a separate concern, research/19). FAIL on any hard
        failure or any query status the engine does not recognise; INCONCLUSIVE
        when a query ran out of budget or was not assessed but nothing failed.
        """
        if self.has_errors:
            return Verdict.FAIL
        known = {QueryStatus.PASS, QueryStatus.INCONCLUSIVE, QueryStatus.NOT_CHECKED}
        unknown_status = any(qr.status not in known for qr in self.query_results) or any(
            ir.status not in known for ir in self.invariant_results
        )
        if unknown_status:
            return Verdict.FAIL  # an unrecognised status is never a silent PASS
        if self.has_inconclusive:
            return Verdict.INCONCLUSIVE
        return Verdict.PASS

    def effective_verdict(self, strict: bool = False) -> Verdict:
        """Verdict after applying invocation policy: with ``strict`` any warning
        downgrades a non-FAIL run to FAIL, so JSON, terminal and exit code agree."""
        verdict = self.verdict
        if strict and verdict is not Verdict.FAIL and self.warning_count > 0:
            return Verdict.FAIL
        return verdict

    @property
    def is_successful(self) -> bool:
        """True only on a clean PASS. Prefer this over ``not has_errors``, which
        treats INCONCLUSIVE/NOT_CHECKED as success."""
        return self.verdict is Verdict.PASS

    @property
    def passed_count(self) -> int:
        return sum(1 for sr in self.scenario_results if sr.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for sr in self.scenario_results if not sr.passed)

    @property
    def warning_count(self) -> int:
        """Every WARNING the run surfaced, across all sections — so the summary,
        ``--strict`` and the shown findings agree (not just structural ones)."""

        def _warns(findings: list[Finding]) -> int:
            return sum(1 for f in findings if f.severity == Severity.WARNING)

        return (
            _warns(self.structural_findings)
            + _warns(self.exploration_findings)
            + sum(_warns(sr.findings) for sr in self.scenario_results)
            + sum(_warns(qr.findings) for qr in self.query_results)
            + sum(_warns(ir.findings) for ir in self.invariant_results)
            + sum(_warns(fr.findings) for fr in self.flow_results)
        )


class Reporter(Protocol):
    def report(self, result: ValidationResult) -> None: ...

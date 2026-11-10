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


class Code(StrEnum):
    """Stable diagnostic identifiers (issue #5).

    A code names the *kind* of a finding; the message is human text and may be
    reworded. Within ``analint.check/v1`` a code value is never renamed or reused
    for a different kind; new codes may be added. Documented in docs/cli.md.
    """

    # structural validation
    EMPTY_MODEL = "structural.empty_model"
    MISSING_ID = "structural.missing_id"
    DUPLICATE_ID = "structural.duplicate_id"
    DUPLICATE_CLASS = "structural.duplicate_class"
    UNREGISTERED = "structural.unregistered"
    STALE_REFERENCE = "structural.stale_reference"
    INVALID_ENTRY = "structural.invalid_entry"
    SCOPE_MISUSE = "structural.scope_misuse"
    UNBOUND_VARIABLE = "structural.unbound_variable"
    EFFECT_CONFLICT = "structural.effect_conflict"
    UNKNOWN_FIELD = "structural.unknown_field"
    LIFECYCLE_UNATTACHED = "structural.lifecycle_unattached"
    TERMINAL_TRANSITION = "structural.terminal_transition"
    UNREACHABLE_LIFECYCLE_STATE = "structural.unreachable_lifecycle_state"
    NO_SCENARIOS = "structural.no_scenarios"
    MISSING_GIVEN = "structural.missing_given"
    DUPLICATE_GIVEN = "structural.duplicate_given"
    EMPTY_FLOW = "structural.empty_flow"
    PAYLOAD_BINDING = "structural.payload_binding"
    PAYLOAD_TYPE_MISMATCH = "structural.payload_type_mismatch"
    CONFLICTING_ROOTS = "structural.conflicting_roots"
    INVALID_INITIAL = "structural.invalid_initial"
    # model loading
    UNLOADED_FILE = "model.unloaded_file"
    ORPHAN = "model.orphan"
    CANONICAL_INITIAL_ERROR = "model.canonical_initial_error"
    # one transition (scenarios, flows, exploration)
    PRE_FAILED = "transition.pre_failed"
    PRE_NOT_APPLICABLE = "transition.pre_not_applicable"
    PRESENCE_REJECTED = "transition.presence_rejected"
    TERMINAL_LOCKED = "transition.terminal_locked"
    EVALUATION_ERROR = "transition.evaluation_error"
    FIELD_CONSTRAINT = "transition.field_constraint"
    UNDECLARED_LIFECYCLE_EDGE = "transition.undeclared_lifecycle_edge"
    POSTCONDITION_VIOLATED = "transition.postcondition_violated"
    # exploration
    ACTION_EXCLUDED = "exploration.action_excluded"
    UNSUPPORTED_VALUE = "exploration.unsupported_value"
    # invariants
    INVARIANT_VIOLATED = "invariant.violated"
    INVARIANT_EVALUATION_ERROR = "invariant.evaluation_error"
    INVARIANT_NOT_CHECKED = "invariant.not_checked"
    # scenarios
    EXPECTED_REJECTION = "scenario.expected_rejection"
    NOT_REJECTED = "scenario.not_rejected"
    THEN_FAILED = "scenario.then_failed"
    THEN_EVALUATION_ERROR = "scenario.then_evaluation_error"
    EVENT_NOT_EMITTED = "scenario.event_not_emitted"
    # flows
    STEP_NOT_RUN = "flow.step_not_run"
    FLOW_INVARIANT_VIOLATED = "flow.invariant_violated"
    CHECKPOINT_FAILED = "flow.checkpoint_failed"
    CHECKPOINT_EVALUATION_ERROR = "flow.checkpoint_evaluation_error"
    CHECKPOINT_EVENT_NOT_EMITTED = "flow.event_not_emitted"
    # queries
    QUERY_INVALID = "query.invalid"
    QUERY_EVALUATION_ERROR = "query.evaluation_error"
    QUERY_VACUOUS = "query.vacuous"
    WITNESS = "query.witness"
    HOLDS = "query.holds"
    REACHED_FORBIDDEN = "query.reached_forbidden"
    NOT_REACHABLE = "query.not_reachable"
    PROPERTY_VIOLATED = "query.property_violated"
    DEAD_END = "query.dead_end"
    GOAL_UNREACHABLE = "query.goal_unreachable"
    DEAD_ACTIONS = "query.dead_actions"
    NOT_ASSESSED = "query.not_assessed"
    UNDECIDED = "query.undecided"
    INITIAL_STATE = "query.initial_state"
    # budget / completeness of a check
    BUDGET_EXHAUSTED = "check.budget_exhausted"
    EXCLUDED_ACTIONS = "check.excluded_actions"
    # TLC backend
    TLC_UNAVAILABLE = "tlc.unavailable"
    TLC_NO_INVARIANT_FORM = "tlc.no_invariant_form"
    TLC_NOT_EXPORTED = "tlc.not_exported"
    TLC_FAILED = "tlc.failed"
    TLC_TRANSITION_DEFECT = "tlc.transition_defect"
    TLC_DECIDED = "tlc.decided"


@dataclass
class Finding:
    severity: Severity
    location: str
    message: str
    code: Code
    # True only on the rejection reason inside a passing Expect.FAIL scenario:
    # the action was blocked as intended, so the ERROR is not actionable.
    expected: bool = False

    def to_dict(self) -> dict:
        data = {
            "severity": self.severity.value,
            "code": self.code.value,
            "location": self.location,
            "message": self.message,
        }
        if self.expected:
            data["expected"] = True
        return data


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
    # the slice the query was checked on (research/34 §5); None = whole model
    slice: dict | None = None
    backend: str | None = None  # "tlc" when `check --tlc` decided it (research/36 R6)
    # Wall time spent by this check, including exploration on cache misses.
    # Shared work is charged only when performed; None means not measured.
    elapsed_ms: float | None = None


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
    slice: dict | None = None  # the slice it was checked on; None = whole model
    backend: str | None = None  # "tlc" when `check --tlc` decided it (research/36 R6)
    elapsed_ms: float | None = None  # includes both passes when a slice is rechecked
    witness_key: Any = None  # internal state key for state-diff traces; not serialized


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

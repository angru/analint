"""Decide checks analint left INCONCLUSIVE with TLC (``check --tlc``, research/36 R6).

Each undecided invariant or Reachable/Unreachable/AlwaysHolds query is exported
on the slice analint explored it on (``validator/slicing.py``) — the same
roots, actions, invariants and frozen fields — and TLC runs it to completion.
A TLC answer replaces the INCONCLUSIVE one and says so (``backend: "tlc"``).
NoDeadEnd (recoverability, a branching-time property) and DeadActions have no
TLC invariant form and stay as analint left them.
"""

from __future__ import annotations

from analint.backends.tla import ExportError, Target, TlaExport, _outside_refs, export_tla
from analint.backends.tlc import TlcResult, TlcUnavailable, find_tlc, run_tlc
from analint.models.invariant import Invariant
from analint.models.query import AlwaysHolds, Reachable, Unreachable
from analint.models.root import Spec
from analint.models.scope import InstanceField
from analint.reporter.base import (
    Finding,
    InvariantResult,
    QueryResult,
    QueryStatus,
    Severity,
    ValidationResult,
)
from analint.validator.explorer import resolve_query_initials
from analint.validator.slicing import Slice, SliceAnalysis


def decide_with_tlc(
    spec: Spec,
    result: ValidationResult,
    analysis: SliceAnalysis | None,
    canonical_initials: list[dict] | None,
    *,
    timeout: float | None = None,
) -> None:
    undecided_invariants = [r for r in result.invariant_results if r.status == "INCONCLUSIVE"]
    undecided_queries = [r for r in result.query_results if r.status == "INCONCLUSIVE"]
    if not undecided_invariants and not undecided_queries:
        return
    try:
        find_tlc()
    except TlcUnavailable as exc:
        result.exploration_findings.append(
            Finding(Severity.WARNING, f"spec:{spec.id}", f"--tlc: {exc}")
        )
        return

    invariants = {inv.id: inv for inv in spec.invariants}
    for res in undecided_invariants:
        inv = invariants.get(res.invariant_id)
        if inv is None or canonical_initials is None:
            continue
        piece = analysis.invariant_slice(inv) if analysis is not None else None
        _decide_invariant(spec, res, inv, piece, analysis, canonical_initials, timeout)

    queries = {q.id: q for q in spec.queries}
    for res in undecided_queries:
        query = queries.get(res.query_id)
        if not isinstance(query, (Reachable, Unreachable, AlwaysHolds)):
            res.findings.append(
                Finding(
                    Severity.INFO,
                    f"query:{res.query_id}",
                    f"--tlc: {type(query).__name__} has no TLC invariant form",
                )
            )
            continue
        initials, _ = resolve_query_initials(query, spec)
        if initials is None:
            continue
        piece = None
        if analysis is not None:
            canonical = not (query.given or query.given_any or query.initial is not None)
            piece = analysis.predicate_slice(query.predicate, canonical=canonical)
        _decide_query(spec, res, query, piece, analysis, initials, timeout)


def _exported(
    spec: Spec,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    target: Target,
) -> TlaExport:
    if analysis is None or piece is None or piece.vars is None:
        return export_tla(spec, initials, target=target)
    roots, _, inert = analysis.project_roots(piece, initials)
    return export_tla(analysis.sliced_spec(piece), roots, target=target, inert=inert)


def _run(
    spec: Spec,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    target: Target,
    timeout: float | None,
    loc: str,
    findings: list[Finding],
) -> TlcResult | None:
    try:
        export = _exported(spec, piece, analysis, initials, target)
    except ExportError as exc:
        findings.append(Finding(Severity.INFO, loc, f"--tlc: not exported — {exc}"))
        return None
    outcome = run_tlc(export, timeout=timeout)
    if outcome.status == "error":
        detail = next(
            (line for line in outcome.output.splitlines() if "Error" in line), outcome.output[-300:]
        )
        findings.append(Finding(Severity.WARNING, loc, f"--tlc: TLC failed — {detail}"))
        return None
    if outcome.violated and outcome.violated.startswith("NoDefect_"):
        action = outcome.violated.removeprefix("NoDefect_")
        findings.append(
            Finding(
                Severity.ERROR,
                loc,
                f"--tlc: a transition defect (hard Field bound, undeclared lifecycle "
                f"edge or false post) is reachable in {action}: "
                f"{' → '.join(outcome.trace) or '(initial state)'}",
            )
        )
        return None
    return outcome


def _note(outcome: TlcResult) -> Finding:
    return Finding(
        Severity.INFO,
        "backend:tlc",
        f"decided by TLC: {outcome.distinct_states} distinct states, {outcome.seconds:.1f}s",
    )


def _decide_invariant(
    spec: Spec,
    res: InvariantResult,
    inv: Invariant,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    timeout: float | None,
) -> None:
    loc = f"invariant:{inv.id}"
    outcome = _run(
        spec, piece, analysis, initials, Target("holds", inv.expression), timeout, loc, res.findings
    )
    if outcome is None:
        return
    res.backend = "tlc"
    res.states_explored = outcome.distinct_states or 0
    if outcome.status == "violation":
        res.status = QueryStatus.FAIL
        res.trace = outcome.trace
        res.findings = [
            Finding(
                Severity.ERROR,
                loc,
                f"invariant '{res.label}' is violated (TLC): "
                f"{' → '.join(outcome.trace) or '(initial state)'}",
            ),
            _note(outcome),
        ]
        return
    # no violation: it holds wherever applicable — is it applicable anywhere?
    scoped = any(isinstance(r, InstanceField) for r in _outside_refs(inv.expression))
    if scoped:
        witness = _run(
            spec,
            piece,
            analysis,
            initials,
            Target("applicable", inv.expression),
            timeout,
            loc,
            res.findings,
        )
        if witness is None:
            return
        if witness.status == "ok":
            res.status = QueryStatus.NOT_CHECKED
            res.findings = [
                Finding(Severity.WARNING, loc, "not checked: never evaluable (TLC)"),
                _note(outcome),
            ]
            return
    res.status = QueryStatus.PASS
    res.findings = [_note(outcome)]


def _decide_query(
    spec: Spec,
    res: QueryResult,
    query: Reachable | Unreachable | AlwaysHolds,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    timeout: float | None,
) -> None:
    loc = f"query:{res.query_id}"
    kind = "always" if isinstance(query, AlwaysHolds) else "never"
    outcome = _run(
        spec, piece, analysis, initials, Target(kind, query.predicate), timeout, loc, res.findings
    )
    if outcome is None:
        return
    res.backend = "tlc"
    res.states_explored = outcome.distinct_states or 0
    found = outcome.status == "violation"
    text = query.label or res.query_id
    if isinstance(query, Reachable):
        res.status = QueryStatus.PASS if found else QueryStatus.FAIL
        message = (
            f"'{text}' reachable (TLC): {' → '.join(outcome.trace) or '(initial state)'}"
            if found
            else f"'{text}' is not reachable in any explored state (TLC)"
        )
    else:
        res.status = QueryStatus.FAIL if found else QueryStatus.PASS
        message = (
            f"'{text}' breaks (TLC): {' → '.join(outcome.trace) or '(initial state)'}"
            if found
            else f"'{text}' holds in every explored state (TLC)"
        )
    res.trace = outcome.trace if found else None
    severity = Severity.ERROR if res.status == QueryStatus.FAIL else Severity.INFO
    res.findings = [Finding(severity, loc, message), _note(outcome)]

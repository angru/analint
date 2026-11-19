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
    Code,
    Finding,
    InvariantResult,
    QueryResult,
    QueryStatus,
    Severity,
    ValidationResult,
)
from analint.validator.explorer import (
    _invalid_root_finding,
    render_state,
    resolve_query_initials,
    state_key,
)
from analint.validator.slicing import Slice, SliceAnalysis
from analint.validator.state_checks import check_invariants


def decide_with_tlc(
    spec: Spec,
    result: ValidationResult,
    analysis: SliceAnalysis | None,
    canonical_initials: list[dict] | None,
    *,
    timeout: float | None = None,
    defect_actions: dict[str, set[str]] | None = None,
) -> None:
    undecided_invariants = [r for r in result.invariant_results if r.status == "INCONCLUSIVE"]
    undecided_queries = [r for r in result.query_results if r.status == "INCONCLUSIVE"]
    if not undecided_invariants and not undecided_queries:
        return
    try:
        find_tlc()
    except TlcUnavailable as exc:
        result.exploration_findings.append(
            Finding(Severity.WARNING, f"spec:{spec.id}", f"--tlc: {exc}", Code.TLC_UNAVAILABLE)
        )
        return

    invariants = {inv.id: inv for inv in spec.invariants}
    for res in undecided_invariants:
        inv = invariants.get(res.invariant_id)
        if inv is None or canonical_initials is None:
            continue
        piece = analysis.invariant_slice(inv) if analysis is not None else None
        _decide_invariant(
            spec,
            res,
            inv,
            piece,
            analysis,
            canonical_initials,
            timeout,
            defect_actions.get(f"invariant:{inv.id}") if defect_actions is not None else None,
        )

    queries = {q.id: q for q in spec.queries}
    for res in undecided_queries:
        query = queries.get(res.query_id)
        if not isinstance(query, (Reachable, Unreachable, AlwaysHolds)):
            res.findings.append(
                Finding(
                    Severity.INFO,
                    f"query:{res.query_id}",
                    f"--tlc: {type(query).__name__} has no TLC invariant form",
                    Code.TLC_NO_INVARIANT_FORM,
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
        _decide_query(
            spec,
            res,
            query,
            piece,
            analysis,
            initials,
            timeout,
            defect_actions.get(f"query:{query.id}") if defect_actions is not None else None,
        )


def _exported(
    spec: Spec,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    target: Target,
    defect_actions: set[str] | None = None,
) -> TlaExport:
    if analysis is None or piece is None or piece.vars is None:
        return export_tla(spec, initials, target=target, defect_actions=defect_actions)
    roots, _, inert = analysis.project_roots(piece, initials)
    return export_tla(
        analysis.sliced_spec(piece),
        roots,
        target=target,
        inert=inert,
        defect_actions=defect_actions,
    )


def _run(
    spec: Spec,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    target: Target,
    timeout: float | None,
    loc: str,
    findings: list[Finding],
    defect_actions: set[str] | None = None,
) -> TlcResult | None:
    try:
        export = _exported(spec, piece, analysis, initials, target, defect_actions)
    except ExportError as exc:
        findings.append(
            Finding(Severity.INFO, loc, f"--tlc: not exported — {exc}", Code.TLC_NOT_EXPORTED)
        )
        return None
    outcome = run_tlc(export, timeout=timeout)
    if outcome.status == "error":
        detail = next(
            (line for line in outcome.output.splitlines() if "Error" in line), outcome.output[-300:]
        )
        findings.append(
            Finding(Severity.WARNING, loc, f"--tlc: TLC failed — {detail}", Code.TLC_FAILED)
        )
        return None
    if outcome.violated and outcome.violated.startswith("NoDefect_"):
        name = outcome.violated.removeprefix("NoDefect_")
        action = export.actions.get(name, name)
        attempted = [*(outcome.trace or ["(initial state)"]), action]
        findings.append(
            Finding(
                Severity.ERROR,
                loc,
                f"--tlc: a transition defect (hard Field bound, undeclared lifecycle "
                f"edge, false post or invalid emitted payload) is reachable in {action}: "
                f"{' → '.join(attempted)}",
                Code.TLC_TRANSITION_DEFECT,
            )
        )
        return None
    return outcome


def _note(outcome: TlcResult) -> Finding:
    return Finding(
        Severity.INFO,
        "backend:tlc",
        f"decided by TLC: {outcome.distinct_states} distinct states, {outcome.seconds:.1f}s",
        Code.TLC_DECIDED,
    )


def _decide_invariant(
    spec: Spec,
    res: InvariantResult,
    inv: Invariant,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    timeout: float | None,
    defect_actions: set[str] | None = None,
) -> None:
    loc = f"invariant:{inv.id}"
    outcome = _run(
        spec,
        piece,
        analysis,
        initials,
        Target("holds", inv.expression),
        timeout,
        loc,
        res.findings,
        defect_actions,
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
                Code.INVARIANT_VIOLATED,
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
            defect_actions,
        )
        if witness is None:
            return
        if witness.status == "ok":
            res.status = QueryStatus.NOT_CHECKED
            res.findings = [
                Finding(
                    Severity.WARNING,
                    loc,
                    "not checked: never evaluable (TLC)",
                    Code.INVARIANT_NOT_CHECKED,
                ),
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
    defect_actions: set[str] | None = None,
) -> None:
    if isinstance(query, Reachable) and len(initials) > 1:
        _decide_reachable_roots(
            spec, res, query, piece, analysis, initials, timeout, defect_actions
        )
        return
    loc = f"query:{res.query_id}"
    kind = "always" if isinstance(query, AlwaysHolds) else "never"
    outcome = _run(
        spec,
        piece,
        analysis,
        initials,
        Target(kind, query.predicate),
        timeout,
        loc,
        res.findings,
        defect_actions,
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
    if isinstance(query, Reachable):
        code = Code.WITNESS if found else Code.NOT_REACHABLE
    elif not found:
        code = Code.HOLDS
    else:
        code = Code.PROPERTY_VIOLATED if isinstance(query, AlwaysHolds) else Code.REACHED_FORBIDDEN
    finding = Finding(severity, loc, message, code)
    if (
        isinstance(query, Reachable)
        and not found
        and check_invariants(spec, initials[0], "initial")
    ):
        finding = _invalid_root_finding(res.query_id, 1)
    res.findings = [finding, _note(outcome)]


def _decide_reachable_roots(
    spec: Spec,
    res: QueryResult,
    query: Reachable,
    piece: Slice | None,
    analysis: SliceAnalysis | None,
    initials: list[dict],
    timeout: float | None,
    defect_actions: set[str] | None,
) -> None:
    """An existential TLC witness must be obtained for each projected root.

    One union-of-roots invariant run only establishes existence from *some*
    root. Retain the existing representative action trace without claiming it
    proves the other roots. An undecided run leaves the query inconclusive unless
    an earlier root already refuted it.
    """
    roots, numbers = initials, list(range(1, len(initials) + 1))
    if analysis is not None and piece is not None:
        roots, numbers, _ = analysis.project_roots(piece, initials)
    seen = set()
    outcomes = []
    invalid_failure = None
    legal_failure = None
    invalid_numbers: set[int] = set()
    added_findings_start = len(res.findings)
    loc = f"query:{res.query_id}"
    text = query.label or res.query_id
    for root, number in zip(roots, numbers, strict=True):
        key = state_key(root)
        if key in seen:
            continue
        seen.add(key)
        outcome = _run(
            spec,
            piece,
            analysis,
            [root],
            Target("never", query.predicate),
            timeout,
            loc,
            res.findings,
            defect_actions,
        )
        if outcome is None:
            if invalid_failure is not None:
                break  # keep the known FAIL and the new backend/defect diagnostic
            return
        outcomes.append((number, root, outcome))
        if outcome.status == "ok":
            if check_invariants(spec, root, "initial"):
                invalid_numbers.add(number)
                if invalid_failure is None:
                    invalid_failure = outcomes[-1]
                continue  # retain ordinary missing-path evidence for legal roots
            legal_failure = outcomes[-1]
            break

    decisive = legal_failure or invalid_failure or outcomes[-1]
    number, root, last = decisive
    found = last.status == "violation"
    representative_number, representative_root, representative = outcomes[0]
    if found:
        number, root = representative_number, representative_root
    res.backend = "tlc"
    res.status = QueryStatus.PASS if found else QueryStatus.FAIL
    res.states_explored = sum(outcome.distinct_states or 0 for _, _, outcome in outcomes)
    res.trace = representative.trace if found else None
    message = (
        f"'{text}' reachable from all {len(outcomes)} initial states (TLC); "
        f"representative witness from init #{number}: "
        f"{' → '.join(representative.trace) or '(initial state)'}"
        if found
        else f"'{text}' is not reachable from init #{number} (TLC)"
    )
    rendered = ", ".join(f"{k}={v}" for k, v in render_state(root).items())
    res.findings = [
        Finding(
            Severity.INFO if found else Severity.ERROR,
            loc,
            message,
            Code.WITNESS if found else Code.NOT_REACHABLE,
        )
        if number not in invalid_numbers
        else _invalid_root_finding(res.query_id, number),
        Finding(Severity.INFO, loc, f"init #{number}: {rendered}", Code.INITIAL_STATE),
        *res.findings[added_findings_start:],
        *[_note(outcome) for _, _, outcome in outcomes],
    ]

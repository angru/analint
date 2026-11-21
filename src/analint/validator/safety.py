"""One-sided safety proofs before requesting invariant-pruning support.

This analysis is deliberately separate from constrained exploration bookkeeping:
canonical invariant trust must never make a speculative own-root graph exact.
Only a clean PASS leaves this module. Every other attempt uses the ordinary
constrained pipeline, including counterexamples found beyond an invariant cut.
"""

from dataclasses import dataclass

from analint.models.query import AlwaysHolds, Unreachable, query_budget
from analint.models.root import Query, Spec
from analint.reporter.base import QueryResult, QueryStatus, Severity
from analint.validator.explorer import (
    Exploration,
    ExplorationStorage,
    _evaluate,
    cover_actions,
    explore_slice,
    resolve_query_initials,
)
from analint.validator.slicing import Slice, SliceAnalysis
from analint.validator.state_checks import check_invariants


@dataclass
class SafetyProof:
    result: QueryResult
    exploration: Exploration
    piece: Slice
    initials: list[dict]
    projected_coverage: tuple[Exploration, ...] = ()


def prove_query(
    query: Query,
    spec: Spec,
    analysis: SliceAnalysis,
    *,
    max_states: int | None = None,
    tlc: bool = False,
    tlc_timeout: float | None = None,
) -> SafetyProof | None:
    if not isinstance(query, (AlwaysHolds, Unreachable)):
        return None
    piece = analysis.predicate_slice(query.predicate, canonical=False, unconstrained=True)
    if piece.vars is None:
        return None  # unknown AST: retain the whole-model fallback and its support
    initials, _ = resolve_query_initials(query, spec)
    if initials is None or any(check_invariants(spec, ctx, "initial") for ctx in initials):
        return None  # do not prove a property by projecting away an illegal root
    budget = query_budget(query, spec.max_states, max_states)
    probe = None
    if isinstance(query, Unreachable):
        from analint.validator.derived_proof import attempt, cover_defects

        probe = attempt(query, analysis, piece, initials, budget)
        blocked = probe.blocked_actions(piece) if probe is not None else ()
        exact_coverage = (
            cover_actions(
                analysis, initials, budget, ExplorationStorage(), canonical=False, actions=blocked
            )
            if blocked
            else {}
        )
        cleared = probe is not None and probe.covered_by(blocked, exact_coverage)
        if probe is not None and (probe.proved or cleared):
            coverage = list(exact_coverage.values())
            for action in piece.actions:
                if id(action) in exact_coverage:
                    continue
                certificate = cover_defects(
                    action, analysis, piece, initials, budget, canonical=False
                )
                if certificate is None:
                    break
                coverage.append(certificate[1])
            else:
                assert isinstance(probe.result, QueryResult)
                probe.result.model = probe.report(covered=blocked if cleared else ())
                return SafetyProof(probe.result, probe.graph, piece, initials, tuple(coverage))
    exp, used = explore_slice(
        analysis,
        piece,
        initials,
        budget,
        ExplorationStorage(),
    )
    if exp.excluded or any(f.severity == Severity.ERROR for f in exp.findings):
        return None
    result = _evaluate(query, query.id, exp, spec)
    if probe is not None:
        result.model = probe.report(result, budget, exact_graph=exp)
    if result.status == QueryStatus.INCONCLUSIVE and tlc:
        from analint.backends.tlc import TlcUnavailable, find_tlc
        from analint.validator.tlc_fallback import _decide_query, _record_exact_backend

        try:
            find_tlc()
        except TlcUnavailable:
            return None  # the ordinary fallback reports backend unavailability
        _decide_query(
            spec,
            result,
            query,
            used,
            analysis,
            initials,
            tlc_timeout,
            {action.id for action in used.actions},
        )
        _record_exact_backend(result, tlc_timeout)
    if result.status != QueryStatus.PASS:
        return None
    result.slice = used.summary()
    return SafetyProof(result, exp, used, initials)

"""Application service: explore a spec's canonical or query-specific state space
and return one ``analint.exploration/v1`` artifact (P4.2).

It reuses the shared model-preparation (`prepare_model`) so validation and
exploration see an identical Spec, and the single query-initial interpretation
(`resolve_query_initials`) so there is no second reading of `given`/`given_any`/
`initial`. It never returns an empty successful artifact: a load failure, a
structural error, an unknown query id or an unbuildable initial raises
``ExplorationError``.
"""

from __future__ import annotations

from pathlib import Path

from analint.reporter.base import Severity
from analint.reporter.exploration_artifact import ExplorationArtifact, canonical_digest
from analint.validator.artifact_builder import (
    _changes,
    _render_state,
    build_exploration_artifact,
    build_summary_artifact,
)
from analint.validator.engine import prepare_model
from analint.validator.explorer import (
    Exploration,
    build_canonical_initials,
    explore,
    resolve_query_initials,
    run_query,
    verify_invariants,
)
from analint.validator.slicing import SliceAnalysis


class ExplorationError(Exception):
    """A structured reason an exploration could not be produced."""

    def __init__(self, kind: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "analint.error/v1",
            "error": self.message,
            "kind": self.kind,
            "details": self.details,
        }


def explore_path(
    path: str | Path,
    *,
    query_id: str | None = None,
    what_if: str | Path | None = None,
    include_graph: bool = True,
) -> ExplorationArtifact:
    prepared = prepare_model(Path(path), what_if=Path(what_if) if what_if else None)
    if prepared.spec is None:
        raise ExplorationError(
            "load", "the spec could not be loaded", [str(e) for e in prepared.load_errors]
        )
    if prepared.has_structural_errors:
        raise ExplorationError(
            "structural",
            "the spec has structural errors",
            [f.message for f in prepared.structural_findings if f.severity is Severity.ERROR],
        )

    spec = prepared.spec
    if query_id is None:
        initials, error = build_canonical_initials(spec)
        source_kind, budget = "canonical", spec.max_states
    else:
        query = next((q for q in spec.queries if q.id == query_id), None)
        if query is None:
            raise ExplorationError(
                "unknown_query",
                f"no query with id '{query_id}'",
                sorted(q.id for q in spec.queries if q.id),
            )
        initials, error = resolve_query_initials(query, spec)
        source_kind, budget = "query", query.max_states

    if not initials:
        raise ExplorationError("unbuildable", error or "could not build an initial state")

    exp = explore(spec, initials, budget)
    if not include_graph:
        return build_summary_artifact(
            exp,
            spec,
            source_kind=source_kind,
            query_id=query_id,
            max_states=budget,
            graph_omitted_reason="compact projection — request the full graph explicitly",
        )
    return build_exploration_artifact(
        exp, spec, source_kind=source_kind, query_id=query_id, max_states=budget
    )


def trace_query(
    path: str | Path,
    query_id: str,
    *,
    what_if: str | Path | None = None,
    sliced: bool = True,
) -> dict[str, object]:
    """The witness/counterexample of a query or invariant as states and changes
    (schema-aligned with the artifact's node ids). A passing property with no
    example returns ``witness: None`` and an explanatory message — not an error.
    The property is decided exactly as ``check`` decides it (budgets, slices
    and the invariant trust a query slice relies on; ``sliced=False`` for the
    whole model), so a witness/counterexample found on a slice is traceable
    even when the whole model exceeds the budget; fields outside the slice
    (listed under ``slice``) then keep their initial values. Query payloads
    retain their ``query`` key; invariant payloads use ``invariant`` instead."""
    prepared = prepare_model(Path(path), what_if=Path(what_if) if what_if else None)
    if prepared.spec is None:
        raise ExplorationError(
            "load", "the spec could not be loaded", [str(e) for e in prepared.load_errors]
        )
    if prepared.has_structural_errors:
        raise ExplorationError(
            "structural",
            "the spec has structural errors",
            [f.message for f in prepared.structural_findings if f.severity is Severity.ERROR],
        )

    spec = prepared.spec
    query = next((q for q in spec.queries if q.id == query_id), None)
    invariant = next((inv for inv in spec.invariants if inv.id == query_id), None)
    if query is not None and invariant is not None:
        raise ExplorationError(
            "ambiguous_property",
            f"'{query_id}' names both a query and an invariant; give them distinct ids",
        )
    if query is None and invariant is None:
        raise ExplorationError(
            "unknown_query",
            f"no query or invariant with id '{query_id}'",
            sorted(p.id for p in [*spec.queries, *spec.invariants] if p.id),
        )
    initials, error = (
        resolve_query_initials(query, spec) if query is not None else build_canonical_initials(spec)
    )
    if not initials:
        raise ExplorationError("unbuildable", error or "could not build an initial state")

    # Decide the property exactly as check does: the same slices, and for a
    # query the invariant trust check establishes first, so the witness key and
    # the parent walk share the one exploration the verdict came from.
    cache: dict = {}
    decided: dict[str, Exploration] = {}
    analysis = SliceAnalysis(spec) if sliced else None
    invariant_results: list = []
    if spec.invariants and (analysis is not None or invariant is not None):
        canonical, canonical_error = (
            (initials, None) if invariant is not None else build_canonical_initials(spec)
        )
        invariant_results, _ = verify_invariants(
            spec,
            canonical,
            build_error=canonical_error,
            max_states=spec.max_states,
            cache=cache,
            analysis=analysis,
            explorations=decided,
        )
    if query is not None:
        result = run_query(query, spec, cache, analysis=analysis, explorations=decided)
        source_kind, kind = "query", result.kind
    else:
        assert invariant is not None  # the id lookup above rejected an unknown property
        result = next(r for r in invariant_results if r.invariant_id == invariant.id)
        source_kind, kind = "invariant", "Invariant"
    exp = decided.get(query_id)
    if result.witness_key is None or exp is None:
        return {
            "schema": "analint.trace/v1",
            source_kind: query_id,
            "status": result.status,
            "root": None,
            "steps": [],
            "final_state": {},
            "witness": None,
            "message": (
                f"{kind} '{query_id}' is INCONCLUSIVE: the budget ran out before a "
                f"witness/counterexample was found"
                if result.status == "INCONCLUSIVE"
                else f"{kind} '{query_id}' has no witness/counterexample to trace"
            ),
        }
    trace = _build_trace(query_id, result.status, result.witness_key, exp, source_kind=source_kind)
    if getattr(result, "slice", None):
        trace["slice"] = result.slice
    return trace


def _build_trace(
    query_id: str,
    status: str,
    witness_key: object,
    exp: Exploration,
    *,
    source_kind: str = "query",
) -> dict:
    rendered: dict = {}

    def render(key: object) -> dict:
        if key not in rendered:
            rendered[key] = _render_state(exp.states[key])
        return rendered[key]

    def node(key: object) -> str:
        return canonical_digest(render(key))

    steps_back: list[tuple] = []
    cur = witness_key
    while True:
        prev, action_id = exp.parents[cur]
        if prev is None:
            root_key = cur
            break
        steps_back.append((prev, action_id, cur))
        cur = prev

    steps = [
        {
            "action": action_id,
            "source": node(src),
            "target": node(tgt),
            "changes": _changes(render(src), render(tgt)),
        }
        for src, action_id, tgt in reversed(steps_back)
    ]
    return {
        "schema": "analint.trace/v1",
        source_kind: query_id,
        "status": status,
        "root": {"index": exp.roots.get(root_key, 1), "node": node(root_key)},
        "steps": steps,
        "final_state": render(witness_key),
    }

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
from analint.reporter.exploration_artifact import ExplorationArtifact
from analint.validator.artifact_builder import build_exploration_artifact
from analint.validator.engine import prepare_model
from analint.validator.explorer import build_canonical_initials, explore, resolve_query_initials


class ExplorationError(Exception):
    """A structured reason an exploration could not be produced."""

    def __init__(self, kind: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict[str, object]:
        return {"error": self.message, "kind": self.kind, "details": self.details}


def explore_path(
    path: str | Path,
    *,
    query_id: str | None = None,
    what_if: str | Path | None = None,
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
    return build_exploration_artifact(
        exp, spec, source_kind=source_kind, query_id=query_id, max_states=budget
    )

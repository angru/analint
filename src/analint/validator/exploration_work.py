"""Invocation-local accounting at native BFS and TLC boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from analint.models.query import query_budget
from analint.reporter.base import QueryResult

if TYPE_CHECKING:
    from analint.models.root import Query, Spec
    from analint.reporter.base import ValidationResult
    from analint.validator.explorer import Exploration


class ExplorationWork:
    def __init__(self) -> None:
        self.phase = "canonical"
        self.root_source = "canonical"
        self.graphs: list[dict] = []
        self.tlc_runs: list[dict] = []
        self.ids: WeakKeyDictionary[Exploration, int] = WeakKeyDictionary()
        self.native_results: dict[str, int | None] = {}

    def query_phase(self, query: Query) -> None:
        from analint.validator.derived_proof import root_source

        self.phase = f"query:{query.id}"
        self.root_source = root_source(query)

    def native(self, exp: Exploration, budget: int, *, projected: bool, origin: str) -> None:
        number = len(self.graphs) + 1
        self.ids[exp] = number
        self.graphs.append(
            {
                "id": number,
                "phase": self.phase,
                "root_source": self.root_source,
                "roots": len(exp.roots),
                "budget": budget,
                "projection": projected,
                "origin": origin,
                "states": exp.state_count,
                "complete": not exp.capped and not exp.excluded,
                "capped": exp.capped,
                "excluded_actions": len(exp.excluded),
            }
        )

    def link(self, prop: str, graph: Exploration | None) -> None:
        self.native_results[prop] = self.ids.get(graph) if graph is not None else None

    def report(
        self, result: ValidationResult, spec: Spec | None, budget: int | None, tlc: bool
    ) -> dict:
        from analint.validator.derived_proof import root_source

        properties = {}
        if spec is not None:
            queries = {q.id or type(q).__name__: q for q in spec.queries}
            for check in [*result.invariant_results, *result.query_results]:
                if isinstance(check, QueryResult):
                    name = f"query:{check.query_id}"
                    query = queries[check.query_id]
                    source, limit = root_source(query), query_budget(query, spec.max_states, budget)
                else:
                    name = f"invariant:{check.invariant_id}"
                    source, limit = "canonical", budget or spec.max_states
                properties[name] = {
                    "root_source": source,
                    "budget": limit,
                    "reported_states": check.states_explored,
                    "backend": check.backend or "native",
                    "native_graph_id": self.native_results.get(name),
                }
        native_states = sum(g["states"] for g in self.graphs if g["origin"] == "built")
        tlc_states = [run["distinct_states"] for run in self.tlc_runs]
        return {
            "native_graphs": self.graphs,
            "native_states_built": native_states,
            "total_search_states": None if None in tlc_states else native_states + sum(tlc_states),
            "tlc_requested": tlc,
            "max_reported_states_per_check": max(
                (p["reported_states"] for p in properties.values()), default=None
            ),
            "properties": properties,
            "tlc_runs": self.tlc_runs,
        }


current_work: ContextVar[ExplorationWork | None] = ContextVar(
    "analint_exploration_work", default=None
)


@contextmanager
def measure_work(enabled: bool) -> Iterator[ExplorationWork | None]:
    work = ExplorationWork() if enabled else None
    token = current_work.set(work)
    try:
        yield work
    finally:
        current_work.reset(token)

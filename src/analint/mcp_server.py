"""MCP server exposing the analint spec to AI agents.

Five tools over the same core as the CLI:
  - check(path, what_if?)    — validate the spec, optionally with a hypothesis patch
  - explore(path, query?, …) — bounded reachability exploration artifact
  - trace(path, query)       — a query or invariant's witness/counterexample as state changes
  - show(path, kind?, name?) — overview, a kind's ids, or details of one object
  - affects(target, path)    — impact analysis for a field / entity / action

Run: `analint-mcp` (stdio transport). Requires the optional dependency:
`pip install analint[mcp]`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analint import query as q
from analint.mcp_worker import isolated_request
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import build_spec, validate
from analint.validator.selection import SelectionError


@isolated_request
def check_spec(
    path: str = ".",
    what_if: str | None = None,
    max_states: int | None = None,
    slice: bool = True,
    tlc: bool = False,
    cache: bool = False,
    compact: bool = False,
    checks: list[str] | None = None,
    scenario_ids: list[str] | None = None,
    tags: list[str] | None = None,
    tlc_timeout: float | None = None,
    explain_slice: bool = False,
) -> dict:
    if max_states is not None and max_states < 1:
        return {
            "schema": "analint.error/v1",
            "error": "max_states must be a positive integer",
            "kind": "usage",
            "details": [],
        }
    try:
        result = validate(
            Path(path),
            checks=checks,
            scenario_ids=scenario_ids,
            tags=tags,
            extra=Path(what_if) if what_if else None,
            max_states=max_states,
            sliced=slice,
            explain_slice=explain_slice,
            tlc=tlc,
            tlc_timeout=tlc_timeout,
            cache=cache,
        )
    except SelectionError as exc:
        return exc.to_dict()
    return result_to_dict(result, compact=compact)


@isolated_request
def explore_spec(
    path: str = ".",
    query: str | None = None,
    what_if: str | None = None,
    include_graph: bool = False,
    max_graph_states: int | None = None,
    observed_values: bool = False,
    max_states: int | None = None,
) -> dict:
    from analint.validator.exploration_service import ExplorationError, explore_path

    try:
        if include_graph and max_graph_states is None:
            return {
                "schema": "analint.error/v1",
                "error": "include_graph=true requires max_graph_states",
                "kind": "usage",
                "details": [],
            }
        artifact = explore_path(
            path,
            query_id=query,
            what_if=what_if,
            include_graph=include_graph,
            observed_values=observed_values,
            max_states=max_states,
        )
        if not include_graph:
            artifact.graph_omitted_reason = (
                "compact — set include_graph + max_graph_states for the graph"
            )
        elif max_graph_states is not None and artifact.summary["states"] > max_graph_states:
            artifact.graph_included = False
            artifact.graph_omitted_reason = f"graph has {artifact.summary['states']} states > max_graph_states {max_graph_states}"
        return artifact.to_dict()
    except ExplorationError as exc:
        return exc.to_dict()


@isolated_request
def trace_spec(
    path: str = ".",
    query: str = "",
    what_if: str | None = None,
    slice: bool = True,
    max_states: int | None = None,
    cache: bool = False,
    tlc: bool = False,
    tlc_timeout: float | None = None,
) -> dict:
    from analint.validator.exploration_service import ExplorationError, trace_query

    try:
        return trace_query(
            path,
            query,
            what_if=what_if,
            sliced=slice,
            max_states=max_states,
            cache=cache,
            tlc=tlc,
            tlc_timeout=tlc_timeout,
        )
    except ExplorationError as exc:
        return exc.to_dict()


@isolated_request
def show_spec(path: str = ".", kind: str | None = None, name: str | None = None) -> dict:
    spec, _, load_errors = build_spec(Path(path))
    if spec is None:
        return _no_spec(load_errors)
    return q.show(spec, kind, name)


@isolated_request
def affects_target(target: str, path: str = ".") -> dict:
    spec, _, load_errors = build_spec(Path(path))
    if spec is None:
        return _no_spec(load_errors)
    return q.affects(spec, target)


def _no_spec(load_errors: list) -> dict:
    return {
        "schema": "analint.error/v1",
        "error": "no spec found",
        "load_errors": [str(e) for e in load_errors],
    }


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("analint")

    @mcp.tool()
    def check(
        path: str = ".",
        what_if: str | None = None,
        max_states: int | None = None,
        slice: bool = True,
        tlc: bool = False,
        cache: bool = False,
        compact: bool = False,
        checks: list[str] | None = None,
        scenario_ids: list[str] | None = None,
        tags: list[str] | None = None,
        tlc_timeout: float | None = None,
        explain_slice: bool = False,
    ) -> dict:
        """Validate the analint spec at `path` (structural checks + scenario runs).

        `checks` selects flow/query/invariant ids (KIND:ID disambiguates), retaining
        every system action. A selected PASS covers only the reported scope.
        `scenario_ids` and `tags` add matching scenarios to an explicit selection.
        Only dependency-related canonical proofs support selected checks.
        Sliced checks limit action coverage to selected dependencies.
        `selection.unassessed_actions` lists actions outside that coverage.
        Unrelated defects encountered during exploration appear in `model_findings`,
        outside the selected verdict. `model_coverage` describes the bounded search.
        `what_if` — optional path to a standalone .py file whose objects
        (invariants, scenarios, actions) are added to the model for this run
        only: use it to test a hypothesis before editing the spec.
        `max_states` — optional override of every exploration budget for this
        run (an INCONCLUSIVE verdict means the budget ran out).
        `explain_slice` — report inclusion paths in each native property closure.
        `slice` — check each invariant/query on its slice of the model (the
        default); false explores the whole model for every check.
        `tlc` — hand every INCONCLUSIVE invariant/query to TLC on its slice
        (needs Java and a TLC jar; results carry `"backend": "tlc"`).
        `cache` — reuse explorations of unchanged slices from earlier runs (same
        result as a fresh run; speeds up repeated checks of a large spec).
        `compact` — return grouped findings with counts and up to three examples
        per group (`analint.check.compact/v1`). Omit it for full findings.
        """
        return check_spec(
            path,
            what_if,
            max_states,
            slice,
            tlc,
            cache,
            compact,
            checks=checks,
            scenario_ids=scenario_ids,
            tags=tags,
            tlc_timeout=tlc_timeout,
            explain_slice=explain_slice,
        )

    @mcp.tool()
    def explore(
        path: str = ".",
        query: str | None = None,
        what_if: str | None = None,
        include_graph: bool = False,
        max_graph_states: int | None = None,
        observed_values: bool = False,
        max_states: int | None = None,
    ) -> dict:
        """Explore the reachable state space at `path` (schema analint.exploration/v1).

        Without `query`, explores the canonical initial; with `query`, that query's
        own initial. Defaults to a compact projection (summary + completeness,
        `graph: null`). Set `include_graph=true` AND `max_graph_states` to receive
        nodes/edges; if the graph is larger than `max_graph_states`, the summary is
        returned with `graph: null` and a `graph_omitted` reason. Set `observed_values`
        to list values per field, and `max_states` to override the exploration budget.
        """
        return explore_spec(
            path, query, what_if, include_graph, max_graph_states, observed_values, max_states
        )

    @mcp.tool()
    def trace(
        path: str = ".",
        query: str = "",
        what_if: str | None = None,
        slice: bool = True,
        max_states: int | None = None,
        cache: bool = False,
        tlc: bool = False,
        tlc_timeout: float | None = None,
    ) -> dict:
        """A query or invariant's witness/counterexample as states and changes.

        `query` is a query or invariant id. Returns the root, a step list
        (`action`/`source`/`target`/`changes`) and the `final_state`, with node ids
        matching the exploration artifact. A passing property with no example
        returns `witness: null` and a message rather than an error.
        The property is decided exactly as `check` decides it (budgets, and its
        slice unless `slice` is false; the payload then carries `slice`, and
        fields outside it keep their initial values). Invariant payloads have
        an `invariant` key in place of `query`. Pass the same `max_states`, `cache`,
        `tlc` and `tlc_timeout` settings as check; calls do not inherit options.
        TLC-decided properties return `action_trace` without state snapshots.
        """
        return trace_spec(path, query, what_if, slice, max_states, cache, tlc, tlc_timeout)

    @mcp.tool()
    def show(path: str = ".", kind: str | None = None, name: str | None = None) -> dict:
        """Inspect the spec model at `path`.

        Without `kind`/`name` — an overview (all ids by kind). With them —
        details of one object; kind is one of: entity, event,
        invariant, query, action, lifecycle, flow, scenario, contract.
        Query details include predicate/goal, budget and declarative roots;
        inspection does not explore states. For action, name may also be a
        parameterized family id: returns its parameters, where clauses,
        shared contract and concrete variant ids.
        """
        return show_spec(path, kind, name)

    @mcp.tool()
    def affects(target: str, path: str = ".") -> dict:
        """Impact analysis before changing something.

        `target` is 'Entity.field' (who reads/writes it, which invariants and
        lifecycles constrain it), an entity/event name, or an action id (what
        it touches and what it emits).
        """
        return affects_target(target, path)

    return mcp


def main() -> None:
    try:
        server = build_server()
    except ImportError as exc:
        raise SystemExit(
            "the 'mcp' package is not installed — run: pip install analint[mcp]"
        ) from exc
    server.run()


if __name__ == "__main__":
    main()

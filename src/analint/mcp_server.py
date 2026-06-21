"""MCP server exposing the analint spec to AI agents.

Five tools over the same core as the CLI:
  - check(path, what_if?)    — validate the spec, optionally with a hypothesis patch
  - explore(path, query?, …) — bounded reachability exploration artifact
  - trace(path, query)       — a query's witness/counterexample as states and changes
  - show(path, kind?, name?) — overview, a kind's ids, or details of one object
  - affects(target, path)    — impact analysis for a field / entity / action

Run: `analint-mcp` (stdio transport). Requires the optional dependency:
`pip install analint[mcp]`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analint import query as q
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import build_spec, validate


def check_spec(path: str = ".", what_if: str | None = None) -> dict:
    result = validate(Path(path), extra=Path(what_if) if what_if else None)
    return result_to_dict(result)


def explore_spec(
    path: str = ".",
    query: str | None = None,
    what_if: str | None = None,
    include_graph: bool = False,
    max_graph_states: int | None = None,
) -> dict:
    from analint.validator.exploration_service import ExplorationError, explore_path

    try:
        if not include_graph:
            # the common path: summary-only, the graph is never materialised
            artifact = explore_path(path, query_id=query, what_if=what_if, include_graph=False)
            artifact.graph_omitted_reason = (
                "compact — set include_graph + max_graph_states for the graph"
            )
            return artifact.to_dict()
        if max_graph_states is None:
            return {
                "schema": "analint.error/v1",
                "error": "include_graph=true requires max_graph_states",
                "kind": "usage",
                "details": [],
            }
        artifact = explore_path(path, query_id=query, what_if=what_if, include_graph=True)
        if artifact.summary["states"] > max_graph_states:
            artifact.graph_included = False
            artifact.graph_omitted_reason = f"graph has {artifact.summary['states']} states > max_graph_states {max_graph_states}"
        return artifact.to_dict()
    except ExplorationError as exc:
        return exc.to_dict()


def trace_spec(path: str = ".", query: str = "", what_if: str | None = None) -> dict:
    from analint.validator.exploration_service import ExplorationError, trace_query

    try:
        return trace_query(path, query, what_if=what_if)
    except ExplorationError as exc:
        return exc.to_dict()


def show_spec(path: str = ".", kind: str | None = None, name: str | None = None) -> dict:
    spec, _, load_errors = build_spec(Path(path))
    if spec is None:
        return _no_spec(load_errors)
    return q.show(spec, kind, name)


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
    def check(path: str = ".", what_if: str | None = None) -> dict:
        """Validate the analint spec at `path` (structural checks + scenario runs).

        `what_if` — optional path to a standalone .py file whose objects
        (invariants, scenarios, actions) are added to the model for this run
        only: use it to test a hypothesis before editing the spec.
        """
        return check_spec(path, what_if)

    @mcp.tool()
    def explore(
        path: str = ".",
        query: str | None = None,
        what_if: str | None = None,
        include_graph: bool = False,
        max_graph_states: int | None = None,
    ) -> dict:
        """Explore the reachable state space at `path` (schema analint.exploration/v1).

        Without `query`, explores the canonical initial; with `query`, that query's
        own initial. Defaults to a compact projection (summary + completeness,
        `graph: null`). Set `include_graph=true` AND `max_graph_states` to receive
        nodes/edges; if the graph is larger than `max_graph_states`, the summary is
        returned with `graph: null` and a `graph_omitted` reason.
        """
        return explore_spec(path, query, what_if, include_graph, max_graph_states)

    @mcp.tool()
    def trace(path: str = ".", query: str = "", what_if: str | None = None) -> dict:
        """A query's witness/counterexample as states and changes (not just action ids).

        `query` is the query id. Returns the root, a step list
        (`action`/`source`/`target`/`changes`) and the `final_state`, with node ids
        matching the exploration artifact. A passing property with no example
        returns `witness: null` and a message rather than an error.
        """
        return trace_spec(path, query, what_if)

    @mcp.tool()
    def show(path: str = ".", kind: str | None = None, name: str | None = None) -> dict:
        """Inspect the spec model at `path`.

        Without `kind`/`name` — an overview (all ids by kind). With them —
        details of one object; kind is one of: entity, actor, event,
        invariant, action, lifecycle, flow, scenario.
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

"""MCP server exposing the analint spec to AI agents.

Three tools over the same core as the CLI:
  - check(path, what_if?)   — validate the spec, optionally with a hypothesis patch
  - show(path, kind?, name?) — overview or details of one model object
  - affects(target, path)   — impact analysis for a field / entity / action

Run: `analint-mcp` (stdio transport). Requires the optional dependency:
`pip install analint[mcp]`.
"""
from __future__ import annotations

from pathlib import Path

from analint import query as q
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import build_spec, validate


def check_spec(path: str = ".", what_if: str | None = None) -> dict:
    result = validate(Path(path), extra=Path(what_if) if what_if else None)
    return result_to_dict(result)


def show_spec(path: str = ".", kind: str | None = None, name: str | None = None) -> dict:
    spec, _, load_errors = build_spec(Path(path))
    if spec is None:
        return {"error": "no spec found", "load_errors": [str(e) for e in load_errors]}
    if kind is None or name is None:
        return q.spec_overview(spec)
    return q.describe(spec, kind, name)


def affects_target(target: str, path: str = ".") -> dict:
    spec, _, load_errors = build_spec(Path(path))
    if spec is None:
        return {"error": "no spec found", "load_errors": [str(e) for e in load_errors]}
    return q.affects(spec, target)


def build_server():
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
        it touches and which actions it triggers downstream).
        """
        return affects_target(target, path)

    return mcp


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        raise SystemExit(
            "the 'mcp' package is not installed — run: pip install analint[mcp]")
    server.run()


if __name__ == "__main__":
    main()

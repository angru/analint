from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Never

import click
import typer
from typer.core import TyperGroup

from analint import query as q
from analint.models.root import Spec
from analint.reporter.json_reporter import report_json
from analint.reporter.terminal import report_terminal
from analint.validator.engine import build_spec, validate

if TYPE_CHECKING:
    from analint.reporter.exploration_artifact import ExplorationArtifact

# Exit codes (stable interface for agents and CI):
#   0 — checks passed (warnings allowed unless --strict)
#   1 — findings: structural errors, failed scenarios, or warnings with --strict
#   2 — usage error (click default)
#   3 — the spec could not be loaded
#   4 — inconclusive: a query exhausted max_states without a verdict (proved nothing)


class _DefaultToCheck(TyperGroup):
    """`analint PATH` keeps working: an unknown first argument routes to `check`."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.exceptions.UsageError:
            return super().resolve_command(ctx, ["check", *args])


app = typer.Typer(
    cls=_DefaultToCheck,
    add_completion=False,
    help="Spec checker — declare how a system behaves, verify it stays consistent.",
)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        ctx.invoke(check)


@app.command()
def check(
    path: Path = typer.Argument(Path("."), help="Directory with spec.py, or a spec file"),
    format: str = typer.Option(
        "terminal", "--format", "-f", help="Output format: terminal or json"
    ),
    scenario: list[str] | None = typer.Option(
        None, "--scenario", "-s", help="Run only this scenario id"
    ),
    tag: list[str] | None = typer.Option(
        None, "--tag", "-t", help="Run only scenarios with this tag"
    ),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors"),
    what_if: Path | None = typer.Option(
        None,
        "--what-if",
        help="Also load this .py file into the model (hypothesis check, spec files untouched)",
    ),
) -> None:
    """Validate the spec: structural checks + scenario runs."""
    result = validate(path, scenario_ids=scenario or None, tags=tag or None, extra=what_if)

    if format == "json":
        report_json(result, strict)
    else:
        report_terminal(result, strict)

    if result.load_errors or result.spec_id == "__empty__":
        raise typer.Exit(3)
    verdict = result.effective_verdict(strict)
    if verdict == "FAIL":
        raise typer.Exit(1)
    if verdict == "INCONCLUSIVE":
        raise typer.Exit(4)


def _print_exploration(art: ExplorationArtifact) -> None:
    s, c = art.summary, art.completeness
    src = f"{art.source['kind']}" + (f" ({art.source['query']})" if art.source["query"] else "")
    print(f"analint explore  spec: {art.spec['id']}  source: {src}")
    status = "COMPLETE" if c["complete"] else f"INCOMPLETE ({', '.join(c['reasons'])})"
    print(f"  {status}  max_states={c['max_states']}")
    print(
        f"  roots {s['roots']}  states {s['states']}  edges {s['edges']}  "
        f"max_depth {s['max_depth']}"
    )
    b = s["branching"]
    print(
        f"  dead_ends {s['dead_ends']}  self_loops {s['self_loops']}  "
        f"branching {b['min']}/{b['mean']}/{b['max']}"
    )
    if s["fired_actions"]:
        print(f"  fired: {', '.join(s['fired_actions'])}")
    for action_id, reason in s["excluded_actions"].items():
        print(f"  excluded {action_id}: {reason}")
    for finding in art.findings:
        print(f"  {finding['severity']} {finding['location']}: {finding['message']}")


@app.command()
def explore(
    path: Path = typer.Argument(Path("."), help="Directory with spec.py, or a spec file"),
    query: str | None = typer.Option(
        None, "--query", help="Explore this query id's state space (default: the canonical initial)"
    ),
    format: str = typer.Option(
        "terminal", "--format", "-f", help="Output format: terminal or json"
    ),
    include_graph: bool = typer.Option(
        False, "--include-graph", help="Emit the full node/edge graph in JSON (default: compact)"
    ),
    what_if: Path | None = typer.Option(
        None, "--what-if", help="Also load this .py file into the model (spec files untouched)"
    ),
) -> None:
    """Explore the reachable state space (canonical or one query's) and report it."""
    from analint.validator.exploration_service import ExplorationError, explore_path

    try:
        artifact = explore_path(path, query_id=query, what_if=what_if)
    except ExplorationError as exc:
        if format == "json":
            print(json.dumps(exc.to_dict(), indent=2, ensure_ascii=False))
        else:
            typer.echo(f"EXPLORE ERROR ({exc.kind}): {exc.message}", err=True)
            for detail in exc.details:
                typer.echo(f"  - {detail}", err=True)
        raise typer.Exit(3) from None

    if format == "json":
        if not include_graph:
            artifact.graph_included = False
            artifact.graph_omitted_reason = (
                "compact projection — pass --include-graph for nodes/edges"
            )
        print(json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_exploration(artifact)


@app.command()
def show(
    kind: str | None = typer.Argument(
        None, help="entity | actor | event | invariant | action | lifecycle | flow | scenario"
    ),
    name: str | None = typer.Argument(None, help="id or class name"),
    path: Path = typer.Option(
        Path("."), "--path", "-p", help="Directory with spec.py, or a spec file"
    ),
) -> None:
    """Inspect the model: overview, or details of one object. Output is JSON."""
    spec = _load_spec_or_exit(path)
    if kind is None:
        _emit(q.spec_overview(spec))
        return
    if name is None:
        overview = q.spec_overview(spec)
        key = kind if kind in overview else kind + "s"
        if key in overview:
            _emit({kind: overview[key]})
            return
        _emit_error({"error": f"unknown kind '{kind}'", "kinds": list(overview)[1:]})
    payload = q.describe(spec, kind, name)
    if "error" in payload:
        _emit_error(payload)
    _emit(payload)


@app.command()
def affects(
    target: str = typer.Argument(..., help="Entity.field, entity/event name, or action id"),
    path: Path = typer.Option(
        Path("."), "--path", "-p", help="Directory with spec.py, or a spec file"
    ),
) -> None:
    """Impact analysis: what reads, writes, or depends on the target. Output is JSON."""
    spec = _load_spec_or_exit(path)
    payload = q.affects(spec, target)
    if "error" in payload:
        _emit_error(payload)
    _emit(payload)


def _load_spec_or_exit(path: Path) -> Spec:
    spec, _, load_errors = build_spec(path)
    if spec is None:
        _emit({"error": "no spec found", "load_errors": [str(e) for e in load_errors]})
        raise typer.Exit(3)
    return spec


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _emit_error(payload: dict) -> Never:
    _emit(payload)
    raise typer.Exit(1)

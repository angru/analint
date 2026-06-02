from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional

import typer

from analint.validator.engine import validate
from analint.reporter.terminal import report_terminal
from analint.reporter.json_reporter import report_json

app = typer.Typer(add_completion=False, help="Analytics linter — validate your system description.")


@app.command()
def main(
    path: Path = typer.Argument(Path("."), help="Path to discover analint files"),
    format: str = typer.Option("terminal", "--format", "-f", help="Output format: terminal or json"),
    scenario: Optional[list[str]] = typer.Option(None, "--scenario", "-s", help="Run only this scenario id"),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="Run only scenarios with this tag"),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop after first failure"),
) -> None:
    result = validate(path, scenario_ids=scenario or None, tags=tag or None)

    if format == "json":
        report_json(result)
    else:
        report_terminal(result)

    if result.has_errors:
        raise typer.Exit(1)
    if strict and result.warning_count > 0:
        raise typer.Exit(1)

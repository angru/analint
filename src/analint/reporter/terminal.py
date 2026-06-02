from __future__ import annotations
from rich.console import Console

from analint.reporter.base import Finding, ScenarioResult, Severity, ValidationResult

console = Console()


def report_terminal(result: ValidationResult) -> None:
    from importlib.metadata import version as _ver
    try:
        ver = _ver("analint")
    except Exception:
        ver = "dev"

    console.print(f"\n[bold]analint v{ver}[/bold]  spec: [cyan]{result.spec_name}[/cyan]\n")

    if result.load_errors:
        for err in result.load_errors:
            console.print(f"  [red]LOAD ERROR[/red]  {err}")
        console.print()

    console.print("[bold]STRUCTURAL[/bold]")
    if not result.structural_findings:
        console.print("  [green]OK[/green]   no structural issues")
    else:
        errors = [f for f in result.structural_findings if f.severity == Severity.ERROR]
        warnings = [f for f in result.structural_findings if f.severity == Severity.WARNING]
        for f in errors:
            console.print(f"  [red]ERROR[/red]  [{f.location}] {f.message}")
        for f in warnings:
            console.print(f"  [yellow]WARN[/yellow]   [{f.location}] {f.message}")
        if errors:
            console.print(f"\n  [red]Structural errors found — scenario validation skipped[/red]")
            _print_summary(result)
            return

    console.print()

    if not result.scenario_results:
        console.print("[bold]SCENARIOS[/bold]")
        console.print("  [dim]no scenarios found[/dim]")
    else:
        console.print("[bold]SCENARIOS[/bold]")
        for sr in result.scenario_results:
            _print_scenario(sr)

    console.print()
    _print_summary(result)


def _print_scenario(sr: ScenarioResult) -> None:
    status = "[green]PASS[/green]" if sr.passed else "[red]FAIL[/red]"
    meta = f"({sr.rules_count} rules)"
    console.print(f"  {status}  {sr.scenario_id:<40} {meta}")
    for f in sr.findings:
        if f.severity == Severity.ERROR:
            console.print(f"         [red]↳[/red] [{f.location}] {f.message}")
        elif f.severity == Severity.WARNING:
            console.print(f"         [yellow]↳[/yellow] [{f.location}] {f.message}")
        elif f.severity == Severity.INFO:
            console.print(f"         [dim]↳[/dim] [{f.location}] {f.message}")


def _print_summary(result: ValidationResult) -> None:
    passed = result.passed_count
    failed = result.failed_count
    warnings = result.warning_count

    parts = []
    if passed:
        parts.append(f"[green]{passed} passed[/green]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    if warnings:
        parts.append(f"[yellow]{warnings} warnings[/yellow]")
    if not parts:
        parts.append("[dim]0 scenarios[/dim]")

    console.print(f"Results: {', '.join(parts)}\n")

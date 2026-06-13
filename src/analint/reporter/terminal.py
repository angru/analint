from __future__ import annotations

from rich.console import Console

from analint.reporter.base import QueryResult, ScenarioResult, Severity, ValidationResult

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
            console.print("\n  [red]Structural errors found — scenario validation skipped[/red]")
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

    if result.exploration_findings:
        console.print()
        console.print("[bold]EXPLORATION[/bold]")
        for f in result.exploration_findings:
            color = "red" if f.severity == Severity.ERROR else "yellow"
            console.print(f"  [{color}]{f.severity.value:<5}[/{color}]  [{f.location}] {f.message}")

    if result.query_results:
        console.print()
        console.print("[bold]QUERIES[/bold]")
        for qr in result.query_results:
            _print_query(qr)

    console.print()
    _print_summary(result)


def _print_query(qr: QueryResult) -> None:
    colors = {"PASS": "green", "FAIL": "red", "INCONCLUSIVE": "yellow"}
    color = colors.get(qr.status, "white")
    meta = f"({qr.kind}, {qr.states_explored} states)"
    console.print(f"  [{color}]{qr.status:<4}[/{color}]  {qr.query_id:<40} {meta}")
    for f in qr.findings:
        if f.severity == Severity.ERROR:
            console.print(f"         [red]↳[/red] {f.message}")
        elif f.severity == Severity.WARNING:
            console.print(f"         [yellow]↳[/yellow] {f.message}")
        else:
            console.print(f"         [dim]↳[/dim] {f.message}")


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
    q_passed = sum(1 for q in result.query_results if q.status == "PASS")
    q_failed = sum(1 for q in result.query_results if q.status == "FAIL")
    q_open = sum(1 for q in result.query_results if q.status == "INCONCLUSIVE")

    parts = []
    if passed:
        parts.append(f"[green]{passed} passed[/green]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    if q_passed or q_failed or q_open:
        q_parts = [f"[green]{q_passed} ok[/green]"]
        if q_failed:
            q_parts.append(f"[red]{q_failed} failed[/red]")
        if q_open:
            q_parts.append(f"[yellow]{q_open} inconclusive[/yellow]")
        parts.append(f"queries: {', '.join(q_parts)}")
    if warnings:
        parts.append(f"[yellow]{warnings} warnings[/yellow]")
    if not parts:
        parts.append("[dim]0 scenarios[/dim]")

    verdict = result.verdict
    vcolor = {"PASS": "green", "FAIL": "red", "INCONCLUSIVE": "yellow"}[verdict]
    console.print(f"Results: {', '.join(parts)}  →  [{vcolor}]{verdict}[/{vcolor}]\n")

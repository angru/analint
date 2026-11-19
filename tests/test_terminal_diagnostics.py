"""Human reports preserve diagnostic subjects and distinguish preparation failure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import analint
from analint.cli import app
from analint.loader.python_loader import LoadError, load_path
from analint.reporter import terminal
from analint.reporter.base import Finding, ScenarioResult, Severity, ValidationResult


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    monkeypatch.setattr(terminal, "console", Console(width=240))


@pytest.mark.parametrize("action_id", ["turn_on", "turn_on[small]"])
def test_structural_counts_and_literal_subjects(tmp_path, action_id):
    entry = tmp_path / "spec.py"
    entry.write_text(f"""from analint import Action, DeadActions, Entity, Not, Set, Spec
class Flag(Entity):
    on: bool = False
turn_on = Action(id={action_id!r}, pre=[Not(Flag.on)], effect=[Set(Flag.on, True)])
spec = Spec(id="s", name="s", actions=[turn_on], queries=[DeadActions()])
""")
    result = CliRunner().invoke(app, ["check", str(entry)])
    assert result.exit_code == 1
    assert f"[action:{action_id}] has no scenarios" in result.stdout
    summary = result.stdout.split("Results:")[1]
    assert "1 structural error" in summary
    assert "1 warning" in summary
    assert "FAIL" in summary


@pytest.mark.parametrize(
    "source,line",
    [
        ('raise TypeError("bad [red] value")\n', 1),
        ('from analint import Param\np = Param("p", 1, 2)\nx = p / 2\n', 3),
        ("x = (\n", 1),
    ],
)
def test_load_failure_has_location_and_no_fake_checks(tmp_path, source, line):
    entry = tmp_path / "spec.py"
    entry.write_text(source)
    runner = CliRunner()
    result = runner.invoke(app, ["check", str(entry)])
    assert result.exit_code == 3
    assert f"{entry}:{line}" in result.stdout.replace("\n", "")
    assert "LOAD ERROR" in result.stdout
    for section in ("STRUCTURAL", "SCENARIOS", "Results:"):
        assert section not in result.stdout
    payload = runner.invoke(app, ["check", str(entry), "-f", "json"])
    assert payload.exit_code == 3
    assert f"{entry}:{line}" in json.loads(payload.stdout)["load_errors"][0]
    if "[red]" in source:
        assert "bad [red] value" in result.stdout


def test_imported_file_location(tmp_path):
    package = tmp_path / "diagnostic_package"
    package.mkdir()
    (package / "__init__.py").write_text("")
    entry = package / "spec.py"
    entry.write_text("from . import rules\n")
    rules = package / "rules.py"
    rules.write_text('\nraise ValueError("broken rule")\n')
    _, _, errors = load_path(entry)
    assert f"{rules}:2" in str(errors[0])
    assert errors[0].path == entry  # preserve the load entry for callers


def test_missing_entry_has_no_invented_line(tmp_path):
    result = CliRunner().invoke(app, ["check", str(tmp_path)])
    assert result.exit_code == 3
    assert "no spec.py entry point" in result.stdout
    assert "STRUCTURAL" not in result.stdout


@pytest.mark.parametrize(
    "section,severity",
    [
        ("exploration", Severity.ERROR),
        ("exploration", Severity.WARNING),
        ("scenario", Severity.ERROR),
        ("scenario", Severity.WARNING),
        ("scenario", Severity.INFO),
    ],
)
def test_plain_subjects_survive_in_other_finding_sections(section, severity, capsys):
    result = ValidationResult(spec_id="s", spec_name="S")
    finding = Finding(severity, "action:deposit", "amount [red] is literal")
    if section == "exploration":
        result.exploration_findings = [finding]
    else:
        result.scenario_results = [
            ScenarioResult(
                scenario_id="deposit", scenario_name="Deposit", passed=False, findings=[finding]
            )
        ]
    terminal.report_terminal(result)
    assert "[action:deposit] amount [red] is literal" in capsys.readouterr().out


def test_load_error_ignores_analint_installed_inside_project(tmp_path):
    # A normal package directory nested under the spec root reproduces a local
    # venv install; reuse this interpreter's dependencies without network setup.
    packages = tmp_path / ".venv" / "lib" / "python" / "site-packages"
    shutil.copytree(
        Path(analint.__file__).parent,
        packages / "analint",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Entity, Field\n"
        "class Wallet(Entity):\n"
        "    balance: int = Field(0, ge=0)\n"
        "broke = Wallet(balance=-1)\n"
    )
    script = (
        "import analint\n"
        "from pathlib import Path\n"
        "from analint.loader.python_loader import load_path\n"
        "print(analint.__file__)\n"
        "print(load_path(Path('spec.py'))[2][0])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(packages)},
        capture_output=True,
        text=True,
        check=True,
    )
    package_path, diagnostic = result.stdout.strip().splitlines()
    assert Path(package_path).is_relative_to(packages)
    assert diagnostic.startswith(f"{entry}:4:")
    assert "Wallet.balance must be >= 0" in diagnostic


@pytest.mark.parametrize(
    "library", ["site-packages/vendor.py", "dist-packages/vendor.py", "stdlib/vendor.py"]
)
def test_load_error_skips_library_frames_under_project(tmp_path, monkeypatch, library):
    import sysconfig

    entry = tmp_path / "spec.py"
    original = sysconfig.get_paths()
    monkeypatch.setattr(
        sysconfig, "get_paths", lambda: {**original, "stdlib": str(tmp_path / "stdlib")}
    )
    namespace = {}
    exec(
        compile(
            'def explode():\n    raise ValueError("library error")\n',
            str(tmp_path / library),
            "exec",
        ),
        namespace,
    )
    try:
        exec(compile("explode()\n", str(entry), "exec"), namespace)
    except ValueError as exc:
        diagnostic = LoadError(entry, exc)
    assert str(diagnostic).startswith(f"{entry}:1: library error")

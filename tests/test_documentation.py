"""Execute the published tutorial and its counterexample, rather than a copy."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from analint.cli import app
from analint.mcp_server import check_spec, explore_spec, trace_spec

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "docs" / "getting-started.md"
runner = CliRunner()


def _code_block(title: str) -> str:
    blocks = re.findall(
        rf'^```python title="{re.escape(title)}"\n(.*?)^```$',
        TUTORIAL.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    assert len(blocks) == 1, f"expected one complete {title} block in the tutorial"
    return blocks[0]


def _json(*args: str, exit_code: int = 0) -> dict:
    result = runner.invoke(app, [*args, "--format", "json"])
    assert result.exit_code == exit_code, result.output
    return json.loads(result.output)


def test_tutorial_checks_and_inspection_commands(tmp_path):
    (tmp_path / "spec.py").write_text(_code_block("spec.py"))
    report = _json("check", str(tmp_path), "--strict")
    assert report["verdict"] == "PASS"
    assert report["passed"] is True
    assert len(report["scenarios"]) == 2
    assert all(item["passed"] for item in report["scenarios"])
    assert report["flows"][0]["actions_run"] == 2
    assert report["invariants"][0]["status"] == "PASS"
    assert {item["id"]: item["status"] for item in report["queries"]} == {
        "can_archive": "PASS",
        "archive_stays_possible": "PASS",
    }
    for args, schema in [
        (["show", "-p", str(tmp_path)], "analint.overview/v1"),
        (["show", "action", "resolve", "-p", str(tmp_path)], "analint.show/v1"),
        (["affects", "Queue.open_tickets", "-p", str(tmp_path)], "analint.affects/v1"),
    ]:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["schema"] == schema
        assert "error" not in payload

    trace = _json("trace", "can_archive", "-p", str(tmp_path))
    assert [step["action"] for step in trace["steps"]] == ["resolve", "archive"]
    graph = _json("explore", str(tmp_path), "--include-graph")
    assert graph["summary"]["states"] == 3
    assert graph["graph"] is not None


def test_tutorial_missing_effect_fails_with_invariant_counterexample(tmp_path):
    source = _code_block("spec.py")
    effect = "        Subtract(Queue.open_tickets, 1),\n"
    assert source.count(effect) == 1
    (tmp_path / "spec.py").write_text(source.replace(effect, ""))
    report = _json("check", str(tmp_path), exit_code=1)
    assert report["verdict"] == "FAIL"
    assert report["passed"] is False
    assert report["invariants"][0]["status"] == "FAIL"
    trace = _json("trace", "resolved_leaves_no_open_ticket", "-p", str(tmp_path))
    assert trace["schema"] == "analint.trace/v1"
    assert trace["invariant"] == "resolved_leaves_no_open_ticket"
    assert trace["status"] == "FAIL"
    assert [step["action"] for step in trace["steps"]] == ["resolve"]
    fields = trace["final_state"]
    assert fields["Queue.open_tickets"] == 1
    assert fields["Ticket.status"] == "Status.RESOLVED"


def test_tutorial_packaged_hypothesis_fails_without_changing_root(tmp_path):
    package = tmp_path / "ticket_spec"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "spec.py").write_text(_code_block("spec.py"))
    hypothesis = tmp_path / "hypothesis.py"
    hypothesis.write_text(_code_block("hypothesis.py"))
    report = _json("check", str(package), "--what-if", str(hypothesis), exit_code=1)
    assert report["load_errors"] == []
    assert not any(item["severity"] == "ERROR" for item in report["structural"])
    results = {item["id"]: item for item in report["invariants"]}
    assert results["queue_is_always_empty"]["status"] == "FAIL"
    trace = _json(
        "trace", "queue_is_always_empty", "-p", str(package), "--what-if", str(hypothesis)
    )
    assert trace["status"] == "FAIL"
    assert trace["steps"] == []
    assert _json("check", str(package))["verdict"] == "PASS"


def test_documented_mcp_requests_match_tutorial(tmp_path):
    (tmp_path / "spec.py").write_text(_code_block("spec.py"))
    report = check_spec(path=str(tmp_path), max_states=10000, slice=True)
    assert report["schema"] == "analint.check/v1"
    assert report["verdict"] == "PASS"
    trace = trace_spec(path=str(tmp_path), query="can_archive")
    assert trace["status"] == "PASS"
    assert [step["action"] for step in trace["steps"]] == ["resolve", "archive"]
    compact = explore_spec(path=str(tmp_path))
    assert compact["summary"]["states"] == 3
    assert compact["graph"] is None
    omitted = explore_spec(path=str(tmp_path), include_graph=True, max_graph_states=2)
    assert omitted["graph"] is None
    included = explore_spec(path=str(tmp_path), include_graph=True, max_graph_states=3)
    assert included["graph"] is not None


def test_gallery_covers_example_intent_manifest():
    gallery = (ROOT / "docs" / "examples.md").read_text()
    manifest = tomllib.loads((ROOT / "examples" / "expectations.toml").read_text())
    rows = re.findall(r"^\|.*?/examples/(\w+)/README\.md.*?\|$", gallery, re.MULTILINE)
    assert set(rows) == set(manifest)
    for name, intent in manifest.items():
        row = next(line for line in gallery.splitlines() if f"/examples/{name}/README.md)" in line)
        assert row.rstrip().endswith(f"{intent['verdict']} |") or (
            intent["broken"] and row.rstrip().endswith("**FAIL, deliberate** |")
        ), row

"""A failed hypothesis must never be reported as an unpatched success."""

import json

import pytest
from typer.testing import CliRunner

from analint.cli import app
from analint.mcp_server import check_spec, explore_spec, trace_spec


@pytest.fixture
def model(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import AlwaysHolds, Entity, Spec\n"
        "class Item(Entity):\n"
        "    value: int = 0\n"
        "q = AlwaysHolds(Item.value == 0, id='q')\n"
        "spec = Spec(id='s', name='S', queries=[q])\n"
    )
    patch = tmp_path / "patch.py"
    patch.write_text("raise ValueError('broken hypothesis')\n")
    return entry, patch


@pytest.mark.parametrize("missing", [False, True])
def test_mcp_inspections_reject_failed_patch(model, missing):
    entry, patch = model
    if missing:
        patch.unlink()
    checked = check_spec(str(entry), what_if=str(patch))
    assert checked["verdict"] == "FAIL"
    for result in (
        explore_spec(str(entry), what_if=str(patch)),
        trace_spec(str(entry), query="q", what_if=str(patch)),
    ):
        assert result["schema"] == "analint.error/v1"
        assert result["kind"] == "load"
        assert result["details"] == checked["load_errors"]
        assert "completeness" not in result
        assert "status" not in result


@pytest.mark.parametrize("command", ["explore", "trace"])
def test_cli_inspections_reject_failed_patch(model, command):
    entry, patch = model
    args = ["explore", str(entry)] if command == "explore" else ["trace", "q", "-p", str(entry)]
    result = CliRunner().invoke(app, [*args, "--what-if", str(patch), "-f", "json"])
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "load"
    assert "broken hypothesis" in payload["details"][0]


def test_successful_patch_still_produces_artifacts(model):
    entry, patch = model
    patch.write_text("from analint_spec import Item\n")
    assert explore_spec(str(entry), what_if=str(patch))["completeness"]["complete"]
    assert trace_spec(str(entry), query="q", what_if=str(patch))["status"] == "PASS"

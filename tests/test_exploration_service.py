"""Exploration service + CLI/MCP explore surface (P4.2)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from analint.cli import app
from analint.mcp_server import explore_spec
from analint.validator.exploration_service import ExplorationError, explore_path

runner = CliRunner()
BP = "examples/branch_protection"


# ── CLI ─────────────────────────────────────────────────────────────────────────


def test_cli_canonical_terminal_is_summary_first():
    result = runner.invoke(app, ["explore", BP])
    assert result.exit_code == 0
    assert "COMPLETE" in result.stdout
    assert "states 121" in result.stdout


def test_cli_json_is_compact_by_default():
    result = runner.invoke(app, ["explore", BP, "--format", "json"])
    assert result.exit_code == 0
    d = json.loads(result.stdout)
    assert d["graph"] is None
    assert "graph_omitted" in d
    assert d["summary"]["states"] == 121  # the summary is still complete


def test_cli_include_graph_emits_full_and_round_trips():
    result = runner.invoke(app, ["explore", BP, "--format", "json", "--include-graph"])
    d = json.loads(result.stdout)
    assert len(d["graph"]["nodes"]) == 121
    assert len(d["graph"]["edges"]) == 383
    assert "graph_omitted" not in d
    assert json.loads(json.dumps(d)) == d


def test_cli_query_specific_source_and_budget():
    result = runner.invoke(
        app, ["explore", "examples/coin", "--query", "supply_never_overflows", "--format", "json"]
    )
    d = json.loads(result.stdout)
    assert d["source"] == {"kind": "query", "query": "supply_never_overflows"}
    assert d["completeness"]["max_states"] > 0


def test_cli_unknown_query_exits_3():
    result = runner.invoke(app, ["explore", "examples/coin", "--query", "nope"])
    assert result.exit_code == 3


# ── service ──────────────────────────────────────────────────────────────────────


def test_service_load_failure_raises_structured():
    with pytest.raises(ExplorationError) as info:
        explore_path("/tmp/analint-does-not-exist-xyz")
    assert info.value.kind == "load"


def test_service_structural_error_raises(tmp_path):
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from analint import Action, Entity, Field, Spec\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=2)\n"
        "a = Action(id='dup', effect=[])\n"
        "b = Action(id='dup', effect=[])\n"  # duplicate id → structural ERROR
        "spec = Spec(id='s', name='S', entities=[Box], actions=[a, b])\n"
    )
    with pytest.raises(ExplorationError) as info:
        explore_path(spec)
    assert info.value.kind == "structural"


def test_service_unbuildable_query_raises(tmp_path):
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from analint import Entity, Field, Initial, Reachable, Spec\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=2)\n"
        # structurally valid, but the where-clause admits no initial state
        "empty = Reachable(Box.n == 1, initial=Initial(vary=[Box.n], where=[Box.n != Box.n]))\n"
        "spec = Spec(id='s', name='S', entities=[Box], queries=[empty])\n"
    )
    with pytest.raises(ExplorationError) as info:
        explore_path(spec, query_id="empty")
    assert info.value.kind == "unbuildable"


def test_service_what_if_is_applied(tmp_path):
    base = tmp_path / "spec.py"
    base.write_text(
        "from analint import Action, Add, Entity, Field, Spec\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=3)\n"
        "tick = Action(id='tick', pre=[Box.n < 1], effect=[Add(Box.n, 1)])\n"
        "spec = Spec(id='s', name='S')\n"  # auto-populate so the what-if action merges
    )
    patch = tmp_path / "more.py"
    patch.write_text(
        "from analint import Action, Add\n"
        "from analint_spec import Box\n"
        "tick_more = Action(id='tick_more', pre=[Box.n < 3], effect=[Add(Box.n, 1)])\n"
    )
    without = explore_path(base)
    with_patch = explore_path(base, what_if=patch)
    # the extra action reaches more states
    assert with_patch.summary["states"] > without.summary["states"]


# ── MCP ──────────────────────────────────────────────────────────────────────────


def test_mcp_compact_by_default():
    d = explore_spec(BP)
    assert d["graph"] is None
    assert "graph_omitted" in d


def test_mcp_include_graph_requires_max_graph_states():
    d = explore_spec(BP, include_graph=True)
    assert "error" in d


def test_mcp_graph_guard_omits_large_graph_without_misreporting_completeness():
    d = explore_spec(BP, include_graph=True, max_graph_states=10)
    assert d["graph"] is None
    assert "graph_omitted" in d
    # the exploration itself is still complete — output omission is not incompleteness
    assert d["summary"]["states"] == 121
    assert d["completeness"]["complete"] is True


def test_mcp_graph_included_within_budget():
    d = explore_spec(BP, include_graph=True, max_graph_states=10000)
    assert d["graph"] is not None
    assert len(d["graph"]["nodes"]) == 121


def test_mcp_unknown_query_returns_structured_error():
    d = explore_spec("examples/coin", query="nope")
    assert d["kind"] == "unknown_query"

"""State-diff query witness traces (P4.3)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from analint.cli import app
from analint.validator.exploration_service import ExplorationError, trace_query

runner = CliRunner()


def _write(tmp_path, body: str):
    spec = tmp_path / "spec.py"
    spec.write_text(body)
    return spec


# ── examples ──────────────────────────────────────────────────────────────────


def test_reachable_witness_has_steps_and_final_state():
    t = trace_query("examples/oauth", "honest_flow_reaches_token")
    assert t["status"] == "PASS"
    assert t["root"]["index"] == 1
    assert len(t["steps"]) >= 1
    for step in t["steps"]:
        assert step["source"].startswith("sha256:")
        assert step["target"].startswith("sha256:")
        assert isinstance(step["changes"], list)
    assert t["final_state"]  # the witness state is rendered


def test_alwaysholds_counterexample():
    t = trace_query("examples/coin", "supply_never_overflows")
    assert t["status"] == "FAIL"
    assert len(t["steps"]) >= 1
    assert any("coins" in c["field"] for step in t["steps"] for c in step["changes"])


def test_passing_unreachable_has_no_witness():
    t = trace_query("examples/oauth", "no_token_to_wrong_client")
    assert t["status"] == "PASS"
    assert t["witness"] is None
    assert t["steps"] == []
    assert "no witness" in t["message"]


def test_multi_root_trace_names_its_root():
    t = trace_query("examples/mafia", "mafia_can_win")
    assert t["status"] == "PASS"
    assert t["root"] is not None
    assert t["root"]["index"] >= 1
    assert t["root"]["node"].startswith("sha256:")


def test_unknown_query_raises():
    with pytest.raises(ExplorationError) as info:
        trace_query("examples/coin", "nope")
    assert info.value.kind == "unknown_query"


# ── inline specs ────────────────────────────────────────────────────────────────


def test_unreachable_counterexample_and_repeated_action(tmp_path):
    spec = _write(
        tmp_path,
        "from analint import Action, Add, Entity, Field, Spec, Unreachable\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=2)\n"
        "tick = Action(id='tick', pre=[Box.n < 2], effect=[Add(Box.n, 1)])\n"
        "never_two = Unreachable(Box.n == 2)\n"  # it IS reachable → FAIL counterexample
        "spec = Spec(id='s', name='S')\n",
    )
    t = trace_query(spec, "never_two")
    assert t["status"] == "FAIL"
    # n: 0 -> 1 -> 2 means the SAME action id appears twice across distinct states
    assert [step["action"] for step in t["steps"]] == ["tick", "tick"]
    assert t["steps"][0]["target"] == t["steps"][1]["source"]  # contiguous path
    assert t["steps"][0]["source"] != t["steps"][1]["target"]  # distinct states


def test_no_dead_end_counterexample(tmp_path):
    spec = _write(
        tmp_path,
        "from analint import Action, Add, Entity, Field, NoDeadEnd, Spec\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=2)\n"
        "tick = Action(id='tick', pre=[Box.n < 2], effect=[Add(Box.n, 1)])\n"
        "can_reset = NoDeadEnd(goal=Box.n == 0)\n"  # once ticked, n==0 unreachable → FAIL
        "spec = Spec(id='s', name='S')\n",
    )
    t = trace_query(spec, "can_reset")
    assert t["status"] == "FAIL"
    assert len(t["steps"]) >= 1


def test_self_loops_do_not_appear_in_the_shortest_trace(tmp_path):
    spec = _write(
        tmp_path,
        "from analint import Action, Add, Entity, Field, Set, Spec, Unreachable\n"
        "class Box(Entity):\n    n: int = Field(0, ge=0, le=2)\n"
        "tick = Action(id='tick', pre=[Box.n < 2], effect=[Add(Box.n, 1)])\n"
        "reset = Action(id='reset', effect=[Set(Box.n, 0)])\n"  # self-loop at n=0
        "never_two = Unreachable(Box.n == 2)\n"
        "spec = Spec(id='s', name='S')\n",
    )
    t = trace_query(spec, "never_two")
    assert t["status"] == "FAIL"
    assert all(step["source"] != step["target"] for step in t["steps"])


def test_presence_flip_appears_in_changes(tmp_path):
    spec = _write(
        tmp_path,
        "from analint import Action, Delete, Entity, Field, Not, Present, Scope, Spec, Unreachable\n"
        "class Item(Entity):\n    tag: int = Field(0, ge=0, le=1)\n"
        "items = Scope(Item, keys=['a'])\n"
        "a = items['a']\n"
        "drop = Action(id='drop', effect=[Delete(a)])\n"
        "gone = Unreachable(Not(Present(a)))\n"  # the slot CAN be deleted → FAIL counterexample
        "spec = Spec(id='s', name='S')\n",
    )
    t = trace_query(spec, "gone")
    assert t["status"] == "FAIL"
    flips = [c for step in t["steps"] for c in step["changes"] if c["field"].endswith(".@present")]
    assert any(c["before"] is True and c["after"] is False for c in flips)


def test_terminal_and_json_render_the_same_steps():
    as_json = runner.invoke(
        app, ["trace", "supply_never_overflows", "-p", "examples/coin", "--format", "json"]
    )
    terminal = runner.invoke(app, ["trace", "supply_never_overflows", "-p", "examples/coin"])
    assert as_json.exit_code == 0 and terminal.exit_code == 0
    for step in json.loads(as_json.stdout)["steps"]:
        assert step["action"] in terminal.stdout

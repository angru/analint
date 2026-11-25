"""Observed field values describe the nodes recorded by this exploration."""

import json
from itertools import product

import pytest
from typer.testing import CliRunner

from analint.cli import app
from analint.mcp_server import explore_spec
from analint.validator.exploration_service import explore_path


def counter_spec(tmp_path, coupled):
    path = tmp_path / "spec.py"
    actions = (
        "step = Action(pre=[Pair.x < 2], effect=[Add(Pair.x, 1), Add(Pair.y, 1)])\n"
        "spec = Spec(id='sample', name='Sample', actions=[step])"
        if coupled
        else "left = Action(pre=[Pair.x < 2], effect=[Add(Pair.x, 1)])\n"
        "right = Action(pre=[Pair.y < 2], effect=[Add(Pair.y, 1)])\n"
        "spec = Spec(id='sample', name='Sample', actions=[left, right])"
    )
    path.write_text(
        "from analint import Action, Add, Entity, Field, Spec\n"
        "class Pair(Entity):\n"
        "    x: int = Field(0, ge=0, le=2)\n"
        "    y: int = Field(0, ge=0, le=2)\n" + actions + "\n"
    )
    return path


@pytest.mark.parametrize("coupled", [False, True], ids=["independent", "lockstep"])
def test_observations_match_recorded_graph_even_when_capped(tmp_path, coupled):
    spec = counter_spec(tmp_path, coupled)
    complete_pairs = {(n, n) for n in range(3)} if coupled else set(product(range(3), repeat=2))
    frontier_pairs = {(0, 0), (1, 1)} if coupled else {(0, 0), (1, 0), (0, 1)}
    for budget, pairs in [(100, complete_pairs), (2, frontier_pairs)]:
        plain = explore_path(spec, max_states=budget).to_dict()
        graph = plain["graph"]
        assert "observed_values" not in plain["summary"]
        assert {(n["state"]["Pair.x"], n["state"]["Pair.y"]) for n in graph["nodes"]} == pairs
        for include_graph in (False, True):
            art = explore_path(
                spec, max_states=budget, include_graph=include_graph, observed_values=True
            ).to_dict()
            assert art["graph"] == (graph if include_graph else None)
            report = art["summary"].pop("observed_values")
            assert art["summary"] == plain["summary"]
            assert art["completeness"] == plain["completeness"]
            assert art["completeness"]["reasons"] == ([] if budget == 100 else ["capped"])
            assert report["count_kind"] == ("exact" if budget == 100 else "lower_bound")
            assert report["backend"] == "native"
            for label, row in report["fields"].items():
                values = list(dict.fromkeys(n["state"][label] for n in graph["nodes"]))
                assert row == {
                    "declared": {"ge": 0, "le": 2},
                    "distinct_count": len(values),
                    "values": values,
                }
            assert set(report["fields"]) == {"Pair.x", "Pair.y"}


def test_absent_slots_have_presence_but_only_present_fields_contribute(tmp_path):
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from analint import Action, Create, Entity, Field, Scope, Spec\n"
        "class Item(Entity):\n"
        "    n: int | None = Field(None, values=[1, 2])\n"
        "items = Scope(Item, keys=['a', 'b'], initially_present=False)\n"
        "create = Action(effect=[Create(items['a'])])\n"
        "spec = Spec(id='sample', name='Sample', actions=[create])\n"
    )
    art = explore_path(spec, include_graph=False, observed_values=True)
    fields = art.summary["observed_values"]["fields"]
    for key, presence, values in [("a", [False, True], [None]), ("b", [False], [])]:
        label = f"Item['{key}']"
        assert fields[f"{label}.@present"] == {
            "declared": {"values": [False, True]},
            "distinct_count": len(presence),
            "values": presence,
        }
        assert fields[f"{label}.n"] == {
            "declared": {"values": [1, 2]},
            "distinct_count": len(values),
            "values": values,
        }


def test_cli_and_mcp_report_partial_values_without_requesting_graph(tmp_path):
    spec = counter_spec(tmp_path, coupled=True)
    args = ["explore", str(spec), "--observed-values", "--max-states", "2"]
    runner = CliRunner()
    terminal = runner.invoke(app, args)
    assert terminal.exit_code == 0, terminal.output
    assert "lower bounds" in terminal.stdout
    assert "Pair.x: 2 distinct [0, 1]" in terminal.stdout
    cli = json.loads(runner.invoke(app, [*args, "-f", "json"]).stdout)
    mcp = explore_spec(str(spec), observed_values=True, max_states=2)
    assert cli["graph"] is mcp["graph"] is None
    assert cli["summary"] == mcp["summary"]
    assert mcp["completeness"] == {"complete": False, "reasons": ["capped"], "max_states": 2}
    assert explore_spec(str(spec), observed_values=True, max_states=0)["kind"] == "usage"


def test_query_roots_supply_values_even_before_the_first_expansion(tmp_path):
    spec = tmp_path / "spec.py"
    spec.write_text(
        "from analint import Entity, Field, Reachable, Spec\n"
        "class Gauge(Entity):\n"
        "    n: int = Field(0, gt=-1, lt=1000000000)\n"
        "q = Reachable(Gauge.n == 7, given_any=[[Gauge(n=7)], [Gauge(n=4)]], max_states=1)\n"
        "spec = Spec(id='sample', name='Sample', queries=[q])\n"
    )
    art = explore_path(spec, query_id="q", observed_values=True, include_graph=False)
    assert art.source == {"kind": "query", "query": "q"}
    assert art.summary["roots"] == art.summary["states"] == 2
    assert art.completeness == {"complete": False, "reasons": ["capped"], "max_states": 1}
    report = art.summary["observed_values"]
    assert report["count_kind"] == "lower_bound"
    assert report["fields"]["Gauge.n"] == {
        "declared": {"gt": -1, "lt": 1000000000},
        "distinct_count": 2,
        "values": [7, 4],
    }

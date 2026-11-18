"""Selection changes verification work, never the allowed system behavior (#21)."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    AlwaysHolds,
    Entity,
    Event,
    Initial,
    Invariant,
    NoDeadEnd,
    Not,
    Reachable,
    Set,
    Spec,
    Unreachable,
)
from analint.cli import app
from analint.mcp_server import check_spec, trace_spec
from analint.reporter.json_reporter import result_to_dict
from analint.validator import SelectionError, validate, validate_spec
from analint.validator.engine import prepare_model
from analint.validator.exploration_service import ExplorationError, trace_query

EXAMPLE = Path(__file__).resolve().parents[1] / "benchmarks/shared_checks.py"


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(EXAMPLE.read_text())
    return path


def _defective(entry):
    text = entry.read_text()
    assert "pre=[Order.reserved, Not(Order.shipped)]," in text
    entry.write_text(
        text.replace("pre=[Order.reserved, Not(Order.shipped)],", "pre=[Order.reserved],")
    )


def _stable(report):
    if isinstance(report, dict):
        return {key: _stable(value) for key, value in report.items() if key != "elapsed_ms"}
    if isinstance(report, list):
        return [_stable(value) for value in report]
    return report


def test_one_spec_reused_for_different_selections_without_mutation(entry):
    spec = prepare_model(entry).spec
    members = {key: getattr(spec, key) for key in ("actions", "flows", "queries", "invariants")}
    before = repr(spec)
    first = validate_spec(spec, checks=["checkout"])
    assert first.verdict == "PASS"
    assert [f.flow_id for f in first.flow_results] == ["checkout"]
    assert first.query_results == first.invariant_results == first.scenario_results == []
    assert first.selection["requested"] == ["flow:checkout"]
    assert first.selection["supporting"] == []
    assert first.selection["model_actions"] == ["reserve", "ship", "release"]
    assert first.selection["action_coverage"] == "executed_steps_only"
    second = validate_spec(spec, checks=["release_reservation"])
    assert [f.flow_id for f in second.flow_results] == ["release_reservation"]
    capped = validate_spec(spec, checks=["can_ship"], max_states=1)
    assert capped.verdict == "INCONCLUSIVE"
    full = validate_spec(spec)
    assert full.verdict == "PASS"
    assert full.selection is None
    assert [q.query_id for q in full.query_results] == ["shipment_keeps_reservation", "can_ship"]
    assert repr(spec) == before
    assert all(getattr(spec, key) is value for key, value in members.items())
    assert _stable(result_to_dict(first)) == _stable(
        result_to_dict(validate_spec(spec, checks=["checkout"]))
    )


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("cache", [False, True])
def test_other_flow_actions_still_expose_cross_flow_violation(entry, monkeypatch, sliced, cache):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(entry.parent / "cache"))
    _defective(entry)
    spec = prepare_model(entry).spec
    flows = validate_spec(
        spec, checks=["checkout", "release_reservation"], sliced=sliced, cache=cache
    )
    assert flows.verdict == "PASS"  # the interference is outside either journey
    selected = validate_spec(
        spec, checks=["shipment_keeps_reservation"], sliced=sliced, cache=cache
    )
    assert selected.verdict == "FAIL"
    [query] = selected.query_results
    assert query.status == "FAIL"
    assert query.trace == ["reserve", "ship", "release"]
    assert selected.selection["supporting"] == ["invariant:reservation_owns_stock"]
    assert selected.selection["model_actions"] == ["reserve", "ship", "release"]
    assert "flow:release_reservation" in selected.selection["not_selected"]
    full = validate_spec(spec, sliced=sliced, cache=cache)
    assert _stable(result_to_dict(selected)["queries"][0]) == _stable(
        result_to_dict(full)["queries"][0]
    )
    trace = trace_query(entry, "query:shipment_keeps_reservation", sliced=sliced, cache=cache)
    assert [step["action"] for step in trace["steps"]] == query.trace
    assert trace["selection"] == selected.selection
    assert trace["verification_verdict"] == "FAIL"


def test_supporting_invariant_failure_cannot_be_hidden(entry):
    spec = prepare_model(entry).spec
    order = next(cls for cls in spec.entities if cls.__name__ == "Order")
    spec.invariants.append(Invariant(order.shipped == False, id="never_ship"))  # noqa: E712
    result = validate_spec(spec, checks=["can_ship"])
    assert result.verdict == "FAIL"
    assert "invariant:never_ship" in result.selection["supporting"]
    assert any(
        r.invariant_id == "never_ship" and r.status == "FAIL" for r in result.invariant_results
    )


def test_an_unselected_action_defect_is_not_hidden(entry):
    spec = prepare_model(entry).spec
    order = next(cls for cls in spec.entities if cls.__name__ == "Order")
    spec.actions[2].post = [order.reserved == True]  # noqa: E712
    selected = validate_spec(spec, checks=["can_ship"])
    assert selected.verdict == "FAIL"
    assert any(
        f.code.value == "transition.postcondition_violated" for f in selected.exploration_findings
    )


def test_structural_validation_still_checks_unselected_behavior(entry):
    spec = prepare_model(entry).spec
    spec.actions[2].id = "ship"
    result = validate_spec(spec, checks=["checkout"])
    assert result.verdict == "FAIL"
    assert result.flow_results == []
    assert any(f.code.value == "structural.duplicate_id" for f in result.structural_findings)


@pytest.mark.parametrize("checks", [[], ["missing"], [""], "checkout", ["action:reserve"]])
def test_invalid_selections_fail_explicitly(entry, checks):
    with pytest.raises(SelectionError):
        validate(entry, checks=checks)


def test_ambiguous_identifiers_require_kind(entry):
    spec = prepare_model(entry).spec
    order = next(cls for cls in spec.entities if cls.__name__ == "Order")
    spec.queries.append(AlwaysHolds(order.reserved == order.reserved, id="checkout"))
    with pytest.raises(SelectionError, match="ambiguous"):
        validate_spec(spec, checks=["checkout"])
    assert validate_spec(spec, checks=["flow:checkout"]).query_results == []
    assert validate_spec(spec, checks=["query:checkout"]).flow_results == []


def test_existing_scenario_filters_and_combined_selection(entry):
    full = validate(entry, tags=["release"])
    assert len(full.flow_results) == 2 and len(full.query_results) == 2
    assert [sc.scenario_id for sc in full.scenario_results] == ["release_example"]
    chosen = validate(entry, checks=["checkout"], scenario_ids=["reserve_example"])
    assert [sc.scenario_id for sc in chosen.scenario_results] == ["reserve_example"]
    assert chosen.selection["requested"] == ["scenario:reserve_example", "flow:checkout"]
    assert validate(entry, checks=["checkout"]).scenario_results == []
    with pytest.raises(SelectionError, match="no scenarios"):
        validate(entry, checks=["checkout"], scenario_ids=["reserve_example"], tags=["release"])
    with pytest.raises(SelectionError, match="unknown scenario"):
        validate(entry, scenario_ids=["missing"])


def test_cli_mcp_library_selection_and_usage_errors_agree(entry):
    runner = CliRunner()
    cli = runner.invoke(app, ["check", str(entry), "--check", "checkout", "--format", "json"])
    assert cli.exit_code == 0, cli.output
    expected = result_to_dict(validate(entry, checks=["checkout"]))
    assert json.loads(cli.stdout) == expected == check_spec(str(entry), checks=["checkout"])
    human = runner.invoke(app, ["check", str(entry), "--check", "checkout"])
    assert "verdict applies only to this scope" in human.output
    assert "SELECTED CHECKS" in human.output
    compact = runner.invoke(
        app, ["check", str(entry), "--check", "checkout", "-f", "json", "--compact"]
    )
    assert json.loads(compact.stdout)["selection"] == expected["selection"]
    invalid = runner.invoke(app, ["check", str(entry), "--check", "missing", "-f", "json"])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["kind"] == "usage"
    assert check_spec(str(entry), checks=[])["kind"] == "usage"
    strict = runner.invoke(
        app, ["check", str(entry), "--check", "checkout", "--strict", "-f", "json"]
    )
    assert strict.exit_code == 0


def test_selected_trace_preserves_budget_without_mutating_query(entry):
    capped = validate(entry, checks=["can_ship"], max_states=1)
    assert capped.verdict == "INCONCLUSIVE"
    assert trace_query(entry, "can_ship", max_states=1)["status"] == "INCONCLUSIVE"
    trace = trace_query(entry, "can_ship", max_states=20)
    assert trace["status"] == "PASS"
    assert [step["action"] for step in trace["steps"]] == ["reserve", "ship"]
    assert trace_spec(str(entry), "can_ship", max_states=20) == trace
    cli = CliRunner().invoke(
        app, ["trace", "can_ship", "-p", str(entry), "--max-states", "20", "-f", "json"]
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == trace
    assert prepare_model(entry).spec.queries[1].max_states == 10_000


def test_persistent_mcp_transport_forwards_selection(entry):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def exercise():
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "analint.mcp_server"], env={**os.environ}
        )
        async with (
            asyncio.timeout(60),
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            for check in ("checkout", "release_reservation"):
                reply = await session.call_tool("check", {"path": str(entry), "checks": [check]})
                assert not reply.isError
                data = json.loads(reply.content[0].text)
                assert data["selection"]["requested"] == [f"flow:{check}"]
                assert data["queries"] == []
            reply = await session.call_tool(
                "trace", {"path": str(entry), "query": "can_ship", "max_states": 1}
            )
            assert not reply.isError
            assert json.loads(reply.content[0].text)["status"] == "INCONCLUSIVE"

    asyncio.run(exercise())


def test_selected_invariant_and_duplicate_selectors(entry):
    spec = prepare_model(entry).spec
    order = next(cls for cls in spec.entities if cls.__name__ == "Order")
    spec.invariants.append(Invariant(order.shipped == order.shipped, id="reflexive"))
    result = validate_spec(
        spec, checks=["reservation_owns_stock", "invariant:reservation_owns_stock"]
    )
    assert result.verdict == "PASS"
    assert result.selection["requested"] == ["invariant:reservation_owns_stock"]
    assert result.selection["supporting"] == ["invariant:reflexive"]
    assert len(result.invariant_results) == 2
    assert result.query_results == result.flow_results == result.scenario_results == []


def test_qualified_trace_resolves_query_invariant_collision(entry):
    entry.write_text(entry.read_text().replace('id="can_ship"', 'id="reservation_owns_stock"'))
    with pytest.raises(ExplorationError) as error:
        trace_query(entry, "reservation_owns_stock")
    assert error.value.kind == "ambiguous_property"
    query = trace_query(entry, "query:reservation_owns_stock")
    assert query["status"] == "PASS"
    assert [step["action"] for step in query["steps"]] == ["reserve", "ship"]
    invariant = trace_query(entry, "invariant:reservation_owns_stock")
    assert invariant["status"] == "PASS"
    assert invariant["witness"] is None


def test_canonical_and_own_roots_are_not_replaced_by_selection(entry):
    spec = prepare_model(entry).spec
    order = next(cls for cls in spec.entities if cls.__name__ == "Order")
    stock = next(cls for cls in spec.entities if cls.__name__ == "Stock")
    spec.initial = Initial(given=[order(reserved=True, shipped=True), stock(available=False)])
    spec.queries[1].given = [order(), stock()]
    before = repr(spec)
    selected = validate_spec(spec, checks=["can_ship", "release_reservation"])
    full = validate_spec(spec)
    assert selected.verdict == "PASS"
    assert selected.query_results[0].trace == ["reserve", "ship"]
    assert _stable(result_to_dict(selected)["queries"][0]) == _stable(
        result_to_dict(full)["queries"][1]
    )
    assert selected.flow_results[0].passed
    assert repr(spec) == before
    spec.initial = Initial(where=[order.reserved, Not(order.reserved)])
    invalid = validate_spec(spec, checks=["checkout"])
    assert invalid.verdict == "FAIL"
    assert any(
        f.code.value == "model.canonical_initial_error" for f in invalid.exploration_findings
    )


def test_excluded_actions_are_reported_and_cannot_turn_a_property_green():
    class Signal(Event):
        ok: bool

    class Box(Entity):
        value: int = 0

    event_step = Action(id="event_step", pre=[Signal.ok], effect=[Set(Box.value, 1)])
    spec = Spec(
        id="excluded",
        name="Excluded event action",
        actions=[event_step],
        queries=[AlwaysHolds(Box.value == 0, id="zero")],
    )
    result = validate_spec(spec, checks=["zero"])
    assert result.verdict == "INCONCLUSIVE"
    assert result.selection["model_actions"] == ["event_step"]
    assert "event_step" in result.selection["excluded_actions"]


def test_repeated_cli_selectors_and_mcp_scenario_filters(entry):
    cli = CliRunner().invoke(
        app,
        [
            "check",
            str(entry),
            "--check",
            "checkout",
            "--check",
            "can_ship",
            "--scenario",
            "reserve_example",
            "--tag",
            "checkout",
            "-f",
            "json",
        ],
    )
    assert cli.exit_code == 0, cli.output
    remote = check_spec(
        str(entry),
        checks=["checkout", "can_ship"],
        scenario_ids=["reserve_example"],
        tags=["checkout"],
    )
    assert _stable(json.loads(cli.stdout)) == _stable(remote)
    untested = entry.parent / "untested.py"
    untested.write_text(
        entry.read_text().replace(
            "scenarios=[reserve_example, ship_example, release_example]",
            "scenarios=[reserve_example]",
        )
    )
    strict = CliRunner().invoke(
        app, ["check", str(untested), "--check", "checkout", "--strict", "-f", "json"]
    )
    assert strict.exit_code == 1  # unselected/orphan behavior still warns
    assert json.loads(strict.stdout)["passed"] is False


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize(
    "query_type,target,status",
    [
        (AlwaysHolds, 0, "INCONCLUSIVE"),
        (AlwaysHolds, 1, "FAIL"),
        (Unreachable, 1, "INCONCLUSIVE"),
        (Unreachable, 0, "FAIL"),
        (Reachable, 1, "INCONCLUSIVE"),
        (Reachable, 0, "PASS"),
        (NoDeadEnd, 0, "INCONCLUSIVE"),
        (NoDeadEnd, 1, "INCONCLUSIVE"),
    ],
)
def test_incomplete_transition_relation_does_not_prove_unseen_behavior(
    sliced, query_type, target, status
):
    class Signal(Event):
        ok: bool

    class Box(Entity):
        value: int = 0

    query = query_type(Box.value == target, id="property")
    spec = Spec(
        id="partial",
        name="Partial",
        queries=[query],
        actions=[Action(id="event_step", pre=[Signal.ok], effect=[Set(Box.value, 1)])],
    )
    selected = validate_spec(spec, checks=["property"], sliced=sliced)
    assert selected.query_results[0].status == status
    assert _stable(result_to_dict(selected)["queries"]) == _stable(
        result_to_dict(validate_spec(spec, sliced=sliced))["queries"]
    )
    if status == "INCONCLUSIVE":
        assert any(
            f.code.value == "check.excluded_actions" for f in selected.query_results[0].findings
        )

"""Invalid materialized event values are transition defects, never exceptions (#20)."""

import asyncio
import json
import os
import sys

import pytest
from typer.testing import CliRunner

from analint import Action, Entity, Event, Field, Spec
from analint.backends.tla import ExportError, Target, export_tla
from analint.cli import app
from analint.mcp_server import check_spec, explore_spec
from analint.reporter.base import Code
from analint.validator.engine import prepare_model, validate
from analint.validator.exploration_service import explore_path
from analint.validator.explorer import build_canonical_initials, explore
from analint.validator.kernel import Outcome, step

SOURCE = """from analint import Action, AlwaysHolds, Entity, Event, Expect, Field, Flow, Scenario, Set, Spec

class Order(Entity):
    total: int = Field(0, ge=0, le=10)

class Paid(Event):
    amount: int = Field(DEFAULT, CONSTRAINT)

start = Action(pre=[Order.total == 0], effect=[Set(Order.total, 5)])
pay = Action(pre=[Order.total == 5], effect=[Set(Order.total, 0)],
             emits=[Paid(amount=EXPRESSION)])
positive = Scenario(name='pay', action=pay, given=[Order(total=5)])
negative = Scenario(name='not a rejection', action=pay, given=[Order(total=5)], expected=Expect.FAIL)
journey = Flow(given=[Order()], steps=[start, pay])
safe = AlwaysHolds(Order.total >= 0)
spec = Spec(id='payload', name='Payload', actions=[start, pay],
            scenarios=[positive, negative], flows=[journey], queries=[safe])
"""


@pytest.fixture
def entry(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(
        SOURCE.replace("DEFAULT", "0")
        .replace("CONSTRAINT", "ge=0, le=10")
        .replace("EXPRESSION", "Order.total - 10")
    )
    return path


@pytest.mark.parametrize(
    ("constraint", "default", "expression"),
    [
        ("ge=0, le=10", "0", "Order.total - 10"),
        ("ge=0, le=10", "0", "Order.total + 11"),
        ("gt=0", "5", "Order.total"),
        ("lt=5", "0", "Order.total + 5"),
        ("values=[0, 5]", "0", "Order.total + 1"),
        ("ge=0, le=10, saturate=True", "0", "Order.total - 10"),
    ],
)
def test_payload_constraints_fail_every_native_execution_path(
    entry, constraint, default, expression
):
    entry.write_text(
        SOURCE.replace("DEFAULT", default)
        .replace("CONSTRAINT", constraint)
        .replace("EXPRESSION", expression)
    )
    prepared = prepare_model(entry)
    assert not prepared.load_errors
    assert not prepared.has_structural_errors
    spec = prepared.spec
    order = spec.scenarios[0].given[0]
    before = dict(order.__dict__)
    transition = step(spec, spec.actions[1], {type(order): order}, trace=["start"])
    assert transition.outcome is Outcome.DEFECT
    assert transition.entered
    assert transition.post_context is None
    assert transition.emitted == []
    assert order.__dict__ == before
    assert transition.findings[0].code is Code.FIELD_CONSTRAINT
    assert "emitted Paid.amount" in transition.findings[0].message
    assert "[after: start → pay]" in transition.findings[0].message

    result = validate(entry)
    assert result.verdict == "FAIL"
    assert all(not scenario.passed for scenario in result.scenario_results)
    assert all(
        any(f.code is Code.FIELD_CONSTRAINT and not f.expected for f in scenario.findings)
        for scenario in result.scenario_results
    )
    [flow] = result.flow_results
    assert not flow.passed
    assert flow.trace == ["start"]
    assert any(f.code is Code.FIELD_CONSTRAINT for f in flow.findings)

    roots, _ = build_canonical_initials(spec)
    exploration = explore(spec, roots, 100)
    assert not exploration.capped
    assert len(exploration.states) == 2
    assert [action for _, action, _ in exploration.edges] == ["start"]
    assert any(
        f.code is Code.FIELD_CONSTRAINT and "[after: start → pay]" in f.message
        for f in exploration.findings
    )
    with pytest.raises(ExportError, match=r"constrained emitted payload Paid\.amount"):
        export_tla(spec, roots, target=Target("always", True))


def test_cli_and_mcp_return_reports_for_invalid_payload(entry):
    runner = CliRunner()
    checked = runner.invoke(app, ["check", str(entry), "--format", "json"])
    assert checked.exit_code == 1, checked.output
    data = json.loads(checked.stdout)
    assert data["verdict"] == "FAIL"
    assert data["scenarios"][0]["findings"][0]["code"] == "transition.field_constraint"
    assert "got -10" in data["scenarios"][0]["findings"][0]["message"]
    human = runner.invoke(app, ["check", str(entry)])
    assert human.exit_code == 1
    assert "Traceback" not in human.output

    explored = runner.invoke(app, ["explore", str(entry), "--format", "json"])
    assert explored.exit_code == 0, explored.output
    artifact = json.loads(explored.stdout)
    assert artifact["schema"] == "analint.exploration/v1"
    assert artifact["findings"][0]["code"] == "transition.field_constraint"
    assert "[after: start → pay]" in artifact["findings"][0]["message"]
    assert artifact == explore_path(entry, include_graph=False).to_dict()
    assert check_spec(str(entry))["verdict"] == "FAIL"
    assert explore_spec(str(entry))["findings"] == artifact["findings"]


def test_mcp_transport_returns_defects_without_protocol_errors(entry):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def exercise():
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "analint.mcp_server"], env={**os.environ}
        )
        async with (
            asyncio.timeout(30),
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            checked = await session.call_tool("check", {"path": str(entry)})
            assert not checked.isError
            report = json.loads(checked.content[0].text)
            assert report["verdict"] == "FAIL"
            assert report["scenarios"][0]["findings"][0]["code"] == "transition.field_constraint"
            explored = await session.call_tool("explore", {"path": str(entry)})
            assert not explored.isError
            artifact = json.loads(explored.content[0].text)
            assert artifact["findings"][0]["code"] == "transition.field_constraint"
            assert "[after: start → pay]" in artifact["findings"][0]["message"]

    asyncio.run(exercise())


def test_valid_payload_and_bare_event_keep_existing_semantics(entry):
    entry.write_text(entry.read_text().replace("Order.total - 10", "Order.total"))
    spec = prepare_model(entry).spec
    order = spec.scenarios[0].given[0]
    result = step(spec, spec.actions[1], {type(order): order})
    assert result.outcome is Outcome.ACCEPTED
    assert result.emitted[0].amount == 0  # event values read the post-state
    paid = type(result.emitted[0])
    bare = Action(id="bare", emits=[paid])
    bare_result = step(spec, bare, {type(order): order})
    assert bare_result.outcome is Outcome.ACCEPTED
    assert bare_result.emitted == [paid]  # bare classes do not instantiate a payload


def test_constructor_errors_are_evaluation_defects_and_discard_partial_emissions():
    class Order(Entity):
        total: int = Field(0, ge=0, le=5)

    class Notice(Event):
        pass

    class Paid(Event):
        amount: int

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            if type(self.amount) is int:
                raise ValueError("constructor failed")

    action = Action(id="pay", emits=[Notice(), Paid(amount=Order.total)])
    spec = Spec(id="s", name="S", actions=[action])
    result = step(spec, action, {Order: Order()}, trace=["start"])
    assert result.outcome is Outcome.DEFECT
    assert result.post_context is None
    assert result.emitted == []
    assert result.findings[0].code is Code.EVALUATION_ERROR
    assert "constructor failed" in result.findings[0].message
    assert "[after: start → pay]" in result.findings[0].message

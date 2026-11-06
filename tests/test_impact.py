"""Impact reports must include initialization, expressions and implicit guards."""

import json
from enum import Enum
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    Add,
    Bound,
    Count,
    Create,
    Delete,
    Entity,
    Event,
    Field,
    ForAll,
    Invariant,
    Key,
    Lifecycle,
    Max,
    Min,
    Not,
    Param,
    Present,
    Scope,
    Set,
    Spec,
    Subtract,
    Sum,
)
from analint import query as q
from analint.cli import app
from analint.mcp_server import affects_target, show_spec
from analint.validator.engine import build_spec, validate


@pytest.fixture
def issue4(tmp_path):
    path = tmp_path / "spec.py"
    path.write_text(
        dedent("""\
        from analint import Absent, Action, Create, Entity, Field, Not, Present, Scenario, Scope, Set, Spec

        class Record(Entity):
            flag: bool = Field(default=False)

        records = Scope(Record, keys=["record"], id="records")
        record = records["record"]
        create_record = Action(pre=[Not(Present(record))], effect=[Create(record, flag=True)])
        set_flag = Action(pre=[Present(record), record.flag == False], effect=[Set(record.flag, True)])
        create_initializes_flag = Scenario(
            action=create_record, given=[Absent(record)],
            then=[Present(record), record.flag == True],
        )
        set_updates_flag = Scenario(
            action=set_flag, given=[record(flag=False)], then=[record.flag == True],
        )
        probe = Spec(
            id="affects_create_probe", name="Create field initialization impact probe",
            actions=[create_record, set_flag],
            scenarios=[create_initializes_flag, set_updates_flag],
        )
        """)
    )
    return path


def test_issue4_reports_both_writers_and_their_scenarios(issue4):
    result = validate(issue4)
    assert result.effective_verdict() == "PASS"
    assert len(result.scenario_results) == 2
    payload = affects_target("Record.flag", str(issue4))
    assert {w["action"] for w in payload["written_by"]} == {"create_record", "set_flag"}
    assert payload["written_by"][0] == {
        "action": "create_record",
        "effect": "Create(Record['record'], flag=True)",
        "initialization": "explicit",
    }
    assert payload["scenarios"] == ["create_initializes_flag", "set_updates_flag"]
    assert affects_target("create_record", str(issue4))["writes"] == [
        "Create(Record['record'], flag=True)"
    ]
    entity = show_spec(str(issue4), "entity", "Record")
    assert entity["written_by"] == ["create_record", "set_flag"]


@pytest.mark.parametrize("target", ["Record.flag", "Record", "create_record", "set_flag"])
def test_issue4_query_cli_and_mcp_agree(issue4, target):
    spec, _, errors = build_spec(issue4)
    assert spec is not None, errors
    expected = q.affects(spec, target)
    cli = CliRunner().invoke(app, ["affects", target, "-p", str(issue4)])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.output) == expected == affects_target(target, str(issue4))
    assert expected["schema"] == "analint.affects/v1"


@pytest.fixture
def impact():
    class Status(Enum):
        ACTIVE = "active"
        CLOSED = "closed"

    class Source(Entity):
        value: int = Field(default=1, ge=0, le=3)

    class Item(Entity):
        value: int = Field(default=0, ge=0, le=3)
        owner: str = "none"
        status: Status = Lifecycle(
            initial=Status.ACTIVE,
            transitions={Status.ACTIVE: [Status.CLOSED]},
            terminal=[Status.CLOSED],
        )

    class Notice(Event):
        value: int

    class IdentityNotice(Event):
        owner: str

    slots = Scope(Item, keys=["a", "b"], initially_present=False, id="slots")
    a, b = slots["a"], slots["b"]
    item = Bound("item", slots)
    target = Param("target", slots)
    create = Action(id="create", params=[target], effect=[Create(target, value=Source.value + 1)])
    defaults = Action(id="defaults", effect=[Create(a)])
    copy = Action(id="copy", effect=[Set(a.value, (Source.value + 1) * 2)])
    add = Action(id="add", effect=[Add(a.value, Source.value)])
    subtract = Action(id="subtract", effect=[Subtract(b.value, Source.value)])
    delete = Action(id="delete", effect=[Delete(a)])
    absent = Action(id="absent", pre=[Not(Present(a))])
    keys = Action(id="keys", emits=[IdentityNotice(owner=Key(a))])
    quantified = Action(id="quantified", pre=[ForAll(item, Key(item) == "a")])
    emit = Action(id="emit", emits=[Notice(value=Source.value + 1)])
    aggregate = Action(
        id="aggregate",
        emits=[Notice(value=Sum(item, item.value) + Count(item, item.value > Source.value))],
    )
    extrema = Action(
        id="extrema", emits=[Notice(value=Min(item, item.value) + Max(item, item.value))]
    )
    membership = Invariant(Count(item, Key(item) == "a") <= 1, id="membership")
    spec = Spec(
        id="impact",
        name="Impact inventory",
        actions=[
            create,
            defaults,
            copy,
            add,
            subtract,
            delete,
            absent,
            keys,
            quantified,
            emit,
            aggregate,
            extrema,
        ],
        invariants=[membership],
    )
    return spec


def test_create_initializes_defaults_and_expanded_targets(impact):
    payload = q.affects(impact, "Item.value")
    creates = [w for w in payload["written_by"] if w["effect"].startswith("Create(")]
    assert len(creates) == 3
    assert {w["initialization"] for w in creates} == {"default", "explicit"}
    assert {w["effect"] for w in creates} == {
        "Create(Item['a'], value=(Source.value + 1))",
        "Create(Item['b'], value=(Source.value + 1))",
        "Create(Item['a'])",
    }
    owner = q.affects(impact, "Item.owner")
    assert len(owner["written_by"]) == 3
    assert all(w["initialization"] == "default" for w in owner["written_by"])
    assert "delete" not in {w["action"] for w in payload["written_by"]}


def test_rhs_and_event_expression_readers_are_included(impact):
    payload = q.affects(impact, "Source.value")
    create_ids = {a.id for a in impact.actions if a.id.startswith("create(")}
    assert len(create_ids) == 2
    assert set(payload["read_by"]) == create_ids | {"copy", "add", "subtract", "emit", "aggregate"}
    assert payload["event_bindings"] == [
        {"action": "emit", "event": "Notice", "payload_field": "value"},
        {"action": "aggregate", "event": "Notice", "payload_field": "value"},
    ]
    assert q.affects(impact, "copy")["reads"] == ["Item['a'].status", "Source.value"]
    assert q.affects(impact, "emit")["emits"] == ["Notice(value=(Source.value + 1))"]
    assert q.describe(impact, "entity", "Source")["read_by"] == payload["read_by"]


@pytest.mark.parametrize("action,slot", [("add", "a"), ("subtract", "b")])
def test_numeric_updates_read_the_old_target(impact, action, slot):
    payload = q.affects(impact, action)
    assert payload["reads"] == [f"Item['{slot}'].status", f"Item['{slot}'].value", "Source.value"]
    assert payload["presence_reads"] == [f"Item['{slot}']"]
    assert payload["presence_writes"] == []


@pytest.mark.parametrize("action", ["aggregate", "extrema"])
def test_aggregate_payloads_read_fields_and_domain_presence(impact, action):
    payload = q.affects(impact, action)
    assert {"Item['a'].value", "Item['b'].value"} <= set(payload["reads"])
    assert payload["presence_reads"] == ["Item['a']", "Item['b']"]
    bindings = q.affects(impact, "Item.value")["event_bindings"]
    assert {b["action"] for b in bindings} == {"aggregate", "extrema"}


def test_presence_and_terminal_guards_are_separate_from_field_writes(impact):
    delete = q.affects(impact, "delete")
    assert delete["reads"] == ["Item['a'].status"]
    assert delete["writes"] == ["Delete(Item['a'])"]
    assert delete["presence_reads"] == ["Item['a']"]
    assert delete["presence_writes"] == [{"instance": "Item['a']", "present": False}]
    defaults = q.affects(impact, "defaults")
    assert defaults["reads"] == []  # Create has no terminal-state lock.
    assert defaults["presence_reads"] == ["Item['a']"]
    assert defaults["presence_writes"] == [{"instance": "Item['a']", "present": True}]
    assert q.affects(impact, "absent")["reads"] == []
    assert q.affects(impact, "absent")["presence_reads"] == ["Item['a']"]
    assert "delete" in q.affects(impact, "Item.status")["read_by"]
    entity = q.affects(impact, "Item")
    assert "delete" in entity["written_by"]
    assert "absent" in entity["read_by"]
    assert "absent" in entity["presence_read_by"]
    assert "delete" in entity["presence_written_by"]
    assert "membership" in entity["invariants"]
    assert q.describe(impact, "invariant", "membership")["entities"] == ["Item"]


def test_key_values_have_no_reads_but_quantifiers_read_membership(impact):
    keys = q.affects(impact, "keys")
    assert keys["reads"] == keys["presence_reads"] == []
    quantified = q.affects(impact, "quantified")
    assert quantified["reads"] == []
    assert quantified["presence_reads"] == ["Item['a']", "Item['b']"]
    assert "keys" not in q.affects(impact, "Item")["read_by"]


def test_payload_only_reader_includes_its_scenario():
    from analint import Scenario

    class Source(Entity):
        value: int = 1

    class Notice(Event):
        value: int

    emit = Action(id="emit", emits=[Notice(value=Source.value + Source.value)])
    scenario = Scenario(id="payload", action=emit, given=[Source()])
    spec = Spec(id="s", name="S", actions=[emit], scenarios=[scenario])
    payload = q.affects(spec, "Source.value")
    assert payload["read_by"] == ["emit"]
    assert payload["scenarios"] == ["payload"]
    assert payload["event_bindings"] == [
        {"action": "emit", "event": "Notice", "payload_field": "value"}
    ]


def test_nonterminal_lifecycle_assignment_reads_the_old_state():
    class Status(Enum):
        START = "start"
        END = "end"

    class Job(Entity):
        status: Status = Lifecycle(initial=Status.START, transitions={Status.START: [Status.END]})

    finish = Action(id="finish", effect=[Set(Job.status, Status.END)])
    spec = Spec(id="s", name="S", actions=[finish])
    assert q.affects(spec, "finish")["reads"] == ["Job.status"]
    assert q.affects(spec, "Job.status")["read_by"] == ["finish"]

"""Read-only query and action-family inspection through the shared CLI/MCP surface."""

import json
from enum import StrEnum
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import (
    Absent,
    Action,
    AlwaysHolds,
    Bound,
    DeadActions,
    Entity,
    Field,
    Flow,
    Initial,
    NoDeadEnd,
    Param,
    Reachable,
    Scenario,
    Scope,
    Set,
    Spec,
    Unreachable,
)
from analint import query as q
from analint.cli import app
from analint.mcp_server import show_spec
from analint.validator.engine import build_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class Counter(Entity):
    n: int = Field(0, ge=0, le=2)


@pytest.mark.parametrize(
    "query_type", [Reachable, Unreachable, AlwaysHolds, NoDeadEnd, DeadActions]
)
def test_query_details_distinguish_predicate_goal_and_dead_actions(query_type):
    args = [] if query_type is DeadActions else [Counter.n == 1]
    query = query_type(*args, id="target", label="Target property", max_states=23)
    spec = Spec(id="s", name="S", entities=[Counter], queries=[query], max_states=1)
    payload = q.show(spec, "query", "target")
    assert payload["schema"] == "analint.show/v1"
    assert payload["type"] == query_type.__name__
    assert payload["label"] == "Target property"
    assert payload["max_states"] == 23  # query budget, not canonical invariant budget
    assert payload["predicate"] == (
        "Counter.n == 1" if query_type in (Reachable, Unreachable, AlwaysHolds) else None
    )
    assert payload["goal"] == ("Counter.n == 1" if query_type is NoDeadEnd else None)
    assert payload["roots"] == {
        "source": "canonical",
        "given": [],
        "given_any": [],
        "initial": None,
    }
    assert "status" not in payload  # inspection does not decide the query


@pytest.mark.parametrize("source", ["canonical", "given", "given_any", "initial", "fixed_initial"])
def test_query_roots_show_own_starts_or_inherited_initial_without_expanding(source, monkeypatch):
    initial = Initial(vary=[Counter.n], where=[Counter.n == 0], max_candidates=7)
    starts = {
        "canonical": {},
        "given": {"given": [Counter(n=1)]},
        "given_any": {"given_any": [[], [Counter(n=2)]]},
        "initial": {"initial": Initial(vary=[Counter.n], where=[Counter.n != Counter.n])},
        "fixed_initial": {"initial": Initial()},
    }
    query = Reachable(Counter.n == 2, id="target", **starts[source])
    spec = Spec(id="s", name="S", queries=[query], initial=initial)

    def forbidden(*args, **kwargs):
        pytest.fail("show must not enumerate initial candidates or explore states")

    monkeypatch.setattr("analint.validator.explorer.build_initial_relation", forbidden)
    monkeypatch.setattr("analint.validator.explorer.explore", forbidden)
    roots = q.show(spec, "query", "target")["roots"]
    assert roots["source"] == ("canonical" if source == "canonical" else "query")
    if source == "canonical":
        assert roots["initial"] == {
            "vary": ["Counter.n"],
            "where": ["Counter.n == 0"],
            "given": [],
            "max_candidates": 7,
        }
    elif source == "given":
        assert roots["given"] == ["Counter(n=1)"]
        assert roots["initial"] is None
    elif source == "given_any":
        assert roots["given_any"] == [[], ["Counter(n=2)"]]
        assert roots["initial"] is None
    else:
        assert roots["initial"]["where"] == (
            ["Counter.n != Counter.n"] if source == "initial" else []
        )
        assert roots["initial"]["vary"] == (["Counter.n"] if source == "initial" else [])


def test_query_initial_preserves_bound_fields_and_absence():
    slots = Scope(Counter, keys=["a"], id="slots", initially_present=False)
    item = Bound("item", slots)
    initial = Initial(vary=[item.n], given=[Absent(slots["a"])])
    query = DeadActions(id="unused", initial=initial)
    spec = Spec(id="s", name="S", queries=[query])
    payload = q.describe(spec, "query", "unused")
    assert payload["roots"]["initial"]["vary"] == ["item.n"]
    assert payload["roots"]["initial"]["given"] == ["Absent(Counter['a'])"]
    assert json.loads(json.dumps(payload)) == payload


def test_family_contract_domains_filtered_members_and_coverage_are_inspectable(monkeypatch):
    class Choice(StrEnum):
        LOW = "low"
        HIGH = "high"

    slots = Scope(Counter, keys=["a", "b"])
    slot = Param("slot", slots)
    choice = Param("choice", Choice)
    amount = Param("amount", 1, 2)
    action = Action(
        id="assign",
        name="Assign counter",
        description="A family",
        tags=["write"],
        params=[slot, choice, amount],
        where=[choice == Choice.HIGH],
        pre=[slot.n == 0],
        effect=[Set(slot.n, amount)],
        post=[slot.n > 0],
    )
    bound = action.bind(slot=slots["a"], choice=Choice.HIGH, amount=1)
    spec = Spec(
        id="s",
        name="S",
        actions=[action],
        scenarios=[Scenario(id="sc", action=bound, given=[slots["a"]()])],
        flows=[Flow(id="journey", given=[slots["a"]()], steps=[bound, bound])],
    )
    concrete = q.show(spec, "action", bound.id)

    def forbidden(*args, **kwargs):
        pytest.fail("show must reuse existing expansions, not expand or evaluate where again")

    monkeypatch.setattr("analint.models.param.expand_action", forbidden)
    payload = q.show(spec, "action", "assign")
    assert payload["kind"] == "action_family"
    assert payload["name"] == "Assign counter"
    assert payload["params"] == [
        {"name": "slot", "domain": ["Counter['a']", "Counter['b']"]},
        {"name": "choice", "domain": ["Choice.LOW", "Choice.HIGH"]},
        {"name": "amount", "domain": ["1", "2"]},
    ]
    assert payload["where"] == ["choice == Choice.HIGH"]
    assert payload["pre"] == ["slot.n == 0"]
    assert payload["effect"] == ["slot.n = amount"]
    assert payload["post"] == ["slot.n > 0"]
    assert payload["variant_count"] == 4
    assert payload["variants"] == [a.id for a in spec.actions]
    assert all("HIGH" in variant for variant in payload["variants"])
    assert payload["scenarios"] == ["sc"]
    assert payload["flows"] == ["journey"]
    assert q.show(spec, "action", bound.id) == concrete
    assert concrete["kind"] == "action"
    assert concrete["effect"] == ["Counter['a'].n = 1"]


def test_family_with_no_variants_is_still_declared_and_inspectable():
    flag = Param("flag", bool)
    action = Action(id="never", params=[flag], where=[flag != flag])
    spec = Spec(id="s", name="S", actions=[action])
    payload = q.show(spec, "action", "never")
    assert payload["variant_count"] == 0
    assert payload["variants"] == []
    assert payload["params"] == [{"name": "flag", "domain": ["False", "True"]}]
    assert "never" in q.show(spec, "action", "missing")["known"]


def test_family_entity_class_domains_have_model_names():
    class Other(Entity):
        n: int = 0

    target = Param("target", Counter, Other)
    action = Action(id="clear", params=[target], effect=[Set(target.n, 0)])
    spec = Spec(id="s", name="S", actions=[action])
    payload = q.show(spec, "action", "clear")
    assert payload["params"] == [{"name": "target", "domain": ["Counter", "Other"]}]
    assert payload["effect"] == ["target.n = 0"]
    assert payload["variants"] == ["clear(target=Counter)", "clear(target=Other)"]


def test_exact_action_id_takes_precedence_over_a_family_name():
    value = Param("value", 1)
    family = Action(id="assign", params=[value], effect=[Set(Counter.n, value)])
    exact = Action(id="assign", effect=[Set(Counter.n, 2)])
    spec = Spec(id="s", name="S", actions=[family, exact])
    payload = q.show(spec, "action", "assign")
    assert payload["kind"] == "action"
    assert payload["effect"] == ["Counter.n = 2"]


@pytest.mark.parametrize(
    ("example", "kind", "name", "expected_kind"),
    [
        ("k8s_replicaset", "query", "quota_never_exceeded", "query"),
        ("oauth", "action", "redeem_code", "action_family"),
    ],
)
def test_existing_models_have_identical_library_cli_and_mcp_details(
    example, kind, name, expected_kind
):
    path = EXAMPLES / example
    spec, _, errors = build_spec(path)
    assert spec is not None, errors
    expected = q.show(spec, kind, name)
    assert expected["kind"] == expected_kind
    result = CliRunner().invoke(app, ["show", kind, name, "-p", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == show_spec(str(path), kind, name) == expected
    if kind == "action":
        contract = q.show(spec, "contract", "oauth-protocol")
        assert name in contract["actions"]
        assert expected["variant_count"] == 32
        variant = expected["variants"][0]
        assert show_spec(str(path), "action", variant)["kind"] == "action"
    else:
        assert expected["type"] == "AlwaysHolds"
        assert expected["roots"]["initial"]["vary"] == ["Namespace.quota"]


def test_query_lookup_and_irregular_singular_plural_lists_have_structured_results():
    query = DeadActions(id="unused")
    spec = Spec(id="s", name="S", entities=[Counter], queries=[query])
    for singular, plural in [("entity", "entities"), ("query", "queries")]:
        assert q.show(spec, singular)["items"] == q.show(spec, plural)["items"]
    missing = q.show(spec, "query", "missing")
    assert missing["schema"] == "analint.show/v1"
    assert missing["known"] == ["unused"]
    assert "error" in missing


def test_cli_and_mcp_unknown_query_report_the_same_lookup_error():
    path = str(EXAMPLES / "k8s_replicaset")
    result = CliRunner().invoke(app, ["show", "query", "missing", "-p", path])
    assert result.exit_code == 1
    assert json.loads(result.output) == show_spec(path, "query", "missing")

"""Invariant execution and applicability plans must not outlive a run (#11)."""

from copy import copy, deepcopy

import pytest

from analint import (
    Action,
    Add,
    Bound,
    Entity,
    Field,
    Flow,
    ForAll,
    Invariant,
    Scenario,
    Scope,
    Spec,
)
from analint.validator import validate_spec
from analint.validator.engine import prepare_model, validate
from analint.validator.exploration_service import trace_query
from analint.validator.explorer import explore
from analint.validator.flow_runner import run_flow
from analint.validator.scenario_runner import run_scenario


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("cache", [False, True])
@pytest.mark.parametrize(
    "kind", ["comparison", "arithmetic", "conjunction", "membership", "quantifier"]
)
def test_nested_edits_refresh_check_and_trace(tmp_path, monkeypatch, sliced, cache, kind):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    expressions = {
        "comparison": "Counter.n <= 3",
        "arithmetic": "Counter.n + 0 <= 3",
        "conjunction": "And(Counter.n >= 0, Counter.n <= 3)",
        "membership": "In(Counter.n, [0, 1, 2, 3])",
        "quantifier": "ForAll(item, item.n <= 3)",
    }
    scoped = kind == "quantifier"
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, And, Bound, Entity, Field, ForAll, In, Invariant, Scope, Spec\n"
        "class Counter(Entity):\n    n: int = Field(0, ge=0, le=3)\n"
        + (
            "slots = Scope(Counter, keys=['a'])\nitem = Bound('item', slots)\ntarget = slots['a']\n"
            if scoped
            else "target = Counter\n"
        )
        + "tick = Action(id='tick', pre=[target.n < 3], effect=[Add(target.n, 1)])\n"
        + f"limit = Invariant({expressions[kind]}, id='limit')\n"
        + "spec = Spec(id='s', name='S', actions=[tick], invariants=[limit])\n"
    )
    prepared = prepare_model(entry)
    assert prepared.spec is not None and not prepared.has_structural_errors
    expression = prepared.spec.invariants[0].expression
    settings = {"sliced": sliced, "cache": cache}
    assert validate(entry, **settings).verdict == "PASS"
    assert trace_query(entry, "limit", **settings)["status"] == "PASS"

    if kind == "comparison":
        expression.right = 1
    elif kind == "arithmetic":
        expression.left.right = 2
    elif kind == "conjunction":
        expression.exprs.append(prepared.spec.entities[0].n <= 1)
    elif kind == "membership":
        expression.values[:] = [0, 1]
    else:
        expression.predicate.right = 1

    # Repeat once more to cover a warm disk-cache result of the edited model.
    for _ in range(2):
        report = validate(entry, **settings)
        assert report.verdict == "FAIL"
        assert report.invariant_results[0].status == "FAIL"
        assert report.invariant_results[0].trace == ["tick", "tick"]
        trace = trace_query(entry, "limit", **settings)
        assert trace["status"] == "FAIL"
        assert [step["action"] for step in trace["steps"]] == ["tick", "tick"]


class Counter(Entity):
    n: int = Field(0, ge=0, le=3)


@pytest.mark.parametrize("copy_kind", ["shallow", "deep", "model_deep"])
@pytest.mark.parametrize("sliced", [False, True])
def test_edits_to_a_previously_checked_copy_are_observed(copy_kind, sliced):
    tick = Action(id="tick", pre=[Counter.n < 3], effect=[Add(Counter.n, 1)])
    original = Spec(
        id="s", name="S", actions=[tick], invariants=[Invariant(Counter.n <= 3, id="limit")]
    )
    assert validate_spec(original, sliced=sliced).verdict == "PASS"
    if copy_kind == "model_deep":
        edited = original.model_copy(deep=True)
    elif copy_kind == "deep":
        edited = deepcopy(original)
    else:
        edited = copy(original)
    edited.invariants[0].expression.right = 1
    assert validate_spec(edited, sliced=sliced).verdict == "FAIL"
    # Shallow copies deliberately share declarations; deep copies isolate them.
    expected = "FAIL" if copy_kind == "shallow" else "PASS"
    assert validate_spec(original, sliced=sliced).verdict == expected


@pytest.mark.parametrize("runner", ["scenario", "flow"])
def test_changed_applicability_is_observed_with_absent_scoped_slots(runner):
    slots = Scope(Counter, keys=["absent", "present"])
    absent, present = slots
    idle = Action(id="idle")
    limit = Invariant(absent.n <= 0, id="limit")
    scenario = Scenario(id="once", action=idle, given=[present(n=1)])
    flow = Flow(id="journey", steps=[idle], given=[present(n=1)])
    spec = Spec(id="s", name="S", actions=[idle], invariants=[limit])

    def run():
        return run_scenario(scenario, spec) if runner == "scenario" else run_flow(flow, spec)

    assert run().passed  # the invariant is inapplicable
    limit.expression.left = present.n
    assert not run().passed  # it now applies, and is false
    limit.expression.left = absent.n
    assert run().passed


@pytest.mark.parametrize("model_copy", [False, True])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("cache", [False, True])
def test_scoped_copy_rebuilds_quantified_closures_and_trace(
    tmp_path, monkeypatch, model_copy, sliced, cache
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, Bound, Entity, Field, ForAll, Invariant, Scope, Spec\n"
        "class Counter(Entity):\n    n: int = Field(0, ge=0, le=3)\n"
        "slots = Scope(Counter, keys=['a'])\n"
        "item = Bound('item', slots)\n"
        "tick = Action(id='tick', pre=[slots['a'].n < 3], effect=[Add(slots['a'].n, 1)])\n"
        "limit = Invariant(ForAll(item, item.n <= 3), id='limit')\n"
        "spec = Spec(id='s', name='S', actions=[tick], invariants=[limit])\n"
    )
    prepared = prepare_model(entry)
    original = prepared.spec
    settings = {"sliced": sliced, "cache": cache}
    assert validate(entry, **settings).verdict == "PASS"
    assert original is not None
    edited = original.model_copy(deep=True) if model_copy else deepcopy(original)
    edited.invariants[0].expression.predicate.right = 1
    # Exercise trace through the real loader's cached module with the new root.
    module = next(m for m in prepared.modules if getattr(m, "spec", None) is original)
    monkeypatch.setattr(module, "spec", edited)
    for _ in range(2):
        assert validate(entry, **settings).verdict == "FAIL"
        trace = trace_query(entry, "limit", **settings)
        assert trace["status"] == "FAIL"
        assert [step["action"] for step in trace["steps"]] == ["tick", "tick"]
    assert validate_spec(original, **settings).verdict == "PASS"


def test_plans_are_reused_within_exploration_without_mutating_declarations(monkeypatch):
    from analint.validator import state_checks

    slots = Scope(Counter, keys=["a"])
    item = Bound("item", slots)
    tick = Action(id="tick", pre=[slots["a"].n < 3], effect=[Add(slots["a"].n, 1)])
    limit = Invariant(ForAll(item, item.n <= 3), id="limit")
    spec = Spec(id="s", name="S", actions=[tick], invariants=[limit])
    attributes = vars(limit).copy()
    compiled = []
    compile_predicate = state_checks.compile_predicate

    def counted(expression):
        compiled.append(expression)
        return compile_predicate(expression)

    monkeypatch.setattr(state_checks, "compile_predicate", counted)
    roots = [{slots["a"]: slots["a"]()}]
    assert len(explore(spec, roots, 10).states) == 4
    assert len(compiled) == 1
    limit.expression.predicate.right = 1
    result = explore(spec, roots, 10)
    assert len(result.states) == 3  # the illegal successor is retained, not expanded
    assert len(result.findings) == 1
    assert len(compiled) == 2
    assert vars(limit).keys() == attributes.keys()
    assert all(value is attributes[key] for key, value in vars(limit).items())


@pytest.mark.parametrize("edit", ["guard", "effect", "query"])
@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("cache", [False, True])
def test_action_and_query_edits_also_refresh_check_and_trace(
    tmp_path, monkeypatch, edit, sliced, cache
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, Entity, Field, Reachable, Spec\n"
        "class Counter(Entity):\n    n: int = Field(0, ge=0, le=3)\n"
        "tick = Action(id='tick', pre=[Counter.n < 3], effect=[Add(Counter.n, 1)])\n"
        "three = Reachable(Counter.n == 3, id='three')\n"
        "spec = Spec(id='s', name='S', actions=[tick], queries=[three])\n"
    )
    spec = prepare_model(entry).spec
    assert spec is not None
    settings = {"sliced": sliced, "cache": cache}
    assert validate(entry, **settings).verdict == "PASS"
    assert len(trace_query(entry, "three", **settings)["steps"]) == 3
    if edit == "guard":
        spec.actions[0].pre[0].right = 1
    elif edit == "effect":
        spec.actions[0].effect[0].amount = 0
    else:
        spec.queries[0].predicate.right = 4
    for _ in range(2):
        assert validate(entry, **settings).verdict == "FAIL"
        trace = trace_query(entry, "three", **settings)
        assert trace["status"] == "FAIL"
        assert trace["witness"] is None

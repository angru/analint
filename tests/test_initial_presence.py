"""Scope defaults affect canonical roots, while snapshots remain explicit."""

import pytest

from analint import (
    Absent,
    Action,
    And,
    Bound,
    Count,
    Create,
    Entity,
    Field,
    Flow,
    ForAll,
    Initial,
    Invariant,
    Key,
    Param,
    Present,
    Reachable,
    Scenario,
    Scope,
    Spec,
    Sum,
)
from analint.query import describe, spec_overview
from analint.validator.exploration_cache import digest
from analint.validator.explorer import (
    build_canonical_initials,
    build_initial,
    build_initial_relation,
    explore,
    resolve_query_initials,
    run_query,
    verify_invariants,
)
from analint.validator.flow_runner import run_flow
from analint.validator.rule_checker import evaluate
from analint.validator.scenario_runner import run_scenario


class Item(Entity):
    value: int = Field(1, ge=1, le=2)


@pytest.mark.parametrize("policy", [True, False])
def test_explicit_snapshots_override_scope_defaults_in_every_root_source(policy):
    slots = Scope(Item, keys=["a", "b", "c"], initially_present=policy)
    a, b, c = slots["a"], slots["b"], slots["c"]
    fixed = Initial(given=[a(value=2), Absent(b)])
    spec = Spec(id="s", name="S", scopes=[slots], initial=fixed)
    for roots, error in (
        build_canonical_initials(spec),
        build_initial_relation(spec, fixed),
        resolve_query_initials(Reachable(Present(a), given=fixed.given), spec),
        resolve_query_initials(Reachable(Present(a), given_any=[fixed.given]), spec),
        resolve_query_initials(Reachable(Present(a), initial=fixed), spec),
    ):
        assert error is None
        assert len(roots) == 1
        assert evaluate(Present(a), roots[0])
        assert not evaluate(Present(b), roots[0])
        assert evaluate(Present(c), roots[0]) is policy
        assert roots[0][a].value == 2

    own = Reachable(Present(b), initial=Initial(given=[Absent(a), b()]))
    roots, error = resolve_query_initials(own, spec)
    assert error is None
    assert not evaluate(Present(a), roots[0])
    assert evaluate(Present(b), roots[0])
    inherited, _ = resolve_query_initials(Reachable(Present(a)), spec)
    assert evaluate(Present(a), inherited[0])
    assert not evaluate(Present(b), inherited[0])


def test_omitted_policy_keeps_present_defaults_and_scenarios_flows_keep_partial_worlds():
    slots = Scope(Item, keys=["a", "b"])
    x = Bound("x", slots)
    audit = Action(id="audit", pre=[Count(x, Present(x)) == 0])
    spec = Spec(id="s", name="S", scopes=[slots], actions=[audit])
    roots, error = build_canonical_initials(spec)
    assert error is None
    assert evaluate(Count(x, Present(x)) == 2, roots[0])
    scenario = Scenario(id="s", name="S", action=audit, given=[])
    flow = Flow(id="f", given=[], steps=[audit])
    assert run_scenario(scenario, spec).passed
    assert run_flow(flow, spec).passed


def test_absent_required_slots_can_be_created_with_explicit_values():
    class Required(Entity):
        value: int

    slots = Scope(Required, keys=["a"], initially_present=False)
    a = slots["a"]
    create = Action(id="create", effect=[Create(a, value=2)])
    query = Reachable(And(Present(a), a.value == 2), id="q")
    spec = Spec(id="s", name="S", actions=[create], queries=[query])
    assert spec.scopes == [slots]
    roots, error = build_canonical_initials(spec)
    assert error is None
    assert not evaluate(Present(a), roots[0])
    result = run_query(query, spec, {})
    assert result.status == "PASS"
    assert result.trace == ["create"]
    unguarded = run_query(Reachable(a.value == 2, id="unsafe"), spec, {})
    assert unguarded.status == "FAIL"
    assert "is absent" in unguarded.findings[0].message


def test_initial_relation_can_mix_explicit_presence_and_finite_field_roots():
    class Flag(Entity):
        enabled: bool = False

    slots = Scope(Item, keys=["a", "b"], initially_present=False)
    x = Bound("x", slots)
    spec = Spec(
        id="s",
        name="S",
        scopes=[slots],
        entities=[Flag],
        initial=Initial(
            vary=[Flag.enabled], given=[slots["a"]()], where=[Count(x, Present(x)) == 1]
        ),
    )
    roots, error = build_canonical_initials(spec)
    assert error is None
    assert len(roots) == 2
    assert {root[Flag].enabled for root in roots} == {False, True}
    for root in roots:
        assert evaluate(Sum(x, x.value) == 1, root)
        assert evaluate(ForAll(x, x.value >= 1), root)


def test_varying_a_field_does_not_implicitly_create_an_absent_slot():
    slots = Scope(Item, keys=["a"], initially_present=False)
    a = slots["a"]
    spec = Spec(id="s", name="S", scopes=[slots])
    roots, error = build_initial_relation(spec, Initial(vary=[a.value]))
    assert roots is None
    assert "because the entity is absent" in error
    roots, error = build_initial_relation(spec, Initial(vary=[a.value], given=[a()]))
    assert error is None
    assert {root[a].value for root in roots} == {1, 2}


def test_initial_policy_joins_the_cache_digest_even_with_identical_explicit_roots():
    slots = Scope(Item, keys=["a"], initially_present=False)
    spec = Spec(id="s", name="S", scopes=[slots])
    root, error = build_initial(spec, [Absent(slots["a"])])
    assert error is None
    first = digest(spec, [root], 100, None, frozenset())[0]
    slots.initially_present = True
    assert digest(spec, [root], 100, None, frozenset())[0] != first


@pytest.mark.parametrize("sliced", [False, True])
def test_an_empty_scope_does_not_hide_a_broken_canonical_invariant(sliced):
    from analint.validator.slicing import SliceAnalysis

    slots = Scope(Item, keys=["a"], initially_present=False)
    x = Bound("x", slots)
    safe = Invariant(Sum(x, x.value) == 1, id="requires_one")
    spec = Spec(id="s", name="S", invariants=[safe])
    roots, error = build_canonical_initials(spec)
    assert error is None
    results, _ = verify_invariants(spec, roots, analysis=SliceAnalysis(spec) if sliced else None)
    assert results[0].status == "FAIL"
    assert results[0].trace == []


@pytest.mark.parametrize("policy", [0, 1, "false", None])
def test_initial_policy_is_a_boolean(policy):
    with pytest.raises(TypeError, match="initially_present must be a bool"):
        Scope(Item, keys=["a"], initially_present=policy)


def test_read_only_model_views_expose_the_policy():
    slots = Scope(Item, keys=["a"], initially_present=False, id="slots")
    spec = Spec(id="s", name="S", scopes=[slots])
    assert spec_overview(spec)["scopes"][0]["initially_present"] is False
    assert describe(spec, "entity", "Item")["scopes"][0]["initially_present"] is False


def test_presence_policy_and_keys_have_exact_tlc_roots():
    from analint.backends.tla import Target, export_tla
    from analint.backends.tlc import TlcUnavailable, find_tlc, run_tlc

    slots = Scope(Item, keys=[1, 2], initially_present=False)
    p = Param("p", slots)
    create = Action(id="create", params=[p], effect=[Create(p, value=Key(p))])
    x = Bound("x", slots)
    safe = Invariant(
        And(ForAll(x, x.value == Key(x)), Sum(x, x.value) == Sum(x, Key(x))), id="safe"
    )
    spec = Spec(
        id="s", name="S", initial=Initial(given=[slots[1]()]), actions=[create], invariants=[safe]
    )
    roots, error = build_canonical_initials(spec)
    assert error is None
    exp = explore(spec, roots, 100)
    assert len(exp.states) == 2
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    outcome = run_tlc(export_tla(spec, roots, target=Target("always", safe.expression)))
    assert outcome.status == "ok", outcome.output
    assert outcome.distinct_states == len(exp.states)

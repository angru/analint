"""Quantified invariant applicability follows presence, not the whole universe."""

import pytest

from analint import (
    Absent,
    Action,
    Bound,
    Entity,
    Field,
    ForAll,
    Invariant,
    Min,
    Scope,
    Set,
    Spec,
    Sum,
)
from analint.validator.explorer import explore, verify_invariants
from analint.validator.slicing import SliceAnalysis
from analint.validator.state_checks import invariant_is_applicable


@pytest.fixture
def slots():
    class Item(Entity):
        value: int = Field(0, ge=0, le=1)

    scope = Scope(Item, keys=["a", "b"])
    return Item, scope, Bound("item", scope)


@pytest.mark.parametrize("sliced", [False, True])
@pytest.mark.parametrize("aggregate", [False, True])
def test_absent_member_does_not_hide_violation(slots, sliced, aggregate):
    entity, scope, bound = slots
    a, b = scope["a"], scope["b"]
    expression = Sum(bound, bound.value) == 0 if aggregate else ForAll(bound, bound.value == 0)
    invariant = Invariant(expression, id="zero")
    action = Action(id="break_zero", effect=[Set(a.value, 1)])
    spec = Spec(
        id="s",
        name="S",
        entities=[entity],
        scopes=[scope],
        invariants=[invariant],
        actions=[action],
    )
    initials = [{a: a(), b: Absent(b)}]
    (result,), _ = verify_invariants(
        spec, initials, analysis=SliceAnalysis(spec) if sliced else None
    )
    assert result.status == "FAIL"
    assert result.trace == ["break_zero"]
    assert any("invariant" in f.message for f in explore(spec, initials, 10).findings)


def test_applicability_cache_tracks_presence_changes(slots):
    _, scope, bound = slots
    a, b = scope["a"], scope["b"]
    invariant = Invariant(ForAll(bound, bound.value == 0), id="zero")
    assert invariant_is_applicable(invariant, {a: Absent(a), b: Absent(b)})
    assert invariant_is_applicable(invariant, {a: a(), b: Absent(b)})
    assert invariant_is_applicable(invariant, {a: a(), b: b(value=1)})
    direct = Invariant(a.value == 0, id="direct")
    assert not invariant_is_applicable(direct, {a: Absent(a), b: b()})


def test_empty_minimum_is_an_evaluation_error_not_unchecked(slots):
    entity, scope, bound = slots
    invariant = Invariant(Min(bound, bound.value) >= 0, id="minimum")
    spec = Spec(id="s", name="S", entities=[entity], scopes=[scope], invariants=[invariant])
    initials = [{ref: Absent(ref) for ref in scope}]
    (result,), _ = verify_invariants(spec, initials)
    assert result.status == "FAIL"
    assert "evaluation error" in result.findings[0].message

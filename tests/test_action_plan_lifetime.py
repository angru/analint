"""Execution plans belong to a run, not a mutable declaration."""

import pytest

from analint import Absent, Action, Create, Entity, Field, Scope, Set, Spec
from analint.validator.explorer import explore
from analint.validator.kernel import Outcome, step


class Counter(Entity):
    n: int = Field(0, ge=0, le=3)


@pytest.mark.parametrize("edit", ["append", "replace", "nested", "copy"])
def test_changed_guards_are_observed_by_next_run(edit):
    action = Action(id="tick", pre=[Counter.n < 3], effect=[Set(Counter.n, Counter.n + 1)])
    spec = Spec(id="s", name="S", actions=[action])
    context = {Counter: Counter()}
    assert step(spec, action, context).outcome is Outcome.ACCEPTED
    assert len(explore(spec, [context], 10).states) == 4
    if edit == "append":
        action.pre.append(Counter.n < 0)
    elif edit == "replace":
        action.pre = [Counter.n < 0]
    elif edit == "nested":
        action.pre[0].right = 0
    else:
        action = action.model_copy(update={"pre": [Counter.n < 0]})
        spec.actions = [action]
    assert step(spec, action, context).outcome is Outcome.REJECTED
    assert len(explore(spec, [context], 10).states) == 1


def test_replaced_effect_rebuilds_presence_guards():
    slots = Scope(Counter, keys=["a"])
    ref = slots["a"]
    action = Action(id="edit", effect=[Create(ref)])
    spec = Spec(id="s", name="S", actions=[action])
    context = {ref: Absent(ref)}
    assert step(spec, action, context).outcome is Outcome.ACCEPTED
    action.effect = [Set(ref.n, 1)]
    assert step(spec, action, context).outcome is Outcome.REJECTED
    action.effect = [Create(ref)]
    assert step(spec, action, context).outcome is Outcome.ACCEPTED


def test_exploration_compiles_once_per_action(monkeypatch):
    from analint.validator import kernel

    action = Action(id="tick", pre=[Counter.n < 3], effect=[Set(Counter.n, Counter.n + 1)])
    spec = Spec(id="s", name="S", actions=[action])
    calls = []
    original = kernel.compile_predicate

    def compile_counted(predicate):
        calls.append(predicate)
        return original(predicate)

    monkeypatch.setattr(kernel, "compile_predicate", compile_counted)
    assert len(explore(spec, [{Counter: Counter()}], 10).states) == 4
    assert len(calls) == 1

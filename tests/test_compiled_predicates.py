"""Compiled predicates must agree with the interpreter (rule_checker.evaluate)
on every example's guards, posts, invariants and query predicates: the same
value, or the same exception type and message."""

from pathlib import Path

import pytest

from analint.models.scope import instance_context_key
from analint.validator.engine import build_spec
from analint.validator.explorer import build_canonical_initials, explore
from analint.validator.rule_checker import compile_predicate, evaluate

ROOT = Path(__file__).parent.parent
SPECS = sorted(p.parent.name for p in (ROOT / "examples").glob("*/spec.py"))


def _outcome(fn):
    try:
        return ("value", fn())
    except Exception as exc:  # the comparison is the point
        return (type(exc), str(exc))


def _predicates(spec):
    for action in spec.actions:
        yield from action.pre
        yield from action.post
    for inv in spec.invariants:
        yield inv.expression
    for query in spec.queries:
        for name in ("predicate", "goal"):
            if getattr(query, name, None) is not None:
                yield getattr(query, name)


@pytest.mark.parametrize("path", [f"examples/{n}" for n in SPECS] + ["benchmarks/broker/m4.py"])
def test_compiled_matches_interpreter(path):
    spec, _, errors = build_spec(ROOT / path)
    assert spec is not None and not errors
    initials, _ = build_canonical_initials(spec)
    states = list(explore(spec, initials, 300).states.values()) if initials else []
    for scenario in spec.scenarios:  # partial givens exercise missing-entity errors
        states.append({instance_context_key(e): e for e in scenario.given})
    predicates = list(_predicates(spec))
    assert predicates
    compared = 0
    for pred in predicates:
        compiled = compile_predicate(pred)
        for ctx in states:
            got = _outcome(lambda c=ctx, f=compiled: f(c))
            assert got == _outcome(lambda c=ctx, p=pred: evaluate(p, c))
            compared += 1
    assert compared


def test_quantifier_evaluates_every_member_like_the_interpreter():
    """evaluate() builds the member list in full, so a later member's error is
    raised even when an earlier member already decides ForAll/Exists."""
    from analint import And, Bound, Entity, Exists, ForAll, Or, Scope

    class Item(Entity):
        value: int = 0

    class Missing(Entity):
        v: int = 0

    items = Scope(Item, keys=["a", "b"])
    x = Bound("x", items)
    ctx = {items["a"]: items["a"](value=1), items["b"]: items["b"](value=0)}
    # member a decides the result; member b reads an entity missing from ctx
    for pred in (
        ForAll(x, And(x.value == 0, Missing.v > 0)),
        Exists(x, Or(x.value == 1, Missing.v > 0)),
    ):
        expected = _outcome(lambda p=pred: evaluate(p, ctx))
        assert expected[0] is KeyError
        compiled = compile_predicate(pred)
        assert _outcome(lambda f=compiled: f(ctx)) == expected

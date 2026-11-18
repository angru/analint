"""Bounded, reproducible differential probes, independent of example snapshots.

24 seeded singleton models and eight scoped models, at most 32 states each; no fuzzing service or timing threshold.
Vary dependency placement and predicate trees, with known PASS/FAIL controls.
"""

from enum import StrEnum
from random import Random

import pytest

from analint import (
    Absent,
    Action,
    Add,
    AlwaysHolds,
    And,
    Bound,
    Count,
    Create,
    Delete,
    Entity,
    Event,
    Exists,
    Field,
    ForAll,
    Implies,
    In,
    Invariant,
    IsNotNull,
    IsNull,
    Key,
    Max,
    Min,
    Not,
    Or,
    Present,
    Reachable,
    Scope,
    Set,
    Spec,
    Sum,
    Unreachable,
)
from analint.reporter.base import Code, Severity
from analint.reporter.json_reporter import result_to_dict
from analint.validator import explorer
from analint.validator.engine import validate_spec
from analint.validator.explorer import build_canonical_initials, explore
from analint.validator.rule_checker import compile_predicate, evaluate
from analint.validator.slicing import SliceAnalysis


class Colour(StrEnum):
    RED = "red"
    BLUE = "blue"


def _model(seed):
    rng = Random(seed)
    limit = rng.randint(1, 3)
    defect = seed % 3  # valid, invariant defect, constrained payload defect
    placement = seed % 4  # effect RHS, precondition, postcondition, emitted value

    class Counter(Entity):
        n: int = Field(0, ge=0, le=limit)
        copied: int = Field(0, ge=0, le=limit)

    class Noise(Entity):
        flag: bool = False

    class Payload(Event):
        n: int = Field(0, ge=0, le=limit)

    increment = Action(id="increment", pre=[Counter.n < limit], effect=[Add(Counter.n, 1)])
    copy = Action(
        id="copy",
        pre=[Counter.n == limit] if placement == 1 else [],
        effect=[Set(Counter.copied, Counter.n if placement == 0 else limit)],
        post=[Counter.n >= 0] if placement == 2 else [],
        emits=[Payload(n=Counter.n)] if placement == 3 else [],
    )
    noise = Action(id="noise", effect=[Set(Noise.flag, True)])
    emit = Action(id="emit", pre=[Counter.n == limit], emits=[Payload(n=Counter.n + (defect == 2))])
    actions = [increment, copy, noise, emit]
    rng.shuffle(actions)
    safe = Counter.n < limit if defect == 1 else Counter.n <= limit
    spec = Spec(
        id=f"seed_{seed}",
        name="Seeded conformance",
        actions=actions,
        invariants=[Invariant(safe, id="bound")],
        queries=[
            Reachable(Counter.copied == limit, id="copied"),
            AlwaysHolds(Counter.copied <= limit, id="bounded"),
            Unreachable(Counter.n > limit, id="overflow"),
        ],
    )
    return spec, defect, rng


def _semantic_shape(result):
    # Slicing intentionally removes unrelated states and stutters. Compare
    # verdicts, shortest witness lengths, and diagnostic identities, not counts.
    return (
        result.verdict,
        [
            (r.invariant_id, r.status, None if r.trace is None else len(r.trace))
            for r in result.invariant_results
        ],
        [
            (r.query_id, r.status, None if r.trace is None else len(r.trace))
            for r in result.query_results
        ],
        {(f.code, f.severity, f.location) for f in result.exploration_findings},
    )


def _without_timing(value):
    if isinstance(value, dict):
        return {k: _without_timing(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [_without_timing(v) for v in value]
    return value


def _outcome(fn):
    try:
        return ("value", fn())
    except Exception as exc:
        return (type(exc), str(exc))


def _tree(rng, leaves, depth):
    if depth == 0:
        return rng.choice(leaves)
    children = [_tree(rng, leaves, depth - 1) for _ in range(2)]
    return rng.choice([And, Or, Implies, lambda a, b: Not(And(a, b))])(*children)


@pytest.mark.parametrize("seed", range(24))
def test_generated_models_agree_across_native_paths(seed, tmp_path, monkeypatch):
    spec, defect, rng = _model(seed)
    whole = validate_spec(spec, sliced=False)
    sliced = validate_spec(spec)
    assert not [f for f in sliced.structural_findings if f.severity is Severity.ERROR]
    assert whole.verdict == sliced.verdict == ("PASS" if defect == 0 else "FAIL")
    assert _semantic_shape(sliced) == _semantic_shape(whole)
    if defect == 2:
        assert any(
            f.code is Code.FIELD_CONSTRAINT and "emitted Payload.n" in f.message
            for f in sliced.exploration_findings
        )

    # Prove that the comparison actually exercises a smaller slice.
    analysis = SliceAnalysis(spec)
    selected = analysis.predicate_slice(spec.queries[0].predicate, canonical=True)
    assert len(selected.actions) < len(spec.actions)
    roots, error = build_canonical_initials(spec)
    assert roots is not None, error
    graph = explore(spec, roots, 100)
    assert not graph.capped and len(graph.states) <= 32
    predicates = [p for a in spec.actions for p in [*a.pre, *a.post]]
    predicates += [i.expression for i in spec.invariants] + [q.predicate for q in spec.queries]
    predicates += [_tree(rng, predicates, 2) for _ in range(8)]
    # Partial context deliberately exercises exception equivalence too.
    for predicate in predicates:
        compiled = compile_predicate(predicate)
        for context in [*graph.states.values(), {}]:
            assert _outcome(lambda p=predicate, c=context: evaluate(p, c)) == _outcome(
                lambda f=compiled, c=context: f(c)
            )

    # Full JSON equality within each mode, including traces and defect messages.
    # A warm run must really hit the disk cache, not silently explore again.
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    for mode, expected in [(False, whole), (True, sliced)]:
        expected_json = _without_timing(result_to_dict(expected))
        assert (
            _without_timing(result_to_dict(validate_spec(spec, sliced=mode, cache=True)))
            == expected_json
        )
        with monkeypatch.context() as patch:

            def unexpected_exploration(*args, **kwargs):
                pytest.fail("warm cache missed")

            patch.setattr(explorer, "_explore", unexpected_exploration)
            assert (
                _without_timing(result_to_dict(validate_spec(spec, sliced=mode, cache=True)))
                == expected_json
            )


@pytest.mark.parametrize("seed", range(8))
def test_generated_scoped_trees_preserve_values_and_errors(seed):
    rng = Random(100 + seed)

    class Item(Entity):
        n: int = 0
        colour: Colour = Colour.RED
        optional: str | None = None

    items = Scope(Item, keys=["a", "b"])
    a, b = items["a"], items["b"]
    x = Bound("x", items)
    leaves = [
        Present(a),
        ForAll(x, x.n >= rng.randint(0, 2)),
        Exists(x, x.n == 1),
        Count(x, x.n > 0) == 1,
        Sum(x, x.n) > 0,
        Min(x, x.n) >= 0,
        Max(x, x.n) < 3,
        ForAll(x, In(Key(x), ["a", "b"])),
        IsNull(a.optional),
        IsNotNull(b.optional),
        In(a.colour, [Colour.RED]),
        a.n + b.n * 2 - 1 >= 0,
    ]
    contexts = [
        {a: a(n=rng.randint(0, 2)), b: b(n=rng.randint(0, 2), colour=Colour.BLUE, optional="x")},
        {a: a(), b: Absent(b)},
        {a: Absent(a), b: Absent(b)},
        {},
    ]
    predicates = leaves + [_tree(rng, leaves, 3) for _ in range(12)]
    seen_error = False
    for predicate in predicates:
        compiled = compile_predicate(predicate)
        for context in contexts:
            expected = _outcome(lambda p=predicate, c=context: evaluate(p, c))
            assert _outcome(lambda f=compiled, c=context: f(c)) == expected
            seen_error |= expected[0] != "value"
    assert seen_error

    # Presence-changing effects and membership-dependent aggregate properties.
    spec = Spec(
        id=f"scope_{seed}",
        name="Scoped conformance",
        scopes=[items],
        actions=[
            Action(id="create", effect=[Create(a, n=rng.randint(0, 2))]),
            Action(id="delete", effect=[Delete(a)]),
        ],
        queries=[
            AlwaysHolds(Sum(x, x.n) >= 0, id="nonnegative"),
            Reachable(Count(x, Present(x)) == 1, id="one"),
        ],
    )
    assert _semantic_shape(validate_spec(spec)) == _semantic_shape(
        validate_spec(spec, sliced=False)
    )

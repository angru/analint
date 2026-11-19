"""Predicate values preserve dependencies, binding and simultaneous effects."""

from enum import Enum
from itertools import permutations, product

import pytest

from analint import (
    Action,
    Add,
    AlwaysHolds,
    And,
    BoolValue,
    Bound,
    Create,
    Entity,
    Event,
    Exists,
    Field,
    ForAll,
    Not,
    Or,
    Param,
    Present,
    Reachable,
    Scope,
    Set,
    Spec,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.backends.tlc import TlcUnavailable, find_tlc, run_tlc
from analint.models.param import _resolve
from analint.models.predicate import Predicate
from analint.reporter.base import Severity
from analint.validator.engine import validate_spec
from analint.validator.exploration_cache import digest, use_store
from analint.validator.explorer import build_canonical_initials, explore
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import compile_predicate, evaluate, resolve
from analint.validator.structural import validate_structural


class Method(Enum):
    CARD = "card"
    WALLET = "wallet"


class Client(Entity):
    card_deposited: bool = False
    ready: bool = False


def _family():
    method = Param("method", Method)
    return Action(
        id="deposit",
        params=[method],
        effect=[
            Set(Client.card_deposited, BoolValue(Or(Client.card_deposited, method == Method.CARD)))
        ],
    )


@pytest.mark.parametrize("initial,method", list(product([False, True], Method)))
def test_parameterized_family_matches_split_actions(initial, method):
    spec = Spec(id="s", name="S", actions=[_family()])
    action = spec.actions[list(Method).index(method)]
    split = Action(
        id="split",
        effect=[
            Set(
                Client.card_deposited,
                True if method is Method.CARD else Client.card_deposited,
            )
        ],
    )
    context = {Client: Client(card_deposited=initial)}
    result = step(spec, action, context)
    reference = step(spec, split, context)
    assert result.outcome is reference.outcome is Outcome.ACCEPTED
    assert result.post_context[Client].card_deposited is (initial or method is Method.CARD)
    assert (
        result.post_context[Client].card_deposited is reference.post_context[Client].card_deposited
    )
    assert context[Client].card_deposited is initial


def test_simultaneous_effects_and_post_state_payload():
    class Recorded(Event):
        ready: bool

    effects = [Set(Client.card_deposited, BoolValue(Client.ready)), Set(Client.ready, True)]
    for order in permutations(effects):
        action = Action(
            id="copy", effect=list(order), emits=[Recorded(ready=BoolValue(Client.ready))]
        )
        spec = Spec(id="s", name="S", actions=[action])
        result = step(spec, action, {Client: Client()})
        assert result.outcome is Outcome.ACCEPTED
        assert result.post_context[Client].card_deposited is False
        assert result.post_context[Client].ready is True
        assert result.emitted[0].ready is True


def test_scoped_params_quantifiers_and_presence():
    clients = Scope(Client, keys=["a", "b"], id="clients")
    a, b = clients["a"], clients["b"]
    p, x = Param("client", clients), Bound("x", clients)
    action = Action(id="copy", params=[p], effect=[Set(p.ready, BoolValue(p.card_deposited))])
    spec = Spec(id="s", name="S", actions=[action])
    context = {a: a(card_deposited=True)}
    assert clients in spec.scopes
    assert step(spec, spec.actions[0], context).post_context[a].ready is True
    assert step(spec, spec.actions[1], context).outcome is Outcome.REJECTED
    predicate = ForAll(x, BoolValue(x.card_deposited) == True)  # noqa: E712
    assert evaluate(predicate, context) and compile_predicate(predicate)(context)
    value = BoolValue(Exists(x, x.card_deposited))
    assert resolve(value, context) is True
    assert resolve(value, {}) is False
    guarded = BoolValue(And(Present(b), b.ready))
    assert resolve(guarded, context) is False
    assert compile_predicate(guarded == False)(context)  # noqa: E712
    create = Action(id="create", effect=[Create(b, ready=value)])
    created = step(spec, create, context)
    assert created.outcome is Outcome.ACCEPTED
    assert created.post_context[b].ready is True
    # No implicit presence guard may hide a malformed effect read.
    bad = Action(id="bad", effect=[Set(a.ready, BoolValue(b.ready))])
    assert step(spec, bad, context).outcome is Outcome.DEFECT
    assert resolve(_resolve(BoolValue(Present(p)), {"client": a}), context) is True


def test_constructor_and_unknown_predicates_fail_closed():
    for value in (True, 1, "true", lambda: True):
        with pytest.raises(TypeError, match="DSL predicate"):
            BoolValue(value)
    with pytest.raises(TypeError, match="no Python truth value"):
        bool(BoolValue(Client.ready))

    class Foreign(Predicate):
        pass

    action = Action(id="unknown", effect=[Set(Client.ready, BoolValue(Foreign()))])
    spec = Spec(id="s", name="S", actions=[action])
    assert any(f.severity is Severity.ERROR for f in validate_structural(spec))
    assert step(spec, action, {Client: Client()}).outcome is Outcome.DEFECT
    raw = Action(id="raw", effect=[Set(Client.ready, Or(Client.ready))])
    assert validate_spec(Spec(id="raw", name="Raw", actions=[raw])).verdict == "FAIL"


def test_compiler_preserves_evaluation_errors_and_short_circuiting():
    class N(Entity):
        zero: int = 0

    bad = N.zero // N.zero == 0
    for predicate, error in [
        (And(Or(), bad), None),
        (Or(And(), bad), None),
        (bad, ZeroDivisionError),
    ]:
        wrapped = BoolValue(predicate) == True  # noqa: E712
        results = []
        for run in (
            lambda wrapped=wrapped: evaluate(wrapped, {N: N()}),
            lambda wrapped=wrapped: compile_predicate(wrapped)({N: N()}),
        ):
            if error:
                with pytest.raises(error) as caught:
                    run()
                results.append(str(caught.value))
            else:
                results.append(run())
        assert results[0] == results[1]


def _dependency_spec(defect=False):
    class Source(Entity):
        ready: bool = False

    set_source = Action(id="source", effect=[Set(Source.ready, True)])
    copy = Action(id="copy", effect=[Set(Client.ready, BoolValue(Source.ready))])
    query = (
        AlwaysHolds(Not(Client.ready), id="safe")
        if defect
        else Reachable(Client.ready, id="reached")
    )
    return Spec(id="s", name="S", actions=[copy, set_source], queries=[query]), Source


@pytest.mark.parametrize("defect", [False, True])
def test_slicing_cache_and_reference_closure_preserve_hidden_reads(tmp_path, monkeypatch, defect):
    spec, source = _dependency_spec(defect)
    assert source in spec.entities
    for sliced in (False, True):
        assert validate_spec(spec, sliced=sliced).verdict == ("FAIL" if defect else "PASS")
    roots, _ = build_canonical_initials(spec)
    before = digest(spec, roots, 100, None, frozenset())[0]
    with use_store(tmp_path):
        cold = explore(spec, roots, 100)
        with monkeypatch.context() as patch:

            def cache_miss(*args, **kwargs):
                pytest.fail("BoolValue exploration did not hit the warm cache")

            patch.setattr("analint.validator.explorer._explore", cache_miss)
            warm = explore(spec, roots, 100)
    assert set(cold.states) == set(warm.states)
    assert list(cold.edges) == list(warm.edges)
    assert len(cold.states) == 3
    spec.actions[0].effect[0].value.predicate = Not(source.ready)
    assert digest(spec, roots, 100, None, frozenset())[0] != before


def test_duplicate_targets_and_field_constraints_remain_errors():
    bad = Action(
        id="duplicate", effect=[Set(Client.ready, True), Set(Client.ready, BoolValue(Client.ready))]
    )
    assert validate_spec(Spec(id="s", name="S", actions=[bad])).verdict == "FAIL"

    class Restricted(Entity):
        flag: bool = Field(False, values=[False])

    action = Action(id="defect", effect=[Set(Restricted.flag, BoolValue(And()))])
    spec = Spec(id="s", name="S", actions=[action])
    assert step(spec, action, {Restricted: Restricted()}).outcome is Outcome.DEFECT


@pytest.mark.parametrize("scoped", [False, True])
def test_native_and_tlc_state_graphs_agree(scoped):
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    if scoped:
        clients = Scope(Client, keys=["a", "b"], id="clients", initially_present=False)
        a, b = clients["a"], clients["b"]
        x = Bound("x", clients)
        actions = [
            Action(id="a", effect=[Create(a, ready=True)]),
            Action(id="b", effect=[Create(b, ready=BoolValue(Exists(x, x.ready)))]),
        ]
        spec = Spec(id="s", name="S", actions=actions)
    else:
        spec, _ = _dependency_spec()
        spec.actions.extend(Spec(id="family", name="Family", actions=[_family()]).actions)
    roots, _ = build_canonical_initials(spec)
    native = explore(spec, roots, 100)
    exported = export_tla(spec, roots, target=Target("always", True))
    result = run_tlc(exported)
    assert result.status == "ok", result.output
    assert result.distinct_states == len(native.states)


def test_static_where_and_invalid_targets_are_not_weakened():
    clients = Scope(Client, keys=["a"], id="clients")
    p = Param("client", clients)
    action = Action(id="bad", params=[p], where=[BoolValue(Present(p)) == True])  # noqa: E712
    with pytest.raises(TypeError, match="cannot be used in where"):
        Spec(id="s", name="S", actions=[action])
    wrong_target = Action(id="bad", effect=[Set(BoolValue(Client.ready), True)])
    assert validate_spec(Spec(id="s", name="S", actions=[wrong_target])).verdict == "FAIL"


@pytest.mark.parametrize(
    "kind",
    [
        "arithmetic",
        "comparison",
        "membership",
        "copied",
        "mixed_roots",
        "constraints",
        "sum",
        "add",
    ],
)
def test_tlc_refuses_python_boolean_numeric_coercion(kind):
    from analint import In, Sum

    class Box(Entity):
        flag: bool = False
        n: int = Field(0, ge=0, le=2)

    value = BoolValue(And())
    actions = [Action(id="set", effect=[Set(Box.flag, value)])]
    target = True
    if kind == "arithmetic":
        actions.append(Action(id="n", effect=[Set(Box.n, value + 1)]))
    elif kind == "comparison":
        target = value == 1
    elif kind == "membership":
        target = In(value, [1])
    elif kind == "copied":
        actions.append(Action(id="n", effect=[Set(Box.n, Box.flag + 1)]))
    elif kind == "mixed_roots":
        actions[0].effect = [Set(Box.n, value)]
    elif kind == "constraints":

        class Constrained(Entity):
            flag: bool = Field(False, ge=0, le=1)

        actions[0].effect = [Set(Constrained.flag, value)]
    elif kind == "sum":
        scope = Scope(Client, keys=["a"], id="clients")
        x = Bound("x", scope)
        actions.append(Action(id="n", effect=[Set(Box.n, Sum(x, BoolValue(x.ready)))]))
    else:
        actions.append(Action(id="n", effect=[Add(Box.n, value)]))
    spec = Spec(id="s", name="S", actions=actions)
    roots, _ = build_canonical_initials(spec)
    with pytest.raises(ExportError, match="BoolValue"):
        export_tla(spec, roots, target=Target("always", target))


def test_tlc_fallback_preserves_positive_and_negative_verdicts():
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    for defect in (False, True):
        spec, _ = _dependency_spec(defect)
        result = validate_spec(spec, max_states=1, tlc=True)
        assert result.verdict == ("FAIL" if defect else "PASS")
        assert result.query_results[0].backend == "tlc"


def test_tlc_preserves_bool_value_transition_defects():
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))

    class Restricted(Entity):
        flag: bool = Field(False, values=[False])

    action = Action(id="defect", effect=[Set(Restricted.flag, BoolValue(Not(Restricted.flag)))])
    spec = Spec(id="s", name="S", actions=[action])
    roots, _ = build_canonical_initials(spec)
    result = run_tlc(export_tla(spec, roots, target=Target("always", True)))
    assert result.status == "violation", result.output
    assert result.violated.startswith("NoDefect_")

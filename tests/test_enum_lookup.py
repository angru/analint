"""Exhaustive tables preserve enum identity, references and transition semantics."""

from enum import Enum, IntEnum

import pytest

from analint import (
    Action,
    AlwaysHolds,
    Bound,
    Entity,
    Field,
    ForAll,
    Lookup,
    Param,
    Scope,
    Set,
    Spec,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.backends.tlc import TlcUnavailable, find_tlc
from analint.models.param import _resolve
from analint.validator.engine import validate_spec
from analint.validator.explorer import build_canonical_initials
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import compile_predicate, evaluate, resolve
from analint.validator.slicing import _operand_vars
from analint.validator.structural import _operand_refs


class Kind(Enum):
    STANDARD = "standard"
    PRO = "pro"


TABLE = {Kind.STANDARD: 60, Kind.PRO: 30}


class Account(Entity):
    kind: Kind = Kind.STANDARD
    balance: int = Field(0, ge=0, le=100)


def test_table_copies_input_and_keeps_selector_dependencies():
    mapping = dict(TABLE)
    lookup = Lookup(Account.kind, mapping)
    mapping[Kind.STANDARD] = 99
    assert resolve(lookup, {Account: Account()}) == 60
    assert len(_operand_refs(lookup)) == 1
    assert _operand_refs(lookup)[0] is Account.kind
    reads = set()
    _operand_vars(lookup, reads)
    assert reads == {(Account, "kind")}
    pred = 2 * lookup == 120
    assert evaluate(pred, {Account: Account()})
    assert compile_predicate(pred)({Account: Account()})


@pytest.mark.parametrize(
    "mapping,error",
    [
        ({}, TypeError),
        ({Kind.STANDARD: 60}, ValueError),
        ({"standard": 60}, TypeError),
        ({Kind.STANDARD: True, Kind.PRO: 30}, TypeError),
        ({Kind.STANDARD: 60.0, Kind.PRO: 30}, TypeError),
    ],
)
def test_invalid_tables_are_rejected(mapping, error):
    with pytest.raises(error):
        Lookup(Account.kind, mapping)


def test_params_where_and_bound_fields():
    kind = Param("kind", Kind)
    lookup = Lookup(kind, TABLE)
    assert resolve(_resolve(lookup, {"kind": Kind.PRO}), {}) == 30
    family = Action(
        id="family", params=[kind], where=[lookup == 30], effect=[Set(Account.balance, lookup)]
    )
    spec = Spec(id="s", name="S", actions=[family])
    assert len(spec.actions) == 1
    scope = Scope(Account, keys=["one"], id="accounts")
    bound = Bound("account", scope)
    predicate = ForAll(bound, Lookup(bound.kind, TABLE) >= 30)
    context = {scope["one"]: scope["one"](kind=Kind.PRO)}
    assert evaluate(predicate, context) and compile_predicate(predicate)(context)
    assert resolve(Lookup(scope["one"].kind, TABLE), context) == 30


def _spec():
    change = Action(
        id="change",
        effect=[Set(Account.kind, Kind.PRO), Set(Account.balance, Lookup(Account.kind, TABLE))],
    )
    query = AlwaysHolds(Lookup(Account.kind, TABLE) >= 30, id="threshold")
    return Spec(id="s", name="S", actions=[change], queries=[query])


def test_effects_use_pre_state_and_cache_preserves_results(tmp_path):
    from analint.validator.exploration_cache import digest, use_store
    from analint.validator.explorer import explore

    spec = _spec()
    result = step(spec, spec.actions[0], {Account: Account()})
    assert result.outcome is Outcome.ACCEPTED
    assert result.post_context[Account].balance == 60
    assert result.post_context[Account].kind is Kind.PRO
    roots, _ = build_canonical_initials(spec)
    first = digest(spec, roots, 100, None, frozenset())[0]
    for sliced in (False, True):
        assert validate_spec(spec, sliced=sliced).verdict == "PASS"
    with use_store(tmp_path):
        cold = explore(spec, roots, 100)
        warm = explore(spec, roots, 100)
    assert set(cold.states) == set(warm.states)
    assert list(cold.edges) == list(warm.edges)
    spec.actions[0].effect[1] = Set(
        Account.balance, Lookup(Account.kind, {Kind.STANDARD: 59, Kind.PRO: 30})
    )
    assert digest(spec, roots, 100, None, frozenset())[0] != first


def test_tlc_matches_lookup_transitions():
    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    spec = _spec()
    result = validate_spec(spec, max_states=1, tlc=True)
    assert result.verdict == "PASS"
    assert result.query_results[0].backend == "tlc"


def test_scalar_enum_equality_and_out_of_domain_selector():
    class Number(IntEnum):
        ONE = 1

    class Box(Entity):
        kind: Number = Number.ONE

    query = AlwaysHolds(Lookup(Box.kind, {Number.ONE: 1}) == 1, id="safe")
    action = Action(id="break", effect=[Set(Box.kind, 1)])
    spec = Spec(id="s", name="S", actions=[action], queries=[query])
    pred = Lookup(1, {Number.ONE: 1}) == 1
    for run in (lambda: evaluate(pred, {}), lambda: compile_predicate(pred)({})):
        assert run() is True
    roots, _ = build_canonical_initials(spec)
    with pytest.raises(ExportError, match="literal enum writes"):
        export_tla(spec, roots, target=Target("always", query.predicate))
    # Equal scalar enum/int states must have identical lookup semantics.
    assert validate_spec(spec).verdict == "PASS"
    from analint import Initial

    spec.initial = Initial(given=[Box(kind=2)])
    assert validate_spec(spec).verdict == "FAIL"

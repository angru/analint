"""Executable AST inventory: add a case here whenever the language grows.

Reference walkers run on structurally valid trees. Runtime leaves must be bound;
parameter substitution and quantifier binding have separate authoring probes.
TLA rendering is a coverage check; the independent TLC suite checks semantics.
"""

import json
from dataclasses import dataclass

import pytest

from analint import (
    Action,
    Add,
    And,
    Bound,
    Count,
    Create,
    Delete,
    Entity,
    Exists,
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
    Param,
    Present,
    Scope,
    Set,
    Spec,
    Subtract,
    Sum,
    query,
)
from analint.backends.tla import ExportError, Target, _Model, _Renderer, export_tla
from analint.models.effect import Effect
from analint.models.expr import Expr, _BinaryExpr
from analint.models.param import _resolve, _subst_pred
from analint.models.predicate import Predicate, _BinaryComparison, _Eq
from analint.models.quantifier import BoundField, bind_operand, bind_predicate
from analint.models.scope import field_context_key
from analint.models.symbolic import Symbolic
from analint.reporter.base import Code, Severity
from analint.validator.engine import validate_spec
from analint.validator.exploration_cache import _canon, _Uncacheable
from analint.validator.rule_checker import compile_predicate, evaluate, resolve
from analint.validator.slicing import (
    PRESENT,
    SliceAnalysis,
    _action_vars,
    _action_writes,
    _operand_vars,
    _pred_vars,
    _Unsliceable,
)
from analint.validator.structural import (
    _check_pred_nodes,
    _collect_field_refs,
    _operand_refs,
    validate_structural,
)


class Counter(Entity):
    n: int = 1


class Item(Entity):
    n: int = 2


items = Scope(Item, keys=["a", "b"], id="items")
a, b = items["a"], items["b"]
x = Bound("x", items)
F = {(Counter, "n")}
S = {(a, "n"), (b, "n")}
P = {(a, PRESENT), (b, PRESENT)}
CTX = {Counter: Counter(), a: a(n=2), b: b(n=3)}
SPEC = Spec(id="inventory", name="Inventory", entities=[Counter], scopes=[items])

# (node, interpreted value, field references, slice reads, TLA spelling or refusal)
CASES = [
    (Counter.n == 1, True, F, F, "="),
    (Counter.n != 1, False, F, F, "#"),
    (Counter.n > 1, False, F, F, ">"),
    (Counter.n >= 1, True, F, F, ">="),
    (Counter.n < 1, False, F, F, "<"),
    (Counter.n <= 1, True, F, F, "<="),
    (And(Counter.n == 1, Counter.n < 2), True, F, F, "/\\"),
    (Or(Counter.n == 0, Counter.n == 1), True, F, F, "\\/"),
    (Not(Counter.n == 1), False, F, F, "~"),
    (Implies(Counter.n == 1, Counter.n == 0), False, F, F, "=>"),
    (In(0, [Counter.n, 0]), True, F, F, "\\in"),
    (IsNull(Counter.n), False, F, F, '"__null__"'),
    (IsNotNull(Counter.n), True, F, F, '"__null__"'),
    (ForAll(x, x.n > 2), False, S, S | P, "=>"),
    (Exists(x, x.n > 2), True, S, S | P, "\\/"),
    (Present(a), True, set(), {(a, PRESENT)}, "present__"),
    (Counter.n + 2, 3, F, F, "+"),
    (Counter.n - 2, -1, F, F, "-"),
    (Counter.n * 2, 2, F, F, "*"),
    (Count(x, x.n > 2), 1, S, S | P, "THEN 1 ELSE 0"),
    (Sum(x, x.n), 5, S, S | P, "ELSE 0"),
    (Min(x, x.n), 2, S, S | P, None),
    (Max(x, x.n), 3, S, S | P, None),
    (Key(a), "a", set(), set(), '"a"'),
    (Counter.n, 1, F, F, "f_n"),
    (a.n, 2, {(a, "n")}, {(a, "n"), (a, PRESENT)}, "f_n"),
]
EFFECTS = [
    (Set(a.n, Counter.n), {(a, "n")}, F | {(a, PRESENT)}),
    (Add(a.n, Counter.n), {(a, "n")}, F | {(a, "n"), (a, PRESENT)}),
    (Subtract(a.n, Counter.n), {(a, "n")}, F | {(a, "n"), (a, PRESENT)}),
    (Create(a, n=Counter.n), {(a, "n"), (a, PRESENT)}, F | {(a, PRESENT)}),
    (Delete(a), {(a, "n"), (a, PRESENT)}, {(a, PRESENT)}),
]


def _descendants(base):
    result = set()
    for child in base.__subclasses__():
        # Other tests intentionally define foreign AST classes. They are not DSL nodes.
        if child.__module__.startswith("analint.models."):
            result.add(child)
        result.update(_descendants(child))
    return result


def test_every_concrete_symbolic_and_effect_node_has_a_case():
    abstract = {Predicate, Expr, _BinaryComparison, _BinaryExpr}
    authoring = {type(x.n), type(Param("p", 1)), type(Param("p", Counter).n)}
    assert _descendants(Symbolic) - abstract == {type(c[0]) for c in CASES} | authoring
    assert _descendants(Effect) == {type(c[0]) for c in EFFECTS}


def _refs(refs):
    return {(field_context_key(ref), ref.field_name) for ref in refs}


@pytest.mark.parametrize(
    "node,value,fields,reads,tla", CASES, ids=[type(c[0]).__name__ for c in CASES]
)
def test_node_across_walkers(node, value, fields, reads, tla):
    predicate = node if isinstance(node, Predicate) else _Eq(node, value)
    assert not _check_pred_nodes(predicate, "inventory")
    assert _refs(_collect_field_refs(predicate)) == fields
    if not isinstance(node, Predicate):
        assert _refs(_operand_refs(node)) == fields
        assert resolve(node, CTX) == value
        extracted = set()
        _operand_vars(node, extracted)
        assert extracted == reads
    else:
        assert evaluate(node, CTX) is value
    assert evaluate(predicate, CTX) == compile_predicate(predicate)(CTX)
    extracted = set()
    _pred_vars(predicate, extracted)
    assert extracted == reads
    assert query._predicate_reads(predicate) == reads
    # Cache encoding must be JSON data, deterministic and sensitive to the tree.
    encoded = json.dumps(_canon(node, {}), sort_keys=True)
    assert encoded == json.dumps(_canon(node, {}), sort_keys=True)
    assert _canon(predicate, {}) != _canon(Not(predicate), {})
    model = _Model(SPEC, [CTX])
    renderer = _Renderer(model, model.var, set())
    render = renderer.pred if isinstance(node, Predicate) else renderer.operand
    if tla is None:
        with pytest.raises(ExportError, match="Min/Max"):
            render(node)
    else:
        output = render(node)
        assert tla in output
        for key, name in fields:
            assert f"{model.var[key]}.f_{name}" in output


@pytest.mark.parametrize("effect,writes,reads", EFFECTS, ids=[type(c[0]).__name__ for c in EFFECTS])
def test_effect_across_walkers(effect, writes, reads):
    action = Action(id="change", effect=[effect])
    spec = Spec(id="effects", name="Effects", entities=[Counter], scopes=[items], actions=[action])
    assert not [f for f in validate_structural(spec) if f.severity is Severity.ERROR]
    assert _action_writes(action) == writes
    variables, locks = _action_vars(action, {})
    assert variables == writes | reads
    assert not locks
    assert query._action_reads(spec, action) == reads
    # Delete changes presence, not a value assignment in the impact report.
    field_writes = set() if isinstance(effect, Delete) else writes - {(a, PRESENT)}
    assert _refs([ref for ref, _ in query._action_writes(action)]) == field_writes
    assert json.dumps(_canon(effect, {}))
    exported = export_tla(spec, [CTX], target=Target("always", True))
    assert exported.actions and "NoDefect_" in exported.config


@pytest.mark.parametrize(
    "leaf,value",
    [(Counter.n, 1), (a.n, 2), (Key(a), "a"), (1, 1), (True, True), (None, None), ("a", "a")],
)
def test_literal_and_reference_leaves(leaf, value):
    assert resolve(leaf, CTX) == value
    assert evaluate(_Eq(leaf, value), CTX) is True
    assert compile_predicate(_Eq(leaf, value))(CTX) is True


def test_authoring_leaves_are_bound_before_runtime_walkers():
    p = Param("p", items)
    for template, expected in [(p.n, 2), (Key(p), "a"), (p, a)]:
        bound = _resolve(template, {"p": a})
        assert resolve(bound, CTX) == expected
        with pytest.raises(_Uncacheable):
            _canon(template, {})
    assert evaluate(_subst_pred(Present(p), {"p": a}), CTX) is True
    assert resolve(bind_operand(x.n, x, a), CTX) == 2
    assert resolve(bind_operand(Key(x), x, a), CTX) == "a"
    assert evaluate(bind_predicate(Present(x), x, a), CTX) is True
    assert _canon(x, {}) and _canon(x.n, {}) and _canon(items, {})
    for unbound in [x.n, Key(x)]:
        assert any(f.code is Code.UNBOUND_VARIABLE for f in _check_pred_nodes(_Eq(unbound, 1), "x"))
        with pytest.raises(KeyError, match="binding"):
            resolve(unbound, CTX)
        with pytest.raises(_Unsliceable):
            _operand_vars(unbound, set())
    assert isinstance(x.n, BoundField)


@dataclass
class ForeignPredicate(Predicate):
    child: object


@dataclass(eq=False)
class ForeignExpr(Expr):
    child: object


@dataclass
class ForeignEffect(Effect):
    child: object


@pytest.mark.parametrize("node", [ForeignPredicate(Counter.n), ForeignExpr(Counter.n)])
def test_unknown_nodes_fail_closed_instead_of_becoming_constants(node):
    predicate = node if isinstance(node, Predicate) else IsNotNull(node)
    spec = Spec(id="foreign", name="Foreign", invariants=[Invariant(predicate, id="bad")])
    assert any(f.code is Code.INVALID_ENTRY for f in validate_structural(spec))
    assert validate_spec(spec).verdict == "FAIL"
    for run in [lambda: evaluate(predicate, CTX), lambda: compile_predicate(predicate)(CTX)]:
        with pytest.raises(TypeError, match="unsupported"):
            run()
    analysis = SliceAnalysis(spec)
    assert analysis.predicate_slice(predicate, canonical=True) is analysis.whole
    with pytest.raises(_Uncacheable):
        _canon(node, {})
    with pytest.raises(_Unsliceable):
        query._predicate_reads(predicate)
    with pytest.raises(ExportError):
        export_tla(spec, [CTX], target=Target("always", predicate))


def test_unknown_effect_is_rejected_and_cannot_disappear_from_export():
    action = Action(id="foreign", effect=[ForeignEffect(Counter.n)])
    spec = Spec(id="foreign", name="Foreign", entities=[Counter], actions=[action])
    assert any(f.code is Code.INVALID_ENTRY for f in validate_structural(spec))
    assert not SliceAnalysis(spec).sliceable
    for walk in [lambda: query._action_reads(spec, action), lambda: query._action_writes(action)]:
        with pytest.raises(_Unsliceable):
            walk()
    with pytest.raises(_Uncacheable):
        _canon(action, {})
    with pytest.raises(ExportError, match="effect"):
        export_tla(spec, [CTX], target=Target("always", True))

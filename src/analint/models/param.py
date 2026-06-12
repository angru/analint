"""Parameterized actions: one declaration, many concrete instances.

A `Param` ranges over a finite domain — entity classes or plain values:

    src    = Param("src", AliceCoins, BobCoins, EveCoins)
    dst    = Param("dst", AliceCoins, BobCoins, EveCoins)
    amount = Param("amount", ge=1, le=3)

    send = Action(
        params=[src, dst, amount],
        where=[src != dst],
        pre=[src.coins >= amount, dst.coins <= MAX_BALANCE - amount],
        effect=[
            Set(src.coins, src.coins - amount),
            Set(dst.coins, dst.coins + amount),
        ],
    )

Expansion happens when the Spec is built: every binding that satisfies the
`where` clauses becomes an ordinary concrete Action (`send(src=AliceCoins,
dst=BobCoins, amount=1)`), so the scenario runner and the reachability engine
never see parameters. Scenarios pick a binding with `send.bind(src=…, …)` —
bindings are memoized, so the scenario's action is identical to the expanded
one. Everything stays declarative and serializable: a parameter is an AST
node, not a host-language loop (research/15 — the factory-function smell).
"""

from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING, Any

from analint.models.effect import Add, Effect, Set, Subtract
from analint.models.entity import FieldDescriptor
from analint.models.expr import Expr, _AddExpr, _MulExpr, _SubExpr
from analint.models.predicate import (
    Predicate,
    _And,
    _Eq,
    _Gt,
    _Gte,
    _Implies,
    _In,
    _IsNotNull,
    _IsNull,
    _Lt,
    _Lte,
    _Ne,
    _Not,
    _Or,
)
from analint.models.quantifier import _Count, _Exists, _ForAll, _Max, _Min, _Sum
from analint.models.scope import InstanceRef, Scope

if TYPE_CHECKING:
    from analint.models.action import Action

Binding = dict[str, Any]


class Param:
    """A named finite domain.

    Three ways to declare the domain, by intent:

        Param("src", Alice, Bob, Eve)   # explicit enumeration (classes/values)
        Param("amount", ge=1, le=3)     # integer range — same vocabulary as Field
        Param("room", Room)             # an Enum class → all its members
        Param("flag", bool)             # → False, True
    """

    def __init__(
        self, name: str, *domain: Any, ge: int | None = None, le: int | None = None
    ) -> None:
        if not name:
            raise TypeError("Param needs a name: Param('src', …)")
        if domain and (ge is not None or le is not None):
            raise TypeError(
                f"Param '{name}': use either an explicit domain or ge=/le= bounds, not both"
            )
        if ge is not None or le is not None:
            if ge is None or le is None:
                raise TypeError(f"Param '{name}': a range needs both ge= and le=")
            if not isinstance(ge, int) or not isinstance(le, int):
                raise TypeError(f"Param '{name}': ge=/le= bounds must be integers")
            if ge > le:
                raise TypeError(f"Param '{name}': ge={ge} is greater than le={le}")
            self.name = name
            self.domain: list[Any] = list(range(ge, le + 1))
            return

        from enum import Enum

        expanded: list[Any] = []
        for entry in domain:
            if isinstance(entry, Scope):
                expanded.extend(entry)
            elif entry is bool:
                expanded.extend([False, True])
            elif entry in (int, float, str):
                raise TypeError(
                    f"Param '{name}': bare {entry.__name__} is an infinite domain — "
                    f"use ge=/le= bounds or enumerate the values"
                )
            elif isinstance(entry, type) and issubclass(entry, Enum):
                expanded.extend(entry)
            else:
                expanded.append(entry)
        if not expanded:
            raise TypeError(f"Param '{name}' needs a non-empty domain")
        self.name = name
        self.domain = expanded

    # attribute access builds field references for entity-class params
    def __getattr__(self, item: str) -> ParamField:
        if item.startswith("_"):
            raise AttributeError(item)
        return ParamField(self, item)

    # comparisons (for where= clauses and value-domain predicates)
    def __eq__(self, other: Any) -> Predicate:  # type: ignore[override]
        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore[override]
        return _Ne(left=self, right=other)

    def __hash__(self) -> int:
        return id(self)

    # arithmetic builds shared expression nodes; param leaves are substituted
    # with concrete values at expansion time
    def __add__(self, other: Any) -> Expr:
        return _AddExpr(self, other)

    def __radd__(self, other: Any) -> Expr:
        return _AddExpr(other, self)

    def __sub__(self, other: Any) -> Expr:
        return _SubExpr(self, other)

    def __rsub__(self, other: Any) -> Expr:
        return _SubExpr(other, self)

    def __repr__(self) -> str:
        return f"Param({self.name})"


class ParamField:
    """`src.coins` — a field of a not-yet-bound entity parameter."""

    def __init__(self, param: Param, field_name: str) -> None:
        self.param = param
        self.field_name = field_name

    def __eq__(self, other: Any) -> Predicate:  # type: ignore[override]
        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore[override]
        return _Ne(left=self, right=other)

    def __gt__(self, other: Any) -> Predicate:
        return _Gt(left=self, right=other)

    def __ge__(self, other: Any) -> Predicate:
        return _Gte(left=self, right=other)

    def __lt__(self, other: Any) -> Predicate:
        return _Lt(left=self, right=other)

    def __le__(self, other: Any) -> Predicate:
        return _Lte(left=self, right=other)

    def __add__(self, other: Any) -> Expr:
        return _AddExpr(self, other)

    def __radd__(self, other: Any) -> Expr:
        return _AddExpr(other, self)

    def __sub__(self, other: Any) -> Expr:
        return _SubExpr(self, other)

    def __rsub__(self, other: Any) -> Expr:
        return _SubExpr(other, self)

    def __hash__(self) -> int:
        return hash((id(self.param), self.field_name))

    def __repr__(self) -> str:
        return f"{self.param.name}.{self.field_name}"


def _resolve(operand: Any, binding: Binding) -> Any:
    """Substitute a binding into an operand; non-param operands pass through."""
    if isinstance(operand, ParamField):
        bound = binding[operand.param.name]
        if isinstance(bound, InstanceRef):
            return getattr(bound, operand.field_name)
        if not isinstance(bound, type):
            raise TypeError(
                f"param '{operand.param.name}' is bound to {bound!r}, but "
                f"'{operand.param.name}.{operand.field_name}' needs an entity class "
                f"or InstanceRef"
            )
        descriptor = getattr(bound, operand.field_name, None)
        if not isinstance(descriptor, FieldDescriptor):
            raise TypeError(
                f"'{bound.__name__}' has no field '{operand.field_name}' "
                f"(required by param '{operand.param.name}')"
            )
        return descriptor
    if isinstance(operand, Param):
        return binding[operand.name]
    if isinstance(operand, _Count):
        return _Count(
            variable=operand.variable,
            predicate=_subst_pred(operand.predicate, binding),
        )
    if isinstance(operand, (_Sum, _Min, _Max)):
        return type(operand)(
            variable=operand.variable,
            operand=_resolve(operand.operand, binding),
        )
    if isinstance(operand, (_AddExpr, _SubExpr, _MulExpr)):
        # substitute param leaves; the expression itself is resolved against
        # the state at evaluation time (rule_checker.resolve)
        return type(operand)(_resolve(operand.left, binding), _resolve(operand.right, binding))
    return operand


def _subst_pred(pred: Predicate, binding: Binding) -> Predicate:
    if isinstance(pred, (_And, _Or)):
        return type(pred)(exprs=[_subst_pred(e, binding) for e in pred.exprs])
    if isinstance(pred, _Not):
        return _Not(expr=_subst_pred(pred.expr, binding))
    if isinstance(pred, _Implies):
        return _Implies(
            left=_subst_pred(pred.left, binding), right=_subst_pred(pred.right, binding)
        )
    if isinstance(pred, (_ForAll, _Exists)):
        return type(pred)(variable=pred.variable, predicate=_subst_pred(pred.predicate, binding))
    if isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        return type(pred)(left=_resolve(pred.left, binding), right=_resolve(pred.right, binding))
    if isinstance(pred, _In):
        return _In(
            operand=_resolve(pred.operand, binding),
            values=[_resolve(v, binding) for v in pred.values],
        )
    if isinstance(pred, (_IsNull, _IsNotNull)):
        return type(pred)(operand=_resolve(pred.operand, binding))
    return pred


def _subst_effect(effect: Effect, binding: Binding) -> Effect:
    if isinstance(effect, Set):
        return Set(field=_resolve(effect.field, binding), value=_resolve(effect.value, binding))
    if isinstance(effect, Subtract):
        return Subtract(
            field=_resolve(effect.field, binding), amount=_resolve(effect.amount, binding)
        )
    if isinstance(effect, Add):
        return Add(field=_resolve(effect.field, binding), amount=_resolve(effect.amount, binding))
    return effect


def _subst_emit(emitted: Any, binding: Binding) -> Any:
    if isinstance(emitted, type):
        return emitted
    cls = type(emitted)
    return cls(**{f: _resolve(v, binding) for f, v in emitted.__dict__.items()})


def _label(value: Any) -> str:
    if isinstance(value, InstanceRef):
        return repr(value)
    if isinstance(value, type):
        return value.__name__
    return repr(value)


def _binding_key(action: Action, binding: Binding) -> tuple:
    return (id(action), tuple((p.name, binding[p.name]) for p in action.params))


# bind() and expansion must hand out the same objects: a scenario's bound
# action has to be identical to the one registered by the expansion
_BIND_MEMO: dict[tuple, Action] = {}


def _where_holds(action: Action, binding: Binding) -> bool:
    from analint.validator.rule_checker import evaluate

    return all(evaluate(_subst_pred(w, binding), {}) for w in action.where)


def bind_action(action: Action, binding: Binding) -> Action:
    """One concrete instance of a parameterized action for an explicit binding."""
    from analint.models.action import Action

    declared = {p.name: p for p in action.params}
    if set(binding) != set(declared):
        raise TypeError(
            f"bind() for '{action.id or action.name}' needs exactly "
            f"{sorted(declared)}, got {sorted(binding)}"
        )
    for name, value in binding.items():
        if value not in declared[name].domain:
            raise ValueError(
                f"'{_label(value)}' is not in the domain of param '{name}' "
                f"of action '{action.id or action.name}'"
            )
    if not _where_holds(action, binding):
        raise ValueError(
            f"binding {{{', '.join(f'{p.name}={_label(binding[p.name])}' for p in action.params)}}} "
            f"violates a where= clause of '{action.id or action.name}'"
        )

    key = _binding_key(action, binding)
    suffix = ", ".join(f"{p.name}={_label(binding[p.name])}" for p in action.params)
    cached = _BIND_MEMO.get(key)
    if cached is not None:
        # bind() may run before the loader fills the base id from the variable
        # name — refresh the derived id once the base action got its name
        if not cached.id and action.id:
            cached.id = f"{action.id}({suffix})"
            cached.family = action.id
        return cached

    concrete = Action(
        id=f"{action.id}({suffix})" if action.id else "",
        name=action.name,
        description=action.description,
        family=action.id,
        by=action.by,
        pre=[_subst_pred(p, binding) for p in action.pre],
        post=[_subst_pred(p, binding) for p in action.post],
        effect=[_subst_effect(e, binding) for e in action.effect],
        requires=list(action.requires),
        emits=[_subst_emit(e, binding) for e in action.emits],
        on=list(action.on),
        tags=list(action.tags),
    )
    _BIND_MEMO[key] = concrete
    return concrete


def expand_action(action: Action) -> list[Action]:
    """All concrete instances of a parameterized action (where-filtered)."""
    if not action.params:
        return [action]
    names = [p.name for p in action.params]
    out: list[Action] = []
    for combo in product(*(p.domain for p in action.params)):
        binding = dict(zip(names, combo, strict=True))
        if not _where_holds(action, binding):
            continue
        out.append(bind_action(action, binding))
    return out

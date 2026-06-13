from __future__ import annotations

from typing import Any

from analint.models.expr import _AddExpr, _MulExpr, _SubExpr
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
from analint.models.quantifier import (
    Bound,
    BoundField,
    _Count,
    _Exists,
    _ForAll,
    _Max,
    _Min,
    _Present,
    _Sum,
)
from analint.models.scope import field_context_key, is_field_ref, is_present, present_instances

Context = dict[Any, Any]


class UnsupportedPredicateError(TypeError):
    """An object that is not a known predicate node reached the evaluator.

    A verifier must never guess: an unknown node is a model error, not `True`.
    """


def resolve(
    operand: Any,
    context: Context,
    bindings: dict[Bound, Any] | None = None,
) -> Any:
    bindings = bindings or {}
    if is_field_ref(operand):
        key = field_context_key(operand)
        entity = context.get(key)
        if entity is None:
            raise KeyError(f"Entity '{key!r}' not in scenario given")
        if not is_present(context, key):
            raise KeyError(f"Entity '{key!r}' is absent")
        return getattr(entity, operand.field_name)
    if isinstance(operand, BoundField):
        instance = bindings.get(operand.variable)
        if instance is None:
            raise KeyError(f"Bound variable '{operand.variable.name}' has no quantifier binding")
        entity = context.get(instance)
        if entity is None:
            raise KeyError(f"Entity '{instance!r}' not in scenario given")
        if not is_present(context, instance):
            raise KeyError(f"Entity '{instance!r}' is absent")
        return getattr(entity, operand.field_name)
    if isinstance(operand, _AddExpr):
        return resolve(operand.left, context, bindings) + resolve(operand.right, context, bindings)
    if isinstance(operand, _SubExpr):
        return resolve(operand.left, context, bindings) - resolve(operand.right, context, bindings)
    if isinstance(operand, _MulExpr):
        return resolve(operand.left, context, bindings) * resolve(operand.right, context, bindings)
    if isinstance(operand, _Count):
        results = [
            evaluate(operand.predicate, context, {**bindings, operand.variable: instance})
            for instance in present_instances(operand.variable.scope, context)
        ]
        return sum(results)
    if isinstance(operand, (_Sum, _Min, _Max)):
        values = [
            resolve(operand.operand, context, {**bindings, operand.variable: instance})
            for instance in present_instances(operand.variable.scope, context)
        ]
        if isinstance(operand, _Sum):
            return sum(values)
        if not values:
            name = type(operand).__name__[1:]
            scope = operand.variable.scope
            raise ValueError(
                f"{name} over Scope '{scope.id or scope.entity_cls.__name__}' "
                f"has no present instances"
            )
        if isinstance(operand, _Min):
            return min(values)
        return max(values)
    return operand


def evaluate(
    pred: Predicate,
    context: Context,
    bindings: dict[Bound, Any] | None = None,
) -> bool:
    bindings = bindings or {}
    if isinstance(pred, _Eq):
        return resolve(pred.left, context, bindings) == resolve(pred.right, context, bindings)
    if isinstance(pred, _Ne):
        return resolve(pred.left, context, bindings) != resolve(pred.right, context, bindings)
    if isinstance(pred, _Gt):
        return resolve(pred.left, context, bindings) > resolve(pred.right, context, bindings)
    if isinstance(pred, _Gte):
        return resolve(pred.left, context, bindings) >= resolve(pred.right, context, bindings)
    if isinstance(pred, _Lt):
        return resolve(pred.left, context, bindings) < resolve(pred.right, context, bindings)
    if isinstance(pred, _Lte):
        return resolve(pred.left, context, bindings) <= resolve(pred.right, context, bindings)
    if isinstance(pred, _And):
        return all(evaluate(e, context, bindings) for e in pred.exprs)
    if isinstance(pred, _Or):
        return any(evaluate(e, context, bindings) for e in pred.exprs)
    if isinstance(pred, _Not):
        return not evaluate(pred.expr, context, bindings)
    if isinstance(pred, _Implies):
        return (not evaluate(pred.left, context, bindings)) or evaluate(
            pred.right, context, bindings
        )
    if isinstance(pred, _In):
        return resolve(pred.operand, context, bindings) in [
            resolve(value, context, bindings) for value in pred.values
        ]
    if isinstance(pred, _IsNull):
        return resolve(pred.operand, context, bindings) is None
    if isinstance(pred, _IsNotNull):
        return resolve(pred.operand, context, bindings) is not None
    if isinstance(pred, _Present):
        target = bindings.get(pred.target) if isinstance(pred.target, Bound) else pred.target
        if target is None:
            raise KeyError(f"Bound variable '{pred.target.name}' has no quantifier binding")
        return is_present(context, target)
    if isinstance(pred, _ForAll):
        results = [
            evaluate(pred.predicate, context, {**bindings, pred.variable: instance})
            for instance in present_instances(pred.variable.scope, context)
        ]
        return all(results)
    if isinstance(pred, _Exists):
        results = [
            evaluate(pred.predicate, context, {**bindings, pred.variable: instance})
            for instance in present_instances(pred.variable.scope, context)
        ]
        return any(results)
    raise UnsupportedPredicateError(
        f"unsupported predicate node: {pred!r} ({type(pred).__name__}) — "
        f"predicates must be built from analint field comparisons and combinators"
    )

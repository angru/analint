from __future__ import annotations

from typing import Any

from analint.models.entity import FieldDescriptor
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

Context = dict[type, Any]


class UnsupportedPredicateError(TypeError):
    """An object that is not a known predicate node reached the evaluator.

    A verifier must never guess: an unknown node is a model error, not `True`.
    """


def resolve(operand: Any, context: Context) -> Any:
    if isinstance(operand, FieldDescriptor):
        entity = context.get(operand.entity_cls)
        if entity is None:
            raise KeyError(f"Entity '{operand.entity_cls.__name__}' not in scenario given")
        return getattr(entity, operand.field_name)
    return operand


def evaluate(pred: Predicate, context: Context) -> bool:
    if isinstance(pred, _Eq):
        return resolve(pred.left, context) == resolve(pred.right, context)
    if isinstance(pred, _Ne):
        return resolve(pred.left, context) != resolve(pred.right, context)
    if isinstance(pred, _Gt):
        return resolve(pred.left, context) > resolve(pred.right, context)
    if isinstance(pred, _Gte):
        return resolve(pred.left, context) >= resolve(pred.right, context)
    if isinstance(pred, _Lt):
        return resolve(pred.left, context) < resolve(pred.right, context)
    if isinstance(pred, _Lte):
        return resolve(pred.left, context) <= resolve(pred.right, context)
    if isinstance(pred, _And):
        return all(evaluate(e, context) for e in pred.exprs)
    if isinstance(pred, _Or):
        return any(evaluate(e, context) for e in pred.exprs)
    if isinstance(pred, _Not):
        return not evaluate(pred.expr, context)
    if isinstance(pred, _Implies):
        return (not evaluate(pred.left, context)) or evaluate(pred.right, context)
    if isinstance(pred, _In):
        return resolve(pred.operand, context) in pred.values
    if isinstance(pred, _IsNull):
        return resolve(pred.operand, context) is None
    if isinstance(pred, _IsNotNull):
        return resolve(pred.operand, context) is not None
    raise UnsupportedPredicateError(
        f"unsupported predicate node: {pred!r} ({type(pred).__name__}) — "
        f"predicates must be built from analint field comparisons and combinators"
    )

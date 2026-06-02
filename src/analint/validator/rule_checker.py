from __future__ import annotations
from analint.models.entity import Entity, FieldDescriptor
from analint.models.predicate import (
    _Eq, _Ne, _Gt, _Gte, _Lt, _Lte,
    _And, _Or, _Not,
    _In, _IsNull, _IsNotNull,
)

Context = dict[type, Entity]


def resolve(operand: object, context: Context) -> object:
    if isinstance(operand, FieldDescriptor):
        entity = context.get(operand.entity_cls)
        if entity is None:
            raise KeyError(f"Entity '{operand.entity_cls.__name__}' not in scenario given")
        return getattr(entity, operand.field_name)
    return operand


def evaluate(pred: object, context: Context) -> bool:
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
    if isinstance(pred, _In):
        return resolve(pred.operand, context) in pred.values
    if isinstance(pred, _IsNull):
        return resolve(pred.operand, context) is None
    if isinstance(pred, _IsNotNull):
        return resolve(pred.operand, context) is not None
    return True

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


# ── compiled evaluation ──────────────────────────────────────────────────────
# The explorer evaluates the same guards and invariants millions of times; the
# isinstance dispatch above dominated exploration (research/34 §8 E). These
# closures mirror evaluate()/resolve() node by node — same evaluation order,
# same exceptions and messages; an unknown node defers to evaluate(), which
# raises UnsupportedPredicateError exactly as before. Every compiled function
# takes (context, bindings).


def compile_predicate(pred: Predicate) -> Any:
    """``f(context) -> bool``, equivalent to ``evaluate(pred, context)``."""
    compiled = _compile_pred(pred)
    return lambda ctx: compiled(ctx, {})


def _compile_pred(pred: Any) -> Any:
    if isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        left, right = _compile_operand(pred.left), _compile_operand(pred.right)
        if isinstance(pred, _Eq):
            return lambda ctx, b: left(ctx, b) == right(ctx, b)
        if isinstance(pred, _Ne):
            return lambda ctx, b: left(ctx, b) != right(ctx, b)
        if isinstance(pred, _Gt):
            return lambda ctx, b: left(ctx, b) > right(ctx, b)
        if isinstance(pred, _Gte):
            return lambda ctx, b: left(ctx, b) >= right(ctx, b)
        if isinstance(pred, _Lt):
            return lambda ctx, b: left(ctx, b) < right(ctx, b)
        return lambda ctx, b: left(ctx, b) <= right(ctx, b)
    if isinstance(pred, (_And, _Or)):
        parts = tuple(_compile_pred(e) for e in pred.exprs)
        if isinstance(pred, _And):
            return lambda ctx, b: all(part(ctx, b) for part in parts)
        return lambda ctx, b: any(part(ctx, b) for part in parts)
    if isinstance(pred, _Not):
        inner = _compile_pred(pred.expr)
        return lambda ctx, b: not inner(ctx, b)
    if isinstance(pred, _Implies):
        antecedent, consequent = _compile_pred(pred.left), _compile_pred(pred.right)
        return lambda ctx, b: (not antecedent(ctx, b)) or consequent(ctx, b)
    if isinstance(pred, _In):
        operand = _compile_operand(pred.operand)
        values = tuple(_compile_operand(v) for v in pred.values)
        return lambda ctx, b: operand(ctx, b) in [value(ctx, b) for value in values]
    if isinstance(pred, (_IsNull, _IsNotNull)):
        operand = _compile_operand(pred.operand)
        if isinstance(pred, _IsNull):
            return lambda ctx, b: operand(ctx, b) is None
        return lambda ctx, b: operand(ctx, b) is not None
    if isinstance(pred, _Present):
        target = pred.target
        if not isinstance(target, Bound):
            return lambda ctx, b: is_present(ctx, target)

        def present(ctx: Context, b: dict) -> bool:
            instance = b.get(target)
            if instance is None:
                raise KeyError(f"Bound variable '{target.name}' has no quantifier binding")
            return is_present(ctx, instance)

        return present
    if isinstance(pred, (_ForAll, _Exists)):
        variable, scope, body = pred.variable, pred.variable.scope, _compile_pred(pred.predicate)
        # the list is built in full, as in evaluate(): a later member's error
        # is raised even when an earlier one already decides the result
        if isinstance(pred, _ForAll):
            return lambda ctx, b: all(
                [body(ctx, {**b, variable: inst}) for inst in present_instances(scope, ctx)]
            )
        return lambda ctx, b: any(
            [body(ctx, {**b, variable: inst}) for inst in present_instances(scope, ctx)]
        )
    return lambda ctx, b: evaluate(pred, ctx, b)


def _compile_operand(operand: Any) -> Any:
    if is_field_ref(operand):
        key = field_context_key(operand)
        name = operand.field_name

        def field(ctx: Context, b: dict) -> Any:
            entity = ctx.get(key)
            if entity is None:
                raise KeyError(f"Entity '{key!r}' not in scenario given")
            if not is_present(ctx, key):
                raise KeyError(f"Entity '{key!r}' is absent")
            return getattr(entity, name)

        return field
    if isinstance(operand, BoundField):
        variable, name = operand.variable, operand.field_name

        def bound_field(ctx: Context, b: dict) -> Any:
            instance = b.get(variable)
            if instance is None:
                raise KeyError(f"Bound variable '{variable.name}' has no quantifier binding")
            entity = ctx.get(instance)
            if entity is None:
                raise KeyError(f"Entity '{instance!r}' not in scenario given")
            if not is_present(ctx, instance):
                raise KeyError(f"Entity '{instance!r}' is absent")
            return getattr(entity, name)

        return bound_field
    if isinstance(operand, (_AddExpr, _SubExpr, _MulExpr)):
        left, right = _compile_operand(operand.left), _compile_operand(operand.right)
        if isinstance(operand, _AddExpr):
            return lambda ctx, b: left(ctx, b) + right(ctx, b)
        if isinstance(operand, _SubExpr):
            return lambda ctx, b: left(ctx, b) - right(ctx, b)
        return lambda ctx, b: left(ctx, b) * right(ctx, b)
    if isinstance(operand, _Count):
        variable, scope = operand.variable, operand.variable.scope
        body = _compile_pred(operand.predicate)
        return lambda ctx, b: sum(
            [body(ctx, {**b, variable: inst}) for inst in present_instances(scope, ctx)]
        )
    if isinstance(operand, (_Sum, _Min, _Max)):
        # empty Min/Max raises exactly as resolve() does
        return lambda ctx, b: resolve(operand, ctx, b)
    return lambda ctx, b: operand

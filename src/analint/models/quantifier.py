"""Finite quantifiers over a bounded Scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from analint.models.entity import all_fields
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
from analint.models.scope import InstanceRef, Scope

if TYPE_CHECKING:
    from analint.models.scope import InstanceField


class Bound:
    """A named variable ranging over every instance in a finite Scope."""

    def __init__(self, name: str, scope: Scope) -> None:
        if not name:
            raise TypeError("Bound needs a name: Bound('account', accounts)")
        if not isinstance(scope, Scope):
            raise TypeError("Bound domain must be a Scope")
        self.name = name
        self.scope = scope

    def __getattr__(self, field_name: str) -> BoundField:
        if field_name.startswith("_"):
            raise AttributeError(field_name)
        if field_name not in all_fields(self.scope.entity_cls):
            raise AttributeError(f"{self.scope.entity_cls.__name__} has no field '{field_name}'")
        return BoundField(self, field_name)

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return self.name


class BoundField:
    """A field of the instance currently bound by a finite quantifier."""

    def __init__(self, variable: Bound, field_name: str) -> None:
        self.variable = variable
        self.field_name = field_name

    @property
    def entity_cls(self) -> type:
        return self.variable.scope.entity_cls

    def __eq__(self, other: Any) -> Predicate:  # type: ignore
        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore
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

    def __mul__(self, other: Any) -> Expr:
        return _MulExpr(self, other)

    def __rmul__(self, other: Any) -> Expr:
        return _MulExpr(other, self)

    def __hash__(self) -> int:
        return hash((id(self.variable), self.field_name))

    def __repr__(self) -> str:
        return f"{self.variable.name}.{self.field_name}"


@dataclass
class _ForAll(Predicate):
    variable: Bound
    predicate: Predicate


@dataclass
class _Exists(Predicate):
    variable: Bound
    predicate: Predicate


@dataclass
class _Present(Predicate):
    target: Any


@dataclass(eq=False)
class _Count(Expr):
    variable: Bound
    predicate: Predicate


@dataclass(eq=False)
class _Sum(Expr):
    variable: Bound
    operand: Any


@dataclass(eq=False)
class _Min(Expr):
    variable: Bound
    operand: Any


@dataclass(eq=False)
class _Max(Expr):
    variable: Bound
    operand: Any


def ForAll(variable: Bound, predicate: Predicate) -> _ForAll:
    """The predicate must hold for every instance in the variable's Scope."""
    if not isinstance(variable, Bound):
        raise TypeError("ForAll variable must be Bound(...)")
    if not isinstance(predicate, Predicate):
        raise TypeError("ForAll body must be a Predicate")
    return _ForAll(variable=variable, predicate=predicate)


def Exists(variable: Bound, predicate: Predicate) -> _Exists:
    """The predicate must hold for at least one instance in the variable's Scope."""
    if not isinstance(variable, Bound):
        raise TypeError("Exists variable must be Bound(...)")
    if not isinstance(predicate, Predicate):
        raise TypeError("Exists body must be a Predicate")
    return _Exists(variable=variable, predicate=predicate)


def Present(target: Any) -> _Present:
    """The scoped instance currently exists in the bounded universe."""
    if not isinstance(target, (Bound, InstanceRef)):
        from analint.models.param import Param

        if not isinstance(target, Param):
            raise TypeError("Present needs an InstanceRef, Bound, or instance Param")
    return _Present(target=target)


def Count(variable: Bound, predicate: Predicate) -> _Count:
    """Count instances in the variable's Scope for which predicate holds."""
    if not isinstance(variable, Bound):
        raise TypeError("Count variable must be Bound(...)")
    if not isinstance(predicate, Predicate):
        raise TypeError("Count body must be a Predicate")
    return _Count(variable=variable, predicate=predicate)


def Sum(variable: Bound, operand: Any) -> _Sum:
    """Sum an operand over every instance in the variable's Scope."""
    if not isinstance(variable, Bound):
        raise TypeError("Sum variable must be Bound(...)")
    if isinstance(operand, Predicate):
        raise TypeError("Sum body must be a value expression; use Count for predicates")
    return _Sum(variable=variable, operand=operand)


def Min(variable: Bound, operand: Any) -> _Min:
    """Return the minimum operand value over a non-empty bounded Scope."""
    if not isinstance(variable, Bound):
        raise TypeError("Min variable must be Bound(...)")
    if isinstance(operand, Predicate):
        raise TypeError("Min body must be a value expression; use Count for predicates")
    return _Min(variable=variable, operand=operand)


def Max(variable: Bound, operand: Any) -> _Max:
    """Return the maximum operand value over a non-empty bounded Scope."""
    if not isinstance(variable, Bound):
        raise TypeError("Max variable must be Bound(...)")
    if isinstance(operand, Predicate):
        raise TypeError("Max body must be a value expression; use Count for predicates")
    return _Max(variable=variable, operand=operand)


def bind_predicate(pred: Predicate, variable: Bound, instance: InstanceRef) -> Predicate:
    """Substitute one Bound variable with a concrete InstanceRef."""
    if isinstance(pred, (_And, _Or)):
        return type(pred)(exprs=[bind_predicate(expr, variable, instance) for expr in pred.exprs])
    if isinstance(pred, _Not):
        return _Not(expr=bind_predicate(pred.expr, variable, instance))
    if isinstance(pred, _Implies):
        return _Implies(
            left=bind_predicate(pred.left, variable, instance),
            right=bind_predicate(pred.right, variable, instance),
        )
    if isinstance(pred, (_ForAll, _Exists)):
        if pred.variable is variable:
            return pred
        return type(pred)(
            variable=pred.variable,
            predicate=bind_predicate(pred.predicate, variable, instance),
        )
    if isinstance(pred, _Present):
        if pred.target is variable:
            return _Present(target=instance)
        return pred
    if isinstance(pred, (_Eq, _Ne, _Gt, _Gte, _Lt, _Lte)):
        return type(pred)(
            left=bind_operand(pred.left, variable, instance),
            right=bind_operand(pred.right, variable, instance),
        )
    if isinstance(pred, _In):
        return _In(
            operand=bind_operand(pred.operand, variable, instance),
            values=[bind_operand(value, variable, instance) for value in pred.values],
        )
    if isinstance(pred, (_IsNull, _IsNotNull)):
        return type(pred)(operand=bind_operand(pred.operand, variable, instance))
    return pred


def bind_operand(operand: Any, variable: Bound, instance: InstanceRef) -> Any:
    if isinstance(operand, BoundField) and operand.variable is variable:
        field: InstanceField = getattr(instance, operand.field_name)
        return field
    if isinstance(operand, _Count):
        if operand.variable is variable:
            return operand
        return _Count(
            variable=operand.variable,
            predicate=bind_predicate(operand.predicate, variable, instance),
        )
    if isinstance(operand, (_Sum, _Min, _Max)):
        if operand.variable is variable:
            return operand
        return type(operand)(
            variable=operand.variable,
            operand=bind_operand(operand.operand, variable, instance),
        )
    if isinstance(operand, (_AddExpr, _SubExpr, _MulExpr)):
        return type(operand)(
            bind_operand(operand.left, variable, instance),
            bind_operand(operand.right, variable, instance),
        )
    return operand

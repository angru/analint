from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Predicate:
    """Base class for all predicate expressions (enables typing and isinstance)."""


def normalize_predicate(value: Any) -> Any:
    """Normalize a boolean field reference in predicate position."""
    if isinstance(value, Predicate):
        return value
    entity_cls = getattr(value, "entity_cls", None)
    if entity_cls is None:
        param = getattr(value, "param", None)
        domain = getattr(param, "domain", ())
        first = domain[0] if domain else None
        entity_cls = getattr(first, "entity_cls", None)
        if entity_cls is None and isinstance(first, type):
            entity_cls = first
    field_name = getattr(value, "field_name", None)
    if entity_cls is None or field_name is None:
        return value
    annotation = None
    for cls in reversed(entity_cls.__mro__):
        annotation = getattr(cls, "__annotations__", {}).get(field_name, annotation)
    return _Eq(left=value, right=True) if annotation is bool or annotation == "bool" else value


# ── Comparison predicates ───────────────────────────────────────────────────────


@dataclass
class _BinaryComparison(Predicate):
    """Closed base for the binary comparison nodes — carries typed operands so
    traversal can read ``.left``/``.right`` without an attr-defined suppression."""

    left: Any
    right: Any


@dataclass
class _Eq(_BinaryComparison):
    pass


@dataclass
class _Ne(_BinaryComparison):
    pass


@dataclass
class _Gt(_BinaryComparison):
    pass


@dataclass
class _Gte(_BinaryComparison):
    pass


@dataclass
class _Lt(_BinaryComparison):
    pass


@dataclass
class _Lte(_BinaryComparison):
    pass


# ── Logical predicates ─────────────────────────────────────────────────────────


@dataclass
class _And(Predicate):
    exprs: list[Predicate]


@dataclass
class _Or(Predicate):
    exprs: list[Predicate]


@dataclass
class _Not(Predicate):
    expr: Predicate


@dataclass
class _Implies(Predicate):
    left: Predicate
    right: Predicate


# ── Membership / null predicates ───────────────────────────────────────────────


@dataclass
class _In(Predicate):
    operand: Any
    values: list[Any]


@dataclass
class _IsNull(Predicate):
    operand: Any


@dataclass
class _IsNotNull(Predicate):
    operand: Any


# ── Public DSL factory functions ───────────────────────────────────────────────


def And(*exprs: Predicate) -> _And:
    """All sub-predicates must hold."""
    return _And(exprs=[normalize_predicate(expr) for expr in exprs])


def Or(*exprs: Predicate) -> _Or:
    """At least one sub-predicate must hold."""
    return _Or(exprs=[normalize_predicate(expr) for expr in exprs])


def Not(expr: Predicate) -> _Not:
    """Negation of a predicate."""
    return _Not(expr=normalize_predicate(expr))


def Implies(left: Predicate, right: Predicate) -> _Implies:
    """If `left` holds, `right` must hold too (vacuously true when `left` is false)."""
    return _Implies(left=normalize_predicate(left), right=normalize_predicate(right))


def In(operand: Any, values: list[Any]) -> _In:
    """Field value must be one of the given values."""
    return _In(operand=operand, values=values)


def IsNull(operand: Any) -> _IsNull:
    """Field value must be None."""
    return _IsNull(operand=operand)


def IsNotNull(operand: Any) -> _IsNotNull:
    """Field value must not be None."""
    return _IsNotNull(operand=operand)

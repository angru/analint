from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Predicate:
    """Base class for all predicate expressions (enables typing and isinstance)."""


# ── Comparison predicates ───────────────────────────────────────────────────────


@dataclass
class _Eq(Predicate):
    left: Any
    right: Any


@dataclass
class _Ne(Predicate):
    left: Any
    right: Any


@dataclass
class _Gt(Predicate):
    left: Any
    right: Any


@dataclass
class _Gte(Predicate):
    left: Any
    right: Any


@dataclass
class _Lt(Predicate):
    left: Any
    right: Any


@dataclass
class _Lte(Predicate):
    left: Any
    right: Any


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
    return _And(exprs=list(exprs))


def Or(*exprs: Predicate) -> _Or:
    """At least one sub-predicate must hold."""
    return _Or(exprs=list(exprs))


def Not(expr: Predicate) -> _Not:
    """Negation of a predicate."""
    return _Not(expr=expr)


def Implies(left: Predicate, right: Predicate) -> _Implies:
    """If `left` holds, `right` must hold too (vacuously true when `left` is false)."""
    return _Implies(left=left, right=right)


def In(operand: Any, values: list[Any]) -> _In:
    """Field value must be one of the given values."""
    return _In(operand=operand, values=values)


def IsNull(operand: Any) -> _IsNull:
    """Field value must be None."""
    return _IsNull(operand=operand)


def IsNotNull(operand: Any) -> _IsNotNull:
    """Field value must not be None."""
    return _IsNotNull(operand=operand)

from __future__ import annotations
from dataclasses import dataclass, field


# ── Comparison predicates ───────────────────────────────────────────────────────

@dataclass
class _Eq:
    left: object
    right: object

@dataclass
class _Ne:
    left: object
    right: object

@dataclass
class _Gt:
    left: object
    right: object

@dataclass
class _Gte:
    left: object
    right: object

@dataclass
class _Lt:
    left: object
    right: object

@dataclass
class _Lte:
    left: object
    right: object


# ── Logical predicates ─────────────────────────────────────────────────────────

@dataclass
class _And:
    exprs: list

@dataclass
class _Or:
    exprs: list

@dataclass
class _Not:
    expr: object


# ── Membership / null predicates ───────────────────────────────────────────────

@dataclass
class _In:
    operand: object
    values: list

@dataclass
class _IsNull:
    operand: object

@dataclass
class _IsNotNull:
    operand: object


# ── Public DSL factory functions ───────────────────────────────────────────────

def And(*exprs: object) -> _And:
    """All sub-predicates must hold."""
    return _And(exprs=list(exprs))

def Or(*exprs: object) -> _Or:
    """At least one sub-predicate must hold."""
    return _Or(exprs=list(exprs))

def Not(expr: object) -> _Not:
    """Negation of a predicate."""
    return _Not(expr=expr)

def In(operand: object, values: list) -> _In:
    """Field value must be one of the given values."""
    return _In(operand=operand, values=values)

def IsNull(operand: object) -> _IsNull:
    """Field value must be None."""
    return _IsNull(operand=operand)

def IsNotNull(operand: object) -> _IsNotNull:
    """Field value must not be None."""
    return _IsNotNull(operand=operand)

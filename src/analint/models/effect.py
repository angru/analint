from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from analint.models.entity import FieldDescriptor

    Amount = Union["FieldDescriptor", int, float]


class Effect:
    """Base class for next-state facts (enables typing and isinstance)."""


@dataclass
class Set(Effect):
    """Fact: after the action, the field holds this value.

    The value may be a literal, an enum member, or another FieldDescriptor —
    resolved against the *pre*-state, like every effect right-hand side.
    """
    field: "FieldDescriptor"
    value: Any


@dataclass
class Subtract(Effect):
    """Fact: after the action, the field holds (old value − amount)."""
    field: "FieldDescriptor"
    amount: "Amount"


@dataclass
class Add(Effect):
    """Fact: after the action, the field holds (old value + amount)."""
    field: "FieldDescriptor"
    amount: "Amount"

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analint.models.scope import FieldRef

    Amount = FieldRef | int | float


class Effect:
    """Base class for next-state facts (enables typing and isinstance)."""


@dataclass
class Set(Effect):
    """Fact: after the action, the field holds this value.

    The value may be a literal, an enum member, or another FieldDescriptor —
    resolved against the *pre*-state, like every effect right-hand side.
    """

    field: FieldRef
    value: Any


@dataclass
class Subtract(Effect):
    """Fact: after the action, the field holds (old value − amount)."""

    field: FieldRef
    amount: Amount


@dataclass
class Add(Effect):
    """Fact: after the action, the field holds (old value + amount)."""

    field: FieldRef
    amount: Amount

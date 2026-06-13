from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analint.models.scope import FieldRef, InstanceRef

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


class Create(Effect):
    """Fact: after the action, this slot is present in its bounded Scope.

    The target is an ``InstanceRef`` (or an instance ``Param``, resolved by
    ``bind()``). Field values may be literals, enum members or other field
    references resolved against the *pre*-state; unspecified fields take their
    declared defaults. The slot must be absent in the pre-state — creating an
    already-present slot is a pre-execution rejection, not an effect.
    """

    def __init__(self, target: InstanceRef, **fields: Any) -> None:
        self.target = target
        self.fields = fields

    def __repr__(self) -> str:
        inner = ", ".join(f"{name}={value!r}" for name, value in self.fields.items())
        return f"Create({self.target!r}{', ' + inner if inner else ''})"


class Delete(Effect):
    """Fact: after the action, this slot is absent from its bounded Scope.

    The target is an ``InstanceRef`` (or an instance ``Param``). The slot must
    be present in the pre-state — deleting an absent slot is a pre-execution
    rejection, not an effect.
    """

    def __init__(self, target: InstanceRef) -> None:
        self.target = target

    def __repr__(self) -> str:
        return f"Delete({self.target!r})"

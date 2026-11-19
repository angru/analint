"""An exhaustive enum-to-integer table, represented as a closed expression."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from analint.models.expr import Expr


@dataclass(eq=False, frozen=True)
class _Lookup(Expr):
    selector: Any
    entries: tuple[tuple[Enum, int], ...]

    def value(self, selector: Any) -> int:
        # Follow the DSL's existing Python equality: scalar Enums compare equal
        # to their underlying values, also when equal states are interned.
        for key, value in self.entries:
            if selector == key:
                return value
        raise ValueError(f"Lookup has no entry for {selector!r}")


def Lookup(selector: Any, mapping: Mapping[Enum, int]) -> Expr:
    """Map every member of one Enum to an integer constant; no default arm."""
    if not mapping:
        raise TypeError("Lookup needs a non-empty enum mapping")
    keys = list(mapping)
    enum = type(keys[0])
    if not isinstance(keys[0], Enum) or any(type(key) is not enum for key in keys):
        raise TypeError("Lookup keys must belong to one Enum")
    if set(keys) != set(enum):
        raise ValueError(f"Lookup must cover every member of {enum.__name__}")
    if any(type(value) is not int for value in mapping.values()):
        raise TypeError("Lookup values must be integer constants (excluding bool)")
    return _Lookup(selector, tuple((key, mapping[key]) for key in enum))

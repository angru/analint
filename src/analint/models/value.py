"""The closed literal domain for operands (distinct from AST nodes)."""

from enum import Enum
from typing import Any

from analint.models.entity import Entity
from analint.models.scope import InstanceRef


def is_literal_operand(value: Any) -> bool:
    """Opaque Python objects cannot stand in for unknown expression nodes.

    Entity classes are declared identities as well as parameter domains:
    ``where=[src != dst]`` compares those identities after substitution.
    They are supported operands, not a blanket allowance for Python classes.
    """
    return (
        value is None
        or isinstance(value, (bool, int, float, str, Enum, InstanceRef))
        or (isinstance(value, type) and issubclass(value, Entity))
    )

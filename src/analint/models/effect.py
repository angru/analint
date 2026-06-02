from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Set:
    """Set field to a fixed value after use case execution."""
    field: object   # FieldDescriptor
    value: object   # literal or enum value


@dataclass
class Subtract:
    """Subtract amount from field value after use case execution."""
    field: object   # FieldDescriptor
    amount: object  # FieldDescriptor or literal


@dataclass
class Add:
    """Add amount to field value after use case execution."""
    field: object   # FieldDescriptor
    amount: object  # FieldDescriptor or literal

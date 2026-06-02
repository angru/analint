from __future__ import annotations
from dataclasses import dataclass, field as dc_field


@dataclass
class Assert:
    """Post-execution assertion on entity state."""
    predicate: object  # predicate expression


@dataclass
class Emitted:
    """Assert that a specific event class was emitted during execution."""
    event_cls: object  # Event subclass


@dataclass
class Flow:
    """Describes a linear sequence of use cases (a user journey)."""
    id: str
    steps: list = dc_field(default_factory=list)  # list[UseCase]
    description: str = ""

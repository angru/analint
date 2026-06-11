from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING

from analint.models.event import Event
from analint.models.predicate import Predicate

if TYPE_CHECKING:
    from analint.models.action import Action


@dataclass
class Assert:
    """Post-execution assertion on entity state."""

    predicate: Predicate


@dataclass
class Emitted:
    """Assert that a specific event class was emitted during execution."""

    event_cls: type[Event]


@dataclass
class Flow:
    """Describes a linear sequence of actions (a user journey)."""

    steps: list[Action] = dc_field(default_factory=list)
    id: str = ""  # filled from the variable name by the loader when empty
    description: str = ""

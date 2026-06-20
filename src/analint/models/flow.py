from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from analint.models.action import Action
from analint.models.event import Event
from analint.models.predicate import Predicate


@dataclass
class Assert:
    """Post-execution assertion on entity state."""

    predicate: Predicate


@dataclass
class Emitted:
    """Assert that a specific event class was emitted during execution."""

    event_cls: type[Event]


# The closed grammar of a flow step: an action interleaved with checkpoints.
FlowEntry = Action | Assert | Emitted


@dataclass
class Flow:
    """An executable user journey: an initial state, then a sequence of actions
    and checkpoints run through the shared transition kernel.

    ``steps`` is a single mixed list of ``Action``\\ s and checkpoints
    (``Assert`` / ``Emitted``). Each action's post-state becomes the next step's
    pre-state — there are no arbitrary state deltas between steps, so every
    transition still honours preconditions. Checkpoints are optional and may
    appear anywhere: run several actions, then assert once. Each action must be
    accepted; the first rejected/defective step fails the flow with a trace.

    ``given`` is the required initial state — a *partial snapshot* (the same builder a
    scenario uses): only the listed entities are present and unspecified Scope
    slots are absent, so this is not the canonical defaults-built world and a step
    that needs an unlisted entity is rejected. ``given=[]`` is an empty world,
    useful only when the flow creates everything it needs; every flow is executed.
    """

    given: list[Any]  # required partial snapshot; [] means no unscoped entities
    steps: list[FlowEntry] = dc_field(default_factory=list)
    id: str = ""  # filled from the variable name by the loader when empty
    description: str = ""

    def __post_init__(self) -> None:
        if self.given is None:
            raise TypeError("Flow.given must be a list, not None")

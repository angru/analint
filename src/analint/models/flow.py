from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

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

    A flow with a non-empty ``given`` is executed; a flow with only steps and no
    ``given`` stays a documented journey (validated structurally, shown, but not
    run), preserving the original journey-documentation use.
    """

    steps: list[Any] = dc_field(default_factory=list)  # Action | Assert | Emitted
    given: list[Any] = dc_field(default_factory=list)  # Entity / InstanceRef snapshots
    id: str = ""  # filled from the variable name by the loader when empty
    description: str = ""

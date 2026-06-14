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

    ``given`` is the execution-mode switch, independent of how many snapshots the
    initial state needs: ``None`` (the default) is a documented journey —
    validated structurally and shown, but not run; a list (even empty) makes the
    flow executable. The initial state is a *partial snapshot* (the same builder a
    scenario uses): only the listed entities are present and unspecified Scope
    slots are absent — this is not the canonical defaults-built world, so a step
    that needs an unlisted entity is rejected.
    """

    steps: list[FlowEntry] = dc_field(default_factory=list)
    given: list[Any] | None = None  # None = documentation; a list = executable
    id: str = ""  # filled from the variable name by the loader when empty
    description: str = ""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from analint.models.action import Action
from analint.models.actor import Actor
from analint.models.entity import Entity, all_fields
from analint.models.event import Event
from analint.models.flow import Flow
from analint.models.invariant import Invariant
from analint.models.lifecycle import Lifecycle
from analint.models.query import (
    AlwaysHolds,
    DeadActions,
    NoDeadEnd,
    Reachable,
    Unreachable,
)
from analint.models.scenario import Scenario

Query = Reachable | Unreachable | AlwaysHolds | NoDeadEnd | DeadActions


class Spec(BaseModel):
    """Root aggregate. With empty lists (the default) everything is discovered
    automatically from the modules imported by the spec entry point; a non-empty
    list is used as-is."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""

    entities: list[type[Entity]] = Field(default_factory=list)
    actors: list[type[Actor]] = Field(default_factory=list)
    events: list[type[Event]] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    lifecycles: list[Lifecycle[Any]] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    queries: list[Query] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        # Parameterized actions expand into concrete instances here, so the
        # runner, the explorer and the queries only ever see bound actions.
        from analint.models.param import expand_action

        if any(a.params for a in self.actions):
            self.actions = [bound for a in self.actions for bound in expand_action(a)]

        if self.lifecycles:
            return
        self.lifecycles = [
            desc.lifecycle
            for entity_cls in self.entities
            for desc in all_fields(entity_cls).values()
            if desc.lifecycle is not None
        ]


Spec.model_rebuild()

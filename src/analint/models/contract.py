from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from analint.models.action import Action
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
from analint.models.scope import Scope

Query = Reachable | Unreachable | AlwaysHolds | NoDeadEnd | DeadActions


class Contract(BaseModel):
    """An explicit, reusable public fragment imported by a root Spec.

    Every exported object is listed directly. This keeps composition from
    depending on which implementation modules happened to be imported.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    id: str
    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    entities: list[type[Entity]] = Field(default_factory=list)
    scopes: list[Scope] = Field(default_factory=list)
    events: list[type[Event]] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    lifecycles: list[Lifecycle[Any]] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    queries: list[Query] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.lifecycles:
            return
        self.lifecycles = [
            desc.lifecycle
            for entity_cls in self.entities
            for desc in all_fields(entity_cls).values()
            if desc.lifecycle is not None
        ]


Contract.model_rebuild()

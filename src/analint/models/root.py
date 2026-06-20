from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from analint.models.action import Action
from analint.models.contract import Contract
from analint.models.entity import Entity, all_fields
from analint.models.event import Event
from analint.models.flow import Flow
from analint.models.initial import Initial
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


class Spec(BaseModel):
    """Root aggregate. With empty lists (the default) everything is discovered
    automatically from the modules imported by the spec entry point; a non-empty
    list is used as-is. When imports are present, composition is fully explicit:
    only contract contents and directly listed local objects are included."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    imports: list[Contract] = Field(default_factory=list)

    entities: list[type[Entity]] = Field(default_factory=list)
    scopes: list[Scope] = Field(default_factory=list)
    events: list[type[Event]] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    lifecycles: list[Lifecycle[Any]] = Field(default_factory=list)
    flows: list[Flow] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    queries: list[Query] = Field(default_factory=list)

    # The canonical initial state(s) of the model: invariants are verified over
    # the states reachable from here, and a query with no initial source of its
    # own starts from it. None means "build a single root from entity defaults".
    initial: Initial | None = None
    # Exploration budget for automatic invariant verification over the canonical
    # model. A finite model larger than this reports INCONCLUSIVE; raise it here.
    max_states: int = Field(default=10_000, gt=0)

    def model_post_init(self, __context: Any) -> None:
        content_fields = (
            "entities",
            "scopes",
            "events",
            "invariants",
            "actions",
            "lifecycles",
            "flows",
            "scenarios",
            "queries",
        )
        for field_name in content_fields:
            imported = [obj for contract in self.imports for obj in getattr(contract, field_name)]
            local = getattr(self, field_name)
            setattr(self, field_name, _deduplicate_by_identity([*imported, *local]))

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


def _deduplicate_by_identity(objects: list[Any]) -> list[Any]:
    seen: set[int] = set()
    result: list[Any] = []
    for obj in objects:
        marker = id(obj)
        if marker not in seen:
            seen.add(marker)
            result.append(obj)
    return result

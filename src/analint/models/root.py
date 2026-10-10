from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

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
    """Root aggregate: the model is exactly what it and its imported contracts
    list, plus the entities, events, scopes and lifecycles that listed behaviour
    references (research/35 R1, R2). Nothing is collected from module globals."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
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
    # Actions as declared, before Param expansion — membership of a
    # parameterized action is about the declaration, not its bound instances.
    _declared_actions: list[Action] = PrivateAttr(default_factory=list)

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

        self._declared_actions = list(self.actions)
        if any(a.params for a in self.actions):
            self.actions = [bound for a in self.actions for bound in expand_action(a)]

        self.close_references()

    def close_references(self) -> None:
        """Derive entities, events, scopes and inline lifecycles from what the
        listed objects reference (research/35 R2). Additive: explicit lists
        keep their order, derived objects are appended. Behaviour is never
        derived."""
        roots = [
            self.initial,
            self.scopes,
            self.invariants,
            self._declared_actions,
            self.actions,
            self.flows,
            self.scenarios,
            self.queries,
        ]
        entities, events, scopes = _referenced_model(roots)
        self.entities = _deduplicate_by_identity([*self.entities, *entities])
        self.events = _deduplicate_by_identity([*self.events, *events])
        self.scopes = _deduplicate_by_identity([*self.scopes, *scopes])
        self.lifecycles = _deduplicate_by_identity(
            [
                *self.lifecycles,
                *(
                    desc.lifecycle
                    for entity_cls in self.entities
                    for desc in all_fields(entity_cls).values()
                    if desc.lifecycle is not None
                ),
            ]
        )


Spec.model_rebuild()


def _referenced_model(roots: list[Any]) -> tuple[list[type], list[type], list[Scope]]:
    """Entity types, event types and scopes reachable from ``roots``."""
    from analint.models.entity import FieldDescriptor

    entities: list[type] = []
    events: list[type] = []
    scopes: list[Scope] = []
    seen: set[int] = set()

    def add_type(cls: type) -> None:
        if issubclass(cls, Event):
            events.append(cls)
        elif issubclass(cls, Entity):
            entities.append(cls)

    stack = list(reversed(roots))
    while stack:
        obj = stack.pop()
        if obj is None or isinstance(obj, (str, int, float, bool)) or id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, type):
            add_type(obj)
            continue
        if isinstance(obj, Scope):
            scopes.append(obj)
            entities.append(obj.entity_cls)
            continue
        if isinstance(obj, FieldDescriptor):
            add_type(obj.entity_cls)
            continue
        if isinstance(obj, (Entity, Event)):
            add_type(type(obj))
            # a scoped snapshot carries its InstanceRef; field values are data
            stack.append(obj.__dict__.get("_analint_instance_ref"))
            continue
        if isinstance(obj, dict):
            children: list[Any] = [*obj.keys(), *obj.values()]
        elif isinstance(obj, (list, tuple, set, frozenset)):
            children = list(obj)
        elif isinstance(obj, BaseModel):
            children = [getattr(obj, name) for name in type(obj).model_fields]
        elif type(obj).__module__.startswith("analint.models."):
            # predicate/effect dataclasses, InstanceRef, Bound, Param, …
            children = list(vars(obj).values()) if hasattr(obj, "__dict__") else []
        else:
            continue
        stack.extend(reversed(children))
    return (
        _deduplicate_by_identity(entities),
        _deduplicate_by_identity(events),
        _deduplicate_by_identity(scopes),
    )


def _deduplicate_by_identity(objects: list[Any]) -> list[Any]:
    seen: set[int] = set()
    result: list[Any] = []
    for obj in objects:
        marker = id(obj)
        if marker not in seen:
            seen.add(marker)
            result.append(obj)
    return result

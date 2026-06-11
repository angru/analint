from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class Spec(BaseModel):
    """Root aggregate. With empty lists (the default) everything is discovered
    automatically from the modules imported by the spec entry point; a non-empty
    list is used as-is."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""

    entities: list[Any] = Field(default_factory=list)    # Entity subclasses (types)
    actors: list[Any] = Field(default_factory=list)      # Actor subclasses (types)
    events: list[Any] = Field(default_factory=list)      # Event subclasses (types)
    invariants: list[Any] = Field(default_factory=list)  # Invariant instances
    actions: list[Any] = Field(default_factory=list)     # Action instances
    lifecycles: list[Any] = Field(default_factory=list)  # Lifecycle instances
    flows: list[Any] = Field(default_factory=list)       # Flow instances
    scenarios: list[Any] = Field(default_factory=list)   # Scenario instances
    queries: list[Any] = Field(default_factory=list)     # Reachable/Unreachable/… instances
    bounds: list[Any] = Field(default_factory=list)      # Bounds instances

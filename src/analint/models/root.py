from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from analint.models.business import BusinessRule, UseCase
from analint.models.scenario import Scenario


class Spec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""

    entities: list[Any] = Field(default_factory=list)       # Entity subclasses (types)
    actors: list[Any] = Field(default_factory=list)          # Actor subclasses (types)
    events: list[Any] = Field(default_factory=list)          # Event subclasses (types)
    state_machines: list[Any] = Field(default_factory=list)  # StateMachine instances
    flows: list[Any] = Field(default_factory=list)           # Flow instances
    rules: list[BusinessRule] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)

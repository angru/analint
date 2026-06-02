from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RuleType(Enum):
    INVARIANT     = "invariant"     # всегда истинно, независимо от UC
    PRECONDITION  = "precondition"  # должно выполняться до запуска UC
    POSTCONDITION = "postcondition" # должно выполняться после применения эффектов UC


class BusinessRule(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    description: str = ""
    rule_type: RuleType = RuleType.INVARIANT
    expression: Any = None  # Predicate instance or None (human-verified if None)
    tags: list[str] = Field(default_factory=list)


class UseCase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    description: str = ""
    actor: Any = None                                    # Actor subclass (type) | None = system
    entities: list[Any] = Field(default_factory=list)   # Entity subclasses (types)
    rules: list[BusinessRule] = Field(default_factory=list)
    requires: list[Any] = Field(default_factory=list)   # UseCase instances that must precede this
    emits: list[Any] = Field(default_factory=list)       # Event subclasses this UC publishes
    triggered_by: list[Any] = Field(default_factory=list)  # Event subclasses that trigger this UC
    effects: list[Any] = Field(default_factory=list)     # Set/Add/Subtract applied after execution
    tags: list[str] = Field(default_factory=list)

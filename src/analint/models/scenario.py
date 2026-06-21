from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from analint.models.action import Action
from analint.models.flow import Emitted
from analint.models.predicate import Predicate, normalize_predicate


class Expect(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class Scenario(BaseModel):
    """A concrete example: initial state, one action, expected outcome.

    `given` holds Entity instances (and, for actions triggered by events,
    Event instances carrying the payload). `then` holds predicates and Emitted checks
    evaluated against the post-state.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    id: str = ""  # filled from the variable name by the loader when empty
    name: str = ""
    description: str = ""
    action: Action
    given: list[Any] = Field(default_factory=list)  # Entity / Event instances
    then: list[Predicate | Emitted] = Field(default_factory=list)
    expected: Expect = Expect.PASS
    tags: list[str] = Field(default_factory=list)

    @field_validator("then", mode="before")
    @classmethod
    def _normalize_then(cls, value: Any) -> Any:
        values = value if isinstance(value, list) else [value]
        return [normalize_predicate(item) for item in values]

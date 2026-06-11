from __future__ import annotations
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from analint.models.action import Action


class Expect(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class Scenario(BaseModel):
    """A concrete example: initial state, one action, expected outcome.

    `given` holds Entity instances (and, for actions triggered by events,
    Event instances carrying the payload). `then` holds Assert/Emitted checks
    evaluated against the post-state.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str = ""             # filled from the variable name by the loader when empty
    name: str = ""
    description: str = ""
    action: Action
    given: list[Any] = Field(default_factory=list)   # Entity / Event instances
    then: list[Any] = Field(default_factory=list)    # [Assert(pred), Emitted(EventCls)]
    expected: Expect = Expect.PASS
    tags: list[str] = Field(default_factory=list)

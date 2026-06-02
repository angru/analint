from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from analint.models.business import UseCase


class Expect(Enum):
    PASS = "pass"
    FAIL = "fail"


class Scenario(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    id: str
    name: str
    description: str = ""
    use_case: UseCase
    given: list[Any] = Field(default_factory=list)  # Entity instances
    then: list[Any] = Field(default_factory=list)    # [Assert(pred), Emitted(EventCls)]
    expected: Expect = Expect.PASS
    tags: list[str] = Field(default_factory=list)

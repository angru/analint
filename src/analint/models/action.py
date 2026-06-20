from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from analint.models.effect import Effect
from analint.models.event import Event
from analint.models.predicate import Predicate

if TYPE_CHECKING:
    from analint.models.param import Param


class Action(BaseModel):
    """A state transition: facts about the world before (`pre`) and after (`effect`).

    `pre` and `post` are plain predicate expressions — no wrapper objects.
    `effect` entries are facts about the next state (Set/Add/Subtract), applied
    simultaneously: every right-hand side is evaluated against the pre-state,
    and the order of the list carries no meaning.

    Behavioural fields. `pre`, `post`, `effect` and `emits` carry behaviour — they
    are evaluated, applied and materialised by the kernel. Event causality is
    realised through state, not through a dispatch primitive.

    Example::

        archive_card = Action(
            pre=[Card.status != CardStatus.ARCHIVED, Card.board_id == Board.id],
            effect=[Set(Card.status, CardStatus.ARCHIVED), Subtract(Board.card_count, 1)],
            emits=[CardArchived(card_id=Card.id)],
        )
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = ""  # filled from the variable name by the loader when empty
    name: str = ""
    description: str = ""
    pre: list[Predicate] = Field(default_factory=list)
    post: list[Predicate] = Field(default_factory=list)
    effect: list[Effect] = Field(default_factory=list)
    emits: list[type[Event] | Event] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Parameterized actions (research/15): one declaration over finite domains,
    # expanded into concrete instances when the Spec is built.
    params: list[Param] = Field(default_factory=list)
    where: list[Predicate] = Field(default_factory=list)
    family: str = ""  # the parameterized action this instance was expanded from
    # Structured parameter bindings of a concrete instance (param name → value),
    # set by bind_action. Private: surfaced only through the exploration artifact.
    _bindings: dict[str, Any] | None = PrivateAttr(default=None)

    @field_validator("emits", "pre", "post", "effect", "params", "where", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> Any:
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v

    def bind(self, **binding: Any) -> Action:
        """A concrete instance of this parameterized action for one binding.

        Memoized: the same binding always returns the same object, so a
        scenario's `action=send.bind(src=…)` is identical to the instance
        the Spec expansion registers.
        """
        from analint.models.param import bind_action

        return bind_action(self, binding)


# after the class definition: param.py needs nothing from this module at
# import time, and pydantic needs the real Param class for model_rebuild
from analint.models.param import Param  # noqa: E402

Action.model_rebuild()

from __future__ import annotations
from dataclasses import dataclass, field

from analint.models.predicate import Predicate


@dataclass
class Invariant:
    """A world-level constraint that must hold in every state.

    Checked in every scenario whose `given` covers the entities the expression
    references (and re-checked after effects are applied). Declared at module
    level; `id` is derived from the variable name when omitted::

        user_is_active = Invariant(User.is_active == True)
    """
    expression: Predicate
    label: str = ""          # human text for reports; defaults to the rendered expression
    id: str = ""             # filled from the variable name by the loader when empty
    description: str = ""
    tags: list[str] = field(default_factory=list)

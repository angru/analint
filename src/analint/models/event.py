from __future__ import annotations

from typing import Any

from analint.models.entity import EntityMeta, _init_fields, all_fields


class Event(metaclass=EntityMeta):
    """Base class for domain events: an observable fact that an action records as
    having happened. Subclass and annotate fields normally.

    Class-level field access returns a FieldDescriptor (same as Entity), so event
    fields can be referenced in predicates if needed.

    An action ``emits`` an event (its payload is materialised by the kernel and
    can be asserted with ``Emitted``). An action's ``on=[E]`` documents that it
    handles ``E`` — it is metadata, not operational dispatch: emitting ``E`` does
    not by itself trigger an ``on=[E]`` action. Event-driven causality is modelled
    through state (see examples/fulfillment, a saga chained via status fields).

    Example::

        class OrderPlaced(Event):
            order_id: str
            total: float
            customer_id: str

        checkout = Action(..., emits=[OrderPlaced(order_id=Order.id)])
        payment  = Action(..., on=[OrderPlaced])  # documents the handler
    """

    def __init__(self, **kwargs: Any) -> None:
        _init_fields(self, kwargs)

    def __repr__(self) -> str:
        parts = ", ".join(f"{k}={self.__dict__.get(k)!r}" for k in all_fields(type(self)))
        return f"{type(self).__name__}({parts})"

from __future__ import annotations
from analint.models.entity import EntityMeta, _init_fields


class Event(metaclass=EntityMeta):
    """Base class for domain events. Subclass and annotate fields normally.

    Class-level field access returns a FieldDescriptor (same as Entity),
    so event fields can be referenced in predicates if needed.

    Example::

        class OrderPlaced(Event):
            order_id: str
            total: float
            customer_id: str

        uc_checkout = UseCase(..., emits=[OrderPlaced])
        uc_payment  = UseCase(..., triggered_by=[OrderPlaced])
    """

    def __init__(self, **kwargs: object) -> None:
        _init_fields(self, kwargs)

    def __repr__(self) -> str:
        all_fields: dict = {}
        for klass in reversed(type(self).__mro__):
            all_fields.update(getattr(klass, "_own_fields", {}))
        parts = ", ".join(f"{k}={self.__dict__.get(k)!r}" for k in all_fields)
        return f"{type(self).__name__}({parts})"

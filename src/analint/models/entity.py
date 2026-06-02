from __future__ import annotations

_MISSING = object()


class FieldDescriptor:
    """Class-level field proxy that yields predicate objects when compared."""

    def __init__(self, entity_cls: type, field_name: str, default: object = _MISSING) -> None:
        self.entity_cls = entity_cls
        self.field_name = field_name
        self.default = default

    # descriptor protocol ──────────────────────────────────────────────────────

    def __set_name__(self, owner: type, name: str) -> None:
        self.field_name = name

    def __get__(self, obj: object, objtype: type | None = None) -> object:
        if obj is None:
            return self
        return obj.__dict__.get(self.field_name)

    def __set__(self, obj: object, value: object) -> None:
        obj.__dict__[self.field_name] = value

    # comparison operators → predicate objects ────────────────────────────────
    # Imports are deferred to avoid circular dependency with predicate.py

    def __eq__(self, other: object) -> object:  # type: ignore[override]
        from analint.models.predicate import _Eq
        return _Eq(left=self, right=other)

    def __ne__(self, other: object) -> object:  # type: ignore[override]
        from analint.models.predicate import _Ne
        return _Ne(left=self, right=other)

    def __gt__(self, other: object) -> object:
        from analint.models.predicate import _Gt
        return _Gt(left=self, right=other)

    def __ge__(self, other: object) -> object:
        from analint.models.predicate import _Gte
        return _Gte(left=self, right=other)

    def __lt__(self, other: object) -> object:
        from analint.models.predicate import _Lt
        return _Lt(left=self, right=other)

    def __le__(self, other: object) -> object:
        from analint.models.predicate import _Lte
        return _Lte(left=self, right=other)

    def __hash__(self) -> int:
        return hash((id(self.entity_cls), self.field_name))

    def __repr__(self) -> str:
        return f"{self.entity_cls.__name__}.{self.field_name}"


class EntityMeta(type):
    def __new__(mcs, name: str, bases: tuple, ns: dict) -> type:
        annotations: dict[str, object] = ns.get("__annotations__", {})
        cls = super().__new__(mcs, name, bases, ns)
        cls._own_fields: dict[str, FieldDescriptor] = {}  # type: ignore[attr-defined]
        for field_name in annotations:
            default = ns.get(field_name, _MISSING)
            desc = FieldDescriptor(cls, field_name, default)
            setattr(cls, field_name, desc)
            cls._own_fields[field_name] = desc  # type: ignore[attr-defined]
        return cls


def _init_fields(instance: object, kwargs: dict) -> None:
    """Shared __init__ logic for Entity and Event."""
    all_fields: dict[str, FieldDescriptor] = {}
    for klass in reversed(type(instance).__mro__):
        all_fields.update(getattr(klass, "_own_fields", {}))
    for field_name, desc in all_fields.items():
        if field_name in kwargs:
            instance.__dict__[field_name] = kwargs[field_name]
        elif desc.default is not _MISSING:
            instance.__dict__[field_name] = desc.default
        else:
            raise TypeError(f"{type(instance).__name__}() missing required field: '{field_name}'")


class Entity(metaclass=EntityMeta):
    """Base class for domain entities. Subclass and annotate fields normally.

    Class-level field access (``Order.total``) returns a ``FieldDescriptor``
    that supports comparison operators to build predicate expressions.
    Instance-level access (``order.total``) returns the stored value.
    """

    def __init__(self, **kwargs: object) -> None:
        _init_fields(self, kwargs)

    def __repr__(self) -> str:
        all_fields: dict[str, FieldDescriptor] = {}
        for klass in reversed(type(self).__mro__):
            all_fields.update(getattr(klass, "_own_fields", {}))
        parts = ", ".join(f"{k}={self.__dict__.get(k)!r}" for k in all_fields)
        return f"{type(self).__name__}({parts})"

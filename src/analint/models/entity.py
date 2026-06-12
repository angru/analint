from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from analint.models.lifecycle import Lifecycle

if TYPE_CHECKING:
    from analint.models.predicate import Predicate

_MISSING = object()


@dataclass
class FieldSpec:
    """Declarative field configuration — created via the `Field(...)` factory."""

    default: Any = _MISSING
    ge: Any = None
    gt: Any = None
    le: Any = None
    lt: Any = None
    values: tuple[Any, ...] | None = None
    saturate: bool = False  # engine: clamp into [ge, le] instead of failing
    description: str = ""

    def has_constraints(self) -> bool:
        return self.values is not None or any(
            v is not None for v in (self.ge, self.gt, self.le, self.lt)
        )

    def violation(self, value: Any) -> str | None:
        """Return a human-readable violation, or None when the value fits."""
        if value is None:
            return None
        if self.values is not None and value not in self.values:
            return f"must be one of {list(self.values)!r}, got {value!r}"
        if self.ge is not None and not value >= self.ge:
            return f"must be >= {self.ge}, got {value!r}"
        if self.gt is not None and not value > self.gt:
            return f"must be > {self.gt}, got {value!r}"
        if self.le is not None and not value <= self.le:
            return f"must be <= {self.le}, got {value!r}"
        if self.lt is not None and not value < self.lt:
            return f"must be < {self.lt}, got {value!r}"
        return None

    def clamp(self, value: Any) -> Any:
        if self.ge is not None and value < self.ge:
            return self.ge
        if self.le is not None and value > self.le:
            return self.le
        return value


def Field(
    default: Any = _MISSING,
    *,
    ge: Any = None,
    gt: Any = None,
    le: Any = None,
    lt: Any = None,
    values: list[Any] | tuple[Any, ...] | None = None,
    saturate: bool = False,
    description: str = "",
) -> Any:
    """Declare a field with constraints, pydantic-style:

        class Warehouse(Entity):
            stock: int = Field(0, ge=0, le=2)

    One declaration drives three checks: instance construction, the post-state
    of every scenario, and the bounds of the reachability engine
    (`saturate=True` clamps instead of failing — for threshold counters).
    """
    if values is not None:
        if not values:
            raise TypeError("Field values= needs at least one value")
        for value in values:
            try:
                hash(value)
            except TypeError as exc:
                raise TypeError(f"Field value {value!r} is not hashable") from exc
        if len(set(values)) != len(values):
            raise TypeError("Field values= must be unique")
    if saturate and (ge is None or le is None):
        raise TypeError("saturate=True requires both ge= and le=")
    if ge is not None and le is not None and ge > le:
        raise TypeError(f"Field ge={ge!r} is greater than le={le!r}")
    return FieldSpec(
        default=default,
        ge=ge,
        gt=gt,
        le=le,
        lt=lt,
        values=tuple(values) if values is not None else None,
        saturate=saturate,
        description=description,
    )


class FieldDescriptor:
    """Class-level field proxy that yields predicate objects when compared."""

    def __init__(
        self,
        entity_cls: type,
        field_name: str,
        default: Any = _MISSING,
        spec: FieldSpec | None = None,
        lifecycle: Lifecycle[Any] | None = None,
    ) -> None:
        self.entity_cls = entity_cls
        self.field_name = field_name
        self.default = default
        self.spec = spec
        self.lifecycle = lifecycle

    # descriptor protocol ──────────────────────────────────────────────────────

    def __set_name__(self, owner: type, name: str) -> None:
        self.field_name = name

    def __get__(self, obj: Any | None, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self.field_name)

    def __set__(self, obj: Any, value: Any) -> None:
        obj.__dict__[self.field_name] = value

    # comparison operators → predicate objects ────────────────────────────────
    # Imports are deferred to avoid circular dependency with predicate.py

    def __eq__(self, other: Any) -> Predicate:  # type: ignore[override]
        from analint.models.predicate import _Eq

        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore[override]
        from analint.models.predicate import _Ne

        return _Ne(left=self, right=other)

    def __gt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gt

        return _Gt(left=self, right=other)

    def __ge__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gte

        return _Gte(left=self, right=other)

    def __lt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lt

        return _Lt(left=self, right=other)

    def __le__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lte

        return _Lte(left=self, right=other)

    # arithmetic operators → expression AST nodes ──────────────────────────────

    def __add__(self, other: Any) -> Any:
        from analint.models.expr import _AddExpr

        return _AddExpr(self, other)

    def __radd__(self, other: Any) -> Any:
        from analint.models.expr import _AddExpr

        return _AddExpr(other, self)

    def __sub__(self, other: Any) -> Any:
        from analint.models.expr import _SubExpr

        return _SubExpr(self, other)

    def __rsub__(self, other: Any) -> Any:
        from analint.models.expr import _SubExpr

        return _SubExpr(other, self)

    def __mul__(self, other: Any) -> Any:
        from analint.models.expr import _MulExpr

        return _MulExpr(self, other)

    def __rmul__(self, other: Any) -> Any:
        from analint.models.expr import _MulExpr

        return _MulExpr(other, self)

    def __hash__(self) -> int:
        return hash((id(self.entity_cls), self.field_name))

    def __repr__(self) -> str:
        return f"{self.entity_cls.__name__}.{self.field_name}"


class EntityMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        ns: dict[str, Any],
    ) -> type:
        cls = super().__new__(mcs, name, bases, ns)
        # Python 3.14 stores annotations lazily (PEP 649), so read them from
        # the completed class rather than from the pre-creation namespace.
        annotations: dict[str, Any] = cls.__annotations__
        own_fields: dict[str, FieldDescriptor] = {}
        dynamic_cls: Any = cls
        dynamic_cls._own_fields = own_fields
        for field_name in annotations:
            declared = ns.get(field_name, _MISSING)
            default: Any = declared
            spec: FieldSpec | None = None
            lifecycle: Lifecycle[Any] | None = None
            if isinstance(declared, FieldSpec):
                spec = declared
                default = declared.default
            elif isinstance(declared, Lifecycle):
                lifecycle = declared
                lifecycle._bind(cls, field_name)
                default = lifecycle.initial
            desc = FieldDescriptor(cls, field_name, default, spec=spec, lifecycle=lifecycle)
            setattr(cls, field_name, desc)
            own_fields[field_name] = desc
        return cls


def all_fields(cls: type) -> dict[str, FieldDescriptor]:
    fields: dict[str, FieldDescriptor] = {}
    for klass in reversed(cls.__mro__):
        fields.update(getattr(klass, "_own_fields", {}))
    return fields


def _init_fields(instance: Any, kwargs: dict[str, Any]) -> None:
    """Shared __init__ logic for Entity and Event."""
    fields = all_fields(type(instance))
    unknown = set(kwargs) - set(fields)
    if unknown:
        raise TypeError(
            f"{type(instance).__name__}() got unknown field(s): {', '.join(sorted(unknown))}"
        )
    for field_name, desc in fields.items():
        if field_name in kwargs:
            value = kwargs[field_name]
        elif desc.default is not _MISSING:
            value = desc.default
        else:
            raise TypeError(f"{type(instance).__name__}() missing required field: '{field_name}'")
        if desc.spec is not None:
            problem = desc.spec.violation(value)
            if problem is not None:
                raise ValueError(f"{type(instance).__name__}.{field_name} {problem}")
        instance.__dict__[field_name] = value


class Entity(metaclass=EntityMeta):
    """Base class for domain entities. Subclass and annotate fields normally.

    Class-level field access (``Order.total``) returns a ``FieldDescriptor``
    that supports comparison operators to build predicate expressions.
    Instance-level access (``order.total``) returns the stored value.
    Fields may carry constraints (``Field(0, ge=0)``) or a state machine
    (``Lifecycle(initial=..., transitions=[...])``) as their default.
    """

    def __init__(self, **kwargs: Any) -> None:
        _init_fields(self, kwargs)

    def __repr__(self) -> str:
        parts = ", ".join(f"{k}={self.__dict__.get(k)!r}" for k in all_fields(type(self)))
        ref = self.__dict__.get("_analint_instance_ref")
        prefix = repr(ref) if ref is not None else type(self).__name__
        return f"{prefix}({parts})"
